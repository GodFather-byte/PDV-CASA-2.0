"""Envio automático ao contador: todo dia 1º, a partir das 08:00 (Brasília), o contador da loja recebe por e-mail o
resumo do mês anterior e um link (válido por 7 dias) para baixar o ZIP com os XMLs das NFC-e e a planilha das notas.

Link em vez de anexo: uma loja grande passa de mil notas por mês e o anexo estouraria o limite do e-mail. O link é um
token aleatório (só o hash fica no banco), vale só para aquela loja e aquele mês e vence em 7 dias.

O dono põe o e-mail do contador no painel (aba Relatórios) e pode mandar um mês fechado na hora ("Enviar agora").
O disparo segue o do relatório diário: qualquer requisição chama `disparar_em_segundo_plano()`, que só olha a memória.
"""
from __future__ import annotations

import csv
import gzip
import io
import logging
import re
import secrets
import threading
import time
import zipfile
from datetime import date, timedelta

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from fastapi.responses import Response
from sqlalchemy import Boolean, Column, Integer, String, update
from sqlalchemy.orm import Session

from backend.database import Base, get_db

log = logging.getLogger("pdv.contador")

HORA_ENVIO = 8
DIAS_LINK = 7
ESPERA_NOVA_TENTATIVA_SEG = 30 * 60
MES_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")


class ContadorEnvio(Base):
    __tablename__ = "contador_envios"
    chave_loja = Column(String, primary_key=True)
    email = Column(String(254), nullable=False, default="")
    ativo = Column(Boolean, nullable=False, default=False)
    ultimo_mes = Column(String(7), nullable=True)            # mês do último envio automático (ou reservado)
    ultimo_status = Column(String(200), nullable=False, default="")
    atualizado_em = Column(String(19), nullable=False, default="")


class ContadorLink(Base):
    __tablename__ = "contador_links"
    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    chave_loja = Column(String, index=True, nullable=False)
    mes = Column(String(7), nullable=False)
    expira_em = Column(String(19), nullable=False)
    criado_em = Column(String(19), nullable=False)


def _agora_txt() -> str:
    from backend.relatorio_diario import agora_brasilia
    return agora_brasilia().strftime("%Y-%m-%d %H:%M:%S")


def mes_do_envio(agora=None) -> str | None:
    """O mês que deve sair agora: o anterior, no dia 1º a partir das 08:00 (e nos dias seguintes, se ainda não saiu)."""
    from backend.relatorio_diario import agora_brasilia
    agora = agora or agora_brasilia()
    if agora.day == 1 and agora.hour < HORA_ENVIO:
        return None
    anterior = date(agora.year, agora.month, 1) - timedelta(days=1)
    return f"{anterior.year:04d}-{anterior.month:02d}"


def nome_do_mes(mes: str) -> str:
    ano, m = mes.split("-")
    return f"{MESES[int(m) - 1]} de {ano}"


def config(db: Session, chave_loja: str) -> dict:
    linha = db.get(ContadorEnvio, chave_loja)
    return {"email": linha.email if linha else "", "ativo": bool(linha.ativo) if linha else False,
            "ultimo_mes": linha.ultimo_mes if linha else None, "ultimo_status": linha.ultimo_status if linha else "",
            "mes_anterior": mes_do_envio() or _mes_anterior_hoje()}


def _mes_anterior_hoje() -> str:
    from backend.relatorio_diario import agora_brasilia
    hoje = agora_brasilia().date()
    anterior = date(hoje.year, hoje.month, 1) - timedelta(days=1)
    return f"{anterior.year:04d}-{anterior.month:02d}"


def salvar(db: Session, chave_loja: str, email: str, ativo: bool) -> dict:
    from backend.painel_usuarios import ErroUsuario, normalizar_email
    email = (email or "").strip()
    if email:
        try:
            email = normalizar_email(email)
        except ErroUsuario:
            raise ValueError("E-mail do contador inválido.") from None
    if ativo and not email:
        raise ValueError("Informe o e-mail do contador para ligar o envio.")
    linha = db.get(ContadorEnvio, chave_loja)
    if linha is None:
        linha = ContadorEnvio(chave_loja=chave_loja, ultimo_mes=mes_do_envio())   # o mês que já passou não sai sozinho
        db.add(linha)
    linha.email, linha.ativo, linha.atualizado_em = email, bool(ativo), _agora_txt()
    db.commit()
    return config(db, chave_loja)


# ---------------------------------------------------------------- conteúdo
def _valor_e_data(xml: bytes) -> tuple[str, str, str]:
    """Número, data de emissão e valor total do nfeProc (texto simples, sem montar a árvore inteira)."""
    texto = xml.decode("utf-8", "replace")
    numero = re.search(r"<nNF>(\d+)</nNF>", texto)
    data = re.search(r"<dhEmi>([^<]{10,})</dhEmi>", texto)
    valor = re.search(r"<vNF>([\d.]+)</vNF>", texto)
    return (numero.group(1) if numero else "", (data.group(1)[:19].replace("T", " ") if data else ""),
            (valor.group(1).replace(".", ",") if valor else ""))


def pacote(db: Session, chave_loja: str, mes: str) -> bytes:
    """ZIP para o contador: XMLs (autorizadas, canceladas, inutilizadas) e notas.csv com uma linha por arquivo."""
    from backend.nfce_xmls import LIMITE_ZIP, NfceXml
    arquivos = (db.query(NfceXml).filter_by(chave_loja=chave_loja, mes=mes).order_by(NfceXml.nome)
                .limit(LIMITE_ZIP).all())
    saida = io.BytesIO()
    planilha = io.StringIO()
    escritor = csv.writer(planilha, delimiter=";")
    escritor.writerow(["situacao", "numero", "emissao", "valor", "chave", "arquivo"])
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for a in arquivos:
            xml = gzip.decompress(a.conteudo)
            pasta = {"nfe": "autorizadas", "cancelamento": "canceladas", "inutilizacao": "inutilizadas"}[a.tipo]
            z.writestr(f"{pasta}/{a.nome}", xml)
            numero, emissao, valor = _valor_e_data(xml) if a.tipo == "nfe" else ("", "", "")
            escritor.writerow([pasta[:-1], numero, emissao, valor, a.chave or "", a.nome])
        z.writestr("notas.csv", "﻿" + planilha.getvalue())      # BOM: o Excel abre com acentos
    return saida.getvalue()


def _contagem(db: Session, chave_loja: str, mes: str) -> dict:
    from backend.nfce_xmls import meses
    for m in meses(db, chave_loja):
        if m["mes"] == mes:
            return m
    return {"mes": mes, "nfe": 0, "cancelamento": 0, "inutilizacao": 0}


def criar_link(db: Session, chave_loja: str, mes: str) -> str:
    from backend.painel import _hash
    from backend.relatorio_diario import agora_brasilia
    token = secrets.token_urlsafe(32)
    db.add(ContadorLink(token_hash=_hash(token), chave_loja=chave_loja, mes=mes, criado_em=_agora_txt(),
                        expira_em=(agora_brasilia() + timedelta(days=DIAS_LINK)).strftime("%Y-%m-%d %H:%M:%S")))
    db.query(ContadorLink).filter(ContadorLink.expira_em <= _agora_txt()).delete(synchronize_session=False)
    db.commit()
    return token


def montar(db: Session, chave_loja: str, mes: str, token: str) -> tuple[str, str]:
    from backend import painel
    from backend.main import Loja
    from backend.painel_usuarios import endereco_publico
    from backend.relatorio_diario import _dinheiro
    loja = db.query(Loja).filter(Loja.chave_loja == chave_loja).first()
    nome = (loja.nome if loja is not None else "") or chave_loja
    ano, m = (int(x) for x in mes.split("-"))
    inicio = date(ano, m, 1)
    fim = (date(ano + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    periodo = painel.relatorio_periodo(db, chave_loja, inicio, fim)
    notas = _contagem(db, chave_loja, mes)
    linhas = [
        f"FECHAMENTO DE {nome_do_mes(mes).upper()} — {nome}",
        "",
        "Arquivos para a contabilidade (link válido por 7 dias):",
        f"{endereco_publico()}/v1/contador/{token}",
        "",
        "O arquivo ZIP tem os XMLs das NFC-e separados em autorizadas, canceladas e inutilizadas, e a planilha",
        "notas.csv (abre no Excel) com número, data, valor e chave de cada nota.",
        "",
        "NOTAS FISCAIS (NFC-e) NA NUVEM",
        f"- Autorizadas: {notas['nfe']}",
        f"- Canceladas: {notas['cancelamento']}",
        f"- Inutilizações: {notas['inutilizacao']}",
    ]
    if not notas["nfe"]:
        linhas.append("  Nenhuma NFC-e deste mês chegou à nuvem. Se a loja emite nota, confira com ela antes de fechar.")
    linhas += ["", "VENDAS DO MÊS (todas, com e sem nota)",
               f"- Faturamento: {_dinheiro(periodo['faturamento_cent'])} em {periodo['quantidade']} venda(s)"]
    for f in periodo.get("formas") or []:
        linhas.append(f"- {f.get('tipo') or f.get('forma')}: {_dinheiro(int(f.get('valor_cent') or 0))}")
    if periodo.get("parcial"):
        linhas.append("  Atenção: parte das vendas antigas já saiu da nuvem; os totais podem estar incompletos.")
    linhas += ["", "Este e-mail é automático e sai todo dia 1º. Dúvidas sobre as vendas: fale com a loja.",
               "WillPDV · WB Sistemas"]
    return f"{nome}: fechamento de {nome_do_mes(mes)} (XMLs das NFC-e)"[:150], "\n".join(linhas)


def enviar_mes(db: Session, chave_loja: str, mes: str, email: str, enviar=None) -> str:
    from backend.cobranca_mercadopago import enviar_email
    from backend.relatorio_diario import agora_brasilia
    token = criar_link(db, chave_loja, mes)
    assunto, corpo = montar(db, chave_loja, mes, token)
    (enviar or enviar_email)(email, assunto, corpo)
    return f"{nome_do_mes(mes)} enviado em {agora_brasilia().strftime('%d/%m %H:%M')} para {email}."


# ---------------------------------------------------------------- envio automático
def enviar_pendentes(db: Session, mes: str | None = None, enviar=None) -> dict:
    mes = mes or mes_do_envio()
    if mes is None:
        return {"enviados": 0, "falhas": 0}
    enviados = falhas = 0
    for linha in db.query(ContadorEnvio).filter(ContadorEnvio.ativo.is_(True)).all():
        if linha.ultimo_mes == mes or not linha.email:
            continue
        anterior = linha.ultimo_mes
        reservado = db.execute(update(ContadorEnvio)
                               .where(ContadorEnvio.chave_loja == linha.chave_loja,
                                      ContadorEnvio.ultimo_mes.is_(None) if anterior is None
                                      else ContadorEnvio.ultimo_mes == anterior)
                               .values(ultimo_mes=mes)).rowcount
        db.commit()
        if reservado != 1:
            continue
        try:
            status = enviar_mes(db, linha.chave_loja, mes, linha.email, enviar)
            enviados += 1
        except Exception as erro:                              # noqa: BLE001 - uma loja não para as outras
            log.error("Envio ao contador de %s falhou: %s", linha.chave_loja, type(erro).__name__)
            db.rollback()
            db.execute(update(ContadorEnvio).where(ContadorEnvio.chave_loja == linha.chave_loja)
                       .values(ultimo_mes=anterior))
            status = f"Falhou: {str(erro)[:150]}"
            falhas += 1
        db.execute(update(ContadorEnvio).where(ContadorEnvio.chave_loja == linha.chave_loja)
                   .values(ultimo_status=status[:200]))
        db.commit()
    return {"enviados": enviados, "falhas": falhas}


_trava = threading.Lock()
_feito: str | None = None
_proxima_tentativa = 0.0


def disparar_em_segundo_plano(agora=None) -> bool:
    global _proxima_tentativa
    mes = mes_do_envio(agora)
    if mes is None or _feito == mes or time.monotonic() < _proxima_tentativa or not _trava.acquire(blocking=False):
        return False

    def rodar():
        global _feito, _proxima_tentativa
        try:
            from backend.main import SessionLocal
            with SessionLocal() as db:
                resultado = enviar_pendentes(db, mes)
            if resultado["falhas"]:
                _proxima_tentativa = time.monotonic() + ESPERA_NOVA_TENTATIVA_SEG
            else:
                _feito = mes
        except Exception:                                      # noqa: BLE001
            log.error("Envio ao contador falhou (erro interno).")
            _proxima_tentativa = time.monotonic() + ESPERA_NOVA_TENTATIVA_SEG
        finally:
            _trava.release()

    threading.Thread(target=rodar, name="envio-contador", daemon=True).start()
    return True


_envios_manuais: dict[str, list[float]] = {}
_trava_manual = threading.Lock()


def pode_enviar_agora(chave_loja: str, limite: int = 3, janela_seg: int = 3600) -> bool:
    agora = time.monotonic()
    with _trava_manual:
        vez = [t for t in _envios_manuais.get(chave_loja, []) if agora - t < janela_seg]
        permitido = len(vez) < limite
        if permitido:
            vez.append(agora)
        _envios_manuais[chave_loja] = vez
        return permitido


# ---------------------------------------------------------------- rotas
def instalar(app: FastAPI, Loja) -> APIRouter:
    from backend.painel import PainelSessao, sessao_do_dono
    router = APIRouter()

    def sessao_ativa(sessao: PainelSessao = Depends(sessao_do_dono), db: Session = Depends(get_db)):
        loja = db.query(Loja).filter(Loja.chave_loja == sessao.chave_loja).first()
        if sessao.grupo_id or loja is None or not loja.ativa:
            raise HTTPException(status_code=401, detail="Abra uma loja para configurar o contador.")
        return sessao

    @router.get("/v1/painel/contador")
    def ver(sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        return config(db, sessao.chave_loja)

    @router.post("/v1/painel/contador")
    def gravar(dados: dict = Body(...), sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        try:
            return salvar(db, sessao.chave_loja, str((dados or {}).get("email") or "")[:254], bool((dados or {}).get("ativo")))
        except ValueError as erro:
            raise HTTPException(status_code=422, detail=str(erro)) from None

    @router.post("/v1/painel/contador/enviar")
    def enviar_agora(dados: dict = Body(...), sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        mes = str((dados or {}).get("mes") or "")
        if not MES_RE.fullmatch(mes):
            raise HTTPException(status_code=422, detail="Escolha o mês.")
        conf = config(db, sessao.chave_loja)
        if not conf["email"]:
            raise HTTPException(status_code=422, detail="Salve o e-mail do contador antes.")
        if not pode_enviar_agora(sessao.chave_loja):
            raise HTTPException(status_code=429, detail="Já foram 3 envios nesta hora. Tente mais tarde.")
        try:
            return {"mensagem": enviar_mes(db, sessao.chave_loja, mes, conf["email"])}
        except Exception as erro:                               # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"E-mail não enviado: {str(erro)[:160]}") from None

    @router.get("/v1/contador/{token}")
    def baixar(token: str, db: Session = Depends(get_db)):
        from backend.painel import _hash
        if not token or len(token) > 100:
            raise HTTPException(status_code=404, detail="Link inválido.")
        link = db.query(ContadorLink).filter_by(token_hash=_hash(token)).first()
        if link is None or link.expira_em <= _agora_txt():
            raise HTTPException(status_code=410, detail="Este link venceu. Peça à loja para enviar de novo.")
        nome = re.sub(r"[^A-Za-z0-9_-]", "_", link.chave_loja)
        return Response(pacote(db, link.chave_loja, link.mes), media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="contabilidade-{nome}-{link.mes}.zip"',
            "Cache-Control": "no-store"})

    app.include_router(router)
    return router
