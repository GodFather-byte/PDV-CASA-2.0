"""Caixa: depois de fechar o caixa volta à tela de operador, e o ADM entra por cima do caixa sem fechar turno nem
venda, voltando sozinho ao operador."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from tests.test_qt_app import BaseQt
from src.ui_qt.app import JanelaPrincipal


class _Dialogos:
    def __init__(self, textos):
        self.textos, self.erros = list(textos), []

    def pedir_texto(self, *_a, **_k):
        return self.textos.pop(0) if self.textos else None

    def erro(self, titulo, texto):
        self.erros.append(texto)


class TesteModoAdm(BaseQt):
    def preparar(self):
        app = self.app()
        id_ = self.ctx.cadastros.salvar("operadores", {"nome": "CAIXA", "senha": "Segura123", "nivel": 0})
        app.ctx.operador = app.ctx.acesso.operador(id_)
        app.principal = JanelaPrincipal(app)
        caixa = app.principal.abrir_caixa()
        return app, caixa

    def test_adm_entra_por_cima_do_caixa_e_volta(self):
        app, caixa = self.preparar()
        caixa.dialogos = _Dialogos(["senha-errada"])
        caixa.entrar_como_adm()
        self.assertIn("não é ADM", caixa.dialogos.erros[-1])
        self.assertEqual(app.ctx.operador.nome, "CAIXA")
        caixa.dialogos = _Dialogos(["ADM"])
        caixa.entrar_como_adm()
        principal = app.principal
        self.assertEqual(app.ctx.operador.nome, "ADM")
        self.assertFalse(caixa.isEnabled())                       # o caixa fica parado enquanto o ADM mexe
        self.assertTrue(principal.btn_voltar_operador.isVisibleTo(principal))
        self.assertIn("CAIXA", principal.btn_voltar_operador.text())
        self.assertTrue(principal._timer_adm.isActive())
        principal.btn_voltar_operador.click()
        self.assertEqual(app.ctx.operador.nome, "CAIXA")
        self.assertTrue(caixa.isEnabled())
        self.assertFalse(principal._timer_adm.isActive())
        eventos = [r["evento"] for r in self.banco.todos("SELECT evento FROM log_eventos ORDER BY id")] \
            if self.banco.valor("SELECT COUNT(*) FROM sqlite_master WHERE name = 'log_eventos'", (), 0) else []
        if eventos:
            self.assertIn("adm_entrou_no_caixa", eventos)
            self.assertIn("adm_saiu_do_caixa", eventos)

    def test_volta_sozinho_depois_do_tempo(self):
        app, caixa = self.preparar()
        caixa.dialogos = _Dialogos(["ADM"])
        caixa.entrar_como_adm()
        app.principal._timer_adm.timeout.emit()                  # passaram 5 minutos sem mexer
        self.assertEqual(app.ctx.operador.nome, "CAIXA")
        self.assertTrue(caixa.isEnabled())

    def test_depois_de_fechar_o_caixa_volta_para_a_tela_de_operador(self):
        app, caixa = self.preparar()
        with patch.object(app, "encerrar_sessao") as encerrar:
            caixa._voltar_ao_login()
        encerrar.assert_called_once()
        self.assertTrue(self.banco.cfg_bool("voltar_login_apos_fechar", True))
