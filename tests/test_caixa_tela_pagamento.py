"""A tela do caixa renovada (cabeçalho, total e ações na coluna da direita, lista com convite quando vazia) e o seletor de
pagamento (Dinheiro, Débito, Crédito e Pix): nada que o operador digite pode travar o caixa nem fechar a venda com um valor errado."""
from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest import mock

from src.core.erros import ErroNegocio
from src.core.valor_pagamento import LIMITE_VALOR_CENT, ler_valor_pagamento


class TesteLeituraDoValor(unittest.TestCase):
    def test_formatos_aceitos(self):
        casos = {"25": 2500, "25,5": 2550, "25,50": 2550, "25.50": 2550, "1.000": 100000, "1.000,50": 100050,
                 "1.000.000": 100000000, "R$ 10,00": 1000, " 10 ": 1000, ",5": 50, ".5": 50, "0,01": 1}
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(ler_valor_pagamento(texto), esperado)

    def test_formatos_recusados(self):
        for texto in ("", "   ", "abc", "1e5", "-5", "+5", "0", "0,00", "1,2,3", "10,555", "1,5,", "5,", "٣", "inf", "nan",
                      "1..000", "12a", "1 2 3 4,5,6"):
            with self.subTest(texto=texto):
                with self.assertRaises(ValueError):
                    ler_valor_pagamento(texto)

    def test_valor_absurdo_e_recusado_com_mensagem(self):
        with self.assertRaises(ValueError) as c:
            ler_valor_pagamento("9" * 25)
        self.assertIn("alto demais", str(c.exception))
        self.assertEqual(ler_valor_pagamento("1.000.000"), LIMITE_VALOR_CENT)         # o limite em si ainda vale
        with self.assertRaises(ValueError):
            ler_valor_pagamento("1.000.001")


if __name__ == "__main__":
    unittest.main()
