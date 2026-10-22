"""Leitura do valor digitado no pagamento do caixa (compartilhada pelas telas)."""
from __future__ import annotations

import re
from decimal import Decimal

from src.core import formatacao as fmt

LIMITE_VALOR_CENT = 100_000_000       # R$ 1.000.000,00: acima disso é erro de digitação (e estoura o banco de dados)
LIMITE_TROCO_CENT = 50_000            # troco acima de R$ 500,00 pede confirmação
_PADRAO_VALOR = re.compile(r"^(?:[0-9]{1,3}(?:\.[0-9]{3})+(?:,[0-9]{1,2})?|[0-9]+(?:[.,][0-9]{1,2})?|[.,][0-9]{1,2})$")


def ler_valor_pagamento(texto: str) -> int:
    """Valor digitado -> centavos. Aceita '25', '25,5', '25.50', '1.000' (mil) e '1.000,50'; recusa letras, sinal, notação
    científica ('1e5'), mais de 2 casas decimais, zero e valores absurdos. Levanta ValueError com a mensagem para o operador."""
    s = (texto or "").strip().replace("R$", "").replace(" ", "")
    if not s:
        raise ValueError("Digite o valor recebido.")
    if not _PADRAO_VALOR.match(s):
        raise ValueError("Valor inválido. Digite só números, com vírgula nos centavos (ex.: 25,50).")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"[0-9]{1,3}\.[0-9]{3}", s):      # 1.000 e 1.000.000 são milhares
        s = s.replace(".", "")
    cent = int((Decimal(s) * 100).to_integral_value())
    if cent <= 0:
        raise ValueError("O valor deve ser maior que zero.")
    if cent > LIMITE_VALOR_CENT:
        raise ValueError(f"Valor alto demais (acima de {fmt.fmt_brl(LIMITE_VALOR_CENT)}). Confira a digitação.")
    return cent
