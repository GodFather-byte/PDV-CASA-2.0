"""Site de vendas na mesma API: preços num arquivo só, WhatsApp e instaladores no R2."""
from __future__ import annotations

import json
import os
import re
import unittest
import xml.etree.ElementTree as ET
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

    def test_dominio_publico_nas_metatags_no_sitemap_e_no_robots(self):
        with mock.patch.dict(os.environ, {
                "PUBLIC_BASE_URL": "",
                "RENDER_EXTERNAL_URL": "https://willpdv-nuvem-6sp0.onrender.com"}):
            self.assertEqual(site_precos.URL_PUBLICA, "https://willpdv.com.br")
            self.assertEqual(site.url_publica(), "https://willpdv.com.br")
            pagina = self.http.get("/")
            termos = self.http.get("/site/termos")
            privacidade = self.http.get("/site/privacidade")
            robots = self.http.get("/robots.txt")
            sitemap = self.http.get("/sitemap.xml")
        self.assertEqual(pagina.status_code, 200)
        texto = pagina.text
        self.assertIn('rel="canonical" href="https://willpdv.com.br/"', texto)
        self.assertIn('property="og:url" content="https://willpdv.com.br/"', texto)
        self.assertIn('property="og:image" content="https://willpdv.com.br/site/balcao.webp"', texto)
        self.assertNotIn("onrender.com", texto)
        dados = json.loads(re.search(
            r'<script type="application/ld\+json">(.*?)</script>', texto, re.S).group(1))
        negocio = next(item for item in dados["@graph"] if item["@type"] == "LocalBusiness")
        self.assertEqual(negocio["url"], "https://willpdv.com.br/")
        self.assertEqual(negocio["image"], "https://willpdv.com.br/site/balcao.webp")
        self.assertEqual(negocio["@id"], "https://willpdv.com.br/#negocio")
        self.assertIn('rel="canonical" href="https://willpdv.com.br/site/termos"', termos.text)
        self.assertIn('rel="canonical" href="https://willpdv.com.br/site/privacidade"', privacidade.text)
        self.assertNotIn("onrender.com", termos.text)
        self.assertNotIn("onrender.com", privacidade.text)
        self.assertEqual(robots.status_code, 200)
        self.assertIn("text/plain", robots.headers["content-type"])
        self.assertIn("Sitemap: https://willpdv.com.br/sitemap.xml", robots.text)
        self.assertNotIn("onrender.com", robots.text)
        self.assertEqual(sitemap.status_code, 200)
        self.assertIn("xml", sitemap.headers["content-type"])
        self.assertNotIn("onrender.com", sitemap.text)
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [el.text for el in ET.fromstring(sitemap.text).findall("s:url/s:loc", ns)]
        self.assertEqual(locs, [
            "https://willpdv.com.br/",
            "https://willpdv.com.br/site/termos",
            "https://willpdv.com.br/site/privacidade",
        ])
        with mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://loja.exemplo.com"}):
            self.assertIn('href="https://loja.exemplo.com/"', self.http.get("/").text)
            self.assertIn("Sitemap: https://loja.exemplo.com/sitemap.xml", self.http.get("/robots.txt").text)

    def test_onrender_redireciona_so_a_pagina_publica(self):
        with mock.patch.dict(os.environ, {
                "PUBLIC_BASE_URL": "",
                "RENDER_EXTERNAL_URL": "https://willpdv-nuvem-6sp0.onrender.com"}):
            antigo = TestClient(app, base_url="https://willpdv-nuvem-6sp0.onrender.com")
            oficial = TestClient(app, base_url="https://willpdv.com.br")
            www = TestClient(app, base_url="https://www.willpdv.com.br")
            for caminho in ("/", "/site", "/site/", "/site/termos", "/site/termos/",
                            "/site/privacidade", "/site/privacidade/", "/site/obrigado",
                            "/site/pagamento-pendente", "/site/pagamento-falhou",
                            "/robots.txt", "/sitemap.xml"):
                resposta = antigo.get(caminho, follow_redirects=False)
                self.assertEqual(resposta.status_code, 301, caminho)
                self.assertEqual(resposta.headers["location"], "https://willpdv.com.br" + caminho)
            cabeca = antigo.head("/site/termos", follow_redirects=False)
            self.assertEqual(cabeca.status_code, 301)
            self.assertEqual(cabeca.headers["location"], "https://willpdv.com.br/site/termos")
            volta = antigo.get(
                "/site/obrigado?payment_id=42&collection_id=99&status=approved",
                follow_redirects=False)
            self.assertEqual(volta.status_code, 301)
            self.assertEqual(
                volta.headers["location"],
                "https://willpdv.com.br/site/obrigado?payment_id=42&collection_id=99&status=approved")
            for caminho in ("/site/estilo.css", "/site/balcao.webp", "/site/teste.js", "/site/checkout.js"):
                self.assertEqual(antigo.get(caminho, follow_redirects=False).status_code, 200, caminho)
            for caminho in ("/health", "/v1/saude"):
                self.assertEqual(antigo.get(caminho, follow_redirects=False).json(), {"status": "ok"})
            for caminho in ("/painel/", "/cardapio/", "/porteiro/", "/central/", "/retaguarda/",
                            "/v1/versao", "/v1/sync/pedido"):
                resposta = antigo.get(caminho, follow_redirects=False)
                self.assertNotEqual(resposta.status_code, 301, caminho)
                self.assertNotIn("willpdv.com.br", resposta.headers.get("location", ""))
            cardapio = antigo.get("/cardapio", follow_redirects=False)
            self.assertEqual(cardapio.status_code, 307)
            self.assertNotIn("willpdv.com.br", cardapio.headers.get("location", ""))
            for caminho, metodo in (
                    ("/v1/pagamentos/checkout", "post"),
                    ("/v1/pagamentos/webhook", "post"),
                    ("/v1/webhooks/mercadopago", "post"),
                    ("/v1/sincronizar", "post"),
                    ("/", "post")):
                resposta = getattr(antigo, metodo)(caminho, follow_redirects=False)
                self.assertNotEqual(resposta.status_code, 301, (metodo, caminho))
                self.assertNotIn("willpdv.com.br", resposta.headers.get("location", ""))
            self.assertEqual(oficial.get("/", follow_redirects=False).status_code, 200)
            self.assertIn('href="https://willpdv.com.br/"', oficial.get("/").text)
            self.assertEqual(www.get("/", follow_redirects=False).status_code, 200)
            self.assertEqual(
                antigo.get("/", headers={"x-forwarded-host": "willpdv.com.br"},
                           follow_redirects=False).status_code, 200)
            self.assertEqual(
                antigo.get("/", headers={"x-forwarded-host": "evil.example"},
                           follow_redirects=False).headers["location"],
                "https://willpdv.com.br/")
        with mock.patch.dict(os.environ, {
                "PUBLIC_BASE_URL": "https://willpdv-nuvem-6sp0.onrender.com"}):
            antigo = TestClient(app, base_url="https://willpdv-nuvem-6sp0.onrender.com")
            self.assertEqual(antigo.get("/", follow_redirects=False).status_code, 200)
            self.assertEqual(antigo.get("/v1/saude", follow_redirects=False).json(), {"status": "ok"})
