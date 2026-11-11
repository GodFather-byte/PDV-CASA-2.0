"""Busca na nuvem a liberação de senha que o fornecedor assinou na central (caixa com internet)."""
from __future__ import annotations


def disponivel(banco) -> bool:
    return bool(banco.cfg("api_url").strip() and banco.cfg("api_token").strip())


def buscar_liberacao(banco, pedido: str, http=None) -> str | None:
    """O código de liberação do `pedido`, ou None se o fornecedor ainda não liberou. RuntimeError sem conexão."""
    from src.sync.painel_envio import _base_nuvem
    if not disponivel(banco):
        return None
    if http is None:
        import requests as http
    try:
        resposta = http.get(f"{_base_nuvem(banco.cfg('api_url'))}/v1/recuperacao-senha", params={"pedido": pedido},
                            headers={"Authorization": f"Bearer {banco.cfg('api_token').strip()}"}, timeout=(4, 8))
    except OSError as erro:
        raise RuntimeError("Sem conexão com a nuvem. Cole o código que o fornecedor enviar.") from erro
    if resposta.status_code == 404:
        return None
    if resposta.status_code != 200:
        raise RuntimeError(f"A nuvem respondeu HTTP {resposta.status_code}. Cole o código que o fornecedor enviar.")
    dados = resposta.json()
    codigo = dados.get("codigo") if isinstance(dados, dict) else None
    return codigo if isinstance(codigo, str) and codigo else None
