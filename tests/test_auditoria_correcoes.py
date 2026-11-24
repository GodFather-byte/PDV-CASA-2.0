"""Correções da auditoria de novembro de 2026: planilha, hash e cabeçalhos HTTP.

Não chama a produção. O caixa 1.14.21 continua mandando o mesmo JSON; estes casos
cobrem o que a nuvem passa a recusar e o que o Excel deixa de executar.
"""
from __future__ import annotations

import io
import unittest
import zipfile

from src.core import seguranca
from src.core.erros import ErroNegocio
from src.core.formatacao import texto_planilha
from src.controllers.importacao_produtos import LIMITE_XLSX_ENTRADAS, escrever_xlsx, ler_tabela_dados

try:
    from tests.test_nuvem import TestClient, nuvem
except (ImportError, RuntimeError):
    TestClient = nuvem = None


class TesteTextoPlanilha(unittest.TestCase):
    def test_numero_brasileiro_continua_numero(self):
        self.assertEqual(texto_planilha("-1.234,56"), "-1.234,56")
        self.assertEqual(texto_planilha("0,50"), "0,50")
        self.assertEqual(texto_planilha(None), "")

    def test_formula_vira_texto(self):
        self.assertEqual(texto_planilha("=CMD|'/c calc'!A1"), "'=CMD|'/c calc'!A1")
        self.assertEqual(texto_planilha("+55 11 99999-0000"), "'+55 11 99999-0000")
        self.assertEqual(texto_planilha("-2+3"), "'-2+3")
        self.assertEqual(texto_planilha("@soma"), "'@soma")
        self.assertEqual(texto_planilha("Cerveja"), "Cerveja")


class TesteIteracoesDoHash(unittest.TestCase):
    def test_hash_com_iteracoes_enormes_nao_roda(self):
        self.assertFalse(seguranca.conferir("abc", "pbkdf2$999999999$" + "ab" * 16 + "$" + "cd" * 32))
        self.assertTrue(seguranca.conferir("abc", seguranca.gerar_hash("abc")))

    def test_senha_do_painel_tambem_tem_teto(self):
        from backend.painel import conferir_senha, gerar_hash_senha
        bomba = "pbkdf2_sha256$9000000$" + "ab" * 16 + "$" + "cd" * 32
        self.assertFalse(conferir_senha("segredo-longo", bomba))
        guardado = gerar_hash_senha("segredo-longo")
        self.assertTrue(conferir_senha("segredo-longo", guardado))


class TestePlanilhaExcel(unittest.TestCase):
    def test_planilha_normal_continua_legivel(self):
        dados = escrever_xlsx([["Produto", "Preço"], ["Cerveja", "3,50"]])
        linhas = ler_tabela_dados(dados, "produtos.xlsx")
        self.assertEqual(linhas[0]["nome"], "Cerveja")

    def test_muitos_arquivos_dentro_do_zip_sao_recusados(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as arquivo:
            for i in range(LIMITE_XLSX_ENTRADAS + 1):
                arquivo.writestr(f"xl/extra{i}.xml", b"<a/>")
        with self.assertRaises(ErroNegocio) as ctx:
            ler_tabela_dados(buf.getvalue(), "bomba.xlsx")
        self.assertIn("grande demais", str(ctx.exception))

    def test_dtd_no_xml_e_recusado(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as arquivo:
            arquivo.writestr("xl/worksheets/sheet1.xml", b"<!DOCTYPE foo [<!ENTITY a 'b'>]><x>&a;</x>")
        with self.assertRaises(ErroNegocio) as ctx:
            ler_tabela_dados(buf.getvalue(), "dtd.xlsx")
        self.assertIn("não aceita", str(ctx.exception))


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteCabecalhosHttp(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(nuvem.app)

    def test_documentacao_da_api_nao_fica_publica(self):
        for caminho in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(self.http.get(caminho).status_code, 404, caminho)

    def test_painel_nao_pode_ser_enquadrado_e_o_https_ganha_hsts(self):
        pagina = self.http.get("/painel/", headers={"x-forwarded-proto": "https"})
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual(pagina.headers["x-frame-options"], "DENY")
        self.assertEqual(pagina.headers["x-content-type-options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", pagina.headers["content-security-policy"])
        self.assertIn("script-src 'self'", pagina.headers["content-security-policy"])
        self.assertIn("max-age=15552000", pagina.headers["strict-transport-security"])
        saude = self.http.get("/health")
        self.assertNotIn("strict-transport-security", saude.headers)
        self.assertEqual(saude.headers["x-frame-options"], "DENY")
        self.assertNotIn("script-src", saude.headers["content-security-policy"])
