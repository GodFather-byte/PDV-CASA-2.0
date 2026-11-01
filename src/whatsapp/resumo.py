"""Texto do resumo para o WhatsApp do dono, sem bot e sem API paga.

O caixa (no fechamento) e o painel (no botão) montam o mesmo texto. O link é
https://wa.me/<número>?text=... — quem envia é o WhatsApp do celular ou do computador.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from src.core import formatacao as fmt

LIMITE_TEXTO = 3500


def numeros(texto: str | None) -> list[str]:
    """'11 99999-9999, 5511988887777' vira dígitos com DDI. Vazio ou curto demais sai fora."""
    saida = []
    for parte in re.split(r"[,;\n]+", texto or ""):
        digitos = re.sub(r"\D", "", parte)
        if digitos.startswith("00"):
            digitos = digitos[2:]
        if len(digitos) in (10, 11):
            digitos = "55" + digitos
        if 12 <= len(digitos) <= 15 and digitos not in saida:
            saida.append(digitos)
    return saida


def link(numero: str, texto: str) -> str:
    return f"https://wa.me/{numero}?text={quote(texto)}"


def links(numeros_destino: list[str], texto: str) -> list[dict]:
    return [{"numero": n, "url": link(n, texto)} for n in numeros_destino]


def _reais(centavos) -> str:
    return "R$ " + fmt.fmt_num(int(centavos or 0))


def _qtd(valor) -> str:
    return fmt.fmt_qtd(valor)


def texto_resumo(dados: dict) -> str:
    """Um texto curto, em português, com o que o dono confere longe da loja."""
    vendas = dados.get("vendas") or {}
    linhas = [
        f"*{dados.get('loja') or 'Loja'}*",
        dados.get("periodo") or "Resumo",
        "",
        f"Total do período: {_reais(vendas.get('liquido_cent', vendas.get('faturamento_cent')))}",
        f"Bruto: {_reais(vendas.get('faturamento_cent'))}",
    ]
    comparacao = dados.get("comparacao")
    if comparacao:
        linhas.append(
            f"Mesmo dia da semana anterior ({comparacao.get('rotulo') or 'semana passada'}): "
            f"{_reais(comparacao.get('faturamento_cent'))}"
        )
    linhas += [
        f"Vendas: {int(vendas.get('quantidade') or 0)}",
        f"Ticket médio: {_reais(vendas.get('ticket_medio_cent'))}",
        f"Taxa de serviço{' (' + dados['servico_pct'] + ')' if dados.get('servico_pct') else ''}: "
        f"{_reais(dados.get('servico_cent'))}",
        "",
        "Garçons:",
    ]
    garcons = dados.get("garcons") or []
    linhas += [f"• {g['nome']}: {_reais(g.get('faturamento_cent'))} ({int(g.get('quantidade') or 0)} vendas)"
               for g in garcons[:8]] or ["• sem lançamento de garçom"]
    linhas += ["", "Produtos mais vendidos:"]
    produtos = dados.get("produtos") or []
    linhas += [f"• {p['nome']}: {_qtd(p.get('quantidade'))} · {_reais(p.get('valor_cent'))}"
               for p in produtos[:8]] or ["• sem venda de produto"]
    linhas += ["", "Formas de pagamento:"]
    formas = dados.get("formas") or []
    linhas += [f"• {f['tipo']}: {_reais(f.get('valor_cent'))}" for f in formas] or ["• sem pagamento registrado"]
    linhas += [
        "",
        f"Cancelamentos: {int(vendas.get('canceladas') or 0)} · {_reais(vendas.get('canceladas_cent'))}",
        f"Descontos: {_reais(vendas.get('desconto_cent'))}",
        f"Sangrias: {_reais(dados.get('sangrias_cent'))}",
        "",
        "Conferência de caixa:",
    ]
    conferencias = dados.get("conferencias") or []
    if not conferencias:
        linhas.append("• nenhum fechamento neste período")
    for conf in conferencias[:6]:
        quem = conf.get("fechado_por") or conf.get("operador") or "não informado"
        linhas.append(
            f"• Turno {conf.get('turno_numero') or '?'} · fechou {quem} · "
            f"esperado {_reais(conf.get('esperado_cent'))} · contado {_reais(conf.get('informado_cent', conf.get('valor_final_cent')))} · "
            f"diferença {_reais(conf.get('diferenca_cent', conf.get('resultado_cent')))}"
        )
        for forma in (conf.get("formas") or [])[:6]:
            if forma.get("informado_cent") is None:
                continue
            linhas.append(
                f"  – {forma.get('tipo')}: esperado {_reais(forma.get('esperado_cent'))}, "
                f"contado {_reais(forma.get('informado_cent'))}, diferença {_reais(forma.get('diferenca_cent'))}"
            )
    perdas = dados.get("perdas") or []
    if perdas:
        linhas += ["", "Perdas na contagem:"]
        linhas += [f"• {p['nome']}: {_qtd(p.get('unidades'))} · {_reais(p.get('valor_cent'))}" for p in perdas[:8]]
    texto = "\n".join(linhas)
    if len(texto) > LIMITE_TEXTO:
        texto = texto[: LIMITE_TEXTO - 20].rstrip() + "\n…(resumo cortado)"
    return texto


def abrir(destino: list[str], texto: str, abrir_url=None) -> list[str]:
    """Abre o WhatsApp (ou o navegador) com o texto pronto. Sem número, não abre nada."""
    import webbrowser
    abrir_url = abrir_url or webbrowser.open
    urls = [item["url"] for item in links(destino, texto)]
    for url in urls:
        abrir_url(url)
    return urls
