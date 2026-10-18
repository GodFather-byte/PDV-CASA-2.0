"""Testes Qt da janela Telegram; toda a Bot API é simulada."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from PySide6.QtWidgets import QApplication, QMessageBox

from src.controllers.telegram_controller import TelegramController
from src.core.erros import ErroPermissao
from src.ui.contexto import Contexto
from src.ui_qt.telegram import JanelaTelegram
from tests.base import BaseTeste


TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"


class TestTelegramQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.chamadas_http = []
        self.ctx.telegram = TelegramController(self.banco, http=self.http)
        self.janelas = []
        self.remendos = []
        for nome, valor in (
            ("warning", None), ("information", None),
            ("question", QMessageBox.StandardButton.Yes),
        ):
            remendo = patch.object(QMessageBox, nome, return_value=valor)
            setattr(self, nome, remendo.start())
            self.remendos.append(remendo)
        self.addCleanup(self._limpar)

    def _limpar(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for remendo in self.remendos:
            remendo.stop()

    def http(self, url, dados, timeout):
        self.chamadas_http.append((url, dict(dados), timeout, threading.get_ident()))
        if url.endswith("/getMe"):
            return {"ok": True, "result": {"id": 91, "username": "loja_bot"}}
        return {"ok": True, "result": {"message_id": len(self.chamadas_http)}}

    def janela(self):
        janela = JanelaTelegram(self.ctx)
        self.janelas.append(janela)
        return janela

    def _esperar(self, predicado, timeout=3):
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            self.aplicacao.processEvents()
            if predicado():
                return True
            time.sleep(0.005)
        self.aplicacao.processEvents()
        return bool(predicado())

    def _configurar_pareamento(self):
        self.banco.cfg_set("telegram_token", TOKEN)
        self.banco.cfg_set("telegram_bot_usuario", "loja_bot")
        self.ctx.telegram._parear(456, "Dono")

    def test_abertura_preserva_estado_real_sem_ativar_ou_falar_com_telegram(self):
        janela = self.janela()
        self.assertEqual(self.chamadas_http, [])
        self.assertFalse(janela.var_ativo.isChecked())
        self.assertEqual(janela.ent_token.text(), "")
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertEqual(self.banco.cfg("telegram_ativo"), "N")

        self._configurar_pareamento()
        janela.atualizar()
        self.assertTrue(janela.var_ativo.isChecked())
        self.assertEqual(janela.grade.rowCount(), 1)
        self.assertEqual(janela.grade.item(0, 0).text(), "Dono")
        self.assertEqual(janela.grade.item(0, 0).data(256), 456)
        self.assertEqual(self.chamadas_http, [])
        janela.close()
        reaberta = self.janela()
        self.assertEqual(reaberta.ent_token.text(), TOKEN)
        self.assertEqual(reaberta.grade.rowCount(), 1)

    def test_conectar_salva_token_validado_na_thread_da_gui(self):
        janela = self.janela()
        janela.ent_token.setText(TOKEN)
        thread_gui = threading.get_ident()
        threads_gravacao = []
        cfg_set_original = self.banco.cfg_set

        def cfg_set(chave, valor):
            threads_gravacao.append(threading.get_ident())
            return cfg_set_original(chave, valor)

        with patch.object(self.banco, "cfg_set", side_effect=cfg_set):
            self.assertTrue(janela.conectar())
            self.assertTrue(self._esperar(lambda: janela._solicitacao is None))
        self.assertEqual(self.ctx.telegram.token, TOKEN)
        self.assertEqual(self.ctx.telegram.bot_usuario(), "loja_bot")
        self.assertEqual(threads_gravacao, [thread_gui, thread_gui, thread_gui])
        self.assertNotEqual(self.chamadas_http[0][3], thread_gui)
        self.assertEqual(self.chamadas_http[0][2], 15)
        self.assertEqual(janela.ent_token.text(), TOKEN)
        self.assertEqual(self.information.call_count, 0)

    def test_falha_de_conexao_mantem_token_digitado_e_nao_grava_segredo(self):
        def falhar(url, dados, timeout):
            self.chamadas_http.append((url, dict(dados), timeout, threading.get_ident()))
            return {"ok": False, "description": f"erro para {TOKEN}", "error_code": 401}

        self.ctx.telegram = TelegramController(self.banco, http=falhar)
        janela = self.janela()
        janela.ent_token.setText(TOKEN)
        janela.conectar()
        self.assertTrue(self._esperar(lambda: janela._solicitacao is None))
        self.assertEqual(self.ctx.telegram.token, "")
        self.assertEqual(janela.ent_token.text(), TOKEN)
        self.assertIn("O Telegram não aceitou esse token", self.warning.call_args.args[2])
        self.assertNotIn(TOKEN, janela.lbl_status.text())
        self.assertNotIn(TOKEN, self.warning.call_args.args[2])

    def test_enviar_teste_em_thread_e_falha_sem_confirmar_sucesso(self):
        self._configurar_pareamento()
        janela = self.janela()
        thread_gui = threading.get_ident()
        self.assertTrue(janela.testar())
        self.assertTrue(self._esperar(lambda: janela._solicitacao is None))
        self.assertEqual(len(self.chamadas_http), 1)
        self.assertEqual(self.chamadas_http[0][1]["chat_id"], 456)
        self.assertNotEqual(self.chamadas_http[0][3], thread_gui)
        self.assertIn("Mensagem de teste enviada para 1 celular(es)", self.information.call_args.args[2])
        self.assertEqual(self.chamadas_http[0][2], 15)

        def falhar(url, dados, timeout):
            self.chamadas_http.append((url, dict(dados), timeout, threading.get_ident()))
            return {"ok": False, "description": "O dono bloqueou o bot.", "error_code": 403}

        janela.tg = self.ctx.telegram = TelegramController(self.banco, http=falhar)
        janela.testar()
        self.assertTrue(self._esperar(lambda: janela._solicitacao is None))
        self.assertIn("O dono bloqueou o bot", self.warning.call_args.args[2])
        self.assertEqual(self.information.call_count, 1)

    def test_codigo_remocao_cancelada_e_alternancia_validam_permissao(self):
        janela = self.janela()
        self.assertFalse(janela.gerar_codigo())
        self.assertIn("Cole primeiro", self.warning.call_args.args[2])
        self._configurar_pareamento()
        janela.atualizar()
        janela.grade.selectRow(0)
        self.question.return_value = QMessageBox.StandardButton.No
        self.assertFalse(janela.remover())
        self.assertEqual(len(self.ctx.telegram.chats()), 1)
        self.assertTrue(janela.var_ativo.isChecked())
        janela.var_ativo.setChecked(False)
        self.assertEqual(self.banco.cfg("telegram_ativo"), "N")
        self.question.assert_called_once()

    def test_revogacao_antes_dos_resultados_de_teste_sucesso_e_erro(self):
        self._configurar_pareamento()
        for falha in (False, True):
            with self.subTest(falha=falha):
                self.banco.executar("UPDATE operadores SET nivel = 4")
                iniciou, liberar = threading.Event(), threading.Event()
                self.addCleanup(liberar.set)

                def http(url, dados, timeout):
                    iniciou.set()
                    liberar.wait(2)
                    if falha:
                        raise OSError(f"erro secreto: {TOKEN}")
                    return {"ok": True, "result": {}}

                self.ctx.telegram = TelegramController(self.banco, http=http)
                janela = self.janela()
                janela.testar()
                self.assertTrue(iniciou.wait(1))
                self.banco.executar("UPDATE operadores SET nivel = 0")
                liberar.set()
                self.assertTrue(self._esperar(lambda: janela._solicitacao is None))
                self.assertEqual(janela.ent_token.text(), "")
                self.assertFalse(janela.btn_testar.isEnabled())
                self.assertIn("não permite", janela.lbl_status.text())
                self.assertNotIn(TOKEN, str(self.warning.call_args))
                self.information.assert_not_called()
                janela.close()

    def test_bloqueio_nao_emite_sinais_nao_reentra_nem_altera_ativo(self):
        self._configurar_pareamento()
        janela = self.janela()
        with patch.object(janela, "_alternar", wraps=janela._alternar) as alternar, \
                patch.object(self.ctx.cadastros, "obter", wraps=self.ctx.cadastros.obter) as obter:
            self.banco.executar("UPDATE operadores SET ativo = 0")
            self.assertFalse(janela.atualizar())
            self.assertEqual(obter.call_count, 1)
            alternar.assert_not_called()
        self.assertEqual(self.banco.cfg("telegram_ativo"), "S")
        self.assertEqual(janela.ent_token.text(), "")
        self.assertFalse(janela.var_ativo.isChecked())

    def test_status_e_erros_sanitizados_sem_alegar_entrega(self):
        self._configurar_pareamento()
        janela = self.janela()
        self.assertNotIn("Funcionando", janela.lbl_status.text())
        self.assertNotIn("recebendo", janela.lbl_status.text())
        self.banco.cfg_set("telegram_erro", f"Falha https://api.telegram.org/bot{TOKEN}/getMe")
        janela.atualizar()
        self.assertIn("[token oculto]", janela.lbl_status.text())
        self.assertNotIn(TOKEN, janela.lbl_status.text())

        def falhar(url, dados, timeout):
            raise TimeoutError(f"expirou https://api.telegram.org/bot{TOKEN}/sendMessage")

        janela.tg = self.ctx.telegram = TelegramController(self.banco, http=falhar)
        janela.testar()
        self.assertTrue(self._esperar(lambda: janela._solicitacao is None))
        self.assertNotIn(TOKEN, self.warning.call_args.args[2])
        janela.atualizar()
        self.assertNotIn(TOKEN, janela.lbl_status.text())
        self.assertNotIn("Funcionando", janela.lbl_status.text())

    def test_close_reject_limpa_segredos_e_descarta_envios_restantes(self):
        self._configurar_pareamento()
        self.ctx.telegram._parear(789, "Segundo")
        for acao in ("close", "reject"):
            with self.subTest(acao=acao):
                iniciou, liberar = threading.Event(), threading.Event()
                self.addCleanup(liberar.set)
                envios = []

                def http(url, dados, timeout):
                    envios.append(dados["chat_id"])
                    iniciou.set()
                    liberar.wait(2)
                    return {"ok": True, "result": {}}

                self.ctx.telegram = TelegramController(self.banco, http=http)
                janela = self.janela()
                janela.var_mostrar.setChecked(True)
                janela.gerar_codigo()
                janela.testar()
                self.assertTrue(iniciou.wait(1))
                getattr(janela, acao)()
                self.assertEqual(janela.ent_token.text(), "")
                self.assertEqual(janela.lbl_codigo.text(), "")
                self.assertFalse(janela.var_mostrar.isChecked())
                self.assertFalse(janela._timer.isActive())
                self.assertIsNone(janela._solicitacao)
                liberar.set()
                self.assertTrue(QThreadPool.globalInstance().waitForDone(2000))
                self.aplicacao.processEvents()
                self.assertEqual(envios, [456])
                self.information.assert_not_called()
                self.assertEqual(janela.lbl_status.text(), "")

    def test_desabilita_reentrada_durante_rede_e_timer_nao_reabilita_conectar(self):
        iniciou, liberar = threading.Event(), threading.Event()
        self.addCleanup(liberar.set)

        def http(url, dados, timeout):
            iniciou.set()
            liberar.wait(2)
            return {"ok": True, "result": {"username": "loja_bot"}}

        self.ctx.telegram = TelegramController(self.banco, http=http)
        janela = self.janela()
        janela.ent_token.setText(TOKEN)
        self.assertTrue(janela.conectar())
        self.assertTrue(iniciou.wait(1))
        janela.atualizar()
        self.assertFalse(janela.btn_conectar.isEnabled())
        self.assertFalse(janela.conectar())
        liberar.set()
        self.assertTrue(self._esperar(lambda: janela._solicitacao is None))

    def test_revogacao_durante_conexao_bloqueia_persistencia(self):
        iniciou = threading.Event()
        liberar = threading.Event()

        def http(url, dados, timeout):
            iniciou.set()
            liberar.wait(2)
            return {"ok": True, "result": {"id": 91, "username": "loja_bot"}}

        self.ctx.telegram = TelegramController(self.banco, http=http)
        janela = self.janela()
        janela.ent_token.setText(TOKEN)
        janela.conectar()
        self.assertTrue(iniciou.wait(1))
        self.banco.executar("UPDATE operadores SET nivel = 0 WHERE id = ?", (self.ctx.operador_id,))
        liberar.set()
        self.assertTrue(self._esperar(lambda: janela._solicitacao is None))
        self.assertEqual(self.ctx.telegram.token, "")
        self.assertIn("não permite", janela.lbl_status.text())
        self.assertEqual(self.information.call_count, 0)

    def test_fechamento_descarta_resultado_de_rede_em_andamento(self):
        iniciou = threading.Event()
        liberar = threading.Event()
        finalizou = threading.Event()

        def http(url, dados, timeout):
            iniciou.set()
            liberar.wait(2)
            finalizou.set()
            return {"ok": True, "result": {"id": 91, "username": "loja_bot"}}

        self.ctx.telegram = TelegramController(self.banco, http=http)
        janela = self.janela()
        janela.ent_token.setText(TOKEN)
        janela.conectar()
        self.assertTrue(iniciou.wait(1))
        janela.close()
        liberar.set()
        self.assertTrue(finalizou.wait(1))
        self.aplicacao.processEvents()
        self.assertEqual(self.ctx.telegram.token, "")
        self.assertEqual(self.information.call_count, 0)
        self.assertEqual(self.warning.call_count, 0)

    def test_acesso_inativo_sem_sessao_ou_nivel_insuficiente_e_negado(self):
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            JanelaTelegram(self.ctx)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        id_operador = self.ctx.operador_id
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (id_operador,))
        with self.assertRaises(ErroPermissao):
            JanelaTelegram(self.ctx)
        self.banco.executar("UPDATE operadores SET ativo = 1, nivel = 0 WHERE id = ?", (id_operador,))
        with self.assertRaises(ErroPermissao):
            JanelaTelegram(self.ctx)

    def test_exigir_acesso_publico_revalida_reabertura_sem_descartar_edicao_permitida(self):
        janela = self.janela()
        janela.ent_token.setText("token digitado ainda não salvo")
        janela.show()
        self.aplicacao.processEvents()

        self.assertTrue(janela.exigir_acesso())
        self.assertEqual(janela.ent_token.text(), "token digitado ainda não salvo")

        self.banco.executar(
            "UPDATE operadores SET nivel = 0 WHERE id = ?", (self.ctx.operador_id,))
        with self.assertRaises(ErroPermissao):
            janela.exigir_acesso()
        self.assertEqual(janela.ent_token.text(), "")


if __name__ == "__main__":
    unittest.main()
