"""Migração v20 -> v21: módulo de operação Pré-pago (comanda pré-paga e pagamento marcado como recarga).
Mesmo padrão de tests/test_esquema_v20.py."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from src.database.conexao import BancoDados


class TesteMigracaoV21(unittest.TestCase):
    def test_banco_da_versao_20_ganha_as_colunas_do_pre_pago_sem_perder_dados(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        caminho = os.path.join(d, "v20.db")
        b = BancoDados(caminho)
        b.executar("ALTER TABLE vendas DROP COLUMN prepago")
        b.executar("ALTER TABLE pagamentos_venda DROP COLUMN recarga")
        b.executar("PRAGMA user_version = 20")
        b.fechar()

        b = BancoDados(caminho)
        self.addCleanup(b.fechar)

        self.assertGreaterEqual(b.valor("PRAGMA user_version"), 21)
        self.assertEqual(b.valor("SELECT nome FROM operadores WHERE nome = 'ADM'"), "ADM")   # nada se perdeu
        self.assertIn("prepago", {r[1] for r in b.todos("PRAGMA table_info(vendas)")})
        self.assertIn("recarga", {r[1] for r in b.todos("PRAGMA table_info(pagamentos_venda)")})
        for tabela, coluna in (("vendas", "prepago"), ("pagamentos_venda", "recarga")):
            padrao = next(r for r in b.todos(f"PRAGMA table_info({tabela})") if r[1] == coluna)[4]
            self.assertEqual(padrao, "0", coluna)


if __name__ == "__main__":
    unittest.main()
