"""Relatórios de estoque, financeiro e clientes (manual ADM 6.08, 6.12 a 6.14, estoque atual)."""
from __future__ import annotations

from src.controllers.produto_controller import ProdutoController
from src.core import formatacao as fmt
from src.core.relatorio import Coluna, Relatorio

M, Q = fmt.fmt_num, fmt.fmt_qtd


class RelatoriosGestao:
    banco = None  # fornecido pela classe concreta

    # ------------------------------------------------------ estoque atual
    def estoque_atual(self, f: dict | None = None) -> tuple[Relatorio, list[dict]]:
        """Posição do estoque. Filtros: situacao (normal|ponto|sem), data + verifica_datas
        ('maior'|'menor' = última atualização >= / <= data), valor + verifica_valores (sobre o custo total),
        unidade_id, subgrupo_id. Devolve (relatório, dados com a situação para colorir a tela)."""
        f = f or {}
        onde, p = ["pr.controla_estoque = 1", "pr.ativo = 1"], []
        if f.get("unidade_id"): onde.append("pr.unidade_id = ?"); p.append(f["unidade_id"])
        if f.get("subgrupo_id"): onde.append("pr.subgrupo_id = ?"); p.append(f["subgrupo_id"])
        if f.get("data"):
            op = ">=" if f.get("verifica_datas", "maior") == "maior" else "<="
            onde.append(f"date(COALESCE(pr.ult_atualizacao, '1900-01-01')) {op} ?"); p.append(f["data"])
        rel = Relatorio("Estoque atual", [Coluna("Código", 13), Coluna("Produto", 30), Coluna("Mínimo", 9, "d"),
                                          Coluna("Atual", 9, "d"), Coluna("Custo", 9, "d"), Coluna("Total", 11, "d"),
                                          Coluna("Un", 4)], criterios=[])
        dados, total = [], 0
        for r in self.banco.todos(
                f"""SELECT pr.*, u.abreviatura AS un FROM produtos pr JOIN unidades u ON u.id = pr.unidade_id
                    WHERE {' AND '.join(onde)} ORDER BY pr.nome""", p):
            d = dict(r)
            d["situacao"] = ProdutoController.situacao_estoque(d)
            d["total_cent"] = fmt.mult_cent(d["ult_preco_cent"], d["qt_atual"])
            if f.get("situacao") and d["situacao"] != f["situacao"]:
                continue
            if f.get("valor") is not None and f.get("valor") != "":
                lim = int(f["valor"])
                if (d["total_cent"] < lim) if f.get("verifica_valores", "maior") == "maior" else (d["total_cent"] > lim):
                    continue
            dados.append(d)
            rel.add(d["codigo"], d["nome"], Q(d["estoque_minimo"]), Q(d["qt_atual"]), M(d["ult_preco_cent"]),
                    M(d["total_cent"]), d["un"])
            total += max(d["total_cent"], 0)
        rel.rodape = [("Produtos listados", str(len(dados))), ("Valor total em estoque (custo)", M(total))]
        return rel, dados

    def formulario_contagem(self) -> Relatorio:
        rel = Relatorio("Formulário de contagem", [Coluna("Código", 13), Coluna("Produto", 32), Coluna("Un", 4),
                                                   Coluna("Contagem", 12)])
        for r in self.banco.todos(
                """SELECT pr.codigo, pr.nome, u.abreviatura AS un FROM produtos pr JOIN unidades u ON u.id = pr.unidade_id
                   WHERE pr.controla_estoque = 1 AND pr.ativo = 1 ORDER BY pr.nome"""):
            rel.add(r["codigo"], r["nome"], r["un"], "__________")
        return rel

    def formulario_pedidos(self, somente_abaixo_do_minimo: bool = False) -> Relatorio:
        rel = Relatorio("Formulário de pedidos", [Coluna("Código", 13), Coluna("Produto", 30), Coluna("Mínimo", 9, "d"),
                                                  Coluna("Atual", 9, "d"), Coluna("Pedir", 10)])
        for r in self.banco.todos(
                "SELECT codigo, nome, estoque_minimo, qt_atual FROM produtos WHERE controla_estoque = 1 AND ativo = 1 ORDER BY nome"):
            if somente_abaixo_do_minimo and r["qt_atual"] > r["estoque_minimo"]:
                continue
            rel.add(r["codigo"], r["nome"], Q(r["estoque_minimo"]), Q(r["qt_atual"]), "________")
        return rel

    def movimento_estoque(self, f: dict) -> Relatorio:
        """Todas as movimentações exceto vendas, por período, tipo ou fornecedor."""
        onde, p = ["1=1"], []
        if f.get("de"): onde.append("l.data >= ?"); p.append(f["de"])
        if f.get("ate"): onde.append("l.data <= ?"); p.append(f["ate"])
        if f.get("tipo"): onde.append("l.tipo = ?"); p.append(f["tipo"])
        if f.get("fornecedor_id"): onde.append("l.fornecedor_id = ?"); p.append(f["fornecedor_id"])
        rel = Relatorio("Movimento de estoque", [
            Coluna("Data", 10), Coluna("Tipo", 10), Coluna("Fornecedor", 14), Coluna("Produto", 24), Coluna("Un", 4),
            Coluna("Quantidade", 10, "d"), Coluna("Unitário", 9, "d"), Coluna("Total", 11, "d")])
        total = 0
        for r in self.banco.todos(
                f"""SELECT l.data, l.tipo, f.nome AS fornecedor, pr.nome, u.abreviatura AS un, i.quantidade,
                           i.preco_unit_cent, i.valor_cent, i.diferenca
                    FROM itens_estoque i JOIN lancamentos_estoque l ON l.id = i.lancamento_id
                    JOIN produtos_historico pr ON pr.id = i.produto_id JOIN unidades u ON u.id = pr.unidade_id
                    LEFT JOIN fornecedores f ON f.id = l.fornecedor_id
                    WHERE {' AND '.join(onde)} ORDER BY l.data, l.id, i.id""", p):
            qt = r["diferenca"] if r["tipo"] == "contagem" else r["quantidade"]
            rel.add(fmt.fmt_data(r["data"]), r["tipo"], r["fornecedor"], r["nome"], r["un"], Q(qt),
                    M(r["preco_unit_cent"]), M(r["valor_cent"]))
            total += r["valor_cent"]
        rel.rodape = [("Total lançado", M(total))]
        return rel

    def posicao_estoque_periodo(self, f: dict) -> Relatorio:
        """Posição do estoque da versão web: para cada produto, soma de cada tipo de movimento no período."""
        onde, p = ["1=1"], []
        if f.get("de"): onde.append("date(m.criado_em) >= ?"); p.append(f["de"])
        if f.get("ate"): onde.append("date(m.criado_em) <= ?"); p.append(f["ate"])
        tipos = ["inicial", "compra", "entrada", "saida", "descarte", "contagem", "desc_acabados", "venda", "estorno_venda"]
        rel = Relatorio("Relatório de estoque", [Coluna("Produto", 24), Coluna("Final", 8, "d")] +
                        [Coluna(t[:8], 8, "d") for t in tipos])
        for r in self.banco.todos(
                f"""SELECT pr.nome, pr.qt_atual, {', '.join(f"COALESCE(SUM(CASE WHEN m.tipo = '{t}' THEN m.quantidade END),0) AS {t}" for t in tipos)}
                    FROM produtos_historico pr LEFT JOIN movimentos_estoque m ON m.produto_id = pr.id AND {' AND '.join(onde)}
                    WHERE pr.controla_estoque = 1 GROUP BY pr.id ORDER BY pr.nome""", p):
            rel.add(r["nome"], Q(r["qt_atual"]), *[Q(r[t]) for t in tipos])
        return rel

    def custo_medio(self, f: dict) -> Relatorio:
        """Preço médio pago por produto e fornecedor nas compras do período."""
        onde, p = ["l.tipo = 'compra'"], []
        if f.get("de"): onde.append("l.data >= ?"); p.append(f["de"])
        if f.get("ate"): onde.append("l.data <= ?"); p.append(f["ate"])
        if f.get("fornecedor_id"): onde.append("l.fornecedor_id = ?"); p.append(f["fornecedor_id"])
        rel = Relatorio("Preço médio dos produtos", [Coluna("Fornecedor", 18), Coluna("Produto", 28), Coluna("Un", 4),
                                                     Coluna("Quantidade", 11, "d"), Coluna("Preço médio", 11, "d"),
                                                     Coluna("Total", 12, "d")])
        for r in self.banco.todos(
                f"""SELECT f.nome AS fornecedor, pr.nome, u.abreviatura AS un, SUM(i.quantidade) AS qt,
                           SUM(i.valor_cent - i.desconto_cent) AS tot
                    FROM itens_estoque i JOIN lancamentos_estoque l ON l.id = i.lancamento_id
                    JOIN produtos_historico pr ON pr.id = i.produto_id JOIN unidades u ON u.id = pr.unidade_id
                    LEFT JOIN fornecedores f ON f.id = l.fornecedor_id WHERE {' AND '.join(onde)}
                    GROUP BY f.id, pr.id ORDER BY f.nome, pr.nome""", p):
            rel.add(r["fornecedor"], r["nome"], r["un"], Q(r["qt"]), M(fmt.dividir_cent(r["tot"], r["qt"])), M(r["tot"]))
        return rel

    # ----------------------------------------------------------- clientes
    def clientes_inativos(self, desde: str, ate: str | None = None) -> Relatorio:
        """Clientes (caderneta/delivery) que não consumiram no período."""
        ate = ate or fmt.hoje()
        rel = Relatorio("Clientes inativos", [Coluna("Nº", 8), Coluna("Cliente", 28), Coluna("Telefone", 14),
                                              Coluna("Última compra", 13), Coluna("Saldo", 11, "d")],
                        criterios=[f"Sem consumo de {fmt.fmt_data(desde)} a {fmt.fmt_data(ate)}"])
        for r in self.banco.todos(
                """SELECT c.numero_consulta, c.nome, c.telefone, c.saldo_cent,
                          (SELECT date(MAX(v.fechada_em)) FROM vendas v WHERE v.cliente_id = c.id
                           AND v.status = 'fechada' AND v.subtotal_cent > 0) AS ultima
                   FROM clientes c WHERE c.ativo = 1 AND NOT EXISTS (
                       SELECT 1 FROM vendas v WHERE v.cliente_id = c.id AND v.status = 'fechada' AND v.subtotal_cent > 0
                       AND v.fechada_em >= ? AND v.fechada_em < ?) ORDER BY c.nome""", (desde, fmt.somar_dias(ate, 1))):
            rel.add(r["numero_consulta"], r["nome"], r["telefone"], fmt.fmt_data(r["ultima"]) or "nunca", M(r["saldo_cent"]))
        return rel

    def clientes_resumo(self, f: dict) -> Relatorio:
        """Entrega, consumo em caderneta, pagamentos e saldo por cliente."""
        onde, p = ["1=1"], []
        if f.get("de"): onde.append("v.fechada_em >= ?"); p.append(f["de"])
        if f.get("ate"): onde.append("v.fechada_em < ?"); p.append(fmt.somar_dias(f["ate"], 1))
        rel = Relatorio("Vendas por clientes", [Coluna("Nº", 8), Coluna("Cliente", 24), Coluna("Entrega", 11, "d"),
                                                Coluna("Consumo", 11, "d"), Coluna("Pagamento", 11, "d"), Coluna("Saldo", 11, "d")])
        for r in self.banco.todos(
                f"""SELECT c.numero_consulta, c.nome, c.saldo_cent,
                    COALESCE(SUM(CASE WHEN v.modalidade = 'entrega' AND v.subtotal_cent > 0 THEN v.total_cent END),0) AS entrega,
                    COALESCE(SUM(CASE WHEN v.modalidade = 'caderneta' AND v.subtotal_cent > 0 THEN v.total_cent END),0) AS consumo,
                    COALESCE(SUM(CASE WHEN v.modalidade = 'caderneta' AND v.subtotal_cent = 0 THEN v.total_cent END),0) AS pagto
                    FROM clientes c JOIN vendas v ON v.cliente_id = c.id AND v.status = 'fechada' AND {' AND '.join(onde)}
                    GROUP BY c.id ORDER BY c.nome""", p):
            rel.add(r["numero_consulta"], r["nome"], M(r["entrega"]), M(r["consumo"]), M(r["pagto"]), M(r["saldo_cent"]))
        return rel

    # --------------------------------------------------------- financeiro
    @staticmethod
    def _grupo_plano(codigo: str, debito: int, resultado: int) -> str:
        if not resultado:
            return "financeiro"
        if not debito:
            return "credito"
        return "provisao" if str(codigo).startswith("3.") else "debito"

    def resultado_financeiro(self, f: dict) -> Relatorio:
        """Demonstrativo por plano de contas. Filtros: de/ate, por ('dt_quitacao'|'dt_entrada'|'dt_vencimento'),
        apenas_resultado, apenas_debitos, plano_id, subplano_id, incluir_previsao, incluir_vendas."""
        por = f.get("por") or "dt_quitacao"
        onde, p = ["1=1"], []
        if f.get("de"): onde.append(f"c.{por} >= ?"); p.append(f["de"])
        if f.get("ate"): onde.append(f"c.{por} <= ?"); p.append(f["ate"])
        if por == "dt_quitacao": onde.append("c.dt_quitacao IS NOT NULL")
        if not f.get("incluir_previsao"): onde.append("c.previsao = 0")
        if f.get("apenas_resultado"): onde.append("pl.resultado = 1")
        if f.get("apenas_debitos"): onde.append("pl.debito = 1")
        if f.get("plano_id"): onde.append("pl.id = ?"); p.append(f["plano_id"])
        if f.get("subplano_id"): onde.append("sp.id = ?"); p.append(f["subplano_id"])
        linhas = [dict(r) for r in self.banco.todos(
            f"""SELECT pl.id AS plano_id, pl.nome AS plano, pl.codigo, pl.debito, pl.resultado, sp.nome AS subplano,
                       SUM(c.valor_cent) AS tot FROM contas c JOIN subplanos sp ON sp.id = c.subplano_id
                JOIN planos_contas pl ON pl.id = sp.plano_id WHERE {' AND '.join(onde)}
                GROUP BY sp.id ORDER BY pl.ordem, pl.nome, sp.nome""", p)]
        vendas = 0
        if f.get("incluir_vendas", True) and not f.get("apenas_debitos") and not f.get("plano_id") and not f.get("subplano_id"):
            ov, pv = ["status = 'fechada'", "subtotal_cent > 0"], []
            if f.get("de"): ov.append("fechada_em >= ?"); pv.append(f["de"])
            if f.get("ate"): ov.append("fechada_em < ?"); pv.append(fmt.somar_dias(f["ate"], 1))
            vendas = self.banco.valor(f"SELECT COALESCE(SUM(total_cent),0) FROM vendas WHERE {' AND '.join(ov)}", pv, 0)
        grupos: dict = {"credito": [], "debito": [], "provisao": [], "financeiro": []}
        for ln in linhas:
            grupos[self._grupo_plano(ln["codigo"], ln["debito"], ln["resultado"])].append(ln)
        rel = Relatorio("Resultado financeiro", [Coluna("Plano / Sub plano", 38), Coluna("Valor", 14, "d"), Coluna("% s/ créditos", 12, "d")],
                        criterios=[f"Período: {fmt.fmt_data(f.get('de')) or '...'} a {fmt.fmt_data(f.get('ate')) or '...'}",
                                   {"dt_quitacao": "Por data de quitação", "dt_entrada": "Por data de entrada",
                                    "dt_vencimento": "Por data de vencimento"}[por]])
        credito = vendas + sum(l["tot"] for l in grupos["credito"])

        def pct(v):
            return Q(v * 100 / credito, 2) if credito else ""

        def bloco(titulo, itens, extra=None):
            rel.add(titulo, "", "", estilo="secao")
            plano_atual = None
            soma = 0
            for l in itens:
                if l["plano"] != plano_atual:
                    plano_atual = l["plano"]
                    rel.add(plano_atual, M(sum(x["tot"] for x in itens if x["plano"] == plano_atual)),
                            pct(sum(x["tot"] for x in itens if x["plano"] == plano_atual)))
                rel.add("    " + l["subplano"], M(l["tot"]), "")
                soma += l["tot"]
            if extra:
                rel.add(extra[0], M(extra[1]), pct(extra[1]))
                soma += extra[1]
            return soma

        c = bloco("Créditos", grupos["credito"], ("Vendas (PDV, cupons fechados)", vendas) if vendas else None)
        rel.add("Total de créditos", M(c), "100,00" if c else "", estilo="subtotal")
        d = bloco("Débitos", grupos["debito"])
        rel.add("Total de débitos", M(d), pct(d), estilo="subtotal")
        rel.add("Resultado operacional", M(c - d), pct(c - d), estilo="total")
        if grupos["provisao"]:
            pr = bloco("Provisões", grupos["provisao"])
            rel.add("Resultado operacional líquido", M(c - d - pr), pct(c - d - pr), estilo="total")
        if grupos["financeiro"]:
            bloco("Movimentação financeira (não afeta o resultado)", grupos["financeiro"])
        return rel

    def extrato_contas(self, f: dict) -> Relatorio:
        """Saldo de cada conta (tipo financeiro): saldo inicial + recebimentos de vendas + contas quitadas."""
        de, ate = f.get("de"), f.get("ate") or fmt.hoje()
        rel = Relatorio("Extrato de contas", [Coluna("Conta", 26), Coluna("Saldo anterior", 14, "d"), Coluna("Entradas", 13, "d"),
                                              Coluna("Saídas", 13, "d"), Coluna("Saldo", 14, "d")],
                        criterios=[f"Até {fmt.fmt_data(ate)}" if not de else f"De {fmt.fmt_data(de)} até {fmt.fmt_data(ate)}"])

        def movimentos(tid, ini, fim):
            entra = sai = 0
            vend = self.banco.valor(
                """SELECT COALESCE(SUM(p.valor_cent - p.troco_cent),0) FROM pagamentos_venda p JOIN vendas v ON v.id = p.venda_id
                   WHERE p.tipo_pagamento_id = ? AND v.status = 'fechada' AND v.fechada_em >= ? AND v.fechada_em < ?""",
                (tid, ini, fmt.somar_dias(fim, 1)), 0)
            entra += vend
            for r in self.banco.todos(
                    """SELECT pl.debito, SUM(c.valor_cent) AS tot FROM contas c JOIN subplanos sp ON sp.id = c.subplano_id
                       JOIN planos_contas pl ON pl.id = sp.plano_id WHERE c.tipo_pagamento_id = ? AND c.dt_quitacao IS NOT NULL
                       AND c.dt_quitacao >= ? AND c.dt_quitacao <= ? GROUP BY pl.debito""", (tid, ini, fim)):
                if r["debito"]: sai += r["tot"]
                else: entra += r["tot"]
            return entra, sai

        tot = [0, 0, 0, 0]
        for t in self.banco.todos("SELECT id, tipo, saldo_inicial_cent FROM tipos_pagamento WHERE ativo = 1 ORDER BY ordem, tipo"):
            anterior = t["saldo_inicial_cent"]
            if de:
                e0, s0 = movimentos(t["id"], "0000-01-01", fmt.somar_dias(de, -1))
                anterior += e0 - s0
            ent, sai = movimentos(t["id"], de or "0000-01-01", ate)
            saldo = anterior + ent - sai
            if anterior == ent == sai == 0:
                continue
            rel.add(t["tipo"], M(anterior), M(ent), M(sai), M(saldo))
            for i, v in enumerate((anterior, ent, sai, saldo)):
                tot[i] += v
        rel.add("TOTAL", *[M(v) for v in tot], estilo="total")
        return rel
