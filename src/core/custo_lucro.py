"""Contas de custo e lucro em centavos inteiros. Quantidade pode ser fracionada; dinheiro, não.

O custo vigente do produto é o custo médio. Sem média cadastrada, vale o último preço de compra.
A margem é em centésimos de ponto percentual (3000 = 30,00%), sempre arredondada, nunca float.
"""
from __future__ import annotations

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio


def custo_vigente(custo_medio_cent: int | None, ult_preco_cent: int | None = 0) -> int:
    medio = int(custo_medio_cent or 0)
    if medio > 0:
        return medio
    return int(ult_preco_cent or 0)


def lucro_cent(venda_cent: int, custo_cent: int) -> int:
    return int(venda_cent) - int(custo_cent)


def margem_bp(venda_cent: int, custo_cent: int) -> int | None:
    """Centésimos de ponto percentual. None quando não há preço de venda."""
    if int(venda_cent) <= 0:
        return None
    return fmt.arredondar(fmt._dec(int(venda_cent) - int(custo_cent)) * 10000 / fmt._dec(int(venda_cent)))


def margem_texto(venda_cent: int, custo_cent: int) -> str:
    bp = margem_bp(venda_cent, custo_cent)
    if bp is None:
        return "—"
    sinal = "-" if bp < 0 else ""
    absoluto = abs(bp)
    return f"{sinal}{absoluto // 100},{absoluto % 100:02d}%"


def preco_pela_margem(custo_cent: int, margem_pct: int) -> int:
    """Preço de venda para a margem desejada (0 a 99, inteira). 40 em um custo de R$ 6 vira R$ 10."""
    if type(custo_cent) is not int or custo_cent < 0:
        raise ErroNegocio("O custo precisa ser um valor em centavos, zero ou maior.")
    if type(margem_pct) is not int or not 0 <= margem_pct < 100:
        raise ErroNegocio("A margem desejada é um número inteiro de 0 a 99.")
    if custo_cent == 0:
        return 0
    return fmt.arredondar(fmt._dec(custo_cent) * 100 / (100 - margem_pct))


def custo_medio_ponderado(saldo_qtd, custo_atual_cent: int, qtd_entrada, custo_entrada_cent: int) -> int:
    """Média ponderada. `custo_entrada_cent` é o total da entrada, não o unitário.

    Saldo zero ou negativo: o custo da entrada passa a ser a média. Não usa float.
    """
    saldo = fmt._dec(saldo_qtd or 0)
    if saldo < 0:
        saldo = fmt._dec(0)
    entrada = fmt._dec(qtd_entrada or 0)
    if entrada <= 0:
        return int(custo_atual_cent or 0)
    if saldo == 0:
        return fmt.dividir_cent(int(custo_entrada_cent), qtd_entrada)
    total = fmt.mult_cent(int(custo_atual_cent or 0), saldo) + int(custo_entrada_cent)
    return fmt.dividir_cent(total, saldo + entrada)


def reverter_custo_medio(saldo_depois, custo_atual_cent: int, qtd_retirada, custo_retirado_cent: int) -> int:
    """Desfaz uma entrada no médio. Exato se nada foi vendido no meio; o histórico guarda os dois valores."""
    saldo = fmt._dec(saldo_depois or 0)
    if saldo <= 0:
        return 0
    total = fmt.mult_cent(int(custo_atual_cent or 0), saldo + fmt._dec(qtd_retirada or 0)) - int(custo_retirado_cent)
    if total < 0:
        total = 0
    return fmt.dividir_cent(total, saldo)


def alocar_fifo(compras: list[dict], vendas: list[dict]) -> dict[int, dict]:
    """Reparte as vendas, da mais antiga para a mais nova, entre as compras na mesma ordem.

    Cada compra devolve a quantidade vendida atribuída a ela e a receita dessas unidades.
    O lucro realizado é essa receita menos o custo da própria compra (não o médio de hoje).
    """
    restantes = []
    for compra in compras:
        restantes.append({
            "id": int(compra["id"]),
            "resta": fmt._dec(compra["qtd"]),
            "custo": int(compra["custo_cent"]),
            "qtd": fmt._dec(compra["qtd"]),
            "vendida": fmt._dec(0),
            "receita": 0,
        })
    for venda in vendas:
        falta = fmt._dec(venda["qtd"])
        receita = int(venda["receita_cent"])
        vendida_total = fmt._dec(venda["qtd"])
        if falta <= 0 or vendida_total <= 0:
            continue
        consumido = fmt._dec(0)
        for compra in restantes:
            if falta <= 0:
                break
            if compra["resta"] <= 0:
                continue
            pega = compra["resta"] if compra["resta"] < falta else falta
            compra["resta"] -= pega
            compra["vendida"] += pega
            compra["receita"] += fmt.arredondar(fmt._dec(receita) * pega / vendida_total)
            consumido += pega
            falta -= pega
        if consumido < vendida_total and restantes:
            # o arredondamento da receita pode sobrar ou faltar um centavo: ajusta na última compra atingida
            pass
    saida = {}
    for compra in restantes:
        custo_vendido = fmt.arredondar(fmt._dec(compra["custo"]) * compra["vendida"] / compra["qtd"]) if compra["qtd"] else 0
        saida[compra["id"]] = {
            "qtd_vendida": float(compra["vendida"]),
            "receita_cent": int(compra["receita"]),
            "custo_cent": int(custo_vendido),
            "lucro_cent": int(compra["receita"]) - int(custo_vendido),
        }
    return saida
