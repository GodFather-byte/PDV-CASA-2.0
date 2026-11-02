"""Quando o caixa fala com a nuvem.

O Neon suspende o compute depois de 5 minutos sem consulta. Por isso o caixa não chama a nuvem
a cada venda: junta o que mudou e manda no máximo a cada `sync_lote_seg` (padrão 15 minutos).
O fechamento do turno e o botão "Atualizar agora" do celular furam essa espera. Sem pendência,
sem expediente para um batimento, ou fora do horário configurado, não há chamada ao banco.

A sondagem do pedido (GET /v1/sync/pedido) é outra coisa: ela só lê a memória do Render e pode
acontecer a cada 20–30 s sem acordar o Neon.
"""
from __future__ import annotations

from src.core import formatacao as fmt

LOTE_PADRAO = 900
LOTE_MIN = 60
LOTE_MAX = 3600
SONDA_SEG = 25
ESPERA_LOCAL = 5
BATIMENTO_SEG = 15 * 60
OCIOSO_MIN = 15
CHAVE_FLUSH = "sync_flush_pedido"
CHAVE_LOTE = "sync_lote_seg"


def lote_seg(banco) -> int:
    try:
        valor = int(banco.cfg_int(CHAVE_LOTE, LOTE_PADRAO))
    except (TypeError, ValueError):
        valor = LOTE_PADRAO
    return min(max(valor, LOTE_MIN), LOTE_MAX)


def lote_minutos(banco) -> int:
    return max(lote_seg(banco) // 60, 1)


def pedir_flush(banco) -> None:
    """O fechamento do turno pede envio imediato. A chave começa com sync_ e não invalida o retrato."""
    banco.cfg_set(CHAVE_FLUSH, fmt.agora())


def flush_pedido(banco) -> bool:
    return bool((banco.cfg(CHAVE_FLUSH) or "").strip())


def url_base(api_url: str) -> str:
    base = (api_url or "").strip().rstrip("/")
    if base.endswith("/v1/sincronizar"):
        base = base[: -len("/v1/sincronizar")]
    return base


def url_pedido(api_url: str) -> str:
    return f"{url_base(api_url)}/v1/sync/pedido"


def url_concluido(api_url: str) -> str:
    return f"{url_base(api_url)}/v1/sync/concluido"


def dentro_do_expediente(banco, agora=None) -> bool:
    """Sem as duas horas, o dia inteiro vale. Com as duas, o intervalo pode cruzar a meia-noite."""
    de = (banco.cfg("sync_expediente_de") or "").strip()
    ate = (banco.cfg("sync_expediente_ate") or "").strip()
    if not de or not ate:
        return True
    try:
        inicio = fmt.para_hora(de)
        fim = fmt.para_hora(ate)
    except ValueError:
        return True
    if not inicio or not fim or inicio == fim:
        return True
    hora = (agora or fmt.agora())[11:16]
    if inicio < fim:
        return inicio <= hora < fim
    return hora >= inicio or hora < fim


def ha_pendencia(banco) -> bool:
    """Mudança local que ainda não subiu. Só lê o SQLite do caixa."""
    from src.sync import cardapio_envio, devolucoes_envio, painel_envio, painel_ritmo
    from src.porteiro import nuvem_envio
    if painel_envio.ligado(banco):
        if painel_envio.pendentes(banco) or devolucoes_envio.pendentes(banco):
            return True
        if painel_ritmo.desatualizado(banco):
            return True
    if cardapio_envio.precisa_enviar(banco):
        return True
    if nuvem_envio.precisa_enviar(banco):
        return True
    from src.core import erros_caixa
    if erros_caixa.pendentes(banco):
        return True
    return False


def ocioso(banco, pendente: bool | None = None) -> bool:
    """Sem fila e sem movimento recente no turno aberto. Aí não há batimento."""
    if pendente if pendente is not None else ha_pendencia(banco):
        return False
    aberto = banco.valor("SELECT COUNT(*) FROM turnos WHERE status = 'aberto'", (), 0)
    if not aberto:
        return True
    ultimo = banco.valor(
        "SELECT MAX(COALESCE(ultimo_lancamento_em, fechada_em, aberta_em)) FROM vendas", (), "") or ""
    if not str(ultimo).strip():
        return True
    try:
        minutos = fmt.minutos_entre(str(ultimo)[:19])
    except ValueError:
        return True
    return minutos < 0 or minutos >= OCIOSO_MIN


def manutencao_devida(banco) -> bool:
    """Licença, aviso de versão e central: cada um já tem o próprio intervalo de horas."""
    from src.atualizacao.cliente import precisa_consultar as programa_precisa
    from src.sync import atualizacoes, licenca_nuvem, ponte
    if not (banco.cfg("api_url") or "").strip():
        return False
    return bool(atualizacoes.precisa_consultar(banco) or licenca_nuvem.precisa(banco)
                or programa_precisa(banco) or (ponte.ativa(banco) and ponte.precisa_rodar(banco)))


def deve_contato(banco, agora: float, ultimo: float, forcar: bool) -> bool:
    """True só quando alguma chamada vai tocar o Neon. A sondagem do pedido fica de fora."""
    if not (banco.cfg("api_url") or "").strip():
        return False
    if forcar:
        return True
    desde = (agora - ultimo) if ultimo else 10 ** 9
    pendente = ha_pendencia(banco)
    if pendente and desde >= lote_seg(banco):
        return True
    if manutencao_devida(banco):
        return True
    if desde >= max(BATIMENTO_SEG, lote_seg(banco)) and dentro_do_expediente(banco) and not ocioso(banco, pendente):
        return True
    return False
