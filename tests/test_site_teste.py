"""Teste grátis pelo site: cria a loja com licença de teste, código de instalação e senha do painel; barra abuso."""
from __future__ import annotations

import os
import unittest
from datetime import date, timedelta
from unittest import mock

from tests.test_nuvem import TestClient, nuvem, preparar_lojas

try:
    from backend import site_teste, site_precos
except (ImportError, RuntimeError):
    site_teste = None


def pedido(**extra):
    base = {"edicao": "willadega", "nome_loja": "Adega do Zé", "responsavel": "José da Silva",
            "whatsapp": "(11) 91234-5678", "cidade": "Osasco", "aceite": True, "site": ""}
    base.update(extra)
    return base


@unittest.skipIf(TestClient is None or site_teste is None, "fastapi/httpx não instalados")
class TesteGratisPeloSite(unittest.TestCase):
    def setUp(self):
        preparar_lojas()
        with nuvem.SessionLocal() as db:
            db.query(site_teste.SiteTeste).delete()
            db.commit()
        self.http = TestClient(nuvem.app, base_url="https://testserver")
        ambiente = mock.patch.dict(os.environ, {"PDV_SITE_TESTE": "1", "PDV_SITE_TESTES_DIA": "30"})
        ambiente.start()
        self.addCleanup(ambiente.stop)
        self.addCleanup(preparar_lojas)

    def criar(self, **extra):
        return self.http.post("/v1/site/teste", json=pedido(**extra))

    def test_cria_loja_em_teste_com_codigo_e_senha_que_funcionam(self):
        r = self.criar()
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertRegex(d["loja"], r"^ADEGA-DO-ZE-[0-9A-F]{4}$")
        self.assertEqual(d["programa"], "Will Adega")
        self.assertEqual(d["validade"], (date.today() + timedelta(days=site_precos.DIAS_TESTE)).isoformat())
        from src.core import codigo_instalacao
        dados = codigo_instalacao.ler(d["codigo_instalacao"])
        self.assertEqual((dados["chave"], dados["url"]), (d["loja"], "https://testserver"))
        with nuvem.SessionLocal() as db:
            loja = db.query(nuvem.Loja).filter_by(chave_loja=d["loja"]).one()
            self.assertEqual((loja.edicao, loja.licenca_ate, loja.ativa), ("willadega", d["validade"], True))
            registro = db.query(site_teste.SiteTeste).one()
            self.assertEqual((registro.whatsapp, registro.responsavel), ("5511912345678", "José da Silva"))
            self.assertNotIn("testclient", registro.ip_hash)                    # IP só como hash
        login = self.http.post("/v1/painel/login", json={"loja": d["loja"], "senha": d["senha_painel"]})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertIn("wa.me/", d["zap_ajuda"])

    def test_restaurante_tambem_pelo_site(self):
        r = self.criar(edicao="willrestaurante", nome_loja="Cantina da Nona")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["programa"], "Will Restaurante")
        self.assertIn("WillRestaurante", r.json()["instalador"])
        with nuvem.SessionLocal() as db:
            self.assertEqual(db.query(nuvem.Loja).filter_by(chave_loja=r.json()["loja"]).one().edicao, "willrestaurante")

    def test_variedades_e_hotel_pelo_site(self):
        variedades = self.criar(edicao="willvariedades", nome_loja="Casa do Fone", whatsapp="11 91111-0001")
        self.assertEqual(variedades.status_code, 200, variedades.text)
        self.assertEqual(variedades.json()["programa"], "Will Variedades")
        self.assertIn("WillVariedades", variedades.json()["instalador"])
        hotel = self.criar(edicao="willhotel", nome_loja="Pousada do Lago", whatsapp="11 91111-0002")
        self.assertEqual(hotel.status_code, 200, hotel.text)
        self.assertEqual(hotel.json()["programa"], "Will Hotel")
        self.assertIn("WillHotel", hotel.json()["instalador"])
        with nuvem.SessionLocal() as db:
            self.assertEqual(db.query(nuvem.Loja).filter_by(chave_loja=variedades.json()["loja"]).one().edicao,
                             "willvariedades")
            self.assertEqual(db.query(nuvem.Loja).filter_by(chave_loja=hotel.json()["loja"]).one().edicao, "willhotel")

    def test_abuso_e_dados_ruins_sao_barrados(self):
        self.assertEqual(self.criar(site="http://spam").status_code, 422)          # robô preencheu a isca
        self.assertEqual(self.criar(aceite=False).status_code, 422)
        self.assertEqual(self.criar(whatsapp="123").status_code, 422)
        self.assertEqual(self.criar(edicao="willnaoexiste").status_code, 422)
        self.assertEqual(self.criar(nome_loja="x").status_code, 422)
        self.assertEqual(self.criar().status_code, 200)
        self.assertEqual(self.criar(nome_loja="Outra Adega").status_code, 409)     # mesmo WhatsApp
        self.assertEqual(self.criar(whatsapp="11 90000-0001").status_code, 200)
        self.assertEqual(self.criar(whatsapp="11 90000-0002").status_code, 200)
        self.assertEqual(self.criar(whatsapp="11 90000-0003").status_code, 429)    # 3 por IP por dia
        with mock.patch.dict(os.environ, {"PDV_SITE_TESTE": "0"}):
            self.assertEqual(self.criar(whatsapp="11 90000-0004").status_code, 403)

    def test_teto_diario(self):
        with mock.patch.dict(os.environ, {"PDV_SITE_TESTES_DIA": "1"}):
            self.assertEqual(self.criar().status_code, 200)
            self.assertEqual(self.criar(whatsapp="11 90000-0009").status_code, 429)

    def test_central_mostra_o_contato_e_a_loja_em_teste(self):
        from backend import central_fornecedor as central
        d = self.criar().json()
        r = self.http.post("/v1/fornecedor/login", json={"credencial": "token-de-teste"},
                           headers={"X-Central-Login": "1"})
        self.assertEqual(r.status_code, 200, r.text)
        lojas = {l["chave"]: l for l in self.http.get("/v1/fornecedor/lojas").json()["lojas"]}
        loja = lojas[d["loja"]]
        self.assertTrue(loja["em_teste"])
        self.assertTrue(loja["teste_parado"])
        self.assertEqual(loja["contato"]["whatsapp"], "5511912345678")
        with nuvem.SessionLocal() as db:
            db.query(central.SessaoFornecedor).delete()
            db.commit()

    def test_pagina_tem_o_formulario(self):
        html = self.http.get("/site/").text
        self.assertIn('id="form-teste"', html)
        self.assertIn('/site/teste.js', html)
        self.assertEqual(self.http.get("/site/teste.js").status_code, 200)
