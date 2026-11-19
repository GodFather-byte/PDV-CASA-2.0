"""Tema: hierarquia dos botões, colunas das tabelas e janela do tamanho do conteúdo (ajuste da primeira exibição)."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,  # noqa: E402
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from src.ui_qt import tema  # noqa: E402

APP = QApplication.instance() or QApplication([])


class Janela(QDialog):
    pass


Janela.__module__ = "src.ui_qt.teste"        # o realce só vale para telas do PDV


class TestTemaModerno(unittest.TestCase):
    def montar(self):
        j = Janela()
        v = QVBoxLayout(j)
        linha = QHBoxLayout()
        self.salvar, self.excluir, self.novo = QPushButton("Salvar"), QPushButton("Excluir"), QPushButton("Novo")
        for b in (self.salvar, self.excluir, self.novo):
            linha.addWidget(b)
        v.addLayout(linha)
        self.tabela = QTableWidget(2, 3)
        self.tabela.setHorizontalHeaderLabels(["Código", "Produto com nome comprido", "Preço"])
        self.tabela.setItem(0, 1, QTableWidgetItem("CERVEJA LATA 350ML GELADA"))
        v.addWidget(self.tabela)
        self.fechar = QPushButton("Fechar")
        v.addWidget(self.fechar)
        j.resize(300, 200)
        return j

    def test_botoes_ganham_hierarquia_e_fechar_nao_estica(self):
        j = self.montar()
        tema.realcar_botoes(j)
        self.assertEqual(self.salvar.objectName(), "primario")
        self.assertEqual(self.excluir.objectName(), "perigo")
        self.assertEqual(self.novo.objectName(), "")
        self.assertEqual(j.layout().itemAt(j.layout().indexOf(self.fechar)).alignment(), Qt.AlignRight)

    def test_tela_que_ja_escolheu_o_primario_fica_como_esta(self):
        j = self.montar()
        self.novo.setObjectName("primario")
        tema.realcar_botoes(j)
        self.assertEqual(self.salvar.objectName(), "")

    def test_colunas_cabem_o_conteudo_e_tabela_configurada_nao_muda(self):
        j = self.montar()
        tema.ajustar_tabelas(j)
        cab = self.tabela.horizontalHeader()
        self.assertGreaterEqual(cab.sectionSize(1), cab.sectionSizeHint(1))
        self.assertTrue(cab.stretchLastSection())
        outra = QTableWidget(1, 2)
        outra.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        outra.horizontalHeader().resizeSection(0, 40)
        j.layout().addWidget(outra)
        tema.ajustar_tabelas(j)
        self.assertEqual(outra.horizontalHeader().sectionSize(0), 40)
        self.assertFalse(outra.horizontalHeader().stretchLastSection())

    def test_janela_cresce_ate_o_conteudo_sem_passar_da_tela(self):
        j = self.montar()
        tema.ajustar_janela(j)
        area = tema._area_util(j)
        self.assertGreaterEqual(j.width(), min(j.sizeHint().width(), area.width() - tema.RESERVA_LARGURA))
        self.assertLessEqual(j.width(), area.width())

    def test_contraste_de_texto_acao_e_foco_nos_dois_modos(self):
        def luminancia(cor):
            canais = (cor.redF(), cor.greenF(), cor.blueF())
            r, g, b = (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in canais)
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        def contraste(cor, fundo):
            menor, maior = sorted((luminancia(cor), luminancia(fundo)))
            return (maior + 0.05) / (menor + 0.05)

        def cor_da_borda(widget):
            imagem = widget.grab().toImage()
            return imagem.pixelColor(0, imagem.height() // 2)

        janela = Janela()
        self.addCleanup(APP.setStyleSheet, APP.styleSheet())
        self.addCleanup(APP.setPalette, APP.palette())
        self.addCleanup(janela.close)
        layout = QVBoxLayout(janela)
        legenda = QLabel("Operador")
        legenda.setObjectName("suave")
        acao = QPushButton("Entrar")
        acao.setObjectName("primario")
        campos = (QLineEdit(), QComboBox(), QSpinBox())
        for widget in (legenda, *campos, acao):
            layout.addWidget(widget)
        janela.show()
        janela.activateWindow()
        for modo in ("claro", "escuro"):
            with self.subTest(modo=modo):
                tema.aplicar(APP, modo)
                APP.processEvents()
                fundo = janela.palette().color(QPalette.Window)
                texto = janela.palette().color(QPalette.WindowText)
                self.assertEqual(luminancia(fundo) > luminancia(texto), modo == "claro")
                self.assertGreaterEqual(contraste(texto, fundo), 4.5)
                self.assertGreaterEqual(contraste(legenda.palette().color(QPalette.WindowText), fundo), 4.5)
                botao = acao.palette()
                self.assertGreaterEqual(contraste(botao.color(QPalette.ButtonText), botao.color(QPalette.Button)), 4.5)
                for campo in campos:
                    acao.setFocus()
                    APP.processEvents()
                    normal = cor_da_borda(campo)
                    campo.setFocus()
                    APP.processEvents()
                    foco = cor_da_borda(campo)
                    self.assertTrue(campo.hasFocus())
                    self.assertNotEqual(normal, foco)
                    base = campo.palette().color(QPalette.Base)
                    self.assertGreaterEqual(contraste(campo.palette().color(QPalette.Text), base), 4.5)
                    self.assertGreaterEqual(contraste(foco, base), 3)


if __name__ == "__main__":
    unittest.main()
