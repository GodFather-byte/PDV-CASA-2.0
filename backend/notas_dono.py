"""Notas de compra enviadas pelo dono: o painel sobe o XML da NF-e e o caixa da loja busca.

A nuvem só guarda e entrega. Ela não dá entrada em estoque, não consulta a SEFAZ e não confere a assinatura da
nota: quem confere os itens e confirma a entrada é o operador, na tela de importação de NF-e do PDV.

Situações: pendente (esperando o caixa buscar) -> baixada (está no caixa, esperando conferência)
-> lancada (entrou no estoque) ou recusada (o caixa recusou, com o motivo). O XML sai da nuvem quando a nota
chega a uma situação final.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from sqlalchemy import Column, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db

LIMITE_XML_BYTES = 2 * 1024 * 1024          # uma NF-e de compra tem dezenas ou centenas de KiB
LIMITE_PENDENTES = 40                       # notas esperando o caixa, por loja
LOTE_ENTREGA = 5                            # notas por busca do caixa (a resposta não cresce sem limite)
DIAS_HISTORICO = 90                         # depois disso a linha (já sem XML) some da lista
SITUACOES_FINAIS = ("lancada", "recusada")


class PainelNota(Base):
    __tablename__ = "painel_notas"
    __table_args__ = (UniqueConstraint("chave_loja", "chave_nfe", name="ux_painel_nota"),)
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    chave_nfe = Column(String, nullable=False)          # 44 dígitos; XML sem Id usa o SHA-256 do arquivo
    numero = Column(String, nullable=False, default="")
    serie = Column(String, nullable=False, default="")
    emitente = Column(String, nullable=False, default="")
    cnpj = Column(String, nullable=False, default="")
    data_emissao = Column(String, nullable=False, default="")
    itens = Column(Integer, nullable=False, default=0)
    valor_cent = Column(Integer, nullable=False, default=0)
    arquivo = Column(String, nullable=False, default="nota.xml")
    xml = Column(Text, nullable=True)                   # base64 dos bytes originais; None depois da situação final
    situacao = Column(String, nullable=False, default="pendente")
    detalhe = Column(String, nullable=False, default="")
    enviada_em = Column(String, nullable=False)
    situacao_em = Column(String, nullable=False)


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _nome_local(elemento) -> str:
    return elemento.tag.rsplit("}", 1)[-1]


def _filho(elemento, nome: str):
    if elemento is None:
        return None
    return next((e for e in elemento if _nome_local(e) == nome), None)


def _texto(elemento, nome: str) -> str:
    filho = _filho(elemento, nome)
    return (filho.text or "").strip() if filho is not None else ""


def ler_cabecalho(dados: bytes) -> dict:
    """Confere que é uma NF-e modelo 55 e devolve o cabeçalho para a lista do painel. Lança ValueError com o motivo."""
    if not dados:
        raise ValueError("O arquivo está vazio.")
    if len(dados) > LIMITE_XML_BYTES:
        raise ValueError("O XML da nota passa de 2 MiB.")
    maiusculo = dados.upper().replace(b"\x00", b"")
    # O ElementTree não busca entidade externa; DTD e entidade são recusados mesmo assim.
    if b"<!DOCTYPE" in maiusculo or b"<!ENTITY" in maiusculo or b"<!ELEMENT" in maiusculo:
        raise ValueError("O XML da nota não pode declarar entidades ou DTD.")
    try:
        raiz = ET.fromstring(dados)
    except ET.ParseError:
        raise ValueError("O arquivo não é um XML válido. Envie o XML da NF-e, não o PDF nem a foto do DANFE.") from None
    info = next((e for e in raiz.iter() if _nome_local(e) == "infNFe"), None)
    if info is None:
        raise ValueError("O XML não contém uma NF-e. Envie o arquivo que o fornecedor mandou por e-mail.")
    ide = _filho(info, "ide")
    if _texto(ide, "mod") != "55":
        raise ValueError("O caixa aceita somente NF-e modelo 55 (nota de compra do fornecedor).")
    emit = _filho(info, "emit")
    cnpj = re.sub(r"\D", "", _texto(emit, "CNPJ") or _texto(emit, "CPF"))
    chave = re.sub(r"\D", "", (info.get("Id") or "").removeprefix("NFe"))
    if len(chave) != 44:
        chave = hashlib.sha256(dados).hexdigest()
    total = _filho(_filho(info, "total"), "ICMSTot")
    try:
        valor_cent = int((Decimal(_texto(total, "vNF") or "0") * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        valor_cent = 0
    return {
        "chave_nfe": chave, "numero": _texto(ide, "nNF")[:20], "serie": _texto(ide, "serie")[:10],
        "emitente": (_texto(emit, "xNome") or f"Fornecedor {cnpj}".strip())[:120], "cnpj": cnpj[:14],
        "data_emissao": (_texto(ide, "dhEmi") or _texto(ide, "dEmi"))[:10],
        "itens": sum(1 for e in info.iter() if _nome_local(e) == "det"), "valor_cent": max(valor_cent, 0)}


def publica(nota: PainelNota) -> dict:
    """O que a lista do painel mostra (sem o XML)."""
    return {"id": nota.id, "numero": nota.numero, "serie": nota.serie, "emitente": nota.emitente, "cnpj": nota.cnpj,
            "data_emissao": nota.data_emissao, "itens": nota.itens, "valor_cent": nota.valor_cent,
            "arquivo": nota.arquivo, "situacao": nota.situacao, "detalhe": nota.detalhe,
            "enviada_em": nota.enviada_em, "situacao_em": nota.situacao_em}


def pendentes(db: Session, chave_loja: str) -> int:
    """Quantas notas esperam o caixa buscar. O envio do painel devolve este número: o caixa só busca se houver."""
    return db.query(PainelNota.id).filter_by(chave_loja=chave_loja, situacao="pendente").count()


def guardar(db: Session, chave_loja: str, nome: str, dados: bytes) -> PainelNota:
    try:
        cabecalho = ler_cabecalho(dados)
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from None
    existente = db.query(PainelNota).filter_by(chave_loja=chave_loja, chave_nfe=cabecalho["chave_nfe"]).first()
    if existente is not None:
        if existente.situacao != "recusada":
            raise HTTPException(status_code=409, detail=f"A nota {existente.numero} deste fornecedor já foi enviada.")
        db.delete(existente)                # recusada pode ser reenviada (o caixa recusou por engano, por exemplo)
        db.flush()
    if pendentes(db, chave_loja) >= LIMITE_PENDENTES:
        raise HTTPException(status_code=409, detail="Há notas demais esperando o caixa. Aguarde a loja buscar as que já estão na fila.")
    agora = _agora()
    arquivo = re.sub(r"[^\w.\- ]", "_", (nome or "nota.xml").strip())[-80:] or "nota.xml"
    nota = PainelNota(chave_loja=chave_loja, arquivo=arquivo, xml=base64.b64encode(dados).decode("ascii"),
                      situacao="pendente", detalhe="", enviada_em=agora, situacao_em=agora, **cabecalho)
    db.add(nota)
    db.commit()
    return nota


def limpar_antigas(db: Session, chave_loja: str) -> None:
    corte = (datetime.now() - timedelta(days=DIAS_HISTORICO)).strftime("%Y-%m-%d %H:%M:%S")
    db.query(PainelNota).filter(PainelNota.chave_loja == chave_loja, PainelNota.situacao.in_(SITUACOES_FINAIS),
                                PainelNota.situacao_em < corte).delete(synchronize_session=False)


def instalar(app: FastAPI, Loja, autenticar) -> APIRouter:
    """Registra as rotas. `autenticar` é a dependência do backend.main (token da loja) e `Loja` o modelo das lojas."""
    from backend.painel import PainelSessao, sessao_do_dono
    Base.metadata.create_all(bind=engine)
    router = APIRouter()

    def sessao_ativa(sessao: PainelSessao = Depends(sessao_do_dono), db: Session = Depends(get_db)):
        loja = db.query(Loja).filter(Loja.chave_loja == sessao.chave_loja).first()
        if loja is None or not loja.ativa:
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        return sessao

    def loja_do_caixa(acesso=Depends(autenticar)) -> str:
        if acesso.admin:
            raise HTTPException(status_code=403, detail="Use o token da loja para buscar as notas.")
        return acesso.loja

    # ---- painel do dono (sessão do dono)
    @router.get("/v1/painel/notas")
    def listar(sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        limpar_antigas(db, sessao.chave_loja)
        db.commit()
        notas = (db.query(PainelNota).filter_by(chave_loja=sessao.chave_loja)
                 .order_by(PainelNota.enviada_em.desc(), PainelNota.id.desc()).limit(100).all())
        return {"notas": [publica(n) for n in notas], "limite_bytes": LIMITE_XML_BYTES}

    @router.post("/v1/painel/notas")
    def enviar(dados: dict = Body(...), sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        conteudo = dados.get("conteudo_b64")
        if not isinstance(conteudo, str) or not conteudo:
            raise HTTPException(status_code=422, detail="Escolha o arquivo XML da nota.")
        if len(conteudo) > LIMITE_XML_BYTES * 4 // 3 + 8:
            raise HTTPException(status_code=413, detail="O XML da nota passa de 2 MiB.")
        try:
            bruto = base64.b64decode(conteudo, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="Não consegui ler o arquivo enviado.") from None
        return {"nota": publica(guardar(db, sessao.chave_loja, str(dados.get("nome") or ""), bruto))}

    @router.delete("/v1/painel/notas/{nota_id}")
    def excluir(nota_id: int, sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        nota = db.query(PainelNota).filter_by(id=nota_id, chave_loja=sessao.chave_loja).first()
        if nota is None:
            raise HTTPException(status_code=404, detail="Nota não encontrada.")
        if nota.situacao == "baixada":
            raise HTTPException(status_code=409, detail="A nota já chegou ao caixa. Peça para recusarem lá, se foi engano.")
        if nota.situacao == "lancada":
            raise HTTPException(status_code=409, detail="A nota já entrou no estoque e fica no histórico.")
        db.delete(nota)
        db.commit()
        return {"excluida": True}

    # ---- caixa da loja (token da loja)
    @router.get("/v1/notas-dono")
    def buscar(chave_loja: str = Depends(loja_do_caixa), db: Session = Depends(get_db)):
        """As notas pendentes, mais antigas primeiro. Continuam pendentes até o caixa confirmar que guardou."""
        notas = (db.query(PainelNota).filter_by(chave_loja=chave_loja, situacao="pendente")
                 .order_by(PainelNota.id).limit(LOTE_ENTREGA).all())
        return {"notas": [{"id": n.id, "chave": n.chave_nfe, "numero": n.numero, "emitente": n.emitente,
                           "arquivo": n.arquivo, "enviada_em": n.enviada_em, "conteudo_b64": n.xml or ""}
                          for n in notas if n.xml],
                "restantes": max(pendentes(db, chave_loja) - len(notas), 0)}

    @router.post("/v1/notas-dono/confirmar")
    def confirmar(dados: dict = Body(...), chave_loja: str = Depends(loja_do_caixa), db: Session = Depends(get_db)):
        """`recebidas`: ids que o caixa guardou. `situacoes`: [{id, situacao, detalhe}] com o desfecho da conferência."""
        recebidas = dados.get("recebidas") or []
        situacoes = dados.get("situacoes") or []
        if not isinstance(recebidas, list) or not isinstance(situacoes, list) or len(recebidas) + len(situacoes) > 200:
            raise HTTPException(status_code=422, detail="Confirmação inválida.")
        agora = _agora()
        confirmadas = []
        for ident in recebidas:
            if type(ident) is not int:
                continue
            nota = db.query(PainelNota).filter_by(id=ident, chave_loja=chave_loja).first()
            if nota is not None and nota.situacao == "pendente":
                nota.situacao, nota.situacao_em = "baixada", agora
            if nota is not None:
                confirmadas.append(ident)
        for item in situacoes:
            if not isinstance(item, dict) or type(item.get("id")) is not int or item.get("situacao") not in SITUACOES_FINAIS:
                continue
            nota = db.query(PainelNota).filter_by(id=item["id"], chave_loja=chave_loja).first()
            if nota is None:
                confirmadas.append(item["id"])       # excluída na nuvem: o caixa pode parar de avisar
                continue
            if nota.situacao != "lancada":           # entrada no estoque não volta atrás por um aviso atrasado
                nota.situacao, nota.situacao_em = item["situacao"], agora
                nota.detalhe = str(item.get("detalhe") or "")[:200]
            nota.xml = None
            confirmadas.append(item["id"])
        db.commit()
        return {"confirmadas": list(dict.fromkeys(confirmadas))}

    app.include_router(router)
    return router
