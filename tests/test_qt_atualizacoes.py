"""Atualizações Qt com banco isolado e rede inteiramente simulada."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from PySide6.QtWidgets import QApplication

from src.core.erros import ErroPermissao
from src.sync import atualizacoes
from src.ui.contexto import Contexto
from src.ui_qt.atualizacoes import JanelaAtualizacoes
from tests.base import BaseTeste


_CONSULTAR_HTTP = atualizacoes.consultar


def resposta(critica=False, url="https://exemplo.invalid/pdv.zip", versao="999.0.0"):
    return {"url_download": url, "versoes": [
        {"versao": versao, "notas": "Correção do troco <sem HTML>", "critica": critica},
    ]}


class TestAtualizacoesQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.banco.cfg_set("api_url", "https://exemplo.invalid/v1/sincronizar")
        self.banco.cfg_set("api_token", "token-de-teste")
        self.janelas = []
        self.liberar = threading.Event()
        self.addCleanup(self._limpar)
        self.rede = patch(
            "src.ui_qt.atualizacoes.atualizacoes.consultar", return_value=resposta())
        self.consulta = self.rede.start()
        self.navegador = patch("src.ui_qt.atualizacoes.webbrowser.open")
        self.abrir_url = self.navegador.start()

    def _limpar(self):
        self.liberar.set()
        QThreadPool.globalInstance().waitForDone(3000)
        self.aplicacao.processEvents()
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.rede.stop()
        self.navegador.stop()

    def janela(self):
        janela = JanelaAtualizacoes(self.ctx)
        self.janelas.append(janela)
        return janela

    def esperar(self, predicado):
        limite = time.monotonic() + 3
        while time.monotonic() < limite:
            self.aplicacao.processEvents()
            if predicado():
                return True
            time.sleep(0.005)
        return bool(predicado())

    def bloquear_rede(self):
        iniciou = threading.Event()

        def consultar(*args):
            iniciou.set()
            self.liberar.wait(3)
            return resposta()

        self.consulta.side_effect = consultar
        janela = self.janela()
        self.assertTrue(janela.consultar())
        self.assertTrue(iniciou.wait(1))
        return janela

    def terminar_rede(self):
        self.liberar.set()
        self.assertTrue(QThreadPool.globalInstance().waitForDone(3000))
        self.aplicacao.processEvents()

    def test_abertura_sem_rede_com_notas_e_download_apenas_por_clique(self):
        atualizacoes.gravar(self.banco, resposta())
        janela = self.janela()
        self.consulta.assert_not_called()
        self.abrir_url.assert_not_called()
        self.assertIn("999.0.0", janela.titulo.text())
        self.assertIn("<sem HTML>", janela.notas.toPlainText())
        janela.btn_baixar.click()
        self.abrir_url.assert_called_once_with("https://exemplo.invalid/pdv.zip")

    def test_consulta_manual_rede_fora_da_gui_e_persistencia_na_gui(self):
        janela = self.janela()
        gui = threading.get_ident()
        threads_rede, threads_banco = [], []
        gravar = self.banco.cfg_set

        def consultar(url, token):
            threads_rede.append(threading.get_ident())
            self.assertEqual(url, "https://exemplo.invalid/v1/sincronizar")
            self.assertEqual(token, "token-de-teste")
            return resposta()

        def cfg_set(*args):
            threads_banco.append(threading.get_ident())
            return gravar(*args)

        self.consulta.side_effect = consultar
        with patch.object(self.banco, "cfg_set", side_effect=cfg_set):
            janela.btn_consultar.click()
            self.assertTrue(self.esperar(lambda: janela._solicitacao is None))
        self.assertEqual(len(threads_rede), 1)
        self.assertNotEqual(threads_rede[0], gui)
        self.assertEqual(threads_banco, [gui, gui])
        self.assertEqual(janela.aviso["ultima"], "999.0.0")
        self.abrir_url.assert_not_called()

    def test_automatica_invisivel_respeita_intervalo_manual_forca(self):
        janela = self.janela()
        avisos = []
        janela.aviso_alterado.connect(avisos.append)
        self.assertTrue(janela.consultar_automaticamente())
        self.assertTrue(self.esperar(lambda: janela._solicitacao is None))
        self.assertFalse(janela.isVisible())
        self.assertEqual(avisos[-1]["ultima"], "999.0.0")
        self.assertFalse(janela.consultar_automaticamente())
        self.assertEqual(self.consulta.call_count, 1)
        self.assertTrue(janela.consultar())
        self.assertTrue(self.esperar(lambda: janela._solicitacao is None))
        self.assertEqual(self.consulta.call_count, 2)
        self.avancar(hours=6)
        self.assertTrue(janela.consultar_automaticamente())
        self.assertTrue(self.esperar(lambda: janela._solicitacao is None))
        self.assertEqual(self.consulta.call_count, 3)
        self.abrir_url.assert_not_called()

    def test_sem_configuracao_nao_inicia_rede(self):
        janela = self.janela()
        for chave in ("api_url", "api_token"):
            with self.subTest(chave=chave):
                anterior = self.banco.cfg(chave)
                self.banco.cfg_set(chave, "")
                self.assertFalse(janela.consultar())
                self.banco.cfg_set(chave, anterior)
        self.consulta.assert_not_called()

    def test_falha_esperada_preserva_pendente(self):
        atualizacoes.gravar(self.banco, resposta())
        janela = self.janela()
        self.consulta.return_value = None
        self.assertTrue(janela.consultar())
        self.assertTrue(self.esperar(lambda: janela._solicitacao is None))
        self.assertEqual(janela.aviso["ultima"], "999.0.0")
        self.assertIn("preservado", janela.mensagem.text())

    def test_erro_inesperado_explicito_sanitizado_sem_persistir_consulta(self):
        atualizacoes.gravar(self.banco, resposta())
        ultima_consulta = self.banco.cfg(atualizacoes.CHAVE_CONSULTA)
        self.avancar(hours=1)
        janela = self.janela()
        self.consulta.side_effect = RuntimeError("segredo token-de-teste")
        with patch.object(atualizacoes, "gravar") as gravar:
            self.assertTrue(janela.consultar())
            self.assertTrue(self.esperar(lambda: janela._solicitacao is None))
            gravar.assert_not_called()
        self.assertEqual(janela.aviso["ultima"], "999.0.0")
        self.assertIn("Erro inesperado", janela.mensagem.text())
        self.assertNotIn("token-de-teste", janela.mensagem.text())
        self.assertNotIn("segredo", janela.mensagem.text())
        self.assertNotIn("concluída", janela.mensagem.text())
        self.assertEqual(self.banco.cfg(atualizacoes.CHAVE_CONSULTA), ultima_consulta)

    def test_dispensar_persiste_versao_nao_critica(self):
        atualizacoes.gravar(self.banco, resposta())
        janela = self.janela()
        janela.btn_dispensar.click()
        self.assertEqual(self.banco.cfg(atualizacoes.CHAVE_DISPENSADA), "999.0.0")
        self.assertIsNone(janela.aviso)
        self.assertFalse(janela.btn_baixar.isEnabled())
        atualizacoes.gravar(self.banco, resposta(versao="999.1.0"))
        janela.show()
        self.assertEqual(janela.aviso["ultima"], "999.1.0")

    def test_critica_nao_pode_ser_dispensada_e_sem_link_orienta_fornecedor(self):
        atualizacoes.gravar(self.banco, resposta(critica=True, url=None))
        janela = self.janela()
        self.assertIn("IMPORTANTE", janela.titulo.text())
        self.assertIn("fornecedor", janela.notas.toPlainText())
        self.assertFalse(janela.btn_dispensar.isEnabled())
        self.assertFalse(janela.dispensar())
        self.assertFalse(janela.baixar())
        self.assertEqual(self.banco.cfg(atualizacoes.CHAVE_DISPENSADA), "")
        self.abrir_url.assert_not_called()

    def test_revalida_pendente_antes_de_dispensar_ou_baixar(self):
        atualizacoes.gravar(self.banco, resposta())
        janela = self.janela()
        atualizacoes.gravar(self.banco, resposta(critica=True, url=None))
        self.assertFalse(janela.dispensar())
        self.assertFalse(janela.baixar())
        self.abrir_url.assert_not_called()

    def test_acesso_nao_inventa_modulo_e_aceita_nivel_zero(self):
        self.banco.executar("UPDATE operadores SET nivel = 0 WHERE id = ?",
                            (self.ctx.operador_id,))
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        with patch.object(self.ctx.acesso, "exigir", side_effect=AssertionError("módulo novo")):
            janela = self.janela()
            self.assertEqual(janela.exigir_acesso(), self.ctx.operador_id)
            self.assertTrue(janela.consultar())
            self.assertTrue(self.esperar(lambda: janela._solicitacao is None))

    def test_sem_sessao_ou_inativo_impede_abertura(self):
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            self.janela()
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?",
                            (self.ctx.operador_id,))
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_logout_durante_rede_descarta_resposta(self):
        janela = self.bloquear_rede()
        self.ctx.operador = None
        self.terminar_rede()
        self.assertIsNone(janela._solicitacao)
        self.assertEqual(self.banco.cfg(atualizacoes.CHAVE_CONSULTA), "")
        self.assertFalse(janela.btn_baixar.isEnabled())

    def test_inativacao_durante_rede_descarta_resposta(self):
        self.bloquear_rede()
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?",
                            (self.ctx.operador_id,))
        self.terminar_rede()
        self.assertEqual(self.banco.cfg(atualizacoes.CHAVE_CONSULTA), "")

    def test_troca_operador_durante_rede_descarta_resposta(self):
        janela = self.bloquear_rede()
        outro = self.ctx.cadastros.salvar(
            "operadores", {"nome": "OUTRO", "senha": "123", "nivel": 4, "ativo": 1})
        self.ctx.operador = self.ctx.acesso.operador(outro)
        self.terminar_rede()
        self.assertEqual(self.banco.cfg(atualizacoes.CHAVE_CONSULTA), "")
        self.assertIn("mudou", janela.mensagem.text())

    def test_troca_configuracao_durante_rede_descarta_resposta(self):
        self.bloquear_rede()
        self.banco.cfg_set("api_token", "outra-loja")
        self.terminar_rede()
        self.assertEqual(self.banco.cfg(atualizacoes.CHAVE_CONSULTA), "")

    def test_refresh_do_mesmo_operador_durante_rede_preserva_resposta(self):
        janela = self.bloquear_rede()
        operador_id = self.ctx.operador_id
        anterior = self.ctx.operador
        self.ctx.operador = self.ctx.acesso.operador(operador_id)
        self.assertIsNot(self.ctx.operador, anterior)
        self.terminar_rede()
        self.assertNotEqual(self.banco.cfg(atualizacoes.CHAVE_CONSULTA), "")
        self.assertEqual(janela.aviso["ultima"], "999.0.0")
        self.assertEqual(janela.mensagem.text(), "Consulta concluída.")

    def test_somente_uma_consulta_em_voo(self):
        janela = self.bloquear_rede()
        self.assertFalse(janela.consultar())
        self.assertFalse(janela.consultar_automaticamente())
        self.terminar_rede()
        self.assertEqual(self.consulta.call_count, 1)

    def test_cancelamento_descarta_retorno_antigo_mesmo_com_nova_consulta(self):
        janela = self.bloquear_rede()
        numero = janela._solicitacao[0]
        janela.cancelar_consulta()
        self.terminar_rede()
        self.assertEqual(self.banco.cfg(atualizacoes.CHAVE_CONSULTA), "")
        self.consulta.side_effect = None
        self.assertTrue(janela.consultar())
        janela._receber(numero, resposta(versao="999.9.0"))
        self.assertTrue(self.esperar(lambda: janela._solicitacao is None))
        self.assertEqual(janela.aviso["ultima"], "999.0.0")

    def test_timer_expirado_descarta_retorno(self):
        janela = self.bloquear_rede()
        janela._limite.start(1)
        self.assertTrue(self.esperar(lambda: janela._solicitacao is None))
        self.assertIn("demorou", janela.mensagem.text())
        self.terminar_rede()
        self.assertEqual(self.banco.cfg(atualizacoes.CHAVE_CONSULTA), "")

    def test_fechar_reject_e_accept_descartam_retorno(self):
        for acao in ("close", "reject", "accept"):
            with self.subTest(acao=acao):
                self.liberar.clear()
                janela = self.bloquear_rede()
                getattr(janela, acao)()
                self.terminar_rede()
                self.assertEqual(self.banco.cfg(atualizacoes.CHAVE_CONSULTA), "")
                self.assertFalse(janela._limite.isActive())

    def test_timer_pode_consultar_novamente_depois_de_fechar_sem_popup(self):
        janela = self.bloquear_rede()
        janela.close()
        self.terminar_rede()
        self.consulta.side_effect = None
        self.assertTrue(janela.consultar_automaticamente())
        self.assertTrue(self.esperar(lambda: janela._solicitacao is None))
        self.assertFalse(janela.isVisible())
        self.assertEqual(janela.aviso["ultima"], "999.0.0")

    def test_sessao_revogada_impede_download_e_dispensar_e_limpa_notas(self):
        atualizacoes.gravar(self.banco, resposta())
        janela = self.janela()
        self.ctx.operador = None
        self.assertFalse(janela.baixar())
        self.assertFalse(janela.dispensar())
        self.assertEqual(janela.notas.toPlainText(), "")
        self.assertIsNone(janela.aviso)
        self.abrir_url.assert_not_called()

    def test_servico_de_rede_preserva_timeout_existente(self):
        http = Mock()
        http.get.return_value = SimpleNamespace(status_code=200, json=lambda: resposta())
        self.assertEqual(_CONSULTAR_HTTP("https://exemplo.invalid", "token", http), resposta())
        self.assertEqual(http.get.call_args.kwargs["timeout"], (3, 10))


if __name__ == "__main__":
    unittest.main()
