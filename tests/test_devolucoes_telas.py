"""Telas Tk e Qt de devolução: busca por cupom, registro autorizado, falha de impressão sem duplicar."""
import os
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.controllers.caixa_controller import CaixaController
from src.controllers.turno_controller import TurnoController
from src.core.erros import ErroPermissao
from src.controllers.contexto import Contexto
from tests.base import BaseTeste


class BaseTela(BaseTeste):
    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        adm = self.operador_adm()
        self.ctx.operador = self.ctx.acesso.operador(adm)
        TurnoController(self.banco).abrir(adm, 1, 10000)
        caixa = CaixaController(self.banco, adm)
        pid = self.novo_produto("SKOL", 800)
        self.vid = caixa.abrir_balcao()
        caixa.adicionar_item(self.vid, pid, 2)
        caixa.adicionar_pagamento(self.vid, self.tipo(), 1600)
        caixa.fechar(self.vid)
        self.cupom = caixa.obter(self.vid)["cupom"]

    def contar(self):
        return self.banco.valor("SELECT COUNT(*) FROM devolucoes")


class TesteDevolucoesQt(BaseTela):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as erro:
            raise __import__("unittest").SkipTest(str(erro))
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def test_registra_e_repete_uuid_sem_duplicar(self):
        from src.ui_qt.devolucoes import JanelaDevolucoes
        janela = JanelaDevolucoes(self.ctx)
        self.addCleanup(janela.deleteLater)
        janela.cupom.setText(str(self.cupom))
        self.assertTrue(janela.buscar())
        janela.grade.selectRow(0)
        janela.quantidade.setText("1")
        self.assertTrue(janela.aplicar())
        janela.motivo.setText("Cliente desistiu")
        uuid = janela.uuid
        with mock.patch.object(JanelaDevolucoes, "_confirmar", return_value=True), \
                mock.patch.object(type(self.ctx.impressao), "enviar", return_value="ok") as enviar:
            dev = janela.registrar()
        self.assertEqual((dev["valor_cent"], dev["uuid"], self.contar()), (800, uuid, 1))
        enviar.assert_called_once()
        self.assertNotEqual(janela.uuid, uuid)
        self.assertEqual(janela.situacao["itens"][0]["saldo"], 1.0)