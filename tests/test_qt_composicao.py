"""Contrato da janela Qt de composição com controladores e banco em memória."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from src.controllers.contexto import Contexto
from src.ui_qt.composicao import JanelaComposicao
from src.ui_qt.tema import aplicar
from tests.base import BaseTeste


class TestComposicaoQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)
        aplicar(cls.aplicacao)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.janelas = []
        self.addCleanup(self._fechar_janelas)

    def _fechar_janelas(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self, produto_id=None):
        janela = JanelaComposicao(self.ctx, produto_id)
        self.janelas.append(janela)
        return janela

    def criar_produtos(self):
        produto = self.novo_produto("PIZZA", compoe="N")
        insumo = self.novo_produto("QUEIJO", estoque=True, compoe="S")
        invalido = self.novo_produto("MOLHO DESATIVADO", compoe="N")
        return produto, insumo, invalido

    def test_busca_produto_por_nome_e_codigo(self):
        produto, _, _ = self.criar_produtos()
        janela = self.janela()
        janela.busca_produto.setText("pizza")
        self.assertTrue(janela.buscar_produto())
        self.assertEqual(janela.produto.currentData(), produto)
        self.assertIn("1 produto(s)", janela.mensagem.text())

        codigo = self.ctx.produtos.por_id(produto)["codigo"]
        janela.busca_produto.setText(codigo)
        self.assertTrue(janela.buscar_produto())
        self.assertEqual(janela.produto.currentData(), produto)

    def test_lista_conteudo_unidade_quantidade_e_custo(self):
        produto, insumo, _ = self.criar_produtos()
        unidade_kg = next(u for u in self.ctx.cadastros.listar("unidades")
                          if u["abreviatura"] == "KG")
        self.banco.executar(
            "UPDATE produtos SET unidade_id = ?, ult_preco_cent = 840 WHERE id = ?",
            (unidade_kg["id"], insumo))
        self.ctx.produtos.incluir_composicao(produto, insumo, 0.125)

        janela = self.janela(produto)
        self.assertEqual(janela.grade.rowCount(), 1)
        self.assertEqual(janela.grade.item(0, 1).text(), "QUEIJO")
        self.assertEqual(janela.grade.item(0, 2).text(), "KG")
        self.assertEqual(janela.grade.item(0, 3).text(), "0,1250")
        self.assertEqual(janela.grade.item(0, 4).text(), "R$ 1,05")
        self.assertIn("Custo total: R$ 1,05", janela.custo.text())

    def test_incluir_valida_insumo_compoe_e_preserva_dados_do_produto(self):
        produto, insumo, invalido = self.criar_produtos()
        janela = self.janela(produto)
        ids_insumos = [janela.insumo.itemData(i) for i in range(janela.insumo.count())]
        self.assertIn(insumo, ids_insumos)
        self.assertNotIn(invalido, ids_insumos)
        self.assertIn("(UN)", janela.insumo.itemText(janela.insumo.findData(insumo)))

        antes = dict(self.banco.um("SELECT * FROM produtos WHERE id = ?", (produto,)))
        janela.insumo.setCurrentIndex(janela.insumo.findData(insumo))
        self.assertEqual(janela.rotulo_qtd.text(), "Quantidade (UN)")
        janela.quantidade.setText("0,1235")
        self.assertTrue(janela.incluir())
        composicao = self.ctx.produtos.composicao(produto)
        self.assertEqual(len(composicao), 1)
        self.assertEqual(composicao[0]["quantidade"], 0.1235)
        depois = dict(self.banco.um("SELECT * FROM produtos WHERE id = ?", (produto,)))
        self.assertEqual(depois, antes)

    def test_excluir_composicao_e_cancelamento_nao_altera_relacao(self):
        produto, insumo, _ = self.criar_produtos()
        self.ctx.produtos.incluir_composicao(produto, insumo, 1.25)
        janela = self.janela(produto)
        janela.grade.selectRow(0)

        with patch("src.ui_qt.composicao.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.No):
            self.assertFalse(janela.excluir())
        self.assertEqual(len(self.ctx.produtos.composicao(produto)), 1)

        with patch("src.ui_qt.composicao.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(janela.excluir())
        self.assertEqual(self.ctx.produtos.composicao(produto), [])
        self.assertEqual(janela.grade.rowCount(), 0)

    def test_revogacao_de_acesso_bloqueia_listagem_e_inclusao(self):
        produto, insumo, _ = self.criar_produtos()
        janela = self.janela(produto)
        janela.insumo.setCurrentIndex(janela.insumo.findData(insumo))
        janela.quantidade.setText("1")
        self.banco.executar("UPDATE operadores SET nivel = 0 WHERE id = ?",
                            (self.ctx.operador_id,))

        self.assertFalse(janela.carregar())
        self.assertIn("não permite", janela.mensagem.text())
        self.assertFalse(janela.incluir())
        self.assertEqual(self.ctx.produtos.composicao(produto), [])
        self.assertEqual(janela.grade.rowCount(), 0)
