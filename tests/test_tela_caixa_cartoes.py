"""A tela do caixa refeita: coluna de cartões, indicadores do cabeçalho, selo da venda, nome da comanda, navegação entre
comandas (clientes e garotas), ações da linha e a disposição que acompanha o tamanho da janela."""
from __future__ import annotations

import os
import re
import tempfile
import unittest

from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.database.esquema import VERSAO_ESQUEMA


def achar(w, classe):
    """O primeiro widget da `classe` dentro de `w`."""
    for f in w.winfo_children():
        if isinstance(f, classe):
            return f
        dentro = achar(f, classe)
        if dentro is not None:
            return dentro
    return None


class TesteMigracaoDoNome(unittest.TestCase):
    def test_banco_v14_ganha_a_coluna_do_nome(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "v14.db")
            b = BancoDados(caminho)
            b.executar("ALTER TABLE vendas DROP COLUMN apelido")
            b.executar("PRAGMA user_version = 14")
            b.fechar()
            b = BancoDados(caminho)
            try:
                self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
                self.assertIn("apelido", {r[1] for r in b.todos("PRAGMA table_info(vendas)")})
            finally:
                b.fechar()


if __name__ == "__main__":
    unittest.main()
