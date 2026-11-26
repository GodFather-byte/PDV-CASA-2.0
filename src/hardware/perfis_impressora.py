"""Tamanho do cupom: largura do papel (58 ou 80 mm) e tamanho da letra (normal ou pequena).

Na térmica o que define o cupom é quantos caracteres cabem por linha. Se o caixa manda mais colunas do que o papel
comporta, cada linha quebra em duas e o cupom sai comprido e bagunçado; se manda menos, sobra papel dos lados. Aqui
fica a tabela certa para cada combinação e o palpite do papel pelo nome da impressora (POS-58, XP-80, Elgin i9...).

A letra pequena é a fonte B das térmicas ESC/POS (ESC M 1): mesma impressora, letra menor, cabe mais por linha e o
cupom fica mais curto. Toda térmica ESC/POS tem as duas fontes.
"""
from __future__ import annotations

import re

PAPEIS = (58, 80)
LETRAS = ("normal", "pequena")
# Caracteres por linha em cada papel e letra (fonte A 12x24 e fonte B 9x17, cabeça de 203 dpi).
COLUNAS = {(58, "normal"): 32, (58, "pequena"): 42, (80, "normal"): 48, (80, "pequena"): 64}

_PAPEL_58 = re.compile(r"(?<!\d)58(?!\d)|58\s*mm|\bmini\b|port[aá]til|bluetooth|\bmtp\b|\bpt-?2\d{2}\b", re.I)
_PAPEL_80 = re.compile(r"(?<!\d)80(?!\d)|80\s*mm|\bi[79]\b|elgin|tm-?t\d|mp-?(4200|2500|100)|bematech|daruma|"
                       r"sweda|tanca|diebold|control\s*id|star\s*tsp|\btsp\d", re.I)


def colunas(papel_mm: int, letra: str = "normal") -> int:
    papel = 58 if int(papel_mm or 0) == 58 else 80
    return COLUNAS[(papel, letra if letra in LETRAS else "normal")]


def colunas_letra_normal(papel_mm: int, colunas_atuais: int = 48) -> int:
    """Largura em caracteres da letra normal (é o que o logotipo usa para saber a largura em pontos)."""
    if int(papel_mm or 0) in PAPEIS:
        return colunas(papel_mm, "normal")
    return min(int(colunas_atuais or 48), 48)


def papel_pelo_nome(*textos: str) -> int | None:
    """Palpite da largura do papel pelo nome e pelo driver da impressora. None quando não dá para saber."""
    texto = " ".join(t or "" for t in textos)
    if _PAPEL_58.search(texto):
        return 58
    if _PAPEL_80.search(texto):
        return 80
    return None


def papel_das_colunas(colunas_atuais: int) -> int:
    """Para quem já usava o caixa antes desta opção: 32 a 42 colunas é papel de 58 mm; o resto, 80 mm."""
    return 58 if int(colunas_atuais or 0) and int(colunas_atuais) <= 42 else 80


def descrever(papel_mm: int, letra: str) -> str:
    return f"papel de {papel_mm} mm, letra {letra} ({colunas(papel_mm, letra)} caracteres por linha)"
