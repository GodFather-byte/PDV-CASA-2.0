"""Cabeçalhos de segurança e o salto de HTTP para HTTPS atrás do proxy.

O Cloudflare e o Render entregam a visita em HTTPS. Se o processo ainda vir
X-Forwarded-Proto: http, a página vai para o mesmo caminho em https. Localhost
e o cliente de teste não redirecionam.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

_SEM_REDIRECT = {"localhost", "127.0.0.1", "testserver"}
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "connect-src 'self'; font-src 'self'; worker-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; object-src 'none'; "
    "form-action 'self' https://www.mercadopago.com https://www.mercadopago.com.br "
    "https://sandbox.mercadopago.com.br"
)


def _proto(request: Request) -> str:
    bruto = request.headers.get("x-forwarded-proto") or ""
    return bruto.split(",")[0].strip().lower()


def _host(request: Request) -> str:
    bruto = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    return bruto.split(",")[0].strip()


def destino_https(request: Request) -> str | None:
    """URL https da mesma visita, ou None se não há o que redirecionar."""
    if _proto(request) != "http":
        return None
    if request.method not in ("GET", "HEAD"):
        return None
    host = _host(request)
    nome = host.split(":")[0].lower()
    if not nome or nome in _SEM_REDIRECT:
        return None
    if urlsplit("https://" + host).hostname is None:
        return None
    consulta = request.url.query
    if any(ord(c) < 32 or c in " \\" for c in consulta):
        consulta = ""
    return "https://" + host + request.url.path + (("?" + consulta) if consulta else "")


def instalar(app: FastAPI) -> None:
    @app.middleware("http")
    async def cabecalhos_e_https(request: Request, call_next):
        destino = destino_https(request)
        if destino is not None:
            resposta = RedirectResponse(destino, status_code=308)
        elif _proto(request) == "http" and request.method not in ("GET", "HEAD"):
            nome = _host(request).split(":")[0].lower()
            if nome and nome not in _SEM_REDIRECT:
                from fastapi.responses import JSONResponse
                resposta = JSONResponse({"detail": "Use HTTPS."}, status_code=400)
            else:
                resposta = await call_next(request)
        else:
            resposta = await call_next(request)
        if "x-content-type-options" not in resposta.headers:
            resposta.headers["X-Content-Type-Options"] = "nosniff"
        if "x-frame-options" not in resposta.headers:
            resposta.headers["X-Frame-Options"] = "DENY"
        if "referrer-policy" not in resposta.headers:
            resposta.headers["Referrer-Policy"] = "no-referrer"
        if "permissions-policy" not in resposta.headers:
            resposta.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        if "content-security-policy" not in resposta.headers:
            resposta.headers["Content-Security-Policy"] = _CSP
        seguro = request.url.scheme == "https" or _proto(request) == "https"
        if seguro and "strict-transport-security" not in resposta.headers:
            resposta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return resposta
