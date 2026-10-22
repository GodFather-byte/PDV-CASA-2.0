"""Painéis de alertas Tk e Qt com banco real em memória: permissão revalidada e seções recortadas."""
from __future__ import annotations

import gc
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest

from src.controllers.acesso_controller import AcessoController
from src.controllers.cadastro_controller import CadastroController
from src.core.erros import ErroPermissao
from src.controllers.contexto import Contexto
from tests.base import BaseTeste


class BaseJanela(BaseTeste):
    def setUp(self):
        super().setUp()
        self.adm = self.operador_adm()
        self.baixo = CadastroController(self.banco).salvar("operadores", {"nome": "BAR", "senha": "1234", "nivel": "1"})
        self.novo_produto("GIN", 9000, estoque=True, qt=0)
        self.banco.cfg_set("integracao_nfce_estado", "preparacao")

    def ctx(self, operador_id):
        return Contexto(self.banco, AcessoController(self.banco).operador(operador_id))


class TesteAlertasQt(BaseJanela):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as erro:
            raise unittest.SkipTest(f"PySide6 ausente: {erro}")
        cls.app = QApplication.instance() or QApplication([])

    def janela(self, operador_id):
        from src.ui_qt.alertas import JanelaAlertas
        j = JanelaAlertas(self.ctx(operador_id))
        self.addCleanup(j.deleteLater)
        return j

    def titulos(self, j):
        return [j.grade.item(i, 2).text() for i in range(j.grade.rowCount())]

    def test_mostra_alertas_do_adm(self):
        j = self.janela(self.adm)
        self.assertIn("Sem estoque: GIN", self.titulos(j))
        self.assertIn("NFC-e em preparação (sem operação)", self.titulos(j))
        self.assertIn("1 crítico", j.resumo.text())

    def test_sem_permissao_nao_cria(self):
        with self.assertRaises(ErroPermissao):
            self.janela(self.baixo)

    def test_exigir_acesso_recorta_e_bloqueia(self):
        AcessoController(self.banco).alterar_nivel_modulo("rel_estoque", 1)
        j = self.janela(self.baixo)
        self.assertEqual(self.titulos(j), ["Sem estoque: GIN"])
        self.assertIn("Sem permissão para: operação", j.secoes_texto.text())
        AcessoController(self.banco).alterar_nivel_modulo("rel_informativos", 1)
        self.assertEqual(j.exigir_acesso(), {"estoque", "operacao"})
        self.assertEqual(j.grade.rowCount(), 2)
        AcessoController(self.banco).alterar_nivel_modulo("rel_estoque", 2)
        AcessoController(self.banco).alterar_nivel_modulo("rel_informativos", 2)
        with self.assertRaises(ErroPermissao):
            j.exigir_acesso()
        self.assertEqual(j.grade.rowCount(), 0)
        j.atualizar()
        self.assertEqual(j.grade.rowCount(), 0)

    def test_casa_sem_alertas(self):
        self.banco.executar("UPDATE produtos SET controla_estoque = 0")
        self.banco.cfg_set("integracao_nfce_estado", "desativado")
        j = self.janela(self.adm)
        self.assertEqual(j.grade.rowCount(), 0)
        self.assertEqual(j.resumo.text(), "Nenhum alerta agora.")

