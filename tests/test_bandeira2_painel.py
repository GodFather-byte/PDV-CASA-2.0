"""Bandeira 2 pelo botão do dono no painel: valor em % ou em reais por item, o caixa aplica pela resposta do envio,
o painel mostra se o caixa já aplicou e guarda o histórico."""
from __future__ import annotations

from pathlib import Path

from src.controllers.produto_controller import ProdutoController
from src.sync import bandeira2_nuvem
from tests.base import BaseTeste
from tests.test_painel_dono import BaseNuvem, TestClient, nuvem

import unittest

if TestClient is not None:
    from backend import bandeira2


class TesteBandeiraNoCaixa(BaseTeste):
    def test_reais_por_item_e_preco_proprio(self):
        self.banco.cfg_set("bandeira2_ativa", "S")
        self.banco.cfg_set("bandeira2_modo", "reais")
        self.banco.cfg_set("bandeira2_reais_cent", "200")
        b = ProdutoController(self.banco).bandeira2()
        self.assertEqual(ProdutoController.preco_bandeira2({"preco_cent": 500}, b), 700)
        self.assertEqual(ProdutoController.preco_bandeira2({"preco_cent": 500, "preco_bandeira2_cent": 900}, b), 900)
        self.assertIsNone(ProdutoController.preco_bandeira2({"preco_cent": 500, "bandeira2": 0}, b))
        self.assertEqual(ProdutoController.descrever_bandeira2(b), "+R$ 2,00")
        self.banco.cfg_set("bandeira2_modo", "pct")
        self.banco.cfg_set("bandeira2_pct", "15")
        b = ProdutoController(self.banco).bandeira2()
        self.assertEqual(ProdutoController.preco_bandeira2({"preco_cent": 1000}, b), 1150)
        self.assertEqual(ProdutoController.descrever_bandeira2(b), "+15%")

    def test_resposta_da_nuvem_so_aplica_versao_mais_nova(self):
        r = {"bandeira2": {"versao": 3, "ativa": True, "modo": "pct", "valor": 20}}
        self.assertTrue(bandeira2_nuvem.anotar_resposta(self.banco, r))
        self.assertTrue(self.banco.cfg_bool("bandeira2_ativa"))
        self.assertEqual((self.banco.cfg("bandeira2_pct"), bandeira2_nuvem.versao_aplicada(self.banco)), ("20", 3))
        self.assertFalse(bandeira2_nuvem.anotar_resposta(self.banco, {"bandeira2": {"versao": 2, "ativa": False}}))
        self.assertTrue(self.banco.cfg_bool("bandeira2_ativa"))
        self.assertFalse(bandeira2_nuvem.anotar_resposta(self.banco, {"bandeira2": {"versao": 9, "modo": "pct", "valor": 999}}))
        self.assertTrue(bandeira2_nuvem.anotar_resposta(
            self.banco, {"bandeira2": {"versao": 4, "ativa": False, "modo": "reais", "valor": 150}}))
        self.assertFalse(self.banco.cfg_bool("bandeira2_ativa"))
        self.assertEqual(self.banco.cfg("bandeira2_reais_cent"), "150")


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteBandeiraPeloPainel(BaseNuvem):
    def setUp(self):
        super().setUp()
        with nuvem.SessionLocal() as db:
            db.query(bandeira2.Bandeira2Loja).delete()
            db.query(bandeira2.Bandeira2Historico).delete()
            db.commit()

    def test_dono_liga_e_o_caixa_aplica_no_envio(self):
        sessao = self.entrar()
        self.assertFalse(self.http.get("/v1/painel/bandeira2", headers=sessao).json()["ativa"])
        self.assertEqual(self.http.post("/v1/painel/bandeira2", json={"ativa": True, "modo": "pct", "valor": 0},
                                        headers=sessao).status_code, 422)
        self.assertEqual(self.http.post("/v1/painel/bandeira2", json={"ativa": True, "modo": "pct", "valor": 500},
                                        headers=sessao).status_code, 422)
        r = self.http.post("/v1/painel/bandeira2", json={"ativa": True, "modo": "reais", "valor": 250}, headers=sessao)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["texto"], "+R$ 2,50 por item")
        self.assertFalse(r.json()["aplicada_no_caixa"])
        self.subir()                                          # o caixa envia e recebe a bandeira na resposta
        b = ProdutoController(self.banco).bandeira2()
        self.assertEqual((b["modo"], b["reais_cent"]), ("reais", 250))
        self.subir()                                          # o envio seguinte conta que já aplicou
        r = self.http.get("/v1/painel/bandeira2", headers=sessao).json()
        self.assertTrue(r["aplicada_no_caixa"])
        self.http.post("/v1/painel/bandeira2", json={"ativa": False, "modo": "reais", "valor": 250}, headers=sessao)
        self.subir()
        self.assertIsNone(ProdutoController(self.banco).bandeira2())
        historico = self.http.get("/v1/painel/bandeira2", headers=sessao).json()["historico"]
        self.assertEqual([h["ativa"] for h in historico], [False, True])

    def test_tela_tem_o_cartao(self):
        raiz = Path(__file__).resolve().parents[1] / "backend" / "painel_web"
        html = (raiz / "index.html").read_text(encoding="utf-8")
        for ident in ("bloco-bandeira2", "bandeira2-botao", "bandeira2-modo", "bandeira2-valor"):
            self.assertIn(f'id="{ident}"', html)
        self.assertIn('"/bandeira2"', (raiz / "app.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
