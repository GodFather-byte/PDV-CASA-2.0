"""Relatório da comissão das garotas: por número (total, pago e a pagar) ou lançamento a lançamento."""
from __future__ import annotations

from src.controllers.relatorio_vendas import periodo_operacional
from src.core import formatacao as fmt
from src.core.relatorio import Coluna, Relatorio

M = fmt.fmt_num
SITUACAO = {"pendente": "A pagar", "paga": "Paga", "cancelada": "Cancelada"}


class RelatoriosComissoes:
    banco = None  # fornecido pela classe concreta

    def _filtros_comissao(self, f: dict) -> tuple[str, list, list[str]]:
        """WHERE, parâmetros e as linhas de 'critérios' do relatório. Sem escolher a situação, os cancelados ficam de fora."""
        situacao = f.get("situacao_comissao")
        if situacao in SITUACAO:
            onde, p = ["c.status = ?"], [situacao]
        else:
            onde, p = ["c.status <> 'cancelada'"], []
        criterios = []
        # O dia é o operacional (a noite inteira, até a virada), como nas vendas: a comissão das 2h conta na noite anterior.
        periodo_operacional(self.banco, f, "c.criado_em", onde, p)
        if f.get("de") or f.get("ate"):
            criterios.append(f"Período: {fmt.fmt_data(f.get('de')) or '...'} a {fmt.fmt_data(f.get('ate')) or '...'}")
        if f.get("turno"):
            onde.append("c.turno_id IN (SELECT id FROM turnos WHERE numero = ?)"); p.append(int(f["turno"]))
            criterios.append(f"Turno: {f['turno']}")
        if f.get("garota"):
            onde.append("c.garota = ?"); p.append(int(f["garota"]))
            criterios.append(f"Garota: {f['garota']}")
        if situacao in SITUACAO:
            criterios.append(f"Situação: {SITUACAO[situacao]}")
        return " AND ".join(onde), p, criterios or ["Todos os lançamentos, menos os cancelados"]

    def comissoes_garotas(self, f: dict) -> Relatorio:
        """Uma linha por garota; com `detalhar` uma linha por lançamento. Cancelados só aparecem se a situação for pedida."""
        onde, p, criterios = self._filtros_comissao(f)
        if f.get("detalhar"):
            return self._comissoes_detalhadas(onde, p, criterios)
        rel = Relatorio("Comissão das garotas", [
            Coluna("Garota", 6, "d"), Coluna("Nome", 20), Coluna("Lanç.", 5, "d"), Coluna("Total", 11, "d"),
            Coluna("Pago", 11, "d"), Coluna("A pagar", 11, "d")], criterios=criterios)
        total = pago = pendente = 0
        for r in self.banco.todos(
                f"""SELECT c.garota, COALESCE(g.nome, '') AS nome, COUNT(*) AS n, SUM(c.valor_cent) AS total,
                           COALESCE(SUM(CASE WHEN c.status = 'paga' THEN c.valor_cent END), 0) AS pago,
                           COALESCE(SUM(CASE WHEN c.status = 'pendente' THEN c.valor_cent END), 0) AS pendente
                    FROM comissoes_garotas c LEFT JOIN garotas g ON g.numero = c.garota
                    WHERE {onde} GROUP BY c.garota ORDER BY c.garota""", p):
            rel.add(r["garota"], r["nome"], r["n"], M(r["total"]), M(r["pago"]), M(r["pendente"]))
            total += r["total"]; pago += r["pago"]; pendente += r["pendente"]
        rel.rodape = [("Total lançado", M(total)), ("Já pago", M(pago)), ("A pagar", M(pendente))]
        return rel

    def _comissoes_detalhadas(self, onde: str, p: list, criterios: list[str]) -> Relatorio:
        rel = Relatorio("Comissão das garotas (lançamentos)", [
            Coluna("Data/hora", 19), Coluna("Garota", 6, "d"), Coluna("Nome", 14), Coluna("Turno", 5, "d"),
            Coluna("Valor", 10, "d"), Coluna("Situação", 9), Coluna("Operador", 12)], criterios=criterios)
        soma = 0
        for r in self.banco.todos(
                f"""SELECT c.*, COALESCE(g.nome, '') AS nome, o.nome AS operador, t.numero AS turno
                    FROM comissoes_garotas c LEFT JOIN garotas g ON g.numero = c.garota
                    LEFT JOIN operadores o ON o.id = c.operador_id LEFT JOIN turnos t ON t.id = c.turno_id
                    WHERE {onde} ORDER BY c.id""", p):
            rel.add(fmt.fmt_datahora(r["criado_em"]), r["garota"], r["nome"], r["turno"], M(r["valor_cent"]),
                    SITUACAO.get(r["status"], r["status"]), r["operador"])
            if r["status"] != "cancelada":
                soma += r["valor_cent"]
        rel.rodape = [("Total (sem os cancelados)", M(soma))]
        return rel
