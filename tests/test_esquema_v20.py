"""Migração v19 -> v20: módulo de operação Rodízio (cobrança fixa por pessoa, por mesa/comanda).
Mesmo padrão de tests/test_esquema_v19.py."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from src.database.conexao import BancoDados


class TesteMigracaoV20(unittest.TestCase):
    def test_banco_da_versao_19_ganha_as_colunas_do_rodizio_sem_perder_dados(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        caminho = os.path.join(d, "v19.db")
        b = BancoDados(caminho)
        sub_id = b.valor("SELECT id FROM subgrupos LIMIT 1")
        b.executar("ALTER TABLE subgrupos DROP COLUMN rodizio_incluso")
        b.executar("ALTER TABLE vendas DROP COLUMN rodizio")
        b.executar("ALTER TABLE vendas DROP COLUMN rodizio_total_cent")
        b.executar("PRAGMA user_version = 19")
        b.fechar()

        b = BancoDados(caminho)
        self.addCleanup(b.fechar)

        self.assertGreaterEqual(b.valor("PRAGMA user_version"), 20)
        self.assertEqual(b.valor("SELECT id FROM subgrupos WHERE id = ?", (sub_id,)), sub_id)   # nada se perdeu
        self.assertEqual(b.valor("SELECT nome FROM operadores WHERE nome = 'ADM'"), "ADM")

        colunas_subgrupos = {r[1] for r in b.todos("PRAGMA table_info(subgrupos)")}
        self.assertIn("rodizio_incluso", colunas_subgrupos)
        self.assertEqual(b.valor("SELECT rodizio_incluso FROM subgrupos WHERE id = ?", (sub_id,)), 0)

        colunas_vendas = {r[1] for r in b.todos("PRAGMA table_info(vendas)")}
        self.assertTrue({"rodizio", "rodizio_total_cent"} <= colunas_vendas)

        b.executar("UPDATE subgrupos SET rodizio_incluso = 1 WHERE id = ?", (sub_id,))
        self.assertEqual(b.valor("SELECT rodizio_incluso FROM subgrupos WHERE id = ?", (sub_id,)), 1)


if __name__ == "__main__":
    unittest.main()
