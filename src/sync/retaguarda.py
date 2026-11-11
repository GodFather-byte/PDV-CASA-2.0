"""Retaguarda na nuvem, lado da rede: sobe o espelho da loja e busca os comandos do dono e do fornecedor.

O caixa só usa a rede quando há o que fazer: o espelho sobe quando alguma seção mudou (compara a impressão digital
com a última enviada), e os comandos descem quando a nuvem avisou que há comando esperando (`retaguarda_pendentes`
na resposta do envio do painel ou do próprio espelho). Assim o banco da nuvem não é acordado à toa.
Usa o endereço e o token da loja do painel do dono. Erro de rede vira RuntimeError; a próxima rodada tenta de novo.
"""
from __future__ import annotations

import json

from src.controllers.retaguarda_controller import CHAVE_LIGADA, RetaguardaController

CHAVE_AVISO = "retaguarda_na_nuvem"          # "S" quando a nuvem disse que há comando para buscar
CHAVE_ENVIADO = "retaguarda_espelho_enviado"  # JSON {seção: impressão digital} do que a nuvem já tem
MAXIMO_LOTES = 10
LIMITE_SECAO_BYTES = 6 * 1024 * 1024          # uma seção maior que isto não sobe (a nuvem recusaria)


def ligado(banco) -> bool:
    from src.sync import painel_envio
    return banco.cfg_bool(CHAVE_LIGADA, False) and painel_envio.ligado(banco)


def anotar_resposta(banco, resposta: dict) -> None:
    """Chamado a cada resposta da nuvem que pode trazer o aviso: guarda que há comando esperando."""
    try:
        if int(resposta.get("retaguarda_pendentes") or 0) > 0 and banco.cfg(CHAVE_AVISO) != "S":
            banco.cfg_set(CHAVE_AVISO, "S")
    except (TypeError, ValueError, AttributeError):
        pass


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
            resposta = http.post(url, json=corpo or {}, headers=cabecalho, timeout=(5, 60))
    except OSError as e:
        raise RuntimeError("Retaguarda: sem conexão com a nuvem.") from e
    if resposta.status_code == 404:
        raise RuntimeError("Retaguarda: a nuvem desta loja ainda não tem este recurso.")
    if resposta.status_code != 200:
        raise RuntimeError(f"Retaguarda: a nuvem respondeu HTTP {resposta.status_code}.")
    dados = resposta.json()
    if not isinstance(dados, dict):
        raise RuntimeError("Retaguarda: resposta inválida da nuvem.")
    return dados


def _enviados(banco) -> dict:
    try:
        dados = json.loads(banco.cfg(CHAVE_ENVIADO) or "{}")
        return dados if isinstance(dados, dict) else {}
    except ValueError:
        return {}


def enviar_espelho(banco, http=None, forcar: bool = False) -> int:
    """Sobe as seções do espelho que mudaram desde o último envio. Devolve quantas subiram."""
    controle = RetaguardaController(banco)
    secoes = controle.espelho()
    digitais = {nome: controle.resumo_secao(dados) for nome, dados in secoes.items()}
    enviados = {} if forcar else _enviados(banco)
    mudaram = [n for n in secoes if enviados.get(n) != digitais[n]]
    sumiram = [n for n in enviados if n not in secoes]
    if not mudaram and not sumiram:
        return 0
    subiram = 0
    # Uma seção por chamada: o cadastro de produtos de uma loja grande não divide o limite com os outros.
    for nome in mudaram:
        texto = json.dumps(secoes[nome], ensure_ascii=False, separators=(",", ":"), default=str)
        if len(texto.encode("utf-8")) > LIMITE_SECAO_BYTES:
            continue
        resposta = _pedir(banco, "POST", "/v1/retaguarda/espelho", http,
                          {"secao": nome, "digital": digitais[nome], "dados": secoes[nome]})
        anotar_resposta(banco, resposta)
        enviados[nome] = digitais[nome]
        subiram += 1
    if sumiram:
        _pedir(banco, "POST", "/v1/retaguarda/espelho", http, {"remover": sumiram})
        for nome in sumiram:
            enviados.pop(nome, None)
    banco.cfg_set(CHAVE_ENVIADO, json.dumps(enviados, separators=(",", ":")))
    return subiram


def baixar_e_aplicar(banco, http=None) -> int:
    """Busca os comandos que esperam o caixa, aplica cada um e conta o resultado à nuvem. Devolve quantos aplicou."""
    controle = RetaguardaController(banco)
    feitos = 0
    for _ in range(MAXIMO_LOTES):
        dados = _pedir(banco, "GET", "/v1/retaguarda/comandos", http)
        comandos = [c for c in (dados.get("comandos") or []) if isinstance(c, dict)]
        if not comandos:
            break
        for comando in comandos:
            controle.aplicar(comando)
            feitos += 1
        empurrar_resultados(banco, http)
        if not int(dados.get("restantes") or 0):
            break
    banco.cfg_set(CHAVE_AVISO, "N")
    return feitos


def empurrar_resultados(banco, http=None) -> int:
    """Conta à nuvem o que foi aplicado ou recusado e ela ainda não confirmou."""
    linhas = banco.todos("SELECT id, situacao, detalhe, novo_id FROM retaguarda_comandos WHERE aviso_ok = 0 LIMIT 100")
    if not linhas:
        return 0
    resposta = _pedir(banco, "POST", "/v1/retaguarda/confirmar", http, {"resultados": [
        {"id": l["id"], "situacao": l["situacao"], "detalhe": l["detalhe"] or "", "novo_id": l["novo_id"]} for l in linhas]})
    confirmados = [i for i in (resposta.get("confirmados") or []) if type(i) is int]
    for ident in confirmados:
        banco.executar("UPDATE retaguarda_comandos SET aviso_ok = 1 WHERE id = ?", (ident,))
    return len(confirmados)


def ha_resultado_a_contar(banco) -> bool:
    return bool(banco.valor("SELECT 1 FROM retaguarda_comandos WHERE aviso_ok = 0 LIMIT 1"))


def sincronizar(banco, http=None, forcar: bool = False) -> dict | None:
    """Uma rodada: aplica os comandos novos, conta os resultados e sobe o espelho que mudou.
    Devolve None com a retaguarda desligada (ou o painel do dono desligado)."""
    if not ligado(banco):
        return None
    aplicados = baixar_e_aplicar(banco, http) if forcar or banco.cfg(CHAVE_AVISO) == "S" else 0
    avisados = empurrar_resultados(banco, http) if ha_resultado_a_contar(banco) else 0
    subiram = enviar_espelho(banco, http, forcar=forcar)
    if banco.cfg(CHAVE_AVISO) == "S":           # o envio do espelho avisou de comando novo: aplica já, sem esperar
        aplicados += baixar_e_aplicar(banco, http)
        subiram += enviar_espelho(banco, http)
    return {"aplicados": aplicados, "avisados": avisados, "secoes": subiram}
