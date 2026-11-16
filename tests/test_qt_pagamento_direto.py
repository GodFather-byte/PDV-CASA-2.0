"""Caixa Qt, recebimento direto (Will Adega): Enter vai ao valor já preenchido e a conta paga fecha sozinha."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from tests.test_qt_caixa import BaseCaixaQt


def tecla(codigo, texto=""):
    return QKeyEvent(QKeyEvent.KeyPress, codigo, Qt.NoModifier, texto)


class TestPagamentoDireto(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("pagamento_direto", "S")
        self.abrir_turno()
        self.novo_produto("CERVEJA", 800, codigo="71")
        self.j = self.janela()
        self.lancar(self.j, "71", "1")
        self.venda = self.j.venda()["id"]

    def fechada(self):
        return self.banco.um("SELECT status, total_cent, troco_cent FROM vendas WHERE id = ?", (self.venda,))

    def pagamentos(self):
        return [(p["tipo"], p["valor_cent"]) for p in self.ctx.caixa.pagamentos(self.venda)]

    def test_enter_vai_ao_valor_preenchido_e_o_segundo_enter_fecha(self):
        self.j.ir_para_pagamento()
        self.assertEqual((self.j.cmb_forma.currentText(), self.j.ent_valor.text()), ("Dinheiro", "8,00"))
        self.j.receber()
        v = self.fechada()
        self.assertEqual((v["status"], v["troco_cent"]), ("fechada", 0))
        self.assertEqual(self.pagamentos(), [("Dinheiro", 800)])
        self.assertIsNone(self.j.venda_id)

    def test_valor_maior_em_dinheiro_fecha_e_mostra_o_troco(self):
        self.j.ir_para_pagamento()
        self.j.ent_valor.setText("10")
        self.j.receber()
        self.assertEqual(self.fechada()["troco_cent"], 200)
        self.assertEqual(self.j.lbl_troco.text(), "2,00")

    def test_letra_no_valor_troca_a_forma_sem_digitar_o_valor_de_novo(self):
        self.j.ir_para_pagamento()
        self.j.ent_valor.setText("50")
        self.assertTrue(self.j._tecla_valor(tecla(Qt.Key_P, "p")))
        self.assertEqual((self.j.cmb_forma.currentText(), self.j.ent_valor.text()), ("Pix", "8,00"))
        self.j.receber()
        self.assertEqual(self.fechada()["status"], "fechada")
        self.assertEqual(self.pagamentos(), [("Pix", 800)])

    def test_seta_troca_a_forma_e_numero_continua_sendo_valor(self):
        self.j.ir_para_pagamento()
        self.assertTrue(self.j._tecla_valor(tecla(Qt.Key_Down)))
        self.assertEqual(self.j.cmb_forma.currentText(), "Cartão Débito")
        self.assertFalse(self.j._tecla_valor(tecla(Qt.Key_5, "5")))

    def test_pagamento_parcial_continua_no_valor_com_o_que_falta(self):
        self.j.ir_para_pagamento()
        self.j.ent_valor.setText("5")
        self.j.receber()
        self.assertEqual(self.fechada()["status"], "aberta")
        self.assertEqual(self.j.ent_valor.text(), "3,00")
        self.j.receber()
        self.assertEqual(self.fechada()["status"], "fechada")
        self.assertEqual(self.pagamentos(), [("Dinheiro", 500), ("Dinheiro", 300)])

    def test_f12_sem_receber_leva_ao_valor_em_vez_de_recusar(self):
        self.j.fechar_venda()
        self.assertEqual(self.fechada()["status"], "aberta")
        self.assertEqual(self.j.ent_valor.text(), "8,00")
        self.assertFalse(self.j.dialogos.avisos if hasattr(self.j.dialogos, "avisos") else False)

    def test_desligado_o_fluxo_classico_continua(self):
        self.banco.cfg_set("pagamento_direto", "N")
        self.assertFalse(self.j._tecla_valor(tecla(Qt.Key_P, "p")))
        self.j.ent_valor.setText("8,00")
        self.j.receber()
        self.assertEqual(self.fechada()["status"], "aberta")          # paga, mas espera o Enter que fecha


if __name__ == "__main__":
    import unittest
    unittest.main()
