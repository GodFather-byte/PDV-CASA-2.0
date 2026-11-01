"""Cardápio digital: o que o caixa publica e o que o celular lê (só consulta)."""
from __future__ import annotations

import json
import unittest
from datetime import datetime
from unittest import mock

from src.cardapio.folha import cartoes, folha_html, intervalo_mesas, url_cardapio
from src.cardapio.preco import preco_para_cardapio
from src.controllers.produto_controller import ProdutoController
from src.core.erros import ErroNegocio
from src.database.esquema import VERSAO_ESQUEMA
from src.sync import cardapio_envio
from tests.test_caixa import BaseCaixa
from tests.test_painel_dono import ADMIN, TOKENS, TestClient, cabecalho, nuvem, preparar_lojas


class RespostaFalsa:
    def __init__(self, status=200, corpo=None):
        self.status_code = status
        self._corpo = corpo if corpo is not None else {"produtos": 0}

    def json(self):
        return self._corpo


class HttpFalso:
    def __init__(self, status=200):
        self.status, self.chamadas = status, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.chamadas.append({"url": url, "corpo": json, "headers": headers})
        return RespostaFalsa(self.status, {"produtos": len((json or {}).get("produtos") or [])})


class TestePrecoEFolha(BaseCaixa):
    def test_coluna_nasce_ligada(self):
        self.assertGreaterEqual(VERSAO_ESQUEMA, 32)
        self.assertEqual(self.banco.valor("SELECT mostrar_no_cardapio FROM produtos WHERE id = ?", (self.skol,)), 1)

    def test_happy_hour_e_promocao_usam_o_preco_do_caixa(self):
        self.banco.executar(
            "UPDATE produtos SET hora_ini = '20:00', hora_fim = '23:00', hora_preco_cent = 500, "
            "promo_de = '2026-10-01', promo_ate = '2026-10-03', promo_preco_cent = 700 WHERE id = ?", (self.skol,))
        produto = self.prod.por_id(self.skol)
        noite = datetime(2026, 10, 3, 21, 0)
        tarde = datetime(2026, 10, 3, 15, 0)
        self.assertEqual(preco_para_cardapio(produto, noite)["preco_cent"],
                         ProdutoController.regra_preco_vigente(produto, noite)["preco_cent"])
        self.assertEqual(preco_para_cardapio(produto, noite),
                         {"preco_cent": 500, "preco_de_cent": 800, "promocao": "horário"})
        self.assertEqual(preco_para_cardapio(produto, tarde),
                         {"preco_cent": 700, "preco_de_cent": 800, "promocao": "período"})

    def test_coleta_esconde_inativo_fora_de_venda_e_nao_manda_custo_nem_estoque(self):
        self.banco.executar("UPDATE produtos SET texto_sugestao = '  bem gelada  ', ult_preco_cent = 400, "
                            "qt_atual = 3 WHERE id = ?", (self.agua,))
        self.banco.executar("UPDATE produtos SET mostrar_no_cardapio = 0 WHERE id = ?", (self.skol,))
        oculto = self.novo_produto("ESCONDIDO", 900)
        self.banco.executar("UPDATE produtos SET ativo = 0 WHERE id = ?", (oculto,))
        interno = self.novo_produto("INSUMO", 100)
        self.banco.executar("UPDATE produtos SET venda = 0 WHERE id = ?", (interno,))
        self.banco.executar("UPDATE subgrupos SET figura = 'C:\\\\fotos\\\\agua.png' WHERE id = "
                            "(SELECT subgrupo_id FROM produtos WHERE id = ?)", (self.agua,))
        catalogo = cardapio_envio.coletar(self.banco)
        nomes = [p["nome"] for p in catalogo["produtos"]]
        self.assertEqual(nomes, ["AGUA"])
        self.assertEqual(catalogo["produtos"][0]["descricao"], "bem gelada")
        self.assertNotIn("foto", catalogo["produtos"][0])
        texto = json.dumps(catalogo)
        self.assertNotIn("ult_preco", texto)
        self.assertNotIn("qt_atual", texto)
        self.assertNotIn("400", texto)

    def test_foto_so_se_for_endereco_web(self):
        self.banco.executar("UPDATE subgrupos SET figura = 'https://exemplo.com/agua.jpg' WHERE id = "
                            "(SELECT subgrupo_id FROM produtos WHERE id = ?)", (self.agua,))
        self.banco.executar("UPDATE produtos SET mostrar_no_cardapio = 0 WHERE id = ?", (self.skol,))
        item = cardapio_envio.coletar(self.banco)["produtos"][0]
        self.assertEqual(item["foto"], "https://exemplo.com/agua.jpg")

    def test_desligado_nao_chama_a_nuvem_e_ligado_nao_repete_o_mesmo_catalogo(self):
        self.banco.cfg_set("api_url", "https://nuvem.exemplo/v1/sincronizar")
        self.banco.cfg_set("api_token", TOKENS["ADEGA-1"])
        http = HttpFalso()
        self.assertIsNone(cardapio_envio.enviar(self.banco, http))
        self.assertEqual(http.chamadas, [])
        self.banco.cfg_set("cardapio_digital", "S")
        self.assertEqual(cardapio_envio.enviar(self.banco, http)["enviado"], True)
        self.assertEqual(http.chamadas[0]["url"], "https://nuvem.exemplo/v1/cardapio/envio")
        self.assertEqual(http.chamadas[0]["headers"]["Authorization"], f"Bearer {TOKENS['ADEGA-1']}")
        self.assertEqual(cardapio_envio.enviar(self.banco, http), {"produtos": 2, "enviado": False})
        self.assertEqual(len(http.chamadas), 1)
        self.banco.cfg_set("cardapio_digital", "N")
        self.assertTrue(cardapio_envio.enviar(self.banco, http)["retirado"])
        self.assertEqual(http.chamadas[-1]["corpo"]["produtos"], [])
        self.assertIsNone(cardapio_envio.enviar(self.banco, http))

    def test_erro_da_nuvem_nao_marca_como_publicado(self):
        self.banco.cfg_set("api_url", "https://nuvem.exemplo/v1/sincronizar")
        self.banco.cfg_set("api_token", TOKENS["ADEGA-1"])
        self.banco.cfg_set("cardapio_digital", "S")
        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            cardapio_envio.enviar(self.banco, HttpFalso(status=503))
        self.assertEqual(self.banco.cfg(cardapio_envio.CHAVE_PUBLICADO), "")

    def test_url_e_folha_trazem_a_mesa_e_a_loja(self):
        self.assertEqual(url_cardapio("https://nuvem.exemplo/v1/sincronizar", "ADEGA-1", 3),
                         "https://nuvem.exemplo/cardapio/?loja=ADEGA-1&mesa=3")
        with self.assertRaises(ErroNegocio):
            intervalo_mesas(0, 2)
        with self.assertRaises(ErroNegocio):
            intervalo_mesas(1, 250)
        itens = cartoes("https://nuvem.exemplo/", "ADEGA-1", 2, 3)
        html = folha_html("Adega Centro", itens)
        self.assertIn("Mesa 2", html)
        self.assertIn("Mesa 3", html)
        self.assertIn("Adega Centro", html)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("loja=ADEGA-1", html)
        self.assertIn("mesa=3", html)
        self.assertEqual(len(cartoes("https://nuvem.exemplo/", "ADEGA-1")), 1)


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteNuvemCardapio(BaseCaixa):
    def setUp(self):
        super().setUp()
        preparar_lojas()
        self.http = TestClient(nuvem.app)
        self.banco.cfg_set("api_url", "http://testserver/v1/sincronizar")
        self.banco.cfg_set("api_token", TOKENS["ADEGA-1"])
        self.banco.cfg_set("chave_loja", "ADEGA-1")
        self.banco.cfg_set("cardapio_digital", "S")

    def test_publica_idempotente_calcula_o_preco_e_nao_vaza_custo(self):
        self.banco.executar(
            "UPDATE produtos SET hora_ini = '20:00', hora_fim = '23:00', hora_preco_cent = 500, "
            "mostrar_no_cardapio = 0 WHERE id = ?", (self.skol,))
        self.banco.executar("UPDATE produtos SET texto_sugestao = 'sem gás', ult_preco_cent = 90 WHERE id = ?", (self.agua,))
        from src.sync.cardapio_envio import coletar
        corpo = coletar(self.banco)
        corpo["produtos"][0]["ult_preco_cent"] = 90
        corpo["produtos"][0]["qt_atual"] = 40
        r = self.http.post("/v1/cardapio/envio", json=corpo, headers=cabecalho())
        self.assertEqual(r.status_code, 200, r.text)
        de_novo = self.http.post("/v1/cardapio/envio", json=corpo, headers=cabecalho())
        self.assertEqual(de_novo.json()["produtos"], 1)
        from backend.cardapio import CardapioLoja
        db = nuvem.SessionLocal()
        try:
            self.assertEqual(db.query(CardapioLoja).count(), 1)
        finally:
            db.close()
        with mock.patch("backend.cardapio.agora_local", return_value=datetime(2026, 10, 3, 21, 0)):
            noite = self.http.get("/v1/cardapio", params={"loja": "ADEGA-1", "mesa": "4"})
        self.assertEqual(noite.status_code, 200, noite.text)
        produto = noite.json()["grupos"][0]["subgrupos"][0]["produtos"][0]
        self.assertEqual(produto["nome"], "AGUA")
        self.assertEqual(produto["preco_cent"], 350)
        self.assertEqual(produto["descricao"], "sem gás")
        self.assertNotIn("ult_preco_cent", produto)
        self.assertNotIn("qt_atual", produto)
        self.assertEqual(noite.json()["mesa"], 4)
        texto = noite.text
        self.assertNotIn("ult_preco", texto)
        self.assertNotIn("qt_atual", texto)
        skol = coletar(self.banco)
        self.banco.executar("UPDATE produtos SET mostrar_no_cardapio = 1 WHERE id = ?", (self.skol,))
        from src.sync import cardapio_envio
        cardapio_envio.enviar(self.banco, _Cliente(self.http))
        with mock.patch("backend.cardapio.agora_local", return_value=datetime(2026, 10, 3, 21, 0)):
            com_hora = self.http.get("/v1/cardapio", params={"loja": "ADEGA-1"}).json()
        skol_pub = next(p for g in com_hora["grupos"] for s in g["subgrupos"] for p in s["produtos"] if p["nome"] == "SKOL")
        self.assertEqual((skol_pub["preco_cent"], skol_pub["preco_de_cent"], skol_pub["promocao"]), (500, 800, "horário"))
        with mock.patch("backend.cardapio.agora_local", return_value=datetime(2026, 10, 3, 15, 0)):
            tarde = self.http.get("/v1/cardapio", params={"loja": "ADEGA-1"}).json()
        skol_tarde = next(p for g in tarde["grupos"] for s in g["subgrupos"] for p in s["produtos"] if p["nome"] == "SKOL")
        self.assertEqual(skol_tarde["preco_cent"], 800)
        self.assertIsNone(skol_tarde["preco_de_cent"])
        self.assertIsNotNone(skol)

    def test_outra_loja_admin_e_mesa_invalida(self):
        from src.sync import cardapio_envio
        cardapio_envio.enviar(self.banco, _Cliente(self.http))
        self.assertEqual(self.http.get("/v1/cardapio", params={"loja": "ADEGA-2"}).status_code, 404)
        self.assertEqual(self.http.post("/v1/cardapio/envio", json={"produtos": []}, headers=ADMIN).status_code, 403)
        self.assertEqual(self.http.post("/v1/cardapio/envio", json={"produtos": []}).status_code, 401)
        self.assertEqual(self.http.get("/v1/cardapio", params={"loja": "ADEGA-1", "mesa": "0"}).status_code, 422)
        lojas = nuvem.SessionLocal()
        try:
            from backend import lojas as lojas_mod
            lojas_mod.definir_ativa(lojas, "ADEGA-1", False)
        finally:
            lojas.close()
        self.assertEqual(self.http.get("/v1/cardapio", params={"loja": "ADEGA-1"}).status_code, 404)

    def test_pagina_e_o_link_do_painel(self):
        pagina = self.http.get("/cardapio/")
        self.assertEqual(pagina.status_code, 200)
        self.assertIn("Buscar no cardápio", pagina.text)
        self.assertIn("Só consulta", pagina.text)
        self.assertEqual(self.http.get("/cardapio", follow_redirects=False).status_code, 307)
        manifesto = self.http.get("/cardapio/manifest.webmanifest")
        self.assertEqual(manifesto.status_code, 200)
        self.assertEqual(manifesto.json()["start_url"], "/cardapio/")
        painel = self.http.get("/painel/").text
        self.assertIn('id="link-cardapio"', painel)


class _Cliente:
    def __init__(self, http):
        self._http = http

    def post(self, url, json=None, headers=None, timeout=None):
        return self._http.post(url, json=json, headers=headers)
