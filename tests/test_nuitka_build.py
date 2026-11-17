"""Proteção do código no executável: os pacotes de `src` vão compilados pelo Nuitka, nunca como `.py` (docs/PROTEGER_CODIGO.md)."""
import os
import unittest
from pathlib import Path
from unittest import mock

import build_pdv
from tools import compilar_nuitka

RAIZ = Path(__file__).resolve().parent.parent


class TestNuitkaBuild(unittest.TestCase):

    def test_compilacao_guardada_so_vale_com_a_mesma_chave_e_todos_os_pacotes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            saida = Path(tmp)
            (saida / "src").mkdir()
            for nome in compilar_nuitka.pacotes():
                (saida / "src" / f"{nome}.pyd").write_bytes(b"x")
            self.assertIsNone(compilar_nuitka.prontas(saida))                       # sem chave gravada
            (saida / "chave.txt").write_text(compilar_nuitka.chave() + "\n", encoding="utf-8")
            self.assertEqual(len(compilar_nuitka.prontas(saida)), len(compilar_nuitka.pacotes()))
            with mock.patch.object(compilar_nuitka.subprocess, "run") as nuitka:
                self.assertEqual(len(compilar_nuitka.compilar(saida)), len(compilar_nuitka.pacotes()))
                nuitka.assert_not_called()                                         # reaproveitou, não compilou
            (saida / "chave.txt").write_text("outra\n", encoding="utf-8")
            self.assertIsNone(compilar_nuitka.prontas(saida))                       # código mudou
            (saida / "chave.txt").write_text(compilar_nuitka.chave() + "\n", encoding="utf-8")
            next((saida / "src").iterdir()).unlink()
            self.assertIsNone(compilar_nuitka.prontas(saida))                       # faltou um pacote

    def test_toda_pasta_de_codigo_vira_pacote_compilado(self):
        pastas = {p.name for p in (RAIZ / "src").iterdir() if p.is_dir() and any(p.glob("*.py"))}
        self.assertEqual(set(compilar_nuitka.pacotes()), pastas)      # pasta nova sem __init__.py iria como .py
        for nome in ("core", "controllers", "ui_qt", "fiscal", "atualizacao"):
            self.assertIn(nome, compilar_nuitka.pacotes())

    def test_imports_de_fora_viram_hidden_import_sem_nomes_de_classe(self):
        externos = compilar_nuitka.imports_externos()
        self.assertIn("PySide6.QtWidgets", externos)
        self.assertIn("sqlite3", externos)
        self.assertNotIn("PySide6.QtCore.QObject", externos)          # classe, não módulo
        self.assertFalse([m for m in externos if m == "src" or m.startswith("src.")])

    def test_compilado_troca_os_py_pelas_extensoes(self):
        extensoes = [Path("build/nuitka/src") / f"{nome}.pyd" for nome in compilar_nuitka.pacotes()]
        with mock.patch.object(compilar_nuitka, "compilar", return_value=extensoes):
            argumentos = build_pdv.argumentos_codigo(["src.core.licenca", "src.ui_qt.caixa", "src.versao"], compilar=True)
        pares = list(zip(argumentos[::2], argumentos[1::2]))
        ocultos = [valor for opcao, valor in pares if opcao == "--hidden-import"]
        self.assertIn(("--exclude-module", "src.core"), pares)
        self.assertIn(("--exclude-module", "src.ui_qt"), pares)
        self.assertIn(("--add-binary", f"{extensoes[0]}{os.pathsep}src"), pares)
        self.assertIn("src.versao", ocultos)                           # arquivo solto continua Python
        self.assertNotIn("src.core.licenca", ocultos)
        self.assertNotIn("src.ui_qt.caixa", ocultos)

    def test_sem_nuitka_e_so_emergencia(self):
        argumentos = build_pdv.argumentos_codigo(["src.core.licenca"], compilar=False)
        self.assertEqual(argumentos, ["--hidden-import", "src.core.licenca"])
        for arquivo in ("build-windows.yml", "will-restaurante.yml"):
            texto = (RAIZ / ".github" / "workflows" / arquivo).read_text(encoding="utf-8")
            self.assertIn("python build_pdv.py", texto)
            self.assertNotIn("--sem-nuitka", texto, arquivo)
        self.assertIn("nuitka", (RAIZ / "requirements-build.in").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
