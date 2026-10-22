"""Janelas Qt de retornáveis, com banco real e revalidação de sessão."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.core.erros import ErroPermissao
from src.controllers.contexto import Contexto
from src.ui_qt.retornaveis import JanelaRetornaveis
from tests.base import BaseTeste


class TestRetornaveisQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.cliente_id = self.banco.inserir("clientes", {"numero_consulta": "10", "nome": "ANA"})
        self.produto_id = self.novo_produto("BALDE")
        self.janelas = []
        self.addCleanup(self.fechar)

    def fechar(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()

    def janela(self):
        janela = JanelaRetornaveis(self.ctx)
        self.janelas.append(janela)
        janela.cliente.setCurrentIndex(janela.cliente.findData(self.cliente_id))
        janela.produto.setCurrentIndex(janela.produto.findData(self.produto_id))
        janela.quantidade.setText("2,1234")
        janela.motivo.setText("Entrega combinada")
        return janela

    def test_gravar_consultar_e_devolver_sem_dialogos_tk(self):
        janela = self.janela()
        self.assertTrue(janela.registrar())
        self.assertEqual(janela.grade_saldos.item(0, 2).text(), "2,1234")
        self.assertEqual(janela.grade_historico.rowCount(), 1)
        janela.tipo.setCurrentIndex(janela.tipo.findData("devolucao"))
        janela.quantidade.setText("0,1234")
        janela.motivo.setText("Retorno parcial")
        self.assertTrue(janela.registrar())
        self.assertEqual(janela.grade_historico.rowCount(), 2)
        self.assertEqual(janela.grade_saldos.item(0, 2).text(), "2,0000")

    def test_abertura_sem_sessao_ou_operador_inativo_recusada(self):
        operador = self.ctx.operador
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            self.janela()
        self.ctx.operador = operador
        self.banco.atualizar("operadores", operador.id, {"ativo": 0})
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_revogacao_modulo_revalidada_em_gravacao_atualizacao_e_reabertura(self):
        self.banco.atualizar("operadores", self.ctx.operador_id, {"nivel": 2})
        self.banco.executar("UPDATE acessos SET nivel = 2 WHERE modulo = 'lanc_estoque'")
        janela = self.janela()
        self.assertTrue(janela.registrar())
        self.banco.executar("UPDATE acessos SET nivel = 3 WHERE modulo = 'lanc_estoque'")
        with self.assertRaises(ErroPermissao):
            janela.exigir_acesso()
        self.assertFalse(janela.registrar())
        self.assertFalse(janela.atualizar())
        self.assertEqual(janela.grade_historico.rowCount(), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM retornaveis_movimentos"), 1)

    def test_inativacao_operador_e_saida_sessao_impedem_gravacao(self):
        janela = self.janela()
        self.banco.atualizar("operadores", self.ctx.operador_id, {"ativo": 0})
        self.assertFalse(janela.registrar())
        self.ctx.operador = None
        self.assertFalse(janela.registrar())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM retornaveis_movimentos"), 0)

    def test_cliente_inativo_consulta_historico_mas_nao_grava(self):
        janela = self.janela()
        self.assertTrue(janela.registrar())
        self.banco.atualizar("clientes", self.cliente_id, {"ativo": 0})
        self.assertTrue(janela.atualizar())
        self.assertIn("(inativo)", janela.cliente.currentText())
        janela.quantidade.setText("1")
        janela.motivo.setText("Teste")
        self.assertFalse(janela.registrar())
        self.assertEqual(janela.grade_historico.rowCount(), 1)

    def test_devolucao_excessiva_e_quantidade_invalida_preservam_formulario(self):
        janela = self.janela()
        janela.tipo.setCurrentIndex(janela.tipo.findData("devolucao"))
        self.assertFalse(janela.registrar())
        self.assertEqual(janela.quantidade.text(), "2,1234")
        janela.tipo.setCurrentIndex(janela.tipo.findData("emprestimo"))
        janela.quantidade.setText("nan")
        self.assertFalse(janela.registrar())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM retornaveis_movimentos"), 0)
