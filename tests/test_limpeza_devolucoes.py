"""Limpeza de movimento com histórico de devoluções (docs/DEVOLUCOES.md)."""
from __future__ import annotations

import sqlite3
import tempfile

from src.controllers.utilitario_controller import UtilitarioController
from src.core import formatacao as fmt
from tests.test_devolucoes import BaseDevolucao

TRAVAS = "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'devolucoes%_sem_exclusao'"


class TesteLimpezaComDevolucoes(BaseDevolucao):
    def setUp(self):
        super().setUp()
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.banco.cfg_set("pasta_backup", self.pasta.name)
        self.util = UtilitarioController(self.banco, self.adm)
        self.turnos.fechar(self.turno, self.adm, 10000, justificativa="teste")
        # Dia -10: V1 com devolução antiga, V2 sem devolução ainda, V3 com troca (venda nova N) toda antiga.
        self.avancar(days=-10)
        t_antigo = self.turnos.abrir(self.adm, 2, 0)
        self.v1 = self.fechada((self.skol, 2))
        self.devolver(self.v1, [{"item_id": self.item(self.v1), "quantidade": 1}])
        self.v2 = self.fechada((self.skol, 1))
        self.v3 = self.fechada((self.agua, 1))
        d3 = self.devolver(self.v3, [{"item_id": self.item(self.v3), "quantidade": 1}], troca=True)
        self.n3 = self.caixa.abrir_troca(d3["id"])
        self.caixa.adicionar_item(self.n3, self.skol, 1)
        self.pagar(self.n3, "Dinheiro", self.caixa.recalcular(self.n3)["total"])
        self.caixa.fechar(self.n3)
        self.turnos.fechar(t_antigo, self.adm, 0, justificativa="teste")
        # Dia -8: turno sem vendas que, no dia -6, devolve parte da V2 (devolução do período preservado).
        self.avancar(days=2)
        self.t_dev = self.turnos.abrir(self.adm, 3, 5000)
        self.avancar(days=2)
        self.d2 = self.devolver(self.v2, [{"item_id": self.item(self.v2), "quantidade": 1}])
        self.turnos.fechar(self.t_dev, self.adm, 0, justificativa="teste")
        self.avancar(days=6)
        self.corte = fmt.fmt_data(fmt.somar_dias(fmt.hoje(), -7))

    def contar(self, tabela):
        return self.banco.valor(f"SELECT COUNT(*) FROM {tabela}")

    def test_limpa_devolucoes_antigas_e_preserva_o_que_ainda_cabe(self):
        res = self.util.limpar_movimento(self.corte)
        vendas = {r[0] for r in self.banco.todos("SELECT id FROM vendas")}
        self.assertEqual(res["devolucoes"], 2)
        self.assertNotIn(self.v1, vendas)
        self.assertNotIn(self.v3, vendas)
        self.assertNotIn(self.n3, vendas)
        self.assertIn(self.v2, vendas)                       # tem devolução depois do corte
        self.assertEqual([r[0] for r in self.banco.todos("SELECT id FROM devolucoes")], [self.d2["id"]])
        self.assertEqual(self.contar("devolucoes_trocas"), 0)
        self.assertIsNotNone(self.banco.um("SELECT 1 FROM turnos WHERE id = ?", (self.t_dev,)))
        self.assertIsNotNone(self.banco.um("SELECT 1 FROM movimentos_caixa WHERE id = ?",
                                           (self.d2["movimento_caixa_id"],)))
        self.assertEqual(self.banco.conexao.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.banco.valor(TRAVAS), 3)
        with self.assertRaises(sqlite3.DatabaseError):
            self.banco.executar("DELETE FROM devolucoes")
        self.assertEqual(self.dev.situacao(self.v2)["itens"][0]["devolvida"], 1)

    def test_troca_recente_segura_a_venda_original_antiga(self):
        # Troca de V1 (antiga) aberta hoje e ainda em andamento: V1 e a devolução precisam ficar.
        self.turnos.abrir(self.adm, 4, 0)
        dt = self.devolver(self.v1, [{"item_id": self.item(self.v1), "quantidade": 1}], troca=True)
        nova = self.caixa.abrir_troca(dt["id"])
        self.util.limpar_movimento(self.corte)
        vendas = {r[0] for r in self.banco.todos("SELECT id FROM vendas")}
        self.assertTrue({self.v1, nova, self.v2} <= vendas)
        self.assertEqual(len(self.dev.da_venda(self.v1)), 2)

    def test_falha_no_meio_desfaz_tudo_inclusive_as_travas(self):
        antes = {t: self.contar(t) for t in ("vendas", "devolucoes", "devolucoes_itens", "devolucoes_trocas",
                                             "turnos", "movimentos_caixa", "movimentos_estoque")}
        original = self.banco.executar

        def falhar(sql, *a, **kw):
            if sql.startswith("DELETE FROM movimentos_estoque"):
                raise sqlite3.OperationalError("falha simulada")
            return original(sql, *a, **kw)

        self.banco.executar = falhar
        with self.assertRaisesRegex(sqlite3.OperationalError, "simulada"):
            self.util.limpar_movimento(self.corte)
        self.banco.executar = original
        self.assertEqual({t: self.contar(t) for t in antes}, antes)
        self.assertEqual(self.banco.valor(TRAVAS), 3)
        with self.assertRaises(sqlite3.DatabaseError):
            self.banco.executar("DELETE FROM devolucoes_itens")