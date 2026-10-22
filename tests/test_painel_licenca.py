"""Indicador de licença: validade e falhas visíveis, sem depender de consulta HTTP."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import mock

from src.core.licenca import Estado
from src.ui.app import App
from src.ui.menu_widgets import PAL
from tests.base import BaseTeste


class TestePainelLicenca(BaseTeste):
    def painel(self, estado, configuracao=None):
        for chave, valor in (configuracao or {}).items():
            self.banco.cfg_set(chave, valor)
        painel = SimpleNamespace(banco=self.banco, aviso_licenca=mock.Mock())
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

    def test_ponte_ativa_mostra_contato_proprio_em_vez_da_nuvem_legada(self):
        aviso = self.painel(Estado("ok", date(2026, 11, 16), 31), {
            "central_ponte_ativa": "S",
            "central_ponte_sucesso_em": "2026-10-17 15:00:00",
            "licenca_nuvem_sucesso_em": "2026-10-16 15:00:00",
            "licenca_nuvem_erro": "Falha antiga da nuvem.",
        })
        texto, cor = aviso.definir.call_args.args
        self.assertIn("17/10/2026", texto)
        self.assertNotIn("16/10/2026", texto)
        self.assertNotIn("Falha antiga", texto)
        self.assertEqual(cor, PAL["verde"])

    def test_erro_da_ponte_ativa_orienta_suporte_sem_expor_detalhes(self):
        aviso = self.painel(Estado("ok", date(2026, 11, 16), 31), {
            "central_ponte_ativa": "S",
            "central_ponte_erro": "Detalhe técnico da conexão.",
        })
        texto, cor = aviso.definir.call_args.args
        self.assertIn("Ponte: consulte Configurações ou Suporte no Telegram.", texto)
        self.assertNotIn("Detalhe técnico", texto)
        self.assertEqual(cor, PAL["ambar"])
