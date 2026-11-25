"""Caixa adicional: as atualizações automáticas da tela não viram erro quando a ligação com o principal pisca."""
from __future__ import annotations

import unittest
from pathlib import Path

from src.database import rede


class TesteTolerarQueda(unittest.TestCase):
    def test_queda_pula_a_rodada_e_a_proxima_roda(self):
        chamadas = []

        def atualizar():
            chamadas.append(1)
            if len(chamadas) == 1:
                raise rede.ErroLigacao("A ligação com o caixa principal caiu durante a operação.")
            return "ok"

        rodada = rede.tolerar_queda(atualizar, "teste")
        with self.assertLogs("pdv.rede", level="WARNING") as log:
            self.assertIsNone(rodada())
        self.assertIn("Atualização automática pulada (teste)", log.output[0])
        self.assertEqual(rodada(), "ok")

    def test_versao_diferente_e_outros_erros_continuam_subindo(self):
        def versao():
            raise rede.ErroVersaoDiferente("versão diferente", versao_principal="9.9.9")

        def outro():
            raise ValueError("bug de verdade")

        with self.assertRaises(rede.ErroVersaoDiferente):
            rede.tolerar_queda(versao)()
        with self.assertRaises(ValueError):
            rede.tolerar_queda(outro)()

    def test_relogios_da_tela_usam_a_tolerancia(self):
        raiz = Path(__file__).resolve().parents[1] / "src" / "ui_qt"
        esperado = {"quartos.py": 4, "app.py": 1, "caixa.py": 1, "cozinha.py": 1, "estado_nuvem.py": 1, "hotel.py": 1}
        for arquivo, quantos in esperado.items():
            self.assertEqual((raiz / arquivo).read_text(encoding="utf-8").count("rede.tolerar_queda("), quantos, arquivo)


if __name__ == "__main__":
    unittest.main()
