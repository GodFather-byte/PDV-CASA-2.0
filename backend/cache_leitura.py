"""Cache em memória das leituras que o celular repete (painel e cardápio).

Um acerto devolve o JSON sem abrir sessão. Assim várias consultas em menos de um minuto não
acordam o Neon. O envio do caixa (venda, cardápio, porteiro) esvazia o cache: a leitura seguinte
vê o que acabou de subir.
"""
from __future__ import annotations

import json
import threading
import time

from starlette.responses import JSONResponse, Response

TTL_SEG = 45

CAMINHOS = {
    "/v1/painel/resumo",
    "/v1/painel/periodo",
    "/v1/painel/produtos",
    "/v1/painel/vendas",
    "/v1/painel/historico",
    "/v1/cardapio",
    "/v1/porteiro/abertas",
    "/porteiro/api/abertas",
}

INVALIDA = {
    "/v1/painel/envio",
    "/v1/cardapio/envio",
    "/v1/porteiro/retrato",
}

_trava = threading.Lock()
_itens: dict[tuple, tuple[float, dict]] = {}


def obter(chave: tuple):
    agora = time.monotonic()
    with _trava:
        achado = _itens.get(chave)
        if achado is None:
            return None
        quando, valor = achado
        if agora - quando > TTL_SEG:
            _itens.pop(chave, None)
            return None
        return valor


def guardar(chave: tuple, valor: dict) -> None:
    with _trava:
        _itens[chave] = (time.monotonic(), valor)


def limpar() -> None:
    with _trava:
        _itens.clear()


def _leitura_repetida(request) -> bool:
    """Só o celular manda este cabeçalho. Os testes e um logout recente passam direto no banco."""
    return request.headers.get("x-pdv-leitura") == "1"


def _chave(request) -> tuple:
    # O preço do cardápio depende do relógio (happy hour). A hora entra na chave para não
    # servir o preço da tarde à noite; dentro do mesmo minuto as consultas repetidas não acordam o banco.
    hora = ""
    if request.url.path == "/v1/cardapio":
        from backend import cardapio as cardapio_mod
        hora = cardapio_mod.agora_local().strftime("%Y%m%d%H%M")
    return (request.url.path, request.headers.get("authorization", ""), request.url.query, hora)


async def tratar(request, call_next):
    caminho = request.url.path
    if request.method == "GET" and caminho in CAMINHOS and _leitura_repetida(request):
        chave = _chave(request)
        hit = obter(chave)
        if hit is not None:
            return JSONResponse(hit)
        resposta = await call_next(request)
        if resposta.status_code != 200:
            return resposta
        corpo = b""
        async for parte in resposta.body_iterator:
            corpo += parte if isinstance(parte, (bytes, bytearray)) else parte.encode("utf-8")
        try:
            dados = json.loads(corpo)
        except json.JSONDecodeError:
            return Response(content=corpo, status_code=200, media_type=resposta.media_type,
                            headers=dict(resposta.headers))
        if isinstance(dados, dict):
            guardar(chave, dados)
            return JSONResponse(dados)
        return Response(content=corpo, status_code=200, media_type="application/json")
    resposta = await call_next(request)
    if request.method == "POST" and caminho in INVALIDA and resposta.status_code == 200:
        limpar()
    return resposta
