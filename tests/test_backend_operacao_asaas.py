"""Inbox/agenda em SQLite e concorrência real no PostgreSQL exclusivo de testes."""
from __future__ import annotations

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import mock

from tests.test_nuvem import TestClient, nuvem

if nuvem is not None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from backend import cobrancas, operacao_asaas as op
    from backend.database import Base, normalizar_url


class CenarioOperacao:
    postgres = False

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"ASAAS_AMBIENTE": "sandbox",
                                                "ASAAS_WEBHOOK_TOKEN": "teste-webhook",
                                                "PDV_API_TOKEN": "token-de-teste"})
        self.env.start()
        self.addCleanup(self.env.stop)
        if self.postgres:
            self.engine = create_engine(normalizar_url(os.environ["PDV_TESTE_NUVEM_DB_URL"]))
        else:
            self.engine = create_engine("sqlite://", poolclass=StaticPool,
                                        connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.fabrica = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.fabrica()
        self.addCleanup(self.db.close)
        self.limpar()
        self.addCleanup(self.limpar)
        self.db.add(nuvem.Loja(chave_loja="OPERACAO", nome="Teste", token_hash="teste-op",
                               ativa=True))
        self.db.add(cobrancas.Assinatura(id="sub_op", chave_loja="OPERACAO", cliente="cus_op",
                                         valor_cent=9900, ambiente="sandbox", criada_em=cobrancas.agora()))
        self.db.commit()
        consulta = mock.patch.object(cobrancas, "consultar", side_effect=self.resposta)
        self.remoto = consulta.start()
        self.addCleanup(consulta.stop)

    def limpar(self):
        self.db.rollback()
        for modelo in (op.Tarefa, op.Worker, cobrancas.Evento, cobrancas.Cobranca,
                       cobrancas.Assinatura, nuvem.Loja):
            self.db.query(modelo).delete()
        self.db.commit()
        self.db.expunge_all()

    def resposta(self, caminho):
        if "/subscriptions/" in caminho:
            return {"data": [{"id": "pay_op"}], "hasMore": False}
        return {"id": caminho.rsplit("/", 1)[-1], "subscription": "sub_op", "customer": "cus_op",
                "billingType": "PIX", "status": "RECEIVED", "value": "99.00", "dueDate": "2026-10-15"}

    def receber(self, evento="evt_op"):
        return op.receber(self.db, evento, "sub_op", "pay_op", "PAYMENT_RECEIVED")

    def tarefa(self, id="evento:evt_op"):
        self.db.expire_all()
        return self.db.get(op.Tarefa, id)

    def validade(self):
        self.db.expire_all()
        return self.db.query(nuvem.Loja).filter_by(chave_loja="OPERACAO").one().licenca_ate

    def cliente(self):
        def banco():
            with self.fabrica() as db:
                yield db
        nuvem.app.dependency_overrides[nuvem.get_db] = banco
        self.addCleanup(nuvem.app.dependency_overrides.clear)
        return TestClient(nuvem.app)


@unittest.skipIf(nuvem is None, "Dependências do backend ausentes")
class TesteContratoInsercao(unittest.TestCase):
    def test_inclusao_usa_returning_sem_depender_de_rowcount_do_driver(self):
        from sqlalchemy.dialects import postgresql, sqlite
        for nome, dialeto in (("postgresql", postgresql.dialect()), ("sqlite", sqlite.dialect())):
            for retornado, esperado in (("evento:evt_contrato", True), (None, False)):
                with self.subTest(dialeto=nome, retornado=retornado):
                    db = mock.Mock()
                    db.bind.dialect.name = nome
                    # Sem rowcount no contrato: INSERT pode devolver -1 ou nem expô-lo.
                    resultado = mock.Mock(spec_set=["scalar_one_or_none"])
                    resultado.scalar_one_or_none.return_value = retornado
                    db.execute.return_value = resultado
                    registro = op.Tarefa(
                        id="evento:evt_contrato", tipo="evento", assinatura="sub_op",
                        pagamento="pay_op", evento="PAYMENT_RECEIVED",
                        criada_em="2026-10-16 16:00:00", proxima_em="2026-10-16 16:00:00",
                        estado="pendente")
                    self.assertIs(op._inserir(db, registro), esperado)
                    comando = db.execute.call_args.args[0]
                    sql = str(comando.compile(dialect=dialeto))
                    self.assertIn("ON CONFLICT (id) DO NOTHING RETURNING", sql)
                    self.assertEqual(list(comando._returning), [op.Tarefa.__table__.c.id])
                    resultado.scalar_one_or_none.assert_called_once_with()


@unittest.skipIf(nuvem is None, "Dependências do backend ausentes")
class TesteOperacaoSQLite(CenarioOperacao, unittest.TestCase):
    def test_webhook_persiste_sem_http_e_repeticao_nao_duplica(self):
        cliente = self.cliente()
        dados = {"id": "evt_op", "event": "PAYMENT_RECEIVED",
                 "payment": {"id": "pay_op", "subscription": "sub_op"}}
        for esperado in ("enfileirado", "repetido"):
            resposta = cliente.post("/v1/webhooks/asaas", json=dados,
                                    headers={"asaas-access-token": "teste-webhook"})
            self.assertEqual(resposta.status_code, 200)
            self.assertEqual(resposta.json()["situacao"], esperado)
        self.remoto.assert_not_called()
        self.assertEqual(self.db.query(op.Tarefa).count(), 1)
        self.assertIsNone(self.validade())
        self.assertTrue(op.executar_uma(self.db))
        self.assertEqual(self.validade(), "2026-11-15")
        self.assertEqual(self.tarefa().estado, "concluida")
        self.assertEqual(self.db.query(cobrancas.Evento).count(), 1)

    def test_commit_inbox_falha_retorna_503_sem_confirmar(self):
        cliente = self.cliente()
        from sqlalchemy.orm import Session
        with mock.patch.object(Session, "commit", side_effect=RuntimeError("segredo")):
            resposta = cliente.post("/v1/webhooks/asaas", headers={"asaas-access-token": "teste-webhook"},
                                    json={"id": "evt_op", "event": "PAYMENT_RECEIVED",
                                          "payment": {"id": "pay_op", "subscription": "sub_op"}})
        self.assertEqual(resposta.status_code, 503)
        self.assertNotIn("segredo", resposta.text)
        self.assertEqual(self.db.query(op.Tarefa).count(), 0)

    def test_conflito_de_evento_e_recusado_sem_alterar_inbox(self):
        self.receber()
        with self.assertRaises(cobrancas.ErroCobranca):
            op.receber(self.db, "evt_op", "sub_op", "pay_outro", "PAYMENT_RECEIVED")
        self.db.rollback()
        self.assertEqual(self.tarefa().pagamento, "pay_op")

    def test_retentativa_backoff_persistido_e_reinicio(self):
        self.receber()
        self.remoto.side_effect = cobrancas.AsaasIndisponivel("Asaas indisponível.")
        self.assertTrue(op.executar_uma(self.db))
        tarefa = self.tarefa()
        self.assertEqual(tarefa.falhas_seguidas, 1)
        self.assertEqual(tarefa.ultimo_erro, "Asaas indisponível.")
        proxima = op.datetime.fromisoformat(tarefa.proxima_em)
        self.assertEqual(self.receber(), "repetido")
        self.assertEqual(self.tarefa().proxima_em, op.texto(proxima))
        self.assertEqual(self.tarefa().falhas_seguidas, 1)
        self.assertFalse(op.executar_uma(self.db, proxima - timedelta(seconds=1)))
        self.db.close()
        with self.fabrica() as outra:
            self.assertTrue(op.executar_uma(outra, proxima))
        self.assertEqual(self.tarefa().falhas_seguidas, 2)
        self.remoto.side_effect = self.resposta
        with self.fabrica() as outra:
            self.assertTrue(op.executar_uma(outra, op.datetime.fromisoformat(self.tarefa().proxima_em)))
        self.assertEqual(self.validade(), "2026-11-15")
        self.assertEqual(self.tarefa().falhas_seguidas, 0)
        self.assertIsNotNone(self.tarefa().ultimo_erro_em)

    def test_commit_worker_falha_nao_deixa_licenca_ou_evento_parcial(self):
        self.receber()
        commit = self.db.commit
        with mock.patch.object(self.db, "commit") as falho:
            # O segundo commit deve ser real para testar a persistência do diagnóstico.
            def confirmar():
                if falho.call_count == 1:
                    raise RuntimeError("senha-secreta")
                return commit()
            falho.side_effect = confirmar
            op.executar_uma(self.db)
        self.assertIsNone(self.validade())
        self.assertEqual(self.db.query(cobrancas.Evento).count(), 0)
        self.assertEqual(self.db.query(cobrancas.Cobranca).count(), 0)
        self.assertEqual(self.tarefa().estado, "erro")
        self.assertNotIn("senha", self.tarefa().ultimo_erro)

    def test_interrupcao_reverte_lock_e_outro_worker_retoma(self):
        self.receber()
        with self.fabrica() as db, mock.patch.object(cobrancas, "processar", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                op.executar_uma(db)
        self.assertEqual(self.tarefa().estado, "pendente")
        self.assertTrue(op.executar_uma(self.db))
        self.assertEqual(self.tarefa().estado, "concluida")

    def test_agenda_persistente_idempotente_e_conciliacao_recupera_webhook_perdido(self):
        agora = op.instante()
        op.agendar(self.db, agora)
        op.agendar(self.db, agora + timedelta(seconds=10))
        self.assertEqual(self.db.query(op.Tarefa).count(), 1)
        self.assertTrue(op.executar_uma(self.db, agora))
        self.assertEqual(self.validade(), "2026-11-15")
        proxima = self.tarefa("conciliar:sub_op").proxima_em
        self.db.close()
        with self.fabrica() as outra:
            op.agendar(outra, agora + timedelta(seconds=20))
            self.assertFalse(op.executar_uma(outra, agora + timedelta(seconds=20)))
        self.assertEqual(self.tarefa("conciliar:sub_op").proxima_em, proxima)
        self.assertEqual(proxima, op.texto(agora + timedelta(seconds=op.INTERVALO_CONCILIACAO)))

    def test_conciliacao_falha_reverte_todas_as_cobrancas_e_retem_erro(self):
        def resposta(caminho):
            if "/subscriptions/" in caminho:
                return {"data": [{"id": "pay_op"}, {"id": "pay_z"}], "hasMore": False}
            if caminho.endswith("pay_z"):
                raise cobrancas.AsaasIndisponivel("Falha na segunda cobrança.")
            return self.resposta(caminho)
        self.remoto.side_effect = resposta
        op.agendar(self.db, op.instante())
        op.executar_uma(self.db)
        self.assertIsNone(self.validade())
        self.assertEqual(self.db.query(cobrancas.Cobranca).count(), 0)
        self.assertEqual(self.tarefa("conciliar:sub_op").estado, "erro")

    def test_indicadores_admin_falhas_atraso_e_recuperacao(self):
        cliente = self.cliente()
        url = "/v1/admin/cobrancas/operacao"
        self.assertEqual(cliente.get(url).status_code, 401)
        self.db.query(nuvem.Loja).update({"token_hash": nuvem.hash_token("token-loja")})
        self.db.commit()
        self.assertEqual(cliente.get(url, headers={"Authorization": "Bearer token-loja"}).status_code, 403)
        admin = {"Authorization": "Bearer token-de-teste"}
        self.assertFalse(cliente.get(url, headers=admin).json()["pronto"])
        self.assertEqual(op.ciclo(self.fabrica), 1)
        self.assertTrue(cliente.get(url, headers=admin).json()["pronto"])
        futuro = op.instante() + timedelta(hours=7)
        estado = op.estado(self.db, futuro)
        self.assertIn("worker_sem_batida", estado["alertas"])
        self.assertIn("conciliacao_atrasada", estado["alertas"])
        self.receber()
        self.remoto.side_effect = RuntimeError("senha-ou-token")
        with self.assertLogs("pdv.asaas.operacao", level="ERROR") as logs:
            op.executar_uma(self.db)
        resposta = cliente.get(url, headers=admin).json()
        self.assertEqual(resposta["tarefas_com_erro"], 1)
        self.assertTrue(resposta["falhas"])
        self.assertNotIn("senha-ou-token", str(resposta) + str(logs.output))
        self.assertIn("ALERTA_ASAAS", str(logs.output))

    def test_migracao_aditiva_preserva_dados_e_eventos_antigos(self):
        self.db.add(cobrancas.Evento(id="evt_legado", cobranca="pay_op",
                                     recebido_em=cobrancas.agora()))
        self.db.commit()
        op.Tarefa.__table__.drop(self.engine)
        op.Worker.__table__.drop(self.engine)
        Base.metadata.create_all(self.engine)
        self.assertEqual(self.db.query(cobrancas.Assinatura).count(), 1)
        self.assertIsNotNone(self.db.get(cobrancas.Evento, "evt_legado"))
        self.receber("evt_legado")
        self.remoto.reset_mock()
        self.assertTrue(op.executar_uma(self.db))
        self.remoto.assert_not_called()
        self.assertEqual(self.tarefa("evento:evt_legado").estado, "concluida")
        self.assertEqual(self.db.query(cobrancas.Evento).count(), 1)

    def test_pendencia_antiga_alerta_mesmo_se_retentativa_esta_no_futuro(self):
        self.receber()
        tarefa = self.tarefa()
        tarefa.criada_em = op.texto(op.instante() - timedelta(minutes=16))
        tarefa.proxima_em = op.texto(op.instante() + timedelta(hours=1))
        self.db.commit()
        indicadores = op.estado(self.db)
        self.assertEqual(indicadores["eventos_pendentes"], 1)
        self.assertEqual(indicadores["pendencias"][0]["id"], tarefa.id)
        self.assertIn("fila_atrasada", indicadores["alertas"])

    def test_cli_lote_unico_retorna_sucesso_ou_alerta(self):
        with mock.patch.object(nuvem, "SessionLocal", self.fabrica), \
                mock.patch.object(op.logging, "basicConfig"):
            self.assertEqual(op.main(["--uma-vez"]), 0)
            self.receber()
            self.remoto.side_effect = cobrancas.AsaasIndisponivel("Falha de teste.")
            self.assertEqual(op.main(["--uma-vez"]), 1)


@unittest.skipUnless(nuvem is not None and os.environ.get("PDV_TESTE_NUVEM_DB_URL", "").startswith(
    ("postgresql://", "postgres://", "postgresql+psycopg://")), "Requer PostgreSQL exclusivo de testes")
class TesteConcorrenciaPostgreSQL(CenarioOperacao, unittest.TestCase):
    postgres = True

    def test_agendadores_concorrentes_nao_duplicam_nem_postergam_agenda(self):
        barreira = threading.Barrier(2)
        agora = op.instante()
        def agendar():
            with self.fabrica() as db:
                barreira.wait(timeout=10)
                op.agendar(db, agora)
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda _: agendar(), range(2)))
        self.assertEqual(self.db.query(op.Tarefa).count(), 1)
        op.agendar(self.db, agora + timedelta(hours=1))
        self.assertEqual(self.tarefa("conciliar:sub_op").proxima_em, op.texto(agora))

    def test_entregas_concorrentes_mesmo_evento_e_commit_unico(self):
        barreira = threading.Barrier(2)
        def enviar():
            with self.fabrica() as db:
                barreira.wait(timeout=10)
                return op.receber(db, "evt_op", "sub_op", "pay_op", "PAYMENT_RECEIVED")
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: enviar(), range(2)))
        self.assertCountEqual(resultados, ["enfileirado", "repetido"])
        self.assertEqual(self.db.query(op.Tarefa).count(), 1)

    def test_skip_locked_impede_dois_workers_mesmo_evento(self):
        self.receber()
        entrou, liberar = threading.Event(), threading.Event()
        def resposta(caminho):
            entrou.set()
            if not liberar.wait(10):
                raise RuntimeError("Tempo limite do teste.")
            return self.resposta(caminho)
        self.remoto.side_effect = resposta
        def executar():
            with self.fabrica() as db:
                return op.executar_uma(db)
        def reenviar():
            with self.fabrica() as db:
                return op.receber(db, "evt_op", "sub_op", "pay_op", "PAYMENT_RECEIVED")
        with ThreadPoolExecutor(max_workers=2) as executor:
            primeiro = executor.submit(executar)
            try:
                self.assertTrue(entrou.wait(10))
                self.assertEqual(executor.submit(reenviar).result(timeout=3), "repetido")
                self.assertFalse(executor.submit(executar).result(timeout=10))
            finally:
                liberar.set()
            self.assertTrue(primeiro.result(timeout=10))
        self.assertEqual(self.remoto.call_count, 1)
        self.assertEqual(self.db.query(cobrancas.Evento).count(), 1)
        self.assertEqual(self.tarefa().tentativas, 1)

    def test_eventos_diferentes_mesma_assinatura_serializam_sem_duplicar_validade(self):
        self.receber()
        self.receber("evt_outro")
        barreira = threading.Barrier(2)
        def executar():
            with self.fabrica() as db:
                barreira.wait(timeout=10)
                return op.executar_uma(db)
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: executar(), range(2)))
        self.assertEqual(resultados, [True, True])
        self.assertEqual(self.db.query(cobrancas.Evento).count(), 2)
        self.assertEqual(self.db.query(cobrancas.Cobranca).count(), 1)
        self.assertEqual(self.validade(), "2026-11-15")

    # Também executados no driver real: rollback de commit e retomada após interrupção.
    test_commit_worker_falha_nao_deixa_licenca_ou_evento_parcial = (
        TesteOperacaoSQLite.test_commit_worker_falha_nao_deixa_licenca_ou_evento_parcial)
    test_commit_inbox_falha_retorna_503_sem_confirmar = (
        TesteOperacaoSQLite.test_commit_inbox_falha_retorna_503_sem_confirmar)
    test_interrupcao_reverte_lock_e_outro_worker_retoma = (
        TesteOperacaoSQLite.test_interrupcao_reverte_lock_e_outro_worker_retoma)
    test_retentativa_backoff_persistido_e_reinicio = (
        TesteOperacaoSQLite.test_retentativa_backoff_persistido_e_reinicio)
    test_agenda_persistente_idempotente_e_conciliacao_recupera_webhook_perdido = (
        TesteOperacaoSQLite.test_agenda_persistente_idempotente_e_conciliacao_recupera_webhook_perdido)
    test_migracao_aditiva_preserva_dados_e_eventos_antigos = (
        TesteOperacaoSQLite.test_migracao_aditiva_preserva_dados_e_eventos_antigos)
