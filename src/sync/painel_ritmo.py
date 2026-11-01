"""Envia mudanças em poucos segundos e mantém a conexão confirmada com batimentos leves."""
import hashlib
import json
import time
from weakref import WeakKeyDictionary

from src.core import formatacao as fmt
from src.sync import painel_envio, devolucoes_envio

BATIMENTO_SEG = 45
_estados = WeakKeyDictionary()


def enviar_se_preciso(banco, http=None, relogio=None):
    if not painel_envio.ligado(banco):
        _estados.pop(banco, None)
        return None
    agora = (relogio or time.monotonic)()
    destino = tuple(banco.cfg(c) for c in ("api_url", "api_token", "chave_loja", "sync_quase_tempo_real"))
    estado = _estados.get(banco)
    revisao = banco.valor("SELECT revisao FROM painel_revisao WHERE id = 1", (), 0)
    dia = fmt.dia_operacional(None, painel_envio._virada(banco))
    assinatura = estado["assinatura"] if estado else None
    foto = None
    if estado is None or estado["destino"] != destino or estado["revisao"] != revisao or estado["dia"] != dia:
        with banco.transacao():
            nova = painel_envio.retrato(banco)
            revisao = banco.valor("SELECT revisao FROM painel_revisao WHERE id = 1", (), 0)
        dados = {k: v for k, v in nova.items() if k not in (
            "momento", "vendas_pendentes_envio", "devolucoes_pendentes_envio")}
        assinatura = hashlib.sha256(json.dumps(dados, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if estado is None or estado["destino"] != destino or assinatura != estado["assinatura"]:
            foto = nova
    vendas = painel_envio.pendentes(banco)
    devolucoes = devolucoes_envio.pendentes(banco)
    anterior = estado["quando"] if estado else 0
    try:
        if foto is not None or vendas or devolucoes:
            resultado = painel_envio.enviar(banco, http, foto=foto)
            confirmado = agora
        elif estado is None or agora - anterior >= BATIMENTO_SEG:
            corpo = {"heartbeat": {"terminal_id": painel_envio.id_do_caixa(banco),
                      "vendas_pendentes_envio": vendas, "devolucoes_pendentes_envio": devolucoes}, "enviado_em": fmt.agora()}
            resposta = painel_envio._postar(banco, corpo, http)
            if resposta.get("heartbeat_confirmado") is not True:
                # Servidor antigo ou limpeza do retrato remoto: volta ao envio completo.
                _estados.pop(banco, None)
                return painel_envio.enviar(banco, http)
            painel_envio.confirmar_sucesso(banco)
            resultado = {"vendas": 0, "lotes": 1}
            confirmado = agora
        else:
            resultado = None
            confirmado = anterior
    except Exception:
        _estados.pop(banco, None)
        raise
    _estados[banco] = {"destino": destino, "revisao": revisao, "dia": dia,
                      "assinatura": assinatura, "quando": confirmado}
    return resultado
