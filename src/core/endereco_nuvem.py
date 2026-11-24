"""Endereço da nuvem para onde o caixa pode mandar o token da loja.

HTTPS vale sempre. HTTP só no próprio computador, num IP de rede local (teste na
loja) ou no host `testserver` do cliente de teste. Um endereço http público não
recebe token, venda nem backup.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

_NOMES_LOCAIS = {"localhost", "testserver"}


def aceita_credencial(url: str) -> bool:
    """True se dá para mandar Authorization para este endereço."""
    try:
        partes = urlsplit((url or "").strip())
    except ValueError:
        return False
    if partes.username or partes.password:
        return False
    host = (partes.hostname or "").rstrip(".").lower()
    if not host:
        return False
    if partes.scheme == "https":
        return True
    if partes.scheme != "http":
        return False
    if host in _NOMES_LOCAIS or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local)


def autorizar(url: str, token: str) -> dict | None:
    """Cabeçalho Bearer, ou None se o endereço não pode receber o token."""
    segredo = (token or "").strip()
    if not segredo or not aceita_credencial(url):
        return None
    return {"Authorization": f"Bearer {segredo}"}
