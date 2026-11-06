"""Quarto pela comanda no caixa Qt: o show (código 33) tem o valor; o número da garota (113) só marca de quem são os shows.
Pagar inicia o quarto e avisa a chave; sem quarto livre, fila oferecida ao liberar."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from tests.test_qt_caixa import BaseCaixaQt, QApplication

if QApplication is not None:
    from PySide6.QtWidgets import QMessageBox
    from src.controllers.cadastro_controller import CadastroController
    from src.ui_qt.quartos import oferecer_fila


class TesteQuartoNaComandaQt(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("usar_quartos", "S")
        self.banco.cfg_set("quartos_qtd", "2")
        CadastroController(self.banco).salvar("garotas", {"numero": 180, "nome": "ANA", "ativo": "S"})
        self.abrir_turno()
        self.novo_produto("SKOL", 800, codigo="101")
        self.show = self.novo_produto("PG 30 MIN", 10000, codigo="33")
        self.banco.cfg_set("quartos_codigo_show", "33")
        self.j = self.janela()

    def pagar_tudo(self):
        self.j.ent_valor.setText(self.j.lbl_total.text())
        self.j.receber()
        self.j.fechar_venda()                                     # Enter/F12 depois do pagamento completo

    def itens(self):
        return self.ctx.caixa.itens(self.j.venda_id) if self.j.venda_id else []

    def test_show_33_tem_o_valor_e_o_numero_dela_so_marca(self):
        self.lancar(self.j, "101", "2")
        self.lancar(self.j, "33")
        self.lancar(self.j, "180")                                            # depois do show: liga o show a ela
        self.assertEqual(self.j.venda()["total_cent"], 2 * 800 + 10000)       # 180 não somou valor
        show = next(i for i in self.itens() if i["produto_id"] == self.show)
        self.assertEqual((show["garota_quarto"], show["preco_unit_cent"]), (180, 10000))
        self.assertIn("Garota 180 ANA", self.j.lbl_venda.text())
        self.assertIn("garota 180 ANA", self.j.tabela.item(1, 1).text())
        self.assertIn("30 min de show", self.j.lbl_status.text())
        self.pagar_tudo()
        self.assertEqual(self.banco.valor("SELECT codigo_profissional FROM quartos_uso WHERE quarto = 1"), "180")
        self.assertEqual(self.ctx.comissoes.quantidade_shows_quartos(180), 1)
        self.assertIn("QUARTO 1  →  ANA (180)  ·  30 min.  Entregue a chave do 1.", self.j.dialogos.avisos[-1])

    def test_numero_antes_e_dois_shows_dao_1h(self):
        self.lancar(self.j, "180")
        self.assertIn("Lance o show (PG 30 MIN)", self.j.lbl_status.text())
        self.lancar(self.j, "33")
        self.lancar(self.j, "33")
        self.assertEqual(self.j.venda()["total_cent"], 20000)
        self.assertTrue(all(i["garota_quarto"] == 180 for i in self.itens()))
        self.lancar(self.j, "180")                                            # repetir o número não soma nada
        self.assertEqual(self.j.venda()["total_cent"], 20000)
        self.pagar_tudo()
        self.assertIn("ANA (180)  ·  1h", self.j.dialogos.avisos[-1])
        self.assertEqual(self.ctx.comissoes.quantidade_shows_quartos(180), 2)

    def test_show_sem_o_numero_dela_nao_fecha(self):
        self.lancar(self.j, "33")
        self.pagar_tudo()
        self.assertIn("Falta o número da garota", " ".join(self.j.dialogos.erros + self.j.dialogos.avisos))
        self.assertEqual(self.j.venda()["status"], "aberta")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM quartos_uso"), 0)

    def test_numero_com_q_escolhe_o_quarto(self):
        self.lancar(self.j, "33")
        self.lancar(self.j, "180Q2")
        self.assertIn("quarto 2", self.j.lbl_venda.text())
        self.pagar_tudo()
        self.assertEqual(self.banco.valor("SELECT quarto FROM quartos_uso"), 2)

    def test_garota_nao_cadastrada_e_regra_dos_100(self):
        self.lancar(self.j, "180Q9")
        self.assertIn("Quarto inexistente", " ".join(self.j.dialogos.erros + [self.j.lbl_status.text()]))
        self.lancar(self.j, "999Q")
        self.assertIn("não cadastrada", self.j.lbl_status.text())
        CadastroController(self.banco).salvar("garotas", {"numero": 51, "nome": "BIA", "ativo": "S"})
        self.novo_produto("AGUA", 300, codigo="51")
        self.lancar(self.j, "51")                                             # abaixo de 100: produto
        self.assertEqual(self.itens()[0]["produto_id"], self.banco.valor("SELECT id FROM produtos WHERE codigo LIKE '%51'"))

    def test_sem_quarto_livre_avisa_e_liberar_oferece_a_fila(self):
        q = self.ctx.quartos
        q.iniciar(1, 1)
        q.iniciar(2, 1)
        self.lancar(self.j, "33")
        self.lancar(self.j, "180")
        self.pagar_tudo()
        self.assertIn("Sem quarto livre: ANA (180) aguardando", self.j.dialogos.avisos[-1])
        q.liberar(2)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as pergunta:
            self.assertTrue(oferecer_fila(self.j, q, 2))
        self.assertIn("O quarto 2 ficou livre. Iniciar agora para ANA (180)", pergunta.call_args.args[2])
        self.assertEqual(self.banco.valor("SELECT codigo_profissional FROM quartos_uso WHERE quarto = 2 "
                                          "AND liberado_em IS NULL"), "180")
        self.assertFalse(oferecer_fila(self.j, q, 2))                       # fila vazia: não pergunta nada

    def test_com_quartos_desligado_33_e_produto_comum(self):
        self.banco.cfg_set("usar_quartos", "N")
        self.lancar(self.j, "33")
        self.pagar_tudo()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM quartos_uso"), 0)
        self.assertEqual(self.banco.valor("SELECT status FROM vendas"), "fechada")
