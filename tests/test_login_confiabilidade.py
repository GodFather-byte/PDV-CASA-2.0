"""Fluxo assíncrono do login sem depender de Tk instalado ou de servidor gráfico."""
from __future__ import annotations

import importlib.util
import sys
import threading
import types
from datetime import date
from pathlib import Path
from unittest import mock

from src.core import ed25519, licenca
from src.core.erros import ErroNegocio
from src.sync import licenca_nuvem
from tests.base import BaseTeste


def carregar_login():
    import src.ui

    class ToplevelFalso:
        def destroy(self):
            self.destruida = True

    tk = types.ModuleType("tkinter")
    tk.Toplevel = ToplevelFalso
    tk.TclError = RuntimeError
    tk.ttk = types.ModuleType("tkinter.ttk")
    tema = types.ModuleType("src.ui.tema")
    tema.mensagem = mock.Mock()
    widgets = types.ModuleType("src.ui.menu_widgets")
    widgets.PAL = {"texto": "texto", "verde": "verde", "vermelho": "vermelho"}
    widgets.FONTE = "fonte"
    widgets.misturar = mock.Mock()
    caminho = Path(__file__).resolve().parents[1] / "src" / "ui" / "login.py"
    spec = importlib.util.spec_from_file_location("login_confiabilidade", caminho)
    modulo = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"tkinter": tk, "tkinter.ttk": tk.ttk,
                                      "src.ui.tema": tema, "src.ui.menu_widgets": widgets}), \
            mock.patch.object(src.ui, "tema", tema, create=True):
        spec.loader.exec_module(modulo)
    return modulo


class TesteLoginAssincrono(BaseTeste):
    def setUp(self):
        super().setUp()
        self.modulo = carregar_login()
        self.banco.cfg_set("licenca_exigir", "S")
        self.banco.cfg_set("api_url", "https://nuvem/v1")
        self.banco.cfg_set("api_token", "token-teste")
        self.janela = object.__new__(self.modulo.JanelaLogin)
        j = self.janela
        j.ctx = types.SimpleNamespace(banco=self.banco, acesso=mock.Mock())
        j.ctx.acesso.autenticar.return_value = types.SimpleNamespace(nome="ADM")
        j.ctx.acesso.precisa_trocar_senha.return_value = False
        j.operador = None
        j._entrando = False
        j._fechada = False
        j._consulta_licenca = None
        j._consulta_after = None
        j.btn_entrar = mock.Mock()
        j.lbl_msg = mock.Mock()
        j.ent_senha = mock.Mock()
        j.var_usuario = mock.Mock()
        j.var_usuario.get.return_value = "ADM"
        j.var_senha = mock.Mock()
        j.var_senha.get.return_value = "Segredo1"
        j.after = mock.Mock(return_value="consulta-agendada")
        j.after_cancel = mock.Mock()
        j.pedir_licenca = mock.Mock(return_value=False)
        self.liberar = threading.Event()
        self.iniciada = threading.Event()
        self.threads = []
        self.thread_rede = None
        classe_thread = threading.Thread

        def criar_thread(**kw):
            thread = classe_thread(**kw)
            self.threads.append(thread)
            return thread

        def consultar(*args, **kw):
            self.thread_rede = threading.get_ident()
            self.iniciada.set()
            if not self.liberar.wait(3):
                raise RuntimeError("Teste não liberou a rede.")
            return licenca_nuvem.ResultadoConsulta(False)

        for patch in (mock.patch.object(self.modulo.threading, "Thread", side_effect=criar_thread),
                      mock.patch.object(licenca_nuvem, "consultar_resultado", side_effect=consultar)):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.encerrar_threads)

    def encerrar_threads(self):
        self.liberar.set()
        for thread in self.threads:
            thread.join(3)

    def iniciar(self):
        self.janela.entrar()
        self.assertTrue(self.iniciada.wait(2))

    def receber(self):
        self.encerrar_threads()
        self.assertTrue(all(not t.is_alive() for t in self.threads))
        self.janela._receber_licenca()

    def test_rede_nao_bloqueia_tk_nem_aceita_cliques_repetidos(self):
        self.iniciar()
        self.assertNotEqual(self.thread_rede, threading.get_ident())
        self.assertTrue(self.janela._entrando)
        self.janela.btn_entrar.configure.assert_called_with(state="disabled")
        self.janela.entrar()
        self.janela.entrar()
        self.assertEqual(len(self.threads), 1)
        self.janela.ctx.acesso.autenticar.assert_not_called()
        self.janela._receber_licenca()
        self.assertEqual(self.janela.after.call_count, 2)
        self.receber()
        self.janela.pedir_licenca.assert_called_once()
        self.assertFalse(self.janela._entrando)
        self.janela.btn_entrar.configure.assert_called_with(state="normal")
        self.assertEqual(self.banco.cfg(licenca_nuvem.CHAVE_FALHAS), "1")

    def test_renovacao_e_retomada_do_login_ocorrem_na_thread_tk(self):
        semente = bytes(range(32))
        codigo = licenca.gerar_licenca(semente, "LOJA-1", 30, date(2026, 10, 3))
        with mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", ed25519.chave_publica(semente).hex()), \
                mock.patch.object(licenca_nuvem, "aplicar", wraps=licenca_nuvem.aplicar) as aplicar:
            self.iniciar()
            self.encerrar_threads()
            self.janela._consulta_licenca.get_nowait()
            self.janela._consulta_licenca.put((licenca_nuvem.ResultadoConsulta(True, codigo), None))
            thread_tk = threading.get_ident()
            aplicar.side_effect = lambda banco, valor: (
                self.assertEqual(threading.get_ident(), thread_tk),
                licenca.ativar(banco, valor))[1]
            self.janela._receber_licenca()
            aplicar.assert_called_once_with(self.banco, codigo)
        self.assertEqual(len(self.threads), 1)
        self.assertEqual(self.janela.operador.nome, "ADM")
        self.janela.pedir_licenca.assert_not_called()
        self.assertTrue(self.janela._fechada)
        self.assertTrue(self.janela.destruida)

    def test_fechamento_cancela_callback_e_descarta_resultado_tardio(self):
        self.iniciar()
        self.janela.destroy()
        self.janela.after_cancel.assert_called_once_with("consulta-agendada")
        with mock.patch.object(licenca_nuvem, "aplicar") as aplicar, \
                mock.patch.object(licenca_nuvem, "registrar_resultado") as registrar:
            self.receber()
            self.janela.entrar()
        aplicar.assert_not_called()
        registrar.assert_not_called()
        self.janela.pedir_licenca.assert_not_called()
        self.janela.ctx.acesso.autenticar.assert_not_called()

    def test_erro_de_aplicacao_e_exibido_e_libera_nova_tentativa(self):
        self.iniciar()
        with mock.patch.object(licenca_nuvem, "aplicar", side_effect=OSError("disco cheio")):
            self.receber()
        self.assertFalse(self.janela._entrando)
        self.janela.btn_entrar.configure.assert_called_with(state="normal")
        self.assertIn("disco cheio", self.janela.lbl_msg.configure.call_args.kwargs["text"])
        self.janela.ctx.acesso.autenticar.assert_not_called()
        self.janela.entrar()
        self.receber()
        self.assertEqual(len(self.threads), 2)

    def test_falha_de_rede_nao_muda_isencao_de_turno_recente(self):
        turno = {"id": 1}
        with mock.patch.object(self.modulo.TurnoController, "atual", return_value=turno), \
                mock.patch.object(licenca, "turno_vale_como_isencao", return_value=True) as isencao:
            self.iniciar()
            self.receber()
        isencao.assert_called_with(self.banco, turno)
        self.janela.pedir_licenca.assert_not_called()
        self.assertEqual(self.janela.operador.nome, "ADM")
        self.assertTrue(self.janela._fechada)

    def test_excecao_inesperada_da_rede_termina_consulta_e_reabre_entrada_manual(self):
        with mock.patch.object(licenca_nuvem, "consultar_resultado", side_effect=RuntimeError("erro de transporte")):
            self.janela.entrar()
            self.receber()
        self.assertFalse(self.janela._entrando)
        self.janela.pedir_licenca.assert_called_once()
        self.janela.ctx.acesso.autenticar.assert_not_called()
        self.assertEqual(self.banco.cfg(licenca_nuvem.CHAVE_FALHAS), "1")

    def test_licenca_nao_exigida_mantem_login_sem_rede(self):
        self.banco.cfg_set("licenca_exigir", "N")
        self.janela.entrar()
        self.assertEqual(self.threads, [])
        self.assertEqual(self.janela.operador.nome, "ADM")
        self.janela.pedir_licenca.assert_not_called()
        self.assertEqual(self.banco.cfg(licenca_nuvem.CHAVE_TENTATIVA), "")

    def test_sem_configuracao_de_nuvem_mantem_entrada_manual(self):
        self.banco.cfg_set("api_url", "")
        self.janela.entrar()
        self.assertEqual(self.threads, [])
        self.janela.pedir_licenca.assert_called_once()
        self.assertFalse(self.janela._entrando)

    def test_senha_errada_depois_da_consulta_libera_nova_entrada(self):
        self.janela.ctx.acesso.autenticar.side_effect = ErroNegocio("Senha Incorreta")
        with mock.patch.object(licenca, "turno_vale_como_isencao", return_value=True):
            self.iniciar()
            self.receber()
        self.assertIsNone(self.janela.operador)
        self.assertFalse(self.janela._entrando)
        self.janela.var_senha.set.assert_called_once_with("")
        self.janela.ent_senha.focus_set.assert_called_once()
