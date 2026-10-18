"""Taxa do cartão de crédito: pagar no crédito acrescenta R$ 5,00 ao total da venda (uma vez por venda)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from src.controllers.impressao_controller import ImpressaoController
from src.database.conexao import BancoDados
from src.database import esquema
from src.database.esquema import VERSAO_ESQUEMA
from tests.test_caixa import BaseCaixa


class TesteTaxaCredito(BaseCaixa):
    def test_forma_credito_semeada_com_taxa_de_5_reais(self):
        self.assertEqual(self.banco.valor("SELECT acrescimo_cent FROM tipos_pagamento WHERE tipo = 'Cartão Crédito'"), 500)
        self.assertEqual(self.banco.valor("SELECT acrescimo_cent FROM tipos_pagamento WHERE tipo = 'Cartão Débito'"), 0)

    def test_credito_acrescenta_5_reais_ao_total(self):
        vid = self.vender((self.skol, 1))                                  # 8,00
        self.assertEqual(self.caixa.acrescimo_da_forma(vid, self.tipo("Cartão Crédito")), 500)
        self.pagar(vid, "Cartão Crédito", 1300)
        v = self.caixa.obter(vid)
        self.assertEqual((v["acrescimo_cent"], v["total_cent"]), (500, 1300))
        v = self.caixa.fechar(vid)
        self.assertEqual((v["status"], v["total_cent"], v["acrescimo_cent"]), ("fechada", 1300, 500))

    def test_pagar_so_o_valor_dos_produtos_no_credito_deixa_faltando_a_taxa(self):
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Cartão Crédito", 800)
        with self.assertRaises(Exception) as e:
            self.caixa.fechar(vid)
        self.assertIn("Faltam R$ 5,00", str(e.exception))

    def test_outras_formas_nao_tem_taxa(self):
        for forma in ("Dinheiro", "Cartão Débito", "Pix"):
            vid = self.vender((self.agua, 1))
            self.pagar(vid, forma, 350)
            v = self.caixa.fechar(vid)
            self.assertEqual((v["total_cent"], v["acrescimo_cent"]), (350, 0), forma)

    def test_taxa_e_cobrada_uma_vez_por_venda(self):
        vid = self.vender((self.skol, 5))                                  # 40,00
        self.pagar(vid, "Cartão Crédito", 2000)
        self.assertEqual(self.caixa.acrescimo_da_forma(vid, self.tipo("Cartão Crédito")), 0)
        self.pagar(vid, "Cartão Crédito", 2500)
        v = self.caixa.fechar(vid)
        self.assertEqual((v["total_cent"], v["acrescimo_cent"]), (4500, 500))

    def test_dinheiro_mais_credito(self):
        vid = self.vender((self.skol, 5))                                  # 40,00
        self.pagar(vid, "Dinheiro", 2000)
        self.pagar(vid, "Cartão Crédito", 2500)
        self.assertEqual(self.caixa.fechar(vid)["total_cent"], 4500)

    def test_remover_o_pagamento_no_credito_tira_a_taxa(self):
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Cartão Crédito", 1300)
        pid = self.caixa.pagamentos(vid)[0]["id"]
        self.caixa.remover_pagamento(pid)
        v = self.caixa.obter(vid)
        self.assertEqual((v["acrescimo_cent"], v["total_cent"]), (0, 800))

    def test_taxa_configuravel_na_forma(self):
        self.banco.executar("UPDATE tipos_pagamento SET acrescimo_cent = 0 WHERE tipo = 'Cartão Crédito'")
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Cartão Crédito", 800)
        self.assertEqual(self.caixa.fechar(vid)["total_cent"], 800)

    def test_cupom_e_fechamento_mostram_a_taxa(self):
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Cartão Crédito", 1300)
        self.caixa.fechar(vid)
        cupom = ImpressaoController(self.banco).cupom(vid)
        self.assertRegex(cupom, r"Taxa do crédito \(\+\) +5,00")
        self.assertEqual(self.turnos.resumo(self.turno)["acrescimo"], 500)


class TesteMigracaoTaxaCredito(unittest.TestCase):
    def test_banco_v13_ganha_a_taxa_no_cartao_de_credito(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "v13.db")
            # A fixture v13 não deve carregar os gatilhos introduzidos na v18.
            with patch.object(esquema, "AUDITORIA", []):
                b = BancoDados(caminho)
            self.assertIsNone(b.um(
                "SELECT name FROM sqlite_master WHERE name = 'auditoria_eventos'"))
            b.executar("INSERT INTO tipos_pagamento(tipo, ordem) VALUES ('Crédito Loja', 20)")
            b.executar("ALTER TABLE tipos_pagamento DROP COLUMN acrescimo_cent")
            b.executar("ALTER TABLE vendas DROP COLUMN acrescimo_cent")
            for tabela in ("tipos_pagamento", "vendas"):
                self.assertNotIn("acrescimo_cent", {r[1] for r in b.todos(f"PRAGMA table_info({tabela})")})
            b.executar("PRAGMA user_version = 13")
            b.fechar()
            b = BancoDados(caminho)
            try:
                self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
                taxas = {r["tipo"]: r["acrescimo_cent"] for r in b.todos("SELECT tipo, acrescimo_cent FROM tipos_pagamento")}
                self.assertEqual(taxas["Cartão Crédito"], 500)
                self.assertEqual(taxas["Cartão Débito"], 0)
                self.assertEqual(taxas["Crédito Loja"], 0)            # crédito da loja não é cartão
                self.assertIn("acrescimo_cent", {r[1] for r in b.todos("PRAGMA table_info(vendas)")})
            finally:
                b.fechar()


if __name__ == "__main__":
    unittest.main()
