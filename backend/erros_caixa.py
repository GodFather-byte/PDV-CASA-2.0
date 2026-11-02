"""Erros do caixa na nuvem. Sobe só no lote que o PDV já manda; a limpeza é a do painel.

No máximo 300 linhas por loja e 30 dias. O mesmo erro soma em `vezes`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Column, Integer, String, Text, UniqueConstraint

from backend.database import Base

RETENCAO_DIAS = 30
TETO_POR_LOJA = 300
LIMITE_MENSAGEM = 300
LIMITE_TRILHA = 4000
LIMITE_CONTEXTO = 300


class ErroCaixa(Base):
    __tablename__ = "erros_caixa"
    __table_args__ = (UniqueConstraint("chave_loja", "assinatura", name="uq_erro_caixa"),)
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    assinatura = Column(String(64), nullable=False)
    nivel = Column(String(20), nullable=False, default="error")
    modulo = Column(String(80), nullable=False, default="")
    mensagem = Column(String(LIMITE_MENSAGEM), nullable=False, default="")
    traceback = Column(Text, nullable=False, default="")
    contexto = Column(String(LIMITE_CONTEXTO), nullable=False, default="")
    vezes = Column(Integer, nullable=False, default=1)
    criado_em = Column(String(19), nullable=False)
    atualizado_em = Column(String(19), nullable=False)


def _corte(texto: str, limite: int) -> str:
    return str(texto or "")[:limite]


def guardar(db, chave_loja: str, itens: list) -> list[str]:
    """Grava ou soma. Devolve as assinaturas aceitas, para o caixa marcar como enviadas."""
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    aceitas = []
    for bruto in itens[:20]:
        if not isinstance(bruto, dict):
            continue
        assinatura = _corte(bruto.get("assinatura"), 64)
        if len(assinatura) < 16:
            continue
        linha = db.query(ErroCaixa).filter_by(chave_loja=chave_loja, assinatura=assinatura).first()
        vezes = max(int(bruto.get("vezes") or 1), 1)
        if linha is None:
            linha = ErroCaixa(
                chave_loja=chave_loja, assinatura=assinatura,
                nivel=_corte(bruto.get("nivel") or "error", 20),
                modulo=_corte(bruto.get("modulo"), 80),
                mensagem=_corte(bruto.get("mensagem"), LIMITE_MENSAGEM),
                traceback=_corte(bruto.get("traceback"), LIMITE_TRILHA),
                contexto=_corte(bruto.get("contexto"), LIMITE_CONTEXTO),
                vezes=vezes, criado_em=_corte(bruto.get("criado_em"), 19) or agora, atualizado_em=agora)
            db.add(linha)
        else:
            linha.vezes = int(linha.vezes or 0) + vezes
            linha.atualizado_em = agora
        aceitas.append(assinatura)
    return aceitas


def podar(db) -> int:
    """Tira o que passou de 30 dias e o que excede o teto por loja. Devolve quantas linhas saíram."""
    limite = (datetime.now() - timedelta(days=RETENCAO_DIAS)).strftime("%Y-%m-%d %H:%M:%S")
    saidas = db.query(ErroCaixa).filter(ErroCaixa.atualizado_em < limite).delete(synchronize_session=False)
    lojas = [r[0] for r in db.query(ErroCaixa.chave_loja).distinct()]
    for chave in lojas:
        ids = [r[0] for r in db.query(ErroCaixa.id).filter_by(chave_loja=chave).order_by(ErroCaixa.id.desc())]
        if len(ids) > TETO_POR_LOJA:
            velhos = ids[TETO_POR_LOJA:]
            saidas += db.query(ErroCaixa).filter(ErroCaixa.id.in_(velhos)).delete(synchronize_session=False)
    return int(saidas or 0)


def listar(db, loja: str | None, desde: str | None, nivel: str | None, limite: int) -> list[dict]:
    consulta = db.query(ErroCaixa)
    if loja:
        consulta = consulta.filter(ErroCaixa.chave_loja == loja)
    if desde:
        consulta = consulta.filter(ErroCaixa.atualizado_em >= desde[:19])
    if nivel:
        consulta = consulta.filter(ErroCaixa.nivel == nivel[:20])
    linhas = consulta.order_by(ErroCaixa.atualizado_em.desc()).limit(max(1, min(limite, 200)))
    return [{
        "loja": r.chave_loja, "nivel": r.nivel, "modulo": r.modulo, "mensagem": r.mensagem,
        "traceback": r.traceback, "contexto": r.contexto, "vezes": r.vezes,
        "criado_em": r.criado_em, "atualizado_em": r.atualizado_em,
    } for r in linhas]
