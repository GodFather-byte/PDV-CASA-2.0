"""Relatórios de vendas e de caixa (manual ADM seção 6.01 a 6.11 e versão web):
venda no período, por grupo e produto mais vendido, entradas/saídas do caixa, fechamentos, comandas, garçons,
C.M.V., comissões, informativo por dia, por hora e cancelados."""
from __future__ import annotations

from src.controllers.produto_controller import ProdutoController
from src.controllers.turno_controller import TurnoController
from src.core import formatacao as fmt
from src.core.posicao import rotulo as rotulo_posicao
from src.core.relatorio import Coluna, Relatorio

M, Q = fmt.fmt_num, fmt.fmt_qtd


def _hora(h: str | None) -> str | None:
    if not h:
        return None
    h = fmt.para_hora(h)
    return h + ":00"



def virada_dia(banco) -> int:
    """Hora em que o dia operacional vira (configuração `virada_dia_hora`, 0 a 23; 6 = a madrugada conta na noite anterior)."""
    return min(max(banco.cfg_int("virada_dia_hora", 6), 0), 23)


def periodo_operacional(banco, f: dict, coluna: str, onde: list, p: list) -> None:
    """Filtro 'de/até' por DIA OPERACIONAL em uma coluna 'AAAA-MM-DD hh:mm:ss': com a virada às 6h, "de 03/10 a 03/10" é a
    noite de 03/10 inteira (até 04/10 05:59), como no relatório de vendas. Faixa em vez de date(coluna), para usar os índices."""
    virada = virada_dia(banco)
    if f.get("de"):
        onde.append(f"{coluna} >= ?"); p.append(fmt.faixa_dia_operacional(f["de"], virada)[0])
    if f.get("ate"):
        onde.append(f"{coluna} < ?"); p.append(fmt.faixa_dia_operacional(f["ate"], virada)[1])

class RelatoriosVendas:
    banco = None  # fornecido pela classe concreta

    # ------------------------------------------------------------- filtros
    def _onde_vendas(self, f: dict, status=("fechada",), a: str = "v") -> tuple[str, list]:
        onde = [f"{a}.status IN ({','.join('?' * len(status))})"]
        p: list = list(status)

        def add(sql, valor):
            onde.append(sql)
            p.append(valor)

        # Faixa em vez de date(coluna): assim o índice de fechada_em é usado ('AAAA-MM-DD' <= 'AAAA-MM-DD hh:mm:ss').
        # O dia é o operacional: com a virada às 6h, "de 03/10 a 03/10" é a noite de 03/10 inteira (até 04/10 05:59).
        virada = self._virada()
        if f.get("de"): add(f"{a}.fechada_em >= ?", fmt.faixa_dia_operacional(f["de"], virada)[0])
        if f.get("ate"): add(f"{a}.fechada_em < ?", fmt.faixa_dia_operacional(f["ate"], virada)[1])
        if f.get("hora_ini"): add(f"time({a}.fechada_em) >= ?", _hora(f["hora_ini"]))
        if f.get("hora_fim"): add(f"time({a}.fechada_em) <= ?", _hora(f["hora_fim"]))
        if f.get("cupom_ini"): add(f"{a}.cupom >= ?", int(f["cupom_ini"]))
        if f.get("cupom_fim"): add(f"{a}.cupom <= ?", int(f["cupom_fim"]))
        if f.get("turno_atual"):
            atual = TurnoController(self.banco).atual()
            add(f"{a}.turno_id = ?", atual["id"] if atual else 0)
        if f.get("turno"): add(f"{a}.turno_id IN (SELECT id FROM turnos WHERE numero = ?)", int(f["turno"]))
        for chave, coluna in (("terminal", "terminal"), ("operador_id", "operador_id"),
                              ("garcom_id", "garcom_id"), ("vendedor_id", "vendedor_id"),
                              ("entregador_id", "entregador_id"), ("cliente_id", "cliente_id")):
            if f.get(chave):
                add(f"{a}.{coluna} = ?", f[chave])
        modalidade = f.get("modalidade")
        if modalidade in ("mesa", "comanda"):     # a comanda é uma venda 'mesa' com comanda = 1
            onde.append(f"{a}.modalidade = 'mesa' AND {a}.comanda = {1 if modalidade == 'comanda' else 0}")
        elif modalidade:
            add(f"{a}.modalidade = ?", modalidade)
        return " AND ".join(onde), p

    def _virada(self) -> int:
        return virada_dia(self.banco)

    def criterios(self, f: dict) -> list[str]:
        c = []
        if f.get("de") or f.get("ate"):
            virada = self._virada()
            c.append(f"Período: {fmt.fmt_data(f.get('de')) or '...'} a {fmt.fmt_data(f.get('ate')) or '...'}"
                     + (f" (o dia vira às {virada:02d}:00)" if virada else ""))
        if f.get("hora_ini") or f.get("hora_fim"):
            c.append(f"Horário: {f.get('hora_ini') or '00:00'} a {f.get('hora_fim') or '23:59'}")
        if f.get("cupom_ini") or f.get("cupom_fim"):
            c.append(f"Cupons: {f.get('cupom_ini') or '...'} a {f.get('cupom_fim') or '...'}")
        if f.get("turno_atual"): c.append("Somente o turno atual")
        if f.get("turno"): c.append(f"Turno: {f['turno']}")
        for chave, rotulo, tabela, col in (("operador_id", "Operador", "operadores", "nome"),
                                           ("garcom_id", "Garçom", "operadores", "nome"),
                                           ("vendedor_id", "Vendedor", "operadores", "nome"),
                                           ("entregador_id", "Entregador", "operadores", "nome"),
                                           ("cliente_id", "Cliente", "clientes", "nome")):
            if f.get(chave):
                c.append(f"{rotulo}: {self.banco.valor(f'SELECT {col} FROM {tabela} WHERE id = ?', (f[chave],), '?')}")
        if f.get("modalidade"): c.append(f"Modalidade: {f['modalidade']}")
        if f.get("grupo_id"):
            c.append("Categoria: " + self.banco.valor("SELECT nome FROM grupos WHERE id = ?", (f["grupo_id"],), "?"))
        return c or ["Todos os dados disponíveis"]

    # ------------------------------------------------------- 6.01 cupons
    def cupons(self, f: dict, incluir_cancelados: bool = True) -> list[dict]:
        status = ("fechada", "cancelada") if incluir_cancelados else ("fechada",)
        onde, p = self._onde_vendas(f, status)
        atual = TurnoController(self.banco).atual()
        linhas = [dict(r) for r in self.banco.todos(
            f"""SELECT v.id, v.cupom, v.fechada_em, v.posicao, v.comanda, v.modalidade, v.status, v.total_cent, v.desconto_cent,
                       v.turno_id, o.nome AS operador, t.numero AS turno
                FROM vendas v LEFT JOIN operadores o ON o.id = v.operador_id
                LEFT JOIN turnos t ON t.id = v.turno_id WHERE {onde} ORDER BY v.cupom""", p)]
        for ln in linhas:
            ln["cancelado"] = ln["status"] == "cancelada"
            ln["atual"] = bool(atual and ln["turno_id"] == atual["id"])
        return linhas

    def cupom_detalhe(self, venda_id: int) -> dict:
        itens = [dict(r) for r in self.banco.todos(
            """SELECT p.codigo, p.nome, i.quantidade, i.preco_unit_cent, i.total_cent, i.cancelado
               FROM itens_venda i JOIN produtos_historico p ON p.id = i.produto_id WHERE i.venda_id = ? ORDER BY i.id""", (venda_id,))]
        pagamentos = [dict(r) for r in self.banco.todos(
            """SELECT t.tipo, p.valor_cent, p.troco_cent FROM pagamentos_venda p
               JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id WHERE p.venda_id = ?""", (venda_id,))]
        return {"itens": itens, "pagamentos": pagamentos}

    def _totais(self, f: dict) -> dict:
        onde, p = self._onde_vendas(f)
        com_itens = f"({onde}) AND EXISTS (SELECT 1 FROM itens_venda i WHERE i.venda_id = v.id AND i.cancelado = 0)"
        r = self.banco.um(
            f"""SELECT COUNT(*) AS tc, COALESCE(SUM(v.subtotal_cent),0) AS venda, COALESCE(SUM(v.desconto_cent),0) AS desconto,
                       COALESCE(SUM(v.servico_cent),0) AS servico, COALESCE(SUM(v.taxa_cent),0) AS taxa,
                       COALESCE(SUM(v.acrescimo_cent),0) AS acrescimo,
                       COALESCE(SUM(v.total_cent),0) AS total, COALESCE(SUM(v.troco_cent),0) AS troco,
                       COALESCE(SUM(v.vale_cent),0) AS vale, COALESCE(SUM(v.pessoas),0) AS pessoas,
                       MIN(v.cupom) AS cupom_ini, MAX(v.cupom) AS cupom_fim
                FROM vendas v WHERE {com_itens}""", p)
        t = dict(r)
        t["tm"] = fmt.dividir_cent(t["total"], t["tc"])
        t["por_pessoa"] = fmt.dividir_cent(t["total"], t["pessoas"])
        for mod in ("mesa", "balcao", "caderneta", "entrega"):
            t[mod] = self.banco.valor(f"SELECT COALESCE(SUM(v.subtotal_cent),0) FROM vendas v WHERE {com_itens} "
                                      "AND v.modalidade = ?", p + [mod], 0)
        t["formas"] = [dict(x) for x in self.banco.todos(
            f"""SELECT tp.tipo, SUM(pg.valor_cent - pg.troco_cent) AS valor FROM pagamentos_venda pg
                JOIN vendas v ON v.id = pg.venda_id JOIN tipos_pagamento tp ON tp.id = pg.tipo_pagamento_id
                WHERE {onde} GROUP BY tp.id ORDER BY tp.ordem""", p)]
        t["por_subgrupo"] = [dict(x) for x in self.banco.todos(
            f"""SELECT g.nome AS grupo, s.nome AS subgrupo, SUM(i.quantidade) AS qt, SUM(i.total_cent) AS total
                FROM itens_venda i JOIN vendas v ON v.id = i.venda_id JOIN produtos_historico pr ON pr.id = i.produto_id
                JOIN subgrupos s ON s.id = pr.subgrupo_id JOIN grupos g ON g.id = s.grupo_id
                WHERE i.cancelado = 0 AND {onde} GROUP BY s.id ORDER BY g.nome, s.nome""", p)]
        return t

    def totalizacao_fita(self, f: dict) -> Relatorio:
        """Totalização do período para a fita (40 colunas): TC, TM, formas e quantidades por subgrupo."""
        t = self._totais(f)
        rel = Relatorio("Venda no período", [Coluna("", 20), Coluna("", 14, "d")], criterios=self.criterios(f))
        rel.add("TC (cupons)", t["tc"]); rel.add("TM (ticket médio)", M(t["tm"]))
        rel.add("Total dos produtos", M(t["venda"])); rel.add("Desconto (-)", M(t["desconto"]))
        rel.add("Serviço (+)", M(t["servico"])); rel.add("Taxa (+)", M(t["taxa"]))
        if t["acrescimo"]:
            rel.add("Taxa do crédito (+)", M(t["acrescimo"]))
        rel.add("TOTAL", M(t["total"]), estilo="total")
        if t["formas"]:
            rel.add("Recebimentos", "", estilo="secao")
            for x in t["formas"]:
                rel.add(x["tipo"], M(x["valor"]))
        rel.add("Troco", M(t["troco"])); rel.add("Contra-vale emitido", M(t["vale"]))
        if t["por_subgrupo"]:
            rel.add("Quantidades por subgrupo", "", estilo="secao")
            for x in t["por_subgrupo"]:
                rel.add(x["subgrupo"], Q(x["qt"]))
        if t["tc"]:
            rel.rodape = [("Cupom inicial / final", f"{t['cupom_ini']} / {t['cupom_fim']}")]
        return rel

    def vendas_periodo(self, f: dict) -> Relatorio:
        """Versão A4: produtos vendidos no período e totalizações."""
        onde, p = self._onde_vendas(f)
        t = self._totais(f)
        rel = Relatorio("Relatório de vendas", [Coluna("Código", 13), Coluna("Produto", 30), Coluna("Un", 4),
                                                Coluna("Quant", 10, "d"), Coluna("P.Médio", 9, "d"), Coluna("Subtotal", 11, "d")],
                        criterios=self.criterios(f))
        for r in self.banco.todos(
                f"""SELECT pr.codigo, pr.nome, u.abreviatura AS un, SUM(i.quantidade) AS qt, SUM(i.total_cent) AS tot
                    FROM itens_venda i JOIN vendas v ON v.id = i.venda_id JOIN produtos_historico pr ON pr.id = i.produto_id
                    JOIN unidades u ON u.id = pr.unidade_id WHERE i.cancelado = 0 AND {onde}
                    GROUP BY pr.id ORDER BY pr.nome""", p):
            rel.add(r["codigo"], r["nome"], r["un"], Q(r["qt"]), M(fmt.dividir_cent(r["tot"], r["qt"])), M(r["tot"]))
        rel.rodape = [("Venda total", M(t["venda"])), ("  Mesa/Comanda/Balcão", M(t["mesa"] + t["balcao"])),
                      ("  Caderneta", M(t["caderneta"])), ("  Entrega", M(t["entrega"])),
                      ("Desconto (-)", M(t["desconto"])), ("Serviço (+)", M(t["servico"])), ("Taxa (+)", M(t["taxa"])),
                      ("Taxa do crédito (+)", M(t["acrescimo"])),
                      ("Total apurado", M(t["total"]))]
        rel.rodape += [(f"Recebido em {x['tipo']}", M(x["valor"])) for x in t["formas"]]
        rel.rodape += [("Cupons (TC)", str(t["tc"])), ("Ticket médio (TM)", M(t["tm"])),
                       ("Pessoas atendidas", str(t["pessoas"])), ("Venda por pessoa", M(t["por_pessoa"]))]
        return rel

    # ---------------------------------------------------- 6.02 por grupo
    def vendas_por_grupo(self, f: dict) -> Relatorio:
        onde, p = self._onde_vendas(f)
        if f.get("grupo_id"):
            onde += " AND g.id = ?"
            p.append(f["grupo_id"])
        rel = Relatorio("Venda por grupo", [Coluna("Grupo / Produto", 36), Coluna("Quant", 10, "d"),
                                            Coluna("Total", 12, "d"), Coluna("%", 8, "d")], criterios=self.criterios(f))
        linhas = self.banco.todos(
            f"""SELECT g.nome AS grupo, pr.nome AS produto, SUM(i.quantidade) AS qt, SUM(i.total_cent) AS tot
                FROM itens_venda i JOIN vendas v ON v.id = i.venda_id JOIN produtos_historico pr ON pr.id = i.produto_id
                JOIN subgrupos s ON s.id = pr.subgrupo_id JOIN grupos g ON g.id = s.grupo_id
                WHERE i.cancelado = 0 AND {onde} GROUP BY pr.id ORDER BY g.nome, pr.nome""", p)
        geral = sum(r["tot"] for r in linhas)
        grupos: dict = {}
        for r in linhas:
            grupos.setdefault(r["grupo"], []).append(r)
        for grupo, itens in grupos.items():
            rel.add(grupo, "", "", "", estilo="secao")
            for r in itens:
                rel.add("  " + r["produto"], Q(r["qt"]), M(r["tot"]), "")
            soma = sum(r["tot"] for r in itens)
            rel.add(f"Total {grupo}", Q(sum(r["qt"] for r in itens)), M(soma),
                    Q(soma * 100 / geral, 2) if geral else "0,00", estilo="subtotal")
        rel.add("TOTAL DE VENDAS", "", M(geral), "100,00" if geral else "0,00", estilo="total")
        return rel

    def mais_vendidos(self, f: dict) -> Relatorio:
        """Produtos mais vendidos no período, opcionalmente recortados por grupo/categoria."""
        onde, p = self._onde_vendas(f)
        if f.get("grupo_id"):
            onde += " AND g.id = ?"
            p.append(f["grupo_id"])
        rel = Relatorio("Produtos mais vendidos", [
            Coluna("Produto", 32), Coluna("Grupo", 18), Coluna("Quantidade", 11, "d"),
            Coluna("Faturamento", 12, "d")], criterios=self.criterios(f))
        linhas = self.banco.todos(
            f"""SELECT pr.nome, g.nome AS grupo, SUM(i.quantidade) AS quantidade, SUM(i.total_cent) AS total
                FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
                JOIN produtos_historico pr ON pr.id = i.produto_id
                JOIN subgrupos s ON s.id = pr.subgrupo_id JOIN grupos g ON g.id = s.grupo_id
                WHERE i.cancelado = 0 AND {onde}
                GROUP BY pr.id ORDER BY quantidade DESC, pr.nome LIMIT 100""", p)
        for item in linhas:
            rel.add(item["nome"], item["grupo"], Q(item["quantidade"]), M(item["total"]))
        rel.rodape = [("Produtos listados", str(len(linhas))),
                      ("Faturamento listado", M(sum(item["total"] for item in linhas)))]
        return rel

    # ----------------------------------------- 6.03 e 6.04 caixa e turnos
    def caixa_movimentos(self, f: dict) -> Relatorio:
        onde, p = ["1=1"], []
        periodo_operacional(self.banco, f, "m.criado_em", onde, p)
        if f.get("turno"): onde.append("t.numero = ?"); p.append(int(f["turno"]))
        if f.get("operador_id"): onde.append("m.operador_id = ?"); p.append(f["operador_id"])
        if f.get("tipo"): onde.append("m.tipo = ?"); p.append(f["tipo"])
        rel = Relatorio("Entradas e saídas financeiras do caixa",
                        [Coluna("Data/hora", 19), Coluna("Turno", 5, "d"), Coluna("Tipo", 8), Coluna("Operador", 14),
                         Coluna("Descrição", 24), Coluna("Valor", 11, "d")], criterios=self.criterios(f))
        ent = sai = 0
        for r in self.banco.todos(
                f"""SELECT m.*, t.numero AS turno, o.nome AS operador FROM movimentos_caixa m
                    JOIN turnos t ON t.id = m.turno_id LEFT JOIN operadores o ON o.id = m.operador_id
                    WHERE {' AND '.join(onde)} ORDER BY m.id""", p):
            rel.add(fmt.fmt_datahora(r["criado_em"]), r["turno"], "Entrada" if r["tipo"] == "entrada" else "Sangria",
                    r["operador"], r["descricao"], M(r["valor_cent"]))
            if r["tipo"] == "entrada": ent += r["valor_cent"]
            else: sai += r["valor_cent"]
        rel.rodape = [("Total de entradas", M(ent)), ("Total de saídas (sangrias)", M(sai))]
        return rel

    def fechamentos(self, f: dict) -> Relatorio:
        onde, p = ["t.status = 'fechado'"], []
        periodo_operacional(self.banco, f, "t.fechado_em", onde, p)
        if f.get("turno"): onde.append("t.numero = ?"); p.append(int(f["turno"]))
        if f.get("operador_id"): onde.append("t.fechado_por = ?"); p.append(f["operador_id"])
        if f.get("terminal"): onde.append("t.terminal = ?"); p.append(f["terminal"])
        rel = Relatorio("Fechamentos do caixa", [
            Coluna("Fechado em", 19), Coluna("Turno", 5, "d"), Coluna("Operador", 12), Coluna("Inicial", 10, "d"),
            Coluna("Final", 10, "d"), Coluna("Esperado", 10, "d"), Coluna("Resultado", 10, "d")], criterios=self.criterios(f))
        soma = 0
        for r in self.banco.todos(
                f"""SELECT t.*, o.nome AS operador FROM turnos t LEFT JOIN operadores o ON o.id = t.fechado_por
                    WHERE {' AND '.join(onde)} ORDER BY t.id""", p):
            rel.add(fmt.fmt_datahora(r["fechado_em"]), r["numero"], r["operador"], M(r["valor_inicial_cent"]),
                    M(r["valor_final_cent"]), M(r["esperado_cent"]), M(r["resultado_cent"]))
            soma += r["resultado_cent"]
        rel.rodape = [("Sobra (+) / Falta (-) acumulada", M(soma))]
        return rel

    # ------------------------------------------------ 6.05 e 6.06 mesas e comandas
    def comandas(self, f: dict) -> Relatorio:
        onde, p = self._onde_vendas(f)
        rel = Relatorio("Mesas e comandas", [Coluna("Posição", 8, "d"), Coluna("Cupom", 7, "d"), Coluna("Data/hora", 19),
                                             Coluna("Operador", 12), Coluna("Garçom", 12), Coluna("Pessoas", 7, "d"),
                                             Coluna("Total", 11, "d")], criterios=self.criterios(f))
        total = 0
        padrao = self.banco.cfg("posicao_padrao", "comanda")
        for r in self.banco.todos(
                f"""SELECT v.*, o.nome AS operador, g.nome AS garcom FROM vendas v
                    LEFT JOIN operadores o ON o.id = v.operador_id LEFT JOIN operadores g ON g.id = v.garcom_id
                    WHERE {onde} AND v.modalidade = 'mesa' ORDER BY v.comanda, v.posicao, v.cupom""", p):
            rel.add(rotulo_posicao(r["comanda"], r["posicao"], padrao), r["cupom"], fmt.fmt_datahora(r["fechada_em"]),
                    r["operador"], r["garcom"], r["pessoas"], M(r["total_cent"]))
            total += r["total_cent"]
        rel.rodape = [("Total das mesas e comandas", M(total))]
        return rel

    def garcons(self, f: dict) -> Relatorio:
        onde, p = self._onde_vendas(f)
        pct = float(self.banco.cfg("comissao_garcom_pct", "0") or 0)
        rel = Relatorio("Produção dos garçons", [
            Coluna("Garçom", 20), Coluna("Cupons", 7, "d"), Coluna("Mesas", 6, "d"), Coluna("Produtos", 12, "d"),
            Coluna("Serviço", 11, "d"), Coluna("Comissão", 11, "d")], criterios=self.criterios(f) + [f"Comissão: {pct:g}% sobre produtos"])
        t = [0, 0, 0, 0, 0]
        for r in self.banco.todos(
                f"""SELECT COALESCE(g.nome, '(sem garçom)') AS garcom, COUNT(*) AS cupons,
                           COUNT(DISTINCT v.comanda * 100000 + v.posicao) AS mesas,
                           SUM(v.subtotal_cent) AS prod, SUM(v.servico_cent) AS serv
                    FROM vendas v LEFT JOIN operadores g ON g.id = v.garcom_id
                    WHERE {onde} AND v.modalidade = 'mesa' GROUP BY v.garcom_id ORDER BY garcom""", p):
            com = fmt.pct_de(r["prod"], pct)
            rel.add(r["garcom"], r["cupons"], r["mesas"], M(r["prod"]), M(r["serv"]), M(com))
            for i, v in enumerate((r["cupons"], r["mesas"], r["prod"], r["serv"], com)):
                t[i] += v
        rel.add("TOTAL", t[0], t[1], M(t[2]), M(t[3]), M(t[4]), estilo="total")
        return rel

    def auditoria_operadores(self, f: dict) -> Relatorio:
        """Um quadro por operador para o dono conferir a noite: o que vendeu, quanto cancelou, quanto de desconto deu e quanto
        tirou do caixa em sangria. Cancelamento alto ou desconto fora do normal é onde costuma estar o problema."""
        onde, p = self._onde_vendas(f)
        virada = self._virada()
        ini = fmt.faixa_dia_operacional(f["de"], virada)[0] if f.get("de") else "0000-01-01 00:00:00"
        fim = fmt.faixa_dia_operacional(f["ate"], virada)[1] if f.get("ate") else "9999-12-31 23:59:59"
        rel = Relatorio("Auditoria por operador", [
            Coluna("Operador", 16), Coluna("Cupons", 7, "d"), Coluna("Vendido", 11, "d"), Coluna("Ticket", 9, "d"),
            Coluna("Desconto", 9, "d"), Coluna("Cup.canc", 8, "d"), Coluna("Itens canc", 10, "d"), Coluna("Sangrias", 10, "d")],
            criterios=self.criterios(f))
        linhas: dict[int, dict] = {}

        def linha(op_id, nome):
            return linhas.setdefault(op_id or 0, {"nome": nome or "(sem operador)", "cupons": 0, "total": 0, "desc": 0,
                                                  "canc": 0, "itens": 0, "sangria": 0})
        for r in self.banco.todos(
                f"""SELECT v.operador_id, o.nome, COUNT(*) AS cupons, SUM(v.total_cent) AS total, SUM(v.desconto_cent) AS desc
                    FROM vendas v LEFT JOIN operadores o ON o.id = v.operador_id
                    WHERE {onde} AND v.subtotal_cent > 0 GROUP BY v.operador_id""", p):
            x = linha(r["operador_id"], r["nome"])
            x["cupons"], x["total"], x["desc"] = r["cupons"], r["total"], r["desc"]
        for r in self.banco.todos(
                """SELECT v.cancelada_por AS op, o.nome, COUNT(*) AS n FROM vendas v LEFT JOIN operadores o ON o.id = v.cancelada_por
                   WHERE v.status = 'cancelada' AND COALESCE(v.fechada_em, v.aberta_em) >= ? AND COALESCE(v.fechada_em, v.aberta_em) < ?
                   GROUP BY v.cancelada_por""", (ini, fim)):
            linha(r["op"], r["nome"])["canc"] = r["n"]
        for r in self.banco.todos(
                """SELECT l.operador_id AS op, o.nome, COUNT(*) AS n FROM log_eventos l LEFT JOIN operadores o ON o.id = l.operador_id
                   WHERE l.evento = 'item_cancelado' AND l.quando >= ? AND l.quando < ? GROUP BY l.operador_id""", (ini, fim)):
            linha(r["op"], r["nome"])["itens"] = r["n"]
        for r in self.banco.todos(
                """SELECT m.operador_id AS op, o.nome, SUM(m.valor_cent) AS total FROM movimentos_caixa m
                   LEFT JOIN operadores o ON o.id = m.operador_id
                   WHERE m.tipo = 'saida' AND m.criado_em >= ? AND m.criado_em < ? GROUP BY m.operador_id""", (ini, fim)):
            linha(r["op"], r["nome"])["sangria"] = r["total"]
        t = [0, 0, 0, 0, 0, 0]
        for x in sorted(linhas.values(), key=lambda x: (-x["total"], x["nome"])):
            ticket = fmt.dividir_cent(x["total"], x["cupons"])
            rel.add(x["nome"], x["cupons"], M(x["total"]), M(ticket), M(x["desc"]), x["canc"], x["itens"], M(x["sangria"]))
            for i, v in enumerate((x["cupons"], x["total"], x["desc"], x["canc"], x["itens"], x["sangria"])):
                t[i] += v
        rel.add("TOTAL", t[0], M(t[1]), M(fmt.dividir_cent(t[1], t[0])), M(t[2]), t[3], t[4], M(t[5]), estilo="total")
        return rel

    # ------------------------------------------------------------ 6.07 CMV
    def cmv(self, f: dict) -> Relatorio:
        """Custo da mercadoria vendida: custo atual (composição ou último preço de compra) x quantidade."""
        onde, p = self._onde_vendas(f)
        if f.get("grupo_id"):
            onde += " AND g.id = ?"
            p.append(f["grupo_id"])
        prods = ProdutoController(self.banco)
        rel = Relatorio("Relatório C.M.V.", [Coluna("Produto", 28), Coluna("Qt.Venda", 9, "d"), Coluna("Custo Unit", 10, "d"),
                                             Coluna("Custo Total", 11, "d"), Coluna("Tot.Vendido", 11, "d"),
                                             Coluna("Resultado", 10, "d"), Coluna("Margem%", 8, "d")],
                        criterios=self.criterios(f))
        grupos: dict = {}
        for r in self.banco.todos(
                f"""SELECT g.nome AS grupo, pr.id, pr.codigo, pr.nome, SUM(i.quantidade) AS qt, SUM(i.total_cent) AS tot
                    FROM itens_venda i JOIN vendas v ON v.id = i.venda_id JOIN produtos_historico pr ON pr.id = i.produto_id
                    JOIN subgrupos s ON s.id = pr.subgrupo_id JOIN grupos g ON g.id = s.grupo_id
                    WHERE i.cancelado = 0 AND {onde} GROUP BY pr.id ORDER BY g.nome, pr.nome""", p):
            custo_un = prods.custo(r["id"])
            grupos.setdefault(r["grupo"], []).append((r, custo_un, fmt.mult_cent(custo_un, r["qt"])))

        def linha(rotulo, custo_un, custo, venda, qt, estilo=""):
            res = venda - custo
            rel.add(rotulo, Q(qt) if qt is not None else "", M(custo_un) if custo_un is not None else "", M(custo),
                    M(venda), M(res), Q(res * 100 / venda, 2) if venda else "0,00", estilo=estilo)

        gc = gv = 0
        for grupo, itens in grupos.items():
            rel.add(grupo, "", "", "", "", "", "", estilo="secao")
            for r, cu, ct in itens:
                linha(f"  {r['nome']}", cu, ct, r["tot"], r["qt"])
            c, v = sum(i[2] for i in itens), sum(i[0]["tot"] for i in itens)
            linha(f"Total do grupo {grupo}", None, c, v, None, "subtotal")
            gc += c; gv += v
        linha("TOTAL GERAL", None, gc, gv, None, "total")
        return rel

    # ----------------------------------------------------------- comissões
    def comissoes_produto(self, f: dict) -> Relatorio:
        onde, p = self._onde_vendas(f)
        rel = Relatorio("Comissão por produto", [Coluna("Operador / Produto", 34), Coluna("Quant", 10, "d"),
                                                 Coluna("Vendido", 12, "d"), Coluna("Comissão", 12, "d")], criterios=self.criterios(f))
        por_op: dict = {}
        for r in self.banco.todos(
                f"""SELECT o.nome AS operador, pr.nome, SUM(i.quantidade) AS qt, SUM(i.total_cent) AS tot, SUM(i.comissao_cent) AS com
                    FROM itens_venda i JOIN vendas v ON v.id = i.venda_id JOIN produtos_historico pr ON pr.id = i.produto_id
                    JOIN operadores o ON o.id = COALESCE(v.vendedor_id, v.operador_id)
                    WHERE i.cancelado = 0 AND o.recebe_comissao = 1 AND i.comissao_cent > 0 AND {onde}
                    GROUP BY o.id, pr.id ORDER BY o.nome, pr.nome""", p):
            por_op.setdefault(r["operador"], []).append(r)
        total = 0
        for op, itens in por_op.items():
            rel.add(op, "", "", "", estilo="secao")
            for r in itens:
                rel.add("  " + r["nome"], Q(r["qt"]), M(r["tot"]), M(r["com"]))
            soma = sum(r["com"] for r in itens)
            rel.add(f"Total {op}", "", M(sum(r["tot"] for r in itens)), M(soma), estilo="subtotal")
            total += soma
        rel.add("TOTAL DE COMISSÕES", "", "", M(total), estilo="total")
        return rel

    def comissoes_venda(self, f: dict) -> Relatorio:
        onde, p = self._onde_vendas(f)
        rel = Relatorio("Comissão por venda", [Coluna("Operador", 24), Coluna("Cupons", 8, "d"), Coluna("Vendido", 12, "d"),
                                               Coluna("%", 6, "d"), Coluna("Comissão", 12, "d")], criterios=self.criterios(f))
        total = 0
        for r in self.banco.todos(
                f"""SELECT o.nome, o.comissao_pct, COUNT(*) AS n, SUM(v.subtotal_cent) AS tot FROM vendas v
                    JOIN operadores o ON o.id = COALESCE(v.vendedor_id, v.operador_id)
                    WHERE o.recebe_comissao = 1 AND {onde} GROUP BY o.id ORDER BY o.nome""", p):
            com = fmt.pct_de(r["tot"], r["comissao_pct"])
            rel.add(r["nome"], r["n"], M(r["tot"]), f"{r['comissao_pct']:g}".replace(".", ","), M(com))
            total += com
        rel.add("TOTAL", "", "", "", M(total), estilo="total")
        return rel

    def comissoes_cliente(self, f: dict) -> Relatorio:
        onde, p = self._onde_vendas(f)
        rel = Relatorio("Vendas por cliente", [Coluna("Cliente", 30), Coluna("Cupons", 8, "d"), Coluna("Total", 12, "d")],
                        criterios=self.criterios(f))
        total = 0
        for r in self.banco.todos(
                f"""SELECT c.nome, COUNT(*) AS n, SUM(v.total_cent) AS tot FROM vendas v
                    JOIN clientes c ON c.id = v.cliente_id WHERE {onde} AND v.modalidade IN ('caderneta','entrega')
                    AND v.subtotal_cent > 0 GROUP BY c.id ORDER BY c.nome""", p):
            rel.add(r["nome"], r["n"], M(r["tot"]))
            total += r["tot"]
        rel.add("TOTAL", "", M(total), estilo="total")
        return rel

    # ------------------------------------------------ versão web: informativos
    def informativo_dias(self, f: dict) -> Relatorio:
        onde, p = self._onde_vendas(f)
        rel = Relatorio("Informativo de vendas", [Coluna("Data", 10), Coluna("Dia", 8), Coluna("Cupons", 7, "d"),
                                                  Coluna("Pessoas", 7, "d"), Coluna("Total", 12, "d"), Coluna("T.M.", 9, "d"),
                                                  Coluna("Último registro", 19)], criterios=self.criterios(f))
        tc = pe = tot = 0
        for r in self.banco.todos(
                f"""SELECT date(v.fechada_em, '-{self._virada()} hours') AS dia, COUNT(*) AS tc, SUM(v.pessoas) AS pessoas,
                           SUM(v.total_cent) AS tot,
                           MAX(v.fechada_em) AS ultimo FROM vendas v
                    WHERE {onde} AND v.subtotal_cent > 0 GROUP BY dia ORDER BY dia""", p):
            rel.add(fmt.fmt_data(r["dia"]), fmt.NOMES_DIA[fmt.dia_semana(r["dia"])], r["tc"], r["pessoas"],
                    M(r["tot"]), M(fmt.dividir_cent(r["tot"], r["tc"])), fmt.fmt_datahora(r["ultimo"]))
            tc += r["tc"]; pe += r["pessoas"]; tot += r["tot"]
        rel.add("TOTAIS", "", tc, pe, M(tot), M(fmt.dividir_cent(tot, tc)), "", estilo="total")
        return rel

    def vendas_por_hora(self, f: dict) -> Relatorio:
        onde, p = self._onde_vendas(f)
        virada = self._virada()          # a noite em ordem: 22h, 23h, 0h, 1h... (não 0h antes das 22h)
        rel = Relatorio("Vendas por hora", [Coluna("Dia", 10), Coluna("Hora", 13), Coluna("Valor", 12, "d"), Coluna("T.C.", 6, "d"),
                                            Coluna("T.M.", 10, "d"), Coluna("Clientes", 8, "d")], criterios=self.criterios(f))
        tc = tot = pe = 0
        linhas = self.banco.todos(
            f"""SELECT date(v.fechada_em, '-{virada} hours') AS dia, CAST(strftime('%H', v.fechada_em) AS INTEGER) AS h,
                       COUNT(*) AS tc, SUM(v.total_cent) AS tot, SUM(v.pessoas) AS pessoas FROM vendas v
                WHERE {onde} AND v.subtotal_cent > 0 GROUP BY dia, h ORDER BY dia, (h - {virada} + 24) % 24""", p)
        for r in linhas:
            rel.add(fmt.NOMES_DIA[fmt.dia_semana(r["dia"])], f"{r['h']:02d}:00 a {r['h'] + 1:02d}:00",
                    M(r["tot"]), r["tc"], M(fmt.dividir_cent(r["tot"], r["tc"])), r["pessoas"])
            tc += r["tc"]; tot += r["tot"]; pe += r["pessoas"]
        rel.add("TOTAIS", "", M(tot), tc, M(fmt.dividir_cent(tot, tc)), pe, estilo="total")
        return rel

    def cancelados(self, f: dict) -> Relatorio:
        ond_v, p_v = self._onde_vendas(f, ("fechada", "cancelada"))
        rel = Relatorio("Cancelamentos", [Coluna("", 26), Coluna("Registros", 10, "d"), Coluna("Quantidade", 12, "d"),
                                          Coluna("Total", 12, "d")], criterios=self.criterios(f))
        r = self.banco.um(
            f"""SELECT SUM(i.cancelado = 0) AS vn, SUM(i.cancelado = 1) AS cn,
                       COALESCE(SUM(CASE WHEN i.cancelado = 0 THEN i.quantidade END),0) AS vq,
                       COALESCE(SUM(CASE WHEN i.cancelado = 1 THEN i.quantidade END),0) AS cq,
                       COALESCE(SUM(CASE WHEN i.cancelado = 0 THEN i.total_cent END),0) AS vt,
                       COALESCE(SUM(CASE WHEN i.cancelado = 1 THEN i.total_cent END),0) AS ct
                FROM itens_venda i JOIN vendas v ON v.id = i.venda_id WHERE {ond_v}""", p_v)
        vn, cn = r["vn"] or 0, r["cn"] or 0
        rel.add("Cancelamento de itens", "", "", "", estilo="secao")
        rel.add("Vendidos", vn, Q(r["vq"]), M(r["vt"])); rel.add("Cancelados", cn, Q(r["cq"]), M(r["ct"]))
        rel.add("% cancelados", Q(cn * 100 / (vn + cn), 2) + "%" if vn + cn else "0,00%", "",
                Q(r['ct'] * 100 / (r['vt'] + r['ct']), 2) + "%" if r["vt"] + r["ct"] else "0,00%", estilo="subtotal")
        c = self.banco.um(
            f"""SELECT SUM(v.status = 'fechada') AS vn, SUM(v.status = 'cancelada') AS cn,
                       COALESCE(SUM(CASE WHEN v.status = 'fechada' THEN v.total_cent END),0) AS vt,
                       COALESCE(SUM(CASE WHEN v.status = 'cancelada' THEN v.subtotal_cent END),0) AS ct
                FROM vendas v WHERE {ond_v}""", p_v)
        vn, cn = c["vn"] or 0, c["cn"] or 0
        rel.add("Cancelamento de cupons", "", "", "", estilo="secao")
        rel.add("Vendidos", vn, "", M(c["vt"])); rel.add("Cancelados", cn, "", M(c["ct"]))
        rel.add("% cancelados", Q(cn * 100 / (vn + cn), 2) + "%" if vn + cn else "0,00%", "",
                Q(c['ct'] * 100 / (c['vt'] + c['ct']), 2) + "%" if c["vt"] + c["ct"] else "0,00%", estilo="subtotal")
        return rel
