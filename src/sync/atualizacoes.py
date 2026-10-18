"""Aviso de versão nova do PDV: pergunta à nuvem (GET /v1/atualizacoes, com o token da loja) se há versão mais nova
publicada e guarda a resposta no banco. A tela principal mostra o aviso a partir do que ficou guardado, sem esperar a rede.

Nada é instalado sozinho: um update que falhasse no meio do expediente pararia o caixa. O aviso traz as notas e o link,
e o dono atualiza na hora certa. Versão crítica (correção de dinheiro ou de dados) não pode ser dispensada.
"""
from __future__ import annotations

import json
import logging

from src.core import formatacao as fmt
from src.versao import VERSAO, mais_nova, valida

log = logging.getLogger("pdv.atualizacoes")

INTERVALO_HORAS = 6           # a consulta é leve, mas não precisa ser a cada rodada da sincronização
CHAVE_RESPOSTA = "atualizacao_resposta"
CHAVE_CONSULTA = "atualizacao_consultada_em"
CHAVE_DISPENSADA = "atualizacao_dispensada"


def url_atualizacoes(api_url: str) -> str:
    """O endereço configurado é o de envio (.../v1/sincronizar); o das atualizações fica ao lado (.../v1/atualizacoes)."""
    base = (api_url or "").strip().rstrip("/")
    if base.endswith("/v1/sincronizar"):
        base = base[: -len("/v1/sincronizar")]
    return f"{base}/v1/atualizacoes"


def consultar(api_url: str, token: str, http=None, versao: str = VERSAO) -> dict | None:
    """Só a parte de rede (pode rodar fora da thread da tela). Devolve a resposta da nuvem ou None se não deu."""
    if not (api_url or "").strip() or not (token or "").strip():
        return None
    if http is None:
        try:
            import requests as http
        except ImportError:
            return None
    try:
        r = http.get(url_atualizacoes(api_url), params={"versao": versao},
                     headers={"Authorization": f"Bearer {token.strip()}"}, timeout=(3, 10))
        if r.status_code != 200:
            log.info("Consulta de atualizações: HTTP %s.", r.status_code)
            return None
        dados = r.json()
    except (OSError, ValueError) as e:            # sem rede ou resposta ilegível: tenta na próxima vez
        log.info("Consulta de atualizações falhou: %s", e)
        return None
    return dados if isinstance(dados, dict) and isinstance(dados.get("versoes"), list) else None


def gravar(banco, dados: dict | None) -> None:
    """Guarda a resposta (na thread do banco). Sem resposta, só não mexe no que já estava guardado."""
    banco.cfg_set(CHAVE_CONSULTA, fmt.agora())
    if dados is not None:
        banco.cfg_set(CHAVE_RESPOSTA, json.dumps(dados, ensure_ascii=False))


def precisa_consultar(banco) -> bool:
    ultima = banco.cfg(CHAVE_CONSULTA)
    return not ultima or fmt.minutos_entre(ultima) >= INTERVALO_HORAS * 60 or fmt.minutos_entre(ultima) < 0


def verificar(banco, http=None, forcar: bool = False) -> dict | None:
    """Consulta (se já passou o intervalo) e devolve o aviso pendente. Usado pela sincronização, que tem o próprio banco."""
    if forcar or precisa_consultar(banco):
        gravar(banco, consultar(banco.cfg("api_url"), banco.cfg("api_token"), http))
    return pendente(banco)


def pendente(banco, versao: str = VERSAO) -> dict | None:
    """O aviso a mostrar agora, ou None. Some sozinho quando o PDV é atualizado (a versão instalada alcança a anunciada)
    e quando o dono dispensa uma versão que não é crítica."""
    try:
        dados = json.loads(banco.cfg(CHAVE_RESPOSTA) or "null")
    except ValueError:
        return None
    if not isinstance(dados, dict):
        return None
    versoes = [v for v in dados.get("versoes") or []
               if isinstance(v, dict) and valida(str(v.get("versao", ""))) and mais_nova(v["versao"], versao)]
    if not versoes:
        return None
    ultima = versoes[0]["versao"]
    critica = any(v.get("critica") for v in versoes)
    if not critica and banco.cfg(CHAVE_DISPENSADA) == ultima:
        return None
    return {"ultima": ultima, "critica": critica, "versoes": versoes, "url_download": dados.get("url_download"),
            "versao_instalada": versao}


def dispensar(banco, aviso: dict) -> None:
    """'Não avisar desta versão'. Uma versão crítica não pode ser dispensada; uma versão mais nova volta a avisar."""
    if not aviso.get("critica"):
        banco.cfg_set(CHAVE_DISPENSADA, aviso["ultima"])
