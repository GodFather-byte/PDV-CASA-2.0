"""Cópia dos XMLs da NFC-e (emissão própria, produção) na nuvem: a loja é obrigada a guardar por 5 anos e o
contador pede os do mês.

O caixa manda, com o token da loja, cada arquivo comprimido (gzip) e em Base64: o nfeProc (nota + protocolo), o
retorno do cancelamento e o da inutilização. A nuvem guarda comprimido (uns 3 a 5 KB por nota) por loja e mês.
O dono baixa o ZIP do mês no painel; o fornecedor também, pela central (suporte). Reenviar o mesmo arquivo não
duplica: (loja, nome) é único.
"""
from __future__ import annotations

import base64
import binascii
import gzip
import io
import re
import zipfile
from datetime import datetime

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from fastapi.responses import Response
from sqlalchemy import Column, Integer, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db

LOTE_MAXIMO = 20
LIMITE_GZ_BYTES = 256 * 1024
LIMITE_XML_BYTES = 1024 * 1024
TIPOS = ("nfe", "cancelamento", "inutilizacao")
NOME_VALIDO = re.compile(r"^[A-Za-z0-9._-]{5,120}\.xml$")
MES_VALIDO = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
LIMITE_ZIP = 20_000                       # arquivos por download (uma loja grande faz uns 9 mil por mês)


class NfceXml(Base):
    __tablename__ = "nfce_xmls"
    __table_args__ = (UniqueConstraint("chave_loja", "nome", name="ux_nfce_xml"),)
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    nome = Column(String, nullable=False)
    tipo = Column(String, nullable=False)
    chave = Column(String, nullable=True)
    mes = Column(String, index=True, nullable=False)        # AAAA-MM da emissão (ou do evento)
    conteudo = Column(LargeBinary, nullable=False)           # XML em gzip
    tamanho = Column(Integer, nullable=False)                # bytes do XML sem compressão
    recebido_em = Column(String, nullable=False)


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conferir(arquivo: dict) -> tuple[str, str, str, str, bytes, int]:
    """Valida um arquivo do lote. Devolve (nome, tipo, chave, mês, gzip, tamanho). Levanta ValueError."""
    nome = str(arquivo.get("nome") or "")
    tipo = str(arquivo.get("tipo") or "")
    mes = str(arquivo.get("mes") or "")
    chave = re.sub(r"\D", "", str(arquivo.get("chave") or ""))[:44]
    if not NOME_VALIDO.match(nome) or tipo not in TIPOS or not MES_VALIDO.match(mes):
        raise ValueError("arquivo sem nome, tipo ou mês válidos")
    try:
        comprimido = base64.b64decode(str(arquivo.get("conteudo_gz_b64") or ""), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("conteúdo inválido") from None
    if not comprimido or len(comprimido) > LIMITE_GZ_BYTES:
        raise ValueError("arquivo vazio ou grande demais")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(comprimido)) as gz:
            xml = gz.read(LIMITE_XML_BYTES + 1)
    except (OSError, EOFError):
        raise ValueError("gzip inválido") from None
    if len(xml) > LIMITE_XML_BYTES:
        raise ValueError("XML grande demais")
    inicio = xml.lstrip()[:200]
    if not inicio.startswith(b"<") or b"<!DOCTYPE" in xml[:2000] or b"<!ENTITY" in xml[:2000]:
        raise ValueError("não é um XML fiscal")
    return nome, tipo, chave, mes, comprimido, len(xml)


def guardar_lote(db: Session, chave_loja: str, arquivos: list) -> tuple[list[str], list[str]]:
    """Grava o lote. Devolve (nomes guardados ou já existentes, nomes recusados)."""
    ok, recusados = [], []
    agora = _agora()
    for arquivo in arquivos:
        try:
            nome, tipo, chave, mes, comprimido, tamanho = conferir(arquivo if isinstance(arquivo, dict) else {})
        except ValueError:
            recusados.append(str((arquivo or {}).get("nome") or "")[:120] if isinstance(arquivo, dict) else "")
            continue
        if db.query(NfceXml.id).filter_by(chave_loja=chave_loja, nome=nome).first() is None:
            db.add(NfceXml(chave_loja=chave_loja, nome=nome, tipo=tipo, chave=chave or None, mes=mes,
                           conteudo=comprimido, tamanho=tamanho, recebido_em=agora))
            db.flush()
        ok.append(nome)
    db.commit()
    return ok, recusados


def meses(db: Session, chave_loja: str) -> list[dict]:
    linhas = (db.query(NfceXml.mes, NfceXml.tipo, func.count(NfceXml.id))
              .filter_by(chave_loja=chave_loja).group_by(NfceXml.mes, NfceXml.tipo).all())
    por_mes: dict = {}
    for mes, tipo, n in linhas:
        por_mes.setdefault(mes, {"mes": mes, "nfe": 0, "cancelamento": 0, "inutilizacao": 0})[tipo] = n
    return sorted(por_mes.values(), key=lambda m: m["mes"], reverse=True)


def zip_do_mes(db: Session, chave_loja: str, mes: str) -> bytes:
    if not MES_VALIDO.match(mes or ""):
        raise HTTPException(status_code=422, detail="Informe o mês no formato AAAA-MM.")
    arquivos = (db.query(NfceXml).filter_by(chave_loja=chave_loja, mes=mes).order_by(NfceXml.nome)
                .limit(LIMITE_ZIP).all())
    if not arquivos:
        raise HTTPException(status_code=404, detail="Nenhum XML de NFC-e neste mês.")
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for a in arquivos:
            pasta = {"nfe": "autorizadas", "cancelamento": "canceladas", "inutilizacao": "inutilizadas"}[a.tipo]
            z.writestr(f"{pasta}/{a.nome}", gzip.decompress(a.conteudo))
    return saida.getvalue()


def _resposta_zip(conteudo: bytes, chave_loja: str, mes: str) -> Response:
    nome = re.sub(r"[^A-Za-z0-9_-]", "_", chave_loja)
    return Response(conteudo, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="nfce-{nome}-{mes}.zip"', "Cache-Control": "no-store"})


def instalar(app: FastAPI, Loja, autenticar) -> APIRouter:
    """Rotas do caixa (token da loja) e do dono (sessão do painel)."""
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
            raise HTTPException(status_code=403, detail="Use o token da loja para enviar os XMLs.")
        return acesso.loja

    @router.post("/v1/nfce/xmls")
    def receber(dados: dict = Body(...), chave_loja: str = Depends(loja_do_caixa), db: Session = Depends(get_db)):
        arquivos = dados.get("arquivos")
        if not isinstance(arquivos, list) or not 0 < len(arquivos) <= LOTE_MAXIMO:
            raise HTTPException(status_code=422, detail=f"Envie de 1 a {LOTE_MAXIMO} arquivos por vez.")
        ok, recusados = guardar_lote(db, chave_loja, arquivos)
        return {"recebidos": ok, "recusados": recusados}

    @router.get("/v1/painel/nfce/meses")
    def meses_do_dono(sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        return {"meses": meses(db, sessao.chave_loja)}

    @router.get("/v1/painel/nfce/xmls")
    def zip_do_dono(mes: str, sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        return _resposta_zip(zip_do_mes(db, sessao.chave_loja, mes), sessao.chave_loja, mes)

    app.include_router(router)
    return router


def instalar_fornecedor(app: FastAPI, sessao, obter, auditar) -> APIRouter:
    """Central: o fornecedor vê os meses e baixa o ZIP de qualquer loja (fica na auditoria)."""
    router = APIRouter()

    @router.get("/v1/fornecedor/lojas/{chave}/nfce/meses")
    def meses_da_loja(chave: str, _=Depends(sessao), db: Session = Depends(get_db)):
        return {"meses": meses(db, obter(db, chave).chave_loja)}

    @router.get("/v1/fornecedor/lojas/{chave}/nfce/xmls")
    def zip_da_loja(chave: str, mes: str, _=Depends(sessao), db: Session = Depends(get_db)):
        loja = obter(db, chave).chave_loja
        conteudo = zip_do_mes(db, loja, mes)
        auditar(db, "baixar_xmls_nfce", loja, mes)
        db.commit()
        return _resposta_zip(conteudo, loja, mes)

    app.include_router(router)
    return router
