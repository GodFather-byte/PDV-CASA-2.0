"""Alertas do painel do dono, um por tipo, só do dia ou período pedido.

O retrato guarda cerca de um mês de fechamentos. Antes, cada fechamento com
`resultado_cent` diferente de zero virava um alerta, e a lista era cortada em 30.
Fechamento antigo sem valor contado (valor final vazio ou zero, sem conferência
por forma) não é diferença: ninguém contou o caixa.
"""
from __future__ import annotations

from src.core import formatacao as fmt

TIPOS = ("cancelamento", "desconto", "sangria", "mesa", "expediente", "conferencia", "estoque")
TOLERANCIA_CAIXA_CENT = 500


def _reais(centavos) -> str:
    return "R$ " + fmt.fmt_num(int(centavos or 0))


def _ligado(cfg: dict, tipo: str) -> bool:
    tipos = cfg.get("tipos")
    if isinstance(tipos, dict) and tipo in tipos:
        return bool(tipos[tipo])
    return True


def _hora_no_intervalo(hora: str, inicio: str, fim: str) -> bool:
    if not inicio or not fim or inicio == fim:
        return True
    if inicio < fim:
        return inicio <= hora < fim
    return hora >= inicio or hora < fim


def _dia_de(registro: dict) -> str:
    for campo in ("dia", "fechado_em", "criado_em", "aberta_em"):
        texto = str(registro.get(campo) or "")
        if len(texto) >= 10 and texto[4] == "-" and texto[7] == "-":
            return texto[:10]
    return ""


def _no_recorte(registro: dict, dia: str | None, ate: str | None) -> bool:
    if not dia:
        return True
    marca = _dia_de(registro)
    if not marca:
        return False
    fim = ate or dia
    return dia <= marca <= fim


def contagem_informada(fechamento: dict) -> bool:
    """Houve contagem digitada. Valor final ausente ou zero sem forma informada é fechamento antigo."""
    formas = fechamento.get("formas") or []
    if any(isinstance(f, dict) and f.get("informado_cent") is not None for f in formas):
        return True
    if formas:
        return False
    valor = fechamento.get("valor_final_cent")
    if valor is None:
        return False
    try:
        contado = int(valor)
    except (TypeError, ValueError):
        return False
    return contado != 0


def montar(resumo: dict, retrato: dict | None, cfg: dict | None, dia: str | None = None,
           ate: str | None = None, hoje: str | None = None) -> list[dict]:
    """Um grupo por tipo: quantidade, texto para o WhatsApp e os itens com data e valor."""
    cfg = cfg or {}
    retrato = retrato or {}
    vendas = (resumo or {}).get("vendas") or {}
    loja = ((resumo or {}).get("loja") or {}).get("nome") or retrato.get("loja_nome") or "Loja"
    hoje = hoje or fmt.hoje()
    ao_vivo = not dia or dia == hoje
    grupos: dict[str, dict] = {}

    def acrescentar(tipo: str, titulo: str, detalhe: str, quando: str, valor_cent: int | None) -> None:
        if not _ligado(cfg, tipo):
            return
        item = {
            "id": f"{tipo}|{quando}|{valor_cent}|{detalhe[:80]}",
            "data": quando[:16],
            "valor_cent": valor_cent,
            "detalhe": detalhe,
        }
        grupo = grupos.get(tipo)
        if grupo is None:
            grupo = {"tipo": tipo, "titulo": titulo, "quantidade": 0, "itens": []}
            grupos[tipo] = grupo
        grupo["quantidade"] += 1
        grupo["itens"].append(item)

    if _no_recorte({"dia": dia or hoje}, dia, ate):
        limite_cancel = int(cfg.get("cancelamento_cent") or 0)
        if limite_cancel and int(vendas.get("canceladas_cent") or 0) >= limite_cancel:
            acrescentar("cancelamento", "Cancelamento acima do combinado",
                        f"{int(vendas.get('canceladas') or 0)} cancelamento(s), {_reais(vendas.get('canceladas_cent'))}.",
                        dia or hoje, int(vendas.get("canceladas_cent") or 0))
        limite_desc = int(cfg.get("desconto_cent") or 0)
        if limite_desc and int(vendas.get("desconto_cent") or 0) >= limite_desc:
            acrescentar("desconto", "Desconto acima do combinado",
                        f"Descontos do período: {_reais(vendas.get('desconto_cent'))}.",
                        dia or hoje, int(vendas.get("desconto_cent") or 0))
    limite_sangria = int(cfg.get("sangria_cent") or 0)
    for sangria in retrato.get("sangrias") or []:
        if not _no_recorte(sangria, dia, ate):
            continue
        valor = int(sangria.get("valor_cent") or 0)
        if limite_sangria and valor >= limite_sangria:
            quando = str(sangria.get("criado_em") or sangria.get("dia") or "")
            acrescentar("sangria", "Sangria alta",
                        f"{_reais(valor)} · {sangria.get('descricao') or 'sem descrição'}.",
                        quando, valor)
    if ao_vivo:
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
                                f"{comanda.get('rotulo') or comanda.get('numero') or 'posição'} aberta desde {aberta}.",
                                aberta, None)
        inicio, fim = str(cfg.get("expediente_de") or ""), str(cfg.get("expediente_ate") or "")
        caixa = retrato.get("caixa") or {}
        if caixa and inicio and fim:
            momento = str(retrato.get("momento") or fmt.agora())
            if not _hora_no_intervalo(momento[11:16], inicio, fim):
                acrescentar("expediente", "Caixa aberto fora do horário",
                            f"Turno {caixa.get('turno_numero') or '?'} aberto às {momento[11:16]}. "
                            f"Horário combinado: {inicio}–{fim}.",
                            momento, None)
        estoque = retrato.get("estoque") or {}
        if int(estoque.get("zerados") or 0) or int(estoque.get("abaixo_minimo_total") or 0):
            nomes = ", ".join(p.get("nome") or "" for p in (estoque.get("abaixo_minimo") or [])[:5])
            acrescentar("estoque", "Estoque baixo",
                        f"{int(estoque.get('zerados') or 0)} zerado(s), "
                        f"{int(estoque.get('abaixo_minimo_total') or 0)} no mínimo ou abaixo."
                        + (f" {nomes}." if nomes else ""),
                        hoje, None)
    tolerancia = int(cfg.get("caixa_cent") if cfg.get("caixa_cent") is not None else TOLERANCIA_CAIXA_CENT)
    for fechamento in retrato.get("fechamentos") or []:
        if not _no_recorte(fechamento, dia, ate):
            continue
        if not contagem_informada(fechamento):
            continue
        diferenca = int(fechamento.get("resultado_cent") or 0)
        if abs(diferenca) <= tolerancia:
            continue
        quando = str(fechamento.get("fechado_em") or fechamento.get("dia") or "")
        acrescentar("conferencia", "Diferença no fechamento do caixa",
                    f"Turno {fechamento.get('turno_numero')} · {fechamento.get('operador') or 'sem nome'} · "
                    f"diferença {_reais(diferenca)} em {quando[:16]}.",
                    quando, diferenca)
    saida = []
    for tipo in TIPOS:
        grupo = grupos.get(tipo)
        if not grupo:
            continue
        grupo["itens"] = grupo["itens"][:12]
        linhas = [f"*{loja}*", grupo["titulo"] + f" ({grupo['quantidade']})"]
        linhas += [f"• {item['data']}: {item['detalhe']}" for item in grupo["itens"]]
        grupo["texto"] = "\n".join(linhas)
        saida.append(grupo)
    return saida
