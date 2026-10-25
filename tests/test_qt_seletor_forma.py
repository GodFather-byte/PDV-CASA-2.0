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
        self.assertEqual([b.text() for b in s._grupo.buttons()], ["1  ·  Dinheiro", "2  ·  Cartão Débito", "3  ·  Pix"])
        self.assertEqual(s.findText("Pix"), 2)
        self.assertEqual(s.findData(len("Pix")), 2)
        vistos = []
        s.currentIndexChanged.connect(vistos.append)
        s._grupo.button(1).click()
        self.assertEqual((s.currentText(), vistos), ("Cartão Débito", [1]))
        self.assertTrue(s._grupo.button(1).isChecked() and not s._grupo.button(0).isChecked())
        s._grupo.button(1).click()                               # clicar de novo não desmarca
        self.assertTrue(s._grupo.button(1).isChecked())

    def test_setas_mudam_a_forma_no_caixa(self):
        self.abrir_turno()
        j = self.janela()
        j.activateWindow()
        j.cmb_forma.setFocus()
        self.aplicacao.processEvents()
        QTest.keyClick(j.cmb_forma, Qt.Key_Right)
        self.assertEqual(j.cmb_forma.currentIndex(), 1)
        QTest.keyClick(j.cmb_forma, Qt.Key_Down)
        self.assertEqual(j.cmb_forma.currentIndex(), min(3, j.cmb_forma.count() - 1))
        QTest.keyClick(j.cmb_forma, Qt.Key_Left)
        QTest.keyClick(j.cmb_forma, Qt.Key_Up)
        self.assertEqual(j.cmb_forma.currentIndex(), 0)

    def test_caixa_usa_o_seletor_e_o_clique_leva_ao_valor(self):
        self.abrir_turno()
        j = self.janela()
        self.assertIsInstance(j.cmb_forma, SeletorForma)
        self.assertEqual(j.cmb_forma.currentText().strip().casefold(), "dinheiro")
        j.cmb_forma._grupo.button(1).click()
        self.assertEqual(j.focusWidget(), j.ent_valor)

    def test_valor_e_troco_maiores(self):
        self.abrir_turno()
        j = self.janela()
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
