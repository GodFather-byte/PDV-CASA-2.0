"""Pedido online no caixa Qt (Will Adega): o botão acende com pedido novo; aceitar vira entrega e recusar avisa a nuvem."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock

from tests.test_qt_caixa import BaseCaixaQt, QApplication

if QApplication is not None:
    from src.controllers.perfil_controller import PerfilController


class TestePedidoOnlineNoCaixa(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        edicao = mock.patch.dict(os.environ, {"PDV_EDICAO": "willadega"})
        edicao.start()
        self.addCleanup(edicao.stop)
        PerfilController(self.banco, self.ctx.operador_id).aplicar("adega")
        for chave, valor in (("pedido_online", "S"), ("pedido_online_whatsapp", "11987654321"), ("cardapio_digital", "S"),
                             ("usar_delivery", "S"), ("api_url", "https://nuvem.exemplo/v1/sincronizar"),
                             ("api_token", "tk")):
            self.banco.cfg_set(chave, valor)
        self.abrir_turno()
        self.skol = self.novo_produto("SKOL", 450, codigo="101")
        self.na_nuvem = [{"id": 31, "numero": 5, "nome": "Maria", "telefone": "11955550000", "retirada": False,
                          "endereco": "Rua B, 20", "bairro": "", "pagamento": "pix", "troco_para_cent": 0,
                          "observacao": "", "itens": [{"codigo": "101", "nome": "SKOL", "qtd": 12}],
                          "total_cent": 5400}]
        self.respostas = []
        rede = "src.ui_qt.pedidos_online.rede."
        for nome, falso in (("consultar", lambda base, token, http=None: list(self.na_nuvem)),
                            ("aceitar", lambda banco, pid, http=None: self.respostas.append(("aceitar", pid))),
                            ("recusar", lambda banco, pid, motivo, http=None: self.respostas.append(("recusar", pid,
                                                                                                    motivo)))):
            p = mock.patch(rede + nome, side_effect=falso)
            p.start()
            self.addCleanup(p.stop)
        bip = mock.patch("src.ui_qt.pedidos_online.QApplication.beep")
        self.bip = bip.start()
        self.addCleanup(bip.stop)
        self.j = self.janela()
        self.j.vigia_pedidos.timer.stop()

    def test_botao_acende_aceitar_vira_entrega_e_avisa_a_nuvem(self):
        v = self.j.vigia_pedidos
        self.assertTrue(self.j.btn_pedidos_online.isVisibleTo(self.j))
        v.buscar(sincrono=True)
        self.assertEqual(self.j.btn_pedidos_online.text(), "🛵 1 pedido online")
        self.assertEqual(self.bip.call_count, 1)
        self.assertIn("Pedido online novo: #5 · Maria", self.j.lbl_status.text())
        v.buscar(sincrono=True)
        self.assertEqual(self.bip.call_count, 1)                             # o mesmo pedido não apita de novo
        self.j.dialogos.escolhas = [31, "aceitar"]
        self.j.btn_pedidos_online.click()
        venda = self.j.venda()
        self.assertEqual((venda["modalidade"], venda["total_cent"]), ("entrega", 12 * 450 + venda["taxa_cent"]))
        self.assertIn("Pedido online #5", venda["mensagem"])
        self.assertEqual(self.respostas, [("aceitar", 31)])
        self.assertEqual(self.j.btn_pedidos_online.text(), "🛵 Pedidos online")
        self.respostas.clear()
        v.buscar(sincrono=True)                                              # a nuvem ainda o lista: só reavisa
        self.assertEqual((self.respostas, v.pedidos), ([("aceitar", 31)], []))

    def test_recusar_com_motivo(self):
        self.j.vigia_pedidos.buscar(sincrono=True)
        self.j.dialogos.escolhas = [31, "recusar"]
        self.j.dialogos.textos = ["Acabou a Skol"]
        self.j.btn_pedidos_online.click()
        self.assertEqual(self.respostas, [("recusar", 31, "Acabou a Skol")])
        self.assertIsNone(self.j.venda_id)
        self.assertIn("#5 recusado", self.j.lbl_status.text())

    def test_some_fora_do_will_adega_ou_desligado(self):
        with mock.patch.dict(os.environ, {"PDV_EDICAO": "willpdv"}):
            self.j.vigia_pedidos.buscar(sincrono=True)
            self.assertFalse(self.j.btn_pedidos_online.isVisibleTo(self.j))
        self.banco.cfg_set("pedido_online", "N")
        self.j.vigia_pedidos.buscar(sincrono=True)
        self.assertFalse(self.j.btn_pedidos_online.isVisibleTo(self.j))
