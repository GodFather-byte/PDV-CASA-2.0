"""Notas de compra do painel do dono: o caixa busca na nuvem o XML que o dono subiu e devolve o desfecho.

A nuvem avisa na resposta do envio do painel (`notas_pendentes`) quando há nota esperando; só então o caixa faz a
busca, para não acordar o banco da nuvem à toa. O que desce fica em `notas_dono` até a conferência na tela de NF-e.
Usa o endereço e o token da loja do painel do dono. Erro de rede vira RuntimeError; a próxima rodada tenta de novo.
"""
from __future__ import annotations

import base64
import binascii

from src.core import formatacao as fmt

CHAVE_AVISO = "notas_dono_na_nuvem"         # "S" quando a nuvem disse que há nota para buscar
MAXIMO_LOTES = 10
LIMITE_XML_BYTES = 2 * 1024 * 1024


def ligado(banco) -> bool:
    from src.sync import painel_envio
    return painel_envio.ligado(banco)


def anotar_resposta(banco, resposta: dict) -> None:
    """Chamado a cada envio do painel que deu certo: guarda o aviso de nota nova (sobrevive a fechar o PDV)."""
    try:
        if int(resposta.get("notas_pendentes") or 0) > 0 and banco.cfg(CHAVE_AVISO) != "S":
            banco.cfg_set(CHAVE_AVISO, "S")
    except (TypeError, ValueError, AttributeError):
        pass


def ha_o_que_fazer(banco) -> bool:
    return ligado(banco) and (banco.cfg(CHAVE_AVISO) == "S" or bool(banco.valor(
        "SELECT 1 FROM notas_dono WHERE aviso_ok = 0 LIMIT 1")))


def _pedir(banco, metodo: str, caminho: str, http=None, corpo: dict | None = None) -> dict:
    from src.sync.painel_envio import _base_nuvem
    if http is None:
        import requests as http
    url = f"{_base_nuvem(banco.cfg('api_url'))}{caminho}"
    cabecalho = {"Authorization": f"Bearer {banco.cfg('api_token').strip()}"}
    try:
        if metodo == "GET":
            resposta = http.get(url, headers=cabecalho, timeout=(5, 30))
        else:
            resposta = http.post(url, json=corpo or {}, headers=cabecalho, timeout=(5, 30))
    except OSError as e:
        raise RuntimeError("Notas do dono: sem conexão com a nuvem.") from e
    if resposta.status_code == 404:
        raise RuntimeError("Notas do dono: a nuvem desta loja ainda não tem este recurso.")
    if resposta.status_code != 200:
        raise RuntimeError(f"Notas do dono: a nuvem respondeu HTTP {resposta.status_code}.")
    dados = resposta.json()
    if not isinstance(dados, dict):
        raise RuntimeError("Notas do dono: resposta inválida da nuvem.")
    return dados


def _guardar(banco, nota: dict) -> bool:
    """Grava a nota que desceu. Devolve True se ficou guardada (ou já estava): só então a nuvem é avisada."""
    try:
        ident = int(nota["id"])
        xml = base64.b64decode(str(nota.get("conteudo_b64") or ""), validate=True)
    except (KeyError, TypeError, ValueError, binascii.Error):
        return False
    if not xml or len(xml) > LIMITE_XML_BYTES:
        return False
    if banco.valor("SELECT 1 FROM notas_dono WHERE id = ?", (ident,)):
        return True
    banco.executar(
        "INSERT INTO notas_dono (id, chave, numero, emitente, arquivo, xml, enviada_em, recebida_em) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ident, str(nota.get("chave") or "")[:64], str(nota.get("numero") or "")[:20],
         str(nota.get("emitente") or "")[:120], str(nota.get("arquivo") or "nota.xml")[:80], xml,
         str(nota.get("enviada_em") or "")[:19] or None, fmt.agora()))
    return True


def baixar(banco, http=None) -> int:
    """Busca as notas pendentes na nuvem e confirma as que guardou. Devolve quantas são novas neste caixa."""
    novas = 0
    for _ in range(MAXIMO_LOTES):
        dados = _pedir(banco, "GET", "/v1/notas-dono", http)
        notas = [n for n in (dados.get("notas") or []) if isinstance(n, dict)]
        guardadas = []
        for nota in notas:
            antes = banco.valor("SELECT 1 FROM notas_dono WHERE id = ?", (nota.get("id"),))
            if _guardar(banco, nota):
                guardadas.append(int(nota["id"]))
                novas += 0 if antes else 1
        if guardadas:
            _pedir(banco, "POST", "/v1/notas-dono/confirmar", http, {"recebidas": guardadas})
        if not guardadas or not int(dados.get("restantes") or 0):
            break
    banco.cfg_set(CHAVE_AVISO, "N")
    return novas


def empurrar_avisos(banco, http=None) -> int:
    """Conta ao painel o desfecho das notas conferidas (lançada ou recusada) que a nuvem ainda não confirmou."""
    linhas = banco.todos("SELECT id, situacao, detalhe FROM notas_dono WHERE aviso_ok = 0 AND situacao <> 'pendente' LIMIT 100")
    if not linhas:
        return 0
    resposta = _pedir(banco, "POST", "/v1/notas-dono/confirmar", http, {"situacoes": [
        {"id": l["id"], "situacao": l["situacao"], "detalhe": l["detalhe"] or ""} for l in linhas]})
    confirmadas = [i for i in (resposta.get("confirmadas") or []) if type(i) is int]
    for ident in confirmadas:
        banco.executar("UPDATE notas_dono SET aviso_ok = 1 WHERE id = ?", (ident,))
    return len(confirmadas)


def sincronizar(banco, http=None, forcar: bool = False) -> dict | None:
    """Uma rodada: desce as notas novas e sobe os desfechos. Sem aviso da nuvem nem desfecho a contar, não usa a rede
    (a não ser com `forcar`, o botão "Buscar agora"). Devolve None com o painel desligado."""
    if not ligado(banco):
        return None
    if not forcar and not ha_o_que_fazer(banco):
        return {"novas": 0, "avisadas": 0}
    from src.controllers.notas_dono_controller import NotasDonoController
    novas = baixar(banco, http) if forcar or banco.cfg(CHAVE_AVISO) == "S" else 0
    NotasDonoController(banco).conciliar()
    return {"novas": novas, "avisadas": empurrar_avisos(banco, http)}
