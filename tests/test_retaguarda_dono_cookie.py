"""A retaguarda do dono entra com a sessão do painel guardada no cookie (o painel não deixa mais o token no aparelho).
Antes, sem o token no localStorage, a página mandava o dono entrar de novo e só abria pela central."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from tests.test_painel_dono import BaseNuvem, TestClient, nuvem

if TestClient is not None:
    from backend import painel, retaguarda

RAIZ = Path(__file__).resolve().parents[1]


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteRetaguardaPeloCookie(BaseNuvem):
    def test_dono_le_e_pede_alteracao_so_com_o_cookie(self):
        with nuvem.SessionLocal() as db:
            painel.definir_senha(db, "ADEGA-1", "senha-forte-1")
        navegador = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(navegador.close)
        r = navegador.post("/v1/painel/login", json={"loja": "ADEGA-1", "senha": "senha-forte-1"},
                           headers={"X-PDV-Painel": "1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("token", r.json())                     # o painel só tem o cookie
        cabecalho = {"X-PDV-Painel": "1"}
        with mock.patch.object(retaguarda, "secao", return_value=({"entidades": []}, "2026-11-27 10:00:00")):
            r = navegador.get("/v1/painel/retaguarda", headers=cabecalho)
            self.assertNotEqual(r.status_code, 401, r.text)
            pedido = {"tipo": "produto.preco", "dados": {"id": 1, "preco_cent": 500}, "resumo": "teste"}
            self.assertEqual(navegador.post("/v1/painel/retaguarda/comandos", json=pedido).status_code, 403)  # sem o cabeçalho
            r = navegador.post("/v1/painel/retaguarda/comandos", json=pedido, headers=cabecalho)
            self.assertNotIn(r.status_code, (401, 403), r.text)
        anonimo = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(anonimo.close)
        self.assertEqual(anonimo.get("/v1/painel/retaguarda", headers=cabecalho).status_code, 401)

    def test_pagina_usa_o_cookie_e_nao_exige_token(self):
        js = (RAIZ / "backend" / "retaguarda_web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('"X-PDV-Painel": "1"', js)
        self.assertIn('credentials: "same-origin"', js)
        self.assertNotIn("if (!estado.token) return mostrarEntrada();", js)


if __name__ == "__main__":
    unittest.main()
