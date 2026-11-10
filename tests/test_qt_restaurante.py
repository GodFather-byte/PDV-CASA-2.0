"""Telas reais dos adicionais e da configuração da cozinha, sem banco de loja."""
import os
from uuid import uuid4
from unittest.mock import patch
from PySide6.QtWidgets import QDialog
from src.core import edicao
from src.controllers.opcoes_produto_controller import OpcoesProdutoController
from src.ui_qt.opcoes_produto import DialogoCadastroOpcoes, DialogoEscolherOpcoes
from src.ui_qt.cozinha_web import DialogoCozinhaWeb
from tests.test_qt_app import BaseQt


class TesteTelasRestaurante(BaseQt):
    def setUp(self):
        super().setUp()
        ambiente = patch.dict(os.environ, {"PDV_EDICAO": "willrestaurante"})
        ambiente.start()
        self.addCleanup(ambiente.stop)
        edicao.preparar(self.banco)
        self.admin()
        sub = self.banco.valor("SELECT id FROM subgrupos LIMIT 1")
        un = self.banco.valor("SELECT id FROM unidades LIMIT 1")
        self.produto = self.ctx.cadastros.salvar("produtos", {
            "codigo": "998", "nome": "HAMBURGUER", "preco_cent": "25,00", "subgrupo_id": sub, "unidade_id": un})
        self.opcao = str(uuid4())
        OpcoesProdutoController(self.banco).salvar(self.produto, [
            {"id": str(uuid4()), "nome": "Ponto", "minimo": 1, "maximo": 1,
             "opcoes": [{"id": self.opcao, "nome": "Ao ponto", "preco_cent": 0}]}])

    def test_escolha_obrigatoria_valida_e_devolve_id(self):
        dialogo = self.janela(DialogoEscolherOpcoes(self.banco, self.produto))
        dialogo.confirmar()
        self.assertNotEqual(dialogo.result(), QDialog.DialogCode.Accepted)
        self.assertIn("Ponto", dialogo.erro.text())
        dialogo.caixas[0][1].setChecked(True)
        dialogo.confirmar()
        self.assertEqual(dialogo.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialogo.opcoes_ids, [self.opcao])

    def test_editar_preco_na_tela_preserva_identificador(self):
        dialogo = self.janela(DialogoCadastroOpcoes(self.ctx, self.produto))
        tabela = dialogo.grupos[0][-1]
        tabela.item(0, 1).setText("3,50")
        dialogo.salvar()
        self.assertEqual(dialogo.result(), QDialog.DialogCode.Accepted)
        opcao = OpcoesProdutoController(self.banco).grupos(self.produto)[0]["opcoes"][0]
        self.assertEqual((opcao["id"], opcao["preco_cent"]), (self.opcao, 350))

    def test_configurar_cozinha_na_tela_grava_hash_e_endereco(self):
        dialogo = self.janela(DialogoCozinhaWeb(self.ctx))
        dialogo.ativo.setChecked(True)
        dialogo.pin.setText("123456")
        dialogo.salvar()
        self.assertTrue(self.banco.cfg_bool("cozinha_web_ativo"))
        self.assertTrue(self.banco.cfg("cozinha_web_pin_hash"))
        self.assertNotEqual(self.banco.cfg("cozinha_web_pin_hash"), "123456")
        self.assertIn("/cozinha/", dialogo.endereco.text())
        self.assertEqual(dialogo.pin.text(), "")
