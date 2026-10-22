"""Textos que o dono recebe no Telegram: resumos sob demanda (os botões do bot) e avisos de eventos do caixa.

Só texto simples (sem formatação do Telegram, para nunca falhar por causa de um caractere). Dinheiro em reais, como no
resto do PDV. O celular é do dono e só quem ele pareou recebe: por isso a caderneta mostra quem deve. Nunca vão CPF, RG,
telefone ou endereço de cliente: só nomes, números de comanda e nomes de operadores.
"""
from __future__ import annotations

from src.controllers.estoque_controller import EstoqueController
from src.controllers.relatorio_vendas import virada_dia
from src.controllers.turno_controller import TurnoController
from src.core import formatacao as fmt
from src.core.posicao import nome as nome_posicao

DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
LIMITE_LISTA = 12          # linhas por lista: o celular não é lugar de relatório de 200 linhas


def _brl(cent) -> str:
    return fmt.fmt_brl(cent)


def _dia_rotulo(dia: str) -> str:
    from datetime import datetime
    d = datetime.strptime(dia[:10], "%Y-%m-%d")
    return f"{DIAS[d.weekday()]} {d.strftime('%d/%m')}"


def _hora(iso: str | None) -> str:
    return (iso or "")[11:16]


def _qtd(q) -> str:
    """2,000 -> '2'; 1,500 -> '1,5'."""
    return fmt.fmt_qtd(q).rstrip("0").rstrip(",")


def dia_atual(banco) -> str:
    return fmt.dia_operacional(virada=virada_dia(banco))


def dia_anterior(banco) -> str:
    return fmt.somar_dias(dia_atual(banco), -1)


def _faixa(banco, dia: str) -> tuple[str, str]:
    return fmt.faixa_dia_operacional(dia, virada_dia(banco))


def _recortar(linhas: list[str], limite: int = LIMITE_LISTA) -> list[str]:
    if len(linhas) <= limite:
        return linhas
    return linhas[:limite] + [f"... e mais {len(linhas) - limite}"]


# ------------------------------------------------------------------ resumos
def resumo(banco, dia: str | None = None, fechado: bool = False) -> str:
    """Faturamento, vendas, formas de pagamento, cancelamentos, sangrias e diferença de caixa de um dia operacional.
    `fechado`: a noite já acabou (resumo automático da manhã); senão é 'até agora'."""
    dia = dia or dia_atual(banco)
    ini, fim = _faixa(banco, dia)
    base = ("FROM vendas v WHERE v.status = 'fechada' AND v.fechada_em >= ? AND v.fechada_em < ? AND v.subtotal_cent > 0 "
            "AND EXISTS (SELECT 1 FROM itens_venda i WHERE i.venda_id = v.id AND i.cancelado = 0)")
    r = banco.um(f"SELECT COUNT(*) AS n, COALESCE(SUM(v.total_cent),0) AS total, COALESCE(SUM(v.pessoas),0) AS pessoas {base}",
                 (ini, fim))
    formas = banco.todos(
        f"""SELECT t.tipo, SUM(p.valor_cent - p.troco_cent) AS valor FROM pagamentos_venda p
            JOIN vendas v ON v.id = p.venda_id JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id
            WHERE v.status = 'fechada' AND v.fechada_em >= ? AND v.fechada_em < ? GROUP BY t.id
            HAVING valor <> 0 ORDER BY t.ordem, t.tipo""", (ini, fim))
    canc = banco.um(
        """SELECT COUNT(*) AS n, COALESCE(SUM(subtotal_cent),0) AS total FROM vendas
           WHERE status = 'cancelada' AND fechada_em >= ? AND fechada_em < ? AND subtotal_cent > 0""", (ini, fim))
    itens_canc = banco.um(
        """SELECT COUNT(*) AS n, COALESCE(SUM(i.total_cent),0) AS total FROM itens_venda i
           WHERE i.cancelado = 1 AND i.cancelado_em >= ? AND i.cancelado_em < ?""", (ini, fim))
    sangrias = banco.valor("SELECT COALESCE(SUM(valor_cent),0) FROM movimentos_caixa WHERE tipo = 'saida' "
                           "AND criado_em >= ? AND criado_em < ?", (ini, fim), 0)
    turnos = banco.todos("SELECT numero, resultado_cent, o.nome AS operador FROM turnos t LEFT JOIN operadores o ON o.id = t.operador_id "
                         "WHERE t.status = 'fechado' AND t.fechado_em >= ? AND t.fechado_em < ? ORDER BY t.id", (ini, fim))

    titulo = "Resumo da noite" if fechado else "Resumo até agora"
    linhas = [f"📊 {titulo} — {_dia_rotulo(dia)}", ""]
    if not r["n"]:
        linhas.append("Nenhuma venda fechada ainda.")
    else:
        linhas += [f"💰 Faturamento: {_brl(r['total'])}",
                   f"🧾 Vendas: {r['n']}  ·  Ticket médio: {_brl(fmt.dividir_cent(r['total'], r['n']))}"]
        if r["pessoas"]:
            linhas.append(f"👥 Pessoas: {r['pessoas']}  ·  {_brl(fmt.dividir_cent(r['total'], r['pessoas']))} por pessoa")
        if formas:
            linhas += ["", "Recebido por forma:"] + [f" • {f['tipo']}: {_brl(f['valor'])}" for f in formas]
    avisos = []
    if canc["n"]:
        avisos.append(f"❌ Cupons cancelados: {canc['n']} ({_brl(canc['total'])})")
    if itens_canc["n"]:
        avisos.append(f"❌ Itens cancelados: {itens_canc['n']} ({_brl(itens_canc['total'])})")
    if sangrias:
        avisos.append(f"💸 Sangrias: {_brl(sangrias)}")
    if avisos:
        linhas += [""] + avisos
    for t in turnos:
        linhas.append(f"⚖️ Turno {t['numero']} ({t['operador'] or '?'}): {_diferenca(t['resultado_cent'])}")
    if fechado:
        sem = banco.valor("SELECT COUNT(*) FROM produtos WHERE controla_estoque = 1 AND ativo = 1 AND qt_atual <= 0", (), 0)
        if sem:
            linhas += ["", f"📦 Produtos sem estoque: {sem} (toque em Estoque para ver)"]
        vencendo = _contas_a_pagar(banco, fmt.hoje(), fmt.hoje())
        if vencendo:
            linhas += [f"💳 Contas a pagar hoje: {len(vencendo)} ({_brl(sum(c['valor_cent'] for c in vencendo))}) — toque em Contas"]
    return "\n".join(linhas)


def _diferenca(resultado_cent: int | None) -> str:
    if resultado_cent is None:
        return "sem conferência"
    if resultado_cent == 0:
        return "✅ caixa bateu certinho"
    return f"{'⚠️ sobrou' if resultado_cent > 0 else '🚨 faltou'} {_brl(abs(resultado_cent))}"


def caixa(banco) -> str:
    """Como está o caixa agora: quem abriu, quanto vendeu no turno e quanto deveria ter de dinheiro na gaveta."""
    turnos = TurnoController(banco)
    t = turnos.atual()
    if t is None:
        ultimo = banco.um("SELECT t.numero, t.fechado_em, t.resultado_cent, o.nome AS operador FROM turnos t "
                          "LEFT JOIN operadores o ON o.id = t.operador_id WHERE t.status = 'fechado' ORDER BY t.id DESC LIMIT 1")
        linhas = ["💵 Nenhum caixa aberto agora."]
        if ultimo:
            linhas.append(f"Último: turno {ultimo['numero']} ({ultimo['operador'] or '?'}), fechado "
                          f"{fmt.fmt_datahora(ultimo['fechado_em'])[:16]} — {_diferenca(ultimo['resultado_cent'])}")
        return "\n".join(linhas)
    res = turnos.resumo(t["id"])
    operador = banco.valor("SELECT nome FROM operadores WHERE id = ?", (t["operador_id"],), "?")
    linhas = [f"💵 Caixa aberto — turno {t['numero']} ({operador})", f"Desde {fmt.fmt_datahora(t['aberto_em'])[:16]}", "",
              f"💰 Vendido no turno: {_brl(res['venda'] + res['servico'] + res['taxa'] - res['desconto'])}",
              f"🧾 Vendas: {res['tc']}  ·  Ticket médio: {_brl(res['tm'])}",
              f"🪙 Dinheiro que deveria estar na gaveta: {_brl(res['esperado'])}"]
    if res["recebimentos"]:
        linhas += ["", "Recebido por forma:"] + [f" • {r['tipo']}: {_brl(r['valor'])}" for r in res["recebimentos"]]
    if res["saidas"] or res["entradas"]:
        linhas += [""] + ([f"💸 Sangrias: {_brl(res['saidas'])}"] if res["saidas"] else []) + \
                  ([f"➕ Suprimentos: {_brl(res['entradas'])}"] if res["entradas"] else [])
    return "\n".join(linhas)


def mais_vendidos(banco, dia: str | None = None, limite: int = 10) -> str:
    dia = dia or dia_atual(banco)
    ini, fim = _faixa(banco, dia)
    linhas = banco.todos(
        """SELECT pr.nome, SUM(i.quantidade) AS qt, SUM(i.total_cent) AS total FROM itens_venda i
           JOIN vendas v ON v.id = i.venda_id JOIN produtos_historico pr ON pr.id = i.produto_id
           WHERE i.cancelado = 0 AND v.status = 'fechada' AND v.fechada_em >= ? AND v.fechada_em < ?
           GROUP BY pr.id ORDER BY total DESC, qt DESC LIMIT ?""", (ini, fim, limite))
    if not linhas:
        return f"🍺 Mais vendidos — {_dia_rotulo(dia)}\n\nNada vendido ainda."
    return "\n".join([f"🍺 Mais vendidos — {_dia_rotulo(dia)}", ""] +
                     [f"{n}. {r['nome']} — {_qtd(r['qt'])} un · {_brl(r['total'])}" for n, r in enumerate(linhas, 1)])


def estoque(banco) -> str:
    sem = [r["nome"] for r in banco.todos(
        "SELECT nome FROM produtos WHERE controla_estoque = 1 AND ativo = 1 AND qt_atual <= 0 ORDER BY nome")]
    ponto = banco.todos(
        "SELECT nome, qt_atual, estoque_minimo FROM produtos WHERE controla_estoque = 1 AND ativo = 1 "
        "AND qt_atual > 0 AND qt_atual <= estoque_minimo ORDER BY (qt_atual / CASE WHEN estoque_minimo > 0 THEN estoque_minimo ELSE 1 END), nome")
    total = banco.valor("SELECT COUNT(*) FROM produtos WHERE controla_estoque = 1 AND ativo = 1", (), 0)
    if not total:
        return "📦 Nenhum produto com controle de estoque ligado."
    linhas = [f"📦 Estoque — {total} produtos controlados", ""]
    if not sem and not ponto:
        return "\n".join(linhas + ["✅ Tudo em dia: nenhum produto zerado ou no ponto de pedido."])
    if sem:
        linhas += [f"🚨 Sem estoque ({len(sem)}):"] + _recortar([f" • {n}" for n in sem]) + [""]
    if ponto:
        linhas += [f"⚠️ Acabando — no ponto de pedido ({len(ponto)}):"] + _recortar(
            [f" • {r['nome']}: {_qtd(r['qt_atual'])} (mín. {_qtd(r['estoque_minimo'])})" for r in ponto])
    return "\n".join(linhas).rstrip()


def abertas(banco) -> str:
    from src.controllers.conferencia_turno import posicoes_abertas
    pos = posicoes_abertas(banco)
    if not pos:
        return "🪑 Nenhuma mesa ou comanda aberta com consumo."
    total = sum(p["total_cent"] for p in pos)
    linhas = [f"🪑 Em aberto agora: {len(pos)} (total {_brl(total)})", ""]
    linhas += _recortar([f" • {p['nome']}: {_brl(p['total_cent'])}" + (" (conta enviada)" if p["status"] == "conta_enviada" else "")
                         for p in sorted(pos, key=lambda p: -p["total_cent"])], 20)
    return "\n".join(linhas)


def cancelamentos(banco, dia: str | None = None) -> str:
    dia = dia or dia_atual(banco)
    ini, fim = _faixa(banco, dia)
    cupons = banco.todos(
        """SELECT v.cupom, v.modalidade, v.comanda, v.posicao, v.subtotal_cent AS total, v.motivo_cancelamento AS motivo,
                  o.nome AS por, v.fechada_em AS quando FROM vendas v LEFT JOIN operadores o ON o.id = v.cancelada_por
           WHERE v.status = 'cancelada' AND v.fechada_em >= ? AND v.fechada_em < ? AND v.subtotal_cent > 0
           ORDER BY v.fechada_em DESC""", (ini, fim))
    itens = banco.todos(
        """SELECT pr.nome, i.quantidade, i.total_cent AS total, i.cancelado_em AS quando, o.nome AS por
           FROM itens_venda i JOIN produtos_historico pr ON pr.id = i.produto_id LEFT JOIN operadores o ON o.id = i.operador_id
           WHERE i.cancelado = 1 AND i.cancelado_em >= ? AND i.cancelado_em < ? ORDER BY i.cancelado_em DESC""", (ini, fim))
    if not cupons and not itens:
        return f"❌ Cancelamentos — {_dia_rotulo(dia)}\n\n✅ Nenhum cancelamento."
    linhas = [f"❌ Cancelamentos — {_dia_rotulo(dia)}", ""]
    if cupons:
        linhas.append(f"Cupons ({len(cupons)}, {_brl(sum(c['total'] for c in cupons))}):")
        linhas += _recortar([f" • {_hora(c['quando'])} cupom {c['cupom']} {_brl(c['total'])} — {c['por'] or '?'}"
                             + (f" — {c['motivo']}" if c["motivo"] else "") for c in cupons], 8)
    if itens:
        linhas += ["", f"Itens ({len(itens)}, {_brl(sum(i['total'] for i in itens))}):"]
        linhas += _recortar([f" • {_hora(i['quando'])} {_qtd(i['quantidade'])}x {i['nome']} {_brl(i['total'])}"
                             + (f" — {i['por']}" if i["por"] else "") for i in itens], 8)
    return "\n".join(linhas)


def ajuda() -> str:
    return ("Sou o bot da sua casa. Toque nos botões aqui embaixo:\n\n"
            "Vendas\n📊 Resumo — vendas da noite até agora\n📅 Ontem — resumo da noite passada\n"
            "🍺 Mais vendidos — top 10 da noite\n📈 Semana — faturamento dos últimos 7 dias\n"
            "🗓️ Mês — mês até hoje e comparação com o anterior\n🕐 Por hora — como a noite está andando\n"
            "👥 Equipe — vendas por garçom/vendedor\n\n"
            "Operação\n💵 Caixa — turno aberto, vendido e dinheiro esperado\n🪑 Abertas — mesas e comandas em aberto\n"
            "❌ Cancelamentos — cupons e itens cancelados\n\n"
            "Estoque\n📦 Estoque — o que zerou ou está acabando\n🛒 Comprar — lista do que repor\n"
            "🔎 Produto — preço, estoque e últimos movimentos\n\n"
            "Financeiro\n💳 Contas — contas a pagar vencidas e próximas\n📒 Caderneta — quem está devendo\n\n"
            "Licença e suporte\n🔐 Licença — situação e vencimento da licença deste caixa\n"
            "🛟 Suporte — versão e contato técnico com o fornecedor\n"
            "🔄 Renovar — pede a renovação ao fornecedor (só o pedido; nada é pago por aqui)\n\n"
            "Também dá para digitar:\n • produto skol — preço, estoque e últimos movimentos\n"
            " • mesa 12 (ou comanda 5) — o consumo da mesa agora\n\n"
            "Os avisos (caixa, cancelamentos, sangrias, produto acabando, licença vencendo) chegam sozinhos.\n"
            "Pelo Telegram você só consulta: nada de dinheiro, preço ou cadastro é alterado no caixa por aqui.")


# ------------------------------------------------- licença e suporte (sem código da licença, tokens ou clientes)
_SITUACAO_LICENCA = {"ok": "✅ Em dia", "aviso": "⏳ Vence em breve", "carencia": "⚠️ Vencida, em carência",
                     "bloqueada": "⛔ Vencida, carência encerrada", "sem_licenca": "⛔ Sem licença válida",
                     "desativada": "ℹ️ Não exigida neste caixa"}
# Estados gravados pela ponte (src/sync/ponte.py): 'pendente' ainda não saiu deste caixa; 'enviada' chegou à central;
# 'atendida' = a central confirmou que este caixa aplicou uma licença posterior ao pedido.
_PEDIDO_STATUS = {"pendente": "registrado neste caixa, aguardando conexão para chegar ao fornecedor",
                  "enviada": "entregue ao fornecedor, aguardando a nova licença",
                  "atendida": "concluído, nova licença já aplicada neste caixa"}


def _data_br(dia) -> str:
    return dia.strftime("%d/%m/%Y") if dia else "?"


def _quando_br(iso) -> str:
    iso = str(iso or "").strip()
    if len(iso) < 10:
        return ""
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" + (f" às {iso[11:16]}" if len(iso) >= 16 else "")


def _pedido(pedido) -> str:
    """Andamento do pedido de renovação: só o estado conhecido e a data (nada de identificador, token ou valor)."""
    if not isinstance(pedido, dict) or not pedido:
        return ""
    status = _PEDIDO_STATUS.get(str(pedido.get("status") or "").strip().lower(), "em andamento")
    quando = _quando_br(pedido.get("criado_em"))
    return f"Pedido de renovação: {status}" + (f" (feito em {quando})" if quando else "")


def licenca(est, pedido=None) -> str:
    """Situação da licença deste caixa (`est` = licenca.estado). Nunca mostra o código da licença."""
    linhas = ["🔐 Licença deste caixa", "", f"Situação: {_SITUACAO_LICENCA.get(est.situacao, est.situacao)}"]
    if est.expira_em:
        linhas.append(f"Válida até: {_data_br(est.expira_em)}")
        if est.dias is not None and est.dias > 0:
            linhas.append(f"Faltam {est.dias} {'dia' if est.dias == 1 else 'dias'}.")
    if est.mensagem:
        linhas += ["", est.mensagem]
    texto_pedido = _pedido(pedido)
    if texto_pedido:
        linhas += ["", texto_pedido]
    if est.situacao != "desativada":
        linhas += ["", "Para pedir a renovação ao fornecedor, toque em 🔄 Renovar. Nenhum pagamento é feito pelo Telegram."]
    return "\n".join(linhas)


def licenca_alerta(est, renovada: bool = False) -> str:
    """Aviso automático de licença. `renovada` só quando a nova validade já está aplicada neste caixa."""
    linhas = []
    if renovada and est.expira_em:
        linhas.append(f"✅ Licença renovada e aplicada neste caixa: válida até {_data_br(est.expira_em)}.")
    if est.situacao in ("aviso", "carencia", "bloqueada", "sem_licenca"):
        icone = "⏳" if est.situacao == "aviso" else "⚠️" if est.situacao == "carencia" else "⛔"
        linhas.append(f"{icone} Licença: {est.mensagem or _SITUACAO_LICENCA[est.situacao]}")
        linhas.append("Toque em 🔄 Renovar para pedir a renovação ao fornecedor.")
    return "\n".join(linhas)


def suporte(versao: str, est, situacao_ponte, fila_pendente: int, telegram_com_erro: bool) -> str:
    """Dados técnicos da própria loja: versão, licença, contato com o fornecedor e pendências. Sem tokens nem o texto
    dos erros (pode ter endereço ou credencial)."""
    linhas = ["🛟 Suporte deste caixa", "", f"Versão do PDV: {versao}",
              f"Licença: {_SITUACAO_LICENCA.get(est.situacao, est.situacao)}"
              + (f" (até {_data_br(est.expira_em)})" if est.expira_em else "")]
    if situacao_ponte is None:
        linhas.append("Contato com o fornecedor: ainda não configurado neste caixa.")
    elif not situacao_ponte.get("ativa", True):
        linhas.append("Contato com o fornecedor: desligado neste caixa.")
    else:
        contato = _quando_br(situacao_ponte.get("ultimo_contato"))
        linhas.append(f"Último contato com o fornecedor: {contato}" if contato else
                      "Último contato com o fornecedor: nenhum registrado.")
        if situacao_ponte.get("com_erro"):
            linhas.append("⚠️ A última tentativa de contato falhou. Confira a internet; detalhes no PDV.")
        linhas.append(_pedido(situacao_ponte.get("pedido")) or "Nenhum pedido de renovação pendente.")
    if fila_pendente:
        linhas.append(f"Avisos esperando envio: {fila_pendente}")
    if telegram_com_erro:
        linhas.append("⚠️ O envio de avisos teve erro recentemente; detalhes em Configurações > Telegram.")
    return "\n".join(linhas)


def renovacao_pedida(entregue: bool, repetido: bool = False, atendida: bool = False) -> str:
    """Resposta ao pedido de renovação. Só fala em licença aplicada quando a ponte marca o pedido como 'atendida'."""
    if atendida:
        return ("✅ O último pedido de renovação já foi concluído: a nova licença está aplicada neste caixa. "
                "Nenhum pedido novo foi criado; confira em 🔐 Licença.")
    if repetido:
        inicio = "📨 Já existe um pedido de renovação entregue ao fornecedor; não foi criado outro."
    elif entregue:
        inicio = "📨 Pedido de renovação entregue ao fornecedor."
    else:
        inicio = ("📝 Pedido de renovação registrado neste caixa, mas ainda NÃO chegou ao fornecedor (sem conexão com a "
                  "central). O PDV reenvia sozinho; acompanhe em 🛟 Suporte.")
    return "\n".join([inicio, "", "A licença só muda depois que o novo código for aplicado neste caixa; você recebe um "
                                   "aviso aqui quando isso acontecer. Nenhuma cobrança ou pagamento é feito pelo Telegram."])


# ------------------------------------------------- consultas do dono (tudo do PDV)
_BASE_VENDAS = ("FROM vendas v WHERE v.status = 'fechada' AND v.fechada_em >= ? AND v.fechada_em < ? AND v.subtotal_cent > 0 "
                "AND EXISTS (SELECT 1 FROM itens_venda i WHERE i.venda_id = v.id AND i.cancelado = 0)")


def _por_dia(banco, ini: str, fim: str) -> dict[str, tuple[int, int]]:
    """{dia operacional: (vendas, faturamento)} entre dois instantes; só dias com venda."""
    virada = virada_dia(banco)
    linhas = banco.todos(
        f"SELECT date(datetime(v.fechada_em, '-{virada} hours')) AS dia, COUNT(*) AS n, COALESCE(SUM(v.total_cent),0) AS total "
        f"{_BASE_VENDAS} GROUP BY dia ORDER BY dia", (ini, fim))
    return {r["dia"]: (r["n"], r["total"]) for r in linhas}


def semana(banco) -> str:
    """Faturamento dos últimos 7 dias operacionais (hoje incluído), com o melhor dia destacado."""
    hoje = dia_atual(banco)
    primeiro = fmt.somar_dias(hoje, -6)
    por_dia = _por_dia(banco, _faixa(banco, primeiro)[0], _faixa(banco, hoje)[1])
    dias = [fmt.somar_dias(primeiro, i) for i in range(7)]
    total = sum(por_dia.get(d, (0, 0))[1] for d in dias)
    vendas = sum(por_dia.get(d, (0, 0))[0] for d in dias)
    if not vendas:
        return "📈 Últimos 7 dias\n\nNenhuma venda nesse período."
    melhor = max(dias, key=lambda d: por_dia.get(d, (0, 0))[1])
    linhas = ["📈 Últimos 7 dias", ""]
    for d in dias:
        n, v = por_dia.get(d, (0, 0))
        marca = " 🏆" if d == melhor else ""
        sufixo = " (até agora)" if d == hoje else ""
        linhas.append(f"{_dia_rotulo(d)}: {_brl(v)} · {n} vendas{sufixo}{marca}")
    ativos = sum(1 for d in dias if por_dia.get(d, (0, 0))[0])
    linhas += ["", f"💰 Total: {_brl(total)} em {vendas} vendas", f"📊 Média por dia com venda: {_brl(fmt.dividir_cent(total, ativos))}"]
    return "\n".join(linhas)


def mes(banco) -> str:
    """O mês até hoje, comparado ao mês anterior no mesmo trecho (dia 1 até o mesmo dia)."""
    from datetime import datetime
    hoje = dia_atual(banco)
    d = datetime.strptime(hoje, "%Y-%m-%d")
    primeiro = d.strftime("%Y-%m-01")
    mes_ant = fmt.somar_dias(primeiro, -1)[:8] + "01"
    mesmo_dia_ant = min(fmt.somar_dias(mes_ant, d.day - 1), fmt.somar_dias(primeiro, -1))
    atual = _por_dia(banco, _faixa(banco, primeiro)[0], _faixa(banco, hoje)[1])
    anterior = _por_dia(banco, _faixa(banco, mes_ant)[0], _faixa(banco, mesmo_dia_ant)[1])
    n = sum(v[0] for v in atual.values())
    total = sum(v[1] for v in atual.values())
    nome_mes = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro",
                "dezembro"][d.month - 1]
    if not n:
        return f"🗓️ {nome_mes.capitalize()}\n\nNenhuma venda neste mês ainda."
    total_ant = sum(v[1] for v in anterior.values())
    melhor = max(atual, key=lambda k: atual[k][1])
    linhas = [f"🗓️ {nome_mes.capitalize()} até hoje", "",
              f"💰 Faturamento: {_brl(total)}", f"🧾 Vendas: {n}  ·  Ticket médio: {_brl(fmt.dividir_cent(total, n))}",
              f"📊 Média por dia com venda: {_brl(fmt.dividir_cent(total, len(atual)))} ({len(atual)} dias)",
              f"🏆 Melhor dia: {_dia_rotulo(melhor)} com {_brl(atual[melhor][1])}"]
    if total_ant:
        pct = round((total - total_ant) * 100 / total_ant)
        linhas += ["", f"Mês anterior no mesmo trecho: {_brl(total_ant)}",
                   f"{'📈' if pct >= 0 else '📉'} {'+' if pct >= 0 else ''}{pct}% em relação a ele"]
    return "\n".join(linhas)


def por_hora(banco, dia: str | None = None) -> str:
    """Faturamento por hora da noite (na ordem em que a noite acontece), com barrinhas."""
    dia = dia or dia_atual(banco)
    ini, fim = _faixa(banco, dia)
    virada = virada_dia(banco)
    horas = {r["h"]: (r["n"], r["total"]) for r in banco.todos(
        f"SELECT CAST(strftime('%H', v.fechada_em) AS INTEGER) AS h, COUNT(*) AS n, COALESCE(SUM(v.total_cent),0) AS total "
        f"{_BASE_VENDAS} GROUP BY h", (ini, fim))}
    if not horas:
        return f"🕐 Por hora — {_dia_rotulo(dia)}\n\nNenhuma venda ainda."
    ordem = [(virada + i) % 24 for i in range(24)]
    usadas = [h for h in ordem if h in horas]
    ate = ordem.index(usadas[-1])
    maior = max(v[1] for v in horas.values()) or 1
    linhas = [f"🕐 Por hora — {_dia_rotulo(dia)}", ""]
    for h in ordem[ordem.index(usadas[0]):ate + 1]:
        n, v = horas.get(h, (0, 0))
        linhas.append(f"{h:02d}h {'█' * max(1, round(v * 10 / maior)) if v else '·':<10} {_brl(v)} ({n})")
    pico = max(horas, key=lambda h: horas[h][1])
    linhas += ["", f"🔥 Pico: {pico:02d}h com {_brl(horas[pico][1])}"]
    return "\n".join(linhas)


def equipe(banco, dia: str | None = None) -> str:
    """Vendas fechadas por garçom/vendedor (quem não tem, vai para quem operou o caixa)."""
    dia = dia or dia_atual(banco)
    ini, fim = _faixa(banco, dia)
    linhas = banco.todos(
        f"""SELECT COALESCE(g.nome, vd.nome, o.nome, '?') AS quem, COUNT(*) AS n, COALESCE(SUM(v.total_cent),0) AS total
            FROM vendas v LEFT JOIN operadores g ON g.id = v.garcom_id LEFT JOIN operadores vd ON vd.id = v.vendedor_id
            LEFT JOIN operadores o ON o.id = v.operador_id
            WHERE v.status = 'fechada' AND v.fechada_em >= ? AND v.fechada_em < ? AND v.subtotal_cent > 0
              AND EXISTS (SELECT 1 FROM itens_venda i WHERE i.venda_id = v.id AND i.cancelado = 0)
            GROUP BY quem ORDER BY total DESC""", (ini, fim))
    if not linhas:
        return f"👥 Equipe — {_dia_rotulo(dia)}\n\nNenhuma venda ainda."
    return "\n".join([f"👥 Equipe — {_dia_rotulo(dia)}", ""] + _recortar(
        [f"{n}. {r['quem']}: {_brl(r['total'])} · {r['n']} vendas · ticket {_brl(fmt.dividir_cent(r['total'], r['n']))}"
         for n, r in enumerate(linhas, 1)], 15))


def _contas_a_pagar(banco, de: str | None, ate: str | None, vencidas: bool = False) -> list[dict]:
    onde = "c.dt_quitacao IS NULL AND pl.debito = 1"
    params: list = []
    if vencidas:
        onde += " AND c.dt_vencimento < ?"
        params.append(de)
    else:
        onde += " AND c.dt_vencimento >= ? AND c.dt_vencimento <= ?"
        params += [de, ate]
    return [dict(r) for r in banco.todos(
        f"""SELECT c.descricao, c.valor_cent, c.dt_vencimento, f.nome AS fornecedor FROM contas c
            JOIN subplanos sp ON sp.id = c.subplano_id JOIN planos_contas pl ON pl.id = sp.plano_id
            LEFT JOIN fornecedores f ON f.id = c.fornecedor_id WHERE {onde} ORDER BY c.dt_vencimento, c.id""", params)]


def contas(banco) -> str:
    """Contas a pagar em aberto: vencidas, de hoje e dos próximos 7 dias."""
    if not banco.cfg_bool("usar_contas", False):
        return "💳 O módulo de contas está desligado neste PDV."
    hoje = fmt.hoje()
    vencidas = _contas_a_pagar(banco, hoje, None, vencidas=True)
    proximas = _contas_a_pagar(banco, hoje, fmt.somar_dias(hoje, 7))
    if not vencidas and not proximas:
        return "💳 Contas a pagar\n\n✅ Nada vencido e nada vencendo nos próximos 7 dias."

    def linha(c):
        quem = c["fornecedor"] or c["descricao"]
        return f" • {fmt.fmt_data(c['dt_vencimento'])[:5]} {quem[:28]}: {_brl(c['valor_cent'])}"
    linhas = ["💳 Contas a pagar", ""]
    if vencidas:
        linhas += [f"🚨 Vencidas ({len(vencidas)}, {_brl(sum(c['valor_cent'] for c in vencidas))}):"] + \
                  _recortar([linha(c) for c in vencidas], 10) + [""]
    if proximas:
        linhas += [f"📅 Hoje e próximos 7 dias ({len(proximas)}, {_brl(sum(c['valor_cent'] for c in proximas))}):"] + \
                  _recortar([linha(c) for c in proximas], 10)
    return "\n".join(linhas).rstrip()


def caderneta(banco) -> str:
    """Quanto a casa tem a receber na caderneta e quem mais deve."""
    devedores = banco.todos("SELECT nome, saldo_cent FROM clientes WHERE saldo_cent < 0 AND ativo = 1 ORDER BY saldo_cent, nome")
    if not devedores:
        return "📒 Caderneta\n\n✅ Ninguém está devendo."
    total = -sum(d["saldo_cent"] for d in devedores)
    return "\n".join([f"📒 Caderneta — {len(devedores)} clientes devendo, total {_brl(total)}", ""] + _recortar(
        [f"{n}. {d['nome']}: {_brl(-d['saldo_cent'])}" for n, d in enumerate(devedores, 1)], 15))


def comprar(banco) -> str:
    """O que precisa ser comprado agora (sem estoque e no ponto de pedido), na quantidade sugerida."""
    lista = EstoqueController(banco).lista_de_compras()
    if not lista:
        return "🛒 Lista de compras\n\n✅ Nada para repor agora (ou falta definir o estoque mínimo dos produtos)."
    linhas = [f"🛒 Comprar — {len(lista)} produtos", ""]
    linhas += _recortar([f" • {p['nome']}: tem {_qtd(p['qt_atual'])}, comprar {_qtd(p['repor'])} {p['unidade']}"
                         + (" 🚨" if p["situacao"] == "sem" else "") for p in lista], 25)
    return "\n".join(linhas)


def produto(banco, busca: str) -> str:
    """Preço, estoque e últimos movimentos de um produto (ou a lista dos que combinam, se forem vários)."""
    busca = (busca or "").strip()
    if not busca:
        return "🔎 Digite o nome depois da palavra produto. Exemplo: produto skol"
    from src.controllers.cadastro_controller import CadastroController
    achados = CadastroController(banco).listar("produtos", texto=busca, apenas_ativos=True)
    if not achados:
        return f"🔎 Não achei nenhum produto com '{busca}'."
    exatos = [p for p in achados if p["nome"].casefold() == busca.casefold()]
    if len(achados) > 1 and len(exatos) != 1:
        return "\n".join([f"🔎 {len(achados)} produtos combinam com '{busca}':", ""] + _recortar(
            [f" • {p['nome']} — {_brl(p['preco_cent'])}" for p in achados], 15) + ["", "Digite o nome completo para ver os detalhes."])
    p = (exatos or achados)[0]
    linhas = [f"🔎 {p['nome']}", f"Preço de venda: {_brl(p['preco_cent'])}"]
    if not p["controla_estoque"]:
        linhas.append("Não controla estoque.")
        return "\n".join(linhas)
    est = EstoqueController(banco)
    situacao = est.produtos.situacao_estoque(p)
    rotulo = {"sem": "🚨 SEM ESTOQUE", "ponto": "⚠️ no ponto de pedido", "normal": "✅ normal"}[situacao]
    linhas += [f"Estoque: {_qtd(p['qt_atual'])} ({rotulo})",
               f"Mínimo: {_qtd(p['estoque_minimo'])}" if p["estoque_minimo"] else "Mínimo: não definido",
               f"Último preço de compra: {_brl(p['ult_preco_cent'])}"]
    movs = est.historico(p["id"], 6)
    if movs:
        linhas += ["", "Últimos movimentos:"] + [
            f" • {fmt.fmt_datahora(m['criado_em'])[:16]} {m['rotulo']} {'+' if m['quantidade'] > 0 else ''}{_qtd(m['quantidade'])} → {_qtd(m['qt_apos'])}"
            for m in movs]
    return "\n".join(linhas)


def mesa(banco, texto: str) -> str:
    """O consumo de uma mesa ou comanda aberta agora: itens, total e quanto tempo faz."""
    from src.core import posicao as pos
    try:
        comanda, numero = pos.interpretar(texto, banco.cfg("posicao_padrao", "comanda"))
    except ValueError as e:
        return f"🪑 {e}"
    if numero == 0:
        return "🪑 Informe o número da mesa ou comanda. Exemplo: mesa 12"
    vendas = banco.todos(
        "SELECT * FROM vendas WHERE modalidade = 'mesa' AND comanda = ? AND posicao = ? AND status IN ('aberta','conta_enviada') "
        "ORDER BY id", (int(comanda), numero))
    nome = pos.nome(comanda, numero)
    if not vendas:
        return f"🪑 {nome} não está aberta."
    v = vendas[0]
    itens = banco.todos(
        """SELECT p.nome, SUM(i.quantidade) AS qt, SUM(i.total_cent) AS total FROM itens_venda i JOIN produtos_historico p ON p.id = i.produto_id
           WHERE i.venda_id = ? AND i.cancelado = 0 GROUP BY p.id ORDER BY MIN(i.id)""", (v["id"],))
    if not itens:
        return f"🪑 {nome} está aberta, sem consumo."
    linhas = [f"🪑 {nome} — aberta às {_hora(v['aberta_em'])}" + (" · conta enviada" if v["status"] == "conta_enviada" else ""), ""]
    linhas += _recortar([f" • {_qtd(i['qt'])}x {i['nome']}: {_brl(i['total'])}" for i in itens], 25)
    linhas += ["", f"💰 Total até agora: {_brl(v['total_cent'] or sum(i['total'] for i in itens))}"]
    return "\n".join(linhas)


# -------------------------------------------------------- avisos de eventos
def _operador(banco, operador_id) -> str:
    return banco.valor("SELECT nome FROM operadores WHERE id = ?", (operador_id,), "?") if operador_id else "?"


def turno_aberto(banco, turno_id: int) -> str:
    t = banco.um("SELECT * FROM turnos WHERE id = ?", (turno_id,))
    return (f"🟢 Caixa aberto — turno {t['numero']}\nOperador: {_operador(banco, t['operador_id'])}\n"
            f"Fundo de caixa: {_brl(t['valor_inicial_cent'])}\n{fmt.fmt_datahora(t['aberto_em'])[:16]}")


def turno_fechado(banco, turno_id: int) -> str:
    """Fechamento: o que vendeu e se o caixa bateu. O operador não vê o 'esperado' na conferência cega; o dono vê."""
    t = banco.um("SELECT * FROM turnos WHERE id = ?", (turno_id,))
    res = TurnoController(banco).resumo(turno_id)
    vendido = res["venda"] + res["servico"] + res["taxa"] + res["acrescimo"] - res["desconto"]
    linhas = [f"🔴 Caixa fechado — turno {t['numero']}", f"Operador: {_operador(banco, t['operador_id'])}",
              f"{fmt.fmt_datahora(t['aberto_em'])[:16]} → {fmt.fmt_datahora(t['fechado_em'])[:16]}", "",
              f"💰 Vendido: {_brl(vendido)} em {res['tc']} vendas",
              f"🪙 Dinheiro esperado: {_brl(t['esperado_cent'])}",
              f"🪙 Dinheiro contado: {_brl(t['valor_final_cent'])}",
              f"⚖️ {_diferenca(t['resultado_cent'])}"]
    if res["saidas"]:
        linhas.append(f"💸 Sangrias no turno: {_brl(res['saidas'])}")
    if res["cupons_cancelados"]:
        linhas.append(f"❌ Cupons cancelados no turno: {len(res['cupons_cancelados'])}")
    return "\n".join(linhas)


def venda_cancelada(banco, venda_id: int) -> str:
    v = banco.um("SELECT v.*, o.nome AS por FROM vendas v LEFT JOIN operadores o ON o.id = v.cancelada_por WHERE v.id = ?", (venda_id,))
    local = {"mesa": nome_posicao(v["comanda"], v["posicao"]), "balcao": "balcão", "caderneta": "caderneta"}.get(v["modalidade"], "entrega")
    linhas = [f"❌ Cupom cancelado — {local}", f"Valor: {_brl(v['total_cent'] or v['subtotal_cent'])}  ·  cupom {v['cupom']}",
              f"Por: {v['por'] or '?'}  às {_hora(v['fechada_em'])}"]
    if v["motivo_cancelamento"]:
        linhas.append(f"Motivo: {v['motivo_cancelamento']}")
    else:
        linhas.append("Motivo: não informado")
    return "\n".join(linhas)


def item_cancelado(banco, item_id: int, motivo: str, operador_id) -> str:
    i = banco.um("SELECT i.*, pr.nome AS produto, v.modalidade, v.comanda, v.posicao FROM itens_venda i "
                 "JOIN produtos_historico pr ON pr.id = i.produto_id JOIN vendas v ON v.id = i.venda_id WHERE i.id = ?", (item_id,))
    local = {"mesa": nome_posicao(i["comanda"], i["posicao"]), "balcao": "balcão", "caderneta": "caderneta"}.get(i["modalidade"], "entrega")
    linhas = [f"❌ Item cancelado — {local}", f"{_qtd(i['quantidade'])}x {i['produto']} ({_brl(i['total_cent'])})",
              f"Por: {_operador(banco, operador_id)}"]
    linhas.append(f"Motivo: {motivo}" if motivo else "Motivo: não informado")
    return "\n".join(linhas)


def movimento_caixa(banco, tipo: str, valor_cent: int, descricao: str, operador_id) -> str:
    cab = "💸 Sangria" if tipo == "saida" else "➕ Suprimento"
    linhas = [f"{cab}: {_brl(valor_cent)}", f"Por: {_operador(banco, operador_id)}"]
    if descricao:
        linhas.append(f"Obs.: {descricao}")
    return "\n".join(linhas)


def backup_falhou(banco, erro: str) -> str:
    return f"⚠️ O backup automático do PDV falhou.\n{erro[:200]}\nAbra Utilitários > Backup de dados e confira a pasta/disco."


def venda_fechada(banco, venda_id: int) -> str | None:
    """Aviso de cada venda fechada (opcional: em noite cheia são muitas mensagens). Pagamento de caderneta não conta como venda."""
    v = banco.um("SELECT v.*, o.nome AS operador FROM vendas v LEFT JOIN operadores o ON o.id = v.operador_id WHERE v.id = ?", (venda_id,))
    if v is None or v["subtotal_cent"] <= 0:
        return None
    local = {"mesa": nome_posicao(v["comanda"], v["posicao"]), "balcao": "balcão", "caderneta": "caderneta"}.get(v["modalidade"], "entrega")
    formas = banco.todos("SELECT t.tipo, SUM(p.valor_cent - p.troco_cent) AS valor FROM pagamentos_venda p "
                         "JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id WHERE p.venda_id = ? GROUP BY t.id", (venda_id,))
    linhas = [f"🧾 Venda — {local}: {_brl(v['total_cent'])}"]
    if formas:
        linhas.append(" + ".join(f"{f['tipo']} {_brl(f['valor'])}" for f in formas))
    linhas.append(f"Por: {v['operador'] or '?'} às {_hora(v['fechada_em'])}")
    return "\n".join(linhas)


def estoque_alerta(banco, alertas: list[tuple[str, str, float, float]]) -> str:
    """`alertas` = [(nome, 'sem'|'ponto', quantidade_agora, minimo)] dos produtos que acabaram de cruzar o limite."""
    linhas = []
    for nome, situacao, qt, minimo in alertas:
        if situacao == "sem":
            linhas.append(f"🚨 {nome} ACABOU (sem estoque)")
        else:
            linhas.append(f"⚠️ {nome} está acabando: restam {_qtd(qt)} (mínimo {_qtd(minimo)})")
    return "\n".join(linhas + ["", "Toque em 🛒 Comprar para ver a lista de reposição."]) if linhas else ""
