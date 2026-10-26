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

    def test_garota_sem_cadastro_tambem_fecha(self):
        self.banco.executar("DELETE FROM garotas")                             # casa que identifica as garotas só pelo número
        vid = self.chamar("45")
        self.j.dialogos.escolhas = []
        self.j.dialogos.confirmacoes = [True]
        self.j.fechar_venda()
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))
        self.assertNotIn("Lance ao menos", " ".join(self.j.dialogos.avisos))

    def test_numero_nao_cadastrado_fecha_com_a_dica_do_1002(self):
        vid = self.chamar("13")                                                # 13 não está no cadastro (só a 12)
        self.j.dialogos.confirmacoes = [True]
        self.j.fechar_venda()
        self.assertIn("1002", self.j.dialogos.perguntas[-1])                   # cliente sem consumo usa o 1002
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))

    def test_botao_fechar_venda_fica_habilitado_na_comanda_vazia_e_fecha(self):
        self.banco.cfg_set("comissao_pede_shows", "N")
        self.assertFalse(self.j.btn_fechar_venda.isEnabled())                  # balcão vazio: nada a fechar
        vid = self.chamar()
        self.assertTrue(self.j.btn_fechar_venda.isEnabled())                   # comanda vazia: pode fechar
        self.j.dialogos.confirmacoes = [True]
        self.j.btn_fechar_venda.click()
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))
        self.assertFalse(self.j.btn_fechar_venda.isEnabled())
        self.chamar("M5")
        self.assertFalse(self.j.btn_fechar_venda.isEnabled())                  # mesa vazia continua sem fechar

    def test_receber_numa_comanda_vazia_tambem_fecha(self):
        self.banco.cfg_set("comissao_pede_shows", "N")
        vid = self.chamar()
        self.j.dialogos.confirmacoes = [True]
        self.j.receber()                                                       # o Enter no valor chama receber()
        self.assertNotIn("Lance ao menos", " ".join(self.j.dialogos.avisos))
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))

    def test_mesa_vazia_continua_pedindo_um_item(self):
        self.chamar("M5")
        self.j.fechar_venda()
        self.assertIn("ao menos um item", self.j.dialogos.avisos[-1])
        self.assertIsNotNone(self.j.venda_id)

    def test_sem_o_modulo_das_garotas_comanda_vazia_continua_pedindo_item(self):
        self.banco.cfg_set("usar_garotas", "N")
        self.chamar("13")
        self.j.fechar_venda()
        self.assertIn("ao menos um item", self.j.dialogos.avisos[-1])

    def _acerto_de_verdade(self, cliques: int):
        """Troca a janela modal do acerto pela própria DialogoAcerto, sem exec(): só aperta Pagar `cliques` vezes."""
        from src.ui_qt.comissao import DialogoAcerto
        dialogos = []

        def abrir(numero, nome, comissao_cent, quantidade, do_caixa_padrao=False):
            dlg = DialogoAcerto(self.j, self.j.ctx, numero, nome, comissao_cent, quantidade, do_caixa_padrao)
            dialogos.append(dlg)
            for _ in range(cliques):
                dlg.confirmar()
            resultado = dlg.resultado
            dlg.deleteLater()
            return resultado
        return patch.object(self.j, "_dialogo_acerto", side_effect=abrir), dialogos

    def test_acerto_sem_shows_fecha_a_conta_zerada_e_a_comanda(self):
        """O que travava no balcão: com shows ligados, Pagar sem shows recusava ("informe os shows") e a comanda não fechava."""
        vid = self.chamar()
        troca, dialogos = self._acerto_de_verdade(2)
        with troca, patch.object(self.j, "_emitir") as emitir:
            self.j.fechar_venda()
        self.assertIn("R$ 0,00", dialogos[0].lbl_msg.text())                   # o primeiro Pagar avisa; o segundo fecha
        acerto = self.banco.um("SELECT garota, total_cent, shows_qtd FROM acertos_garotas")
        self.assertEqual(tuple(acerto), (12, 0, 0))
        self.assertEqual(emitir.call_args[0][0], "Recibo de acerto")
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))
        self.assertIsNone(self.j.venda_id)
        self.assertEqual([t["chave"] for t in self.j.cartoes.tiles()], ["0"])
        self.assertIn("fechada sem valor", self.j.lbl_status.text())
        self.assertEqual(self.j.dialogos.avisos, [])

    def test_um_pagar_so_avisa_e_nao_grava_nada(self):
        vid = self.chamar()
        troca, _ = self._acerto_de_verdade(1)
        self.j.dialogos.confirmacoes = [False]                                 # desistiu: nem acerto, nem fechar
        with troca:
            self.j.fechar_venda()
        self.assertIsNone(self.banco.um("SELECT id FROM acertos_garotas"))
        self.assertEqual(self.j.venda_id, vid)

    def test_acerto_com_shows_tambem_fecha_a_comanda(self):
        vid = self.chamar()
        acerto = {"do_caixa": False, "shows": 2, "valor_show_cent": 5000, "pix_cent": 0, "vale_cent": 0, "zerado": False}
        with patch.object(self.j, "_dialogo_acerto", return_value=acerto), patch.object(self.j, "_emitir"):
            self.j.fechar_venda()
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))
        self.assertIsNone(self.j.venda_id)

    def test_comanda_so_com_comissao_paga_e_fecha(self):
        self.banco.cfg_set("comissao_na_linha", "S")
        vid = self.chamar()
        self.j.ctx.comissoes.lancar(12, 3000, self.j._turno()["id"], self.j.ctx.operador_id)
        self.j.recarregar()
        acerto = {"do_caixa": False, "shows": 0, "valor_show_cent": 0, "pix_cent": 0, "vale_cent": 0, "zerado": False}
        with patch.object(self.j, "_dialogo_acerto", return_value=acerto), patch.object(self.j, "_emitir"):
            self.j.fechar_venda()
        self.assertEqual(self.banco.valor("SELECT total_cent FROM acertos_garotas"), 3000)
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))
        self.assertIsNone(self.j.venda_id)

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
