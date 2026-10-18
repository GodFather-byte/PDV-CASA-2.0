"""Indicador de licença: validade e falhas visíveis, sem depender de consulta HTTP."""
from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from src.core.licenca import Estado
from src.ui.app import App
from src.ui.menu_widgets import PAL


class TestePainelLicenca(unittest.TestCase):
    def painel(self, estado, configuracao=None):
        cfg = configuracao or {}
        painel = SimpleNamespace(banco=mock.Mock(), aviso_licenca=mock.Mock())
        painel.banco.cfg.side_effect = lambda chave: cfg.get(chave, "")
        with mock.patch("src.core.licenca.estado", return_value=estado):
            App.mostrar_situacao_licenca(painel)
        return painel.aviso_licenca

    def test_desativada_nao_mostra_aviso(self):
        aviso = self.painel(Estado("desativada"))
        aviso.pack_forget.assert_called_once()
        aviso.definir.assert_not_called()

    def test_valida_mostra_prazo_e_ultima_consulta(self):
        aviso = self.painel(Estado("ok", date(2026, 11, 16), 31),
                           {"licenca_nuvem_sucesso_em": "2026-10-16 15:00:00"})
        texto, cor = aviso.definir.call_args.args
        self.assertIn("16/11/2026", texto)
        self.assertIn("16/10/2026", texto)
        self.assertEqual(cor, PAL["verde"])

    def test_falha_de_rede_e_visivel_sem_declarar_licenca_bloqueada(self):
        aviso = self.painel(Estado("ok", date(2026, 11, 16), 31), {"licenca_nuvem_erro": "Sem conexão."})
        texto, cor = aviso.definir.call_args.args
        self.assertIn("Sem conexão.", texto)
        self.assertEqual(cor, PAL["ambar"])

    def test_bloqueada_destaca_mensagem_em_vermelho(self):
        aviso = self.painel(Estado("bloqueada", date(2026, 10, 1), -15, "Renove sua licença."))
        texto, cor = aviso.definir.call_args.args
        self.assertIn("Renove sua licença.", texto)
        self.assertEqual(cor, PAL["vermelho"])
