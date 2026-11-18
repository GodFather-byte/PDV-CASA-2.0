"""Pedido do Insta-BDelivery no caixa Qt: aparece no mesmo botão, vira entrega e a resposta volta para a vitrine."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import test_qt_pedido_online as base
from tests.test_qt_caixa import QApplication

if QApplication is not None:
    from src.sync import insta_bdelivery as insta


class TestePedidoDaVitrineNoCaixa(base.TestePedidoOnlineNoCaixa):
    """Só a vitrine ligada: o que a busca devolve vem marcado como Insta, com o id negativo."""

    def setUp(self):
        super().setUp()
        self.banco.cfg_set("api_token", "")                              # sem o canal da nuvem
        self.banco.cfg_set(insta.CHAVE_URL, "https://vitrine.exemplo/api/pdv")
        self.banco.cfg_set(insta.CHAVE_TOKEN, "ibd_chave")
        self.j.vigia_pedidos._mostrar()

    def test_botao_acende_aceitar_vira_entrega_e_avisa_a_nuvem(self):
        v = self.j.vigia_pedidos
        self.assertTrue(self.j.btn_pedidos_online.isVisibleTo(self.j))
        v.buscar(sincrono=True)
        self.assertEqual(self.j.btn_pedidos_online.text(), "🛵 1 pedido online")
        self.assertIn("Pedido online novo: Insta #5 · Maria", self.j.lbl_status.text())
        self.assertEqual([p["id"] for p in v.pedidos], [-5])
        self.j.dialogos.escolhas = [-5, "aceitar"]
        self.j.btn_pedidos_online.click()
        venda = self.banco.um("SELECT * FROM vendas WHERE mensagem LIKE 'Pedido Insta #5 ·%'")
        self.assertEqual((venda["modalidade"], venda["forma_online"], venda["pedido_online_id"]), ("entrega", "pix", -5))
        self.assertEqual(self.respostas, [("aceitar", -5)])
        self.assertEqual(venda["pedido_online_aviso_ok"], 1)
        self.assertEqual(self.j.btn_pedidos_online.text(), "🛵 Pedidos online")
        v.buscar(sincrono=True)                                          # a vitrine ainda lista: o caixa avisa de novo
        self.assertEqual(self.respostas[-1], ("aceitar", -5))
        self.assertEqual(v.pedidos, [])

    def test_recusar_manda_o_motivo_para_a_vitrine(self):
        self.j.vigia_pedidos.buscar(sincrono=True)
        self.j.dialogos.escolhas = [-5, "recusar"]
        self.j.dialogos.textos = ["Acabou"]
        self.j.btn_pedidos_online.click()
        self.assertEqual(self.respostas, [("recusar", -5, "Acabou")])
        self.assertIn("Pedido Insta #5 recusado", self.j.lbl_status.text())


# Daqui só interessa a preparação da classe base; os testes dela (canal da nuvem, mesa) rodam no módulo deles.
for _nome in dir(base.TestePedidoOnlineNoCaixa):
    if _nome.startswith("test_") and _nome not in TestePedidoDaVitrineNoCaixa.__dict__:
        setattr(TestePedidoDaVitrineNoCaixa, _nome, None)
del base
