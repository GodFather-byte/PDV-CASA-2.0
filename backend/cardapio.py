"""Cardápio digital, só consulta. O caixa publica o catálogo (POST /v1/cardapio/envio, token da loja)
e o celular abre /cardapio/?loja=CHAVE&mesa=N sem senha. Não há pedido, custo nem estoque.

A nuvem guarda o catálogo da loja e troca pelo próximo envio. O preço de promoção e de happy hour
é calculado na consulta, no horário de Brasília.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, String, Text
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db
from src.cardapio.preco import agora_local, preco_para_cardapio

PASTA_WEB = Path(__file__).resolve().parent / "cardapio_web"
MAX_PRODUTOS = 2000
CHAVE_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
DATA_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
HORA_RE = re.compile(r"\d{2}:\d{2}")
_FOTO_MAX = 300
_LOGO_MAX = 60000


class CardapioLoja(Base):
    """Um catálogo por loja. Reenviar substitui. Não guarda histórico nem custo."""
    __tablename__ = "cardapio_lojas"
    chave_loja = Column(String, primary_key=True)
    nome = Column(String, nullable=False, default="")
    logo = Column(Text, nullable=False, default="")
    produtos = Column(Text, nullable=False, default="[]")
    atualizado_em = Column(String, nullable=False)


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _txt(valor, limite: int) -> str:
    return str(valor or "")[:limite]


def _int(valor, padrao: int = 0) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def _data(valor) -> str:
    texto = str(valor or "")[:10]
    return texto if DATA_RE.fullmatch(texto) else ""


def _hora(valor) -> str:
    texto = str(valor or "")[:5]
    return texto if HORA_RE.fullmatch(texto) else ""


def _dia(valor) -> int | None:
    n = _int(valor, -1)
    return n if 1 <= n <= 7 else None


def _url(valor) -> str:
    texto = str(valor or "").strip()
    if len(texto) > _FOTO_MAX or not texto.lower().startswith(("https://", "http://")):
        return ""
    return texto


def _logo(valor) -> str:
    texto = str(valor or "").strip()
    if not texto.startswith("data:image/") or len(texto) > _LOGO_MAX:
        return ""
    return texto


def produto_limpo(item: dict) -> dict | None:
    """Só os campos do cardápio. Custo, estoque e o que mais vier no JSON são ignorados."""
    if not isinstance(item, dict):
        return None
    nome = _txt(item.get("nome"), 80).strip()
    preco = _int(item.get("preco_cent"), -1)
    if not nome or preco < 0 or preco > 10_000_000:
        return None
    limpo = {
        "nome": nome,
        "grupo": _txt(item.get("grupo"), 40).strip() or "Outros",
        "subgrupo": _txt(item.get("subgrupo"), 40).strip() or "Geral",
        "preco_cent": preco,
        "promo_de": _data(item.get("promo_de")), "promo_ate": _data(item.get("promo_ate")),
        "promo_preco_cent": max(_int(item.get("promo_preco_cent")), 0),
        "sem_inicial": _dia(item.get("sem_inicial")), "sem_final": _dia(item.get("sem_final")),
        "sem_preco_cent": max(_int(item.get("sem_preco_cent")), 0),
        "hora_ini": _hora(item.get("hora_ini")), "hora_fim": _hora(item.get("hora_fim")),
        "hora_preco_cent": max(_int(item.get("hora_preco_cent")), 0),
    }
    descricao = " ".join(_txt(item.get("descricao"), 240).split())
    if descricao:
        limpo["descricao"] = descricao
    foto = _url(item.get("foto"))
    if foto:
        limpo["foto"] = foto
    return limpo


def _ler_produtos(bruto: str) -> list[dict]:
    try:
        dados = json.loads(bruto or "[]")
    except ValueError:
        return []
    if not isinstance(dados, list):
        return []
    return [p for p in (produto_limpo(i) for i in dados) if p]


def agrupar(produtos: list[dict], quando: datetime | None = None) -> list[dict]:
    """Grupos e subgrupos na ordem em que o caixa mandou, com o preço daquele momento."""
    grupos: list[dict] = []
    indice: dict[tuple[str, str], dict] = {}
    for item in produtos:
        chave = (item["grupo"], item["subgrupo"])
        bloco = indice.get(chave)
        if bloco is None:
            grupo = next((g for g in grupos if g["nome"] == item["grupo"]), None)
            if grupo is None:
                grupo = {"nome": item["grupo"], "subgrupos": []}
                grupos.append(grupo)
            bloco = {"nome": item["subgrupo"], "produtos": []}
            grupo["subgrupos"].append(bloco)
            indice[chave] = bloco
        preco = preco_para_cardapio(item, quando)
        publico = {"nome": item["nome"], **preco}
        if item.get("descricao"):
            publico["descricao"] = item["descricao"]
        if item.get("foto"):
            publico["foto"] = item["foto"]
        bloco["produtos"].append(publico)
    return grupos


def _mesa(mesa: str | None) -> int | None:
    if mesa is None or mesa == "":
        return None
    if not str(mesa).isdigit() or not 1 <= int(mesa) <= 999:
        raise HTTPException(status_code=422, detail="Informe a mesa de 1 a 999.")
    return int(mesa)


def instalar(app: FastAPI, Loja, autenticar) -> APIRouter:
    Base.metadata.create_all(bind=engine)
    router = APIRouter()

    def _loja_ativa(db: Session, chave: str):
        if not CHAVE_RE.fullmatch(chave or ""):
            raise HTTPException(status_code=404, detail="Cardápio não publicado.")
        loja = db.query(Loja).filter(Loja.chave_loja == chave).first()
        if loja is None or not loja.ativa:
            raise HTTPException(status_code=404, detail="Cardápio não publicado.")
        return loja

    @router.post("/v1/cardapio/envio")
    def envio(dados: dict = Body(...), acesso=Depends(autenticar), db: Session = Depends(get_db)):
        if acesso.admin:
            raise HTTPException(status_code=403, detail="Use o token da loja para publicar o cardápio.")
        bruto = dados.get("produtos")
        if not isinstance(bruto, list) or len(bruto) > MAX_PRODUTOS:
            raise HTTPException(status_code=422, detail=f"Envie uma lista de até {MAX_PRODUTOS} produtos.")
        produtos = [p for p in (produto_limpo(i) for i in bruto) if p]
        linha = db.get(CardapioLoja, acesso.loja)
        if linha is None:
            linha = CardapioLoja(chave_loja=acesso.loja)
            db.add(linha)
        linha.nome = _txt(dados.get("loja_nome"), 80).strip()
        linha.logo = _logo(dados.get("logo"))
        linha.produtos = json.dumps(produtos, ensure_ascii=False)
        linha.atualizado_em = _txt(dados.get("enviado_em"), 19) or _agora()
        db.commit()
        return {"produtos": len(produtos)}

    @router.get("/v1/cardapio")
    def consultar(loja: str = Query(..., max_length=64), mesa: str | None = Query(None, max_length=4),
                  db: Session = Depends(get_db)):
        cadastro = _loja_ativa(db, loja.strip())
        linha = db.get(CardapioLoja, cadastro.chave_loja)
        if linha is None:
            raise HTTPException(status_code=404, detail="O cardápio ainda não foi publicado.")
        numero = _mesa(mesa)
        return {
            "loja": {"chave": cadastro.chave_loja, "nome": linha.nome or cadastro.nome},
            "logo": linha.logo or "",
            "mesa": numero,
            "atualizado_em": linha.atualizado_em,
            "grupos": agrupar(_ler_produtos(linha.produtos), agora_local()),
        }

    app.include_router(router)
    if PASTA_WEB.is_dir():
        @app.get("/cardapio", include_in_schema=False)
        def cardapio_raiz():
            return RedirectResponse(url="/cardapio/")

        @app.get("/cardapio/", include_in_schema=False)
        def cardapio_index():
            return FileResponse(PASTA_WEB / "index.html", headers={"Cache-Control": "no-cache"})

        app.mount("/cardapio", StaticFiles(directory=str(PASTA_WEB)), name="cardapio")
    return router
