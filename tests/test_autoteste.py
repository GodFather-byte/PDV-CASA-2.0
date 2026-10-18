"""Autoteste do programa instalado (WillPDV.exe --autoteste): a lista de módulos, o relatório e a linha de comando."""
from __future__ import annotations

import importlib
import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from src import autoteste

RAIZ = Path(__file__).resolve().parents[1]


def _tk_disponivel() -> bool:
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


class TesteListaDeModulos(unittest.TestCase):
    def test_lista_acompanha_os_arquivos_de_src(self):
        """Módulo novo precisa entrar em MODULOS, senão o autoteste do executável não o confere."""
        reais = {".".join(p.relative_to(RAIZ).with_suffix("").parts) for p in (RAIZ / "src").rglob("*.py")
                 if p.name != "__init__.py"} - {"src.app"}
        self.assertEqual(sorted(reais - set(autoteste.MODULOS)), [], "módulos que faltam em autoteste.MODULOS")
        self.assertEqual(sorted(set(autoteste.MODULOS) - reais), [], "módulos listados que não existem mais")
        self.assertEqual(len(autoteste.MODULOS), len(set(autoteste.MODULOS)))


@unittest.skipUnless(_tk_disponivel(), "sem ambiente gráfico")
class TesteExecutar(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.saida = Path(self.pasta.name) / "autoteste.txt"

    def test_tudo_certo_devolve_zero_e_escreve_o_relatorio(self):
        self.assertEqual(autoteste.executar(str(self.saida)), 0)
        texto = self.saida.read_text(encoding="utf-8")
        self.assertIn("RESULTADO: TUDO CERTO", texto)
        for etapa in ("módulos", "bibliotecas", "telas"):
            self.assertIn(f"OK    {etapa}:", texto)
        self.assertNotIn("rede", texto)             # a rede só é conferida com --rede

    def test_modulo_que_nao_carrega_vira_falha_e_e_listado_pelo_nome(self):
        real = importlib.import_module

        def importar(nome, *a, **k):
            if nome == "src.ui.telegram_ui":
                raise ModuleNotFoundError("No module named 'xyz'")
            return real(nome, *a, **k)

        with mock.patch("src.autoteste.importlib.import_module", side_effect=importar):
            self.assertEqual(autoteste.executar(str(self.saida)), 1)
        texto = self.saida.read_text(encoding="utf-8")
        self.assertIn("FALHA módulos", texto)
        self.assertIn("src.ui.telegram_ui", texto)
        self.assertIn("RESULTADO: COM FALHAS", texto)
        self.assertIn("OK    telas:", texto)        # uma etapa com falha não impede as outras de rodar

    def test_rede_so_conta_quando_o_telegram_responde(self):
        from src.sync.telegram_api import ErroTelegram
        with mock.patch("src.sync.telegram_api.ClienteTelegram.quem_sou", side_effect=ErroTelegram("não autorizado", 401)):
            self.assertEqual(autoteste.executar(str(self.saida), rede=True), 0)
        self.assertIn("HTTPS com o Telegram funciona", self.saida.read_text(encoding="utf-8"))
        with mock.patch("src.sync.telegram_api.ClienteTelegram.quem_sou", side_effect=ErroTelegram("Sem conexão")):
            self.assertEqual(autoteste.executar(str(self.saida), rede=True), 1)
        self.assertIn("FALHA rede", self.saida.read_text(encoding="utf-8"))

    def test_linha_de_comando_do_programa(self):
        r = subprocess.run([sys.executable, "-m", "src.app", "--autoteste", str(self.saida)], cwd=RAIZ,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("TUDO CERTO", self.saida.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
