"""Envia o retrato quando os dados mudam. Sem mudança, não há batimento curto: o Neon dorme.

Um batimento (pedido vazio que só renova o horário) sai no máximo a cada 15 minutos, e só com a
loja em movimento e dentro do expediente. Ociosa ou fora do horário, não sai.
"""
import hashlib
import json
import time
from weakref import WeakKeyDictionary

from src.core import formatacao as fmt
from src.sync import painel_envio, devolucoes_envio

_estados = WeakKeyDictionary()


def desatualizado(banco) -> bool:
    """O retrato local mudou desde o último envio bem-sucedido. Não chama a rede."""
    if not painel_envio.ligado(banco):
        return False
    estado = _estados.get(banco)
    if estado is None:
        return True
    revisao = banco.valor("SELECT revisao FROM painel_revisao WHERE id = 1", (), 0)
    dia = fmt.dia_operacional(None, painel_envio._virada(banco))
    destino = tuple(banco.cfg(c) for c in ("api_url", "api_token", "chave_loja", "sync_quase_tempo_real"))
    return estado["destino"] != destino or estado["revisao"] != revisao or estado["dia"] != dia


def pode_batimento(banco, decorrido: float) -> bool:
    from src.sync.ociosidade import BATIMENTO_SEG, dentro_do_expediente, ocioso
    if decorrido < BATIMENTO_SEG:
        return False
    if not dentro_do_expediente(banco):
        return False
    return not ocioso(banco)


def enviar_se_preciso(banco, http=None, relogio=None, forcar_batimento: bool = False):
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
        elif forcar_batimento or pode_batimento(banco, agora - anterior):
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
