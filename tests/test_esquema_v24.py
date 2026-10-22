"""Índice parcial do consumo: instalação, atualização e busca pela janela de datas."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.controllers.estoque_controller import EstoqueController
from src.database.conexao import BancoDados
from src.database.esquema import VERSAO_ESQUEMA
from tests.base import BaseTeste


class TesteIndiceConsumoV24(BaseTeste):
    def setUp(self):
        super().setUp()
        self.pid = self.novo_produto()
        for tipo, referencia, quantidade, quando in (
                ("venda", "venda", -10, "2026-09-03 21:00:00"),
                ("estorno_venda", "venda", 2, "2026-10-03 21:00:00"),
                ("venda", "venda", -100, "2026-09-03 20:59:59"),
                ("venda", "venda", -100, "2026-10-03 21:00:01"),
                ("quebra", "venda", -100, "2026-10-03 21:00:00"),
                ("venda", "item_estoque", -100, "2026-10-03 21:00:00"),
                ("desc_acabados", "item_estoque", -100, "2026-10-03 21:00:00")):
            self.banco.inserir("movimentos_estoque", {
                "produto_id": self.pid, "tipo": tipo, "ref_tipo": referencia,
                "quantidade": quantidade, "qt_apos": 0, "criado_em": quando})

    def verificar_indice_e_janela(self, banco):
        self.assertEqual(banco.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
        indices = [dict(r) for r in banco.todos("PRAGMA index_list(movimentos_estoque)")]
        indice = next(r for r in indices if r["name"] == "ix_movest_consumo")
        self.assertEqual(indice["partial"], 1)
        self.assertEqual([r["name"] for r in banco.todos("PRAGMA index_info(ix_movest_consumo)")],
                         ["ref_tipo", "criado_em", "produto_id"])
        sql_indice = banco.valor("SELECT sql FROM sqlite_master WHERE name = 'ix_movest_consumo'")
        self.assertIn("WHERE ref_tipo = 'venda' AND tipo IN ('venda','estorno_venda')", sql_indice)
        with patch.object(banco, "todos", wraps=banco.todos) as consulta:
            self.assertEqual(EstoqueController(banco)._consumo_30_dias(), {self.pid: 8})
        self.assertEqual(consulta.call_count, 1)
        sql, parametros = consulta.call_args.args
        plano = " ".join(r["detail"] for r in banco.todos("EXPLAIN QUERY PLAN " + sql, parametros))
        self.assertRegex(plano, r"SEARCH (?:movimentos_estoque|m) USING INDEX ix_movest_consumo\b")
        self.assertIn("criado_em>?", plano)
        self.assertIn("criado_em<?", plano)
        self.assertNotRegex(plano, r"\bSCAN (?:movimentos_estoque|m)\b")

    def test_banco_novo_tem_indice_parcial_e_plano_por_janela(self):
        self.verificar_indice_e_janela(self.banco)

    def test_migracao_e_reabertura_v24_instalam_indice_sem_mudar_movimentos(self):
        for versao in (23, 24):
            with self.subTest(versao=versao), tempfile.TemporaryDirectory(dir=".") as pasta:
                caminho = Path(pasta) / "loja.db"
                banco = BancoDados(str(caminho))
                try:
                    self.banco.conexao.backup(banco.conexao)
                    banco.executar("DROP INDEX ix_movest_consumo")
                    if versao == 23:
                        banco.executar("ALTER TABLE itens_venda DROP COLUMN regra_preco_json")
                    banco.executar(f"PRAGMA user_version = {versao}")
                    antes = [tuple(r) for r in banco.todos("SELECT * FROM movimentos_estoque ORDER BY id")]
                finally:
                    banco.fechar()
                for _ in range(2):
                    banco = BancoDados(str(caminho))
                    try:
                        self.verificar_indice_e_janela(banco)
                        self.assertEqual([tuple(r) for r in banco.todos(
                            "SELECT * FROM movimentos_estoque ORDER BY id")], antes)
                        self.assertEqual(banco.valor(
                            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'ix_movest_consumo'"), 1)
                        self.assertEqual(banco.valor("PRAGMA integrity_check"), "ok")
                        self.assertEqual(banco.todos("PRAGMA foreign_key_check"), [])
                    finally:
                        banco.fechar()
                self.assertEqual(len(list(Path(pasta).glob("*.bak"))), 1)
