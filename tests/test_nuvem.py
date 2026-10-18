"""Nuvem (FastAPI): lojas, tokens, lista do administrador e o laço de licença e atualizações do PDV."""
from __future__ import annotations

import atexit
import io
import logging
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock

from src.sync.sincronizador import Sincronizador, proxima_espera
from tests.base import BaseTeste

# O backend lê o banco e o token do ambiente quando é importado: aponta para uma pasta temporária.
_PASTA = tempfile.mkdtemp(prefix="pdv_nuvem_")
# PDV_TESTE_NUVEM_DB_URL roda os mesmos testes contra outro banco (ex.: um PostgreSQL de teste, como o Neon/Render).
os.environ["PDV_NUVEM_DB_URL"] = (os.environ.get("PDV_TESTE_NUVEM_DB_URL")
                                  or "sqlite:///" + (Path(_PASTA) / "nuvem.db").as_posix())
os.environ["PDV_API_TOKEN"] = "token-de-teste"
try:
    from fastapi.testclient import TestClient
    from backend import lojas
    from backend import main as nuvem
except (ImportError, RuntimeError):      # o backend é opcional: sem fastapi/httpx só roda o cliente
    TestClient = nuvem = lojas = None

ADMIN = {"Authorization": "Bearer token-de-teste"}                  # PDV_API_TOKEN: só o painel de todas as lojas
TOKENS = {"LOJA-1": "token-da-loja-1", "LOJA-2": "token-da-loja-2"}


def cabecalho(loja="LOJA-1"):
    return {"Authorization": f"Bearer {TOKENS[loja]}"}


def preparar_lojas():
    """A nuvem de teste é compartilhada: garante as duas lojas, ativas e com os tokens conhecidos."""
    db = nuvem.SessionLocal()
    try:
        db.query(nuvem.Loja).delete()
        for chave, token in TOKENS.items():
            db.add(nuvem.Loja(chave_loja=chave, nome=chave, token_hash=nuvem.hash_token(token), ativa=True))
        db.commit()
    finally:
        db.close()


def _limpar():
    if nuvem is not None:
        nuvem.engine.dispose()
    shutil.rmtree(_PASTA, ignore_errors=True)


atexit.register(_limpar)


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteApi(BaseTeste):
    def setUp(self):
        super().setUp()
        preparar_lojas()
        self.http = TestClient(nuvem.app)

    def test_saude_nao_exige_token(self):
        self.assertEqual(self.http.get("/v1/saude").status_code, 200)

    def test_token_obrigatorio_e_invalido_e_recusado(self):
        self.assertEqual(self.http.get("/v1/licenca").status_code, 401)
        self.assertEqual(self.http.get("/v1/licenca", headers={"Authorization": "Bearer errado"}).status_code, 401)

    def test_loja_desativada_e_recusada(self):
        db = nuvem.SessionLocal()
        db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").update({"ativa": False})
        db.commit()
        db.close()
        r = self.http.get("/v1/licenca", headers=cabecalho())
        self.assertEqual(r.status_code, 403)
        self.assertIn("desativada", r.json()["detail"])

    def test_nuvem_nao_recebe_vendas_nem_tem_painel(self):
        self.assertEqual(self.http.post("/v1/sincronizar", json={}, headers=cabecalho()).status_code, 404)
        self.assertEqual(self.http.get("/v1/dashboard/resumo", headers=ADMIN).status_code, 404)

    def test_admin_ve_as_lojas_e_loja_nao_ve(self):
        r = self.http.get("/v1/admin/lojas", headers=ADMIN)
        self.assertEqual(sorted(l["chave_loja"] for l in r.json()["lojas"]), ["LOJA-1", "LOJA-2"])
        self.assertEqual(self.http.get("/v1/admin/lojas", headers=cabecalho()).status_code, 403)


class TesteSincronizador(BaseTeste):
    """O laço do PDV: só licença e versão nova (a nuvem não recebe vendas)."""

    def setUp(self):
        super().setUp()
        self.banco.cfg_set("api_url", "http://nuvem.local/v1/sincronizar")
        self.banco.cfg_set("api_token", "segredo")

    def test_nuvem_desligada_nao_faz_nada(self):
        self.banco.cfg_set("api_url", "")
        with mock.patch("src.sync.atualizacoes.verificar") as ver:
            self.assertTrue(Sincronizador(self.banco, http=object()).rodada())
        ver.assert_not_called()

    def test_rodada_verifica_versao_e_renova_licenca(self):
        with mock.patch("src.sync.atualizacoes.verificar", return_value=None) as ver, \
                mock.patch("src.sync.licenca_nuvem.renovar") as ren:
            self.assertTrue(Sincronizador(self.banco, http=object()).rodada())
        ver.assert_called_once()
        ren.assert_called_once()

    def test_falha_na_rodada_nao_derruba_o_laco_e_aumenta_a_espera(self):
        esperas = []
        with mock.patch("src.sync.atualizacoes.verificar", side_effect=RuntimeError("boom")), \
                mock.patch.object(logging.getLogger("pdv.sync"), "exception"):
            Sincronizador(self.banco, http=object()).iniciar_loop(rodadas=3, dormir=esperas.append)
        self.assertEqual(esperas, [proxima_espera(60, n) for n in (1, 2, 3)])
        self.assertLess(esperas[0], esperas[2])

    def test_espera_dobra_a_cada_falha_ate_o_limite(self):
        self.assertEqual([proxima_espera(60, n) for n in range(4)], [60, 120, 240, 480])
        self.assertEqual(proxima_espera(60, 10), 600)
        self.assertEqual(proxima_espera(1, 0), 5)


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteCadastroDeLojas(unittest.TestCase):
    def setUp(self):
        self.db = nuvem.SessionLocal()
        self.addCleanup(self.db.close)
        self.db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja.like("CAD-%")).delete(synchronize_session=False)
        self.db.commit()
        self.http = TestClient(nuvem.app)

    def test_criar_mostra_o_token_uma_vez_e_guarda_so_o_hash(self):
        token = lojas.criar(self.db, "CAD-1", "Boate Teste")
        self.assertGreaterEqual(len(token), 40)
        loja = self.db.query(nuvem.Loja).filter_by(chave_loja="CAD-1").one()
        self.assertNotEqual(loja.token_hash, token)
        self.assertEqual(loja.token_hash, nuvem.hash_token(token))
        r = self.http.get("/v1/licenca", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 404)           # autenticou; só falta registrar a assinatura

    def test_novo_token_invalida_o_antigo(self):
        antigo = lojas.criar(self.db, "CAD-2", "Boate Teste")
        novo = lojas.novo_token(self.db, "CAD-2")
        self.assertNotEqual(antigo, novo)
        self.assertEqual(self.http.get("/v1/licenca", headers={"Authorization": f"Bearer {antigo}"}).status_code, 401)
        self.assertEqual(self.http.get("/v1/licenca", headers={"Authorization": f"Bearer {novo}"}).status_code, 404)

    def test_validacoes(self):
        lojas.criar(self.db, "CAD-3", "Boate Teste")
        for chave, nome in (("CAD-3", "Repetida"), ("", "Sem chave"), ("CAD 4", "Com espaço"), ("CAD-5", "")):
            with self.subTest(chave=chave), self.assertRaises(lojas.ErroLoja):
                lojas.criar(self.db, chave, nome)
        with self.assertRaises(lojas.ErroLoja):
            lojas.novo_token(self.db, "CAD-NAO-EXISTE")

    def test_linha_de_comando(self):
        saida = io.StringIO()
        with mock.patch.object(lojas, "SessionLocal", return_value=self.db), mock.patch.object(self.db, "close"), \
                redirect_stdout(saida):
            self.assertEqual(lojas.main(["criar", "CAD-6", "Boate Linha"]), 0)
            self.assertEqual(lojas.main(["desativar", "CAD-6"]), 0)
            self.assertEqual(lojas.main(["listar"]), 0)
            self.assertEqual(lojas.main(["comando-errado"]), 2)
        self.assertIn("Token (guarde agora", saida.getvalue())
        self.assertRegex(saida.getvalue(), r"CAD-6\s+INATIVA\s+sem assinatura\s+Boate Linha")

