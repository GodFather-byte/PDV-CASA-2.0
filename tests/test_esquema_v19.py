"""Migração v18 -> v19: módulo de operação Cozinha/Bar (setores de impressão nomeados e status de
preparo por item). Mesmo padrão de tests/test_fila_impressao.py::TesteMigracaoV5."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from src.database.conexao import BancoDados


class TesteMigracaoV19(unittest.TestCase):
    def test_banco_da_versao_18_ganha_setores_e_status_de_preparo_sem_perder_dados(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        caminho = os.path.join(d, "v18.db")
        b = BancoDados(caminho)
        sub_id = b.valor("SELECT id FROM subgrupos LIMIT 1")
        b.executar("DROP TABLE setores_impressao")
        b.executar("ALTER TABLE subgrupos DROP COLUMN setor_impressao_id")
        b.executar("ALTER TABLE itens_venda DROP COLUMN status_preparo")
        b.executar("ALTER TABLE itens_venda DROP COLUMN preparo_atualizado_em")
        b.executar("ALTER TABLE itens_venda DROP COLUMN preparo_operador_id")
        b.executar("ALTER TABLE fila_impressao DROP COLUMN setor_id")
        b.executar("PRAGMA user_version = 18")
        b.fechar()

        b = BancoDados(caminho)
        self.addCleanup(b.fechar)

        self.assertGreaterEqual(b.valor("PRAGMA user_version"), 19)
        self.assertEqual(b.valor("SELECT COUNT(*) FROM setores_impressao"), 0)   # nasce vazia
        self.assertEqual(b.valor("SELECT id FROM subgrupos WHERE id = ?", (sub_id,)), sub_id)   # nada se perdeu
        self.assertEqual(b.valor("SELECT nome FROM operadores WHERE nome = 'ADM'"), "ADM")

        colunas_subgrupos = {r[1] for r in b.todos("PRAGMA table_info(subgrupos)")}
        self.assertIn("setor_impressao_id", colunas_subgrupos)
        self.assertIsNone(b.valor("SELECT setor_impressao_id FROM subgrupos WHERE id = ?", (sub_id,)))

        colunas_itens = {r[1] for r in b.todos("PRAGMA table_info(itens_venda)")}
        self.assertTrue({"status_preparo", "preparo_atualizado_em", "preparo_operador_id"} <= colunas_itens)
        padrao = next(r for r in b.todos("PRAGMA table_info(itens_venda)") if r[1] == "status_preparo")[4]
        self.assertEqual(padrao, "'pendente'")

        self.assertIn("setor_id", [r[1] for r in b.todos("PRAGMA table_info(fila_impressao)")])

        setor_id = b.inserir("setores_impressao", {"nome": "Cozinha", "conexao": "pasta", "ativo": 1, "ordem": 0})
        b.executar("UPDATE subgrupos SET setor_impressao_id = ? WHERE id = ?", (setor_id, sub_id))
        self.assertEqual(b.valor("SELECT setor_impressao_id FROM subgrupos WHERE id = ?", (sub_id,)), setor_id)


if __name__ == "__main__":
    unittest.main()
