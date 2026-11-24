"""Cabeçalhos, documentação fechada e endereço da nuvem que pode receber o token."""
from __future__ import annotations

import unittest

from src.core.endereco_nuvem import aceita_credencial, autorizar

try:
    from fastapi.testclient import TestClient
    from backend.main import app
except (ImportError, RuntimeError):
    TestClient = app = None


class TesteEndereco(unittest.TestCase):
    def test_http_publico_nao_leva_token(self):
        self.assertIsNone(autorizar("http://nuvem.exemplo", "token-da-loja-1"))
        self.assertFalse(aceita_credencial("http://8.8.8.8"))
        for url in ("https://willpdv.com.br", "http://127.0.0.1:8000", "http://10.1.2.3:8000",
                    "http://192.168.0.8", "http://nuvem.local/v1", "http://testserver/v1/sincronizar"):
            self.assertTrue(aceita_credencial(url), url)
            self.assertEqual(autorizar(url, "token-da-loja-1")["Authorization"], "Bearer token-da-loja-1")


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteCabecalhos(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(app)

    def test_docs_fechados_e_cabecalhos_no_site_e_no_painel(self):
        self.assertIsNone(app.docs_url)
        self.assertIsNone(app.redoc_url)
        self.assertIsNone(app.openapi_url)
        for caminho in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(self.http.get(caminho).status_code, 404, caminho)
        for caminho in ("/", "/painel/"):
            r = self.http.get(caminho)
            self.assertEqual(r.status_code, 200, caminho)
            self.assertEqual(r.headers["x-content-type-options"], "nosniff")
            self.assertEqual(r.headers["x-frame-options"], "DENY")
            self.assertEqual(r.headers["referrer-policy"], "no-referrer")
            self.assertIn("camera=()", r.headers["permissions-policy"])
            self.assertIn("frame-ancestors 'none'", r.headers["content-security-policy"])
            self.assertIn("script-src 'self'", r.headers["content-security-policy"])
            self.assertNotIn("strict-transport-security", r.headers)

    def test_https_de_verdade_manda_hsts_e_http_publico_redireciona(self):
        seguro = TestClient(app, base_url="https://willpdv.com.br")
        self.addCleanup(seguro.close)
        pagina = seguro.get("/")
        self.assertEqual(pagina.status_code, 200)
        self.assertIn("max-age=31536000", pagina.headers["strict-transport-security"])
        r = self.http.get("/", headers={"X-Forwarded-Proto": "http", "Host": "willpdv.com.br"},
                          follow_redirects=False)
        self.assertEqual(r.status_code, 308)
        self.assertEqual(r.headers["location"], "https://willpdv.com.br/")
        aviso = self.http.post("/v1/pagamentos/webhook", headers={"X-Forwarded-Proto": "http", "Host": "willpdv.com.br"})
        self.assertEqual(aviso.status_code, 400)
