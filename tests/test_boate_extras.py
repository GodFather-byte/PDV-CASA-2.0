"""Funções de boate: a consulta de comanda na saída da casa e o alerta de dinheiro demais na gaveta."""
from __future__ import annotations

import unittest

from src.controllers.cadastro_controller import CadastroController
from src.controllers.comissao_controller import ComissaoController
from src.core import formatacao as fmt
from tests.test_caixa import BaseCaixa


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


if __name__ == "__main__":
    unittest.main()
