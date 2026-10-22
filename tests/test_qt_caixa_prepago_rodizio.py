"""Caixa Qt: rodízio e recarga do pré-pago pelos métodos do CaixaController, com módulos ligados/desligados."""
from src.core import formatacao as fmt
from tests.test_qt_caixa import BaseCaixaQt


class TestCaixaQtPrepagoRodizio(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.abrir_turno()
        self.cerveja = self.novo_produto("CERVEJA", 800, codigo="71")
        for chave in ("usar_rodizio", "usar_prepago"):
            self.banco.cfg_set(chave, "1")
        self.banco.cfg_set("valor_rodizio_pessoa", "50,00")
        self.j = self.janela()

    def chamar(self, pos="M1"):
        self.j.ent_pos.setText(pos)
        self.j.btn_chamar.click()
        return self.j.venda_id

    def acao(self, chave, textos=(), escolhas=(), confirmacoes=()):
        self.j.dialogos.textos = list(textos)
        self.j.dialogos.escolhas = list(escolhas)
        self.j.dialogos.confirmacoes = list(confirmacoes)
        self.j.acoes[chave].trigger()

    def venda(self, vid):
        return dict(self.banco.um("SELECT * FROM vendas WHERE id = ?", (vid,)))

    def test_acoes_seguem_os_modulos(self):
        self.j.recarregar()
        self.assertTrue(self.j.acoes["rodizio"].isVisible())
        self.assertTrue(self.j.acoes["recarga"].isVisible())
        self.banco.cfg_set("usar_rodizio", "0")
        self.banco.cfg_set("usar_prepago", "0")
        self.j.recarregar()
        self.assertFalse(self.j.acoes["rodizio"].isVisible())
        self.assertFalse(self.j.acoes["recarga"].isVisible())
        vid = self.chamar()
        self.j.rodizio()                                          # módulo desligado: nada é perguntado
        self.j.recarga()
        self.assertEqual(self.venda(vid)["rodizio"], 0)
        self.assertEqual(self.ctx.caixa.pagamentos(vid), [])

    def test_rodizio_liga_valida_e_desliga(self):
        self.acao("rodizio")                                      # no balcão: pede para chamar a mesa
        self.assertIn("Chame uma mesa", self.j.dialogos.avisos[-1])
        vid = self.chamar()
        self.lancar(self.j, "71", "1")
        self.acao("rodizio", textos=["0", "abc", "2"])             # ligado com 1 a 999 pessoas
        self.assertEqual(len(self.j.dialogos.avisos), 3)
        v = self.venda(vid)
        self.assertEqual((v["rodizio"], v["pessoas"]), (1, 2))
        self.assertIn("Rodízio: 2 pessoa(s)", self.j.lbl_detalhe.text())
        self.assertIn("Rodízio: 2", self.j.lbl_status.text())
        self.acao("rodizio", textos=["0"])                        # ligado: 0 desliga
        self.assertEqual(self.venda(vid)["rodizio"], 0)
        self.assertNotIn("Rodízio", self.j.lbl_detalhe.text())

    def test_recarga_mostra_saldo_e_fecha_devolvendo_a_sobra(self):
        vid = self.chamar("C5")
        self.acao("recarga", textos=["30,00"], escolhas=[self.tipo("Dinheiro")])
        self.assertEqual(self.ctx.caixa.saldo_prepago(vid)["saldo"], 3000)
        self.assertEqual(self.j.lbl_troco.text(), "30,00")
        self.assertIn("Pré-pago", self.j.lbl_venda.text())
        self.lancar(self.j, "71", "1")
        saldo = self.ctx.caixa.saldo_prepago(vid)["saldo"]
        self.assertTrue(0 < saldo < 3000)                         # consumo com serviço da casa
        self.assertEqual(self.j.lbl_troco.text(), fmt.fmt_num(saldo))
        self.lancar(self.j, "71", "3")                            # passaria do crédito: o controlador recusa
        self.assertTrue(any("Crédito insuficiente" in e for e in self.j.dialogos.erros))
        self.assertEqual(self.ctx.caixa.saldo_prepago(vid)["saldo"], saldo)
        self.j.dialogos.confirmacoes = [True]
        self.j.fechar_venda()
        v = self.venda(vid)
        self.assertEqual(v["status"], "fechada")
        self.assertEqual(v["troco_cent"], saldo)                   # recarga em dinheiro: a sobra sai como troco

    def test_recarga_por_pix_confirma_devolucao_e_desistencia(self):
        vid = self.chamar("C6")
        self.acao("recarga", textos=["20,00"], escolhas=[None])   # desistiu na forma: nada gravado
        self.assertEqual(self.ctx.caixa.pagamentos(vid), [])
        self.acao("recarga", textos=["20,00"], escolhas=[self.tipo("Pix")])
        self.assertTrue(self.j.btn_fechar_venda.isEnabled())      # pré-pago sem consumo também fecha
        self.j.dialogos.confirmacoes = [False]
        self.j.fechar_venda()
        self.assertEqual(self.venda(vid)["status"], "aberta")
        self.assertIn("devolva R$ 20,00", self.j.dialogos.perguntas[-1])
        self.j.dialogos.confirmacoes = [True]
        self.j.fechar_venda()
        self.assertEqual(self.venda(vid)["status"], "fechada")
        self.assertEqual(self.banco.valor("SELECT valor_cent FROM movimentos_caixa WHERE tipo = 'saida'"), 2000)

    def test_atalhos_explicitos(self):
        from PySide6.QtGui import QShortcut
        teclas = {a.key().toString() for a in self.j.findChildren(QShortcut)}
        self.assertTrue({"Ctrl+R", "Ctrl+Shift+P"} <= teclas)

    def test_pedido_remoto_vai_ao_setor_do_subgrupo(self):
        from unittest.mock import patch
        with patch.object(self.ctx.impressao, "pedido_remoto", return_value={"COZINHA": "texto"}), \
                patch.object(self.ctx.impressao, "setor_do_subgrupo", return_value=7) as setor, \
                patch.object(self.ctx.impressao, "enviar_remoto") as enviar:
            self.lancar(self.j, "71", "1")
        setor.assert_called_with("COZINHA")
        enviar.assert_called_with("texto", "pedido_COZINHA", setor=7)
