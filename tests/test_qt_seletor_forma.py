"""Seletor da forma de pagamento em botões, tela cheia do caixa e valores maiores."""
from __future__ import annotations

import unittest

from tests.test_qt_caixa import BaseCaixaQt

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
except ImportError:                                   # pragma: no cover - sem PySide6 estes testes não rodam
    Qt = None

from src.ui_qt.seletor_forma import SeletorForma


class TesteSeletorForma(BaseCaixaQt):
    def novo_seletor(self, *formas):
        s = SeletorForma()
        self.addCleanup(s.deleteLater)           # sem dono: destrói no teste, não na coleta de lixo do fim do processo
        self.addCleanup(s.close)
        for nome in formas:
            s.addItem(nome, len(nome))
        return s

    def test_um_botao_por_forma_com_o_numero_e_dinheiro_marcado(self):
        s = self.novo_seletor("Dinheiro", "Cartão Débito", "Pix")
        self.assertEqual(s.count(), 3)
        self.assertEqual(s.currentText(), "Dinheiro")
        self.assertEqual([b.text() for b in s._botoes], ["1  ·  Dinheiro", "2  ·  Cartão Débito", "3  ·  Pix"])
        self.assertEqual(s.findText("Pix"), 2)
        self.assertEqual(s.findData(len("Pix")), 2)
        vistos = []
        s.currentIndexChanged.connect(vistos.append)
        s._botoes[1].click()
        self.assertEqual((s.currentText(), vistos), ("Cartão Débito", [1]))
        self.assertTrue(s._botoes[1].isChecked() and not s._botoes[0].isChecked())
        s._botoes[1].click()                               # clicar de novo não desmarca
        self.assertTrue(s._botoes[1].isChecked())

    def test_setas_mudam_a_forma(self):
        s = self.novo_seletor("Dinheiro", "Cartão Débito", "Cartão Crédito", "Pix")
        s.show()
        QTest.keyClick(s, Qt.Key_Right)
        self.assertEqual(s.currentIndex(), 1)
        QTest.keyClick(s, Qt.Key_Down)
        self.assertEqual(s.currentIndex(), 3)
        QTest.keyClick(s, Qt.Key_Left)
        QTest.keyClick(s, Qt.Key_Up)
        self.assertEqual(s.currentIndex(), 0)

    def test_caixa_usa_o_seletor_e_o_clique_leva_ao_valor(self):
        self.abrir_turno()
        j = self.janela()
        self.assertIsInstance(j.cmb_forma, SeletorForma)
        self.assertEqual(j.cmb_forma.currentText().strip().casefold(), "dinheiro")
        j.cmb_forma._botoes[1].click()
        self.assertEqual(j.focusWidget(), j.ent_valor)

    def test_valor_e_troco_maiores(self):
        self.abrir_turno()
        j = self.janela()
        self.assertGreaterEqual(j.ent_valor.sizeHint().height(), 44)
        self.assertIn("16pt", j.styleSheet().split("QLineEdit#valor")[1].split("}")[0])
        self.assertIn("22pt", j.styleSheet().split("QLabel#troco")[1].split("}")[0])


class TesteTelaCheia(BaseCaixaQt):
    def test_alterna_e_volta(self):
        self.abrir_turno()
        j = self.janela()
        self.assertFalse(j.isFullScreen())
        j.alternar_tela_cheia()
        self.assertTrue(j.isFullScreen())
        self.assertIn("Sair", j.btn_tela_cheia.text())
        j.alternar_tela_cheia()
        self.assertFalse(j.isFullScreen())
        self.assertNotIn("Sair", j.btn_tela_cheia.text())

    def test_config_padrao_liga_a_tela_cheia(self):
        self.assertEqual(self.banco.cfg("caixa_tela_cheia"), "S")


if __name__ == "__main__":
    unittest.main()
