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
    from src.core.endereco_nuvem import autorizar
    url = f"{_base_nuvem(banco.cfg('api_url'))}/v1/recuperacao-senha"
    cabecalho = autorizar(url, banco.cfg("api_token"))
    if cabecalho is None:
        raise RuntimeError("O endereço da nuvem precisa ser HTTPS. Cole o código que o fornecedor enviar.")
    try:
        resposta = http.get(url, params={"pedido": pedido}, headers=cabecalho, timeout=(4, 8))
    except OSError as erro:
        raise RuntimeError("Sem conexão com a nuvem. Cole o código que o fornecedor enviar.") from erro
    if resposta.status_code == 404:
        return None
    if resposta.status_code != 200:
        raise RuntimeError(f"A nuvem respondeu HTTP {resposta.status_code}. Cole o código que o fornecedor enviar.")
    dados = resposta.json()
    codigo = dados.get("codigo") if isinstance(dados, dict) else None
    return codigo if isinstance(codigo, str) and codigo else None
