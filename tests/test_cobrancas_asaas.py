"""Cobrança recorrente: confirmação remota, isolamento e renovação do PDV."""
from __future__ import annotations

import io
import os
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
    from backend import cobrancas, operacao_asaas


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteCobrancasAsaas(BaseChave):
    def setUp(self):
        super().setUp()
        self.ambiente = mock.patch.dict(os.environ, {"ASAAS_AMBIENTE": "sandbox",
                                                     "ASAAS_WEBHOOK_TOKEN": "segredo-do-webhook",
                                                     "ASAAS_API_KEY": "chave-ficticia-de-teste"})
        self.ambiente.start()
        self.addCleanup(self.ambiente.stop)
        self.db = nuvem.SessionLocal()
        self.addCleanup(self.db.close)
        self.limpar()
        self.addCleanup(self.limpar)
        preparar_lojas()
        self.http = TestClient(nuvem.app)
        self.dados = {"id": "pay_1", "subscription": "sub_1", "customer": "cus_1",
                      "billingType": "PIX", "status": "RECEIVED", "value": Decimal("99.00"),
                      "dueDate": "2026-10-15", "invoiceUrl": "https://sandbox.asaas.com/i/exemplo"}
        self.consulta = mock.patch.object(cobrancas, "consultar", side_effect=self.resposta)
        self.remoto = self.consulta.start()
        self.addCleanup(self.consulta.stop)
        cobrancas.vincular(self.db, "LOJA-1", "sub_1", 9900)

    def limpar(self):
        self.db.query(operacao_asaas.Tarefa).delete()
        self.db.query(operacao_asaas.Worker).delete()
        self.db.query(cobrancas.Evento).delete()
        self.db.query(cobrancas.Cobranca).delete()
        self.db.query(cobrancas.Assinatura).delete()
        self.db.commit()

    def resposta(self, caminho):
        if caminho == "/subscriptions/sub_1":
            return {"id": "sub_1", "customer": "cus_1", "cycle": "MONTHLY", "status": "ACTIVE",
                    "billingType": "PIX", "value": Decimal("99.00")}
        if caminho.startswith("/subscriptions/sub_1/payments"):
            return {"data": [{"id": self.dados["id"]}], "hasMore": False}
        return dict(self.dados)

    def enviar(self, evento="evt_1", headers=None, processar=True, **alteracoes):
        dados = {"id": evento, "event": "PAYMENT_RECEIVED",
                 "payment": {"id": "pay_1", "subscription": "sub_1", "value": 999999,
                             "status": "RECEIVED"}}
        dados.update(alteracoes)
        resposta = self.http.post("/v1/webhooks/asaas", json=dados,
                                  headers={"asaas-access-token": "segredo-do-webhook"} if headers is None else headers)
        if processar and resposta.status_code == 200:
            self.db.expire_all()
            operacao_asaas.executar_uma(self.db)
        return resposta

    def validade(self, chave="LOJA-1"):
        self.db.expire_all()
        return self.db.query(nuvem.Loja).filter_by(chave_loja=chave).one().licenca_ate

    def test_pagamento_confere_api_e_renova_so_a_loja_vinculada(self):
        self.assertEqual(self.enviar().status_code, 200)
        self.assertEqual(self.validade(), "2026-11-15")
        self.assertIsNone(self.validade("LOJA-2"))
        self.assertEqual(self.db.get(cobrancas.Cobranca, "pay_1").valor_cent, 9900)

    def test_webhook_exige_segredo_proprio_e_configuracao(self):
        for headers in ({}, cabecalho(), {"asaas-access-token": "errado"}):
            self.assertEqual(self.enviar(headers=headers).status_code, 401)
        with mock.patch.dict(os.environ, {"ASAAS_WEBHOOK_TOKEN": ""}):
            self.assertEqual(self.enviar().status_code, 503)
        self.assertIsNone(self.validade())

    def test_pendente_vencida_e_dinheiro_nao_liberam(self):
        for numero, status in enumerate(("PENDING", "OVERDUE", "RECEIVED_IN_CASH", "REFUNDED",
                                        "CHARGEBACK_REQUESTED")):
            self.dados["status"] = status
            self.assertEqual(self.enviar(f"evt_{numero}").status_code, 200)
            self.assertIsNone(self.validade())

    def test_evento_repetido_nao_duplica_nem_acrescenta_mes(self):
        self.enviar()
        self.remoto.reset_mock()
        self.assertEqual(self.enviar().json()["situacao"], "repetido")
        self.remoto.assert_not_called()
        self.assertEqual(self.enviar("evt_2").status_code, 200)
        self.assertEqual(self.validade(), "2026-11-15")
        self.assertEqual(self.db.query(cobrancas.Cobranca).count(), 1)
        self.assertEqual(self.db.query(cobrancas.Evento).count(), 2)

    def test_evento_antigo_consulta_estado_atual_e_estorno_retira_validade_no_servidor(self):
        self.enviar()
        self.dados["status"] = "REFUNDED"
        self.assertEqual(self.enviar("evt_estorno", event="PAYMENT_REFUNDED").status_code, 200)
        self.assertIsNone(self.validade())
        self.enviar("evt_recebido_antigo")
        self.assertIsNone(self.validade())

    def test_divergencias_e_payload_invalido_nao_liberam(self):
        for campo, valor in (("customer", "cus_outro"), ("subscription", "sub_outra"),
                             ("id", "pay_outro"), ("value", Decimal("9.90")), ("dueDate", "invalida"),
                             ("billingType", "CREDIT_CARD")):
            with self.subTest(campo=campo):
                original = self.dados[campo]
                self.dados[campo] = valor
                self.assertEqual(self.enviar(f"evt_{campo}").status_code, 200)
                self.db.expire_all()
                self.assertEqual(self.db.get(operacao_asaas.Tarefa, f"evento:evt_{campo}").estado, "erro")
                self.assertIsNone(self.validade())
                self.dados[campo] = original
        self.assertEqual(self.enviar(event="SUBSCRIPTION_CREATED").status_code, 422)
        self.assertEqual(self.enviar(evento="../../segredo").status_code, 422)

    def test_assinatura_desconhecida_e_avulsa_nao_liberam(self):
        resposta = self.enviar(payment={"id": "pay_1", "subscription": "sub_desconhecida"})
        self.assertEqual(resposta.json()["situacao"], "enfileirado")
        self.db.expire_all()
        self.assertEqual(self.db.get(operacao_asaas.Tarefa, "evento:evt_1").estado, "erro")
        self.assertEqual(self.enviar(payment={"id": "pay_1"}).json()["situacao"], "sem_assinatura")
        self.assertIsNone(self.validade())

    def test_falha_remota_nao_marca_evento_e_permite_retentativa(self):
        self.remoto.side_effect = cobrancas.AsaasIndisponivel("Falha de teste")
        self.assertEqual(self.enviar().status_code, 200)
        self.assertEqual(self.db.query(cobrancas.Evento).count(), 0)
        self.assertIsNone(self.validade())
        self.remoto.side_effect = self.resposta
        tarefa = self.db.get(operacao_asaas.Tarefa, "evento:evt_1")
        tarefa.proxima_em = "2000-01-01 00:00:00"
        self.db.commit()
        self.assertEqual(self.enviar().status_code, 200)
        self.assertEqual(self.validade(), "2026-11-15")

    def test_mes_calendario_ano_bissexto_e_dinheiro_exato(self):
        self.assertEqual(cobrancas.fim_periodo(date(2026, 1, 31)), date(2026, 2, 28))
        self.assertEqual(cobrancas.fim_periodo(date(2028, 1, 31)), date(2028, 2, 29))
        self.assertEqual(cobrancas.fim_periodo(date(2026, 12, 31)), date(2027, 1, 31))
        self.assertEqual(cobrancas.centavos(Decimal("99.90")), 9990)
        for invalido in ("NaN", "Infinity", "-1", "0", "1.001", None, True):
            with self.assertRaises(cobrancas.ErroCobranca):
                cobrancas.centavos(invalido)

    def test_conciliacao_recupera_pagamento_sem_webhook(self):
        self.assertEqual(cobrancas.reconciliar(self.db, "LOJA-1"), 1)
        self.assertEqual(self.validade(), "2026-11-15")

    def test_confirmado_libera_e_loja_desativada_nao_e_reativada(self):
        lojas.definir_ativa(self.db, "LOJA-1", False)
        self.dados["status"] = "CONFIRMED"
        self.assertEqual(self.enviar().status_code, 200)
        self.assertEqual(self.validade(), "2026-11-15")
        self.assertEqual(self.http.get("/v1/licenca", headers=cabecalho()).status_code, 403)

    def test_comando_manual_nao_concorre_com_a_validade_do_asaas(self):
        with self.assertRaises(lojas.ErroLoja):
            lojas.definir_assinatura(self.db, "LOJA-1", date(2027, 1, 1))
        lojas.definir_assinatura(self.db, "LOJA-2", date(2027, 1, 1))
        self.assertEqual(self.validade("LOJA-2"), "2027-01-01")

    def test_conciliacao_paginada_e_pagamento_antigo_nao_encurta_o_novo(self):
        def resposta(caminho):
            if "?limit=100&offset=0" in caminho:
                return {"data": [{"id": "pay_1"}], "hasMore": True}
            if "?limit=100&offset=1" in caminho:
                return {"data": [{"id": "pay_2"}], "hasMore": False}
            if caminho == "/payments/pay_2":
                return dict(self.dados, id="pay_2", dueDate="2026-11-15")
            return self.resposta(caminho)
        self.remoto.side_effect = resposta
        self.assertEqual(cobrancas.reconciliar(self.db, "LOJA-1"), 2)
        self.enviar()
        self.assertEqual(self.validade(), "2026-12-15")

    def test_preserva_validade_manual_anterior_ao_vinculo(self):
        assinatura = self.db.get(cobrancas.Assinatura, "sub_1")
        assinatura.validade_anterior = "2027-01-01"
        self.db.commit()
        self.enviar()
        self.assertEqual(self.validade(), "2027-01-01")
        self.dados["status"] = "REFUNDED"
        self.enviar("evt_estorno")
        self.assertEqual(self.validade(), "2027-01-01")

    def test_vinculo_recusa_duplicidade_ambiente_errado_e_plano_divergente(self):
        with self.assertRaises(cobrancas.ErroCobranca):
            cobrancas.vincular(self.db, "LOJA-2", "sub_1", 9900)
        with self.assertRaises(cobrancas.ErroCobranca):
            cobrancas.vincular(self.db, "LOJA-2", "sub_outra", 5000)
        with mock.patch.dict(os.environ, {"ASAAS_AMBIENTE": "producao"}):
            self.assertEqual(self.enviar().status_code, 200)
            self.db.expire_all()
            self.assertEqual(self.db.get(operacao_asaas.Tarefa, "evento:evt_1").estado, "erro")
        self.assertIsNone(self.validade())

    def test_pagamento_chega_ao_pdv_pelo_fluxo_de_licenca_existente(self):
        vencimento = date.today() + timedelta(days=3)
        self.dados["dueDate"] = vencimento.isoformat()
        self.assertEqual(self.enviar().status_code, 200)
        banco = BancoDados(":memory:")
        self.addCleanup(banco.fechar)
        banco.cfg_set("licenca_exigir", "S")
        banco.cfg_set("api_url", "https://nuvem/v1/sincronizar")
        banco.cfg_set("api_token", "token-da-loja-1")
        http = mock.Mock()
        http.get.side_effect = lambda url, **kw: self.http.get(url.replace("https://nuvem", ""), **kw)
        self.assertTrue(licenca_nuvem.renovar(banco, http, forcar=True))
        self.assertEqual(licenca.estado(banco).expira_em, cobrancas.fim_periodo(vencimento))

    def test_cli_encaminha_listagem_e_conciliacao(self):
        saida = io.StringIO()
        with redirect_stdout(saida):
            self.assertEqual(lojas.main(["cobranca", "listar"]), 0)
            self.assertEqual(lojas.main(["cobranca", "conciliar", "LOJA-1"]), 0)
        self.assertIn("9900 centavos", saida.getvalue())
        self.assertIn("Cobranças conciliadas: 1", saida.getvalue())


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteClienteAsaas(unittest.TestCase):
    def test_endereco_cabecalhos_timeout_e_decimal(self):
        with mock.patch.dict(os.environ, {"ASAAS_API_KEY": "teste", "ASAAS_AMBIENTE": "sandbox"}), \
                mock.patch.object(cobrancas, "urlopen") as abrir:
            abrir.return_value.__enter__.return_value.read.return_value = b'{"value":99.90}'
            self.assertEqual(cobrancas.consultar("/payments/pay_1")["value"], Decimal("99.90"))
            requisicao = abrir.call_args.args[0]
            self.assertEqual(requisicao.full_url, "https://api-sandbox.asaas.com/v3/payments/pay_1")
            self.assertEqual(requisicao.get_header("Access_token"), "teste")
            self.assertEqual(abrir.call_args.kwargs["timeout"], 10)

    def test_erros_nao_expoem_segredos(self):
        for erro in (URLError("segredo"), HTTPError("url-secreta", 401, "segredo", {}, None),
                     TimeoutError("segredo")):
            with mock.patch.dict(os.environ, {"ASAAS_API_KEY": "teste", "ASAAS_AMBIENTE": "sandbox"}), \
                    mock.patch.object(cobrancas, "urlopen", side_effect=erro), \
                    self.assertRaises(cobrancas.AsaasIndisponivel) as resultado:
                cobrancas.consultar("/payments/pay_1")
            self.assertNotIn("segredo", str(resultado.exception))


if __name__ == "__main__":
    unittest.main()
