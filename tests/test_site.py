"""Site de vendas na mesma API: preços num arquivo só, WhatsApp e instaladores no R2."""
from __future__ import annotations

import json
import os
import re
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
        self.assertEqual(site_precos.ADEGA_MENSAL_CENT, 9_000)
        self.assertEqual(site_precos.RESTAURANTE_MENSAL_CENT, 14_999)
        self.assertEqual(site_precos.VARIEDADES_MENSAL_CENT, 15_999)
        self.assertEqual(site_precos.HOTEL_MENSAL_CENT, 19_999)
        self.assertEqual(site_precos.BOATE_MENSAL_CENT, 24_999)
        self.assertEqual(site_precos.anual_cent(site_precos.ADEGA_MENSAL_CENT), 90_000)
        self.assertEqual(site_precos.anual_cent(site_precos.RESTAURANTE_MENSAL_CENT), 149_990)
        self.assertEqual(site_precos.anual_cent(site_precos.VARIEDADES_MENSAL_CENT), 159_990)
        self.assertEqual(site_precos.anual_cent(site_precos.HOTEL_MENSAL_CENT), 199_990)
        self.assertEqual(site_precos.anual_cent(site_precos.BOATE_MENSAL_CENT), 249_990)
        self.assertFalse(hasattr(site_precos, "INSTALACAO_CENT"))
        self.assertEqual(site_precos.WHATSAPP_PADRAO, "5511915168336")
        self.assertEqual(site.telefone_internacional(), "+55 11 91516-8336")

    def test_raiz_e_site_mostram_planos_e_o_whatsapp_padrao(self):
        with _sem_whatsapp_no_ambiente():
            for caminho in ("/", "/site", "/site/"):
                pagina = self.http.get(caminho)
                self.assertEqual(pagina.status_code, 200, caminho)
                texto = pagina.text
                self.assertNotIn("{{", texto)
                self.assertIn("sistema de caixa (PDV) em Osasco e região", texto)
                self.assertIn('property="og:title"', texto)
                self.assertIn('property="og:locale" content="pt_BR"', texto)
                self.assertIn("+55 11 91516-8336", texto)
                for cidade in site_precos.CIDADES:
                    self.assertIn(cidade, texto)
                for centavos in (site_precos.ADEGA_MENSAL_CENT, site_precos.RESTAURANTE_MENSAL_CENT,
                                 site_precos.VARIEDADES_MENSAL_CENT, site_precos.HOTEL_MENSAL_CENT,
                                 site_precos.BOATE_MENSAL_CENT):
                    self.assertIn(fmt_brl(centavos), texto)
                    self.assertIn(fmt_brl(site_precos.anual_cent(centavos)), texto)
                    self.assertIn(site.preco_schema(centavos), texto)
                    self.assertIn(site.preco_schema(site_precos.anual_cent(centavos)), texto)
                self.assertIn("2 meses grátis", texto)
                self.assertIn("Instalação grátis", texto)
                self.assertNotIn("Em breve", texto)
                self.assertNotIn("300,00", texto)
                self.assertNotIn("300.00", texto)
                self.assertNotIn("149,90", texto)
                self.assertNotIn("149.90", texto)
                self.assertIn("7 dias", texto)
                self.assertIn("Não há pedido online", texto)
                self.assertIn("Pedido online pelo cardápio", texto)
                self.assertIn(site.link_whatsapp(site.MENSAGEM_CONTATO), texto)
                self.assertIn("(11) 91516-8336", texto)
                self.assertIn('class="zap fixo"', texto)
                self.assertIn(
                    f"{site_precos.R2_BASE}/willpdv/{VERSAO}/WillPDV-Setup-{VERSAO}.exe", texto)
                self.assertIn(
                    f"{site_precos.R2_BASE}/willadega/{VERSAO}/WillAdega-Setup-{VERSAO}.exe", texto)
                self.assertIn("Assinar", texto)
                self.assertIn("Will Restaurante", texto)
                self.assertIn("Will Variedades", texto)
                self.assertIn("Will Hotel", texto)
                self.assertIn("Feito para hotéis e pousadas", texto)
                self.assertIn("WillRestaurante-Instalador.exe", texto)
                self.assertIn("WillVariedades-Instalador.exe", texto)
                self.assertIn("WillHotel-Instalador.exe", texto)
                self.assertIn('value="willrestaurante"', texto)
                self.assertIn('value="willvariedades"', texto)
                self.assertIn('value="willhotel"', texto)
                self.assertIn('id="form-teste"', texto)
                self.assertIn('id="servicos"', texto)
                self.assertIn('data-periodo="anual"', texto)
                for chave, nome, cent, prefixo, periodo in site_precos.SERVICOS:
                    self.assertIn(nome, texto)
                    self.assertIn(fmt_brl(cent), texto)
                    self.assertIn(site.preco_schema(cent), texto)
                    if prefixo:
                        self.assertIn(prefixo, texto)
                    if periodo:
                        self.assertIn(f"/{periodo}", texto)
                    self.assertIn(site.link_whatsapp(f"{site.MENSAGEM_CONTATO} sobre {nome}."), texto)
                dados = json.loads(re.search(
                    r'<script type="application/ld\+json">(.*?)</script>', texto, re.S).group(1))
                tipos = [item["@type"] for item in dados["@graph"]]
                self.assertIn("LocalBusiness", tipos)
                self.assertIn("SoftwareApplication", tipos)
                self.assertIn("Service", tipos)
                self.assertIn('href="/site/termos"', texto)
                self.assertIn('href="/site/privacidade"', texto)
                self.assertIn("Ao enviar, você concorda com os", texto)
                self.assertIn(">Termos de Uso</a>", texto)
                self.assertIn(">Política de Privacidade</a>", texto)
                self.assertLess(texto.index('id="form-teste"'), texto.index("Ao enviar, você concorda"))
                self.assertLess(texto.index("Ao enviar, você concorda"), texto.index('id="teste-pronto"'))

    def test_termos_e_privacidade(self):
        with _sem_whatsapp_no_ambiente():
            for caminho, titulo in (("/site/termos", "Termos de Uso"), ("/site/termos/", "Termos de Uso"),
                                    ("/site/privacidade", "Política de Privacidade"),
                                    ("/site/privacidade/", "Política de Privacidade")):
                pagina = self.http.get(caminho)
                self.assertEqual(pagina.status_code, 200, caminho)
                self.assertIn("text/html", pagina.headers["content-type"])
                texto = pagina.text
                self.assertNotIn("{{", texto)
                self.assertIn(f"<h1>{titulo}</h1>", texto)
                self.assertIn("Última atualização: 23 de novembro de 2026", texto)
                self.assertIn("WillPDV - Willyan Neres, Osasco-SP", texto)
                self.assertIn('href="/site/estilo.css"', texto)
                self.assertIn('class="topo"', texto)
                self.assertIn('class="rodape-docs"', texto)
                self.assertIn('href="/site/termos"', texto)
                self.assertIn('href="/site/privacidade"', texto)
                self.assertIn("(11) 91516-8336", texto)
                self.assertIn('href="/site/#teste"', texto)
                self.assertEqual(texto.count("[CNPJ]"), 1)
                self.assertIn("<!-- Identificação fiscal, quando houver: [CNPJ].", texto)
                self.assertNotRegex(texto, r"[\w.+-]+@[\w.-]+\.[a-z]{2,}")
            termos = self.http.get("/site/termos").text
            self.assertIn("instalação na loja é grátis", termos.lower())
            self.assertIn("paga 10", termos)
            self.assertIn("12 meses", termos)
            self.assertIn("foro da Comarca de Osasco-SP", termos)
            self.assertIn("Código de Defesa do Consumidor", termos)
            self.assertIn("proporcional", termos)
            self.assertIn("fidelidade", termos)
            for nome in ("Will Adega", "Will Restaurante", "Will Variedades", "Will Hotel", "boate e bar"):
                self.assertIn(nome, termos)
            for centavos in (site_precos.ADEGA_MENSAL_CENT, site_precos.RESTAURANTE_MENSAL_CENT,
                             site_precos.VARIEDADES_MENSAL_CENT, site_precos.HOTEL_MENSAL_CENT,
                             site_precos.BOATE_MENSAL_CENT):
                self.assertIn(fmt_brl(centavos), termos)
            self.assertIn(str(site_precos.DIAS_TESTE), termos)
            privacidade = self.http.get("/site/privacidade").text
            self.assertIn("Lei 13.709/2018", privacidade)
            self.assertIn("controlador", privacidade)
            self.assertIn("operador", privacidade)
            self.assertIn("Render", privacidade)
            self.assertIn("Não vendemos dados pessoais", privacidade)
            self.assertIn("não grava cookie", privacidade)
            self.assertIn("armazenamento local", privacidade)
            self.assertIn("WhatsApp {{telefone}}".replace("{{telefone}}", "(11) 91516-8336"), privacidade)
            self.assertEqual(self.http.get("/v1/saude").json(), {"status": "ok"})

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
