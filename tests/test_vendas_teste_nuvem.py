"""Vendas de teste apagadas: caixa -> nuvem e painel do dono -> caixa (API de verdade via TestClient)."""
from __future__ import annotations

import unittest

from src.controllers.vendas_teste_controller import VendasTesteController
from tests.test_painel_dono import BaseNuvem, TestClient, nuvem

SENHA = "segredo123"


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteVendasTesteNuvem(BaseNuvem):
    def setUp(self):
        super().setUp()
        self.ctl = VendasTesteController(self.banco, self.adm)
        self.ctl.definir_senha(SENHA, SENHA)

    def _venda(self):
        self.venda_fechada((self.skol, 1))
        linha = self.banco.um("SELECT id, uuid FROM vendas ORDER BY id DESC LIMIT 1")
        return linha["id"], linha["uuid"]

    def _na_nuvem(self, uuid):
        from backend import painel
        with nuvem.SessionLocal() as db:
            return db.query(painel.PainelVenda).filter_by(chave_loja="ADEGA-1", uuid=uuid).first() is not None

    def test_apagada_no_caixa_some_da_nuvem_e_nao_volta(self):
        vid, uuid = self._venda()
        lote_antigo = __import__("src.sync.painel_envio", fromlist=["x"]).coletar_vendas(self.banco)
        self.assertEqual([v["uuid"] for v in lote_antigo], [uuid])
        self.subir()
        self.assertTrue(self._na_nuvem(uuid))
        self.ctl.apagar([vid], SENHA)
        self.subir()
        self.assertFalse(self._na_nuvem(uuid))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas_apagadas WHERE enviada_em IS NULL"), 0)
        self.assertIsNone(self.banco.um("SELECT 1 FROM seguranca_dono WHERE enviada_em IS NULL"))
        # um reenvio atrasado da mesma venda é confirmado, mas não volta para o painel
        r = self.http.post("/v1/painel/envio", json={"vendas": lote_antigo},
                           headers={"Authorization": "Bearer token-da-adega-1"})
        self.assertEqual(r.json()["uuids"], [uuid])
        self.assertFalse(self._na_nuvem(uuid))

    def test_painel_pede_caixa_apaga_e_confirma(self):
        vid, uuid = self._venda()
        self.subir()
        sessao = self.entrar()
        lista = self.http.get("/v1/painel/vendas-teste?inicio=2026-10-03&fim=2026-10-03", headers=sessao).json()
        self.assertTrue(lista["senha_configurada"])
        self.assertEqual([v["uuid"] for v in lista["vendas"]], [uuid])
        r = self.http.post("/v1/painel/vendas-teste/apagar", json={"uuids": [uuid], "senha": SENHA}, headers=sessao)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["pedidas"], 1)
        self.subir()                  # caixa recebe a ordem e apaga
        self.assertIsNone(self.banco.um("SELECT 1 FROM vendas WHERE id = ?", (vid,)))
        self.subir()                  # caixa confirma: some da nuvem
        self.assertFalse(self._na_nuvem(uuid))
        hist = self.http.get("/v1/painel/vendas-teste?inicio=2026-10-03&fim=2026-10-03", headers=sessao).json()
        self.assertEqual((hist["historico"][0]["situacao"], hist["historico"][0]["origem"]), ("apagada", "painel"))

    def test_painel_nfce_recusada_pelo_caixa(self):
        vid, uuid = self._venda()
        self.banco.executar("INSERT INTO nfce_notas(venda_id, ref, ambiente, situacao, criada_em) "
                            "VALUES (?, 'r9', 'producao', 'autorizada', '2026-10-03 21:00:00')", (vid,))
        self.subir()
        sessao = self.entrar()
        self.http.post("/v1/painel/vendas-teste/apagar", json={"uuids": [uuid], "senha": SENHA}, headers=sessao)
        self.subir()
        self.subir()
        self.assertIsNotNone(self.banco.um("SELECT 1 FROM vendas WHERE id = ?", (vid,)))
        self.assertTrue(self._na_nuvem(uuid))
        hist = self.http.get("/v1/painel/vendas-teste?inicio=2026-10-03&fim=2026-10-03", headers=sessao).json()
        self.assertEqual(hist["vendas"][0]["pedido"], "recusada")
        self.assertIn("NFC-e", hist["vendas"][0]["motivo"])

    def test_painel_senha_errada_bloqueia(self):
        _, uuid = self._venda()
        self.subir()
        sessao = self.entrar()
        codigos = [self.http.post("/v1/painel/vendas-teste/apagar", json={"uuids": [uuid], "senha": "errada"},
                                  headers=sessao).status_code for _ in range(5)]
        self.assertEqual(codigos, [403, 403, 403, 403, 423])
        r = self.http.post("/v1/painel/vendas-teste/apagar", json={"uuids": [uuid], "senha": SENHA}, headers=sessao)
        self.assertEqual(r.status_code, 423)

    def test_sem_sessao_nao_entra(self):
        r = self.http.post("/v1/painel/vendas-teste/apagar", json={"uuids": ["x"], "senha": SENHA})
        self.assertEqual(r.status_code, 401)
