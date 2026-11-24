"""Pedido online (Will Adega): o caixa busca na nuvem os pedidos novos e responde (aceitar ou recusar).

Usa o mesmo endereço e token da loja do cardápio digital. Sem nuvem, sem pedido online ou fora do Will Adega: nada.
Erro de rede vira RuntimeError com a mensagem para a tela; quem chama decide (a busca automática só tenta de novo).
"""
from __future__ import annotations

from src.sync import insta_bdelivery as insta
from src.sync.cardapio_envio import _base_nuvem


def _edicao_pede(banco) -> bool:
    from src.core import edicao
    return edicao.atual().chave in {"willadega", "willrestaurante"} and banco.cfg_bool("pedido_online", False)


def nuvem_ligada(banco) -> bool:
    """O pedido do cardápio da nuvem (QR, mesa)."""
    return (_edicao_pede(banco) and banco.cfg_bool("cardapio_digital", False) and bool(banco.cfg("api_url").strip())
            and bool(banco.cfg("api_token").strip()))


def insta_ligado(banco) -> bool:
    """O pedido da vitrine do Insta-BDelivery (entrega e retirada)."""
    return _edicao_pede(banco) and insta.configurado(banco)


def ligado(banco) -> bool:
    return nuvem_ligada(banco) or insta_ligado(banco)


def acesso(banco) -> tuple[str, str]:
    """Endereço base e token da loja (lidos na thread da tela: a busca em segundo plano não toca no banco)."""
    return _base_nuvem(banco.cfg("api_url")), banco.cfg("api_token").strip()


def _pedir(base: str, token: str, metodo: str, caminho: str, http=None, corpo: dict | None = None) -> dict:
    if http is None:
        import requests as http
    url = f"{base}{caminho}"
    from src.core.endereco_nuvem import autorizar
    cabecalho = autorizar(url, token)
    if cabecalho is None:
        raise RuntimeError("Pedido online: o endereço da nuvem precisa ser HTTPS.")
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


def fontes(banco) -> list[tuple[str, str, str]]:
    """De onde vêm os pedidos: (canal, endereço, chave). Lido na thread da tela; a busca em si só usa a rede."""
    lista = []
    if nuvem_ligada(banco):
        lista.append(("", *acesso(banco)))
    if insta_ligado(banco):
        lista.append((insta.CANAL, *insta.acesso(banco)))
    return lista


def consultar_fontes(origens: list[tuple[str, str, str]], http=None) -> tuple[list[dict], str]:
    """Só rede. Junta os pedidos dos canais; um canal fora do ar não esconde os pedidos do outro."""
    pedidos, erros = [], []
    for canal, base, token in origens:
        try:
            lista = consultar(base, token, http)
            pedidos.extend(insta.normalizar(p) for p in lista) if canal == insta.CANAL else pedidos.extend(lista)
        except (RuntimeError, KeyError, TypeError, ValueError) as e:
            erros.append(str(e) if isinstance(e, RuntimeError) else "Pedido online: resposta inesperada do Insta-BDelivery.")
    return pedidos, " ".join(erros)


def novos(banco, http=None) -> list[dict]:
    """Pedidos que ainda esperam o caixa (mais antigo primeiro, por canal)."""
    if not ligado(banco):
        return []
    pedidos, erro = consultar_fontes(fontes(banco), http)
    if erro and not pedidos:
        raise RuntimeError(erro)
    return pedidos


def _destino(banco, pedido_id: int) -> tuple[str, str, int]:
    """Endereço, chave e o número que aquele canal conhece. O `id` negativo é do Insta-BDelivery."""
    if insta.do_insta(pedido_id):
        return (*insta.acesso(banco), insta.numero_remoto(pedido_id))
    return (*acesso(banco), int(pedido_id))


def aceitar(banco, pedido_id: int, http=None) -> None:
    base, token, numero = _destino(banco, pedido_id)
    _pedir(base, token, "POST", f"/v1/pedidos-online/{numero}/aceitar", http)


def recusar(banco, pedido_id: int, motivo: str, http=None) -> None:
    base, token, numero = _destino(banco, pedido_id)
    _pedir(base, token, "POST", f"/v1/pedidos-online/{numero}/recusar", http, {"motivo": motivo})


def atualizar_situacao(banco, pedido_id: int, situacao: str, motivo: str = "", http=None) -> None:
    """saiu, entregue ou cancelado. Repetir a mesma situação é inofensivo."""
    base, token, numero = _destino(banco, pedido_id)
    _pedir(base, token, "POST", f"/v1/pedidos-online/{numero}/situacao", http,
           {"situacao": situacao, "motivo": motivo or ""})


def empurrar_avisos(banco, http=None) -> None:
    """Manda à nuvem o que o caixa já decidiu (aceito, saiu, entregue, cancelado) e ainda não confirmou."""
    if not ligado(banco):
        return
    linhas = banco.todos(
        "SELECT id, pedido_online_id, pedido_online_aviso, motivo_cancelamento FROM vendas "
        "WHERE pedido_online_id IS NOT NULL AND COALESCE(pedido_online_aviso_ok, 1) = 0")
    for linha in linhas:
        aviso = linha["pedido_online_aviso"] or ""
        try:
            if aviso == "aceito":
                aceitar(banco, int(linha["pedido_online_id"]), http)
            elif aviso in ("saiu", "entregue", "cancelado"):
                atualizar_situacao(banco, int(linha["pedido_online_id"]), aviso,
                                   linha["motivo_cancelamento"] or "", http)
            else:
                continue
        except RuntimeError:
            continue
        banco.executar("UPDATE vendas SET pedido_online_aviso_ok = 1 WHERE id = ?", (linha["id"],))

    # Uma mesa recebe vários pedidos: cada confirmação tem sua própria fila durável.
    for linha in banco.todos("SELECT pedido_id, aviso FROM pedidos_mesa_importados WHERE aviso_ok = 0 ORDER BY pedido_id"):
        try:
            aceitar(banco, linha["pedido_id"], http)
            if linha["aviso"] != "aceito":
                atualizar_situacao(banco, linha["pedido_id"], linha["aviso"], http=http)
        except RuntimeError:
            continue
        banco.executar("UPDATE pedidos_mesa_importados SET aviso_ok = 1 WHERE pedido_id = ? AND aviso = ?",
                        (linha["pedido_id"], linha["aviso"]))
