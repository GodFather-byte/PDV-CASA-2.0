"""tools.rodar_testes: o relatório de um módulo que falhou tem de sair mesmo num terminal que não é UTF-8 (Windows)."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import rodar_testes


class TesteRelatorioEmTerminalCp1252(unittest.TestCase):
    def _rodar(self, resultado):
        """Roda o `main` com a saída padrão em cp1252 estrito, como o console do Windows no CI."""
        bruto = io.BytesIO()
        saida = io.TextIOWrapper(bruto, encoding="cp1252", errors="strict")
        with tempfile.TemporaryDirectory() as pasta, \
                mock.patch.object(rodar_testes, "TEMPOS", Path(pasta) / "tempos.json"), \
                mock.patch.object(rodar_testes, "rodar", return_value=resultado), \
                mock.patch.object(sys, "stdout", saida):
            codigo = rodar_testes.main(["tests.test_exemplo"])
            saida.flush()
        return codigo, bruto.getvalue().decode("cp1252")

    def test_saida_com_caractere_fora_do_cp1252_nao_derruba_o_relatorio(self):
        # "�" é o que sobra quando a saída do módulo não era UTF-8; "✓" e "🛵" aparecem em mensagens de teste.
        falha = "AssertionError: esperado � ✓ 🛵 módulos que faltam"
        codigo, texto = self._rodar(("tests.test_exemplo", "FALHOU", 1.5, falha))
        self.assertEqual(codigo, 1)
        self.assertIn("===== FALHOU: tests.test_exemplo =====", texto)
        self.assertIn("AssertionError: esperado", texto)
        self.assertIn("módulos que faltam", texto)                  # o que cabe no cp1252 sai inteiro
        self.assertIn("0/1 módulos OK", texto)

    def test_modulo_ok_devolve_zero(self):
        codigo, texto = self._rodar(("tests.test_exemplo", "OK", 0.2, ""))
        self.assertEqual(codigo, 0)
        self.assertIn("1/1 módulos OK", texto)


if __name__ == "__main__":
    unittest.main()
