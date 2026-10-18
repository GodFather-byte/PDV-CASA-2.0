"""Caderneta (venda a prazo) e consulta de clientes no caixa: escolher cliente,
saldo, débitos e créditos, últimos produtos consumidos e lista de devedores."""
from __future__ import annotations

from src.core import formatacao as fmt


class CadernetaController:
    def __init__(self, banco):
        self.banco = banco

    def buscar(self, texto: str, limite: int = 50) -> list[dict]:
        """Por número para consulta (exato) ou parte do nome, só clientes ativos."""
        t = (texto or "").strip()
        linhas = self.banco.todos(
            """SELECT c.*, b.nome AS bairro, b.taxa_cent FROM clientes c
               LEFT JOIN bairros b ON b.id = c.bairro_id
               WHERE c.ativo = 1 AND (c.numero_consulta = ? OR norm(c.nome) LIKE norm(?) OR c.telefone LIKE ?)
               ORDER BY (c.numero_consulta = ?) DESC, c.nome LIMIT ?""",
            (t, f"%{t}%", f"%{t}%", t, limite))
        return [dict(r) for r in linhas]

    def obter(self, cliente_id: int) -> dict | None:
        r = self.banco.um(
            """SELECT c.*, b.nome AS bairro, b.taxa_cent FROM clientes c
               LEFT JOIN bairros b ON b.id = c.bairro_id WHERE c.id = ?""", (cliente_id,))
        return dict(r) if r else None

    def lancamentos(self, cliente_id: int, desde: str | None = None, cupom_inicial: int | None = None) -> list[dict]:
        """Débitos e créditos (mais recentes primeiro)."""
        sql = """SELECT l.*, v.cupom FROM caderneta l LEFT JOIN vendas v ON v.id = l.venda_id
                 WHERE l.cliente_id = ?"""
        params: list = [cliente_id]
        if desde:
            sql += " AND date(l.criado_em) >= ?"
            params.append(desde)
        if cupom_inicial:
            sql += " AND v.cupom >= ?"
            params.append(cupom_inicial)
        return [dict(r) for r in self.banco.todos(sql + " ORDER BY l.id DESC", params)]

    def produtos_da_venda(self, venda_id: int) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            """SELECT p.nome, i.quantidade, i.preco_unit_cent, i.total_cent FROM itens_venda i
               JOIN produtos_historico p ON p.id = i.produto_id WHERE i.venda_id = ? AND i.cancelado = 0 ORDER BY i.id""",
            (venda_id,))]

    def pagamentos_da_venda(self, venda_id: int) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            """SELECT t.tipo, p.valor_cent - p.troco_cent AS valor_cent FROM pagamentos_venda p
               JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id WHERE p.venda_id = ?""", (venda_id,))]

    def ultimas_compras(self, cliente_id: int, limite: int = 30) -> list[dict]:
        """'Últimas Compras' da tela de caderneta/entrega: o que o cliente já consumiu."""
        return [dict(r) for r in self.banco.todos(
            """SELECT v.cupom, date(v.fechada_em) AS data, p.nome, i.quantidade, i.total_cent
               FROM itens_venda i JOIN vendas v ON v.id = i.venda_id JOIN produtos_historico p ON p.id = i.produto_id
               WHERE v.cliente_id = ? AND v.status = 'fechada' AND i.cancelado = 0
               ORDER BY v.id DESC, i.id LIMIT ?""", (cliente_id, limite))]

    def devedores(self) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            "SELECT * FROM clientes WHERE saldo_cent < 0 ORDER BY saldo_cent, nome")]

    def texto_extrato(self, cliente_id: int, largura: int = 40) -> str:
        """Extrato simples para a opção Imprimir da caderneta."""
        c = self.obter(cliente_id)
        linhas = [f"CADERNETA - {c['nome']}".center(largura), "=" * largura]
        for l in reversed(self.lancamentos(cliente_id)):
            sinal = "-" if l["tipo"] == "debito" else "+"
            esq = f"{fmt.fmt_data(l['criado_em'][:10])} cupom {l['cupom'] or '-'}"
            dir_ = f"{sinal}{fmt.fmt_num(l['valor_cent'])}"
            linhas.append(esq + dir_.rjust(largura - len(esq)))
        linhas += ["-" * largura, "SALDO".ljust(largura - 12) + fmt.fmt_num(c["saldo_cent"]).rjust(12)]
        return "\n".join(linhas)
