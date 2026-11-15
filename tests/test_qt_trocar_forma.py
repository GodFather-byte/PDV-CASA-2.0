"""Caixa Qt: errou a forma (Débito + Enter com a conta paga) e troca para outra sem cancelar a venda."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from tests.test_qt_caixa import BaseCaixaQt


class TestTrocarFormaPaga(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.abrir_turno()
        self.novo_produto("CERVEJA", 800, codigo="71")
        self.j = self.janela()
        self.lancar(self.j, "71", "1")

    def enter_na_forma(self):
        self.j._tecla_forma(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))

    def pagamentos(self):
        return [(p["tipo"], p["valor_cent"]) for p in self.ctx.caixa.pagamentos(self.j.venda()["id"])]

    def pagar_no_debito(self):
        self.forma(self.j, "Cartão Débito")
        self.enter_na_forma()
        self.j.ent_valor.setText("8,00")
        self.j.receber()
        self.assertEqual(self.pagamentos(), [("Cartão Débito", 800)])

    def test_escolher_outra_forma_com_a_conta_paga_troca_o_pagamento(self):
        self.pagar_no_debito()
        self.forma(self.j, "Dinheiro")
        self.j.dialogos.confirmacoes = [True]
        self.enter_na_forma()
        self.assertEqual(self.pagamentos(), [])                       # o débito saiu; a venda continua aberta
        self.assertEqual(self.j.cmb_forma.currentText(), "Dinheiro")
        self.assertEqual(self.j.ent_valor.text(), "8,00")             # valor que falta, pronto para o Enter
        self.j.ent_valor.setText("10,00")
        self.j.receber()
        self.assertEqual(self.pagamentos(), [("Dinheiro", 1000)])     # e o troco funciona
        self.assertEqual(self.j.lbl_troco.text(), "2,00")

    def test_desistir_da_troca_mantem_o_pagamento(self):
        self.pagar_no_debito()
        self.forma(self.j, "Dinheiro")
        self.j.dialogos.confirmacoes = [False]
        self.enter_na_forma()
        self.assertEqual(self.pagamentos(), [("Cartão Débito", 800)])

    def test_mesma_forma_ou_conta_em_aberto_segue_o_fluxo_normal(self):
        self.forma(self.j, "Dinheiro")
        self.enter_na_forma()                                         # nada pago: só vai para o valor
        self.assertEqual(self.pagamentos(), [])
        self.assertFalse(self.j.dialogos.confirmacoes)
        self.pagar_no_debito()
        self.forma(self.j, "Cartão Débito")
        self.enter_na_forma()                                         # mesma forma: não pergunta nada
        self.assertEqual(self.pagamentos(), [("Cartão Débito", 800)])


if __name__ == "__main__":
    import unittest
    unittest.main()
