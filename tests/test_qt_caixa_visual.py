"""Coluna do meio do caixa repaginada: etiqueta da venda, produto achado antes do Enter, − e + da quantidade, item recém-lançado
em destaque, lista vazia com orientação, atalhos como teclas e a tabela sem rolagem para o lado."""
from __future__ import annotations

import unittest

from tests.test_qt_caixa import BaseCaixaQt

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
except ImportError:                                   # pragma: no cover - sem PySide6 estes testes não rodam
    Qt = None


class TesteColunaDoMeio(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.abrir_turno()
        self.skol = self.novo_produto("SKOL", 800, codigo="101")
        self.heineken = self.novo_produto("HEINEKEN", 1200, codigo="44", estoque=True, qt=48)
        self.j = self.janela()

    def chamar(self, texto):
        self.j.ent_pos.setText(texto)
        self.j.btn_chamar.click()

    def test_etiqueta_mostra_o_tipo_da_venda_e_a_garota_em_rosa(self):
        self.assertEqual(self.j.lbl_etq_venda.text(), "BALCÃO")
        self.chamar("M5")
        self.assertEqual(self.j.lbl_etq_venda.text(), "MESA")
        self.chamar("130")
        self.assertEqual(self.j.lbl_etq_venda.text(), "COMANDA")              # comanda sem comissão nem cadastro
        self.j.ctx.comissoes.lancar(130, 1500, self.j._turno()["id"], self.j.ctx.operador_id)
        self.j.recarregar()
        self.assertEqual(self.j.lbl_etq_venda.text(), "GAROTA")
        from src.ui_qt.caixa import ETIQUETAS
        rosa = ETIQUETAS[self.j._modo_visual()]["garota"][0]
        self.assertIn(rosa, self.j.lbl_etq_venda.styleSheet())
        self.assertEqual(self.j.lbl_venda.text(), "Comanda 130  ·  Aberta")   # sem o número repetido

    def test_codigo_enter_mostra_o_produto_achado_e_os_botoes_mudam_a_quantidade(self):
        self.j.ent_codigo.setText("44")
        self.j.lancar_item(pedir_quantidade=True)
        self.assertTrue(self.j.lbl_achado.isVisibleTo(self.j))
        self.assertIn("HEINEKEN", self.j.lbl_achado.text())
        self.assertIn("estoque: 48", self.j.lbl_achado.text())
        self.assertIn("1 × R$ 12,00 = R$ 12,00", self.j.lbl_achado.text())
        self.j.btn_qtd_mais.click()
        self.j.btn_qtd_mais.click()
        self.assertEqual(self.j.ent_qtd.text(), "3")
        self.assertIn("3 × R$ 12,00 = R$ 36,00", self.j.lbl_achado.text())
        for _ in range(5):
            self.j.btn_qtd_menos.click()
        self.assertEqual(self.j.ent_qtd.text(), "1")                           # nunca abaixo de 1
        self.j.ent_qtd.setText("2")
        self.j.lancar_item()                                                    # o segundo Enter lança
        self.assertFalse(self.j.lbl_achado.isVisibleTo(self.j))
        self.assertEqual(self.contar("itens_venda"), 1)

    def test_item_recem_lancado_fica_em_destaque_ate_o_proximo(self):
        self.lancar(self.j, "101")
        verde = self.j.tabela.item(0, 1).background().color()
        self.assertNotEqual(verde, QColor(0, 0, 0))
        self.assertTrue(self.j.tabela.item(0, 1).font().bold())
        self.lancar(self.j, "44")
        self.assertFalse(self.j.tabela.item(0, 1).font().bold())               # o anterior volta ao normal
        self.assertTrue(self.j.tabela.item(1, 1).font().bold())

    def test_lista_vazia_orienta_e_some_com_o_primeiro_item(self):
        self.assertTrue(self.j.lbl_vazio.isVisibleTo(self.j))
        self.assertIn("Passe o leitor", self.j.lbl_vazio.text())
        self.lancar(self.j, "101")
        self.assertFalse(self.j.lbl_vazio.isVisibleTo(self.j))

    def test_atalhos_como_teclas_e_tabela_sem_rolagem_para_o_lado(self):
        from PySide6.QtWidgets import QLabel
        teclas = [l.text() for l in self.j.lbl_dica_nav.findChildren(QLabel) if l.objectName() == "tecla"]
        self.assertEqual(teclas, ["Enter", "F12", "Esc", "Del"])
        self.assertEqual(self.j.tabela.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        self.assertIn(self.j.btn_operacoes.objectName(), ("neutro",))
        self.assertEqual(self.j.btn_cancelar_venda.objectName(), "cancelar")
        self.assertEqual(self.j.btn_comissoes.objectName(), "rosa")


if __name__ == "__main__":
    unittest.main()


class TesteCaixaCabeNoMonitor(BaseCaixaQt):
    """O monitor do balcão tem 1366 pontos de largura: a janela não pode exigir mais que isso, senão estica para fora da tela
    e corta o painel do pagamento (aconteceu na comanda da garota com comissão, com os quatro botões de baixo visíveis)."""

    def test_comanda_da_garota_com_comissao_cabe_em_1366_nos_dois_modos(self):
        self.abrir_turno()
        for modo in ("claro", "escuro"):
            self.banco.cfg_set("tema_visual", modo)
            j = self.janela()
            j.resize(1366, 768)
            self.aplicacao.processEvents()
            self.assertLessEqual(j.minimumSizeHint().width(), 1340, f"balcão vazio, modo {modo}")   # com folga
            j.ent_pos.setText("122")
            j.btn_chamar.click()
            for valor in (3000, 1500, 3000):
                self.ctx.comissoes.lancar(122, valor, j._turno()["id"], self.ctx.operador_id)
            j.recarregar()
            self.aplicacao.processEvents()
            self.assertTrue(j.btn_pagar_garota.isVisibleTo(j))
            self.assertLessEqual(j.minimumSizeHint().width(), 1340, f"comanda da garota, modo {modo}")
            self.assertLessEqual(j.width(), 1366)
            self.banco.executar("DELETE FROM comissoes_garotas")
            j.close()
