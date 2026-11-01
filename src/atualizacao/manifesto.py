"""Manifesto assinado de uma atualização do programa.

A chave pública vai no PDV. A semente privada fica só no GitHub Secret `PDV_ATUALIZACAO_CHAVE`
(ou na máquina de quem publica). Não é a chave da licença.
"""
from __future__ import annotations

import json

from src.core import ed25519

# Troque este valor só junto com a semente privada, e só antes do último instalador manual.
CHAVE_PUBLICA_HEX = "2dbf1db570be8be3ecdb591f3025db2c7742269a817f79b1e99ab4e973f9409e"
EDICOES = ("willpdv", "ea_superacoes", "bar")
CANAIS = ("estavel",)
CAMPOS = ("canal", "edicao", "minima", "notas", "obrigatoria", "sha256", "tamanho", "url", "versao")


def nucleo(pacote: dict) -> dict:
    return {chave: pacote[chave] for chave in CAMPOS}


def mensagem(pacote: dict) -> bytes:
    return json.dumps(nucleo(pacote), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def assinar(semente: bytes, pacote: dict) -> str:
    return ed25519.assinar(semente, mensagem(pacote)).hex()


def conferir(pacote: dict, publica_hex: str = CHAVE_PUBLICA_HEX) -> bool:
    try:
        assinatura = bytes.fromhex(str(pacote.get("assinatura") or ""))
        publica = bytes.fromhex(publica_hex)
        nucleo(pacote)
    except (ValueError, KeyError):
        return False
    return ed25519.verificar(publica, mensagem(pacote), assinatura)
