"""Alertas do painel do dono, calculados dos dados que o caixa já mandou.

Não há consulta extra: o resumo que o celular já pede devolve a lista. O badge é a contagem.
Cada item traz o texto pronto para o link do WhatsApp.
"""
from __future__ import annotations

from src.core import formatacao as fmt


def _reais(centavos) -> str:
    return "R$ " + fmt.fmt_num(int(centavos or 0))


def _hora_no_intervalo(hora: str, inicio: str, fim: str) -> bool:
    if not inicio or not fim or inicio == fim:
        return True
    if inicio < fim:
        return inicio <= hora < fim
    return hora >= inicio or hora < fim


def montar(resumo: dict, retrato: dict | None, cfg: dict | None) -> list[dict]:
    """Lista de {tipo, titulo, texto}. Limites em centavos e horas; 0 desliga aquele aviso."""
    cfg = cfg or {}
    retrato = retrato or {}
    vendas = (resumo or {}).get("vendas") or {}
    loja = ((resumo or {}).get("loja") or {}).get("nome") or retrato.get("loja_nome") or "Loja"
    alertas = []

    def acrescentar(tipo: str, titulo: str, detalhe: str) -> None:
        alertas.append({
            "tipo": tipo,
            "titulo": titulo,
            "texto": f"*{loja}*\n{titulo}\n{detalhe}",
        })

    limite_cancel = int(cfg.get("cancelamento_cent") or 0)
    if limite_cancel and int(vendas.get("canceladas_cent") or 0) >= limite_cancel:
        acrescentar("cancelamento", "Cancelamento acima do combinado",
                    f"{int(vendas.get('canceladas') or 0)} cancelamento(s), {_reais(vendas.get('canceladas_cent'))}.")
    limite_desc = int(cfg.get("desconto_cent") or 0)
    if limite_desc and int(vendas.get("desconto_cent") or 0) >= limite_desc:
        acrescentar("desconto", "Desconto acima do combinado",
                    f"Descontos do período: {_reais(vendas.get('desconto_cent'))}.")
    limite_sangria = int(cfg.get("sangria_cent") or 0)
    for sangria in retrato.get("sangrias") or []:
        if limite_sangria and int(sangria.get("valor_cent") or 0) >= limite_sangria:
            acrescentar("sangria", "Sangria alta",
                        f"{_reais(sangria.get('valor_cent'))} · {sangria.get('descricao') or 'sem descrição'} · "
                        f"{sangria.get('criado_em') or ''}")
    horas = float(cfg.get("mesa_horas") or 0)
    if horas > 0:
        for comanda in retrato.get("comandas") or []:
            aberta = str(comanda.get("aberta_em") or "")[:19]
            try:
                minutos = fmt.minutos_entre(aberta) if aberta else -1
            except ValueError:
                minutos = -1
            if minutos >= horas * 60:
                acrescentar("mesa", "Mesa ou comanda aberta há muitas horas",
                            f"{comanda.get('rotulo') or comanda.get('numero') or 'posição'} aberta desde {aberta}.")
    inicio, fim = str(cfg.get("expediente_de") or ""), str(cfg.get("expediente_ate") or "")
    caixa = retrato.get("caixa") or {}
    if caixa and inicio and fim:
        momento = str(retrato.get("momento") or fmt.agora())[11:16]
        if not _hora_no_intervalo(momento, inicio, fim):
            acrescentar("expediente", "Caixa aberto fora do horário",
                        f"Turno {caixa.get('turno_numero') or '?'} aberto às {momento}. "
                        f"Horário combinado: {inicio}–{fim}.")
    for fechamento in retrato.get("fechamentos") or []:
        diferenca = int(fechamento.get("resultado_cent") or 0)
        if diferenca:
            acrescentar("conferencia", "Diferença no fechamento do caixa",
                        f"Turno {fechamento.get('turno_numero')} · {fechamento.get('operador') or 'sem nome'} · "
                        f"diferença {_reais(diferenca)}.")
    estoque = (retrato.get("estoque") or {})
    if int(estoque.get("zerados") or 0) or int(estoque.get("abaixo_minimo_total") or 0):
        nomes = ", ".join(p.get("nome") or "" for p in (estoque.get("abaixo_minimo") or [])[:5])
        acrescentar("estoque", "Estoque baixo",
                    f"{int(estoque.get('zerados') or 0)} zerado(s), "
                    f"{int(estoque.get('abaixo_minimo_total') or 0)} no mínimo ou abaixo."
                    + (f" {nomes}." if nomes else ""))
    return alertas[:30]
