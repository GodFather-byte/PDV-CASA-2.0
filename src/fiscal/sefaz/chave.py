"""Chave de acesso da NF-e/NFC-e (44 números) e o dígito verificador (módulo 11)."""
from __future__ import annotations

import re
import secrets
from datetime import datetime

UF_SP = "35"
MODELO_NFCE = "65"


def digito(chave43: str) -> str:
    """DV da chave: pesos 2 a 9 da direita para a esquerda; resto 0 ou 1 dá 0."""
    if not re.fullmatch(r"\d{43}", chave43 or ""):
        raise ValueError("A chave sem o dígito precisa ter 43 números.")
    soma, peso = 0, 2
    for numero in reversed(chave43):
        soma += int(numero) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def codigo_numerico(numero: int) -> str:
    """cNF: 8 números aleatórios, diferente do número da nota (regra da SEFAZ)."""
    while True:
        cnf = f"{secrets.randbelow(10 ** 8):08d}"
        if int(cnf) != int(numero):
            return cnf


def montar(uf: str, emissao: datetime, cnpj: str, serie: int, numero: int, tp_emis: int, cnf: str,
           modelo: str = MODELO_NFCE) -> str:
    """Chave completa: cUF + AAMM + CNPJ + modelo + série + número + tpEmis + cNF + DV."""
    cnpj = re.sub(r"\D", "", cnpj or "")
    if len(cnpj) != 14:
        raise ValueError("CNPJ do emitente inválido.")
    if not (0 <= int(serie) <= 999 and 1 <= int(numero) <= 999_999_999):
        raise ValueError("Série ou número da nota fora da faixa.")
    if not re.fullmatch(r"\d{8}", cnf or ""):
        raise ValueError("Código numérico (cNF) inválido.")
    base = f"{int(uf):02d}{emissao:%y%m}{cnpj}{modelo}{int(serie):03d}{int(numero):09d}{int(tp_emis)}{cnf}"
    return base + digito(base)


def valida(chave: str) -> bool:
    return bool(re.fullmatch(r"\d{44}", chave or "")) and digito(chave[:43]) == chave[43]
