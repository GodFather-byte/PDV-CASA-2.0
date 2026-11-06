"""Código de instalação da loja: endereço da nuvem, chave da loja e token num texto só.

A central do fornecedor gera o código ao cadastrar a loja (ou ao trocar o token); no caixa, colar o código na tela de
licença configura a nuvem e busca a licença, sem digitar endereço, chave e token separados. O código vale o mesmo que o
token da loja: aparece uma vez e deve ser guardado com o mesmo cuidado.

Formato: ``WILL1-`` seguido do JSON {"u": endereço, "l": loja, "t": token} em base64 para URL, sem "=" no fim.
"""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import urlsplit

from src.core.erros import ErroNegocio

PREFIXO = "WILL1-"
CHAVE = re.compile(r"[A-Za-z0-9._-]{1,64}")
TOKEN = re.compile(r"[A-Za-z0-9_-]{16,200}")
URL_MAX = 200
LOCAIS = ("localhost", "127.0.0.1")


def _url_valida(url: str) -> bool:
    if not isinstance(url, str) or not url or len(url) > URL_MAX:
        return False
    try:
        partes = urlsplit(url)
    except ValueError:
        return False
    if partes.username or partes.password or not partes.hostname or partes.query or partes.fragment:
        return False
    return partes.scheme == "https" or (partes.scheme == "http" and partes.hostname in LOCAIS)


def gerar(url: str, chave: str, token: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not _url_valida(url) or not CHAVE.fullmatch(chave or "") or not TOKEN.fullmatch(token or ""):
        raise ValueError("Dados inválidos para o código de instalação.")
    corpo = json.dumps({"u": url, "l": chave, "t": token}, separators=(",", ":")).encode("utf-8")
    return PREFIXO + base64.urlsafe_b64encode(corpo).decode("ascii").rstrip("=")


def parece_codigo(texto: str) -> bool:
    return "".join((texto or "").split()).upper().startswith(PREFIXO)


def ler(texto: str) -> dict:
    """{"url", "chave", "token"} de um código colado (espaços e quebras de linha são ignorados)."""
    limpo = "".join((texto or "").split())
    if not limpo.upper().startswith(PREFIXO):
        raise ErroNegocio("Isto não é um código de instalação. Ele começa com WILL1-.")
    miolo = limpo[len(PREFIXO):]
    if len(miolo) > 1000:
        raise ErroNegocio("Código de instalação inválido.")
    try:
        dados = json.loads(base64.urlsafe_b64decode(miolo + "=" * (-len(miolo) % 4)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ErroNegocio("Código de instalação incompleto ou danificado. Copie de novo, inteiro.") from None
    if not isinstance(dados, dict):
        raise ErroNegocio("Código de instalação inválido.")
    url, chave, token = dados.get("u"), dados.get("l"), dados.get("t")
    if not _url_valida(url) or not isinstance(chave, str) or not CHAVE.fullmatch(chave) \
            or not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise ErroNegocio("Código de instalação inválido. Gere um novo na central do fornecedor.")
    return {"url": url.rstrip("/"), "chave": chave, "token": token}
