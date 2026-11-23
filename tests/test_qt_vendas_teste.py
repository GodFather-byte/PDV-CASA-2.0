"""Telas Qt da senha de segurança do dono e de apagar vendas de teste."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication

from src.controllers.contexto import Contexto
from src.ui_qt.vendas_teste import JanelaApagarVendasTeste, JanelaSenhaSeguranca
from tests.test_caixa import BaseCaixa


class TesteQtVendasTeste(BaseCaixa):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.adm)
        self.janelas = []
        self.addCleanup(self._fechar)

    def _fechar(self):
        for j in self.janelas:
            j.close()
            j.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _janela(self, cls, **kw):
        j = cls(self.ctx, **kw)
        self.janelas.append(j)
        return j

    def _criar_senha(self):
        j = self._janela(JanelaSenhaSeguranca)
        j.nova.setText("segredo123")
        j.confirma.setText("segredo123")
        self.assertTrue(j.salvar())

    def test_sem_senha_botao_desligado(self):
        j = self._janela(JanelaApagarVendasTeste)
        self.assertFalse(j.botao_apagar.isEnabled())
        self.assertIn("senha de segurança", j.mensagem.text())

    def test_senha_que_nao_confere_mostra_erro(self):
        j = self._janela(JanelaSenhaSeguranca)
        j.nova.setText("segredo123")
        j.confirma.setText("outra")
        self.assertFalse(j.salvar())
        self.assertIn("confirmação", j.mensagem.text())

    def test_marca_confere_total_e_apaga(self):
        self._criar_senha()
        vid = self.vender((self.skol, 2))
        self.pagar(vid, "Dinheiro", 1600)
        self.caixa.fechar(vid)
        perguntas = []
        j = self._janela(JanelaApagarVendasTeste, perguntar=lambda m: perguntas.append(m) or True)
        self.assertEqual(len(j.vendas), 1)
        j.marcar_todas()
        self.assertIn("16,00", j.total.text())
        j.senha.setText("segredo123")
        self.assertEqual(j.apagar(), {"apagadas": 1, "total_cent": 1600})
        self.assertIn("16,00", perguntas[0])
        self.assertEqual(j.vendas, [])
        self.assertEqual(j.senha.text(), "")

    def test_senha_errada_nao_apaga(self):
        self._criar_senha()
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Dinheiro", 800)
        self.caixa.fechar(vid)
        j = self._janela(JanelaApagarVendasTeste, perguntar=lambda m: True)
        j.marcar_todas()
        j.senha.setText("errada")
        self.assertIsNone(j.apagar())
        self.assertIn("incorreta", j.mensagem.text())
        self.assertEqual(len(j.vendas), 1)
        self.assertEqual(j.tabela.item(0, 0).checkState(), Qt.CheckState.Checked)
