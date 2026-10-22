"""Pré-pago (usar_prepago): o cliente carrega crédito na comanda (Recarga), só consome até o saldo e na saída recebe a sobra
de volta, como troco ou, se a recarga veio por Pix/cartão ou num turno já fechado, como uma saída registrada da gaveta."""
from __future__ import annotations

import unittest
from unittest import mock

from src.controllers.impressao_controller import ImpressaoController
from src.core.erros import ErroNegocio
from tests.test_caixa import BaseCaixa


class BasePrepago(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("usar_prepago", "S")
        self.banco.cfg_set("cobra_servico_comanda", "N")      # conta redonda nos exemplos; o serviço tem teste próprio
        self.vid, _ = self.caixa.abrir_mesa(15, comanda=True)

    def recarga(self, valor, forma="Dinheiro", vid=None):
        return self.caixa.recarregar(vid or self.vid, self.tipo(forma), valor)

    def n_itens(self, vid=None):
        return self.banco.valor("SELECT COUNT(*) FROM itens_venda WHERE venda_id = ? AND cancelado = 0", (vid or self.vid,))

    def saidas(self, turno=None):
        return self.banco.todos("SELECT valor_cent, descricao FROM movimentos_caixa WHERE turno_id = ? AND tipo = 'saida'",
                                (turno or self.turno,))


class TesteRecarga(BasePrepago):
    def test_recarga_marca_a_comanda_e_o_pagamento(self):
        pid = self.recarga(10000)
        self.assertEqual(self.caixa.obter(self.vid)["prepago"], 1)
        self.assertEqual(self.banco.valor("SELECT recarga FROM pagamentos_venda WHERE id = ?", (pid,)), 1)
        self.assertEqual(self.caixa.saldo_prepago(self.vid), {"credito": 10000, "consumo": 0, "saldo": 10000})
        self.assertIn("R$ 100,00", self.banco.valor("SELECT detalhe FROM log_eventos WHERE evento = 'recarga'"))

    def test_recusa_com_o_modulo_desligado(self):
        self.banco.cfg_set("usar_prepago", "N")
        with self.assertRaisesRegex(ErroNegocio, "desligado"):
            self.recarga(5000)
        self.assertEqual(self.caixa.pagamentos(self.vid), [])
        self.assertEqual(self.caixa.obter(self.vid)["prepago"], 0)

    def test_recusa_fora_de_mesa_ou_comanda(self):
        balcao = self.caixa.abrir_balcao()
        with self.assertRaises(ErroNegocio):
            self.recarga(5000, vid=balcao)

    def test_comanda_sem_recarga_continua_como_sempre(self):
        outra, _ = self.caixa.abrir_mesa(20, comanda=True)
        self.caixa.adicionar_item(outra, self.skol, 5)                          # sem crédito nenhum e lança normal
        self.assertEqual(self.caixa.obter(outra)["prepago"], 0)
        self.assertEqual(self.caixa.liquidar(outra)["devolucao"], 0)


class TesteCredito(BasePrepago):
    def test_consome_ate_o_credito_e_bloqueia_o_que_passa(self):
        self.recarga(2000)
        self.caixa.adicionar_item(self.vid, self.skol, 2)                       # 16,00 de 20,00
        with self.assertRaisesRegex(ErroNegocio, r"saldo é R\$ 4,00 e isto custa R\$ 8,00"):
            self.caixa.adicionar_item(self.vid, self.skol, 1)
        self.assertEqual(self.n_itens(), 1)                                     # o que passou não ficou lançado
        self.assertEqual(self.caixa.obter(self.vid)["total_cent"], 1600)
        self.recarga(1000)
        self.caixa.adicionar_item(self.vid, self.skol, 1)                       # com a recarga, lança
        self.assertEqual(self.caixa.saldo_prepago(self.vid)["saldo"], 600)

    def test_servico_conta_no_credito(self):
        self.banco.cfg_set("cobra_servico_comanda", "S")
        self.recarga(1000)
        self.caixa.adicionar_item(self.vid, self.skol, 1)                       # 8,00 + 10% = 8,80
        with self.assertRaisesRegex(ErroNegocio, r"custa R\$ 3,85"):
            self.caixa.adicionar_item(self.vid, self.agua, 1)                   # 3,50 + 10%

    def test_limite_geral_da_comanda_nao_vale_para_a_pre_paga(self):
        self.banco.cfg_set("limite_comanda", "10")                             # R$ 10,00 para quem não carregou crédito
        self.recarga(5000)
        for _ in range(3):
            self.caixa.adicionar_item(self.vid, self.skol, 1)                   # 24,00: passa do limite, cabe no crédito
        comum, _ = self.caixa.abrir_mesa(20, comanda=True)
        self.caixa.adicionar_item(comum, self.skol, 2)
        with self.assertRaisesRegex(ErroNegocio, "limite"):
            self.caixa.adicionar_item(comum, self.skol, 1)

    def test_transferir_item_para_a_pre_paga_respeita_o_credito(self):
        self.recarga(1000)
        origem, _ = self.caixa.abrir_mesa(20, comanda=True)
        item = self.caixa.adicionar_item(origem, self.skol, 2)
        with self.assertRaisesRegex(ErroNegocio, "Crédito insuficiente"):
            self.caixa.transferir_item(item, (True, 15), 2)                     # 16,00 não cabe em 10,00
        self.assertEqual(self.n_itens(origem), 1)
        self.caixa.transferir_item(item, (True, 15), 1)                         # 8,00 cabe
        self.assertEqual(self.caixa.saldo_prepago(self.vid)["saldo"], 200)

    def test_juntar_comanda_inteira_na_pre_paga_respeita_o_credito(self):
        self.recarga(1000)
        origem, _ = self.caixa.abrir_mesa(20, comanda=True)
        self.caixa.adicionar_item(origem, self.skol, 2)
        with self.assertRaisesRegex(ErroNegocio, "Crédito insuficiente"):
            self.caixa.transferir_mesa((True, 20), (True, 15))
        with self.assertRaisesRegex(ErroNegocio, "Crédito insuficiente"):
            self.caixa.transferir_varias([(True, 20)], (True, 15))
        self.assertEqual(self.n_itens(origem), 1)                               # nada mudou de lugar

    def test_pre_paga_juntada_numa_comanda_comum_vira_adiantamento(self):
        self.recarga(5000)
        self.caixa.adicionar_item(self.vid, self.skol, 1)
        comum, _ = self.caixa.abrir_mesa(20, comanda=True)
        self.caixa.adicionar_item(comum, self.skol, 10)
        self.caixa.transferir_mesa((True, 15), (True, 20))                      # a comum não trava: paga a diferença na saída
        self.assertEqual(self.caixa.obter(comum)["prepago"], 0)
        self.assertEqual(self.caixa.liquidar(comum)["falta"], 8800 - 5000)


class TesteSaida(BasePrepago):
    def test_sobra_de_recarga_em_dinheiro_vira_troco(self):
        self.recarga(5000)
        self.caixa.adicionar_item(self.vid, self.skol, 2)
        v = self.caixa.fechar(self.vid)
        self.assertEqual((v["total_cent"], v["pago_cent"], v["troco_cent"]), (1600, 5000, 3400))
        self.assertEqual(self.saidas(), [])
        self.assertEqual(self.turnos.dinheiro_esperado(self.turno), 10000 + 1600)

    def test_sobra_de_recarga_por_pix_sai_da_gaveta_como_devolucao(self):
        self.recarga(5000, "Pix")
        self.caixa.adicionar_item(self.vid, self.skol, 2)
        liq = self.caixa.liquidar(self.vid)
        self.assertEqual((liq["troco"], liq["devolucao"], liq["vale"]), (0, 3400, 0))
        v = self.caixa.fechar(self.vid)
        self.assertEqual((v["total_cent"], v["pago_cent"], v["troco_cent"]), (1600, 5000, 0))
        self.assertEqual([(s["valor_cent"], s["descricao"]) for s in self.saidas()],
                         [(3400, "Devolução do crédito pré-pago da comanda 15")])
        self.assertEqual(self.turnos.dinheiro_esperado(self.turno), 10000 - 3400)      # o dinheiro saiu da gaveta
        pix = next(l for l in self.turnos.maquininha(self.turno)["linhas"] if l["tipo"] == "Pix")
        self.assertEqual(pix["valor"], 5000)                                            # a maquininha bate com o que entrou

    def test_recarga_de_turno_ja_fechado_volta_pelo_turno_atual(self):
        self.recarga(5000)                                                      # dinheiro do turno 1
        self.turnos.fechar(self.turno, self.adm, 15000)
        turno2 = self.turnos.abrir(self.adm, 2, 10000)
        self.caixa.adicionar_item(self.vid, self.skol, 2)
        v = self.caixa.fechar(self.vid)
        self.assertEqual(v["troco_cent"], 0)                                    # o turno 1 já foi conferido: não muda
        self.assertEqual(self.banco.valor("SELECT troco_cent FROM pagamentos_venda WHERE venda_id = ?", (self.vid,)), 0)
        self.assertEqual([s["valor_cent"] for s in self.saidas(turno2)], [3400])
        self.assertEqual(self.turnos.dinheiro_esperado(turno2), 10000 - 3400)

    def test_dinheiro_e_pix_juntos_troco_primeiro_e_o_resto_como_devolucao(self):
        self.recarga(2000)
        self.recarga(3000, "Pix")
        self.caixa.adicionar_item(self.vid, self.skol, 1)
        liq = self.caixa.liquidar(self.vid)
        self.assertEqual((liq["troco"], liq["devolucao"]), (2000, 2200))

    def test_pix_pago_a_mais_na_saida_continua_recusado(self):
        self.recarga(1000, "Pix")
        self.caixa.adicionar_item(self.vid, self.skol, 1)
        self.pagar(self.vid, "Pix", 5000)                                       # não é recarga: não vira devolução
        with self.assertRaisesRegex(ErroNegocio, "não permite troco"):
            self.caixa.liquidar(self.vid)

    def test_sem_consumo_fecha_devolvendo_a_recarga(self):
        self.recarga(3000)
        v = self.caixa.fechar(self.vid)
        self.assertEqual((v["status"], v["total_cent"], v["troco_cent"]), ("fechada", 0, 3000))
        self.assertTrue(v["cupom"])
        comum, _ = self.caixa.abrir_mesa(20, comanda=True)
        self.pagar(comum, "Dinheiro", 1000)
        with self.assertRaisesRegex(ErroNegocio, "não tem itens"):              # a comanda comum continua exigindo item
            self.caixa.fechar(comum)

    def test_cupom_mostra_a_devolucao_e_a_pre_conta_o_saldo(self):
        self.recarga(5000, "Pix")
        self.caixa.adicionar_item(self.vid, self.skol, 2)
        imp = ImpressaoController(self.banco)
        pre = imp.pre_conta(self.vid)
        self.assertIn("Crédito carregado", pre)
        self.assertRegex(pre, r"Saldo\s+34,00")
        self.caixa.fechar(self.vid)
        self.assertRegex(imp.cupom(self.vid), r"Devolução do crédito\s+34,00")


if __name__ == "__main__":
    unittest.main()
