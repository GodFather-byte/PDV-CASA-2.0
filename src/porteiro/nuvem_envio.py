"""Manda o retrato das comandas abertas para a nuvem, para o porteiro consultar pelo 4G.

O painel do dono só recebe venda fechada. A portaria precisa do que ainda está aberto. O corpo é
pequeno (só as posições abertas e o hash do PIN, nunca o PIN). A mesma foto não sai de novo:
isso acordaria o Neon. O celular mostra a hora do último envio; o botão "Atualizar agora" ou o
fechamento do turno pede um envio na hora. No Wi-Fi do caixa a lista continua ao vivo.
"""
from __future__ import annotations

import json
import logging
import time
from urllib.parse import quote

from src.core import formatacao as fmt
from src.porteiro.consulta import retrato
from src.porteiro.servico import porta_configurada, url_do_qr, urls_publicas

log = logging.getLogger("pdv.porteiro")

ESPERA_MUDANCA = 8          # segundos: um lançamento atrás do outro vira um envio só
ESPERA_FALHA_MAX = 300

_estado = {"quando": 0.0, "assinatura": "", "falhas": 0}


def zerar_envio() -> None:
    _estado.update(quando=0.0, assinatura="", falhas=0)


def _base(api_url: str) -> str:
    base = (api_url or "").strip().rstrip("/")
    if base.endswith("/v1/sincronizar"):
        base = base[: -len("/v1/sincronizar")]
    return base


def url_retrato(api_url: str) -> str:
    return f"{_base(api_url)}/v1/porteiro/retrato"


def url_da_pagina(api_url: str) -> str:
    base = _base(api_url)
    return f"{base}/porteiro" if base else ""


def endereco_4g(banco) -> str:
    """Linha para a tela do caixa. A chave da loja identifica a casa; não é o token."""
    pagina = url_da_pagina(banco.cfg("api_url"))
    chave = (banco.cfg("chave_loja") or "").strip()
    if not pagina or not chave:
        return "Pelo 4G: configure o endereço da nuvem e a chave da loja (Configurações > Nuvem)."
    return f"Pelo 4G: {pagina}/?loja={quote(chave)}"


def ligado(banco) -> bool:
    return (banco.cfg_bool("porteiro_ativo", False) and bool((banco.cfg("porteiro_pin_hash") or "").strip())
            and bool(banco.cfg("api_url").strip()) and bool(banco.cfg("api_token").strip())
            and banco.cfg_bool("usar_mesas", True))


def montar(banco) -> dict:
    from src.sync.painel_envio import id_do_caixa
    porta = porta_configurada(banco.cfg("porteiro_porta", "8765"))
    url = url_do_qr(urls_publicas(porta)) if porta else ""
    foto = retrato(banco)
    return {
        "momento": fmt.agora(),
        "pin_hash": banco.cfg("porteiro_pin_hash"),
        "terminal_id": id_do_caixa(banco),
        "url_lan": url,
        "posicao_padrao": foto["posicao_padrao"],
        "posicoes": foto["posicoes"],
    }


def _assinatura(corpo: dict) -> str:
    return json.dumps({"pin": corpo.get("pin_hash"), "url": corpo.get("url_lan"),
                        "padrao": corpo.get("posicao_padrao"), "posicoes": corpo.get("posicoes")},
                       ensure_ascii=False, sort_keys=True, default=str)


def precisa_enviar(banco) -> bool:
    """A foto das comandas mudou desde o último envio. Parada, não renova o horário: isso acordaria o Neon."""
    if not ligado(banco):
        return False
    if not _estado["quando"]:
        return True
    return _assinatura(montar(banco)) != _estado["assinatura"]


def enviar_se_preciso(banco, http=None, relogio=None, forcar: bool = False) -> dict | None:
    """Envia se a foto mudou. Sem mudança não chama a rede, mesmo que o último envio seja antigo.
    `forcar` é o fechamento do turno ou o botão do celular."""
    if not ligado(banco):
        return None
    relogio = relogio or time.monotonic
    corpo = montar(banco)
    agora = relogio()
    assinatura = _assinatura(corpo)
    mudou = assinatura != _estado["assinatura"]
    desde = agora - _estado["quando"]
    if not forcar and _estado["quando"]:
        if _estado["falhas"]:
            if desde < min(30 * 2 ** (_estado["falhas"] - 1), ESPERA_FALHA_MAX):
                return {"enviado": False}
        elif not mudou:
            return {"enviado": False}
        elif desde < (5 if banco.cfg_bool("sync_quase_tempo_real") else ESPERA_MUDANCA):
            return {"enviado": False}
    try:
        _post(banco, corpo, http)
    except Exception:
        _estado["quando"] = agora
        _estado["falhas"] = min(_estado["falhas"] + 1, 6)
        raise
    _estado.update(quando=agora, assinatura=assinatura, falhas=0)
    log.info("Porteiro: %d comanda(s) aberta(s) enviada(s) à nuvem.", len(corpo["posicoes"]))
    return {"enviado": True, "posicoes": len(corpo["posicoes"])}


def _post(banco, corpo: dict, http) -> None:
    if http is None:
        import requests as http
    url = url_retrato(banco.cfg("api_url"))
    cabecalhos = {"Authorization": f"Bearer {banco.cfg('api_token').strip()}"}
    try:
        resposta = http.post(url, json=corpo, headers=cabecalhos, timeout=(5, 20))
    except OSError as exc:
        log.warning("Porteiro sem ligação com a nuvem: %s", exc)
        raise
    if getattr(resposta, "status_code", 0) != 200:
        log.warning("Porteiro: a nuvem respondeu HTTP %s.", getattr(resposta, "status_code", "?"))
        raise RuntimeError(f"Nuvem do porteiro: HTTP {getattr(resposta, 'status_code', '?')}.")
