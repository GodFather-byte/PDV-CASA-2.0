"""Cálculo de totais do caixa, sem gravação e com as regras originais de serviço, desconto e consumação."""
from src.core import formatacao as fmt


def calcular(caixa, v: dict, itens: list[dict] | None = None) -> dict:
    itens = itens if itens is not None else caixa.itens(v["id"])
    rodizio_total = 0
    itens_cobrados = itens
    if v.get("rodizio"):
        # Rodízio: produtos do subgrupo "incluso" não entram na conta por item (preço fixo cobre eles);
        # bebida e extras (subgrupo não marcado) continuam cobrados normalmente, por item.
        itens_cobrados = [i for i in itens if not i["rodizio_incluso"]]
        valor_pessoa = fmt.para_centavos(caixa.banco.cfg("valor_rodizio_pessoa", "0") or 0)
        rodizio_total = valor_pessoa * (v["pessoas"] or 0)
    subtotal = sum(i["total_cent"] for i in itens_cobrados) + rodizio_total
    if v["desconto_pct"] > 0:
        desconto = fmt.pct_de(subtotal, v["desconto_pct"])
    else:
        desconto = v["desconto_cent"]
    desconto = min(max(desconto, 0), subtotal)
    servico = 0
    chave_servico = "cobra_servico_comanda" if v.get("comanda") else "cobra_servico_mesa"
    if v["modalidade"] == "mesa" and caixa.banco.cfg_bool(chave_servico, True):
        if v["servico_manual"]:
            servico = v["servico_cent"]
        else:
            base = sum(i["total_cent"] for i in itens_cobrados if i["cobra_servico"]) + rodizio_total
            servico = fmt.pct_de(base, caixa.banco.cfg("servico_pct", "10") or 0)
    taxa = v["taxa_cent"]
    if v["modalidade"] == "mesa" and v.get("comanda") and not v.get("rodizio"):
        taxa = caixa.complemento_consumacao(v["posicao"], subtotal - desconto)      # comanda não tem taxa de entrega
    acrescimo = caixa.acrescimo_pagamento(v)
    return {"subtotal": subtotal, "desconto": desconto, "servico": servico, "taxa": taxa, "acrescimo": acrescimo,
            "rodizio_total": rodizio_total,
            "total": subtotal - desconto + servico + taxa + acrescimo}

