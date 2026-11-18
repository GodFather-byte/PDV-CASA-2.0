"""Insta-BDelivery (vitrine de delivery com IA) ligado às lojas pela central.

- Implantação: o fornecedor cola na central o endereço e a chave do Insta-BDelivery da loja; a nuvem entrega ao caixa
  na resposta do envio do painel (o caixa manda o hash do que já tem; só recebe se for diferente). Depois que o caixa
  confirma, a chave em texto sai daqui e fica só o hash.
- IA paga: o Insta-BDelivery pergunta `GET /v1/parceiro/insta/ia?h=<sha256 da chave>` se a IA da loja está liberada.
  O hash é o mesmo que o Insta guarda; a resposta é só sim ou não, conforme o liga/desliga da IA na central.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db

URL_VALIDA = re.compile(r"^https://[A-Za-z0-9.-]+(:\d{1,5})?(/[A-Za-z0-9._~/-]*)?$")
HASH_VALIDO = re.compile(r"^[0-9a-f]{64}$")


class InstaLoja(Base):
    __tablename__ = "insta_lojas"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, unique=True, index=True, nullable=False)
    url = Column(String, nullable=False)
    token_hash = Column(String, index=True, nullable=False)       # sha256 da chave (o que o Insta guarda)
    config_hash = Column(String, nullable=False)                   # sha256 de "url|chave" (o que o caixa manda)
    token_pendente = Column(String)                                # chave em texto até o caixa confirmar
    atualizado_em = Column(String, nullable=False)
    entregue_em = Column(String)


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def hash_config(url: str, token: str) -> str:
    """O mesmo cálculo do caixa (src/sync/insta_bdelivery.hash_config)."""
    return sha256(f"{url.strip().rstrip('/')}|{token.strip()}")


def para_resposta(db: Session, chave_loja: str, dados: dict) -> dict:
    """Chaves da resposta do envio do painel: entrega a configuração ou registra que o caixa já a tem."""
    linha = db.query(InstaLoja).filter_by(chave_loja=chave_loja).first()
    if linha is None:
        return {}
    do_caixa = str(dados.get("insta_hash") or "")
    if do_caixa == linha.config_hash:
        if linha.token_pendente or not linha.entregue_em:
            linha.token_pendente, linha.entregue_em = None, _agora()
            db.commit()
        return {}
    if not linha.token_pendente or "insta_hash" not in dados:
        return {}                     # caixa antigo (não manda o hash) ou chave já esquecida: nada a entregar
    return {"insta": {"url": linha.url, "token": linha.token_pendente}}


def instalar(app: FastAPI) -> APIRouter:
    Base.metadata.create_all(bind=engine)
    router = APIRouter()

    @router.get("/v1/parceiro/insta/ia")
    def ia_liberada(h: str = "", db: Session = Depends(get_db)):
        if not HASH_VALIDO.match(h or ""):
            raise HTTPException(status_code=422, detail="Hash inválido.")
        linha = db.query(InstaLoja).filter_by(token_hash=h).first()
        if linha is None:
            return {"liberada": False}
        from backend.ia import _registro
        liberada = bool(_registro(db, linha.chave_loja).ativa)
        db.commit()
        return {"liberada": liberada}

    app.include_router(router)
    return router


def instalar_fornecedor(app: FastAPI, sessao, obter, auditar) -> APIRouter:
    router = APIRouter()

    def situacao(linha: InstaLoja | None) -> dict:
        if linha is None:
            return {"configurado": False}
        return {"configurado": True, "url": linha.url, "atualizado_em": linha.atualizado_em,
                "entregue_em": linha.entregue_em, "aguardando_caixa": bool(linha.token_pendente)}

    @router.get("/v1/fornecedor/lojas/{chave}/insta")
    def ver(chave: str, _=Depends(sessao), db: Session = Depends(get_db)):
        loja = obter(db, chave).chave_loja
        return situacao(db.query(InstaLoja).filter_by(chave_loja=loja).first())

    @router.post("/v1/fornecedor/lojas/{chave}/insta")
    def gravar(chave: str, dados: dict = Body(...), _=Depends(sessao), db: Session = Depends(get_db)):
        loja = obter(db, chave).chave_loja
        linha = db.query(InstaLoja).filter_by(chave_loja=loja).first()
        if dados.get("remover") is True:
            if linha is not None:
                db.delete(linha)
            auditar(db, "insta_loja", loja, "removido")
            db.commit()
            return situacao(None)
        url = str(dados.get("url") or "").strip().rstrip("/")
        token = str(dados.get("token") or "").strip()
        if not URL_VALIDA.match(url) or len(url) > 200:
            raise HTTPException(status_code=422, detail="Endereço inválido. Use https://… (ex.: https://site/api/pdv).")
        if not re.fullmatch(r"ibd_[0-9a-f]{64}", token):
            raise HTTPException(status_code=422, detail="Chave inválida: copie a chave inteira gerada no painel do "
                                                        "Insta-BDelivery (começa com ibd_).")
        if linha is None:
            linha = InstaLoja(chave_loja=loja)
            db.add(linha)
        linha.url, linha.token_hash, linha.config_hash = url, sha256(token), hash_config(url, token)
        linha.token_pendente, linha.atualizado_em, linha.entregue_em = token, _agora(), None
        auditar(db, "insta_loja", loja, url)
        db.commit()
        return situacao(linha)

    app.include_router(router)
    return router
