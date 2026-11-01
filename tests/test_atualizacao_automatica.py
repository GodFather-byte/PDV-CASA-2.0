"""Atualização assinada: manifesto, download, caixa ocupado e a nuvem."""
from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path

from src.atualizacao import cliente
from src.atualizacao.manifesto import assinar, conferir
from src.core import ed25519
from src.versao import VERSAO
from tests.test_caixa import BaseCaixa
from tests.test_nuvem import ADMIN, TestClient, nuvem

SEMENTE = bytes.fromhex("11" * 32)
PUBLICA = ed25519.chave_publica(SEMENTE).hex()


def pacote(**extras):
    base = {
        "edicao": "willpdv", "canal": "estavel", "versao": "9.9.9", "sha256": "ab" * 32, "tamanho": 4,
        "url": "https://arquivos.exemplo/willpdv.exe", "notas": "Correção.", "obrigatoria": 0, "minima": "",
    }
    base.update(extras)
    base["assinatura"] = assinar(SEMENTE, base)
    return base


class TesteManifesto(unittest.TestCase):
    def test_assinatura_recusa_troca_de_hash(self):
        bom = pacote()
        self.assertTrue(conferir(bom, PUBLICA))
        ruim = dict(bom)
        ruim["sha256"] = "cd" * 32
        self.assertFalse(conferir(ruim, PUBLICA))

    def test_script_instala_em_silencio_e_sobe_o_sync(self):
        texto = cliente.script_aplicar(Path("C:/tmp/setup.exe"), Path("C:/Program Files/WillPDV"),
                                       Path("C:/tmp/anterior"), "WillPDV.exe")
        self.assertIn("/VERYSILENT", texto)
        self.assertIn("--confirmar-atualizacao", texto)
        self.assertIn("--sync", texto)
        self.assertIn("xcopy", texto)


class TesteCaixa(BaseCaixa):
    def test_nao_instala_com_venda_aberta_e_a_obrigatoria_ignora_o_adiamento(self):
        self.vender((self.skol, 1))
        self.assertIn("aberta", cliente.caixa_ocupado(self.banco))
        self._fechar()
        self.assertIsNone(cliente.caixa_ocupado(self.banco))
        cliente.adiar(self.banco, "9.9.9")
        self.assertTrue(cliente.adiada(self.banco, "9.9.9"))
        self.assertTrue(cliente.abaixo_da_minima("1.0.0", "1.2.0"))
        self.assertFalse(cliente.abaixo_da_minima(VERSAO, ""))

    def _fechar(self):
        from src.controllers.caixa_controller import CaixaController
        venda = self.banco.um("SELECT id FROM vendas WHERE status = 'aberta'")
        total = CaixaController(self.banco, self.adm).obter(venda["id"])["total_cent"]
        self.pagar(venda["id"], "Dinheiro", total)
        return self.caixa.fechar(venda["id"])

    def test_download_recusa_arquivo_trocado(self):
        class Http:
            def get(self, url, timeout=None):
                return type("R", (), {"status_code": 200, "content": b"bom!"})()
        destino = Path(self.banco.caminho).parent / "pacote.exe" if False else Path(os.environ.get("TEMP", "/tmp")) / "pacote-teste.exe"
        sha = hashlib.sha256(b"bom!").hexdigest()
        cliente.baixar("https://arquivos.exemplo/a.exe", destino, sha, 4, Http())
        self.assertEqual(destino.read_bytes(), b"bom!")
        with self.assertRaises(RuntimeError):
            cliente.baixar("https://arquivos.exemplo/a.exe", destino, "00" * 32, 4, Http())
        destino.unlink(missing_ok=True)


@unittest.skipIf(TestClient is None or nuvem is None, "fastapi/httpx não instalados")
class TesteNuvem(unittest.TestCase):
    def setUp(self):
        from tests.test_nuvem import preparar_lojas
        preparar_lojas()
        self.http = TestClient(nuvem.app)
        self._env = os.environ.get("PDV_ATUALIZACAO_PUBLICA")
        os.environ["PDV_ATUALIZACAO_PUBLICA"] = PUBLICA

    def tearDown(self):
        if self._env is None:
            os.environ.pop("PDV_ATUALIZACAO_PUBLICA", None)
        else:
            os.environ["PDV_ATUALIZACAO_PUBLICA"] = self._env

    def test_publica_a_ultima_da_edicao_e_recusa_assinatura_falsa(self):
        from backend.atualizacao_remota import publicar
        falso = pacote()
        falso["assinatura"] = "ab" * 64
        self.assertEqual(self.http.post("/v1/admin/atualizacao", json=falso, headers=ADMIN).status_code, 422)
        self.assertEqual(self.http.post("/v1/admin/atualizacao", json=pacote(), headers={"Authorization": "Bearer token-da-loja"}).status_code, 401)
        db = nuvem.SessionLocal()
        try:
            publicar(db, pacote(versao="9.1.0", notas="antiga"))
            publicar(db, pacote())
            publicar(db, pacote(edicao="ea_superacoes", versao="9.9.9", url="https://arquivos.exemplo/adega.exe"))
        finally:
            db.close()
        r = self.http.get("/v1/atualizacao/ultima", params={"edicao": "willpdv", "canal": "estavel", "versao": "1.0.0"})
        self.assertEqual(r.status_code, 200, r.text)
        corpo = r.json()
        self.assertTrue(corpo["disponivel"])
        self.assertEqual(corpo["pacote"]["versao"], "9.9.9")
        self.assertTrue(conferir(corpo["pacote"], PUBLICA))
        adega = self.http.get("/v1/atualizacao/ultima", params={"edicao": "ea_superacoes"}).json()
        self.assertEqual(adega["pacote"]["url"], "https://arquivos.exemplo/adega.exe")
        self.assertEqual(self.http.get("/v1/atualizacao/ultima", params={"edicao": "bar"}).json()["disponivel"], False)

    def test_arquivo_local_so_sai_se_o_hash_conferir(self):
        import tempfile
        from backend.atualizacao_remota import publicar
        dados = b"instalador"
        sha = hashlib.sha256(dados).hexdigest()
        with tempfile.TemporaryDirectory() as pasta:
            os.environ["PDV_ATUALIZACAO_DIR"] = pasta
            destino = Path(pasta) / "willpdv" / "estavel"
            destino.mkdir(parents=True)
            (destino / "9.9.9.exe").write_bytes(dados)
            db = nuvem.SessionLocal()
            try:
                publicar(db, pacote(sha256=sha, tamanho=len(dados), url="/v1/atualizacao/arquivo?edicao=willpdv&canal=estavel&versao=9.9.9"))
            finally:
                db.close()
            ok = self.http.get("/v1/atualizacao/arquivo", params={"edicao": "willpdv", "canal": "estavel", "versao": "9.9.9"})
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.content, dados)
            (destino / "9.9.9.exe").write_bytes(b"trocado!!")
            self.assertEqual(self.http.get("/v1/atualizacao/arquivo", params={"edicao": "willpdv", "canal": "estavel", "versao": "9.9.9"}).status_code, 409)
            os.environ.pop("PDV_ATUALIZACAO_DIR", None)


if __name__ == "__main__":
    unittest.main()
