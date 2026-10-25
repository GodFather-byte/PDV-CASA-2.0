"""Tela cheia do caixa e valor/troco maiores."""
from __future__ import annotations

import unittest

from tests.test_qt_caixa import BaseCaixaQt

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
except ImportError:                                   # pragma: no cover - sem PySide6 estes testes não rodam
    Qt = None


class TesteValorETroco(BaseCaixaQt):
    def test_forma_comeca_em_dinheiro_e_valor_e_troco_sao_maiores(self):
        self.abrir_turno()
        j = self.janela()
        self.assertEqual(j.cmb_forma.currentText().strip().casefold(), "dinheiro")
        self.assertGreaterEqual(j.ent_valor.sizeHint().height(), 44)
        self.assertIn("16pt", j.styleSheet().split("QLineEdit#valor")[1].split("}")[0])
        self.assertIn("22pt", j.styleSheet().split("QLabel#troco")[1].split("}")[0])


class TesteTelaCheia(BaseCaixaQt):
    def test_alterna_e_volta(self):
        # Sem janela real em tela cheia: sem gerenciador de janelas (xvfb do CI) isso só traz instabilidade; o estado é simulado.
        self.abrir_turno()
        j = self.janela()
        estado = {"cheia": False}
        j.showFullScreen = lambda: estado.update(cheia=True)
        j.showNormal = lambda: estado.update(cheia=False)
        j.isFullScreen = lambda: estado["cheia"]
        j.alternar_tela_cheia()
        self.assertTrue(estado["cheia"])
        self.assertIn("Sair", j.btn_tela_cheia.text())
        j.alternar_tela_cheia()
        self.assertFalse(estado["cheia"])
        self.assertNotIn("Sair", j.btn_tela_cheia.text())

    def test_config_padrao_liga_a_tela_cheia(self):
        self.assertEqual(self.banco.cfg("caixa_tela_cheia"), "S")


if __name__ == "__main__":
    unittest.main()
