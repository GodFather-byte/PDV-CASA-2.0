"""Bandeira 2 pelo painel do dono: a nuvem guarda o que o dono escolheu (ligada, % ou reais por item) com um número
de versão. O caixa manda a versão que já aplicou em cada envio do painel; quando a nuvem tem uma mais nova, devolve na
resposta e o caixa grava nas configurações. O botão do dono acorda o caixa (pedido de envio), então leva segundos.
"""
from __future__ import annotations

from src.core import formatacao as fmt

CHAVE_VERSAO = "bandeira2_versao"


def versao_aplicada(banco) -> int:
    return max(0, banco.cfg_int(CHAVE_VERSAO, 0))


def para_envio(banco) -> dict:
    """O que vai no corpo do envio: a versão aplicada e o estado local (o dono vê no painel o que está valendo)."""
    return {"bandeira2_versao": versao_aplicada(banco),
            "bandeira2_local": {"ativa": banco.cfg_bool("bandeira2_ativa", False),
                                "modo": banco.cfg("bandeira2_modo", "pct") or "pct",
                                "pct": banco.cfg("bandeira2_pct", "0") or "0",
                                "reais_cent": banco.cfg_int("bandeira2_reais_cent", 0)}}


def anotar_resposta(banco, dados: dict) -> bool:
    """Aplica a bandeira 2 que veio da nuvem, se for mais nova que a do caixa. Devolve True quando mudou algo."""
    bloco = dados.get("bandeira2") if isinstance(dados, dict) else None
    if not isinstance(bloco, dict):
        return False
    try:
        versao = int(bloco.get("versao") or 0)
    except (TypeError, ValueError):
        return False
    if versao <= versao_aplicada(banco):
        return False
    modo = "reais" if bloco.get("modo") == "reais" else "pct"
    try:
        valor = int(bloco.get("valor") or 0)
    except (TypeError, ValueError):
        return False
    if not 0 <= valor <= (100_000 if modo == "reais" else 300):
        return False
    ativa = bool(bloco.get("ativa"))
    banco.cfg_set("bandeira2_ativa", "S" if ativa else "N")
    banco.cfg_set("bandeira2_modo", modo)
    if modo == "reais":
        banco.cfg_set("bandeira2_reais_cent", str(valor))
    else:
        banco.cfg_set("bandeira2_pct", str(valor))
    banco.cfg_set(CHAVE_VERSAO, str(versao))
    texto = (f"+{fmt.fmt_brl(valor)} por item" if modo == "reais" else f"+{valor}%")
    banco.log("bandeira2_painel", ("ligada " + texto if ativa else "desligada") + f" pelo dono ({bloco.get('por') or 'painel'})")
    return True
