"""Ledger imutável de devoluções do painel. Ajustes analíticos não movimentam dinheiro nem salários."""
import json
import math
from datetime import date, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Column, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import insert as inserir_postgres
from sqlalchemy.dialects.sqlite import insert as inserir_sqlite

from backend.database import Base


class PainelDevolucao(Base):
    __tablename__ = "painel_devolucoes"
    __table_args__ = (UniqueConstraint("chave_loja", "uuid", name="ux_painel_devolucao"),)
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    uuid = Column(String, nullable=False)
    dia = Column(String, index=True, nullable=False)
    valor_cent = Column(Integer, nullable=False)
    dados = Column(Text, nullable=False)
    recebida_em = Column(String, nullable=False)


def guardar(db, chave: str, dado: dict, agora: str, corte: str) -> str:
    try:
        uid = str(UUID(dado["uuid"]))
        UUID(dado["venda_uuid"])
        if date.fromisoformat(dado["dia"]).isoformat() != dado["dia"]:
            raise ValueError
        instante = datetime.strptime(dado["criado_em"], "%Y-%m-%d %H:%M:%S")
        if instante.strftime("%Y-%m-%d %H:%M:%S") != dado["criado_em"]:
            raise ValueError
        if type(dado["valor_cent"]) is not int or dado["valor_cent"] < 0:
            raise ValueError
        if dado["modo"] not in ("dinheiro_gaveta", "externo", "caderneta"):
            raise ValueError
        if type(dado["custo_completo"]) is not bool or not isinstance(dado["itens"], list) or len(dado["itens"]) > 2000:
            raise ValueError
        for i in dado["itens"]:
            qtd = i["quantidade"]
            if type(qtd) not in (int, float) or not math.isfinite(qtd) or qtd <= 0:
                raise ValueError
            if type(i["item_id"]) is not int or i["item_id"] <= 0 or type(i["retorna_estoque"]) is not bool:
                raise ValueError
            if type(i["comissao_ajuste_cent"]) is not int:
                raise ValueError
            for campo in ("custo_recuperado_cent", "comissao_ajuste_cent"):
                v = i.get(campo)
                if v is not None and (type(v) is not int or v < 0):
                    raise ValueError
            if dado["custo_completo"] and i.get("custo_recuperado_cent") is None:
                raise ValueError
        corpo = json.dumps(dado, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(status_code=422, detail="Devolução inválida; confira UUID, datas e valores em centavos.") from None
    if dado["dia"] < corte:
        return uid
    inserir = inserir_sqlite if db.get_bind().dialect.name == "sqlite" else inserir_postgres
    db.execute(inserir(PainelDevolucao).values(chave_loja=chave, uuid=uid, dia=dado["dia"],
               valor_cent=dado["valor_cent"], dados=corpo, recebida_em=agora).on_conflict_do_nothing(
                   index_elements=["chave_loja", "uuid"]))
    existente = db.query(PainelDevolucao).filter_by(chave_loja=chave, uuid=uid).one()
    if existente.dados != corpo:
        raise HTTPException(status_code=409, detail="O UUID de devolução já identifica outro conteúdo imutável.")
    return uid


def resumo(db, chave: str, de: str, ate: str) -> dict:
    linhas = db.query(PainelDevolucao).filter(PainelDevolucao.chave_loja == chave,
                PainelDevolucao.dia >= de, PainelDevolucao.dia <= ate).all()
    r = {"quantidade": len(linhas), "valor_cent": 0, "custo_recuperado_cent": 0,
         "comissao_ajuste_cent": 0, "custos_incompletos": 0}
    for linha in linhas:
        d = json.loads(linha.dados)
        r["valor_cent"] += linha.valor_cent
        r["custos_incompletos"] += int(not d["custo_completo"])
        r["custo_recuperado_cent"] += sum(i.get("custo_recuperado_cent") or 0 for i in d["itens"])
        r["comissao_ajuste_cent"] += sum(i.get("comissao_ajuste_cent") or 0 for i in d["itens"])
    return r


def por_dia(db, chave: str, de: str, ate: str) -> dict:
    return dict(db.query(PainelDevolucao.dia, func.sum(PainelDevolucao.valor_cent)).filter(
        PainelDevolucao.chave_loja == chave, PainelDevolucao.dia >= de, PainelDevolucao.dia <= ate
    ).group_by(PainelDevolucao.dia).all())
