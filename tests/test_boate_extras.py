"""Funções de boate: a consulta de comanda na saída da casa e o alerta de dinheiro demais na gaveta."""
from __future__ import annotations

import unittest

from src.controllers.cadastro_controller import CadastroController
from src.controllers.comissao_controller import ComissaoController
from src.core import formatacao as fmt
from tests.test_caixa import BaseCaixa
from tests.test_fechamento_turno import rotulos
from tests.test_ui import BaseUI
from tests.ui_robo import clicar, entradas


class BaseBoate(BaseCaixa):
    def comanda(self, numero, *itens):
        vid, _ = self.caixa.abrir_mesa(numero, comanda=True)
        for pid, qtd in itens:
            self.caixa.adicionar_item(vid, pid, qtd)
        return vid

    def pagar_tudo(self, vid, forma="Dinheiro"):
        tipo = self.tipo(forma)                                # com a taxa do crédito, quando a forma cobra
        self.caixa.adicionar_pagamento(vid, tipo, self.caixa.obter(vid)["total_cent"] + self.caixa.acrescimo_da_forma(vid, tipo))
        return self.caixa.fechar(vid)


class TesteSituacaoDaPosicao(BaseBoate):
    def test_numero_que_nunca_apareceu(self):
        self.assertEqual(self.caixa.situacao_posicao(True, 99), {"situacao": "sem_registro"})

    def test_aberta_com_consumo_diz_quanto_deve(self):
        self.comanda(7, (self.skol, 1), (self.agua, 1))
        s = self.caixa.situacao_posicao(True, 7)
        self.assertEqual((s["situacao"], s["total_cent"], s["itens"], s["conta_enviada"]), ("aberta", 1265, 2, False))   # 8,00 + 3,50 + 10%
        self.assertEqual(s["quando"], fmt.agora())

    def test_conta_enviada_continua_aberta_e_avisa(self):
        vid = self.comanda(7, (self.skol, 1))
        self.caixa.enviar_conta(vid)
        s = self.caixa.situacao_posicao(True, 7)
        self.assertEqual((s["situacao"], s["conta_enviada"]), ("aberta", True))

    def test_paga_traz_cupom_total_e_hora(self):
        vid = self.comanda(7, (self.skol, 1))
        self.avancar(minutes=40)
        self.pagar_tudo(vid)
        s = self.caixa.situacao_posicao(True, 7)
        self.assertEqual((s["situacao"], s["cupom"], s["total_cent"]), ("paga", 1, 880))
        self.assertEqual(s["quando"], fmt.agora())

    def test_aberta_sem_consumo_e_vazia(self):
        self.comanda(7)
        self.assertEqual(self.caixa.situacao_posicao(True, 7), {"situacao": "vazia"})

    def test_item_cancelado_nao_conta_como_consumo(self):
        vid = self.comanda(7, (self.skol, 1))
        self.caixa.cancelar_item(self.caixa.itens(vid)[0]["id"])
        self.assertEqual(self.caixa.situacao_posicao(True, 7)["situacao"], "vazia")

    def test_cancelada(self):
        vid = self.comanda(7, (self.skol, 1))
        self.caixa.cancelar_venda(vid, "cliente desistiu")
        s = self.caixa.situacao_posicao(True, 7)
        self.assertEqual(s["situacao"], "cancelada")
        self.assertTrue(s["quando"])

    def test_comanda_reutilizada_vale_a_venda_mais_recente(self):
        self.pagar_tudo(self.comanda(7, (self.skol, 1)))                    # o primeiro cliente paga e sai
        self.assertEqual(self.caixa.situacao_posicao(True, 7)["situacao"], "paga")
        self.comanda(7, (self.agua, 2))                                      # o cartão volta com outro cliente
        s = self.caixa.situacao_posicao(True, 7)
        self.assertEqual((s["situacao"], s["total_cent"]), ("aberta", 770))
        self.pagar_tudo(self.caixa.abrir_mesa(7, comanda=True)[0])
        self.assertEqual(self.caixa.situacao_posicao(True, 7)["cupom"], 2)   # o cupom do segundo, não o do primeiro

    def test_mesa_e_comanda_com_o_mesmo_numero_sao_coisas_diferentes(self):
        self.comanda(5, (self.skol, 1))
        self.assertEqual(self.caixa.situacao_posicao(True, 5)["situacao"], "aberta")
        self.assertEqual(self.caixa.situacao_posicao(False, 5)["situacao"], "sem_registro")


class TesteDinheiroEsperado(BaseBoate):
    def confere(self):
        self.assertEqual(self.turnos.dinheiro_esperado(self.turno), self.turnos.resumo(self.turno)["esperado"])
        return self.turnos.dinheiro_esperado(self.turno)

    def test_so_o_fundo_de_caixa(self):
        self.assertEqual(self.confere(), 10000)

    def test_vendas_em_dinheiro_somam_ja_sem_o_troco(self):
        vid = self.comanda(7, (self.skol, 1))
        self.caixa.adicionar_pagamento(vid, self.tipo("Dinheiro"), 2000)      # paga com 20,00: R$ 11,20 de troco
        self.caixa.fechar(vid)
        self.assertEqual(self.confere(), 10000 + 880)

    def test_cartao_e_pix_nao_entram_na_gaveta(self):
        self.pagar_tudo(self.comanda(7, (self.skol, 1)), "Cartão Crédito")
        self.pagar_tudo(self.comanda(8, (self.skol, 1)), "Pix")
        self.assertEqual(self.confere(), 10000)

    def test_forma_cadastrada_pelo_dono_fica_na_gaveta(self):
        self.banco.inserir("tipos_pagamento", {"tipo": "Cheque", "ordem": 50})        # padrão: fica na gaveta
        self.pagar_tudo(self.comanda(7, (self.skol, 1)), "Cheque")
        self.assertEqual(self.confere(), 10000 + 880)

    def test_sangria_e_suprimento(self):
        self.pagar_tudo(self.comanda(7, (self.skol, 2)))
        self.turnos.movimentar(self.turno, self.adm, "saida", 5000, "sangria")
        self.turnos.movimentar(self.turno, self.adm, "entrada", 2000, "troco")
        self.assertEqual(self.confere(), 10000 + 1760 - 5000 + 2000)

    def test_venda_aberta_ou_cancelada_nao_conta(self):
        self.comanda(7, (self.skol, 1))
        vid = self.comanda(8, (self.skol, 1))
        self.caixa.cancelar_venda(vid, "teste")
        self.assertEqual(self.confere(), 10000)

    def test_pagamento_de_comissao_tirado_do_caixa_conta_como_sangria(self):
        CadastroController(self.banco).salvar("garotas", {"numero": 180, "nome": "MARIA", "ativo": "S"})
        com = ComissaoController(self.banco)
        com.lancar(180, 2500, self.turno, self.adm)
        com.pagar(180, self.turno, self.adm, True)
        self.assertEqual(self.confere(), 10000 - 2500)

    def test_cada_turno_so_conta_o_seu(self):
        self.pagar_tudo(self.comanda(7, (self.skol, 1)))
        self.turnos.fechar(self.turno, self.adm, 10880)
        turno2 = self.turnos.abrir(self.adm, 2, 5000)
        self.assertEqual(self.turnos.dinheiro_esperado(turno2), 5000)
        self.assertEqual(self.turnos.dinheiro_esperado(turno2), self.turnos.resumo(turno2)["esperado"])


class BaseBoateNaTela(BaseUI):
    def setUp(self):
        super().setUp()
        self.abrir_turno()
        from src.ui.caixa_ui import JanelaCaixa
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()
        self.turno = self.ctx.turnos.atual()["id"]

    def comanda(self, numero, *itens):
        vid, _ = self.ctx.caixa.abrir_mesa(numero, comanda=True)
        for pid, qtd in itens:
            self.ctx.caixa.adicionar_item(vid, pid, qtd)
        return vid

    def vender_em(self, forma, numero=7, qtd=1):
        vid = self.comanda(numero, (self.skol, qtd))
        tipo = self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = ?", (forma,))
        self.ctx.caixa.adicionar_pagamento(
            vid, tipo, self.ctx.caixa.obter(vid)["total_cent"] + self.ctx.caixa.acrescimo_da_forma(vid, tipo))
        return self.ctx.caixa.fechar(vid)


class TesteConsultaDeComandaNaTela(BaseBoateNaTela):
    def consultar(self, numero):
        """Abre a consulta, digita o número e devolve o texto da resposta."""
        respostas = []

        def dialogo(w):
            campos = entradas(w)
            if campos:
                campos[0].insert(0, str(numero)); clicar(w, "OK")
            else:
                respostas.append(rotulos(w)); clicar(w, "OK")
        self.robo.quando("Dialogo", dialogo, vezes=4)
        self.cx.consultar_comanda()
        self.sem_travar()
        self.assertEqual(len(respostas), 1, respostas)
        return respostas[0]

    def test_o_botao_esta_na_barra_do_caixa(self):
        nomes = [t[0] for t in self.cx.tarefas]
        self.assertIn("Consulta Comanda", nomes)
        self.assertEqual(nomes[-1], "Sair")
        self.assertEqual(len(self.cx.botoes_tarefa), len(self.cx.tarefas))

    def test_comanda_paga_pode_sair(self):
        self.vender_em("Dinheiro", numero=7)
        texto = self.consultar(7)
        self.assertIn("Comanda 7: PAGA", texto)
        self.assertIn("Cupom 1", texto)
        self.assertIn("R$ 8,80", texto)

    def test_comanda_aberta_mostra_quanto_falta_pagar(self):
        self.comanda(7, (self.skol, 2))
        texto = self.consultar(7)
        self.assertIn("Comanda 7: ABERTA - A PAGAR R$ 17,60", texto)
        self.assertIn("1 item(ns)", texto)

    def test_numero_que_nao_existe(self):
        self.assertIn("Comanda 99: nenhum registro.", self.consultar(99))

    def test_a_consulta_nao_mexe_na_venda_que_esta_na_tela(self):
        self.cx.var_pos.set("12"); self.cx.chamar_mesa()
        venda = self.cx.venda_id
        self.vender_em("Pix", numero=7)
        self.consultar(7)
        self.assertEqual(self.cx.venda_id, venda)
        self.assertEqual(self.cx.venda()["posicao"], 12)

    def test_comanda_de_garota_lembra_da_comissao_a_pagar(self):
        self.ctx.comissoes.lancar(180, 2500, self.turno, self.ctx.operador_id)
        texto = self.consultar(180)
        self.assertIn("Comanda 180: nenhum registro.", texto)
        self.assertIn("Comissão da garota 180 a pagar: R$ 25,00.", texto)

    def test_mesa_tambem_pode_ser_consultada(self):
        vid, _ = self.ctx.caixa.abrir_mesa(5)
        self.ctx.caixa.adicionar_item(vid, self.skol, 1)
        self.assertIn("Mesa 5: ABERTA - A PAGAR R$ 8,80", self.consultar("M5"))

    def test_desistir_nao_mostra_nada(self):
        self.robo.quando("Dialogo", lambda w: clicar(w, "Cancelar"), vezes=2)
        self.cx.consultar_comanda()
        self.sem_travar()
        self.assertEqual(len(self.robo.log), 1)                                # só a janela do número abriu


class TesteAlertaDeGaveta(BaseBoateNaTela):
    def test_sem_limite_configurado_nunca_avisa(self):
        self.vender_em("Dinheiro", qtd=500)                                   # R$ 4.400,00 em dinheiro
        self.assertEqual(self.cx._alerta_gaveta(), "")

    def test_abaixo_do_limite_nao_avisa(self):
        self.banco.cfg_set("limite_gaveta", "200")                            # fundo de R$ 100 + venda de R$ 8,80
        self.vender_em("Dinheiro")
        self.assertEqual(self.cx._alerta_gaveta(), "")

    def test_passando_do_limite_pede_sangria_sem_dizer_quanto_ha(self):
        self.banco.cfg_set("limite_gaveta", "105")
        self.vender_em("Dinheiro")                                            # R$ 100,00 + 8,80 = 108,80 > 105
        alerta = self.cx._alerta_gaveta()
        self.assertEqual(alerta, "ATENÇÃO: a gaveta passou de R$ 105,00. Faça uma sangria (F7).")
        self.assertNotIn("108", alerta)                                       # o valor esperado não é revelado

    def test_exatamente_no_limite_ainda_nao_avisa(self):
        self.banco.cfg_set("limite_gaveta", "100")
        self.assertEqual(self.cx._alerta_gaveta(), "")

    def test_cartao_e_pix_nao_disparam_o_alerta(self):
        self.banco.cfg_set("limite_gaveta", "100")
        self.vender_em("Cartão Crédito", numero=7, qtd=50)
        self.vender_em("Pix", numero=8, qtd=50)
        self.assertEqual(self.cx._alerta_gaveta(), "")

    def test_a_sangria_derruba_o_alerta(self):
        self.banco.cfg_set("limite_gaveta", "105")
        self.vender_em("Dinheiro")
        self.assertNotEqual(self.cx._alerta_gaveta(), "")
        self.ctx.turnos.movimentar(self.turno, self.ctx.operador_id, "saida", 5000, "sangria")
        self.assertEqual(self.cx._alerta_gaveta(), "")

    def test_ao_fechar_a_venda_o_status_traz_o_aviso_em_laranja(self):
        from src.ui import tema
        self.banco.cfg_set("limite_gaveta", "105")
        venda = self.vender_em("Dinheiro")
        self.cx._pos_fechamento(venda)
        texto = self.cx.status.cget("text")
        self.assertIn("Venda 1 fechada.", texto)
        self.assertIn("ATENÇÃO: a gaveta passou de R$ 105,00. Faça uma sangria (F7).", texto)
        self.assertEqual(str(self.cx.status.cget("foreground")), tema.COR["aviso"])

    def test_venda_comum_continua_com_a_mensagem_verde_de_sempre(self):
        from src.ui import tema
        venda = self.vender_em("Dinheiro")
        self.cx._pos_fechamento(venda)
        self.assertEqual(self.cx.status.cget("text"), "Venda 1 fechada. Troco R$ 0,00.")
        self.assertEqual(str(self.cx.status.cget("foreground")), tema.COR["ok"])

    def test_a_configuracao_aparece_nas_configuracoes_e_valida_o_valor(self):
        from src.controllers.config_controller import CAMPOS_CONFIG, ConfigController
        from src.core.erros import ErroValidacao
        self.assertIn("limite_gaveta", [c[0] for c in CAMPOS_CONFIG])
        ConfigController(self.banco).salvar_config({"limite_gaveta": "1500"})
        self.assertEqual(self.banco.cfg_int("limite_gaveta"), 1500)
        with self.assertRaises(ErroValidacao):
            ConfigController(self.banco).salvar_config({"limite_gaveta": "2000000"})


if __name__ == "__main__":
    unittest.main()
