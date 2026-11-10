"""Pedido QR de mesa: conta existente, reenvio, limites e rollback."""
import os
from unittest.mock import patch
from fastapi import HTTPException
from src.core import edicao
from src.core.erros import ErroNegocio
from src.controllers.entrega_controller import EntregaController
from src.controllers.pedido_online_controller import PedidoOnlineController
from backend.pedido_online import montar_pedido
from tests.test_caixa import BaseCaixa


class TestePedidoMesa(BaseCaixa):
    def setUp(self):
        super().setUp()
        contexto = patch.dict(os.environ, {"PDV_EDICAO": "willrestaurante"})
        contexto.start()
        self.addCleanup(contexto.stop)
        edicao.preparar(self.banco)
        self.ctrl = PedidoOnlineController(self.banco, self.caixa, EntregaController(self.banco, self.caixa),
                                           self.prod, self.adm)
        self.codigo = str(int(self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (self.skol,))))

    def pedido(self, uid=100, **extra):
        return {"id": uid, "numero": uid, "mesa": 1, "nome": "Ana", "telefone": "11999990000",
                "itens": [{"codigo": self.codigo, "qtd": 1}], **extra}

    def test_reenvio_nao_duplica_e_novo_pedido_soma_na_mesma_mesa(self):
        a = self.ctrl.importar(self.pedido())
        b = self.ctrl.importar(self.pedido())
        c = self.ctrl.importar(self.pedido(101))
        self.assertEqual(a["venda_id"], b["venda_id"])
        self.assertEqual(a["venda_id"], c["venda_id"])
        self.assertTrue(b["ja_existia"])
        self.assertEqual(self.caixa.obter(a["venda_id"])["modalidade"], "mesa")
        self.assertEqual(sum(i["quantidade"] for i in self.caixa.itens(a["venda_id"])), 2)
        self.assertEqual(self.ctrl.ja_importado(100, 100), a["venda_id"])
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM clientes"), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM pedidos_mesa_importados WHERE aviso_ok = 0"), 2)

    def test_item_invalido_desfaz_pedido_inteiro(self):
        antes = self.banco.valor("SELECT COUNT(*) FROM vendas")
        with self.assertRaises(ErroNegocio):
            self.ctrl.importar(self.pedido(itens=[{"codigo": self.codigo, "qtd": 1},
                                                  {"codigo": "999999999999", "qtd": 1}]))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas"), antes)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM pedidos_mesa_importados"), 0)

    def test_mesa_fora_da_faixa_e_edicao_errada_recusam(self):
        with self.assertRaises(ErroNegocio):
            self.ctrl.importar(self.pedido(mesa=100000))
        with patch.dict(os.environ, {"PDV_EDICAO": "willadega"}), self.assertRaises(ErroNegocio):
            self.ctrl.importar(self.pedido())

    def test_cancelamento_da_conta_marca_todos_os_pedidos(self):
        a = self.ctrl.importar(self.pedido())
        self.ctrl.importar(self.pedido(101))
        self.caixa.cancelar_venda(a["venda_id"], "Cliente desistiu")
        estados = self.banco.todos("SELECT aviso, aviso_ok FROM pedidos_mesa_importados")
        self.assertEqual([tuple(r) for r in estados], [("cancelado", 0), ("cancelado", 0)])

    def test_nuvem_mesa_sem_endereco_ou_taxa_e_adega_nao_aceita(self):
        corpo = {"nome": "Ana", "telefone": "11999990000", "mesa": 2,
                 "itens": [{"codigo": "1", "qtd": 1}]}
        catalogo = {"1": {"nome": "Hambúrguer", "preco_cent": 2500}}
        dados = montar_pedido({"mesas": 3, "taxa_padrao_cent": 900}, catalogo, corpo)
        self.assertEqual((dados["mesa"], dados["taxa_cent"], dados["pagamento"]), (2, 0, "na_mesa"))
        with self.assertRaises(HTTPException):
            montar_pedido({"mesas": 0}, catalogo, corpo)
        corpo["mesa"] = True
        with self.assertRaises(HTTPException):
            montar_pedido({"mesas": 3}, catalogo, corpo)


# O fluxo público também precisa provar que a mesa publicada chega ao CaixaController.
from tests.test_pedido_online import BasePedido, _Http
from tests.test_painel_dono import TestClient, TOKENS, cabecalho, nuvem, preparar_lojas


class TestePedidoMesaNaNuvem(BasePedido):
    def setUp(self):
        super().setUp()
        contexto = patch.dict(os.environ, {"PDV_EDICAO": "willrestaurante"})
        contexto.start()
        self.addCleanup(contexto.stop)
        edicao.preparar(self.banco)
        preparar_lojas()
        from backend.pedido_online import PedidoOnline, PedidoOnlineConfig
        with nuvem.SessionLocal() as db:
            db.query(PedidoOnline).delete()
            db.query(PedidoOnlineConfig).delete()
            db.query(nuvem.Loja).filter_by(chave_loja="ADEGA-1").update({"edicao": "willrestaurante"})
            db.commit()
        self.http = TestClient(nuvem.app)
        self.banco.cfg_set("api_url", "http://testserver/v1/sincronizar")
        self.banco.cfg_set("api_token", TOKENS["ADEGA-1"])
        from src.sync import cardapio_envio
        cardapio_envio.enviar(self.banco, _Http(self.http))

    def test_qr_mesa_cliente_nuvem_e_conta_existente(self):
        pagina = self.http.get("/v1/cardapio?loja=ADEGA-1&mesa=1")
        self.assertEqual(pagina.status_code, 200)
        self.assertGreaterEqual(pagina.json()["pedido"]["mesas"], 1)
        corpo = {"loja": "ADEGA-1", "mesa": 1, "nome": "Ana", "telefone": "11999990000",
                 "itens": [{"codigo": self.cod_skol, "qtd": 1}]}
        pedido = self.http.post("/v1/cardapio/pedido", json=corpo)
        self.assertEqual(pedido.status_code, 200, pedido.text)
        self.assertEqual(pedido.json()["total_cent"], 800)
        novos = self.http.get("/v1/pedidos-online", headers=cabecalho()).json()["pedidos"]
        self.assertEqual(novos[0]["mesa"], 1)
        resultado = self.ctrl.importar(novos[0])
        self.assertEqual(self.caixa.obter(resultado["venda_id"])["modalidade"], "mesa")
        self.assertTrue(self.ctrl.importar(novos[0])["ja_existia"])
