"""Tema: hierarquia dos botões, colunas das tabelas e janela do tamanho do conteúdo (ajuste da primeira exibição)."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QHeaderView, QPushButton, QTableWidget,  # noqa: E402
                               QTableWidgetItem, QVBoxLayout)

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

    def test_cores_novas_tem_versao_no_modo_claro(self):
        import re
        claro = {}
        from pathlib import Path
        codigo = Path(tema.__file__).read_text(encoding="utf-8")
        for original, nova in re.findall(r'"(#[0-9a-f]{6})": "(#[0-9a-f]{6})"', codigo):
            claro[original] = nova
        usadas = set(re.findall(r"#[0-9a-f]{6}", tema.ESTILO))
        self.assertFalse(usadas - set(claro), "cor do tema escuro sem par no claro")


if __name__ == "__main__":
    unittest.main()
