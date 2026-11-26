"""Bandeira 2 pelo painel do dono: um botão liga/desliga e o valor (+% em tudo ou +R$ por item) escolhido ali.

A nuvem guarda o que o dono escolheu com uma versão. A cada envio do painel o caixa conta qual versão já aplicou; se a
nuvem tiver uma mais nova, vai na resposta (`bandeira2`). O botão também acorda o caixa (pedido de envio na memória),
então o caixa aplica em segundos. Cada mudança fica no histórico (quem, quando, valor).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.orm import Session

from backend.database import Base, get_db

LIMITE_PCT = 300
LIMITE_REAIS_CENT = 100_000


class Bandeira2Loja(Base):
    __tablename__ = "bandeira2_lojas"
    chave_loja = Column(String, primary_key=True)
    ativa = Column(Boolean, nullable=False, default=False)
    modo = Column(String(5), nullable=False, default="pct")       # pct | reais
    valor = Column(Integer, nullable=False, default=0)            # % inteiro ou centavos por item
    versao = Column(Integer, nullable=False, default=0)
    atualizado_em = Column(String(19), nullable=False, default="")
    aplicada_versao = Column(Integer, nullable=False, default=0)  # o que o caixa disse que já aplicou
    aplicada_em = Column(String(19), nullable=True)


class Bandeira2Historico(Base):
    __tablename__ = "bandeira2_historico"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    quando = Column(String(19), nullable=False)
    ativa = Column(Boolean, nullable=False)
    modo = Column(String(5), nullable=False)
    valor = Column(Integer, nullable=False)
    por = Column(String(80), nullable=False, default="")


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def descrever(modo: str, valor: int) -> str:
    if modo == "reais":
        return "+R$ " + f"{valor / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " por item"
    return f"+{valor}%"


def situacao(db: Session, chave_loja: str, local: dict | None = None) -> dict:
    linha = db.get(Bandeira2Loja, chave_loja)
    historico = (db.query(Bandeira2Historico).filter_by(chave_loja=chave_loja)
                 .order_by(Bandeira2Historico.id.desc()).limit(10).all())
    return {
        "ativa": bool(linha.ativa) if linha else False,
        "modo": linha.modo if linha else "pct",
        "valor": int(linha.valor) if linha else 0,
        "texto": descrever(linha.modo, int(linha.valor)) if linha else "",
        "aplicada_no_caixa": bool(linha) and linha.aplicada_versao >= linha.versao,
        "aplicada_em": linha.aplicada_em if linha else None,
        "historico": [{"quando": h.quando, "ativa": bool(h.ativa), "texto": descrever(h.modo, h.valor), "por": h.por}
                      for h in historico],
    }


def alterar(db: Session, chave_loja: str, ativa: bool, modo: str, valor, por: str = "") -> dict:
    modo = "reais" if modo == "reais" else "pct"
    if type(valor) is not int:
        raise ValueError("Informe o valor da bandeira 2.")
    limite = LIMITE_REAIS_CENT if modo == "reais" else LIMITE_PCT
    if not 0 <= valor <= limite:
        raise ValueError("Valor fora do limite (até 300% ou R$ 1.000,00 por item).")
    if ativa and valor == 0:
        raise ValueError("Para ligar a bandeira 2, informe quanto ela aumenta.")
    linha = db.get(Bandeira2Loja, chave_loja)
    if linha is None:
        linha = Bandeira2Loja(chave_loja=chave_loja, versao=0, aplicada_versao=0)
        db.add(linha)
    linha.ativa, linha.modo, linha.valor = bool(ativa), modo, valor
    linha.versao = int(linha.versao or 0) + 1
    linha.atualizado_em = _agora()
    db.add(Bandeira2Historico(chave_loja=chave_loja, quando=linha.atualizado_em, ativa=bool(ativa), modo=modo,
                              valor=valor, por=(por or "painel")[:80]))
    db.commit()
    return situacao(db, chave_loja)


def para_resposta(db: Session, chave_loja: str, dados: dict) -> dict:
    """No envio do painel: anota o que o caixa já aplicou e devolve a escolha do dono se for mais nova."""
    linha = db.get(Bandeira2Loja, chave_loja)
    if linha is None:
        return {}
    try:
        aplicada = int(dados.get("bandeira2_versao") or 0)
    except (TypeError, ValueError):
        aplicada = 0
    if aplicada != linha.aplicada_versao and aplicada <= linha.versao:
        linha.aplicada_versao = aplicada
        linha.aplicada_em = _agora()
        db.commit()
    if aplicada >= linha.versao:
        return {}
    return {"bandeira2": {"versao": linha.versao, "ativa": bool(linha.ativa), "modo": linha.modo,
                          "valor": int(linha.valor), "por": "painel do dono"}}


def instalar(app: FastAPI, Loja) -> APIRouter:
    from backend.painel import PainelSessao, sessao_do_dono
    router = APIRouter()

    def sessao_ativa(sessao: PainelSessao = Depends(sessao_do_dono), db: Session = Depends(get_db)):
        loja = db.query(Loja).filter(Loja.chave_loja == sessao.chave_loja).first()
        if sessao.grupo_id or loja is None or not loja.ativa:
            raise HTTPException(status_code=401, detail="Abra uma loja para usar a bandeira 2.")
        return sessao

    @router.get("/v1/painel/bandeira2")
    def ver(sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        return situacao(db, sessao.chave_loja)

    @router.post("/v1/painel/bandeira2")
    def mudar(dados: dict = Body(...), sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        dados = dados or {}
        try:
            resultado = alterar(db, sessao.chave_loja, bool(dados.get("ativa")), str(dados.get("modo") or "pct"),
                                dados.get("valor"), "painel do dono")
        except ValueError as erro:
            raise HTTPException(status_code=422, detail=str(erro)) from None
        try:
            from backend.memoria_nuvem import memoria
            memoria.pedir(sessao.chave_loja)            # acorda o caixa: ele envia e recebe a bandeira na resposta
        except Exception:                                # noqa: BLE001 - sem o aviso, vale no próximo envio
            pass
        return resultado

    app.include_router(router)
    return router
