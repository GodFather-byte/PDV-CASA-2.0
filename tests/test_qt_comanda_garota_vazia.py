"""Comanda da garota sem nada lançado: pode ser fechada (ou ter os shows acertados) em vez de travar no aviso."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.test_qt_caixa import BaseCaixaQt

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
except ImportError:                                   # pragma: no cover - sem PySide6 estes testes não rodam
    Qt = None

from src.controllers.cadastro_controller import CadastroController


class TesteComandaDaGarotaVazia(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.abrir_turno()
        CadastroController(self.banco).salvar("garotas", {"numero": 12, "nome": "BIA", "ativo": "S"})
        self.j = self.janela()
        self.j.activateWindow()
        self.aplicacao.processEvents()

    def chamar(self, texto="12"):
        self.j.ent_pos.setText(texto)
        self.j.btn_chamar.click()
        return self.j.venda_id

    def test_sem_shows_pede_confirmacao_e_fecha_a_comanda_vazia(self):
        self.banco.cfg_set("comissao_pede_shows", "N")
        vid = self.chamar()
        self.assertIsNotNone(vid)
        self.j.dialogos.confirmacoes = [True]
        self.j.fechar_venda()
        self.assertIn("BIA", self.j.dialogos.perguntas[-1])
        self.assertIsNone(self.j.venda_id)
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))
        self.assertEqual([t["chave"] for t in self.j.cartoes.tiles()], ["0"])
        self.assertIn("fechada, sem lançamentos", self.j.lbl_status.text())

    def test_dizer_nao_mantem_a_comanda_aberta(self):
        self.banco.cfg_set("comissao_pede_shows", "N")
        vid = self.chamar()
        self.j.dialogos.confirmacoes = [False]
        self.j.fechar_venda()
        self.assertEqual(self.j.venda_id, vid)
        self.assertIsNotNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))

    def test_com_shows_abre_o_acerto_e_desistindo_dele_pergunta_se_e_so_fechar(self):
        vid = self.chamar()
        self.j.dialogos.confirmacoes = [True]
        with patch.object(self.j, "_dialogo_acerto", return_value=None):         # Esc no acerto dos shows
            self.j.fechar_venda()
        self.assertIn("sem nada lançado", self.j.dialogos.perguntas[-1])
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))

    def test_com_shows_pagando_o_acerto_nao_pergunta_nada(self):
        self.chamar()
        acerto = {"do_caixa": False, "shows": 1, "valor_show_cent": 5000, "pix_cent": 0, "vale_cent": 0}
        with patch.object(self.j, "_dialogo_acerto", return_value=acerto), patch.object(self.j, "_emitir"):
            self.j.fechar_venda()
        self.assertEqual(self.banco.valor("SELECT shows_cent FROM acertos_garotas"), 5000)
        self.assertEqual(self.j.dialogos.perguntas, [])

    def test_desistir_do_acerto_e_do_fechamento_mantem_a_comanda(self):
        vid = self.chamar()
        self.j.dialogos.confirmacoes = [False]
        with patch.object(self.j, "_dialogo_acerto", return_value=None):
            self.j.fechar_venda()
        self.assertEqual(self.j.venda_id, vid)

    def test_garota_inativa_tambem_fecha_sem_lancamento(self):
        self.banco.executar("UPDATE garotas SET ativo = 0 WHERE numero = 12")
        vid = self.chamar()
        self.j.dialogos.confirmacoes = [True]
        self.j.fechar_venda()
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))

    def test_comanda_de_cliente_vazia_continua_pedindo_um_item(self):
        self.chamar("13")                                   # 13 não é garota cadastrada
        self.j.fechar_venda()
        self.assertIn("ao menos um item", self.j.dialogos.avisos[-1])
        self.assertIsNotNone(self.j.venda_id)

    def test_enter_com_o_codigo_vazio_fecha_a_comanda_da_garota(self):
        self.banco.cfg_set("comissao_pede_shows", "N")
        vid = self.chamar()
        self.j.ent_codigo.setFocus()
        self.j.dialogos.confirmacoes = [True]
        QTest.keyClick(self.j.ent_codigo, Qt.Key_Return)
        self.aplicacao.processEvents()
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))


if __name__ == "__main__":
    unittest.main()
