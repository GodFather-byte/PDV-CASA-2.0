"""Preço que o cardápio mostra: o mesmo preço vigente do caixa (promoção, dia da semana e happy hour).

A nuvem recalcula na hora da consulta, no horário de Brasília, para o happy hour não ficar preso
na hora em que o caixa enviou o catálogo.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.controllers.produto_controller import ProdutoController

_BRASILIA = ZoneInfo("America/Sao_Paulo")


def agora_local() -> datetime:
    """Agora no horário de Brasília, sem fuso (o mesmo formato do relógio do caixa)."""
    return datetime.now(_BRASILIA).replace(tzinfo=None)


def preco_para_cardapio(produto: dict, quando: datetime | None = None) -> dict:
    """Preço em centavos e, se uma promoção venceu, o preço de cadastro para riscar."""
    regra = ProdutoController.regra_preco_vigente(produto, quando or agora_local())
    cadastro = int(produto.get("preco_cent") or 0)
    vigente = int(regra["preco_cent"])
    promocao = regra.get("tipo") == "promocao" and vigente < cadastro
    return {
        "preco_cent": vigente,
        "preco_de_cent": cadastro if promocao else None,
        "promocao": regra.get("criterio") if promocao else None,
    }
