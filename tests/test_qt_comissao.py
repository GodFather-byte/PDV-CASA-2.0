"""Contrato da migração Qt de comissão e saída, com banco real em memória."""
from unittest.mock import patch

from tests.test_qt_caixa import BaseCaixaQt


class TestComissaoQt(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.turno = self.abrir_turno()
        self.banco.cfg_set("comissao_na_linha", "N")
        self.banco.cfg_set("imprimir_via_comissao", "N")
        self.banco.cfg_set("comissao_pede_shows", "N")
        self.banco.cfg_set("num_comandas", "300")
        self.banco.cfg_set("posicao_padrao", "comanda")

    def marcar(self, numero=180, cent=1500):
        return self.ctx.comissoes.lancar(numero, cent, self.turno, self.ctx.operador_id)

    def acerto(self, **valores):
        return dict(do_caixa=False, shows=0, valor_show_cent=0, pix_cent=0, vale_cent=0, zerado=False) | valores

    def comanda(self, j):
        j.ent_pos.setText("180")
        j.btn_chamar.click()
        self.assertIsNotNone(j.venda_id)
        self.assertEqual(self.ctx.caixa.obter(j.venda_id)["comanda"], 1)

    def garota(self, numero=180, ativo=1):
        self.banco.inserir("garotas", {"numero": numero, "nome": "ANA", "ativo": ativo})

    def f12(self, j):
        from PySide6.QtGui import QShortcut
        atalhos = [a for a in j.findChildren(QShortcut) if a.key().toString() == "F12"]
        self.assertEqual(len(atalhos), 1)
        atalhos[0].activated.emit()

    def test_lancamento_em_janela_preserva_valor_e_operador(self):
        j = self.janela()
        with patch.object(j, "_dialogo_comissao", return_value=(180, 1500)):
            j.lancar_comissao()
        evento = self.ctx.comissoes.lancamentos(180)[0]
        self.assertEqual(evento["valor_cent"], 1500)
        self.assertEqual(evento["operador_id"], self.ctx.operador_id)
        self.assertEqual(self.ctx.comissoes.pendente(180), 1500)
        self.assertEqual(self.contar("itens_venda"), 0)

    def test_cancelar_dialogo_nao_lanca(self):
        j = self.janela()
        with patch.object(j, "_dialogo_comissao", return_value=None):
            j.lancar_comissao()
        self.assertEqual(self.contar("comissoes_garotas"), 0)

    def test_lancar_sem_autorizacao_nao_abre_dialogo(self):
        self.banco.cfg_set("exigir_senha_comissao", "S")
        self.operador_bar()
        j = self.janela()
        j.dialogos.textos = [None]
        with patch.object(j, "_dialogo_comissao") as dialogo:
            j.lancar_comissao()
        dialogo.assert_not_called()
        self.assertEqual(self.contar("comissoes_garotas"), 0)

    def test_supervisor_autoriza_sem_trocar_operador_da_comissao(self):
        self.banco.cfg_set("exigir_senha_comissao", "S")
        operador = self.operador_bar()
        j = self.janela()
        j.dialogos.textos = ["ADM"]
        with patch.object(j, "_dialogo_comissao", return_value=(180, 1500)):
            j.lancar_comissao()
        self.assertEqual(self.ctx.comissoes.lancamentos(180)[0]["operador_id"], operador)
        self.assertEqual(self.ctx.operador_id, operador)
        self.assertEqual(j.dialogos.textos, [])

    def test_sem_turno_nao_lanca(self):
        self.ctx.turnos.fechar(self.turno, self.ctx.operador_id, 10000)
        j = self.janela()
        with patch.object(j, "_dialogo_comissao", return_value=(180, 1500)):
            j.lancar_comissao()
        self.assertEqual(self.contar("comissoes_garotas"), 0)

    def test_comissao_independe_do_consumo_da_comanda(self):
        j = self.janela()
        j.ent_pos.setText("180")
        j.btn_chamar.click()
        venda = j.venda_id
        with patch.object(j, "_dialogo_comissao", return_value=(180, 1500)):
            j.lancar_comissao()
        self.assertEqual(self.ctx.comissoes.pendente(180), 1500)
        self.assertEqual(self.ctx.caixa.recalcular(venda)["total"], 0)

    def test_cancelar_acerto_preserva_pendencias(self):
        self.marcar()
        j = self.janela()
        with patch.object(j, "_dialogo_acerto", return_value=None):
            j.pagar_comissao(180)
        self.assertEqual(self.ctx.comissoes.pendente(180), 1500)
        self.assertEqual(self.contar("acertos_garotas"), 0)

    def test_acerto_fora_do_caixa_nao_cria_saida(self):
        self.marcar()
        j = self.janela()
        with patch.object(j, "_dialogo_acerto", return_value=self.acerto()), patch.object(j, "_emitir"):
            j.pagar_comissao(180)
        self.assertEqual(self.ctx.comissoes.pendente(180), 0)
        pago = self.banco.um("SELECT * FROM acertos_garotas")
        self.assertEqual(pago["total_cent"], 1500)
        self.assertFalse(pago["tirou_do_caixa"])
        self.assertIsNone(pago["movimento_id"])

    def test_acerto_com_shows_vale_pix_so_retira_dinheiro(self):
        self.marcar()
        self.banco.cfg_set("comissao_pede_shows", "S")
        j = self.janela()
        escolha = dict(do_caixa=True, shows=2, valor_show_cent=5000, vale_cent=2000, pix_cent=3000)
        with patch.object(j, "_dialogo_acerto", return_value=escolha), patch.object(j, "_emitir") as emitir:
            j.pagar_comissao(180)
        pago = self.banco.um("SELECT * FROM acertos_garotas")
        self.assertEqual((pago["comissao_cent"], pago["shows_cent"], pago["total_cent"]), (1500, 10000, 11500))
        self.assertEqual((pago["vale_cent"], pago["pix_cent"]), (2000, 3000))
        movimento = self.banco.um("SELECT * FROM movimentos_caixa WHERE id = ?", (pago["movimento_id"],))
        self.assertEqual(movimento["valor_cent"], 6500)
        self.assertEqual(emitir.call_count, 2)
        self.assertTrue(emitir.call_args_list[0].kwargs["abrir_gaveta"])
        self.assertFalse(emitir.call_args_list[1].kwargs.get("abrir_gaveta", False))

    def test_vale_maior_que_total_nao_paga(self):
        self.marcar()
        j = self.janela()
        escolha = dict(do_caixa=True, shows=0, valor_show_cent=0, vale_cent=1501, pix_cent=0)
        with patch.object(j, "_dialogo_acerto", return_value=escolha), patch.object(j, "_emitir"):
            j.pagar_comissao(180)
        self.assertEqual(self.ctx.comissoes.pendente(180), 1500)
        self.assertEqual(self.contar("acertos_garotas"), 0)
        self.assertTrue(j.dialogos.erros or j.dialogos.avisos)

    def test_pix_maior_que_saldo_apos_vale_nao_paga(self):
        self.marcar()
        j = self.janela()
        escolha = dict(do_caixa=True, shows=0, valor_show_cent=0, vale_cent=500, pix_cent=1001)
        with patch.object(j, "_dialogo_acerto", return_value=escolha), patch.object(j, "_emitir"):
            j.pagar_comissao(180)
        self.assertEqual(self.ctx.comissoes.pendente(180), 1500)
        self.assertEqual(self.contar("acertos_garotas"), 0)

    def test_pagamento_sem_autorizacao_preserva_comissao(self):
        self.marcar()
        self.operador_bar()
        j = self.janela()
        j.dialogos.textos = [None]
        with patch.object(j, "_dialogo_acerto") as dialogo:
            j.pagar_comissao(180)
        dialogo.assert_not_called()
        self.assertEqual(self.ctx.comissoes.pendente(180), 1500)

    def test_so_shows_podem_ser_acertados_sem_comissao(self):
        self.banco.cfg_set("comissao_pede_shows", "S")
        j = self.janela()
        escolha = dict(do_caixa=False, shows=1, valor_show_cent=5000, vale_cent=0, pix_cent=5000)
        with patch.object(j, "_dialogo_acerto", return_value=escolha), patch.object(j, "_emitir"):
            j.pagar_comissao(180)
        pago = self.banco.um("SELECT * FROM acertos_garotas")
        self.assertEqual((pago["comissao_cent"], pago["shows_cent"], pago["pix_cent"]), (0, 5000, 5000))

    def test_sem_shows_e_sem_comissao_nao_paga(self):
        j = self.janela()
        with patch.object(j, "_dialogo_acerto", return_value=self.acerto()), patch.object(j, "_emitir"):
            j.pagar_comissao(180)
        self.assertEqual(self.contar("acertos_garotas"), 0)

    def test_modo_na_linha_converte_pontos_e_restaura_campos(self):
        self.banco.cfg_set("comissao_na_linha", "S")
        j = self.janela()
        self.comanda(j)
        self.lancar(j, self.ctx.comissoes.codigo())
        self.assertTrue(j.modo_comissao)
        self.assertEqual(j.ent_codigo.text(), "180")
        self.assertEqual(j.lbl_cod_titulo.text(), "Garota nº:")
        j.ent_qtd.setText("2")
        esperado = self.ctx.comissoes.para_centavos("2")
        j.btn_lancar.click()
        self.assertEqual(self.ctx.comissoes.pendente(180), esperado)
        self.assertFalse(j.modo_comissao)
        self.assertEqual(j.lbl_cod_titulo.text(), "Código ou nome do produto:")
        self.assertEqual(j.lbl_qtd_titulo.text(), "Quantidade:")
        self.assertEqual(j.btn_lancar.text(), "Lançar")
        self.assertTrue(j.lbl_comissao_nome.isHidden())
        self.assertEqual(self.contar("itens_venda"), 0)

    def test_comanda_sem_cadastro_lanca_direto_sem_perguntar(self):
        """Com outras garotas cadastradas, a comanda 180 (sem cadastro) lança a comissão sem o "Lançar assim mesmo?"."""
        self.banco.cfg_set("comissao_na_linha", "S")
        self.garota(numero=12)                                                 # o cadastro não está vazio
        j = self.janela()
        self.comanda(j)
        self.lancar(j, self.ctx.comissoes.codigo())
        self.assertEqual(j.lbl_comissao_nome.text(), "COMISSÃO - garota 180")
        j.ent_qtd.setText("2")
        j.btn_lancar.click()                                                   # DialogosFalsos falha se perguntar algo
        self.assertEqual(j.dialogos.perguntas, [])
        self.assertEqual(self.ctx.comissoes.pendente(180), self.ctx.comissoes.para_centavos("2"))

    def test_janela_da_comissao_sem_cadastro_tambem_nao_pergunta(self):
        from src.ui_qt.comissao import conferir_lancamento, descrever_garota
        self.garota(numero=12)
        j = self.janela()
        self.assertIsNone(conferir_lancamento(j.dialogos, self.ctx, 99, 1000))
        self.assertEqual(j.dialogos.perguntas, [])
        self.assertEqual(descrever_garota(self.ctx, "99"), ("", False))       # sem o aviso vermelho "não cadastrada"

    def test_modo_na_linha_em_reais(self):
        self.banco.cfg_set("comissao_na_linha", "S")
        self.banco.cfg_set("comissao_em_pontos", "N")
        j = self.janela()
        self.lancar(j, self.ctx.comissoes.codigo())
        self.lancar(j, "180", "12,34")
        self.assertEqual(self.ctx.comissoes.pendente(180), 1234)

    def test_esc_e_troca_de_posicao_descartam_digitacao(self):
        self.banco.cfg_set("comissao_na_linha", "S")
        j = self.janela()
        for trocar in (False, True):
            self.lancar(j, self.ctx.comissoes.codigo())
            j.ent_codigo.setText("180")
            j.ent_qtd.setText("2")
            if trocar:
                j.ent_pos.setText("181")
                j.btn_chamar.click()
            else:
                j.cancelar_modo_comissao()
            self.assertFalse(j.modo_comissao)
        self.assertEqual(self.contar("comissoes_garotas"), 0)

    def test_comanda_sugere_numero_na_janela(self):
        j = self.janela()
        self.comanda(j)
        with patch.object(j, "_dialogo_comissao", return_value=None) as dialogo:
            j.lancar_comissao()
        dialogo.assert_called_once_with("180")

    def test_inativa_e_valor_alto_exigem_confirmacao_e_sem_cadastro_nao(self):
        from src.controllers.comissao_controller import LIMITE_CONFIRMAR_CENT
        self.garota(181, ativo=0)
        j = self.janela()
        with patch.object(j, "_dialogo_comissao", side_effect=[(180, 1500), None]):
            j.lancar_comissao()                                                # 180 sem cadastro: lança direto
        self.assertEqual(j.dialogos.perguntas, [])
        self.assertEqual(self.ctx.comissoes.pendente(180), 1500)
        self.banco.executar("DELETE FROM comissoes_garotas")
        for numero, valor in ((181, 1500), (181, LIMITE_CONFIRMAR_CENT + 1)):
            j.dialogos.confirmacoes = [False]
            with patch.object(j, "_dialogo_comissao", side_effect=[(numero, valor), None]):
                j.lancar_comissao()
            self.assertEqual(self.contar("comissoes_garotas"), 0)
        j.dialogos.confirmacoes = [True, False]
        with patch.object(j, "_dialogo_comissao", side_effect=[(181, LIMITE_CONFIRMAR_CENT + 1), None]):
            j.lancar_comissao()
        self.assertEqual(self.contar("comissoes_garotas"), 0)
        self.assertEqual(j.dialogos.confirmacoes, [])

    def test_falha_da_via_preserva_lancamento_e_registra_log(self):
        self.banco.cfg_set("imprimir_via_comissao", "S")
        j = self.janela()
        with patch.object(j, "_dialogo_comissao", return_value=(180, 1500)), patch.object(
                type(self.ctx.impressao), "imprimir_via_comissao", side_effect=OSError("impressora desligada")):
            j.lancar_comissao()
        self.assertEqual(self.ctx.comissoes.pendente(180), 1500)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento='via_comissao_falhou'"), 1)

    def test_falha_do_recibo_nao_desfaz_acerto(self):
        self.marcar()
        j = self.janela()
        with patch.object(j, "_dialogo_acerto", return_value=self.acerto()), patch.object(
                j, "_emitir", side_effect=OSError("impressora desligada")), patch.object(j, "_registrar_falha") as log:
            j.pagar_comissao(180)
        self.assertEqual(self.ctx.comissoes.pendente(180), 0)
        self.assertEqual(self.contar("acertos_garotas"), 1)
        self.assertTrue(j.dialogos.erros)
        log.assert_called_once()

    def test_padrao_do_caixa_e_encaminhado_ao_dialogo(self):
        self.marcar()
        self.banco.cfg_set("comissao_paga_do_caixa", "S")
        j = self.janela()
        with patch.object(j, "_dialogo_acerto", return_value=None) as dialogo:
            j.pagar_comissao(180)
        self.assertEqual(dialogo.call_args.args, (180, "", 1500, 1, True))

    def test_f12_comissao_sem_consumo_abre_acerto(self):
        self.banco.cfg_set("comissao_na_linha", "S")
        self.marcar()
        j = self.janela()
        self.comanda(j)
        with patch.object(j, "_dialogo_acerto", return_value=self.acerto()), patch.object(j, "_emitir"):
            self.f12(j)
        self.assertEqual(self.ctx.comissoes.pendente(180), 0)
        self.assertEqual(self.contar("pagamentos_venda"), 0)

    def test_f12_consumo_e_comissao_permite_escolher_acerto(self):
        self.banco.cfg_set("comissao_na_linha", "S")
        self.marcar()
        self.novo_produto(codigo="10")
        j = self.janela()
        self.comanda(j)
        self.lancar(j, "10")
        venda = j.venda_id
        j.dialogos.escolhas = ["comissao"]
        with patch.object(j, "_dialogo_acerto", return_value=self.acerto()), patch.object(j, "_emitir"):
            self.f12(j)
        self.assertEqual(self.ctx.comissoes.pendente(180), 0)
        self.assertEqual(self.ctx.caixa.obter(venda)["status"], "aberta")
        self.assertEqual(len(self.ctx.caixa.itens(venda)), 1)
        self.assertEqual(self.contar("pagamentos_venda"), 0)

    def test_f12_garota_ativa_sem_comissao_permite_so_shows(self):
        self.banco.cfg_set("comissao_na_linha", "S")
        self.banco.cfg_set("comissao_pede_shows", "S")
        self.garota()
        j = self.janela()
        self.comanda(j)
        with patch.object(j, "_dialogo_acerto", return_value=self.acerto(shows=1, valor_show_cent=5000)), patch.object(
                j, "_emitir"):
            self.f12(j)
        self.assertEqual(self.banco.valor("SELECT shows_cent FROM acertos_garotas"), 5000)

    def test_cancelamento_pela_lista_e_painel(self):
        self.banco.cfg_set("comissao_na_linha", "S")
        lid = self.marcar()
        j = self.janela()
        self.comanda(j)
        j.tabela.setCurrentCell(0, 0)
        self.assertEqual(j._comissao_selecionada(), lid)
        j.dialogos.confirmacoes = [True]
        j.btn_cancelar_item.click()
        self.assertEqual(self.banco.valor("SELECT status FROM comissoes_garotas WHERE id=?", (lid,)), "cancelada")
        lid = self.marcar()
        painel = j.abrir_comissoes()
        self.assertIs(painel, j.abrir_comissoes())
        self.assertTrue(painel.selecionar_garota(180))
        self.assertTrue(painel.selecionar_lancamento(lid))
        j.dialogos.confirmacoes = [True]
        painel.btn_cancelar.click()
        self.assertEqual(self.banco.valor("SELECT status FROM comissoes_garotas WHERE id=?", (lid,)), "cancelada")

    def test_cancelamento_de_comissao_paga_e_recusado(self):
        from src.ui_qt.comissao import cancelar_lancamento
        lid = self.marcar()
        self.ctx.comissoes.pagar(180, self.turno, self.ctx.operador_id, False)
        j = self.janela()
        j.dialogos.confirmacoes = [True]
        self.assertFalse(cancelar_lancamento(j, lid, "comissão paga"))
        self.assertEqual(self.banco.valor("SELECT status FROM comissoes_garotas WHERE id=?", (lid,)), "paga")
        self.assertTrue(j.dialogos.avisos or j.dialogos.erros)

    def test_cancelamento_exige_autorizacao_e_confirmacao(self):
        from src.ui_qt.comissao import cancelar_lancamento
        lid = self.marcar()
        self.banco.cfg_set("exigir_senha_cancelamento", "S")
        self.operador_bar()
        j = self.janela()
        j.dialogos.textos = [None]
        self.assertFalse(cancelar_lancamento(j, lid, "comissão pendente"))
        self.assertEqual(self.ctx.comissoes.pendente(180), 1500)
        j.dialogos.textos = ["ADM"]
        j.dialogos.confirmacoes = [False]
        self.assertFalse(cancelar_lancamento(j, lid, "comissão pendente"))
        self.assertEqual(self.ctx.comissoes.pendente(180), 1500)
        self.assertEqual(j.dialogos.textos, [])
        self.assertEqual(j.dialogos.confirmacoes, [])

    def test_dialogo_real_de_comissao_valida_numero_e_valor(self):
        from src.ui_qt.comissao import DialogoComissao
        j = self.janela()
        for pontos, texto, esperado in (("S", "2", self.ctx.comissoes.para_centavos("2")), ("N", "12,34", 1234)):
            self.banco.cfg_set("comissao_em_pontos", pontos)
            dlg = DialogoComissao(j, self.ctx, "180")
            dlg.ent_numero.setText("invalido")
            dlg.gravar()
            self.assertIsNone(dlg.resultado)
            self.assertTrue(dlg.lbl_msg.text())
            dlg.ent_numero.setText("180")
            dlg.ent_valor.setText("0")
            dlg.gravar()
            self.assertIsNone(dlg.resultado)
            dlg.ent_valor.setText(texto)
            dlg.gravar()
            self.assertEqual(dlg.resultado, (180, esperado))

    def test_dialogo_real_de_acerto_valida_vale_pix_e_shows(self):
        from src.ui_qt.comissao import DialogoAcerto
        self.banco.cfg_set("comissao_pede_shows", "S")
        self.banco.cfg_set("show_valores", "50;60")
        j = self.janela()
        dlg = DialogoAcerto(j, self.ctx, 180, "ANA", 1500, 1, True)
        self.assertTrue(dlg.chk_do_caixa.isChecked())
        dlg.ent_qtd.setText("2")
        dlg.confirmar()
        self.assertIsNone(dlg.resultado)
        dlg.grupo_show.button(5000).setChecked(True)
        dlg.ent_vale.setText("115,01")
        dlg.confirmar()
        self.assertIsNone(dlg.resultado)
        dlg.ent_vale.setText("20,00")
        dlg.ent_pix.setText("95,01")
        dlg.confirmar()
        self.assertIsNone(dlg.resultado)
        dlg.tudo_no_pix()
        dlg.confirmar()
        self.assertEqual(dlg.resultado, self.acerto(do_caixa=True, shows=2, valor_show_cent=5000,
                                                  vale_cent=2000, pix_cent=9500, nome="ANA"))

    def test_dialogo_real_traz_o_nome_do_cadastro_e_deixa_digitar_outro(self):
        from src.ui_qt.comissao import DialogoAcerto
        self.banco.cfg_set("comissao_pede_shows", "S")
        dlg = DialogoAcerto(self.janela(), self.ctx, 180, "ANA", 0, 0)
        self.assertEqual(dlg.ent_nome.text(), "ANA")
        dlg.ent_nome.setText("  Bia  Souza ")
        dlg.ent_qtd.setText("2")
        dlg.grupo_show.buttons()[0].setChecked(True)
        dlg.confirmar()
        self.assertEqual(dlg.resultado["nome"], "Bia Souza")
        self.assertEqual(dlg.resultado["shows"], 2)

    def test_dialogo_real_sem_comissao_nem_shows_fecha_zerado_no_segundo_pagar(self):
        from src.ui_qt.comissao import DialogoAcerto
        self.banco.cfg_set("comissao_pede_shows", "S")
        dlg = DialogoAcerto(self.janela(), self.ctx, 180, "ANA", 0, 0)
        dlg.confirmar()
        self.assertIsNone(dlg.resultado)                                       # o primeiro só avisa
        self.assertIn("R$ 0,00", dlg.lbl_msg.text())
        dlg.confirmar()
        self.assertEqual(dlg.resultado, self.acerto(zerado=True, nome="ANA"))


class TestSaidaQt(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.abrir_turno()
        self.banco.cfg_set("num_comandas", "300")
        self.banco.cfg_set("posicao_padrao", "comanda")
        self.novo_produto("SKOL", 800, codigo="10")

    def test_saida_da_comanda_vazia_emite_ticket_e_limpa_tela(self):
        j = self.janela()
        j.ent_pos.setText("180")
        j.btn_chamar.click()
        venda = j.venda_id
        self.assertIsNotNone(venda)
        with patch.object(j, "_emitir") as emitir:
            j.liberar_saida()
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (venda,)))
        self.assertIsNone(j.venda_id)
        self.assertEqual(self.banco.cfg_int("ultimo_ticket_saida", 0), 1)
        self.assertTrue(any(chamada.kwargs.get("tipo") == "saida" for chamada in emitir.call_args_list))

    def test_saida_com_consumo_recusada_sem_alterar_venda(self):
        j = self.janela()
        j.ent_pos.setText("180")
        j.btn_chamar.click()
        self.lancar(j, "10")
        venda = j.venda_id
        antes = dict(self.ctx.caixa.obter(venda))
        self.assertEqual(self.ctx.caixa.itens(venda)[0]["total_cent"], 800)
        with patch.object(j, "_emitir") as emitir:
            j.liberar_saida()
        self.assertEqual(self.ctx.caixa.obter(venda)["status"], "aberta")
        self.assertEqual(dict(self.ctx.caixa.obter(venda)), antes)
        self.assertEqual(self.banco.cfg_int("ultimo_ticket_saida", 0), 0)
        emitir.assert_not_called()

    def test_codigo_saida_pergunta_posicao_sem_venda(self):
        j = self.janela()
        j.dialogos.textos = ["180"]
        with patch.object(j, "_emitir") as emitir:
            self.lancar(j, self.ctx.caixa.codigo_saida())
        self.assertEqual(self.banco.cfg_int("ultimo_ticket_saida", 0), 1)
        self.assertEqual(len(self.ctx.caixa.saidas_liberadas(self.ctx.turnos.atual()["id"])), 1)
        emitir.assert_called_once()
        self.assertEqual(j.dialogos.textos, [])

    def test_falha_ticket_preserva_saida_e_registra_erro(self):
        j = self.janela()
        j.dialogos.textos = ["180"]
        with patch.object(j, "_emitir", side_effect=OSError("impressora desligada")), patch.object(
                j, "_registrar_falha") as log:
            j.liberar_saida()
        self.assertEqual(self.banco.cfg_int("ultimo_ticket_saida", 0), 1)
        self.assertTrue(j.dialogos.erros)
        log.assert_called_once()

    def test_cancelar_pergunta_de_saida_nao_grava(self):
        j = self.janela()
        j.dialogos.textos = [None]
        with patch.object(j, "_emitir") as emitir:
            self.lancar(j, self.ctx.caixa.codigo_saida())
        self.assertEqual(self.banco.cfg_int("ultimo_ticket_saida", 0), 0)
        self.assertEqual(self.ctx.caixa.saidas_liberadas(self.ctx.turnos.atual()["id"]), [])
        emitir.assert_not_called()
