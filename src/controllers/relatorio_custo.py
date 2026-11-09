"""Relatórios de custo e lucro. Reusa o custo congelado na venda (`itens_venda_custos`) e o custo médio do produto.

O realizado de uma nota de compra não é o médio de hoje: as vendas entram na ordem, da mais antiga
para a mais nova, e cada nota absorve a quantidade que ainda cabia nela. O lucro dessa parte usa o
custo da própria nota. O que não vendeu fica só na previsão, pelo preço de venda atual.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from src.core import custo_lucro
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.core.relatorio import Coluna, Relatorio

M, Q = fmt.fmt_num, fmt.fmt_qtd


def _periodo(f: dict) -> tuple[list[str], list]:
    onde, p = ["v.status = 'fechada'", "i.cancelado = 0"], []
    if f.get("de"):
        onde.append("v.fechada_em >= ?")
        p.append(f["de"] if " " in str(f["de"]) else f["de"] + " 00:00:00")
    if f.get("ate"):
        onde.append("v.fechada_em < ?")
        p.append(fmt.somar_dias(str(f["ate"])[:10], 1) + " 00:00:00")
    if f.get("produto_id"):
        onde.append("i.produto_id = ?")
        p.append(f["produto_id"])
    if f.get("grupo_id"):
        onde.append("g.id = ?")
        p.append(f["grupo_id"])
    if f.get("fornecedor_id"):
        onde.append(
            "EXISTS (SELECT 1 FROM itens_estoque ie JOIN lancamentos_estoque l ON l.id = ie.lancamento_id "
            "WHERE ie.produto_id = i.produto_id AND l.tipo = 'compra' AND l.fornecedor_id = ?)")
        p.append(f["fornecedor_id"])
    return onde, p


class RelatoriosCusto:
    def _exigir(self) -> None:
        from src.controllers.acesso_controller import AcessoController
        from src.core.erros import ErroPermissao
        operador_id = getattr(self, "operador_id", None)
        if type(operador_id) is not int:
            operador_id = getattr(self.banco, "_operador_auditoria", None)
        acesso = AcessoController(self.banco)
        linha = (self.banco.um("SELECT * FROM operadores WHERE id = ? AND ativo = 1", (operador_id,))
                 if type(operador_id) is int else None)
        if linha is None or not acesso.pode(acesso.operador(linha["id"]), "rel_custo"):
            raise ErroPermissao("Custo e lucro só aparecem para o gerente.")

    def lucro_periodo(self, f: dict) -> Relatorio:
        self._exigir()
        onde, p = _periodo(f or {})
        junta = ("FROM itens_venda i JOIN vendas v ON v.id = i.venda_id "
                 "JOIN produtos_historico pr ON pr.id = i.produto_id "
                 "JOIN subgrupos s ON s.id = pr.subgrupo_id JOIN grupos g ON g.id = s.grupo_id "
                 "LEFT JOIN itens_venda_custos c ON c.item_id = i.id "
                 f"WHERE {' AND '.join(onde)}")
        itens = self.banco.um(
            f"""SELECT COALESCE(SUM(i.total_cent),0) AS venda, COALESCE(SUM(c.custo_cent),0) AS custo,
                       SUM(CASE WHEN c.item_id IS NULL THEN 1 ELSE 0 END) AS sem_custo {junta}""", p)
        vendas = self.banco.um(
            f"""SELECT COALESCE(SUM(v.total_cent),0) AS bruto, COALESCE(SUM(v.desconto_cent),0) AS desconto,
                       COUNT(DISTINCT v.id) AS n
                FROM vendas v WHERE v.status = 'fechada' AND v.id IN (
                    SELECT i.venda_id {junta})""", p)
        bruto, desconto = int(vendas["bruto"] or 0), int(vendas["desconto"] or 0)
        venda_itens, custo = int(itens["venda"] or 0), int(itens["custo"] or 0)
        lucro = custo_lucro.lucro_cent(venda_itens, custo)
        rel = Relatorio("Lucro do período", [Coluna("Indicador", 36), Coluna("Valor", 16, "d")],
                        criterios=["Custo = valor congelado na venda. Venda dos itens não inclui taxa nem serviço."])
        rel.add("Vendas (total do cupom)", M(bruto))
        rel.add("Descontos", M(desconto))
        rel.add("Venda dos itens", M(venda_itens))
        rel.add("Custo da mercadoria vendida", M(custo))
        rel.add("Lucro bruto", M(lucro), estilo="total")
        rel.add("Margem sobre os itens", custo_lucro.margem_texto(venda_itens, custo))
        rel.rodape = [("Cupons", str(vendas["n"] or 0)),
                      ("Itens sem custo cadastrado", str(itens["sem_custo"] or 0))]
        return rel

    def ranking_lucro(self, f: dict) -> Relatorio:
        self._exigir()
        onde, p = _periodo(f or {})
        rel = Relatorio("Produtos por lucro", [Coluna("Produto", 28), Coluna("Qtd", 8, "d"),
                                               Coluna("Venda", 12, "d"), Coluna("Custo", 12, "d"),
                                               Coluna("Lucro", 12, "d"), Coluna("Margem", 8, "d")])
        linhas = []
        for r in self.banco.todos(
                f"""SELECT pr.nome, SUM(i.quantidade) AS qtd, SUM(i.total_cent) AS venda,
                           SUM(COALESCE(c.custo_cent, 0)) AS custo
                    FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
                    JOIN produtos_historico pr ON pr.id = i.produto_id
                    JOIN subgrupos s ON s.id = pr.subgrupo_id JOIN grupos g ON g.id = s.grupo_id
                    LEFT JOIN itens_venda_custos c ON c.item_id = i.id
                    WHERE {' AND '.join(onde)} GROUP BY pr.id ORDER BY (SUM(i.total_cent) - SUM(COALESCE(c.custo_cent, 0))) DESC""",
                p):
            linhas.append(r)
        for r in linhas:
            rel.add(r["nome"], Q(r["qtd"]), M(r["venda"]), M(r["custo"]),
                    M(custo_lucro.lucro_cent(r["venda"], r["custo"])),
                    custo_lucro.margem_texto(r["venda"], r["custo"]))
        if linhas:
            pior = linhas[-1]
            rel.rodape = [("Mais lucrativo", linhas[0]["nome"]), ("Menos lucrativo", pior["nome"])]
        return rel

    def alerta_custo(self, f: dict) -> Relatorio:
        self._exigir()
        onde, p = _periodo(f or {})
        rel = Relatorio("Vendido abaixo do custo ou sem custo", [
            Coluna("Cupom", 8), Coluna("Produto", 24), Coluna("Venda", 12, "d"), Coluna("Custo", 12, "d"),
            Coluna("Situação", 16)])
        for r in self.banco.todos(
                f"""SELECT v.cupom, pr.nome, i.total_cent, c.custo_cent
                    FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
                    JOIN produtos_historico pr ON pr.id = i.produto_id
                    JOIN subgrupos s ON s.id = pr.subgrupo_id JOIN grupos g ON g.id = s.grupo_id
                    LEFT JOIN itens_venda_custos c ON c.item_id = i.id
                    WHERE {' AND '.join(onde)} AND (c.custo_cent IS NULL OR i.total_cent < c.custo_cent)
                    ORDER BY v.cupom""", p):
            situacao = "sem custo" if r["custo_cent"] is None else "abaixo do custo"
            rel.add(r["cupom"], r["nome"], M(r["total_cent"]), M(r["custo_cent"] or 0), situacao)
        rel.rodape = [("Ocorrências", str(len(rel.linhas)))]
        return rel

    def curva_abc(self, f: dict) -> Relatorio:
        self._exigir()
        onde, p = _periodo(f or {})
        linhas = [dict(r) for r in self.banco.todos(
            f"""SELECT pr.nome, SUM(i.total_cent) - SUM(COALESCE(c.custo_cent, 0)) AS lucro
                FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
                JOIN produtos_historico pr ON pr.id = i.produto_id
                JOIN subgrupos s ON s.id = pr.subgrupo_id JOIN grupos g ON g.id = s.grupo_id
                LEFT JOIN itens_venda_custos c ON c.item_id = i.id
                WHERE {' AND '.join(onde)} GROUP BY pr.id
                HAVING SUM(i.total_cent) - SUM(COALESCE(c.custo_cent, 0)) > 0
                ORDER BY lucro DESC""", p)]
        total = sum(int(r["lucro"]) for r in linhas) or 1
        acumulado = 0
        rel = Relatorio("Curva ABC pelo lucro", [Coluna("Produto", 28), Coluna("Lucro", 12, "d"),
                                                 Coluna("% acum.", 10, "d"), Coluna("Classe", 8)])
        for r in linhas:
            acumulado += int(r["lucro"])
            pct = acumulado * 10000 // total
            classe = "A" if pct <= 8000 else "B" if pct <= 9500 else "C"
            rel.add(r["nome"], M(r["lucro"]), f"{pct // 100},{pct % 100:02d}%", classe)
        rel.criterios = ["A até 80% do lucro, B até 95%, C o restante. Itens com lucro zero ou negativo ficam de fora."]
        return rel

    def giro_estoque(self, f: dict) -> Relatorio:
        self._exigir()
        f = f or {}
        onde, p = ["pr.ativo = 1", "pr.controla_estoque = 1"], []
        if f.get("grupo_id"):
            onde.append("g.id = ?")
            p.append(f["grupo_id"])
        if f.get("produto_id"):
            onde.append("pr.id = ?")
            p.append(f["produto_id"])
        venda_onde, venda_p = ["v.status = 'fechada'", "i.cancelado = 0"], []
        if f.get("de"):
            venda_onde.append("v.fechada_em >= ?")
            venda_p.append(str(f["de"])[:10] + " 00:00:00")
        if f.get("ate"):
            venda_onde.append("v.fechada_em < ?")
            venda_p.append(fmt.somar_dias(str(f["ate"])[:10], 1) + " 00:00:00")
        rel = Relatorio("Giro e valor do estoque", [
            Coluna("Produto", 22), Coluna("Saldo", 8, "d"), Coluna("Vendido", 8, "d"),
            Coluna("Giro", 8, "d"), Coluna("A custo", 12, "d"), Coluna("A venda", 12, "d")])
        custo_total = venda_total = 0
        for r in self.banco.todos(
                f"""SELECT pr.id, pr.nome, pr.qt_atual, pr.preco_cent, pr.custo_medio_cent, pr.ult_preco_cent,
                           (SELECT COALESCE(SUM(i.quantidade), 0) FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
                            WHERE i.produto_id = pr.id AND {' AND '.join(venda_onde)}) AS vendido
                    FROM produtos pr JOIN subgrupos s ON s.id = pr.subgrupo_id JOIN grupos g ON g.id = s.grupo_id
                    WHERE {' AND '.join(onde)} ORDER BY pr.nome""", venda_p + p):
            custo = custo_lucro.custo_vigente(r["custo_medio_cent"], r["ult_preco_cent"])
            a_custo = fmt.mult_cent(custo, r["qt_atual"]) if r["qt_atual"] > 0 else 0
            a_venda = fmt.mult_cent(r["preco_cent"], r["qt_atual"]) if r["qt_atual"] > 0 else 0
            custo_total += a_custo
            venda_total += a_venda
            rel.add(r["nome"], Q(r["qt_atual"]), Q(r["vendido"]), _giro(r["vendido"], r["qt_atual"]),
                    M(a_custo), M(a_venda))
        rel.rodape = [("Estoque a custo", M(custo_total)), ("Estoque a preço de venda", M(venda_total))]
        rel.criterios = ["Giro = quantidade vendida no período ÷ saldo de hoje. Valor só do saldo positivo."]
        return rel

    def lucro_calendario(self, f: dict) -> Relatorio:
        self._exigir()
        f = f or {}
        onde, p = _periodo(f)
        grupo = _agrupar(f.get("agrupar"))
        expressao = {
            "dia": "date(v.fechada_em)",
            "semana": "strftime('%Y-%W', v.fechada_em)",
            "mes": "strftime('%Y-%m', v.fechada_em)",
        }[grupo]
        titulo = {"dia": "Lucro por dia", "semana": "Lucro por semana", "mes": "Lucro por mês"}[grupo]
        rotulo = {"dia": "Dia", "semana": "Semana", "mes": "Mês"}[grupo]
        rel = Relatorio(titulo, [Coluna(rotulo, 12), Coluna("Venda", 12, "d"),
                                 Coluna("Custo", 12, "d"), Coluna("Lucro", 12, "d")],
                        criterios=["Semana começa na segunda (ano-número). Mês é ano-mês."])
        for r in self.banco.todos(
                f"""SELECT {expressao} AS periodo, SUM(i.total_cent) AS venda, SUM(COALESCE(c.custo_cent, 0)) AS custo
                    FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
                    JOIN produtos_historico pr ON pr.id = i.produto_id
                    JOIN subgrupos s ON s.id = pr.subgrupo_id JOIN grupos g ON g.id = s.grupo_id
                    LEFT JOIN itens_venda_custos c ON c.item_id = i.id
                    WHERE {' AND '.join(onde)} GROUP BY periodo ORDER BY periodo""", p):
            quando = fmt.fmt_data(r["periodo"]) if grupo == "dia" else r["periodo"]
            rel.add(quando, M(r["venda"]), M(r["custo"]),
                    M(custo_lucro.lucro_cent(r["venda"], r["custo"])))
        return rel

    def lucro_forma(self, f: dict) -> Relatorio:
        """O lucro do cupom é repartido entre as formas na proporção do valor pago em cada uma."""
        self._exigir()
        f = f or {}
        onde, params = ["v.status = 'fechada'"], []
        if f.get("de"):
            onde.append("v.fechada_em >= ?")
            params.append(str(f["de"])[:10] + " 00:00:00")
        if f.get("ate"):
            onde.append("v.fechada_em < ?")
            params.append(fmt.somar_dias(str(f["ate"])[:10], 1) + " 00:00:00")
        por_forma: dict[str, int] = {}
        for v in self.banco.todos(
                f"""SELECT v.id, v.total_cent,
                           (SELECT COALESCE(SUM(i.total_cent),0) FROM itens_venda i
                            WHERE i.venda_id = v.id AND i.cancelado = 0) AS venda,
                           (SELECT COALESCE(SUM(c.custo_cent),0) FROM itens_venda_custos c
                            JOIN itens_venda i ON i.id = c.item_id
                            WHERE i.venda_id = v.id AND i.cancelado = 0) AS custo
                    FROM vendas v WHERE {' AND '.join(onde)}""", params):
            lucro = custo_lucro.lucro_cent(v["venda"], v["custo"])
            pagamentos = self.banco.todos(
                """SELECT t.tipo, p.valor_cent FROM pagamentos_venda p
                   JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id WHERE p.venda_id = ?""", (v["id"],))
            pago = sum(int(p["valor_cent"]) for p in pagamentos) or 1
            for pag in pagamentos:
                parte = fmt.arredondar(fmt._dec(lucro) * fmt._dec(pag["valor_cent"]) / fmt._dec(pago))
                por_forma[pag["tipo"]] = por_forma.get(pag["tipo"], 0) + parte
        rel = Relatorio("Lucro por forma de pagamento", [Coluna("Forma", 24), Coluna("Lucro atribuído", 16, "d")],
                        criterios=["O lucro do cupom acompanha a forma na proporção do que foi pago nela."])
        for nome, valor in sorted(por_forma.items(), key=lambda par: -par[1]):
            rel.add(nome, M(valor))
        return rel

    def compras_fornecedor(self, f: dict) -> Relatorio:
        self._exigir()
        f = f or {}
        onde, p = ["l.tipo = 'compra'"], []
        if f.get("de"):
            onde.append("l.data >= ?")
            p.append(str(f["de"])[:10])
        if f.get("ate"):
            onde.append("l.data <= ?")
            p.append(str(f["ate"])[:10])
        if f.get("fornecedor_id"):
            onde.append("l.fornecedor_id = ?")
            p.append(f["fornecedor_id"])
        rel = Relatorio("Compras por fornecedor", [Coluna("Fornecedor", 28), Coluna("Notas", 8, "d"),
                                                   Coluna("Total", 14, "d")])
        for r in self.banco.todos(
                f"""SELECT COALESCE(f.nome, 'Sem fornecedor') AS nome, COUNT(DISTINCT l.id) AS notas,
                           COALESCE(SUM(i.valor_cent - i.desconto_cent), 0) AS total
                    FROM lancamentos_estoque l JOIN itens_estoque i ON i.lancamento_id = l.id
                    LEFT JOIN fornecedores f ON f.id = l.fornecedor_id
                    WHERE {' AND '.join(onde)} GROUP BY f.id ORDER BY total DESC""", p):
            rel.add(r["nome"], r["notas"], M(r["total"]))
        return rel

    def perdas_cascos(self, f: dict) -> Relatorio:
        self._exigir()
        f = f or {}
        onde, p = ["(l.tipo IN ('descarte', 'saida') OR l.tipo_perda IN ('quebra', 'oxidacao', 'devolucao'))"], []
        if f.get("de"):
            onde.append("l.data >= ?")
            p.append(str(f["de"])[:10])
        if f.get("ate"):
            onde.append("l.data <= ?")
            p.append(str(f["ate"])[:10])
        rel = Relatorio("Perdas, quebras e cascos", [Coluna("Tipo", 20), Coluna("Quantidade", 12, "d"),
                                                     Coluna("Valor", 14, "d")])
        for r in self.banco.todos(
                f"""SELECT COALESCE(l.tipo_perda, l.tipo) AS tipo, SUM(i.quantidade) AS qtd,
                           SUM(i.valor_cent) AS valor
                    FROM itens_estoque i JOIN lancamentos_estoque l ON l.id = i.lancamento_id
                    WHERE {' AND '.join(onde)} GROUP BY tipo ORDER BY tipo""", p):
            rel.add(r["tipo"], Q(r["qtd"]), M(r["valor"]))
        cascos_onde, cp = ["v.status = 'fechada'", "i.cancelado = 0", "i.cascos_emprestados > 0"], []
        if f.get("de"):
            cascos_onde.append("v.fechada_em >= ?")
            cp.append(str(f["de"])[:10] + " 00:00:00")
        if f.get("ate"):
            cascos_onde.append("v.fechada_em < ?")
            cp.append(fmt.somar_dias(str(f["ate"])[:10], 1) + " 00:00:00")
        cascos = self.banco.valor(
            f"""SELECT COALESCE(SUM(i.cascos_emprestados), 0) FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
                WHERE {' AND '.join(cascos_onde)}""", cp, 0)
        rel.add("Cascos emprestados", Q(cascos), M(0))
        rel.criterios = ["Casco emprestado não tem valor de perda aqui: é quantidade que saiu sem voltar."]
        return rel

    def resumo_nota(self, lanc_id: int) -> dict:
        """Previsto pela nota inteira e realizado pelo que as vendas já cobriram dela."""
        self._exigir()
        from src.controllers.estoque_controller import EstoqueController
        est = EstoqueController(self.banco)
        lanc = est.lancamento(lanc_id)
        if lanc["tipo"] != "compra":
            raise ErroNegocio("O resumo de lucro é de nota de compra.")
        itens = est.itens(lanc_id)
        custo = venda = 0
        realizados = []
        for item in itens:
            liquido = max(int(item["valor_cent"]) - int(item["desconto_cent"]), 0)
            produto = self.banco.um("SELECT preco_cent FROM produtos WHERE id = ?", (item["produto_id"],))
            preco = int(produto["preco_cent"]) if produto else 0
            previsto = fmt.mult_cent(preco, item["quantidade"])
            custo += liquido
            venda += previsto
            compras = [dict(r) for r in self.banco.todos(
                """SELECT i.id, i.quantidade AS qtd, (i.valor_cent - i.desconto_cent) AS custo_cent
                   FROM itens_estoque i JOIN lancamentos_estoque l ON l.id = i.lancamento_id
                   WHERE i.produto_id = ? AND l.tipo = 'compra' AND i.aplicado = 1
                   ORDER BY l.data, i.id""", (item["produto_id"],))]
            vendas = [dict(r) for r in self.banco.todos(
                """SELECT i.quantidade AS qtd, i.total_cent AS receita_cent
                   FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
                   WHERE i.produto_id = ? AND i.cancelado = 0 AND v.status = 'fechada'
                   ORDER BY v.fechada_em, i.id""", (item["produto_id"],))]
            parte = custo_lucro.alocar_fifo(compras, vendas).get(item["id"], {
                "qtd_vendida": 0, "receita_cent": 0, "custo_cent": 0, "lucro_cent": 0})
            realizados.append(parte)
        receita = sum(p["receita_cent"] for p in realizados)
        custo_real = sum(p["custo_cent"] for p in realizados)
        return {
            "custo_cent": custo,
            "venda_prevista_cent": venda,
            "lucro_previsto_cent": custo_lucro.lucro_cent(venda, custo),
            "margem_prevista": custo_lucro.margem_texto(venda, custo),
            "qtd_vendida": sum(p["qtd_vendida"] for p in realizados),
            "receita_cent": receita,
            "lucro_realizado_cent": receita - custo_real,
            "margem_realizada": custo_lucro.margem_texto(receita, custo_real),
        }


def _agrupar(valor) -> str:
    chave = str(valor or "dia").strip().casefold().replace("ê", "e")
    return chave if chave in ("dia", "semana", "mes") else "dia"


def _giro(vendido, saldo) -> str:
    base = Decimal(str(saldo or 0))
    if base <= 0:
        return "—"
    razao = (Decimal(str(vendido or 0)) / base).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{razao:.2f}".replace(".", ",")


# O RelatorioController herda os métodos. O banco vem de lá.
RelatoriosCusto.banco = None
