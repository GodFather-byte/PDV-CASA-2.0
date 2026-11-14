"""Consumo da garota: lançado na comanda dela (código numérico das Configurações, preço digitado, em vermelho) e descontado no acerto."""
from unittest.mock import patch

from src.controllers.comissao_controller import ComissaoController
from src.controllers.config_controller import ConfigController
from src.controllers.impressao_controller import ImpressaoController
from src.core.erros import ErroNegocio, ErroValidacao
from tests.test_caixa import BaseCaixa
from tests.test_qt_caixa import BaseCaixaQt


class TestDrinksGarota(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.com = ComissaoController(self.banco)

    def drink(self, garota=180, cent=1500):
        return self.com.lancar_consumo(garota, cent, self.turno, self.adm)

    def saidas(self, tipo="saida"):
        return [dict(r) for r in self.banco.todos("SELECT * FROM movimentos_caixa WHERE tipo = ?", (tipo,))]

    def test_desligado_de_fabrica_e_numerico_nas_configuracoes(self):
        self.assertEqual(self.com.codigo_consumo(), "")
        self.assertFalse(self.com.eh_codigo_consumo("49"))
        with self.assertRaisesRegex(ErroValidacao, "só números"):
            ConfigController(self.banco).salvar_config({"codigo_consumo_garota": "D"})
        ConfigController(self.banco).salvar_config({"codigo_consumo_garota": "049"})
        self.assertEqual(self.com.codigo_consumo(), "49")
        self.assertTrue(self.com.eh_codigo_consumo(" 0049 "))
        self.assertFalse(self.com.eh_codigo_consumo("50"))
        self.banco.cfg_set("usar_garotas", "N")
        self.assertFalse(self.com.eh_codigo_consumo("49"))

    def test_codigo_igual_ao_da_comissao_e_recusado(self):
        with self.assertRaisesRegex(ErroValidacao, "mesmo código"):
            ConfigController(self.banco).salvar_config({"codigo_consumo_garota": "50"})

    def test_lanca_e_cancela(self):
        did = self.drink(cent=1200)
        self.drink(cent=800)
        self.assertEqual(self.com.consumo_pendente(180), 2000)
        self.com.cancelar_consumo(did, self.adm, "errado")
        self.assertEqual(self.com.consumo_pendente(180), 800)
        with self.assertRaises(ErroNegocio):
            self.com.cancelar_consumo(did, self.adm)
        with self.assertRaises(ErroNegocio):
            self.com.lancar_consumo(180, 0, self.turno, self.adm)

    def test_acerto_desconta_os_drinks_e_tira_so_o_que_ela_recebe(self):
        self.com.lancar(180, 10000, self.turno, self.adm)             # R$ 100,00 de comissão
        self.drink(cent=1500)
        self.drink(cent=1000)                                        # R$ 25,00 em drinks
        pag = self.com.pagar(180, self.turno, self.adm, tirar_do_caixa=True, vale_cent=2000)
        self.assertEqual((pag["total_cent"], pag["consumo_cent"], pag["dinheiro_cent"]), (10000, 2500, 5500))
        saida = self.saidas()[0]
        self.assertEqual(saida["valor_cent"], 5500)
        self.assertIn("consumo descontado: R$ 25,00", saida["descricao"])
        self.assertEqual(self.com.consumo_pendente(180), 0)
        acerto = self.banco.um("SELECT * FROM acertos_garotas WHERE id = ?", (pag["acerto_id"],))
        self.assertEqual(acerto["consumo_cent"], 2500)
        self.assertEqual(self.com.consumos_do_turno(self.turno)["total_cent"], 2500)
        recibo = ImpressaoController(self.banco).recibo_comissao(pag, "ADM")
        self.assertIn("Consumo (2) descontado", recibo)

    def test_drinks_alem_da_comissao_ela_paga_a_diferenca_ao_caixa(self):
        self.com.lancar(180, 2000, self.turno, self.adm)
        self.drink(cent=3500)
        with self.assertRaises(ErroNegocio):                         # não há o que pagar por Pix
            self.com.pagar(180, self.turno, self.adm, tirar_do_caixa=True, pix_cent=100)
        pag = self.com.pagar(180, self.turno, self.adm, tirar_do_caixa=True)
        self.assertEqual((pag["dinheiro_cent"], pag["recebido_cent"], pag["tirou_do_caixa"]), (0, 1500, False))
        self.assertTrue(pag["recebeu_no_caixa"])
        self.assertEqual(self.saidas(), [])
        self.assertEqual(self.saidas("entrada")[0]["valor_cent"], 1500)
        self.assertIn("ELA PAGOU AO CAIXA", ImpressaoController(self.banco).recibo_comissao(pag, "ADM"))

    def test_so_drinks_tambem_fecha_o_acerto(self):
        self.drink(cent=1000)
        pag = self.com.pagar(180, self.turno, self.adm, tirar_do_caixa=False)
        self.assertEqual((pag["recebido_cent"], pag["recebeu_no_caixa"]), (1000, False))
        self.assertEqual(self.saidas("entrada"), [])

    def test_drinks_que_mudaram_depois_de_abrir_o_acerto_recusam(self):
        primeiro = self.drink()
        self.com.lancar(180, 5000, self.turno, self.adm)
        self.drink()
        with self.assertRaisesRegex(ErroNegocio, "consumo da garota mudou"):
            self.com.pagar(180, self.turno, self.adm, consumos_ids=[primeiro])
        self.assertEqual(self.com.consumo_pendente(180), 3000)


class TestDrinksGarotaQt(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.turno = self.abrir_turno()
        self.banco.cfg_set("imprimir_via_comissao", "N")
        self.banco.cfg_set("comissao_pede_shows", "N")
        self.banco.cfg_set("num_comandas", "300")
        self.banco.cfg_set("posicao_padrao", "comanda")
        self.banco.cfg_set("codigo_consumo_garota", "49")

    def comanda(self, j, numero="180"):
        j.ent_pos.setText(numero)
        j.btn_chamar.click()
        self.assertIsNotNone(j.venda_id)

    def test_codigo_lanca_o_consumo_na_comanda_em_vermelho(self):
        from src.ui_qt.caixa import LINHAS_CONSUMO
        j = self.janela()
        self.comanda(j)
        j.ent_codigo.setText("49")
        j.lancar_item(pedir_quantidade=True)
        self.assertTrue(j.modo_comissao)
        self.assertEqual(j.lancando, "consumo")
        self.assertEqual(j.ent_codigo.text(), "180")
        j.ent_qtd.setText("12,00")
        j.lancar_item()
        self.assertEqual(self.ctx.comissoes.consumo_pendente(180), 1200)
        self.assertFalse(j.modo_comissao)
        self.assertEqual(self.contar("itens_venda"), 0)                 # não é venda nem estoque
        linhas = [j.tabela.item(i, 1).text() for i in range(j.tabela.rowCount())]
        self.assertIn("CONSUMO (descontar)", linhas)
        celula = j.tabela.item(linhas.index("CONSUMO (descontar)"), 1)
        self.assertEqual(celula.foreground().color().name(), LINHAS_CONSUMO[j._modo_visual()][2])
        self.assertIn("Consumo dela: - R$ 12,00", j.lbl_aviso_venda.text())

    def test_esc_descarta_e_cancelar_item_cancela_o_drink(self):
        j = self.janela()
        self.comanda(j)
        j.ent_codigo.setText("049")
        j.lancar_item(pedir_quantidade=True)
        j.cancelar_modo_comissao()
        self.assertEqual(self.contar("consumos_garotas"), 0)
        self.ctx.comissoes.lancar_consumo(180, 900, self.turno, self.ctx.operador_id)
        j.recarregar()
        linha = next(i for i in range(j.tabela.rowCount()) if j.tabela.item(i, 1).text().startswith("CONSUMO"))
        j.tabela.setCurrentCell(linha, 1)
        with patch.object(j.dialogos, "confirmar", return_value=True):
            j.cancelar_item()
        self.assertEqual(self.ctx.comissoes.consumo_pendente(180), 0)

    def test_acerto_real_mostra_e_desconta_os_drinks(self):
        from src.ui_qt.comissao import DialogoAcerto
        self.ctx.comissoes.lancar(180, 5000, self.turno, self.ctx.operador_id)
        self.ctx.comissoes.lancar_consumo(180, 2000, self.turno, self.ctx.operador_id)
        j = self.janela()
        dlg = DialogoAcerto(j, self.ctx, 180, "", 5000, 1)
        self.addCleanup(dlg.close)
        self.assertEqual(dlg.lbl_total.text(), "R$ 30,00")
        dlg.ent_vale.setText("40,00")
        dlg.calcular()
        self.assertEqual(dlg.lbl_total.text(), "ELA PAGA AO CAIXA R$ 10,00")
        dlg.ent_vale.setText("")
        dlg.confirmar()
        self.assertEqual(len(dlg.resultado["consumos_ids"]), 1)
