"""Erros do caixa: sem segredo na fila, sobem no lote e a nuvem soma os iguais."""
from __future__ import annotations

from src.core import erros_caixa
from src.core.erros_caixa import assinatura, limpar_texto, registrar
from tests.base import BaseTeste

try:
    from fastapi.testclient import TestClient
    from tests.test_nuvem import ADMIN, nuvem, preparar_lojas
except (ImportError, RuntimeError):
    TestClient = nuvem = preparar_lojas = ADMIN = None


class TesteFilaLocal(BaseTeste):
    def test_tira_segredo_e_soma_o_mesmo_erro(self):
        texto = limpar_texto("falhou Bearer abcdefgh token=segredo-longo ana@loja.com 123.456.789-00 (11) 98888-7777")
        self.assertNotIn("abcdefgh", texto)
        self.assertNotIn("segredo-longo", texto)
        self.assertNotIn("ana@loja.com", texto)
        self.assertNotIn("123.456.789-00", texto)
        self.assertNotIn("98888-7777", texto)
        registrar("error", "caixa", "quebrou token=segredo", "linha\nlinha", banco=self.banco)
        registrar("error", "caixa", "quebrou token=segredo", "linha\nlinha", banco=self.banco)
        fila = erros_caixa.pendentes(self.banco)
        self.assertEqual(len(fila), 1)
        self.assertEqual(fila[0]["vezes"], 2)
        self.assertNotIn("segredo", fila[0]["mensagem"])
        self.assertEqual(len(fila[0]["assinatura"]), 64)
        self.assertEqual(assinatura("error", "caixa", "a", "b"), assinatura("error", "caixa", "a", "b"))


if TestClient is not None:
    class TesteNuvem(BaseTeste):
        def setUp(self):
            super().setUp()
            preparar_lojas()
            self.http = TestClient(nuvem.app)

        def test_admin_lista_e_a_loja_nao_ve_e_o_repetido_soma(self):
            from backend.erros_caixa import ErroCaixa
            cab = {"Authorization": "Bearer token-da-loja-1"}
            corpo = {"erros": [{
                "assinatura": "a" * 64, "nivel": "error", "modulo": "caixa",
                "mensagem": "quebrou", "traceback": "tb", "contexto": "versao=1.10.0",
                "vezes": 2, "criado_em": "2026-11-01 22:00:00"}]}
            r = self.http.post("/v1/painel/envio", json=corpo, headers=cab)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["erros"], ["a" * 64])
            self.http.post("/v1/painel/envio", json=corpo, headers=cab)
            with nuvem.SessionLocal() as db:
                linha = db.query(ErroCaixa).filter_by(assinatura="a" * 64).one()
                self.assertEqual(linha.vezes, 4)
            negado = self.http.get("/v1/admin/erros-caixa", headers=cab)
            self.assertEqual(negado.status_code, 403)
            lista = self.http.get("/v1/admin/erros-caixa", params={"loja": "LOJA-1", "limit": 10}, headers=ADMIN)
            self.assertEqual(lista.status_code, 200, lista.text)
            self.assertEqual(lista.json()["erros"][0]["vezes"], 4)
            self.assertNotIn("token", lista.text)
