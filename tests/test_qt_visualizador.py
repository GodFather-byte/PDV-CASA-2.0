"""Saídas do visualizador Qt simuladas: nenhum arquivo da loja ou hardware."""
import os
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QPlainTextEdit

from src.core.erros import ErroPermissao
from src.hardware.impressora_termica import ErroImpressao
from src.ui.contexto import Contexto
from src.ui_qt.visualizador import JanelaVisualizador
from tests.base import BaseTeste


class TestVisualizadorQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.ctx.impressao = SimpleNamespace(
            modo=Mock(return_value="termica"),
            enviar=Mock(return_value="historico_simulado.txt"))
        self.janela = JanelaVisualizador(
            self.ctx, "Relatório", "AÇÃO\nTOTAL 10,53\n", modulo="rel_caixa",
            nome="caixa", tipo="relatorio")
        self.addCleanup(self.fechar)

    def fechar(self):
        self.janela.close()
        self.janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def confirmar(self, resposta=QMessageBox.StandardButton.Yes, **kwargs):
        return patch("src.ui_qt.visualizador.QMessageBox.question",
                     return_value=resposta, **kwargs)

    def preservar(self):
        self.assertEqual(self.janela.caixa.toPlainText(), "AÇÃO\nTOTAL 10,53\n")
        self.assertEqual(self.janela.texto, "AÇÃO\nTOTAL 10,53\n")

    def test_abertura_somente_leitura_sem_impressao(self):
        self.preservar()
        self.assertTrue(self.janela.caixa.isReadOnly())
        self.assertEqual(self.janela.caixa.lineWrapMode(), QPlainTextEdit.LineWrapMode.NoWrap)
        self.ctx.impressao.enviar.assert_not_called()

    def test_salvar_utf8_conteudo_original_e_cancelar(self):
        abrir = mock_open()
        with patch("src.ui_qt.visualizador.QFileDialog.getSaveFileName",
                   return_value=("simulado.txt", "")), patch(
                       "src.ui_qt.visualizador.Path.open", abrir):
            self.janela.salvar_botao.click()
        abrir.assert_called_once_with("w", encoding="utf-8", newline="")
        abrir().write.assert_called_once_with(self.janela.texto)
        self.assertEqual(self.janela.mensagem.text(), "Texto salvo.")
        with patch("src.ui_qt.visualizador.QFileDialog.getSaveFileName",
                   return_value=("", "")), patch(
                       "src.ui_qt.visualizador.Path.open") as abrir:
            self.assertFalse(self.janela.salvar())
            abrir.assert_not_called()
        self.assertEqual(self.janela.mensagem.text(), "")
        self.ctx.impressao.enviar.assert_not_called()

    def test_erro_de_escrita_preserva_documento(self):
        with patch("src.ui_qt.visualizador.Path.open", side_effect=OSError("Sem espaço")):
            self.assertFalse(self.janela.salvar("simulado.txt"))
        self.assertIn("Não foi possível salvar: Sem espaço", self.janela.mensagem.text())
        self.preservar()

    def test_impressao_explicita_confirma_e_repassa_contrato(self):
        with self.confirmar() as confirmar:
            self.assertTrue(self.janela.imprimir())
        self.assertEqual(confirmar.call_args.args[-1], QMessageBox.StandardButton.No)
        self.ctx.impressao.enviar.assert_called_once_with(
            self.janela.texto, "caixa", tipo="relatorio")
        self.assertEqual(self.janela.mensagem.text(), "Enviado para a fila da impressora térmica.")
        self.preservar()

    def test_cancelar_impressao_nao_envia_e_limpa_sucesso_anterior(self):
        self.janela.mensagem.setText("Enviado anteriormente")
        with self.confirmar(QMessageBox.StandardButton.No):
            self.assertFalse(self.janela.imprimir())
        self.ctx.impressao.enviar.assert_not_called()
        self.assertEqual(self.janela.mensagem.text(), "")

    def test_windows_nao_envia_duas_vezes_e_tela_usa_arquivo(self):
        for modo in ("windows", "tela", "arquivo"):
            with self.subTest(modo=modo):
                self.ctx.impressao.modo.return_value = modo
                self.ctx.impressao.enviar.reset_mock()
                with self.confirmar(), patch(
                        "src.ui_qt.visualizador.os.startfile", create=True) as imprimir:
                    self.assertTrue(self.janela.imprimir())
                self.ctx.impressao.enviar.assert_called_once()
                if modo == "windows":
                    imprimir.assert_not_called()
                else:
                    imprimir.assert_called_once_with("historico_simulado.txt", "print")

    def test_falhas_de_impressao_preservam_texto_sem_anunciar_sucesso(self):
        for erro in (ErroImpressao("Sem impressora"), OSError("Spooler indisponível")):
            with self.subTest(erro=erro), self.confirmar():
                self.ctx.impressao.enviar.side_effect = erro
                self.assertFalse(self.janela.imprimir())
                self.assertIn(f"Não foi possível imprimir: {erro}", self.janela.mensagem.text())
                self.preservar()

    def test_falha_no_comando_print_preserva_documento(self):
        self.ctx.impressao.modo.return_value = "tela"
        with self.confirmar(), patch("src.ui_qt.visualizador.os.startfile",
                                    create=True, side_effect=OSError("Sem associação")):
            self.assertFalse(self.janela.imprimir())
        self.assertIn("Não foi possível imprimir: Sem associação", self.janela.mensagem.text())
        self.preservar()

    def test_sem_comando_do_windows_nao_anuncia_impressao(self):
        self.ctx.impressao.modo.return_value = "tela"
        with self.confirmar(), patch("src.ui_qt.visualizador.os", spec=[]):
            self.assertFalse(self.janela.imprimir())
        self.assertIn("Não foi possível imprimir neste sistema", self.janela.mensagem.text())
        self.assertIn("historico_simulado.txt", self.janela.mensagem.text())

    def test_acesso_e_sessao_revalidados_antes_de_qualquer_saida(self):
        for estado in ("sem_sessao", "inativo", "removido", "nivel", "modulo", "outra_sessao"):
            with self.subTest(estado=estado):
                self.banco.executar("UPDATE operadores SET ativo = 1, nivel = 3 WHERE nome = 'ADM'")
                self.ctx.acesso.alterar_nivel_modulo("rel_caixa", 1)
                self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
                if estado == "sem_sessao":
                    self.ctx.operador = None
                elif estado == "inativo":
                    self.banco.executar("UPDATE operadores SET ativo = 0 WHERE nome = 'ADM'")
                elif estado == "nivel":
                    self.banco.executar("UPDATE operadores SET nivel = 0 WHERE nome = 'ADM'")
                elif estado == "modulo":
                    self.ctx.acesso.alterar_nivel_modulo("rel_caixa", 4)
                elif estado == "outra_sessao":
                    outro = self.banco.inserir(
                        "operadores", {"nome": "OUTRO", "senha": "", "nivel": 4})
                    self.ctx.operador = self.ctx.acesso.operador(outro)
                with self.confirmar() as confirmar, patch(
                        "src.ui_qt.visualizador.Path.open") as abrir, patch.object(
                            self.ctx.cadastros, "obter",
                            wraps=self.ctx.cadastros.obter) as obter:
                    if estado == "removido":
                        obter.side_effect = lambda *_: None
                    self.assertFalse(self.janela.salvar("simulado.txt"))
                    self.assertFalse(self.janela.imprimir())
                    abrir.assert_not_called()
                    confirmar.assert_not_called()
                self.ctx.impressao.enviar.assert_not_called()
                self.preservar()

    def test_revalida_apos_confirmacao_e_dialogo_de_arquivo(self):
        def revogar(*_):
            self.banco.executar("UPDATE operadores SET ativo = 0 WHERE nome = 'ADM'")
            return QMessageBox.StandardButton.Yes

        with self.confirmar(side_effect=revogar):
            self.assertFalse(self.janela.imprimir())
        self.ctx.impressao.enviar.assert_not_called()
        self.banco.executar("UPDATE operadores SET ativo = 1 WHERE nome = 'ADM'")

        def trocar_sessao(*_):
            self.ctx.operador = None
            return "simulado.txt", ""

        with patch("src.ui_qt.visualizador.QFileDialog.getSaveFileName",
                   side_effect=trocar_sessao), patch(
                       "src.ui_qt.visualizador.Path.open") as abrir:
            self.assertFalse(self.janela.salvar())
            abrir.assert_not_called()
        self.preservar()

    def test_abertura_sem_modulo_ou_acesso_nao_permitida(self):
        with self.assertRaises(ErroPermissao):
            JanelaVisualizador(self.ctx, "Título", "Texto", modulo="")
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            JanelaVisualizador(self.ctx, "Título", "Texto", modulo="rel_caixa")
