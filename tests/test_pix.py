"""Pix integrado (Mercado Pago): cobrança, confirmação, cancelamento e o caixa só recebendo depois do banco."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.controllers.pix_controller import PixController
from src.core.erros import ErroNegocio
from src.pagamentos.mercadopago_pix import Cobranca, MercadoPagoPix
from tests.test_caixa import BaseCaixa
from tests.test_qt_caixa import BaseCaixaQt, QApplication

QR = "00020126580014br.gov.bcb.pix0136chave520400005303986540510.005802BR6304ABCD"
PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class ProvedorFalso:
    def __init__(self):
        self.criadas, self.consultas, self.canceladas = [], [], []
        self.situacao = "pendente"
        self.ao_criar = None
        self.ao_cancelar = "cancelado"

    def criar(self, valor_cent, descricao, referencia, email, expira_min=15):
        self.criadas.append((valor_cent, descricao, referencia, email, expira_min))
        if self.ao_criar is not None:
            return self.ao_criar
        return Cobranca("pendente", "pending_waiting_transfer", "123", QR, PNG)

    def consultar(self, provedor_id):
        self.consultas.append(provedor_id)
        return Cobranca(self.situacao, "", provedor_id)

    def cancelar(self, provedor_id):
        self.canceladas.append(provedor_id)
        return Cobranca(self.ao_cancelar, "", provedor_id)


class BasePix(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("pix_integrado", "S")
        self.banco.executar("UPDATE loja SET email = 'loja@exemplo.com.br', nome_fantasia = 'EMPORIO' WHERE id = 1")
        self.provedor = ProvedorFalso()
        self.pix = PixController(self.banco, provedor=self.provedor)
        self.vid = self.vender((self.skol, 2))           # 16,00

    def falta(self):
        return self.banco.valor("SELECT total_cent FROM vendas WHERE id = ?", (self.vid,))


class TesteCobranca(BasePix):
    def test_so_forma_pix_e_so_ligado(self):
        self.assertTrue(self.pix.usar_no_recebimento(self.tipo("Pix")))
        self.assertFalse(self.pix.usar_no_recebimento(self.tipo("Dinheiro")))
        self.banco.cfg_set("pix_integrado", "N")
        self.assertFalse(self.pix.usar_no_recebimento(self.tipo("Pix")))

    def test_gera_qr_com_o_valor_e_a_referencia(self):
        c = self.pix.iniciar(self.vid, 1600)
        self.assertEqual((c["situacao"], c["provedor_id"], c["copia_cola"], c["imagem_base64"]), ("pendente", "123", QR, PNG))
        valor, descricao, referencia, email, expira = self.provedor.criadas[0]
        self.assertEqual((valor, email, expira), (1600, "loja@exemplo.com.br", 15))
        self.assertIn("EMPORIO", descricao)
        self.assertEqual(referencia, c["referencia"])
        self.assertIsNone(self.banco.um("SELECT id FROM pagamentos_venda WHERE venda_id = ?", (self.vid,)))

    def test_pix_nao_da_troco(self):
        with self.assertRaisesRegex(ErroNegocio, "não dá troco"):
            self.pix.iniciar(self.vid, 2000)
        self.assertEqual(self.provedor.criadas, [])

    def test_sem_email_nao_gera(self):
        self.banco.executar("UPDATE loja SET email = '' WHERE id = 1")
        with self.assertRaisesRegex(ErroNegocio, "e-mail"):
            self.pix.iniciar(self.vid, 1600)
        self.banco.cfg_set("pix_email_pagador", "caixa@exemplo.com.br")
        self.pix.iniciar(self.vid, 1600)
        self.assertEqual(self.provedor.criadas[-1][3], "caixa@exemplo.com.br")

    def test_sem_internet_avisa_e_marca_erro(self):
        self.provedor.ao_criar = Cobranca(None, "Sem conexão com o Mercado Pago (OSError).")
        with self.assertRaisesRegex(ErroNegocio, "Sem internet"):
            self.pix.iniciar(self.vid, 1600)
        self.assertEqual(self.banco.valor("SELECT situacao FROM pix_cobrancas"), "erro")

    def test_aprovado_cancelado_e_pago_antes_de_cancelar(self):
        c = self.pix.iniciar(self.vid, 1600)
        self.assertEqual(self.pix.verificar(c["id"]), "pendente")
        self.provedor.situacao = "aprovado"
        self.assertEqual(self.pix.verificar(c["id"]), "aprovado")
        self.assertIsNotNone(self.pix.obter(c["id"])["aprovada_em"])
        self.assertEqual(self.pix.cancelar(c["id"]), "aprovado")              # pago não volta atrás
        # outra cobrança: o cliente pagou no instante em que o caixa desistiu
        self.provedor.situacao = "pendente"
        d = self.pix.iniciar(self.vid, 1600)
        self.provedor.ao_cancelar = "erro"
        self.provedor.situacao = "aprovado"
        self.assertEqual(self.pix.cancelar(d["id"]), "aprovado")
        # e uma que cancela de verdade
        self.provedor.situacao, self.provedor.ao_cancelar = "pendente", "cancelado"
        e = self.pix.iniciar(self.vid, 1600)
        self.assertEqual(self.pix.cancelar(e["id"]), "cancelado")
        self.assertEqual(self.provedor.canceladas[-1], "123")

    def test_vincular_so_aprovado_e_lista_dos_sem_venda(self):
        c = self.pix.iniciar(self.vid, 1600)
        with self.assertRaisesRegex(ErroNegocio, "aprovado"):
            self.pix.vincular(c["id"], 1)
        self.provedor.situacao = "aprovado"
        self.pix.verificar(c["id"])
        self.assertEqual([x["id"] for x in self.pix.aprovados_sem_pagamento()], [c["id"]])
        pid = self.caixa.adicionar_pagamento(self.vid, self.tipo("Pix"), 1600)
        self.pix.vincular(c["id"], pid)
        self.assertEqual(self.pix.aprovados_sem_pagamento(), [])

    def test_imprime_o_qr_na_fila(self):
        c = self.pix.iniciar(self.vid, 1600)
        self.pix.imprimir_qr(c)
        dados = self.banco.valor("SELECT dados FROM fila_impressao WHERE tipo = 'pix'")
        self.assertIn(QR.encode(), dados)


class TesteMercadoPago(unittest.TestCase):
    def http(self, codigo, corpo):
        chamadas = []

        def chamar(url, **kw):
            chamadas.append((url, kw))
            return SimpleNamespace(status_code=codigo, json=lambda: corpo)
        return SimpleNamespace(post=chamar, get=chamar, put=chamar), chamadas

    def test_criar_monta_o_pedido_e_le_o_qr(self):
        http, chamadas = self.http(201, {"id": 987, "status": "pending", "status_detail": "pending_waiting_transfer",
                                         "point_of_interaction": {"transaction_data": {
                                             "qr_code": QR, "qr_code_base64": PNG}}})
        c = MercadoPagoPix("APP_USR-1", http).criar(1050, "Venda 1", "ref-1", "a@b.com", 15)
        url, kw = chamadas[0]
        self.assertEqual(url, "https://api.mercadopago.com/v1/payments")
        self.assertEqual(kw["headers"]["Authorization"], "Bearer APP_USR-1")
        self.assertEqual(kw["headers"]["X-Idempotency-Key"], "ref-1")
        self.assertEqual(kw["json"]["transaction_amount"], 10.5)
        self.assertEqual((kw["json"]["payment_method_id"], kw["json"]["payer"]), ("pix", {"email": "a@b.com"}))
        self.assertIn("date_of_expiration", kw["json"])
        self.assertEqual((c.situacao, c.provedor_id, c.copia_cola, c.imagem_base64), ("pendente", "987", QR, PNG))

    def test_traducao_dos_status(self):
        casos = [(200, {"status": "approved"}, "aprovado"), (200, {"status": "rejected"}, "cancelado"),
                 (200, {"status": "cancelled", "status_detail": "expired"}, "expirado"),
                 (200, {"status": "in_process"}, "pendente"), (503, {}, None), (401, {}, "erro"),
                 (400, {"message": "payer.email inválido"}, "erro")]
        for codigo, corpo, esperado in casos:
            http, _ = self.http(codigo, corpo)
            self.assertEqual(MercadoPagoPix("T", http).consultar("1").situacao, esperado, corpo)

    def test_cancelar_e_sem_rede(self):
        http, chamadas = self.http(200, {"status": "cancelled"})
        self.assertEqual(MercadoPagoPix("T", http).cancelar("55").situacao, "cancelado")
        self.assertEqual((chamadas[0][0], chamadas[0][1]["json"]),
                         ("https://api.mercadopago.com/v1/payments/55", {"status": "cancelled"}))

        def quebra(*a, **k):
            raise OSError("sem rede")
        self.assertIsNone(MercadoPagoPix("T", SimpleNamespace(get=quebra)).consultar("1").situacao)
        with self.assertRaisesRegex(ValueError, "Access Token"):
            MercadoPagoPix(" ", http)


@unittest.skipIf(QApplication is None, "PySide6 não instalado")
class TesteCaixaComPix(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("pix_integrado", "S")
        self.banco.executar("UPDATE loja SET email = 'loja@exemplo.com.br' WHERE id = 1")
        self.abrir_turno()
        self.novo_produto("SKOL", 800, codigo="10")
        self.j = self.janela()
        self.lancar(self.j, "10")
        self.provedor = ProvedorFalso()
        original = PixController.__init__

        def com_falso(pix, banco, operador_id=None, provedor=None):
            original(pix, banco, operador_id, provedor or self.provedor)
        p = mock.patch.object(PixController, "__init__", com_falso)
        p.start()
        self.addCleanup(p.stop)

    def receber_pix(self):
        self.j.cmb_forma.setCurrentIndex(self.j.cmb_forma.findText("Pix"))
        self.j.ent_valor.setText("8,00")
        self.j.receber()

    def pagamentos(self):
        return self.banco.todos("SELECT * FROM pagamentos_venda WHERE venda_id = ?", (self.j.venda_id,))

    def test_so_recebe_quando_o_banco_confirma(self):
        from src.ui_qt import pix as tela

        def paga(dialogo):
            self.assertTrue(dialogo.qr.pixmap() is not None and not dialogo.qr.pixmap().isNull())
            self.assertEqual(self.pagamentos(), [])          # QR na tela, nada recebido ainda
            self.assertEqual(dialogo.conferir(), "pendente")
            self.provedor.situacao = "aprovado"
            dialogo.conferir()
            return dialogo.result()

        with mock.patch.object(tela.DialogoPix, "exec", paga):
            self.receber_pix()
        self.assertEqual(len(self.pagamentos()), 1)
        self.assertEqual(self.banco.valor("SELECT pagamento_id FROM pix_cobrancas"), self.pagamentos()[0]["id"])

    def test_desistir_nao_recebe_e_cancela_no_mercado_pago(self):
        from src.ui_qt import pix as tela

        def desiste(dialogo):
            dialogo.reject()
            return dialogo.result()

        with mock.patch.object(tela.DialogoPix, "exec", desiste):
            self.receber_pix()
        self.assertEqual(self.pagamentos(), [])
        self.assertEqual(self.provedor.canceladas, ["123"])
        self.assertEqual(self.banco.valor("SELECT situacao FROM pix_cobrancas"), "cancelado")

    def test_sem_internet_avisa_e_nao_recebe(self):
        self.provedor.ao_criar = Cobranca(None, "Sem conexão com o Mercado Pago (OSError).")
        self.receber_pix()
        self.assertEqual(self.pagamentos(), [])
        self.assertTrue(any("Sem internet" in str(a) for a in self.j.dialogos.avisos))

    def test_desligado_recebe_como_sempre(self):
        self.banco.cfg_set("pix_integrado", "N")
        self.receber_pix()
        self.assertEqual(len(self.pagamentos()), 1)
        self.assertEqual(self.provedor.criadas, [])


if __name__ == "__main__":
    unittest.main()
