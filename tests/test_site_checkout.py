"""Checkout Pro do site: preço no servidor, Pix e cartão, webhook que confere na API."""
from __future__ import annotations

import copy
import hashlib
import hmac
import os
import time
import unittest
from decimal import Decimal
from unittest import mock

from tests.test_nuvem import TestClient, nuvem

try:
    from backend import cobranca_mercadopago as cobranca
    from backend import site_checkout as checkout
    from backend import site_precos
except (ImportError, RuntimeError):
    checkout = cobranca = None


def assinar(data_id, request_id="req-site-01", segredo="segredo-do-webhook", ts=None):
    ts = str(int(time.time()) if ts is None else ts)
    manifesto = f"id:{str(data_id).lower()};request-id:{request_id};ts:{ts};"
    v1 = hmac.new(segredo.encode(), manifesto.encode(), hashlib.sha256).hexdigest()
    return {"x-signature": f"ts={ts},v1={v1}", "x-request-id": request_id}


PRECOS = {
    "adega-mensal": (Decimal("90.00"), 9_000, 1),
    "adega-anual": (Decimal("900.00"), 90_000, 10),
    "restaurante-mensal": (Decimal("149.99"), 14_999, 1),
    "restaurante-anual": (Decimal("1499.90"), 149_990, 10),
    "variedades-mensal": (Decimal("159.99"), 15_999, 1),
    "variedades-anual": (Decimal("1599.90"), 159_990, 10),
    "hotel-mensal": (Decimal("199.99"), 19_999, 1),
    "hotel-anual": (Decimal("1999.90"), 199_990, 10),
    "boate-mensal": (Decimal("249.99"), 24_999, 1),
    "boate-anual": (Decimal("2499.90"), 249_990, 10),
}


@unittest.skipIf(TestClient is None or checkout is None, "fastapi/httpx não instalados")
class TesteCheckoutSite(unittest.TestCase):
    def setUp(self):
        self.ambiente = mock.patch.dict(os.environ, {
            "MP_ACCESS_TOKEN": "TEST-token-ficticio",
            "MP_WEBHOOK_SECRET": "",
            "PUBLIC_BASE_URL": "",
            "RENDER_EXTERNAL_URL": "",
            "MP_VARREDURA": "0",
        })
        self.ambiente.start()
        self.addCleanup(self.ambiente.stop)
        self.http = TestClient(nuvem.app)
        self.chamadas = []
        self.quebrar = False
        self.pagamento = {
            "id": 555, "status": "approved", "transaction_amount": Decimal("90.00"),
            "currency_id": "BRL", "external_reference": "",
        }
        self.consulta = mock.patch.object(cobranca, "requisitar", side_effect=self.fake)
        self.consulta.start()
        self.addCleanup(self.consulta.stop)
        self.limpar()
        self.addCleanup(self.limpar)

    def limpar(self):
        with nuvem.SessionLocal() as db:
            db.query(checkout.PagamentoSite).delete()
            db.query(checkout.Pedido).delete()
            db.commit()

    def fake(self, metodo, caminho, corpo=None, idempotencia=None):
        self.chamadas.append({"metodo": metodo, "caminho": caminho, "corpo": corpo,
                              "idempotencia": idempotencia})
        if self.quebrar:
            raise cobranca.MercadoPagoIndisponivel("indisponível")
        if metodo == "POST" and caminho == "/checkout/preferences":
            return {
                "id": "pref-site-1",
                "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=pref-site-1",
                "sandbox_init_point": "https://sandbox.mercadopago.com.br/checkout/v1/redirect?pref_id=pref-site-1",
            }
        if metodo == "GET" and caminho.startswith("/merchant_orders/"):
            return {"id": 900, "payments": [{"id": 555, "status": "refunded", "transaction_amount": 1}]}
        if metodo == "GET" and caminho.startswith("/v1/payments/"):
            dados = copy.deepcopy(self.pagamento)
            pid = caminho.rsplit("/", 1)[-1]
            dados["id"] = int(pid) if pid.isdigit() else pid
            return dados
        raise AssertionError((metodo, caminho))

    def comprar(self, plano="adega-mensal", **extra):
        corpo = {"plano": plano, "nome": "Maria Silva", "email": "maria@exemplo.com",
                 "whatsapp": "(11) 91234-5678", "loja": "Adega da Maria",
                 "valor": 1, "preco": 1, "unit_price": 0.01, "valor_cent": 1, "parcelas": 1,
                 "instalacao": 5000}
        corpo.update(extra)
        return self.http.post("/v1/pagamentos/checkout", json=corpo)

    def preferencia(self):
        return next(c for c in self.chamadas if c["caminho"] == "/checkout/preferences")

    def pedido(self, pedido_id):
        with nuvem.SessionLocal() as db:
            linha = db.get(checkout.Pedido, pedido_id)
            db.expunge(linha)
            return linha

    def notificar(self, data_id="555", tipo="payment", headers=None, corpo=None, **params):
        consulta = {"data.id": data_id, "type": tipo}
        consulta.update(params)
        return self.http.post("/v1/pagamentos/webhook", params=consulta, headers=headers or {},
                              json=corpo if corpo is not None else {
                                  "status": "approved", "transaction_amount": 1, "data": {"id": "1"}})

    def test_precos_e_parcelas_sao_do_servidor(self):
        self.assertEqual(set(checkout.PLANOS), set(PRECOS))
        for plano, (reais, centavos, parcelas) in PRECOS.items():
            self.chamadas.clear()
            r = self.comprar(plano, valor=1, parcelas=99)
            self.assertEqual(r.status_code, 200, r.text)
            corpo = r.json()
            self.assertEqual(corpo["valor_cent"], centavos)
            self.assertEqual(corpo["plano"], plano)
            self.assertTrue(corpo["init_point"].startswith("https://sandbox.mercadopago.com.br/"))
            self.assertNotIn("TEST-token-ficticio", r.text)
            pref = self.preferencia()["corpo"]
            self.assertEqual(len(pref["items"]), 1)
            self.assertEqual(pref["items"][0]["unit_price"], reais)
            self.assertEqual(pref["items"][0]["currency_id"], "BRL")
            self.assertEqual(pref["items"][0]["quantity"], 1)
            self.assertIsInstance(pref["items"][0]["unit_price"], Decimal)
            self.assertEqual(pref["payment_methods"]["installments"], parcelas)
            self.assertEqual(pref["payment_methods"]["default_installments"], 1)
            excluidos = {item["id"] for item in pref["payment_methods"]["excluded_payment_types"]}
            self.assertEqual(excluidos, {"ticket", "atm"})
            self.assertEqual(pref["auto_return"], "approved")
            self.assertEqual(pref["back_urls"]["success"], site_precos.URL_PUBLICA + "/site/obrigado")
            self.assertEqual(pref["back_urls"]["pending"], site_precos.URL_PUBLICA + "/site/pagamento-pendente")
            self.assertEqual(pref["back_urls"]["failure"], site_precos.URL_PUBLICA + "/site/pagamento-falhou")
            self.assertEqual(pref["notification_url"], site_precos.URL_PUBLICA + "/v1/pagamentos/webhook")
            self.assertEqual(pref["external_reference"], corpo["pedido"])
            self.assertEqual(pref["payer"]["email"], "maria@exemplo.com")
            self.assertEqual(pref["payer"]["phone"], {"area_code": "11", "number": "912345678"})
            self.assertNotIn("valor", pref)
            self.assertNotIn(1, (pref["items"][0]["unit_price"],))
            guardado = self.pedido(corpo["pedido"])
            self.assertEqual((guardado.plano, guardado.valor_cent, guardado.status, guardado.whatsapp),
                             (plano, centavos, "aguardando", "5511912345678"))
            self.assertEqual(guardado.loja, "Adega da Maria")
            self.assertRegex(guardado.criado_em, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
            self.assertEqual(self.preferencia()["idempotencia"], corpo["pedido"])

    def test_base_publica_e_token_de_producao(self):
        with mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://loja.exemplo.com"}):
            r = self.comprar("boate-anual")
        self.assertEqual(r.status_code, 200, r.text)
        pref = self.preferencia()["corpo"]
        self.assertEqual(pref["back_urls"]["success"], "https://loja.exemplo.com/site/obrigado")
        self.assertEqual(pref["items"][0]["unit_price"], Decimal("2499.90"))
        self.assertEqual(pref["payment_methods"]["installments"], 10)
        self.chamadas.clear()
        with mock.patch.dict(os.environ, {
                "PUBLIC_BASE_URL": "http://inseguro.exemplo",
                "RENDER_EXTERNAL_URL": "https://willpdv-nuvem-6sp0.onrender.com"}):
            self.assertEqual(checkout.base_publica(), "https://willpdv.com.br")
            self.assertEqual(site_precos.URL_PUBLICA, "https://willpdv.com.br")
        self.chamadas.clear()
        with mock.patch.dict(os.environ, {
                "PUBLIC_BASE_URL": "",
                "RENDER_EXTERNAL_URL": "https://willpdv-nuvem-6sp0.onrender.com"}):
            r = self.comprar("adega-mensal")
        self.assertEqual(r.status_code, 200, r.text)
        pref = self.preferencia()["corpo"]
        self.assertEqual(pref["back_urls"]["success"], "https://willpdv.com.br/site/obrigado")
        self.assertEqual(pref["back_urls"]["pending"], "https://willpdv.com.br/site/pagamento-pendente")
        self.assertEqual(pref["back_urls"]["failure"], "https://willpdv.com.br/site/pagamento-falhou")
        self.assertEqual(pref["notification_url"], "https://willpdv.com.br/v1/pagamentos/webhook")
        pedido_id = r.json()["pedido"]
        self.pagamento["external_reference"] = pedido_id
        no_dominio = TestClient(nuvem.app, base_url="https://willpdv.com.br")
        aviso = no_dominio.post(
            "/v1/pagamentos/webhook", params={"data.id": "555", "type": "payment"},
            json={"status": "approved", "transaction_amount": 1}, follow_redirects=False)
        self.assertEqual(aviso.status_code, 200, aviso.text)
        self.assertEqual(aviso.json()["situacao"], "processado")
        no_onrender = TestClient(nuvem.app, base_url="https://willpdv-nuvem-6sp0.onrender.com")
        de_novo = no_onrender.post(
            "/v1/pagamentos/webhook", params={"data.id": "555", "type": "payment"},
            json={"status": "approved"}, follow_redirects=False)
        self.assertEqual(de_novo.status_code, 200, de_novo.text)
        self.assertNotIn("location", de_novo.headers)
        with mock.patch.dict(os.environ, {"MP_ACCESS_TOKEN": "APP_USR-ficticio", "PUBLIC_BASE_URL": ""}):
            r = self.comprar("adega-mensal")
        self.assertTrue(r.json()["init_point"].startswith("https://www.mercadopago.com.br/checkout/"))

    def test_sem_token_o_site_cai_no_whatsapp_e_a_rota_responde_503(self):
        with mock.patch.dict(os.environ, {"MP_ACCESS_TOKEN": ""}):
            pagina = self.http.get("/site/").text
            r = self.comprar()
        self.assertEqual(r.status_code, 503)
        self.assertIn("WhatsApp", r.json()["detail"])
        self.assertNotIn("checkout-abrir", pagina)
        self.assertEqual(pagina.count('<span class="so-mes">Assinar agora</span>'), 10)
        self.assertEqual(pagina.count('<span class="so-ano">Comprar</span>'), 10)
        self.assertIn("https://wa.me/5511915168336", pagina)
        self.assertEqual(pagina.count(">Assinar</a>"), 5)
        self.assertIn('id="form-teste"', pagina)
        self.assertIn("Testar grátis", pagina)
        self.assertIn("Falar no WhatsApp", pagina)
        self.assertEqual(self.chamadas, [])

    def test_com_token_o_botao_abre_o_formulario(self):
        pagina = self.http.get("/site/").text
        self.assertNotIn("{{", pagina)
        self.assertNotIn("TEST-token-ficticio", pagina)
        self.assertEqual(pagina.count("checkout-abrir"), 10)
        self.assertIn('data-plano="variedades"', pagina)
        self.assertIn('data-plano="hotel"', pagina)
        self.assertIn("Will Variedades", pagina)
        self.assertIn("Will Hotel", pagina)
        self.assertIn('id="form-checkout"', pagina)
        self.assertIn("Nome da loja", pagina)
        self.assertIn('src="/site/checkout.js"', pagina)
        self.assertEqual(pagina.count(">Assinar</a>"), 5)
        self.assertIn('id="form-teste"', pagina)
        js = self.http.get("/site/checkout.js")
        self.assertEqual(js.status_code, 200)
        self.assertIn("init_point", js.text)
        self.assertNotIn("TEST-token-ficticio", js.text)

    def test_paginas_de_retorno_e_dados_ruins(self):
        for caminho, titulo in (("/site/obrigado", "Obrigado"), ("/site/obrigado/", "Obrigado"),
                                ("/site/pagamento-pendente", "Pagamento pendente"),
                                ("/site/pagamento-pendente/", "Pagamento pendente"),
                                ("/site/pagamento-falhou", "Pagamento não concluído"),
                                ("/site/pagamento-falhou/", "Pagamento não concluído")):
            pagina = self.http.get(caminho, params={"payment_id": "42", "status": "<script>approved</script>"})
            self.assertEqual(pagina.status_code, 200, caminho)
            self.assertIn('href="/site/estilo.css"', pagina.text)
            self.assertIn('class="topo"', pagina.text)
            self.assertIn(f"<h1>{titulo}</h1>", pagina.text)
            self.assertIn("Número do pagamento: 42.", pagina.text)
            self.assertNotIn("<script>", pagina.text)
            self.assertNotIn("{{", pagina.text)
            self.assertIn("Chamar no WhatsApp", pagina.text)
        self.assertEqual(self.comprar(plano="inexistente").status_code, 422)
        self.assertEqual(self.comprar(nome="An").status_code, 422)
        self.assertEqual(self.comprar(email="nao-e-email").status_code, 422)
        self.assertEqual(self.comprar(whatsapp="123").status_code, 422)
        self.assertEqual(self.comprar(loja="A").status_code, 422)
        self.assertEqual(self.chamadas, [])

    def test_webhook_confirma_na_api_e_ignora_o_corpo(self):
        pedido_id = self.comprar().json()["pedido"]
        self.pagamento["external_reference"] = pedido_id
        self.pagamento["status"] = "pending"
        r = self.notificar()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["situacao"], "processado")
        self.assertIn("/v1/payments/555", [c["caminho"] for c in self.chamadas])
        guardado = self.pedido(pedido_id)
        self.assertEqual(guardado.status, "pendente")
        self.assertEqual(guardado.valor_pago_cent, 9_000)
        self.assertEqual(guardado.payment_id, "555")
        self.assertIsNone(guardado.pago_em)
        self.pagamento["status"] = "approved"
        r = self.notificar()
        self.assertEqual(r.json()["situacao"], "processado")
        guardado = self.pedido(pedido_id)
        self.assertEqual(guardado.status, "aprovado")
        self.assertEqual(guardado.valor_cent, 9_000)
        self.assertRegex(guardado.pago_em, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        with nuvem.SessionLocal() as db:
            self.assertEqual(db.query(checkout.PagamentoSite).count(), 1)
            db.get(checkout.Pedido, pedido_id).atualizado_em = "1999-01-01 00:00:00"
            db.commit()
        r = self.notificar()
        self.assertEqual(r.json()["situacao"], "idempotente")
        self.assertEqual(self.pedido(pedido_id).atualizado_em, "1999-01-01 00:00:00")
        with nuvem.SessionLocal() as db:
            self.assertEqual(db.query(checkout.PagamentoSite).count(), 1)
        aviso = self.http.get("/v1/pagamentos/webhook", params={"id": "555", "topic": "payment"})
        self.assertEqual(aviso.json()["situacao"], "idempotente")
        self.pagamento.update(status="approved", transaction_amount=Decimal("1.00"))
        outro = self.notificar(data_id="777")
        self.assertEqual(outro.json()["situacao"], "ja_aprovado")
        self.assertEqual(self.pedido(pedido_id).status, "aprovado")
        self.assertEqual(self.pedido(pedido_id).payment_id, "555")
        self.assertEqual(self.pedido(pedido_id).atualizado_em, "1999-01-01 00:00:00")

    def test_valor_ou_moeda_diferente_nao_aprova(self):
        pedido_id = self.comprar("restaurante-mensal").json()["pedido"]
        self.pagamento.update(external_reference=pedido_id, status="approved",
                              transaction_amount=Decimal("1.00"), currency_id="BRL")
        self.assertEqual(self.notificar().json()["situacao"], "processado")
        guardado = self.pedido(pedido_id)
        self.assertEqual(guardado.status, "divergente")
        self.assertEqual(guardado.valor_pago_cent, 100)
        self.assertNotEqual(guardado.status, "aprovado")
        self.pagamento.update(transaction_amount=Decimal("149.99"), currency_id="USD", id=556)
        self.assertEqual(self.notificar(data_id="556").json()["situacao"], "processado")
        self.assertEqual(self.pedido(pedido_id).status, "divergente")

    def test_assinatura_so_quando_o_segredo_existe(self):
        pedido_id = self.comprar().json()["pedido"]
        self.pagamento["external_reference"] = pedido_id
        with mock.patch.dict(os.environ, {"MP_WEBHOOK_SECRET": "segredo-do-webhook"}):
            self.assertEqual(self.notificar().status_code, 401)
            self.assertEqual(self.notificar(headers=assinar("555", segredo="outro")).status_code, 401)
            self.assertEqual(self.pedido(pedido_id).status, "aguardando")
            ok = self.notificar(headers=assinar("555"))
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(self.pedido(pedido_id).status, "aprovado")
        self.pagamento["external_reference"] = "f" * 32
        self.assertEqual(self.notificar(data_id="557").json()["situacao"], "ignorado")
        self.assertEqual(self.pedido(pedido_id).payment_id, "555")

    def test_ordem_do_mercado_pago_busca_cada_pagamento(self):
        pedido_id = self.comprar().json()["pedido"]
        self.pagamento["external_reference"] = pedido_id
        r = self.notificar(data_id="900", tipo="merchant_order")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["situacao"], "processado")
        caminhos = [c["caminho"] for c in self.chamadas]
        self.assertIn("/merchant_orders/900", caminhos)
        self.assertIn("/v1/payments/555", caminhos)
        self.assertEqual(self.pedido(pedido_id).status, "aprovado")

    def test_falha_nao_revela_o_token_nem_o_email(self):
        self.quebrar = True
        with self.assertLogs("pdv.site_checkout", level="ERROR") as saida:
            r = self.comprar()
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("TEST-token-ficticio", r.text)
        texto = "\n".join(saida.output)
        self.assertNotIn("TEST-token-ficticio", texto)
        self.assertNotIn("maria@exemplo.com", texto)
        self.assertEqual(self._ultimo().status, "erro")

    def _ultimo(self):
        with nuvem.SessionLocal() as db:
            linha = db.query(checkout.Pedido).one()
            db.expunge(linha)
            return linha

    def test_sem_token_o_webhook_responde_503(self):
        pedido_id = self.comprar().json()["pedido"]
        self.pagamento["external_reference"] = pedido_id
        with mock.patch.dict(os.environ, {"MP_ACCESS_TOKEN": ""}):
            r = self.notificar()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.pedido(pedido_id).status, "aguardando")
