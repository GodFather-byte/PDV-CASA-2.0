"""O Neon só acorda quando há o que enviar, no fechamento, ou quando o celular pede."""
from __future__ import annotations

import unittest
from unittest import mock

from src.core import formatacao as fmt
from src.sync.ociosidade import (
    CHAVE_FLUSH, deve_contato, dentro_do_expediente, lote_seg, pedir_flush,
)
from src.sync.sincronizador import Sincronizador
from tests.base import BaseTeste
from tests.test_caixa import BaseCaixa

try:
    from tests.test_nuvem import ADMIN, TestClient, cabecalho, nuvem, preparar_lojas
    from backend.database import SessionLocal, argumentos_engine
    from backend.memoria_nuvem import memoria
except (ImportError, RuntimeError):
    TestClient = nuvem = memoria = None
    SessionLocal = argumentos_engine = preparar_lojas = ADMIN = cabecalho = None


class TesteDecisao(BaseTeste):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("api_url", "https://nuvem.exemplo")
        self.banco.cfg_set("api_token", "segredo")
        self.banco.cfg_set("atualizacao_consultada_em", fmt.agora())
        self.banco.cfg_set("atualizacao_pacote_em", fmt.agora())

    def test_sem_pendencia_nao_chama_o_banco(self):
        self.assertFalse(deve_contato(self.banco, 2000, 2000, False))

    def test_lote_segura_pendencia_e_o_fechamento_fura(self):
        self.assertEqual(lote_seg(self.banco), 900)
        with mock.patch("src.sync.ociosidade.ha_pendencia", return_value=True), \
                mock.patch("src.sync.ociosidade.manutencao_devida", return_value=False):
            self.assertFalse(deve_contato(self.banco, 1000, 1000, False))
            self.assertTrue(deve_contato(self.banco, 1900, 1000, False))
            self.assertTrue(deve_contato(self.banco, 1060, 1000, True))

    def test_expediente_cruza_a_meia_noite(self):
        self.banco.cfg_set("sync_expediente_de", "18:00")
        self.banco.cfg_set("sync_expediente_ate", "06:00")
        self.assertTrue(dentro_do_expediente(self.banco, "2026-10-03 22:10:00"))
        self.assertTrue(dentro_do_expediente(self.banco, "2026-10-04 03:00:00"))
        self.assertFalse(dentro_do_expediente(self.banco, "2026-10-03 12:00:00"))
        self.banco.cfg_set("sync_expediente_de", "")
        self.assertTrue(dentro_do_expediente(self.banco, "2026-10-03 12:00:00"))

    def test_sincronizador_respeita_o_lote_e_o_pedido_local(self):
        sync = Sincronizador(self.banco, http=object())
        with mock.patch.object(Sincronizador, "_rodada", return_value=True) as envio, \
                mock.patch.object(Sincronizador, "_pedido_remoto", return_value=None), \
                mock.patch("src.sync.ociosidade.ha_pendencia", return_value=True), \
                mock.patch("src.sync.ociosidade.manutencao_devida", return_value=False):
            with mock.patch("src.sync.sincronizador.time.time", return_value=1000):
                self.assertTrue(sync.rodada())
            with mock.patch("src.sync.sincronizador.time.time", return_value=1060):
                self.assertTrue(sync.rodada())
            self.assertEqual(envio.call_count, 1)
            pedir_flush(self.banco)
            with mock.patch("src.sync.sincronizador.time.time", return_value=1060):
                self.assertTrue(sync.rodada())
            self.assertEqual(envio.call_count, 2)
            self.assertEqual(self.banco.cfg(CHAVE_FLUSH), "")


class TesteFechamentoPedeFlush(BaseCaixa):
    def test_fechar_turno_pede_envio_imediato(self):
        self.turnos.fechar(self.turno, self.adm, 10000)
        self.assertTrue(self.banco.cfg(CHAVE_FLUSH))


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteMemoriaSemBanco(BaseTeste):
    def setUp(self):
        super().setUp()
        preparar_lojas()
        memoria.zerar()
        self.http = TestClient(nuvem.app)

    def test_health_e_pedido_nao_abrem_o_neon(self):
        with mock.patch("backend.database.SessionLocal", side_effect=AssertionError("neon")), \
                mock.patch("backend.main.SessionLocal", side_effect=AssertionError("neon")):
            self.assertEqual(self.http.get("/health").json()["status"], "ok")
            r = self.http.get("/v1/sync/pedido", headers={"Authorization": "Bearer nada"})
            self.assertEqual(r.status_code, 200)
            self.assertFalse(r.json()["conhecido"])
            r = self.http.post("/v1/sync/pedido", headers={"Authorization": "Bearer nada"})
            self.assertFalse(r.json()["conhecido"])

    def test_botao_grava_pedido_e_o_caixa_ve_sem_banco(self):
        memoria.lembrar_token("token-da-loja-1", "LOJA-1")
        memoria.lembrar_sessao("sessao-do-dono", "LOJA-1")
        with mock.patch("backend.database.SessionLocal", side_effect=AssertionError("neon")), \
                mock.patch("backend.main.SessionLocal", side_effect=AssertionError("neon")):
            pedido = self.http.post("/v1/sync/pedido", headers={"Authorization": "Bearer sessao-do-dono"}).json()
            self.assertTrue(pedido["pedido"])
            visto = self.http.get("/v1/sync/pedido", headers=cabecalho()).json()
            self.assertTrue(visto["pedido"])
            self.assertEqual(visto["id"], pedido["id"])
            self.http.post("/v1/sync/concluido", json={"momento": "2026-10-03 21:15:00", "id": pedido["id"]},
                           headers=cabecalho())
            estado = self.http.get("/v1/sync/estado", headers={"Authorization": "Bearer sessao-do-dono"}).json()
            self.assertEqual(estado["momento"], "2026-10-03 21:15:00")
            self.assertEqual(estado["id"], pedido["id"])

    def test_pool_nao_tem_laco_de_keepalive(self):
        postgres = argumentos_engine("postgresql+psycopg://u:p@h/db")
        self.assertTrue(postgres["pool_pre_ping"])
        self.assertEqual(postgres["pool_recycle"], 300)
        self.assertTrue(postgres["pool_use_lifo"])
        self.assertNotIn("pool_recycle", argumentos_engine("sqlite:///x.db"))

    def test_segunda_leitura_do_resumo_nao_abre_sessao(self):
        from backend.cache_leitura import limpar
        limpar()
        self.http.post("/v1/admin/lojas/LOJA-1/painel", json={"senha": "senha-forte-1"}, headers=ADMIN)
        token = self.http.post("/v1/painel/login", json={"loja": "LOJA-1", "senha": "senha-forte-1"}).json()["token"]
        cab = {"Authorization": f"Bearer {token}", "X-PDV-Leitura": "1"}
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=cab).status_code, 200)
        original = SessionLocal
        chamadas = {"n": 0}

        def contar():
            chamadas["n"] += 1
            return original()

        with mock.patch("backend.database.SessionLocal", contar), \
                mock.patch("backend.main.SessionLocal", contar), \
                mock.patch("backend.painel.SessionLocal", contar):
            r = self.http.get("/v1/painel/resumo", headers=cab)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(chamadas["n"], 0)
        self.assertIn("atualizacao_seg", r.json())
