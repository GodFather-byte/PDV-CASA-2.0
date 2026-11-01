"""Assinatura mensal: boleto, Pix, e-mail, WhatsApp e geração na janela do vencimento."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
import unittest
from datetime import date
from decimal import Decimal
from unittest import mock

from tests.test_nuvem import TestClient, cabecalho, nuvem, preparar_lojas

if nuvem is not None:
    from sqlalchemy import inspect, text
    from backend import cobranca_mercadopago as cobranca


def _pedido(**extras):
    dados = {
        "chave_loja": "LOJA-1",
        "valor_cent": 24999,
        "dia_vencimento": 10,
        "email": "financeiro@exemplo.com",
        "whatsapp": "+55 11 98888-7777",
        "nome": "Maria Silva",
        "documento": "529.982.247-25",
        "cep": "01310-100",
        "logradouro": "Avenida Paulista",
        "numero": "1000",
        "bairro": "Bela Vista",
        "cidade": "São Paulo",
        "uf": "sp",
    }
    dados.update(extras)
    return dados


@unittest.skipIf(nuvem is None, "Dependências do backend ausentes")
class TesteAssinaturaMensal(unittest.TestCase):
    def setUp(self):
        self.ambiente = mock.patch.dict(os.environ, {
            "MP_ACCESS_TOKEN": "TEST-token-ficticio",
            "MP_WEBHOOK_SECRET": "segredo-do-webhook",
            "MP_VARREDURA": "0",
            "SMTP_HOST": "",
            "SMTP_PORT": "",
            "SMTP_USER": "",
            "SMTP_PASSWORD": "",
            "SMTP_FROM": "",
            "WHATSAPP_API_URL": "",
            "WHATSAPP_API_TOKEN": "",
        })
        self.ambiente.start()
        self.addCleanup(self.ambiente.stop)
        self.db = nuvem.SessionLocal()
        self.addCleanup(self.db.close)
        self.limpar()
        self.addCleanup(self.limpar)
        preparar_lojas()
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
        if metodo == "POST" and caminho == "/v1/payments" and corpo and corpo.get("payment_method_id") == "pix":
            return {"id": 777, "status": "pending", "point_of_interaction": {"transaction_data": {
                "qr_code": "00020126580014br.gov.bcb.pix",
                "qr_code_base64": "QUJDRA==",
                "ticket_url": "https://www.mercadopago.com.br/payments/777/ticket"}}}
        if metodo == "POST" and caminho == "/v1/payments":
            return {"id": 888, "status": "pending", "payment_method_id": corpo.get("payment_method_id"),
                    "transaction_details": {
                        "external_resource_url": "https://www.mercadopago.com.br/mlb/payments/boleto/888"},
                    "barcode": {"content": "23793.38128 60000.000003 00000.000400 1 84340000024999"}}
        if metodo == "POST" and caminho == "/checkout/preferences":
            return {"id": "pref-mensal",
                    "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=pref-mensal",
                    "sandbox_init_point": "https://sandbox.mercadopago.com.br/checkout/v1/redirect?pref_id=pref-mensal"}
        if metodo == "GET" and caminho.startswith("/v1/payments/"):
            return {"id": int(caminho.rsplit("/", 1)[-1]), "status": "approved",
                    "transaction_amount": Decimal("249.99"), "currency_id": "BRL",
                    "external_reference": self.referencia, "payment_type_id": "ticket"}
        raise AssertionError((metodo, caminho))

    def test_janela_calendario_e_dia_31_em_fevereiro(self):
        self.assertEqual(cobranca.vencimentos_abertos(date(2026, 10, 5), 10, 5), [date(2026, 10, 10)])
        self.assertEqual(cobranca.vencimentos_abertos(date(2026, 10, 4), 10, 5), [])
        self.assertEqual(cobranca.vencimentos_abertos(date(2026, 10, 20), 10, 5), [date(2026, 10, 10)])
        self.assertEqual(cobranca.vencimentos_abertos(date(2026, 10, 31), 10, 5), [])
        self.assertEqual(cobranca.vencimentos_abertos(date(2026, 11, 5), 10, 5), [date(2026, 11, 10)])
        self.assertEqual(cobranca.dia_no_mes(2026, 2, 31), date(2026, 2, 28))
        self.assertEqual(cobranca.vencimentos_abertos(date(2026, 2, 23), 31, 5), [date(2026, 2, 28)])
        self.assertEqual(cobranca.proximo_vencimento(date(2026, 10, 31), 10, 5), date(2026, 11, 10))

    def test_documento_e_whatsapp(self):
        self.assertEqual(cobranca.validar_documento("529.982.247-25"), ("CPF", "52998224725"))
        self.assertEqual(cobranca.normalizar_whatsapp("+55 11 98888-7777"), "+5511988887777")
        self.assertEqual(cobranca.normalizar_whatsapp("11988887777"), "+5511988887777")
        self.assertEqual(cobranca.normalizar_whatsapp("(11) 3333-4444"), "+551133334444")
        for invalido in ("123", "529.982.247-26", "111.111.111-11", "+55 10 98888-7777", "11888877777"):
            with self.assertRaises(cobranca.ErroCobranca):
                if "@" in invalido or "529" in invalido or "111" in invalido:
                    cobranca.validar_documento(invalido)
                else:
                    cobranca.normalizar_whatsapp(invalido)

    def test_cnpj_valido_e_invalido(self):
        tipo, numero = cobranca.validar_documento("11.444.777/0001-61")
        self.assertEqual((tipo, numero), ("CNPJ", "11444777000161"))
        with self.assertRaises(cobranca.ErroCobranca):
            cobranca.validar_documento("11.444.777/0001-62")

    def test_gera_boleto_e_pix_na_janela_e_nao_repete_o_aviso(self):
        self.assertEqual(cobranca.definir_assinatura_de_pedido(self.db, _pedido()), "criada")
        plano = self.db.query(cobranca.Plano).filter_by(chave_loja="LOJA-1").one()
        self.assertEqual(plano.whatsapp, "+5511988887777")
        self.assertEqual(plano.pagador_documento, "52998224725")
        self.assertEqual(plano.cep, "01310100")
        self.assertEqual(plano.uf, "SP")
        self.assertEqual(plano.validade_anterior, None)
        self.assertEqual(cobranca.gerar_recorrencias(self.db, date(2026, 10, 4), "LOJA-1"), 0)
        self.assertEqual(self.chamadas, [])
        self.assertEqual(cobranca.gerar_recorrencias(self.db, date(2026, 10, 5), "LOJA-1"), 1)
        pix = next(c for c in self.chamadas if c["corpo"] and c["corpo"].get("payment_method_id") == "pix")
        boleto = next(c for c in self.chamadas if c["corpo"] and c["corpo"].get("payment_method_id") == "bolbradesco")
        preferencia = next(c for c in self.chamadas if c["caminho"] == "/checkout/preferences")
        self.assertEqual(pix["corpo"]["transaction_amount"], Decimal("249.99"))
        self.assertEqual(boleto["corpo"]["payer"]["identification"], {"type": "CPF", "number": "52998224725"})
        self.assertEqual(boleto["corpo"]["payer"]["first_name"], "Maria")
        self.assertEqual(boleto["corpo"]["payer"]["address"]["federal_unit"], "SP")
        self.assertEqual(boleto["corpo"]["payer"]["address"]["zip_code"], "01310100")
        self.assertTrue(boleto["idempotencia"].endswith("boleto"))
        self.assertEqual(preferencia["corpo"]["payment_methods"]["excluded_payment_types"],
                         [{"id": "bank_transfer"}, {"id": "ticket"}])
        self.assertNotIn("TEST-token", str(self.chamadas))
        registro = self.db.query(cobranca.Cobranca).filter_by(vencimento="2026-10-10").one()
        self.referencia = registro.id
        self.assertEqual(registro.boleto_url, "https://www.mercadopago.com.br/mlb/payments/boleto/888")
        self.assertIn("23793", registro.boleto_linha)
        self.assertEqual(registro.pix_copia_cola, "00020126580014br.gov.bcb.pix")
        self.assertEqual(registro.aviso_email, "nao_configurado")
        self.assertEqual(registro.aviso_whatsapp, "nao_configurado")
        self.assertIsNotNone(registro.avisada_em)
        antes = len(self.chamadas)
        self.assertEqual(cobranca.gerar_recorrencias(self.db, date(2026, 10, 6), "LOJA-1"), 0)
        self.assertEqual(len(self.chamadas), antes)
        resposta = cobranca.reenviar(self.db, "LOJA-1")
        self.assertIn("wa.me/5511988887777", resposta["whatsapp_link"])
        self.assertIn("00020126580014br.gov.bcb.pix", resposta["whatsapp_link"])
        self.assertEqual(resposta["boleto_linha"], registro.boleto_linha)
        self.assertIn("payments/boleto/888", resposta["whatsapp_link"])

    def test_metodo_de_boleto_configuravel_e_pagamento_renova_a_licenca(self):
        cobranca.definir_assinatura_de_pedido(self.db, _pedido())
        with mock.patch.dict(os.environ, {"MP_BOLETO_METODO": "pec"}):
            self.assertEqual(cobranca.gerar_recorrencias(self.db, date(2026, 10, 5), "LOJA-1"), 1)
        boleto = next(c for c in self.chamadas if c["corpo"] and c["caminho"] == "/v1/payments"
                      and c["corpo"].get("payment_method_id") != "pix")
        self.assertEqual(boleto["corpo"]["payment_method_id"], "pec")
        registro = self.db.query(cobranca.Cobranca).one()
        self.referencia = registro.id
        self.assertEqual(cobranca.processar_notificacao(self.db, "888", "req-boleto-01"), "processado")
        self.db.expire_all()
        loja = self.db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").one()
        self.assertEqual(loja.licenca_ate, "2026-11-10")

    def test_email_e_whatsapp_usam_o_texto_da_cobranca_sem_vazar_segredo(self):
        cobranca.definir_assinatura_de_pedido(self.db, _pedido())
        enviados = []

        def email(destino, assunto, corpo):
            enviados.append(("email", destino, assunto, corpo))

        def zap(telefone, texto):
            enviados.append(("zap", telefone, texto))

        with mock.patch.dict(os.environ, {
            "SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_USER": "conta@exemplo.com",
            "SMTP_PASSWORD": "senha-de-app", "SMTP_FROM": "conta@exemplo.com",
            "WHATSAPP_API_URL": "https://bot.exemplo.com/enviar", "WHATSAPP_API_TOKEN": "token-zap",
        }), mock.patch.object(cobranca, "enviar_email", side_effect=email), \
                mock.patch.object(cobranca, "enviar_whatsapp_api", side_effect=zap):
            self.assertEqual(cobranca.gerar_recorrencias(self.db, date(2026, 10, 5), "LOJA-1"), 1)
        self.assertEqual(enviados[0][1], "financeiro@exemplo.com")
        self.assertIn("https://www.mercadopago.com.br/mlb/payments/boleto/888", enviados[0][3])
        self.assertIn("23793", enviados[0][3])
        self.assertIn("00020126580014br.gov.bcb.pix", enviados[0][3])
        self.assertNotIn("senha-de-app", enviados[0][3])
        self.assertEqual(enviados[1][1], "+5511988887777")
        self.assertIn("00020126580014br.gov.bcb.pix", enviados[1][2])
        self.db.expire_all()
        self.assertEqual(self.db.query(cobranca.Cobranca).one().aviso_email, "enviado")
        self.assertEqual(self.db.query(cobranca.Cobranca).one().aviso_whatsapp, "enviado")

    def test_smtp_e_whatsapp_http_nao_colocam_segredo_na_mensagem_de_erro(self):
        with mock.patch.dict(os.environ, {
            "SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_USER": "conta@exemplo.com",
            "SMTP_PASSWORD": "senha-de-app", "SMTP_FROM": "conta@exemplo.com",
        }), mock.patch.object(cobranca.smtplib, "SMTP", side_effect=OSError("senha-de-app recusada")):
            with self.assertRaises(cobranca.ErroCobranca) as erro:
                cobranca.enviar_email("destino@exemplo.com", "Assunto", "Corpo")
        self.assertNotIn("senha-de-app", str(erro.exception))
        capturado = {}

        class Resposta:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, n=-1):
                return b""

        def abrir(pedido):
            capturado["url"] = pedido.full_url
            capturado["auth"] = pedido.get_header("Authorization")
            capturado["corpo"] = pedido.data
            return Resposta()

        with mock.patch.dict(os.environ, {
            "WHATSAPP_API_URL": "https://bot.exemplo.com/enviar", "WHATSAPP_API_TOKEN": "token-zap",
        }), mock.patch.object(cobranca, "_abrir", side_effect=abrir):
            cobranca.enviar_whatsapp_api("+5511988887777", "Olá")
        self.assertEqual(capturado["url"], "https://bot.exemplo.com/enviar")
        self.assertEqual(capturado["auth"], "Bearer token-zap")
        self.assertEqual(capturado["corpo"], '{"to":"+5511988887777","text":"Olá"}'.encode("utf-8"))
        with mock.patch.dict(os.environ, {"WHATSAPP_API_URL": "http://inseguro", "WHATSAPP_API_TOKEN": "x"}):
            with self.assertRaises(cobranca.ErroCobranca):
                cobranca.enviar_whatsapp_api("+5511988887777", "Olá")

    def test_admin_cadastra_por_curl_e_recusa_loja_e_token(self):
        http = TestClient(nuvem.app)
        url = "/v1/admin/cobrancas/assinatura"
        self.assertEqual(http.post(url, json=_pedido()).status_code, 401)
        self.assertEqual(http.post(url, json=_pedido(), headers=cabecalho()).status_code, 403)
        incompleto = _pedido()
        incompleto.pop("documento")
        admin = {"Authorization": "Bearer token-de-teste"}
        recusa = http.post(url, json=incompleto, headers=admin)
        self.assertEqual(recusa.status_code, 422)
        self.assertIn("CPF ou CNPJ", recusa.json()["detail"])
        with mock.patch.object(cobranca, "date") as relogio:
            relogio.today.return_value = date(2026, 10, 31)
            relogio.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            resposta = http.post(url, json=_pedido(), headers=admin)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        corpo = resposta.json()
        self.assertEqual(corpo["situacao"], "criada")
        self.assertEqual(corpo["valor_cent"], 24999)
        self.assertEqual(corpo["dia_vencimento"], 10)
        self.assertEqual(corpo["emitidas"], 0)
        self.assertEqual(corpo["proximo_vencimento"], "2026-11-10")
        self.assertEqual(corpo["whatsapp"], "+5511988887777")
        self.assertNotIn("52998224725", resposta.text)
        self.assertEqual(http.post(url, json=_pedido(chave_loja="NAO-EXISTE"), headers=admin).status_code, 404)
        self.assertEqual(cobranca.definir_assinatura_de_pedido(self.db, _pedido(valor_cent=30000)), "atualizada")
        self.db.expire_all()
        self.assertEqual(self.db.query(cobranca.Plano).filter_by(chave_loja="LOJA-1").one().valor_cent, 30000)

    def test_migracao_acrescenta_colunas_e_preserva_a_licenca(self):
        loja = self.db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").one()
        loja.licenca_ate = "2027-04-01"
        self.db.add(cobranca.Plano(id="e" * 32, chave_loja="LOJA-1", valor_cent=100, email_pagador="a@b.co",
                                   criado_em=cobranca.agora()))
        self.db.commit()
        self.db.execute(text("ALTER TABLE planos_mercadopago DROP COLUMN dia_vencimento"))
        self.db.commit()
        self.addCleanup(cobranca.garantir_esquema, self.db.get_bind())
        cobranca.garantir_esquema(self.db.get_bind())
        colunas = {c["name"] for c in inspect(self.db.get_bind()).get_columns("planos_mercadopago")}
        self.assertIn("dia_vencimento", colunas)
        self.assertIn("whatsapp", colunas)
        self.db.expire_all()
        self.assertEqual(self.db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").one().licenca_ate, "2027-04-01")
        self.assertEqual(self.db.query(cobranca.Plano).one().valor_cent, 100)


if __name__ == "__main__":
    unittest.main()
