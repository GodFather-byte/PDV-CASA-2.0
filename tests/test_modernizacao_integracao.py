"""Contratos de distribuição, comandos e relatórios da migração gradual."""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from importlib.metadata import distribution
from pathlib import Path
from unittest import mock

import build_pdv
from src import autoteste_qt

RAIZ = Path(__file__).resolve().parents[1]


class TesteDistribuicaoModerna(unittest.TestCase):
    def test_build_inclui_avisos_licencas_e_versoes_reais(self):
        with tempfile.TemporaryDirectory() as pasta:
            build_pdv.copiar_licencas(Path(pasta))
            licencas = Path(pasta) / "licencas"
            self.assertIn("GNU LESSER", (licencas / "LGPL-3.0-only.txt").read_text(encoding="utf-8"))
            self.assertIn("GNU GENERAL", (licencas / "GPL-3.0-only.txt").read_text(encoding="utf-8"))
            manifesto = (licencas / "DEPENDENCIAS.txt").read_text(encoding="utf-8")
            for nome in ("PySide6-Essentials", "shiboken6", "cryptography", "cffi"):
                self.assertIn(nome, manifesto)
                arquivos_licenca = {
                    Path(arquivo).name
                    for arquivo in distribution(nome).files or ()
                    if ".dist-info" in str(arquivo)
                    and ("license" in str(arquivo).lower() or "copying" in str(arquivo).lower())
                }
                pasta_pacote = licencas / "pacotes" / nome
                copiados = {arquivo.name for arquivo in pasta_pacote.iterdir()} if pasta_pacote.exists() else set()
                self.assertEqual(copiados, arquivos_licenca, nome)

    def test_instalador_tem_previa_sem_trocar_atalho_padrao(self):
        texto = (RAIZ / "instalador" / "WillPDV.iss").read_text(encoding="utf-8-sig")
        self.assertIn('Parameters: "--qt"', texto)
        self.assertIn('Name: "{autoprograms}\\{#Nome}"; Filename: "{app}\\{#Exe}"', texto)

    def test_interfaces_mutuamente_exclusivas(self):
        resultado = subprocess.run([sys.executable, "-m", "src.app", "--qt", "--tk"],
                                   capture_output=True, timeout=30, cwd=RAIZ)
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn(b"--qt ou --tk", resultado.stderr)

    def test_workflow_valida_qt_empacotado_e_instalado(self):
        texto = (RAIZ / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")
        self.assertGreaterEqual(texto.count("--autoteste-qt"), 2)


class TesteRelatorioQt(unittest.TestCase):
    def test_falha_explicita_e_relatorio_persistente(self):
        with tempfile.TemporaryDirectory() as pasta:
            saida = Path(pasta) / "resultado.txt"
            with mock.patch("src.ui_qt.app.autoteste", side_effect=RuntimeError("falha de teste")), \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as console:
                self.assertEqual(autoteste_qt.executar(str(saida)), 1)
            texto = saida.read_text(encoding="utf-8")
            self.assertIn("RESULTADO: COM FALHAS", texto)
            self.assertEqual(console.getvalue(), texto)
