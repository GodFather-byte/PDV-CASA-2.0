"""Ficha de crédito em dinheiro: lançamento na comanda e sangria no mesmo commit.

Opt-in por código de produto na configuração da loja. A associação pelo ID imutável
do item na descrição do movimento mantém compatibilidade com bancos já instalados.
Não repetir nem estornar movimentação sem confirmação de devolução física do dinheiro.
"""
from __future__ import annotations

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

PREFIXO_SAIDA = "FICHA-ITEM:"
PREFIXO_ESTORNO = "ESTORNO-FICHA-ITEM:"


def eh_ficha(banco, produto: dict) -> bool:
    configurado = str(banco.cfg("codigo_ficha_sangria") or "").strip().lstrip("0")
    codigo = str(produto.get("codigo") or "").strip().lstrip("0")
    return bool(configurado and codigo and configurado == codigo)


def _movimento(banco, prefixo: str, item_id: int) -> dict | None:
    registro = banco.um(
        "SELECT * FROM movimentos_caixa WHERE descricao LIKE ? ORDER BY id LIMIT 1",
        (f"{prefixo}{item_id} %",))
    return dict(registro) if registro else None


def saida_do_item(banco, item_id: int) -> dict | None:
    return _movimento(banco, PREFIXO_SAIDA, item_id)


def estorno_do_item(banco, item_id: int) -> dict | None:
    return _movimento(banco, PREFIXO_ESTORNO, item_id)


def fichas_ativas_na_venda(banco, venda_id: int) -> list[dict]:
    resultado = []
    for item in banco.todos(
        "SELECT id FROM itens_venda WHERE venda_id = ? AND cancelado = 0 ORDER BY id",
        (venda_id,)):
        mov = saida_do_item(banco, item["id"])
        if mov and not estorno_do_item(banco, item["id"]):
            resultado.append({"item_id": item["id"], "valor_cent": mov["valor_cent"]})
    return resultado


def registrar_saida(banco, turnos, item_id: int, venda: dict, valor_cent: int, operador_id: int) -> dict:
    """Chamar dentro da transação que incluiu o item; falha desfaz os dois registros."""
    if venda["modalidade"] != "mesa" or not venda["comanda"]:
        raise ErroNegocio("Ficha com sangria automática só pode ser lançada em comanda.")
    if valor_cent <= 0:
        raise ErroNegocio("Valor da ficha precisa ser maior que zero.")
    if saida_do_item(banco, item_id):
        raise ErroNegocio("Esta ficha já possui sangria registrada.")
    turno = turnos.exigir_aberto()
    if turnos.dinheiro_esperado(turno["id"]) < valor_cent:
        raise ErroNegocio("Dinheiro esperado no caixa insuficiente para entregar esta ficha.")
    descricao = f"{PREFIXO_SAIDA}{item_id} COMANDA {venda['posicao']}"
    mid = turnos.movimentar(turno["id"], operador_id, "saida", valor_cent, descricao)
    return {"movimento_id": mid, "item_id": item_id, "valor_cent": valor_cent, "comanda": venda["posicao"]}


def registrar_estorno(banco, turnos, item_id: int, operador_id: int) -> int:
    """Só após operador confirmar que o dinheiro físico retornou à gaveta."""
    original = saida_do_item(banco, item_id)
    if original is None:
        return 0
    if estorno_do_item(banco, item_id):
        raise ErroNegocio("A ficha já foi estornada; confira os movimentos de caixa.")
    turno = turnos.exigir_aberto()
    descricao = f"{PREFIXO_ESTORNO}{item_id} DEVOLUCAO DINHEIRO"
    turnos.movimentar(turno["id"], operador_id, "entrada", original["valor_cent"], descricao)
    return original["valor_cent"]
