"""Infraestrutura comum dos testes: banco em memória e relógio controlável."""
from __future__ import annotations

import unittest
from datetime import datetime

from src.core import formatacao as fmt
from src.database.conexao import BancoDados


class BaseTeste(unittest.TestCase):
    agora = datetime(2026, 10, 3, 21, 0, 0)

    def setUp(self):
        self._hora = {"t": self.agora}
        fmt.definir_relogio(lambda: self._hora["t"])
        self.banco = BancoDados(":memory:")
        self.addCleanup(self.banco.fechar)
        self.addCleanup(fmt.definir_relogio, None)

    def avancar(self, **kw):
        from datetime import timedelta
        self._hora["t"] = self._hora["t"] + timedelta(**kw)

    # ------------------------------------------------------------- fábricas
    def novo_produto(self, nome="SKOL", preco=800, codigo=None, estoque=False, qt=0, **extra):
        from src.controllers.cadastro_controller import CadastroController
        cad = CadastroController(self.banco)
        sub = self.banco.valor("SELECT id FROM subgrupos LIMIT 1")
        un = self.banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'")
        valores = {
            "codigo": codigo or cad.proximo_codigo_produto(), "nome": nome,
            "subgrupo_id": sub, "unidade_id": un, "preco_cent": f"{preco / 100:.2f}".replace(".", ","),
            "controla_estoque": "S" if estoque else "N",
        }
        valores.update(extra)
        pid = cad.salvar("produtos", valores)
        if qt:
            self.banco.executar("UPDATE produtos SET qt_atual = ? WHERE id = ?", (qt, pid))
        return pid

    def operador_adm(self) -> int:
        return self.banco.valor("SELECT id FROM operadores WHERE nome = 'ADM'")

    def tipo(self, nome="Dinheiro") -> int:
        return self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = ?", (nome,))
