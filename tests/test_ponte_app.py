"""A ponte deve iniciar antes do login, sem depender do processo --sync."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.ui.app import App


class TestePonteApp(unittest.TestCase):
    def test_banco_em_memoria_nao_inicia_servico(self):
        app = object.__new__(App)
        app.banco = SimpleNamespace(caminho=":memory:")
        app.servico_ponte = None
        with patch("src.ui.app.ServicoPonte") as classe:
            app._iniciar_ponte()
        classe.assert_not_called()

    def test_inicia_antes_do_login_e_para_antes_de_fechar_banco(self):
        app = object.__new__(App)
        app.banco = MagicMock()
        app.banco.caminho = "somente-mock.db"
        app.root = MagicMock()
        app.ctx = MagicMock()
        app.ctx.utilitarios.idade_backup_horas.return_value = 1
        app.servico_telegram = None
        app.servico_impressao = None
        app.servico_ponte = None
        app._iniciar_telegram = MagicMock()
        app._iniciar_fila_impressao = MagicMock()
        ordem = []
        app.root.mainloop.side_effect = lambda: ordem.append("login")
        app.banco.fechar.side_effect = lambda: ordem.append("fechou_banco")
        with patch("src.ui.app.ServicoPonte") as classe:
            classe.return_value.iniciar.side_effect = lambda: ordem.append("iniciou_ponte")
            classe.return_value.parar.side_effect = lambda: ordem.append("parou_ponte")
            app.run()
        self.assertEqual(ordem, ["iniciou_ponte", "login", "parou_ponte", "fechou_banco"])
