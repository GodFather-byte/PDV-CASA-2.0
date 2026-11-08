"""Site de vendas na mesma API: preços num arquivo só, WhatsApp e instaladores no R2."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from backend import site, site_precos
from src.core.formatacao import fmt_brl
from src.versao import VERSAO

try:
    from fastapi.testclient import TestClient
    from backend.main import app
except (ImportError, RuntimeError):
    TestClient = app = None


def _sem_whatsapp_no_ambiente():
    return mock.patch.dict(os.environ, {site.VAR_WHATSAPP: ""}, clear=False)


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteSite(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(app)

    def test_precos_do_arquivo_e_o_anual_cobra_dez_meses(self):
        self.assertEqual(site_precos.meses_cobrados(), 10)
        self.assertEqual(site_precos.anual_cent(site_precos.ADEGA_MENSAL_CENT), 149_900)
        self.assertEqual(site_precos.anual_cent(site_precos.BOATE_MENSAL_CENT), 249_990)
        self.assertEqual(site_precos.WHATSAPP_PADRAO, "5511915168336")

    def test_raiz_e_site_mostram_planos_e_o_whatsapp_padrao(self):
        with _sem_whatsapp_no_ambiente():
            for caminho in ("/", "/site", "/site/"):
                pagina = self.http.get(caminho)
                self.assertEqual(pagina.status_code, 200, caminho)
                texto = pagina.text
                self.assertNotIn("{{", texto)
                self.assertIn(fmt_brl(site_precos.ADEGA_MENSAL_CENT), texto)
                self.assertIn(fmt_brl(site_precos.BOATE_MENSAL_CENT), texto)
                self.assertIn(fmt_brl(site_precos.INSTALACAO_CENT), texto)
                self.assertIn(fmt_brl(site_precos.anual_cent(site_precos.ADEGA_MENSAL_CENT)), texto)
                self.assertIn("2 meses", texto)
                self.assertIn("7 dias", texto)
                self.assertIn("Não há pedido online", texto)
                self.assertIn("Pedido online pelo cardápio", texto)
                self.assertIn("https://wa.me/5511915168336?text=", texto)
                self.assertIn("(11) 91516-8336", texto)
                self.assertIn(
                    f"{site_precos.R2_BASE}/willpdv/{VERSAO}/WillPDV-Setup-{VERSAO}.exe", texto)
                self.assertIn(
                    f"{site_precos.R2_BASE}/willadega/{VERSAO}/WillAdega-Setup-{VERSAO}.exe", texto)
                self.assertIn("Assinar", texto)

    def test_variavel_troca_o_numero(self):
        with mock.patch.dict(os.environ, {site.VAR_WHATSAPP: "(11) 98888-7777"}):
            texto = self.http.get("/").text
        self.assertIn("https://wa.me/5511988887777?text=", texto)
        self.assertNotIn("5511915168336", texto)

    def test_numero_invalido_volta_ao_padrao(self):
        with mock.patch.dict(os.environ, {site.VAR_WHATSAPP: "abc"}):
            self.assertEqual(site.numero_whatsapp(), site_precos.WHATSAPP_PADRAO)

    def test_css_e_as_rotas_antigas_continuam(self):
        css = self.http.get("/site/estilo.css")
        self.assertEqual(css.status_code, 200)
        self.assertIn("text/css", css.headers["content-type"])
        self.assertEqual(self.http.get("/health").json(), {"status": "ok"})
        self.assertEqual(self.http.get("/v1/saude").json(), {"status": "ok"})
        versao = self.http.get("/v1/versao")
        self.assertEqual(versao.status_code, 200)
        self.assertEqual(versao.json()["versao"], VERSAO)
        cardapio = self.http.get("/cardapio/")
        self.assertEqual(cardapio.status_code, 200)
        self.assertIn("Cardápio", cardapio.text)
        self.assertNotIn("Will Adega", cardapio.text)
        porteiro = self.http.get("/porteiro/")
        self.assertEqual(porteiro.status_code, 200)
        self.assertNotIn("R$ 149,90", porteiro.text)
        self.assertEqual(self.http.get("/painel/").status_code, 200)
        self.assertEqual(self.http.get("/cardapio", follow_redirects=False).status_code, 307)
