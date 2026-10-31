"""Porteiro na nuvem: retrato por loja, PIN, consulta só de leitura e a página em /porteiro/."""
from __future__ import annotations

import unittest

from src.core import seguranca

try:
    from backend.porteiro import PorteiroRetrato, sessoes
    from tests.test_nuvem import ADMIN, TestClient, cabecalho, nuvem, preparar_lojas
except (ImportError, RuntimeError):
    TestClient = nuvem = preparar_lojas = sessoes = PorteiroRetrato = None

PIN = "2468"


def _posicao(numero=7, devido=880):
    return {
        "situacao": "devendo", "titulo": "DEVENDO", "motivo": "aberta",
        "detalhe": "Ainda falta R$ 8,80.", "cabecalho": f"Comanda {numero}",
        "nome": f"Comanda {numero}", "apelido": "", "comanda": True, "numero": numero,
        "rotulo": str(numero), "devido_cent": devido, "total_cent": devido, "pago_cent": 0,
        "valor_txt": "R$ 8,80",
        "itens": [{"nome": "SKOL", "quantidade": 1, "quantidade_txt": "1", "total_cent": 800, "total_txt": "R$ 8,00"}],
        "cupom": None,
    }


def _corpo(posicoes, terminal="caixa1", momento="2026-10-31 22:00:00"):
    return {
        "momento": momento, "pin_hash": seguranca.gerar_hash(PIN), "terminal_id": terminal,
        "url_lan": "http://10.0.0.8:8765/porteiro", "posicao_padrao": "comanda", "posicoes": posicoes,
    }


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TestePorteiroNuvem(unittest.TestCase):
    def setUp(self):
        sessoes.zerar()
        preparar_lojas()
        db = nuvem.SessionLocal()
        try:
            db.query(PorteiroRetrato).delete()
            db.commit()
        finally:
            db.close()
        self.http = TestClient(nuvem.app)

    def test_consulta_e_da_loja_certa_e_so_leitura(self):
        self.assertEqual(self.http.post("/v1/porteiro/retrato", json=_corpo([_posicao()]),
                                        headers=cabecalho()).status_code, 200)
        self.assertEqual(self.http.post("/v1/porteiro/retrato", json=_corpo([], terminal="caixa2"),
                                        headers=cabecalho("LOJA-2")).status_code, 200)
        self.assertEqual(self.http.post("/v1/porteiro/retrato", json=_corpo([_posicao()]),
                                        headers=ADMIN).status_code, 403)
        ruim = self.http.post("/v1/porteiro/entrar", json={"chave": "LOJA-1", "pin": "0000"})
        self.assertEqual(ruim.status_code, 401)
        self.assertNotIn("0000", ruim.text)
        for _ in range(3):
            self.assertEqual(self.http.post("/v1/porteiro/entrar",
                                            json={"chave": "LOJA-1", "pin": "1111"}).status_code, 401)
        self.assertEqual(self.http.post("/v1/porteiro/entrar",
                                        json={"chave": "LOJA-1", "pin": "2222"}).status_code, 429)
        self.assertEqual(self.http.post("/v1/porteiro/entrar",
                                        json={"chave": "LOJA-1", "pin": PIN}).status_code, 429)
        sessoes.zerar()
        ok = self.http.post("/v1/porteiro/entrar", json={"chave": "LOJA-1", "pin": PIN})
        self.assertEqual(ok.status_code, 200)
        token = ok.json()["token"]
        self.assertNotIn(PIN, token)
        self.assertEqual(ok.json()["caixa_url"], "http://10.0.0.8:8765/porteiro")
        dono = {"Authorization": f"Bearer {token}"}
        consulta = self.http.get("/v1/porteiro/consulta", params={"q": "7"}, headers=dono)
        self.assertEqual(consulta.status_code, 200)
        corpo = consulta.json()
        self.assertEqual((corpo["situacao"], corpo["devido_cent"], corpo["fonte"]), ("devendo", 880, "nuvem"))
        self.assertTrue(corpo["origem_txt"].startswith("Na nuvem"))
        self.assertEqual(corpo["itens"][0]["nome"], "SKOL")
        self.assertNotIn("pin_hash", corpo)
        livre = self.http.get("/v1/porteiro/consulta", params={"q": "8"}, headers=dono)
        self.assertEqual(livre.json()["situacao"], "liberada")
        outra = self.http.post("/v1/porteiro/entrar", json={"chave": "LOJA-2", "pin": PIN})
        self.assertEqual(outra.status_code, 200)
        alheia = self.http.get("/v1/porteiro/consulta", params={"q": "7"},
                               headers={"Authorization": "Bearer " + outra.json()["token"]})
        self.assertEqual(alheia.json()["situacao"], "liberada")
        self.assertEqual(self.http.post("/v1/porteiro/retrato", json=_corpo([_posicao()]), headers=dono).status_code, 401)
        self.assertIn(self.http.delete("/v1/porteiro/consulta").status_code, (404, 405))

    def test_caixa_velho_nao_segura_comanda_que_o_novo_ja_nao_mostra(self):
        self.http.post("/v1/porteiro/retrato", json=_corpo([_posicao(9)], terminal="velho",
                                                           momento="2026-10-31 21:00:00"), headers=cabecalho())
        self.http.post("/v1/porteiro/retrato", json=_corpo([], terminal="novo", momento="2026-10-31 22:00:00"),
                       headers=cabecalho())
        ok = self.http.post("/v1/porteiro/entrar", json={"chave": "LOJA-1", "pin": PIN})
        consulta = self.http.get("/v1/porteiro/consulta", params={"q": "9"},
                                 headers={"Authorization": "Bearer " + ok.json()["token"]})
        self.assertEqual(consulta.json()["situacao"], "liberada")

    def test_a_pagina_sobe_na_nuvem(self):
        pagina = self.http.get("/porteiro/")
        self.assertEqual(pagina.status_code, 200)
        self.assertIn("pt-BR", pagina.text)
        self.assertEqual(self.http.get("/porteiro/api/saude").json()["modo"], "nuvem")
        self.assertEqual(self.http.get("/porteiro").status_code, 200)
