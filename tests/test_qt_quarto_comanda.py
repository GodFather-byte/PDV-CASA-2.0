"""Quarto pela comanda no caixa Qt: G25 lança o show da garota; pagar inicia o quarto e avisa a chave; fila ao liberar."""
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
        self.j = self.janela()

    def pagar_tudo(self):
        self.j.ent_valor.setText(self.j.lbl_total.text())
        self.j.receber()
        self.j.fechar_venda()                                     # Enter/F12 depois do pagamento completo

    def itens(self):
        return self.ctx.caixa.itens(self.j.venda_id) if self.j.venda_id else []

    def test_g180_lanca_o_show_e_pagar_inicia_o_quarto_e_avisa_a_chave(self):
        self.lancar(self.j, "101", "2")
        self.lancar(self.j, "G180", "2")
        quarto = next(i for i in self.itens() if i["garota_quarto"] == 180)
        self.assertEqual((quarto["quantidade"], quarto["preco_unit_cent"]), (2, 9000))
        self.assertIn("garota 180 ANA", self.j.tabela.item(1, 1).text())
        self.assertIn("O tempo começa quando a conta for paga", self.j.lbl_status.text())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM quartos_uso"), 0)
        self.pagar_tudo()
        self.assertEqual(self.banco.valor("SELECT codigo_profissional FROM quartos_uso WHERE quarto = 1"), "180")
        self.assertIn("QUARTO 1  →  ANA (180)  ·  1h.  Entregue a chave do 1.", self.j.dialogos.avisos[-1])

    def test_g180q2_escolhe_o_quarto_e_garota_inexistente_avisa(self):
        self.lancar(self.j, "G180Q2")
        self.assertIn("quarto 2", self.j.tabela.item(0, 1).text())
        self.pagar_tudo()
        self.assertEqual(self.banco.valor("SELECT quarto FROM quartos_uso"), 2)
        self.lancar(self.j, "G999")
        self.assertIn("não cadastrada", self.j.lbl_status.text())
        self.assertEqual(self.itens(), [])

    def test_produto_do_quarto_pelo_codigo_pergunta_a_garota(self):
        produto = self.ctx.quartos.produto_quarto()
        self.j.dialogos.textos = ["180"]
        self.lancar(self.j, str(int(produto["codigo"])))
        self.assertEqual(self.itens()[0]["garota_quarto"], 180)
        self.assertIn("Número da garota", self.j.dialogos.perguntas[-1])

    def test_sem_quarto_livre_avisa_e_liberar_oferece_a_fila(self):
        q = self.ctx.quartos
        q.iniciar(1, 1)
        q.iniciar(2, 1)
        self.lancar(self.j, "G180")
        self.pagar_tudo()
        self.assertIn("Sem quarto livre: ANA (180) aguardando", self.j.dialogos.avisos[-1])
        q.liberar(2)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as pergunta:
            self.assertTrue(oferecer_fila(self.j, q, 2))
        self.assertIn("O quarto 2 ficou livre. Iniciar agora para ANA (180)", pergunta.call_args.args[2])
        self.assertEqual(self.banco.valor("SELECT codigo_profissional FROM quartos_uso WHERE quarto = 2 "
                                          "AND liberado_em IS NULL"), "180")
        self.assertFalse(oferecer_fila(self.j, q, 2))                       # fila vazia: não pergunta nada

    def test_so_a_letra_q_numero_da_garota_e_quarto(self):
        self.lancar(self.j, "180Q2")
        self.assertEqual((self.itens()[0]["garota_quarto"], self.itens()[0]["quarto_pedido"]), (180, 2))
        self.lancar(self.j, "180q")
        self.assertEqual((self.itens()[1]["garota_quarto"], self.itens()[1]["quarto_pedido"]), (180, None))
        self.lancar(self.j, "2*180 Q 1")                              # 2 blocos = 1h, quarto 1
        self.assertEqual((self.itens()[2]["quantidade"], self.itens()[2]["quarto_pedido"]), (2, 1))

    def test_so_o_numero_da_garota_lanca_o_quarto(self):
        self.lancar(self.j, "180")
        self.assertEqual((self.itens()[0]["garota_quarto"], self.itens()[0]["quarto_pedido"]), (180, None))
        self.lancar(self.j, "2*180")
        self.assertEqual(self.itens()[0]["quantidade"], 3)                      # somou na mesma linha: 1h30
        self.lancar(self.j, "101")                                    # produto continua produto
        self.assertEqual(self.itens()[1]["garota_quarto"], None)
        self.pagar_tudo()
        self.assertIn("ANA (180)  ·  1h30", self.j.dialogos.avisos[-1])

    def test_a_partir_de_100_a_garota_vence_o_produto_e_abaixo_e_produto(self):
        self.novo_produto("CHARUTO", 2000, codigo="180")
        self.lancar(self.j, "180")
        self.assertEqual(self.itens()[0]["garota_quarto"], 180)               # 180 >= 100: garota, sem pergunta
        CadastroController(self.banco).salvar("garotas", {"numero": 51, "nome": "BIA", "ativo": "S"})
        self.novo_produto("AGUA", 300, codigo="51")
        self.lancar(self.j, "51")
        self.assertEqual(self.itens()[1]["garota_quarto"], None)              # abaixo de 100: produto
        self.banco.cfg_set("quartos_garota_minimo", "200")
        self.lancar(self.j, "180")
        self.assertEqual(self.itens()[2]["garota_quarto"], None)              # mínimo mudou: 180 virou produto
        self.assertEqual(self.j.dialogos.perguntas, [])

    def test_repetir_o_numero_soma_meia_hora_na_mesma_linha(self):
        self.lancar(self.j, "180")
        self.lancar(self.j, "101")
        self.lancar(self.j, "180")
        linhas = [i for i in self.itens() if i["garota_quarto"] == 180]
        self.assertEqual([(i["quantidade"], i["total_cent"]) for i in linhas], [(2, 18000)])
        self.assertIn("ANA (180): agora 1h", self.j.lbl_status.text())
        self.pagar_tudo()
        self.assertIn("ANA (180)  ·  1h", self.j.dialogos.avisos[-1])
        self.assertEqual(self.ctx.comissoes.quantidade_shows_quartos(180), 2)

    def test_com_quartos_desligado_g180_e_so_texto_de_busca(self):
        self.banco.cfg_set("usar_quartos", "N")
        self.lancar(self.j, "G180")
        self.assertEqual(self.itens(), [])
