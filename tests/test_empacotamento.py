"""Dados do executável (PyInstaller) e arquivos que nunca podem ir para o repositório."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.database import conexao
from src.database.conexao import BancoDados


class TesteDadosDoExecutavel(unittest.TestCase):
    def test_codigo_fonte_usa_a_raiz_do_projeto(self):
        self.assertTrue((conexao._raiz_dados() / "src" / "database" / "conexao.py").exists())

    def test_executavel_grava_em_localappdata_e_nao_dentro_do_pacote(self):
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": pasta}):
            self.assertEqual(conexao._raiz_dados(), Path(pasta) / "WILL-PDV")

    def test_banco_cria_a_pasta_que_ainda_nao_existe(self):
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / "novo" / "dados" / "loja.db"
            BancoDados(str(destino)).fechar()
            self.assertTrue(destino.exists())

    def test_gitignore_cobre_banco_wal_build_e_chaves(self):
        linhas = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8").splitlines()
        for padrao in ("*.db", "*.db-wal", "*.db-shm", "*.db-journal", "build/", "dist/", "*.key"):
            self.assertIn(padrao, linhas)


class TesteWorkflowDeBuild(unittest.TestCase):
    """O GitHub Actions que gera o instalador para baixar: não dá para rodá-lo aqui, então ao menos garante o que ele promete."""
    texto = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")

    def test_gera_programa_e_instalador_e_guarda_para_baixar(self):
        for trecho in ("windows-latest", "python build_pdv.py", "upload-artifact", "WillPDV-Setup-*.exe", "choco install innosetup"):
            self.assertIn(trecho, self.texto)

    def test_confere_o_programa_empacotado_e_o_instalado_antes_de_entregar(self):
        self.assertGreaterEqual(self.texto.count("--autoteste"), 2)           # no .exe e no instalado
        self.assertIn("/VERYSILENT", self.texto)                              # instala de verdade
        self.assertLess(self.texto.index("--autoteste"), self.texto.index("actions/upload-artifact"))

    def test_so_a_publicacao_na_release_escreve_no_repositorio(self):
        self.assertIn("permissions:\n  contents: read", self.texto)
        self.assertEqual(self.texto.count("contents: write"), 3)             # publicação: tag v*, "última versão" e a da adega
        antes_da_publicacao = self.texto[:self.texto.index("  publicar:")]      # build e licenciador só leem o repositório
        self.assertNotIn("contents: write", antes_da_publicacao)

    def test_ultima_versao_vai_para_a_aba_releases_so_a_partir_da_main(self):
        trecho = self.texto[self.texto.index("  ultima_versao:"):]
        self.assertIn("if: github.ref == 'refs/heads/main'", trecho)
        for esperado in ("ultima-versao", "WillPDV-Instalador.exe", "WillPDV-Portatil.zip", "--prerelease", "--cleanup-tag"):
            self.assertIn(esperado, trecho)
        self.assertNotIn("WillLicencas", trecho)                     # a Release é pública: o programa do fornecedor fica de fora
        self.assertIn("needs: build", trecho)                        # só publica o que passou nos autotestes


    def test_programa_de_licencas_tem_job_proprio_e_nao_vai_para_a_aba_releases(self):
        for trecho in ("python build_licenciador.py", "WillLicencas-Instalador-", "WillLicencas-Setup-*.exe", "docs/LICENCIADOR.md"):
            self.assertIn(trecho, self.texto)
        release = self.texto[self.texto.index("  publicar:"):]
        self.assertNotIn("WillLicencas", release)                    # é ferramenta do fornecedor: nada de link público no Releases
        self.assertGreaterEqual(self.texto.count("--autoteste"), 4)   # PDV: no .exe e no instalado; licenças: no .exe e no instalado


    def test_adega_tem_job_proprio_com_os_mesmos_autotestes_e_release_propria(self):
        job = self.texto[self.texto.index("  adega:"):self.texto.index("  publicar:")]
        for trecho in ("python build_pdv.py --edicao ea_superacoes", "EASuperacoes-Setup-*.exe", "edicao.txt", "--autoteste",
                       "--autoteste-qt", "/VERYSILENT", "--sync", "EASuperacoes-Instalador-", "EASuperacoes-Portatil-"):
            self.assertIn(trecho, job)
        self.assertNotIn("contents: write", job)
        release = self.texto[self.texto.index("  ultima_versao_adega:"):]
        for trecho in ("needs: adega", "if: github.ref == 'refs/heads/main'", "ultima-versao-adega", "EASuperacoes-Instalador.exe"):
            self.assertIn(trecho, release)


class TesteInstaladores(unittest.TestCase):
    pasta = Path(__file__).resolve().parents[1] / "instalador"

    def test_scripts_do_inno_em_utf8_com_bom_e_appids_diferentes(self):
        ids = []
        for nome in ("WillPDV.iss", "WillLicencas.iss", "EASuperacoes.iss"):
            bruto = (self.pasta / nome).read_bytes()
            self.assertTrue(bruto.startswith(b"\xef\xbb\xbf"), f"{nome} precisa de BOM: sem ele o Inno lê os acentos como ANSI")
            ids.append([l for l in bruto.decode("utf-8-sig").splitlines() if l.startswith("AppId=")][0])
        self.assertEqual(len(set(ids)), 3)                            # os três instalam lado a lado

    def test_logotipos_existem_e_os_scripts_apontam_para_eles(self):
        import re
        for nome, prefixo in (("WillPDV.iss", "willpdv"), ("WillLicencas.iss", "willlicencas"),
                              ("EASuperacoes.iss", "ea-superacoes")):
            texto = (self.pasta / nome).read_text(encoding="utf-8-sig")
            for arquivo in (f"{prefixo}-assistente.bmp", f"{prefixo}-assistente-pequena.bmp"):
                self.assertIn(arquivo, texto)
                self.assertTrue((self.pasta / arquivo).is_file(), arquivo)
            self.assertTrue((self.pasta / f"{prefixo}.ico").is_file())
            self.assertTrue(re.search(r"^\[Code\]", texto, re.M))      # o instalador encerra o programa que ficou aberto
            self.assertIn("PrepareToInstall", texto)

    def test_imagens_do_assistente_tem_o_tamanho_do_inno(self):
        import struct
        for prefixo in ("willpdv", "willlicencas", "ea-superacoes"):
            for nome, esperado in ((f"{prefixo}-assistente.bmp", (164, 314)), (f"{prefixo}-assistente-pequena.bmp", (55, 55))):
                cab = (self.pasta / nome).read_bytes()[:30]
                self.assertEqual(cab[:2], b"BM")
                self.assertEqual(struct.unpack("<ii", cab[18:26]), esperado, nome)

    def test_icone_da_janela_so_no_windows_e_nunca_derruba(self):
        from unittest import mock
        from licenciador import icone
        self.assertTrue(icone.caminho("willpdv.ico").is_file())
        self.assertIsNone(icone.caminho("nao_existe.ico"))
        with mock.patch.object(sys, "platform", "linux"):
            self.assertFalse(icone.aplicar(object()))                 # Linux/Mac não leem .ico
        with mock.patch.object(sys, "platform", "win32"):
            self.assertFalse(icone.aplicar(object()))                 # janela sem iconbitmap: ignora o erro em vez de levantar


class TesteLicencaDoRepositorio(unittest.TestCase):
    raiz = Path(__file__).resolve().parents[1]

    def test_licenca_proprietaria_existe_e_o_readme_aponta_para_ela(self):
        texto = (self.raiz / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Todos os direitos reservados", texto)
        self.assertIn("ENGLISH SUMMARY", texto)
        self.assertNotIn("MIT License", texto)               # produto vendido por licença: não é código aberto
        self.assertIn("(LICENSE)", (self.raiz / "README.md").read_text(encoding="utf-8"))


class TesteChavesForaDoRepositorio(unittest.TestCase):
    raiz = Path(__file__).resolve().parents[1]

    def test_nenhuma_chave_privada_nem_licenca_no_repositorio(self):
        for caminho in self.raiz.rglob("*.py"):
            if "tests" in caminho.parts or ".venv" in caminho.parts:
                continue
            self.assertNotIn("PRIVATE KEY", caminho.read_text(encoding="utf-8", errors="ignore"), caminho)


if __name__ == "__main__":
    unittest.main()

    def test_instalador_da_adega_usa_o_executavel_e_a_pasta_da_edicao(self):
        from src.core import edicao
        ed = edicao.EDICOES["ea_superacoes"]
        texto = (self.pasta / ed.script_instalador).read_text(encoding="utf-8-sig")
        self.assertIn(f'#define Exe "{ed.executavel}.exe"', texto)
        self.assertIn(f'#define Pasta "{ed.executavel}"', texto)
        self.assertIn('#define Nome "E&A Superações"', texto)
        self.assertIn("OutputBaseFilename=EASuperacoes-Setup-", texto)
        self.assertTrue(ed.executavel.isascii() and ed.executavel.isalnum())    # vai no cmd do [Code]: sem & nem acento


class TesteBuildPorEdicao(unittest.TestCase):
    def test_build_escolhe_a_edicao_pela_linha_de_comando(self):
        import build_pdv
        self.assertEqual(build_pdv.edicao_escolhida([]).chave, "willpdv")
        self.assertEqual(build_pdv.edicao_escolhida(["--edicao", "ea_superacoes"]).executavel, "EASuperacoes")
        self.assertEqual(build_pdv.edicao_escolhida(["--sem-instalador", "--edicao=ea_superacoes"]).chave, "ea_superacoes")
        with self.assertRaises(SystemExit):
            build_pdv.edicao_escolhida(["--edicao", "adega"])
