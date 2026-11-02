"""Ficha de dinheiro: débito auditável, estorno explícito e fechamento correto."""
from __future__ import annotations

from src.controllers import ficha_sangria
from src.controllers.impressao_controller import ImpressaoController
from src.core.erros import ErroNegocio
from tests.test_caixa import BaseCaixa


class TesteFichaSangria(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("codigo_ficha_sangria", "31")
        self.ficha = self.novo_produto("FICHA DE DINHEIRO", 1000, codigo="31")
        self.venda, _ = self.caixa.abrir_mesa(12, comanda=True)

    def test_ficha_retira_dinheiro_sem_cobrar_servico_e_gera_movimento_unico(self):
        saldo = self.turnos.dinheiro_esperado(self.turno)
        item = self.caixa.adicionar_item(self.venda, self.ficha, 1, confirmar_entrega_ficha=True)
        mov = ficha_sangria.saida_do_item(self.banco, item)
        self.assertIsNotNone(mov)
        self.assertEqual(mov["valor_cent"], 1000)
        self.assertEqual(mov["tipo"], "saida")
        self.assertEqual(self.turnos.dinheiro_esperado(self.turno), saldo - 1000)
        self.assertEqual(self.caixa.itens(self.venda)[0]["cobra_servico"], 0)
        self.assertEqual(self.banco.valor(
            "SELECT COUNT(*) FROM movimentos_caixa WHERE tipo = 'saida'"), 1)
        self.assertEqual(self.caixa.obter(self.venda)["status"], "aberta")

    def test_sem_configuracao_produto_31_nao_faz_sangria(self):
        self.banco.cfg_set("codigo_ficha_sangria", "")
        saldo = self.turnos.dinheiro_esperado(self.turno)
        item = self.caixa.adicionar_item(self.venda, self.ficha, 1, confirmar_entrega_ficha=True)
        self.assertIsNone(ficha_sangria.saida_do_item(self.banco, item))
        self.assertEqual(self.turnos.dinheiro_esperado(self.turno), saldo)

    def test_bloqueia_ficha_no_balcao_ou_sem_dinheiro(self):
        with self.assertRaisesRegex(ErroNegocio, "comanda"):
            self.caixa.adicionar_item(self.caixa.abrir_balcao(), self.ficha, 1, confirmar_entrega_ficha=True)
        with self.assertRaisesRegex(ErroNegocio, "insuficiente"):
            self.caixa.adicionar_item(self.venda, self.ficha, 11, confirmar_entrega_ficha=True)
        self.assertEqual(self.banco.valor(
            "SELECT COUNT(*) FROM itens_venda WHERE venda_id = ?", (self.venda,)), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 0)

    def test_cancelamento_exige_devolucao_do_dinheiro_e_estorna_uma_vez(self):
        saldo = self.turnos.dinheiro_esperado(self.turno)
        item = self.caixa.adicionar_item(self.venda, self.ficha, 1, confirmar_entrega_ficha=True)
        with self.assertRaisesRegex(ErroNegocio, "devolução física"):
            self.caixa.cancelar_item(item, "erro")
        self.assertEqual(self.turnos.dinheiro_esperado(self.turno), saldo - 1000)
        self.caixa.cancelar_item(item, "dinheiro devolvido", devolucao_ficha_confirmada=True)
        self.assertEqual(self.turnos.dinheiro_esperado(self.turno), saldo)
        self.assertIsNotNone(ficha_sangria.estorno_do_item(self.banco, item))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 2)
        with self.assertRaises(ErroNegocio):
            self.caixa.cancelar_item(item, "segunda vez", devolucao_ficha_confirmada=True)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 2)

    def test_cancelamento_da_comanda_requer_devolucao(self):
        saldo = self.turnos.dinheiro_esperado(self.turno)
        self.caixa.adicionar_item(self.venda, self.ficha, 2, confirmar_entrega_ficha=True)
        with self.assertRaisesRegex(ErroNegocio, "devolução física"):
            self.caixa.cancelar_venda(self.venda, "erro")
        self.caixa.cancelar_venda(self.venda, "dinheiro devolvido", True)
        self.assertEqual(self.turnos.dinheiro_esperado(self.turno), saldo)
        self.assertEqual(self.banco.valor(
            "SELECT COUNT(*) FROM movimentos_caixa WHERE tipo='entrada'"), 1)

    def test_impede_transferencia_de_ficha_entregue(self):
        item = self.caixa.adicionar_item(self.venda, self.ficha, 1, confirmar_entrega_ficha=True)
        with self.assertRaisesRegex(ErroNegocio, "não pode ser transferida"):
            self.caixa.transferir_item(item, (True, 13), 1)
        with self.assertRaisesRegex(ErroNegocio, "não pode ser transferida"):
            self.caixa.transferir_mesa((True, 12), (True, 13))

    def test_comprovante_conta_valor_comanda_e_identificacao(self):
        texto = ImpressaoController(self.banco).comprovante_ficha(1000, 12, "ADM", 42)
        self.assertIn("FICHA", texto)
        self.assertIn("10,00", texto)
        self.assertIn("12", texto)
        self.assertIn("42", texto)
        self.assertIn("ADM", texto)
