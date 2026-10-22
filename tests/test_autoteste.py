"""Autoteste do programa instalado (WillPDV.exe --autoteste): a lista de módulos, o relatório e a linha de comando."""
from __future__ import annotations

import importlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import autoteste

RAIZ = Path(__file__).resolve().parents[1]


class TesteListaDeModulos(unittest.TestCase):
    def test_lista_acompanha_os_arquivos_de_src(self):
        """Módulo novo precisa entrar em MODULOS, senão o autoteste do executável não o confere."""
        reais = {".".join(p.relative_to(RAIZ).with_suffix("").parts) for p in (RAIZ / "src").rglob("*.py")
                 if p.name != "__init__.py"} - {"src.app"}
        self.assertEqual(sorted(reais - set(autoteste.MODULOS)), [], "módulos que faltam em autoteste.MODULOS")
        self.assertEqual(sorted(set(autoteste.MODULOS) - reais), [], "módulos listados que não existem mais")
        self.assertEqual(len(autoteste.MODULOS), len(set(autoteste.MODULOS)))


if __name__ == "__main__":
    unittest.main()
