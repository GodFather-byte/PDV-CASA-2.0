"""Migração v22 -> v23: operador e observação nos movimentos de estoque."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.database.conexao import BancoDados


class TesteMigracaoV23(unittest.TestCase):
    def test_adiciona_rastreabilidade_a_movimentos_existentes(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "v22.db"
            banco = BancoDados(str(caminho))
            for linha in banco.todos(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'auditoria_%_estoque_%'"):
                banco.executar(f'DROP TRIGGER "{linha["name"]}"')
            banco.executar("ALTER TABLE movimentos_estoque DROP COLUMN observacao")
            banco.executar("ALTER TABLE movimentos_estoque DROP COLUMN operador_id")
            banco.executar("ALTER TABLE lancamentos_estoque DROP COLUMN tipo_perda")
            banco.executar("PRAGMA user_version = 22")
            banco.fechar()

            banco = BancoDados(str(caminho))
            self.addCleanup(banco.fechar)
            colunas = {linha["name"] for linha in banco.todos("PRAGMA table_info(movimentos_estoque)")}
            self.assertEqual(banco.valor("PRAGMA user_version"), 23)
            self.assertTrue({"operador_id", "observacao"} <= colunas)
            self.assertIn("tipo_perda", {linha["name"] for linha in banco.todos("PRAGMA table_info(lancamentos_estoque)")})


if __name__ == "__main__":
    unittest.main()
