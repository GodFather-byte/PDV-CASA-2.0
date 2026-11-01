"""Estado local da entrega: não confunde uma falha da API com prova de ausência de internet no computador."""
from datetime import datetime

from src.core import formatacao as fmt
from src.sync import painel_envio, devolucoes_envio


def situacao(banco) -> dict:
    vendas = painel_envio.pendentes(banco)
    devolucoes = devolucoes_envio.pendentes(banco)
    ultimo = banco.cfg(painel_envio.CHAVE_ULTIMO_ENVIO)
    erro = banco.cfg(painel_envio.CHAVE_ULTIMO_ERRO)
    try:
        atraso = max(int((fmt.agora_dt() - datetime.strptime(ultimo, "%Y-%m-%d %H:%M:%S")).total_seconds()), 0)
    except ValueError:
        atraso = None
    if not banco.cfg_bool("painel_dono"):
        estado, texto = "desligado", "Envio do painel desligado"
    elif not painel_envio.ligado(banco):
        estado, texto = "nao_configurado", "Configure o endereço e o token da nuvem"
    elif erro:
        estado, texto = "falha", "Falha na comunicação com a nuvem; dados preservados no caixa"
    elif not ultimo:
        estado, texto = "aguardando", "Aguardando a primeira confirmação da nuvem"
    elif atraso is None or atraso > max(90, 3 * (5 if banco.cfg_bool("sync_quase_tempo_real") else banco.cfg_int("sync_intervalo_seg", 60))):
        estado, texto = "atrasado", "Envio atrasado; confira a conexão e o serviço de sincronização"
    elif vendas or devolucoes:
        estado, texto = "pendente", "Aguardando envio dos registros pendentes"
    else:
        estado, texto = "em_dia", "Nuvem em dia"
    return {"estado": estado, "texto": texto, "vendas_pendentes": vendas, "devolucoes_pendentes": devolucoes,
            "ultimo_envio": ultimo, "atraso_seg": atraso, "erro": erro}
