"""Pedido online (Will Adega): o caixa busca na nuvem os pedidos novos e responde (aceitar ou recusar).

Usa o mesmo endereço e token da loja do cardápio digital. Sem nuvem, sem pedido online ou fora do Will Adega: nada.
Erro de rede vira RuntimeError com a mensagem para a tela; quem chama decide (a busca automática só tenta de novo).
"""
from __future__ import annotations

from src.sync.cardapio_envio import _base_nuvem


def ligado(banco) -> bool:
    from src.core import edicao
    return (edicao.atual().chave == "willadega" and banco.cfg_bool("pedido_online", False)
            and banco.cfg_bool("cardapio_digital", False) and bool(banco.cfg("api_url").strip())
            and bool(banco.cfg("api_token").strip()))


def acesso(banco) -> tuple[str, str]:
    """Endereço base e token da loja (lidos na thread da tela: a busca em segundo plano não toca no banco)."""
    return _base_nuvem(banco.cfg("api_url")), banco.cfg("api_token").strip()


def _pedir(base: str, token: str, metodo: str, caminho: str, http=None, corpo: dict | None = None) -> dict:
    if http is None:
        import requests as http
    url = f"{base}{caminho}"
    cabecalho = {"Authorization": f"Bearer {token}"}
    try:
        if metodo == "GET":
            resposta = http.get(url, headers=cabecalho, timeout=(5, 15))
        else:
            resposta = http.post(url, json=corpo or {}, headers=cabecalho, timeout=(5, 15))
    except OSError as e:
        raise RuntimeError(f"Pedido online: sem conexão com a nuvem ({e}).") from e
    if resposta.status_code != 200:
        try:
            detalhe = resposta.json().get("detail")
        except (ValueError, AttributeError):
            detalhe = None
        raise RuntimeError(f"Pedido online: {detalhe or f'a nuvem respondeu HTTP {resposta.status_code}'}.")
    return resposta.json()


def consultar(base: str, token: str, http=None) -> list[dict]:
    """Só rede (pode rodar fora da thread da tela)."""
    return list(_pedir(base, token, "GET", "/v1/pedidos-online", http).get("pedidos") or [])


def novos(banco, http=None) -> list[dict]:
    """Pedidos que ainda esperam o caixa (mais antigo primeiro)."""
    if not ligado(banco):
        return []
    return consultar(*acesso(banco), http)


def aceitar(banco, pedido_id: int, http=None) -> None:
    _pedir(*acesso(banco), "POST", f"/v1/pedidos-online/{int(pedido_id)}/aceitar", http)


def recusar(banco, pedido_id: int, motivo: str, http=None) -> None:
    _pedir(*acesso(banco), "POST", f"/v1/pedidos-online/{int(pedido_id)}/recusar", http, {"motivo": motivo})
