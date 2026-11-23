"""Insta-BDelivery: a vitrine de delivery com atendente de IA, ligada ao caixa (Will Adega e Will Restaurante).

O Insta-BDelivery fala o mesmo contrato do cardápio da nuvem (`/v1/cardapio/envio`, `/v1/pedidos-online`), então o caixa
só precisa saber o endereço e a chave (Configurações > Nuvem). Os dois canais convivem: a nuvem segue com o cardápio por
QR e o pedido da mesa; o Insta-BDelivery fica com a entrega e a retirada.

Os pedidos dos dois canais têm numeração própria. Para não se confundirem no caixa, o pedido do Insta-BDelivery leva
`canal = "insta"` e um `id` negativo (menos o número dele); é esse `id` que fica em `vendas.pedido_online_id`.
"""
from __future__ import annotations

CANAL = "insta"
CHAVE_URL = "instab_url"
CHAVE_TOKEN = "instab_token"
CHAVE_HASH = "instab_cardapio_hash"


def acesso(banco) -> tuple[str, str]:
    """Endereço base (sem a barra final) e chave da loja."""
    return (banco.cfg(CHAVE_URL) or "").strip().rstrip("/"), (banco.cfg(CHAVE_TOKEN) or "").strip()


def hash_config(banco) -> str:
    """O que o caixa já tem (mesmo cálculo de backend/insta.hash_config); vazio sem configuração."""
    import hashlib
    base, token = acesso(banco)
    return hashlib.sha256(f"{base}|{token}".encode("utf-8")).hexdigest() if base and token else ""


def anotar_resposta(banco, dados: dict) -> bool:
    """A central cadastrou (ou trocou) o Insta-BDelivery desta loja: grava endereço e chave. Devolve se mudou."""
    novo = dados.get("insta")
    if not isinstance(novo, dict):
        return False
    url, token = str(novo.get("url") or "").strip().rstrip("/"), str(novo.get("token") or "").strip()
    if not url.startswith("https://") or not token.startswith("ibd_") or len(url) > 200 or len(token) > 100:
        return False
    banco.cfg_set(CHAVE_URL, url)
    banco.cfg_set(CHAVE_TOKEN, token)
    banco.log("insta_bdelivery", f"configurado pela central: {url}", None)
    return True


def configurado(banco) -> bool:
    base, token = acesso(banco)
    return bool(base and token)


def do_insta(pedido_id) -> bool:
    return int(pedido_id) < 0


def numero_remoto(pedido_id) -> int:
    """O número que o Insta-BDelivery conhece, a partir do `id` guardado no caixa."""
    return -int(pedido_id)


def normalizar(pedido: dict) -> dict:
    """Marca o canal e troca o `id` pelo negativo do número, que não colide com os pedidos da nuvem."""
    return {**pedido, "canal": CANAL, "id": -int(pedido["numero"])}
