"""Cobrança da licença pelo Mercado Pago: assinatura do webhook, Pix, Checkout Pro e renovação."""
from __future__ import annotations

import copy
import hashlib
import hmac
import io
import os
import threading
import time
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock
from urllib.error import HTTPError, URLError

from tests.test_nuvem import TestClient, cabecalho, lojas, nuvem, preparar_lojas
from tests.test_licenca_nuvem import BaseChave
from src.core import licenca
from src.database.conexao import BancoDados
from src.sync import licenca_nuvem

if nuvem is not None:
    from backend import cobranca_mercadopago as cobranca


def assinar(data_id, request_id, segredo="segredo-do-webhook", ts=None):
    ts = str(int(time.time()) if ts is None else ts)
    manifesto = f"id:{data_id.lower()};request-id:{request_id};ts:{ts};"
    v1 = hmac.new(segredo.encode(), manifesto.encode(), hashlib.sha256).hexdigest()
    return {"x-signature": f"ts={ts},v1={v1}", "x-request-id": request_id}


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteCobrancasMercadoPago(BaseChave):
    def setUp(self):
        super().setUp()
        self.ambiente = mock.patch.dict(os.environ, {
            "MP_ACCESS_TOKEN": "TEST-token-ficticio",
            "MP_WEBHOOK_SECRET": "segredo-do-webhook",
            "MP_VARREDURA": "0",
        })
        self.ambiente.start()
        self.addCleanup(self.ambiente.stop)
        self.db = nuvem.SessionLocal()
        self.addCleanup(self.db.close)
        self.limpar()
        self.addCleanup(self.limpar)
        preparar_lojas()
        self.http = TestClient(nuvem.app)
        self.cobranca_id = "a" * 32
        self.plano_id = "b" * 32
        self.db.add(cobranca.Plano(
            id=self.plano_id, chave_loja="LOJA-1", valor_cent=9900, email_pagador="pagador@exemplo.com",
            criado_em=cobranca.agora()))
        self.db.add(cobranca.Cobranca(
            id=self.cobranca_id, plano=self.plano_id, chave_loja="LOJA-1",
            chave_vencimento="LOJA-1:2026-10-15", valor_cent=9900, vencimento="2026-10-15",
            status="pendente", pix_id="555", preference_id="pref-teste",
            pix_copia_cola="00020126TESTEPIX",
            checkout_url="https://sandbox.mercadopago.com.br/checkout/v1/redirect?pref_id=pref-teste",
            criada_em=cobranca.agora(), consultada_em=cobranca.agora()))
        self.db.commit()
        self.pagamento = {
            "id": 555, "status": "approved", "transaction_amount": Decimal("99.00"),
            "transaction_amount_refunded": 0, "currency_id": "BRL",
            "external_reference": self.cobranca_id, "payment_method_id": "pix",
            "payment_type_id": "bank_transfer", "metadata": {"chave_loja": "LOJA-1"},
        }
        self.chamadas = []
        self.consulta = mock.patch.object(cobranca, "requisitar", side_effect=self.fake)
        self.remoto = self.consulta.start()
        self.addCleanup(self.consulta.stop)

    def limpar(self):
        self.db.rollback()
        for modelo in (cobranca.Pagamento, cobranca.Evento, cobranca.Cobranca, cobranca.Plano):
            self.db.query(modelo).delete()
        self.db.commit()

    def fake(self, metodo, caminho, corpo=None, idempotencia=None):
        self.chamadas.append({"metodo": metodo, "caminho": caminho, "corpo": corpo,
                              "idempotencia": idempotencia})
        if metodo == "POST" and caminho == "/v1/payments":
            return {"id": 777, "status": "pending", "point_of_interaction": {"transaction_data": {
                "qr_code": "00020126580014br.gov.bcb.pix",
                "qr_code_base64": "QUJDRA==",
                "ticket_url": "https://www.mercadopago.com.br/payments/777/ticket"}}}
        if metodo == "POST" and caminho == "/checkout/preferences":
            return {"id": "pref-nova",
                    "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=pref-nova",
                    "sandbox_init_point": "https://sandbox.mercadopago.com.br/checkout/v1/redirect?pref_id=pref-nova"}
        if metodo == "PUT":
            return {"id": caminho.rsplit("/", 1)[-1], "status": "cancelled"}
        if "/payments/search" in caminho:
            return {"results": [{"id": self.pagamento["id"]}]}
        if metodo == "GET" and caminho.startswith("/v1/payments/"):
            dados = copy.deepcopy(self.pagamento)
            pid = caminho.rsplit("/", 1)[-1].split("?", 1)[0]
            if pid.isdigit():
                dados["id"] = int(pid)
            return dados
        raise AssertionError((metodo, caminho))

    def enviar(self, evento="req-00001", data_id="555", tipo="payment", headers=None, ts=None, corpo=None):
        cab = assinar(data_id, evento, ts=ts) if headers is None else headers
        return self.http.post(
            "/v1/webhooks/mercadopago",
            params={"data.id": data_id, "type": tipo},
            json=corpo if corpo is not None else {"type": tipo, "action": "payment.updated",
                                                   "data": {"id": "corpo-nao-confiavel"},
                                                   "status": "refunded", "transaction_amount": 1},
            headers=cab)

    def validade(self, chave="LOJA-1"):
        self.db.expire_all()
        return self.db.query(nuvem.Loja).filter_by(chave_loja=chave).one().licenca_ate

    def test_manifesto_oficial_poe_o_id_em_minusculas(self):
        self.assertEqual(
            cobranca.manifesto("999999999", "bbf4e0c0-7b6e-4f0a", "1704908010"),
            "id:999999999;request-id:bbf4e0c0-7b6e-4f0a;ts:1704908010;")
        self.assertEqual(cobranca.manifesto("AbC12", "req-teste", "1"),
                         "id:abc12;request-id:req-teste;ts:1;")

    def test_pagamento_aprovado_na_api_renova_so_a_loja_e_ignora_o_corpo(self):
        resposta = self.enviar()
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json()["situacao"], "processado")
        self.assertEqual(self.validade(), "2026-11-15")
        self.assertIsNone(self.validade("LOJA-2"))
        self.assertEqual(self.db.get(cobranca.Pagamento, "555").valor_cent, 9900)
        self.assertEqual(self.db.get(cobranca.Cobranca, self.cobranca_id).status, "aprovada")
        # Duas leituras: a da rota e a de dentro do bloqueio da loja. O corpo não entra.
        self.assertEqual(sum(1 for c in self.chamadas if c["metodo"] == "GET"), 2)

    def test_webhook_exige_assinatura_e_segredo(self):
        for headers in ({}, cabecalho(), {"x-signature": "ts=1,v1=00", "x-request-id": "req-invalido"}):
            self.assertEqual(self.enviar(headers=headers).status_code, 401)
        ruim = assinar("555", "req-1", segredo="outro-segredo")
        self.assertEqual(self.enviar(headers=ruim).status_code, 401)
        with mock.patch.dict(os.environ, {"MP_WEBHOOK_SECRET": ""}):
            self.assertEqual(self.enviar().status_code, 503)
        self.assertEqual(self.enviar(ts=int(time.time()) - cobranca.TOLERANCIA_ASSINATURA_SEG - 5).status_code, 401)
        self.assertIsNone(self.validade())

    def test_aceita_ts_em_milissegundos_e_cabecalho_reordenado(self):
        self.pagamento["status"] = "pending"
        self.assertEqual(self.enviar(evento="req-millis", ts=int(time.time() * 1000)).status_code, 200)
        ts = str(int(time.time()))
        v1 = hmac.new(b"segredo-do-webhook",
                      cobranca.manifesto("555", "req-ordem", ts).encode(), hashlib.sha256).hexdigest()
        headers = {"x-signature": f"v1={v1}, ts={ts}", "x-request-id": "req-ordem"}
        self.pagamento["status"] = "pending"
        self.assertEqual(self.enviar(evento="req-ordem", headers=headers).status_code, 200)
        self.assertIsNone(self.validade())

    def test_tipo_que_nao_e_pagamento_nao_consulta_a_api(self):
        antes = len(self.chamadas)
        resposta = self.enviar(tipo="merchant_order")
        self.assertEqual(resposta.json()["situacao"], "ignorado")
        self.assertEqual(len(self.chamadas), antes)
        resposta = self.enviar(evento="req-letra", data_id="ABC")
        self.assertEqual(resposta.json()["situacao"], "ignorado")
        self.assertEqual(len(self.chamadas), antes)
        self.assertIsNone(self.validade())

    def test_pendente_estorno_chargeback_e_valor_divergente_nao_liberam(self):
        for numero, status in enumerate(("pending", "rejected", "refunded", "charged_back",
                                        "cancelled", "in_process", "in_mediation")):
            self.pagamento["status"] = status
            self.pagamento["transaction_amount_refunded"] = 0
            self.assertEqual(self.enviar(f"req-st-{numero}").status_code, 200)
            self.assertIsNone(self.validade())
        self.pagamento["status"] = "approved"
        self.pagamento["transaction_amount_refunded"] = Decimal("1.00")
        self.assertEqual(self.enviar("req-parcial").status_code, 200)
        self.assertIsNone(self.validade())
        self.pagamento["transaction_amount_refunded"] = 0
        self.pagamento["transaction_amount"] = Decimal("9.90")
        self.assertEqual(self.enviar("req-valor").status_code, 200)
        self.assertIsNone(self.validade())
        self.assertEqual(self.db.get(cobranca.Cobranca, self.cobranca_id).status, "divergente")
        self.pagamento["transaction_amount"] = Decimal("99.00")
        self.pagamento["currency_id"] = "USD"
        self.assertEqual(self.enviar("req-moeda").status_code, 200)
        self.assertIsNone(self.validade())
        self.pagamento["currency_id"] = "BRL"
        self.pagamento["metadata"] = {"chave_loja": "LOJA-2"}
        self.assertEqual(self.enviar("req-loja").status_code, 200)
        self.assertIsNone(self.validade())

    def test_evento_repetido_nao_consulta_de_novo_nem_soma_outro_mes(self):
        self.assertEqual(self.enviar().json()["situacao"], "processado")
        chamadas = len(self.chamadas)
        self.assertEqual(self.enviar().json()["situacao"], "repetido")
        self.assertEqual(len(self.chamadas), chamadas)
        self.assertEqual(self.enviar("req-00002").status_code, 200)
        self.assertEqual(self.validade(), "2026-11-15")
        self.assertEqual(self.db.query(cobranca.Pagamento).count(), 1)
        self.assertEqual(self.db.query(cobranca.Evento).count(), 2)

    def test_estorno_retira_a_validade_e_o_estado_vem_da_api(self):
        self.enviar()
        self.assertEqual(self.validade(), "2026-11-15")
        self.pagamento["status"] = "refunded"
        self.assertEqual(self.enviar("req-estorno").status_code, 200)
        self.assertIsNone(self.validade())
        self.enviar("req-antigo")
        self.assertIsNone(self.validade())

    def test_referencia_desconhecida_nao_libera(self):
        self.pagamento["external_reference"] = "f" * 32
        resposta = self.enviar()
        self.assertEqual(resposta.json()["situacao"], "desconhecida")
        self.assertIsNone(self.validade())
        self.assertEqual(self.enviar().json()["situacao"], "repetido")

    def test_falha_remota_nao_grava_evento_e_a_retentativa_renova(self):
        self.remoto.side_effect = cobranca.MercadoPagoIndisponivel("Falha de teste")
        resposta = self.enviar()
        self.assertEqual(resposta.status_code, 503)
        self.assertNotIn("Falha de teste", resposta.text)
        self.assertEqual(self.db.query(cobranca.Evento).count(), 0)
        self.assertIsNone(self.validade())
        self.remoto.side_effect = self.fake
        self.assertEqual(self.enviar().status_code, 200)
        self.assertEqual(self.validade(), "2026-11-15")

    def test_segunda_leitura_falha_nao_grava_licenca_parcial(self):
        self.remoto.side_effect = [copy.deepcopy(self.pagamento),
                                   cobranca.MercadoPagoIndisponivel("segunda")]
        self.assertEqual(self.enviar().status_code, 503)
        self.assertEqual(self.db.query(cobranca.Evento).count(), 0)
        self.assertIsNone(self.validade())

    def test_commit_falho_responde_503_sem_vazar_o_erro(self):
        from sqlalchemy.orm import Session
        with mock.patch.object(Session, "commit", side_effect=RuntimeError("senha-secreta")):
            resposta = self.enviar()
        self.assertEqual(resposta.status_code, 503, resposta.text)
        self.assertNotIn("senha-secreta", resposta.text)
        self.assertIsNone(self.validade())
        self.assertEqual(self.db.query(cobranca.Evento).count(), 0)

    def test_mes_calendario_ano_bissexto_e_dinheiro_exato(self):
        self.assertEqual(cobranca.fim_periodo(date(2026, 1, 31)), date(2026, 2, 28))
        self.assertEqual(cobranca.fim_periodo(date(2028, 1, 31)), date(2028, 2, 29))
        self.assertEqual(cobranca.fim_periodo(date(2026, 12, 31)), date(2027, 1, 31))
        self.assertEqual(cobranca.centavos(Decimal("99.90")), 9990)
        self.assertEqual(cobranca.para_json({"transaction_amount": Decimal("99.90")}),
                         b'{"transaction_amount":99.90}')
        for invalido in ("NaN", "Infinity", "-1", "0", "1.001", None, True):
            with self.assertRaises(cobranca.ErroCobranca):
                cobranca.centavos(invalido)

    def test_conciliacao_e_varredura_recuperam_pagamento_sem_webhook(self):
        self.assertEqual(cobranca.reconciliar(self.db, "LOJA-1"), 1)
        self.assertEqual(self.validade(), "2026-11-15")
        self.pagamento["status"] = "refunded"
        self.assertGreaterEqual(cobranca.varrer(self.db), 1)
        self.assertIsNone(self.validade())

    def test_dois_pagamentos_da_mesma_cobranca_nao_somam_meses_e_o_pix_e_cancelado(self):
        self.enviar()
        self.pagamento = dict(self.pagamento, id=556, payment_method_id="credit_card",
                              payment_type_id="credit_card")
        self.remoto.side_effect = self.fake_dois
        self.assertEqual(self.enviar("req-cartao", data_id="556").status_code, 200)
        self.assertEqual(self.validade(), "2026-11-15")
        self.assertEqual(self.db.query(cobranca.Pagamento).count(), 2)
        self.assertTrue(any(c["metodo"] == "PUT" and c["caminho"] == "/v1/payments/555" for c in self.chamadas))

    def fake_dois(self, metodo, caminho, corpo=None, idempotencia=None):
        self.chamadas.append({"metodo": metodo, "caminho": caminho, "corpo": corpo,
                              "idempotencia": idempotencia})
        if metodo == "PUT":
            return {"id": "555", "status": "cancelled"}
        if caminho.endswith("/555"):
            pix = dict(self.pagamento, id=555, status="pending", payment_method_id="pix")
            return pix
        if metodo == "GET":
            return copy.deepcopy(self.pagamento)
        raise AssertionError((metodo, caminho))

    def test_cobranca_mais_nova_nao_e_encurtada_por_estorno_da_antiga(self):
        self.enviar()
        segunda = "c" * 32
        self.db.add(cobranca.Cobranca(
            id=segunda, plano=self.plano_id, chave_loja="LOJA-1",
            chave_vencimento="LOJA-1:2026-11-15", valor_cent=9900, vencimento="2026-11-15",
            status="pendente", criada_em=cobranca.agora(), consultada_em=cobranca.agora()))
        self.db.commit()
        self.pagamento = dict(self.pagamento, id=556, external_reference=segunda)
        self.enviar("req-nova", data_id="556")
        self.assertEqual(self.validade(), "2026-12-15")
        self.pagamento["status"] = "refunded"
        self.enviar("req-estorna-nova", data_id="556")
        self.assertEqual(self.validade(), "2026-11-15")

    def test_preserva_validade_anterior_ao_plano(self):
        plano = self.db.get(cobranca.Plano, self.plano_id)
        plano.validade_anterior = "2027-01-01"
        self.db.commit()
        self.enviar()
        self.assertEqual(self.validade(), "2027-01-01")
        self.pagamento["status"] = "refunded"
        self.enviar("req-estorno")
        self.assertEqual(self.validade(), "2027-01-01")

    def test_comando_manual_nao_concorre_com_o_plano(self):
        with self.assertRaises(lojas.ErroLoja):
            lojas.definir_assinatura(self.db, "LOJA-1", date(2027, 1, 1))
        lojas.definir_assinatura(self.db, "LOJA-2", date(2027, 2, 1))
        self.assertEqual(self.validade("LOJA-2"), "2027-02-01")
        self.assertEqual(cobranca.definir_plano(self.db, "LOJA-2", 1500, "outra@exemplo.com"), "criado")
        plano = self.db.query(cobranca.Plano).filter_by(chave_loja="LOJA-2").one()
        self.assertEqual(plano.validade_anterior, "2027-02-01")
        self.assertEqual(cobranca.definir_plano(self.db, "LOJA-2", 1600, "outra@exemplo.com"), "atualizado")
        self.db.expire_all()
        plano = self.db.query(cobranca.Plano).filter_by(chave_loja="LOJA-2").one()
        self.assertEqual((plano.valor_cent, plano.validade_anterior), (1600, "2027-02-01"))
        with self.assertRaises(cobranca.ErroCobranca):
            cobranca.definir_plano(self.db, "LOJA-2", 1600, "invalido")
        with self.assertRaises(lojas.ErroLoja):
            lojas.definir_assinatura(self.db, "LOJA-2", date(2028, 1, 1))

    def test_loja_desativada_recebe_a_data_mas_nao_a_licenca(self):
        lojas.definir_ativa(self.db, "LOJA-1", False)
        self.assertEqual(self.enviar().status_code, 200)
        self.assertEqual(self.validade(), "2026-11-15")
        self.assertEqual(self.http.get("/v1/licenca", headers=cabecalho()).status_code, 403)

    def test_pagamento_chega_ao_pdv_pelo_fluxo_de_licenca_existente(self):
        vencimento = date.today() + timedelta(days=3)
        registro = self.db.get(cobranca.Cobranca, self.cobranca_id)
        registro.vencimento = vencimento.isoformat()
        registro.chave_vencimento = f"LOJA-1:{vencimento.isoformat()}"
        self.db.commit()
        self.assertEqual(self.enviar().status_code, 200)
        banco = BancoDados(":memory:")
        self.addCleanup(banco.fechar)
        banco.cfg_set("licenca_exigir", "S")
        banco.cfg_set("api_url", "https://nuvem/v1/sincronizar")
        banco.cfg_set("api_token", "token-da-loja-1")
        http = mock.Mock()
        http.get.side_effect = lambda url, **kw: self.http.get(url.replace("https://nuvem", ""), **kw)
        self.assertTrue(licenca_nuvem.renovar(banco, http, forcar=True))
        self.assertEqual(licenca.estado(banco).expira_em, cobranca.fim_periodo(vencimento))

    def test_gerar_pix_e_checkout_e_repetir_nao_cria_outra(self):
        with mock.patch.dict(os.environ, {"RENDER_EXTERNAL_URL": "https://willpdv-nuvem.onrender.com"}):
            criada = cobranca.gerar(self.db, "LOJA-1", date(2026, 12, 20))
        self.assertEqual(criada.pix_copia_cola, "00020126580014br.gov.bcb.pix")
        self.assertTrue(criada.checkout_url.startswith("https://sandbox.mercadopago.com.br/"))
        pix = next(c for c in self.chamadas if c["caminho"] == "/v1/payments")
        preferencia = next(c for c in self.chamadas if c["caminho"] == "/checkout/preferences")
        self.assertEqual(pix["corpo"]["payment_method_id"], "pix")
        self.assertEqual(pix["corpo"]["transaction_amount"], Decimal("99.00"))
        self.assertEqual(pix["corpo"]["payer"]["email"], "pagador@exemplo.com")
        self.assertEqual(pix["corpo"]["external_reference"], criada.id)
        self.assertEqual(pix["corpo"]["notification_url"],
                         "https://willpdv-nuvem.onrender.com/v1/webhooks/mercadopago")
        self.assertEqual(pix["idempotencia"], criada.id)
        self.assertEqual(preferencia["corpo"]["payment_methods"]["excluded_payment_types"],
                         [{"id": "bank_transfer"}])
        self.assertEqual(preferencia["corpo"]["payment_methods"]["installments"], 1)
        self.assertEqual(preferencia["idempotencia"], criada.id + "pref")
        self.assertNotIn("TEST-token", str(self.chamadas))
        antes = len(self.chamadas)
        de_novo = cobranca.gerar(self.db, "LOJA-1", date(2026, 12, 20))
        self.assertEqual(de_novo.id, criada.id)
        self.assertEqual(len(self.chamadas), antes)

    def test_token_de_producao_usa_o_link_de_producao(self):
        with mock.patch.dict(os.environ, {"MP_ACCESS_TOKEN": "APP_USR-ficticio"}):
            criada = cobranca.gerar(self.db, "LOJA-1", date(2027, 3, 1))
        self.assertTrue(criada.checkout_url.startswith("https://www.mercadopago.com.br/checkout/"))

    def test_cli_lista_gera_e_concilia(self):
        saida = io.StringIO()
        with redirect_stdout(saida):
            self.assertEqual(lojas.main(["cobranca", "listar"]), 0)
            self.assertEqual(lojas.main(["cobranca", "gerar", "LOJA-1", "2026-12-20"]), 0)
            self.assertEqual(lojas.main(["cobranca", "conciliar", "LOJA-1"]), 0)
        texto = saida.getvalue()
        self.assertIn("9900 centavos", texto)
        self.assertIn("00020126580014br.gov.bcb.pix", texto)
        self.assertIn("Pagamentos conciliados: ", texto)
        self.assertEqual(self.validade(), "2026-11-15")
        self.assertNotIn("TEST-token", texto)
        self.assertNotIn("segredo-do-webhook", texto)

    def test_admin_so_com_o_token_do_fornecedor_e_sem_segredo(self):
        url = "/v1/admin/cobrancas/operacao"
        self.assertEqual(self.http.get(url).status_code, 401)
        self.assertEqual(self.http.get(url, headers=cabecalho()).status_code, 403)
        corpo = self.http.get(url, headers={"Authorization": "Bearer token-de-teste"}).json()
        self.assertEqual(corpo["provedor"], "mercadopago")
        self.assertFalse(corpo["varredura_no_processo"])
        self.assertGreaterEqual(corpo["planos"], 1)
        self.assertGreaterEqual(corpo["cobrancas_pendentes"], 1)
        texto = str(corpo)
        self.assertNotIn("segredo-do-webhook", texto)
        self.assertNotIn("TEST-token", texto)
        self.assertNotIn("00020126TESTEPIX", texto)
        self.assertNotIn("pagador@exemplo.com", texto)

    def test_migracao_preserva_licenca_e_nao_apaga_tabela_antiga(self):
        from sqlalchemy import inspect, text
        loja = self.db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").one()
        loja.licenca_ate = "2027-03-01"
        self.db.execute(text(
            "CREATE TABLE IF NOT EXISTS assinaturas_asaas (id VARCHAR PRIMARY KEY, chave_loja VARCHAR)"))
        self.db.execute(text("DELETE FROM assinaturas_asaas WHERE id = 'sub_antiga'"))
        self.db.execute(text(
            "INSERT INTO assinaturas_asaas (id, chave_loja) VALUES ('sub_antiga', 'LOJA-1')"))
        self.db.commit()
        cobranca.garantir_esquema(self.db.get_bind())
        self.db.expire_all()
        self.assertEqual(self.db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").one().licenca_ate, "2027-03-01")
        self.assertEqual(self.db.execute(text(
            "SELECT chave_loja FROM assinaturas_asaas WHERE id = 'sub_antiga'")).scalar(), "LOJA-1")
        inspetor = inspect(self.db.get_bind())
        for tabela in ("planos_mercadopago", "cobrancas_mercadopago", "pagamentos_mercadopago",
                       "eventos_mercadopago"):
            self.assertTrue(inspetor.has_table(tabela), tabela)


@unittest.skipIf(nuvem is None, "Dependências do backend ausentes")
class TesteClienteMercadoPago(unittest.TestCase):
    def setUp(self):
        self.ambiente = mock.patch.dict(os.environ, {
            "MP_ACCESS_TOKEN": "TEST-token-ficticio", "MP_WEBHOOK_SECRET": "segredo", "MP_VARREDURA": "0"})
        self.ambiente.start()
        self.addCleanup(self.ambiente.stop)

    def test_endereco_bearer_timeout_e_sem_redirecionar(self):
        vistos = {}

        class Abertura:
            def open(self, requisicao, timeout=None):
                vistos["timeout"] = timeout
                vistos["url"] = requisicao.full_url
                vistos["auth"] = requisicao.get_header("Authorization")
                vistos["idempotencia"] = requisicao.get_header("X-idempotency-key")
                vistos["corpo"] = requisicao.data

                class Resposta:
                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        return False

                    def read(self, n=-1):
                        return b'{"id":1,"transaction_amount":99.90}'
                return Resposta()

        with mock.patch.object(cobranca, "build_opener", return_value=Abertura()):
            dados = cobranca.requisitar("POST", "/v1/payments", {"transaction_amount": Decimal("99.90")},
                                        idempotencia="chave-1")
        self.assertEqual(dados["transaction_amount"], Decimal("99.90"))
        self.assertEqual(vistos["url"], "https://api.mercadopago.com/v1/payments")
        self.assertEqual(vistos["auth"], "Bearer TEST-token-ficticio")
        self.assertEqual(vistos["idempotencia"], "chave-1")
        self.assertEqual(vistos["timeout"], cobranca.TIMEOUT)
        self.assertIn(b'"transaction_amount":99.90', vistos["corpo"])
        with self.assertRaises(cobranca.MercadoPagoIndisponivel):
            cobranca._SemRedirecionamento().redirect_request(None, None, 302, "vai", {}, "https://outro")

    def test_erros_nao_expoem_segredos(self):
        for erro in (URLError("segredo"), HTTPError("https://api.mercadopago.com/segredo", 401, "segredo", {}, None),
                     TimeoutError("segredo")):
            with mock.patch.object(cobranca, "_abrir", side_effect=erro), \
                    self.assertRaises(cobranca.MercadoPagoIndisponivel) as resultado:
                cobranca.requisitar("GET", "/v1/payments/1")
            self.assertNotIn("segredo", str(resultado.exception))
            self.assertNotIn("TEST-token", str(resultado.exception))


@unittest.skipUnless(
    nuvem is not None and os.environ.get("PDV_TESTE_NUVEM_DB_URL", "").startswith(
        ("postgresql://", "postgres://", "postgresql+psycopg://")),
    "Requer PostgreSQL exclusivo de testes")
class TesteConcorrenciaPostgreSQL(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.database import Base, normalizar_url
        self.ambiente = mock.patch.dict(os.environ, {
            "MP_ACCESS_TOKEN": "TEST-token-ficticio",
            "MP_WEBHOOK_SECRET": "segredo-do-webhook",
            "MP_VARREDURA": "0",
        })
        self.ambiente.start()
        self.addCleanup(self.ambiente.stop)
        self.engine = create_engine(normalizar_url(os.environ["PDV_TESTE_NUVEM_DB_URL"]))
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        cobranca.garantir_esquema(self.engine)
        self.fabrica = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.fabrica()
        self.addCleanup(self.db.close)
        self.limpar()
        self.addCleanup(self.limpar)
        self.db.add(nuvem.Loja(chave_loja="LOJA-PG", nome="PG", token_hash="t", ativa=True))
        self.db.add(cobranca.Plano(
            id="p" * 32, chave_loja="LOJA-PG", valor_cent=9900, email_pagador="pg@exemplo.com",
            criado_em=cobranca.agora()))
        self.db.add(cobranca.Cobranca(
            id="d" * 32, plano="p" * 32, chave_loja="LOJA-PG", chave_vencimento="LOJA-PG:2026-10-15",
            valor_cent=9900, vencimento="2026-10-15", status="pendente", pix_id="555",
            criada_em=cobranca.agora(), consultada_em=cobranca.agora()))
        self.db.commit()
        self.pagamento = {
            "id": 555, "status": "approved", "transaction_amount": "99.00", "currency_id": "BRL",
            "external_reference": "d" * 32, "payment_type_id": "bank_transfer",
        }
        consulta = mock.patch.object(cobranca, "requisitar", side_effect=self.resposta)
        self.remoto = consulta.start()
        self.addCleanup(consulta.stop)

    def limpar(self):
        self.db.rollback()
        for modelo in (cobranca.Pagamento, cobranca.Evento, cobranca.Cobranca, cobranca.Plano, nuvem.Loja):
            self.db.query(modelo).delete()
        self.db.commit()

    def resposta(self, metodo, caminho, corpo=None, idempotencia=None):
        if metodo == "GET" and "/search" not in caminho:
            return copy.deepcopy(self.pagamento)
        raise AssertionError(caminho)

    def test_notificacoes_concorrentes_do_mesmo_evento_renovam_uma_vez(self):
        from concurrent.futures import ThreadPoolExecutor
        barreira = threading.Barrier(2)

        def enviar():
            with self.fabrica() as db:
                barreira.wait(timeout=10)
                return cobranca.processar_notificacao(db, "555", "req-concorrente")

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: enviar(), range(2)))
        self.assertCountEqual(resultados, ["processado", "repetido"])
        with self.fabrica() as db:
            self.assertEqual(db.query(cobranca.Evento).count(), 1)
            self.assertEqual(db.query(cobranca.Pagamento).count(), 1)
            self.assertEqual(db.query(nuvem.Loja).filter_by(chave_loja="LOJA-PG").one().licenca_ate, "2026-11-15")


if __name__ == "__main__":
    unittest.main()
