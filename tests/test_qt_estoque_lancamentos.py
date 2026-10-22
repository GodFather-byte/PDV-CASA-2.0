"""Testes dos lançamentos de estoque Qt com controladores e banco em memória."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from src.controllers.contexto import Contexto
from src.ui_qt.estoque_lancamentos import JanelaLancamentosEstoque
from src.ui_qt.tema import aplicar
from tests.base import BaseTeste


class TestLancamentosEstoqueQt(BaseTeste):
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

    def janela(self, lancamento_id=None):
        janela = JanelaLancamentosEstoque(
            self.ctx, lancamento_id=lancamento_id)
        self.janelas.append(janela)
        return janela

    def test_novo_lancamento_compra_guarda_custos_em_centavos_e_movimenta_saldo(self):
        produto_id = self.novo_produto("GELO", estoque=True)
        fornecedor_id = self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        janela = self.janela()
        janela.tipo.setCurrentIndex(janela.tipo.findData("compra"))
        janela.fornecedor.setCurrentIndex(janela.fornecedor.findData(fornecedor_id))
        janela.descricao.setText("Compra semanal")
        janela.data.setText("03/10/2026")
        janela.valor_nota.setText("123,45")
        janela.documento.setText("NF-10")
        janela.nota_fiscal.setText("00010")
        self.assertTrue(janela.iniciar())
        lancamento_id = janela.lancamento_id
        self.assertEqual(janela.lancamento["valor_cent"], 12345)
        self.assertEqual(janela.lancamento["fornecedor_id"], fornecedor_id)
        self.assertEqual(janela.lancamento["documento"], "NF-10")
        self.assertTrue(janela.valor_nota.isEnabled() is False)

        janela.produto.setCurrentIndex(janela.produto.findData(produto_id))
        janela.quantidade.setText("2")
        janela.valor_item.setText("10,25")
        janela.desconto_item.setText("1,00")
        self.assertTrue(janela.adicionar_item())
        item = self.ctx.estoque.itens(lancamento_id)[0]
        self.assertEqual((item["valor_cent"], item["desconto_cent"]), (1025, 100))
        self.assertEqual(item["preco_unit_cent"], 463)
        self.assertEqual(
            self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto_id,)),
            2)
        self.assertEqual(
            self.banco.valor("SELECT ult_preco_cent FROM produtos WHERE id = ?", (produto_id,)),
            463)
        self.assertEqual(self.ctx.estoque.lancamento(lancamento_id)["valor_cent"], 12345)
        self.assertEqual(janela.grade_itens.item(0, 6).text(), "10,25")

    def test_pedido_pendente_permite_cancelar_custo_e_recusa_confirmacao_sem_alterar_estoque(self):
        produto_id = self.novo_produto("GELO", estoque=True)
        fornecedor_id = self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        lancamento_id = self.ctx.estoque.pedido_sugerido(
            fornecedor_id, [(produto_id, 5)])
        janela = self.janela(lancamento_id)
        self.assertEqual(janela.lancamento["tipo"], "pedido")
        self.assertEqual(
            self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto_id,)),
            0)
        with patch.object(QInputDialog, "getText", return_value=("", False)):
            self.assertFalse(janela.confirmar_entrega())
        self.assertEqual(self.ctx.estoque.lancamento(lancamento_id)["tipo"], "pedido")
        with patch.object(QInputDialog, "getText", return_value=("12,50", True)), \
                patch.object(QMessageBox, "question",
                             return_value=QMessageBox.StandardButton.No):
            self.assertFalse(janela.confirmar_entrega())
        self.assertEqual(self.ctx.estoque.lancamento(lancamento_id)["tipo"], "pedido")
        self.assertEqual(
            self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto_id,)),
            0)
        self.assertEqual(self.ctx.estoque.itens(lancamento_id)[0]["valor_cent"], 0)

    def test_confirmar_entrega_converte_pedido_em_compra_com_custo_em_centavos(self):
        produto_id = self.novo_produto("GELO", estoque=True)
        fornecedor_id = self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        lancamento_id = self.ctx.estoque.pedido_sugerido(
            fornecedor_id, [(produto_id, 5)])
        janela = self.janela(lancamento_id)
        with patch.object(QInputDialog, "getText", return_value=("12,50", True)), \
                patch.object(QMessageBox, "question",
                             return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(janela.confirmar_entrega())
        lancamento = self.ctx.estoque.lancamento(lancamento_id)
        item = self.ctx.estoque.itens(lancamento_id)[0]
        self.assertEqual(lancamento["tipo"], "compra")
        self.assertEqual(lancamento["valor_cent"], 1250)
        self.assertEqual((item["valor_cent"], item["preco_unit_cent"]), (1250, 250))
        self.assertEqual(
            self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto_id,)),
            5)
        self.assertEqual(
            self.banco.valor("SELECT ult_preco_cent FROM produtos WHERE id = ?", (produto_id,)),
            250)
        self.assertFalse(janela.btn_confirmar.isEnabled())

    def test_revogacao_apos_dialogo_de_custo_impede_confirmacao_e_preserva_saldo(self):
        produto_id = self.novo_produto("GELO", estoque=True)
        fornecedor_id = self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        lancamento_id = self.ctx.estoque.pedido_sugerido(
            fornecedor_id, [(produto_id, 5)])
        self.banco.executar(
            "UPDATE operadores SET nivel = 2 WHERE id = ?", (self.ctx.operador_id,))
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        janela = self.janela(lancamento_id)

        def revogar(*_args, **_kwargs):
            self.banco.executar(
                "UPDATE acessos SET nivel = 3 WHERE modulo = 'lanc_estoque'")
            return "12,50", True

        with patch.object(QInputDialog, "getText", side_effect=revogar):
            self.assertFalse(janela.confirmar_entrega())
        self.assertEqual(self.ctx.estoque.lancamento(lancamento_id)["tipo"], "pedido")
        self.assertEqual(
            self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto_id,)),
            0)
        self.assertEqual(janela.grade_lancamentos.rowCount(), 0)

    def test_revogacao_de_sessao_apos_confirmacao_impede_exclusao(self):
        produto_id = self.novo_produto("GELO", estoque=True)
        lancamento_id = self.ctx.estoque.registrar_rapido(
            produto_id, "entrada", 3)
        self.banco.executar(
            "UPDATE operadores SET nivel = 2 WHERE id = ?", (self.ctx.operador_id,))
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        janela = self.janela(lancamento_id)
        # Reabre o lançamento, e a resposta afirmativa revoga o módulo antes da gravação.
        def revogar(*_args, **_kwargs):
            self.banco.executar(
                "UPDATE acessos SET nivel = 3 WHERE modulo = 'lanc_estoque'")
            return QMessageBox.StandardButton.Yes

        with patch.object(QMessageBox, "question", side_effect=revogar):
            self.assertFalse(janela.excluir_lancamento())
        self.assertEqual(
            self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto_id,)),
            3)
        self.assertEqual(
            self.banco.valor(
                "SELECT COUNT(*) FROM lancamentos_estoque WHERE id = ?",
                (lancamento_id,)), 1)
        self.assertEqual(janela.grade_lancamentos.rowCount(), 0)

    def test_cancelar_exclusao_preserva_movimento_e_confirmar_estorna(self):
        produto_id = self.novo_produto("GELO", estoque=True)
        lancamento_id = self.ctx.estoque.registrar_rapido(
            produto_id, "entrada", 3)
        janela = self.janela(lancamento_id)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No):
            self.assertFalse(janela.excluir_lancamento())
        self.assertEqual(
            self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto_id,)),
            3)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(janela.excluir_lancamento())
        self.assertEqual(
            self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto_id,)),
            0)
        self.assertEqual(
            self.banco.valor(
                "SELECT COUNT(*) FROM lancamentos_estoque WHERE id = ?",
                (lancamento_id,)), 0)

    def test_lista_de_lancamentos_abre_pedido_existente_e_itens_podem_ser_removidos(self):
        produto_id = self.novo_produto("GELO", estoque=True, qt=2)
        fornecedor_id = self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        lancamento_id = self.ctx.estoque.pedido_sugerido(
            fornecedor_id, [(produto_id, 5)])
        janela = self.janela()
        self.assertEqual(janela.grade_lancamentos.rowCount(), 1)
        self.assertEqual(janela.grade_lancamentos.item(0, 1).text(), "Pedido")
        janela.grade_lancamentos.selectRow(0)
        self.assertEqual(janela.lancamento_id, lancamento_id)
        self.assertEqual(janela.grade_itens.rowCount(), 1)
        janela.grade_itens.selectRow(0)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No):
            self.assertFalse(janela.remover_item())
        self.assertEqual(self.ctx.estoque.itens(lancamento_id)[0]["quantidade"], 5)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(janela.remover_item())
        self.assertEqual(self.ctx.estoque.itens(lancamento_id), [])
        self.assertEqual(self.ctx.estoque.lancamento(lancamento_id)["tipo"], "pedido")

    def test_revogacao_apos_dialogo_de_exclusao_de_item_impede_estorno(self):
        produto_id = self.novo_produto("GELO", estoque=True)
        lancamento_id = self.ctx.estoque.registrar_rapido(
            produto_id, "entrada", 3)
        item = self.ctx.estoque.itens(lancamento_id)[0]
        self.banco.executar(
            "UPDATE operadores SET nivel = 2 WHERE id = ?", (self.ctx.operador_id,))
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        janela = self.janela(lancamento_id)
        janela.grade_itens.selectRow(0)

        def revogar(*_args, **_kwargs):
            self.banco.executar(
                "UPDATE acessos SET nivel = 3 WHERE modulo = 'lanc_estoque'")
            return QMessageBox.StandardButton.Yes

        with patch.object(QMessageBox, "question", side_effect=revogar):
            self.assertFalse(janela.remover_item())
        self.assertEqual(
            self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto_id,)),
            3)
        self.assertEqual(self.ctx.estoque.itens(lancamento_id)[0]["id"], item["id"])
