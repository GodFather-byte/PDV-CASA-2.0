"""Teste grátis pelo site: o cliente preenche nome da loja, responsável e WhatsApp e recebe na hora o instalador, o
código de instalação (com a licença de teste) e a senha do painel do dono. Sem o fornecedor criar nada à mão.

A loja nasce na central com licença até hoje + DIAS_TESTE e aparece em "Em teste". Contra abuso: campo-isca para
robôs, no máximo 3 cadastros por IP por dia, um teste por WhatsApp e um teto diário (PDV_SITE_TESTES_DIA, padrão 30).
Desligar: PDV_SITE_TESTE=0. O IP e o WhatsApp ficam guardados só como hash (o WhatsApp também em claro, para o
fornecedor ligar: é o contato que o cliente deu para isso).
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import unicodedata
from datetime import date, datetime, timedelta

from fastapi import Body, FastAPI, HTTPException, Request
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Session

from backend import site_precos as precos
from backend.database import Base, SessionLocal, engine
from src.core.edicao import EDICOES

POR_IP_DIA = 3
EDICOES_SITE = ("willpdv", "willadega", "willrestaurante", "willvariedades", "willhotel")


class SiteTeste(Base):
    __tablename__ = "site_testes"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    nome_loja = Column(String, nullable=False)
    responsavel = Column(String, nullable=False)
    whatsapp = Column(String, nullable=False)
    whatsapp_hash = Column(String, index=True, nullable=False)
    edicao = Column(String, nullable=False)
    cidade = Column(String, nullable=True)
    ip_hash = Column(String, index=True, nullable=False)
    criado_em = Column(String, index=True, nullable=False)


def ligado() -> bool:
    return os.environ.get("PDV_SITE_TESTE", "1").strip() not in ("0", "nao", "não", "false")


def teto_diario() -> int:
    try:
        return max(0, int(os.environ.get("PDV_SITE_TESTES_DIA", "30")))
    except ValueError:
        return 30


def _hash(texto: str) -> str:
    sal = os.environ.get("PDV_SITE_SAL", "willpdv-site")
    return hashlib.sha256(f"{sal}|{texto}".encode()).hexdigest()


def _texto(dados: dict, campo: str, minimo: int, maximo: int, rotulo: str) -> str:
    valor = re.sub(r"\s+", " ", str(dados.get(campo) or "")).strip()
    if not minimo <= len(valor) <= maximo:
        raise HTTPException(status_code=422, detail=f"Preencha {rotulo} ({minimo} a {maximo} letras).")
    return valor


def whatsapp_normalizado(bruto: str) -> str:
    digitos = re.sub(r"\D", "", bruto or "")
    if len(digitos) in (10, 11):
        digitos = "55" + digitos
    if not re.fullmatch(r"55\d{10,11}", digitos):
        raise HTTPException(status_code=422, detail="Informe o WhatsApp com DDD (ex.: 11 91234-5678).")
    return digitos


def chave_para(nome: str) -> str:
    """'Adega do Zé' -> 'ADEGA-DO-ZE-7K3F' (o sufixo evita colisão e adivinhação)."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Z0-9]+", "-", sem_acento.upper()).strip("-")[:40] or "LOJA"
    return f"{base}-{secrets.token_hex(2).upper()}"


def endereco_nuvem(request: Request) -> str:
    base = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if base:
        return base
    base = str(request.base_url).rstrip("/")
    if base.startswith("http://") and request.url.hostname not in ("localhost", "127.0.0.1", "testserver"):
        base = "https://" + base[len("http://"):]
    return base


def criar_teste(db: Session, request: Request, dados: dict) -> dict:
    from backend import painel
    from backend.central_fornecedor import link_instalador, qr_svg
    from backend.lojas import criar, definir_assinatura
    from backend.main import Loja
    from src.core import codigo_instalacao

    if not ligado():
        raise HTTPException(status_code=403, detail="O teste pelo site está pausado. Chame no WhatsApp.")
    if str(dados.get("site") or "").strip():                       # campo-isca: gente não preenche
        raise HTTPException(status_code=422, detail="Cadastro recusado.")
    if dados.get("aceite") is not True:
        raise HTTPException(status_code=422, detail="Confirme que leu os termos do teste.")
    nome = _texto(dados, "nome_loja", 3, 80, "o nome da loja")
    responsavel = _texto(dados, "responsavel", 3, 80, "o seu nome")
    cidade = re.sub(r"\s+", " ", str(dados.get("cidade") or "")).strip()[:60] or None
    whatsapp = whatsapp_normalizado(str(dados.get("whatsapp") or ""))
    edicao = str(dados.get("edicao") or "willadega")
    if edicao not in EDICOES_SITE:
        raise HTTPException(
            status_code=422,
            detail="Escolha o programa: boate/bar, adega, restaurante, variedades ou hotel.")

    hoje = date.today().isoformat()
    ip_hash = _hash(request.client.host if request.client else "?")
    zap_hash = _hash(whatsapp)
    if db.query(SiteTeste).filter(SiteTeste.whatsapp_hash == zap_hash).first():
        raise HTTPException(status_code=409, detail="Este WhatsApp já fez um teste. Chame no WhatsApp para continuar.")
    if db.query(SiteTeste).filter(SiteTeste.ip_hash == ip_hash, SiteTeste.criado_em >= hoje).count() >= POR_IP_DIA:
        raise HTTPException(status_code=429, detail="Muitos cadastros daqui hoje. Chame no WhatsApp.")
    if db.query(SiteTeste).filter(SiteTeste.criado_em >= hoje).count() >= teto_diario():
        raise HTTPException(status_code=429, detail="Os testes de hoje acabaram. Chame no WhatsApp que liberamos.")

    chave = chave_para(nome)
    while db.query(Loja).filter(Loja.chave_loja == chave).first() is not None:
        chave = chave_para(nome)
    token = criar(db, chave, nome)
    db.query(Loja).filter_by(chave_loja=chave).update({"edicao": edicao})
    validade = date.today() + timedelta(days=precos.DIAS_TESTE)
    definir_assinatura(db, chave, validade)
    senha = painel.gerar_senha()
    painel.definir_senha(db, chave, senha)
    db.add(SiteTeste(chave_loja=chave, nome_loja=nome, responsavel=responsavel, whatsapp=whatsapp,
                     whatsapp_hash=zap_hash, edicao=edicao, cidade=cidade, ip_hash=ip_hash,
                     criado_em=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    db.commit()
    base = endereco_nuvem(request)
    try:
        codigo = codigo_instalacao.gerar(base, chave, token)
    except ValueError:
        codigo = ""
    from backend.site import link_whatsapp
    return {"loja": chave, "programa": EDICOES[edicao].nome, "validade": validade.isoformat(),
            "dias": precos.DIAS_TESTE, "instalador": link_instalador(edicao), "codigo_instalacao": codigo,
            "qr_instalacao": qr_svg(codigo), "painel": f"{base}/painel/", "senha_painel": senha,
            "zap_ajuda": link_whatsapp(f"Olá! Criei o teste do {EDICOES[edicao].nome} pelo site: {nome} ({chave}). "
                                       "Pode me ajudar a instalar?")}


def contatos(db: Session) -> dict[str, dict]:
    """Para a central: responsável e WhatsApp de quem se cadastrou pelo site, por loja."""
    return {t.chave_loja: {"responsavel": t.responsavel, "whatsapp": t.whatsapp, "cidade": t.cidade,
                           "origem": "site", "criado_em": t.criado_em}
            for t in db.query(SiteTeste).all()}


def instalar(app: FastAPI) -> None:
    Base.metadata.create_all(bind=engine)

    @app.post("/v1/site/teste", include_in_schema=False)
    def teste(request: Request, dados: dict = Body(...)):
        with SessionLocal() as db:
            return criar_teste(db, request, dados)
