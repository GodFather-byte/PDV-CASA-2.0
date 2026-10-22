"""Versão do PDV. Suba o número a cada entrega e publique as notas na nuvem
(`python -m backend.atualizacoes publicar <versão> --notas "..."`): os caixas conectados avisam o dono."""
from __future__ import annotations

import re

VERSAO = "1.9.0"

_FORMATO = re.compile(r"\d{1,4}(\.\d{1,4}){0,3}")


def valida(versao: str) -> bool:
    return bool(_FORMATO.fullmatch((versao or "").strip()))


def chave(versao: str) -> tuple[int, ...]:
    """'1.10.2' -> (1, 10, 2, 0): compara número a número (1.10 é mais nova que 1.9) e ignora zeros à direita."""
    if not valida(versao):
        raise ValueError(f"Versão inválida: {versao!r} (use números separados por ponto, ex.: 1.2.0).")
    partes = [int(p) for p in versao.strip().split(".")]
    return tuple(partes + [0] * (4 - len(partes)))


def mais_nova(a: str, b: str) -> bool:
    """True se `a` é mais nova que `b`."""
    return chave(a) > chave(b)
