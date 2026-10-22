"""Fluxos Qt do assistente de impressora; nenhum teste envia trabalho real."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from src.controllers import impressao_assistente as assistente
from src.core.erros import ErroPermissao
from src.hardware.impressoras_so import ImpressoraWindows
from src.controllers.contexto import Contexto
from src.ui_qt.assistente_impressora import JanelaAssistenteImpressora
from tests.base import BaseTeste


ELGIN = ImpressoraWindows("Elgin i9", "USB001", "Elgin i9 Series", termica_provavel=True)
PDF = ImpressoraWindows("Microsoft Print to PDF", "PORTPROMPT:", "Microsoft Print To PDF", virtual=True)


class TestAssistenteImpressoraQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.janelas = []
        self.addCleanup(self._fechar_janelas)
        self.listagem = patch(
            "src.ui_qt.assistente_impressora.impressoras_so.listar_impressoras",
            return_value=[PDF, ELGIN],
        )
        self.listagem.start()
        self.addCleanup(self.listagem.stop)
        self.diagnostico = patch(
            "src.ui_qt.assistente_impressora.assistente.diagnosticar",
            return_value=[assistente.Achado("aviso", "Fila requer atenção.", "Confira no Windows.")],
        )
        self.diagnostico.start()
        self.addCleanup(self.diagnostico.stop)

    def _fechar_janelas(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        janela = JanelaAssistenteImpressora(self.ctx)
        self.janelas.append(janela)
        return janela

    def selecionar(self, janela, nome):
        indice = next(i for i, imp in enumerate(janela.impressoras) if imp.nome == nome)
        janela.grade.selectRow(indice)

    def test_lista_achados_e_sugestao_de_impressora_termica(self):
        janela = self.janela()
        self.assertEqual(janela.grade.rowCount(), 2)
        self.assertEqual(janela._nome_selecionado(), "Elgin i9")
        self.assertIn("ATENÇÃO: Fila requer atenção.", janela.achados.toPlainText())
        self.assertIn("Como resolver: Confira no Windows.", janela.achados.toPlainText())
        self.assertFalse(janela.btn_instalar.isEnabled())
        self.assertFalse(janela.btn_fila.isEnabled())

    def test_configura_e_envia_teste_com_permissao_revalidada(self):
        janela = self.janela()
        with patch.object(self.ctx.impressao, "impressora_de", return_value=object()) as criar, \
             patch.object(self.ctx.impressao, "imprimir_teste") as imprimir, \
             patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QMessageBox, "information"):
            janela.configurar_e_testar()

        maquina = self.ctx.config.maquina()
        self.assertEqual(maquina["impressora_termica_endereco"], "Elgin i9")
        self.assertEqual(maquina["impressora_termica_conexao"], "spooler")
        criar.assert_called_once_with("spooler", "Elgin i9")
        imprimir.assert_called_once()
        self.assertEqual(imprimir.call_args.args[0], criar.return_value)

    def test_permissao_revalidada_antes_de_configurar(self):
        janela = self.janela()
        with patch.object(self.ctx.acesso, "exigir", side_effect=ErroPermissao("Sem acesso.")), \
             patch.object(assistente, "configurar") as configurar, \
             patch.object(self.ctx.impressao, "imprimir_teste") as imprimir, \
             patch.object(QMessageBox, "warning"):
            janela.configurar_e_testar()
        configurar.assert_not_called()
        imprimir.assert_not_called()

    def test_permissao_revalidada_novamente_antes_do_teste(self):
        janela = self.janela()
        with patch.object(self.ctx.acesso, "exigir",
                          side_effect=[None, ErroPermissao("A permissão foi retirada.")]), \
             patch.object(self.ctx.impressao, "imprimir_teste") as imprimir, \
             patch.object(QMessageBox, "warning"):
            janela.configurar_e_testar()
        self.assertEqual(self.ctx.config.maquina()["impressora_termica_endereco"], "Elgin i9")
        imprimir.assert_not_called()

    def test_impressora_virtual_exige_confirmacao_previa(self):
        janela = self.janela()
        self.selecionar(janela, PDF.nome)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as confirmar, \
             patch.object(assistente, "configurar") as configurar, \
             patch.object(self.ctx.impressao, "imprimir_teste") as imprimir:
            janela.configurar_e_testar()
        confirmar.assert_called_once()
        configurar.assert_not_called()
        imprimir.assert_not_called()

    def test_erro_de_impressao_nao_afirma_que_trabalho_foi_enviado(self):
        janela = self.janela()
        with patch.object(self.ctx.impressao, "impressora_de", return_value=object()), \
             patch.object(self.ctx.impressao, "imprimir_teste", side_effect=OSError("spooler indisponível")), \
             patch.object(QMessageBox, "warning") as aviso, \
             patch.object(QMessageBox, "question") as confirmar:
            janela.configurar_e_testar()
        aviso.assert_called_once()
        self.assertIn("não foi confirmado", aviso.call_args.args[2])
        confirmar.assert_not_called()

    def test_atualizar_preserva_escolha_e_copiar_usa_relatorio(self):
        janela = self.janela()
        self.selecionar(janela, PDF.nome)
        self.listagem.return_value = [ELGIN, PDF]
        janela.atualizar()
        self.assertEqual(janela._nome_selecionado(), PDF.nome)

        with patch.object(assistente, "relatorio", return_value="DIAGNÓSTICO MOCKADO") as relatorio, \
             patch.object(QMessageBox, "information"):
            janela.copiar_diagnostico()
        relatorio.assert_called_once()
        self.assertEqual(QApplication.clipboard().text(), "DIAGNÓSTICO MOCKADO")

    def test_configuracoes_windows_usam_inicio_existente_sem_abrir_no_teste(self):
        janela = self.janela()
        with patch("src.ui_qt.assistente_impressora.sys.platform", "win32"), \
             patch("src.ui_qt.assistente_impressora.os.startfile", create=True) as abrir:
            janela.abrir_configuracoes_windows()
        abrir.assert_called_once_with("ms-settings:printers")
