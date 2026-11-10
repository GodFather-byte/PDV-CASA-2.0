"""Telas dos vários caixas: Caixas da loja (principal), ligação na tela de entrada e a abertura do caixa adicional."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from src.controllers.contexto import Contexto
from src.core.erros import ErroPermissao
from src.database import rede
from src.database.conexao import BancoDados
from src.ui_qt.app import SO_NO_PRINCIPAL, App, JanelaPrincipal, preparar_inicio
from src.ui_qt.login import JanelaLogin
from src.ui_qt.rede_caixas import JanelaCaixasDaLoja, ligar_este_computador, perguntar_sem_ligacao


class BaseQtRede(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.caminho = os.path.join(self.pasta.name, "loja.db")
        self.banco = BancoDados(self.caminho)
        self.addCleanup(self.banco.fechar)
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.autenticar("ADM", "ADM")
        self.banco.cfg_set("rede_caixas_porta", str(self._porta_livre()))
        self.servico = rede.ServicoRedeCaixas(self.caminho)
        self.addCleanup(self.servico.parar)
        self.janelas = []
        self.addCleanup(self._fechar_janelas)

    @staticmethod
    def _porta_livre():
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _fechar_janelas(self):
        for janela in reversed(self.janelas):
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self, janela):
        self.janelas.append(janela)
        return janela

    def ligar_servico(self):
        self.banco.cfg_set("rede_caixas", "S")
        self.servico.iniciar()
        self.assertTrue(self.servico.ativo)
        return rede.url("127.0.0.1", rede.porta_da_loja(self.banco))

    def adicional(self, terminal=2):
        url = self.ligar_servico()
        rede.registrar_ligacao(url, rede.chave_da_loja(self.banco), terminal, f"pc-{terminal}")
        self.addCleanup(rede.esquecer_ligacao, url)
        banco = BancoDados(url, semear=False)
        self.addCleanup(banco.fechar)
        return banco


class TesteCaixasDaLoja(BaseQtRede):
    def test_ligar_mostra_o_codigo_e_desligar_para_de_atender(self):
        tela = self.janela(JanelaCaixasDaLoja(self.ctx, self.servico))
        self.assertFalse(tela.atender.isChecked())
        self.assertEqual(tela.codigo.toPlainText(), "")
        tela.atender.setChecked(True)
        tela._alternar(True)
        self.assertTrue(self.servico.ativo)
        codigo = rede.ler_codigo(tela.codigo.toPlainText())
        self.assertEqual((codigo["porta"], codigo["chave"]),
                         (rede.porta_da_loja(self.banco), rede.chave_da_loja(self.banco)))
        self.assertIn("Atendendo na porta", tela.estado.text())
        tela._alternar(False)
        self.assertFalse(self.servico.ativo)
        self.assertFalse(self.banco.cfg_bool("rede_caixas"))

    def test_lista_quem_esta_ligado_e_libera_so_quem_saiu(self):
        outro = self.adicional(terminal=2)
        tela = self.janela(JanelaCaixasDaLoja(self.ctx, self.servico))
        self.assertEqual(tela.tabela.rowCount(), 1)
        self.assertEqual((tela.tabela.item(0, 0).text(), tela.tabela.item(0, 2).text()), ("Caixa 2", "Ligado agora"))
        tela.tabela.selectRow(0)
        tela._liberar()
        self.assertIn("está ligado agora", tela.estado.text())
        self.assertIn(2, rede.terminais_registrados(self.banco))
        outro.fechar()
        for _ in range(300):
            if not self.servico.conectados():
                break
            self.aplicacao.processEvents()
            import time
            time.sleep(0.01)
        tela.atualizar()
        self.assertEqual(tela.tabela.item(0, 2).text(), "Desligado")
        tela.tabela.selectRow(0)
        tela._liberar()
        self.assertEqual(rede.terminais_registrados(self.banco), {})
        self.assertEqual(tela.tabela.rowCount(), 0)

    def test_codigo_novo_tira_quem_tinha_o_antigo(self):
        url = self.ligar_servico()
        antiga = rede.chave_da_loja(self.banco)
        tela = self.janela(JanelaCaixasDaLoja(self.ctx, self.servico))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            tela._trocar_codigo()
        self.assertNotEqual(rede.chave_da_loja(self.banco), antiga)
        rede.registrar_ligacao(url, antiga, 2, "pc-2")
        self.addCleanup(rede.esquecer_ligacao, url)
        with self.assertRaises(rede.ErroLigacao):
            BancoDados(url, semear=False)

    def test_exige_permissao_de_maquinas(self):
        self.banco.executar("UPDATE operadores SET nivel = 1 WHERE id = ?", (self.ctx.operador_id,))
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        with self.assertRaises(ErroPermissao):
            JanelaCaixasDaLoja(self.ctx, self.servico)


class TesteLigarEsteComputador(BaseQtRede):
    def test_cola_o_codigo_confere_com_o_principal_e_grava(self):
        self.ligar_servico()
        codigo = rede.gerar_codigo(["127.0.0.1"], rede.porta_da_loja(self.banco), rede.chave_da_loja(self.banco))
        with tempfile.TemporaryDirectory() as local, patch.object(rede, "RAIZ", local), \
                patch.object(QInputDialog, "getMultiLineText", return_value=(codigo, True)), \
                patch.object(QInputDialog, "getInt", return_value=(4, True)), \
                patch.object(QMessageBox, "information") as aviso:
            self.assertTrue(ligar_este_computador(None, BancoDados(":memory:")))
            salva = rede.ligacao_salva()
        aviso.assert_called_once()
        self.assertEqual((salva["terminal"], salva["porta"]), (4, rede.porta_da_loja(self.banco)))
        self.assertEqual(rede.terminais_registrados(self.banco)[4]["instalacao"], salva["instalacao"])

    def test_codigo_que_nao_entra_nao_grava_nada(self):
        self.ligar_servico()
        errado = rede.gerar_codigo(["127.0.0.1"], rede.porta_da_loja(self.banco), rede.nova_chave())
        with tempfile.TemporaryDirectory() as local, patch.object(rede, "RAIZ", local), \
                patch.object(QInputDialog, "getMultiLineText", return_value=(errado, True)), \
                patch.object(QInputDialog, "getInt", return_value=(2, True)), \
                patch.object(QMessageBox, "warning") as aviso:
            self.assertFalse(ligar_este_computador(None, BancoDados(":memory:")))
            self.assertIsNone(rede.ligacao_salva())
        self.assertIn("código de ligação", aviso.call_args.args[2])

    def test_caixa_adicional_desliga_e_volta_ao_banco_proprio(self):
        remoto = self.adicional(terminal=2)
        codigo = rede.codigo_da_loja(self.banco)
        with tempfile.TemporaryDirectory() as local, patch.object(rede, "RAIZ", local), \
                patch.object(QMessageBox, "information"):
            rede.salvar_ligacao(codigo, 2)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
                self.assertFalse(ligar_este_computador(None, remoto))
            self.assertIsNotNone(rede.ligacao_salva())
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                self.assertTrue(ligar_este_computador(None, remoto))
            self.assertIsNone(rede.ligacao_salva())

    def test_tela_de_entrada_mostra_o_botao_certo(self):
        entrada = self.janela(JanelaLogin(self.ctx))
        self.assertEqual(entrada.btn_rede.text(), "Ligar a outro caixa da loja")
        remoto = self.adicional(terminal=7)
        entrada_adicional = self.janela(JanelaLogin(Contexto(remoto)))
        self.assertIn("Caixa 7", entrada_adicional.btn_rede.text())
        with patch("src.ui_qt.rede_caixas.ligar_este_computador", return_value=False) as ligar:
            entrada.btn_rede.click()
        ligar.assert_called_once()


class TesteAberturaDoCaixaAdicional(BaseQtRede):
    def test_so_a_impressora_roda_e_o_que_e_do_principal_fica_desligado(self):
        remoto = self.adicional(terminal=2)
        app = App(remoto, self.aplicacao)
        self.addCleanup(self.aplicacao.aboutToQuit.disconnect, app.finalizar)
        self.addCleanup(app.finalizar)
        with patch("src.ui_qt.app.ServicoFilaImpressao") as impressao, patch("src.ui_qt.app.ServicoPonte") as ponte, \
                patch("src.ui_qt.app.ServicoPorteiro") as porteiro, \
                patch("src.ui_qt.app.ServicoSincronizacao") as nuvem, \
                patch("src.ui_qt.app.rede.ServicoRedeCaixas") as atender, \
                patch("src.controllers.utilitario_controller.UtilitarioController.backup_automatico") as backup:
            app.iniciar()
            impressao.assert_called_once_with(remoto.caminho)
            for servico in (ponte, porteiro, nuvem, atender):
                servico.assert_not_called()
            app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
            app.principal = JanelaPrincipal(app)
            for chave in SO_NO_PRINCIPAL:
                self.assertFalse(app.principal.botoes[chave].isEnabled(), chave)
            self.assertTrue(app.principal.botoes["caixas_loja"].isEnabled())
            tela = app.principal.abrir_caixas_loja()
            self.assertIn("caixa 2", tela.explicacao.text())
            self.assertFalse(tela.atender.isEnabled())
            app.finalizar()
        backup.assert_not_called()

    def test_principal_sobe_o_atendimento_junto_com_os_servicos(self):
        self.banco.cfg_set("rede_caixas", "S")
        app = App(self.banco, self.aplicacao)
        self.addCleanup(self.aplicacao.aboutToQuit.disconnect, app.finalizar)
        self.addCleanup(app.finalizar)
        with patch("src.ui_qt.app.ServicoFilaImpressao"), patch("src.ui_qt.app.ServicoPonte"), \
                patch("src.ui_qt.app.ServicoPorteiro"), patch("src.ui_qt.app.ServicoSincronizacao"), \
                patch("src.controllers.utilitario_controller.UtilitarioController.backup_automatico"), \
                patch("src.controllers.utilitario_controller.UtilitarioController.idade_backup_horas", return_value=1):
            app.iniciar()
            self.assertIsNotNone(app.rede_caixas)
            self.assertTrue(app.rede_caixas.ativo)
            app.finalizar()
        self.assertFalse(app.rede_caixas.ativo)

    def test_bootstrap_do_adicional_nao_confere_arquivo_local(self):
        with patch("src.ui_qt.app.caminho_padrao", return_value="pdv://192.168.0.10:47811"), \
                patch("src.core.instancia.InstanciaUnica") as trava, \
                patch("src.ui_qt.app.registro.configurar_logs"), \
                patch("src.database.protecao.preparar_banco") as preparar:
            trava.return_value.adquirir.return_value = True
            self.assertIs(preparar_inicio(), trava.return_value)
        preparar.assert_not_called()
        trava.assert_called_once_with(rede.arquivo_ligacao())

    def test_sem_ligacao_na_abertura_pergunta_o_que_fazer(self):
        def clicar(rotulo):                      # pelo texto: a ordem dos botões muda conforme o sistema
            def exec_(caixa):
                caixa._escolhido = next(b for b in caixa.buttons() if b.text().replace("&", "") == rotulo)
                return 0
            return exec_
        for rotulo, confirma, esperado in (
                ("Tentar de novo", None, "tentar"), ("Fechar", None, "fechar"),
                ("Usar o banco deste computador", QMessageBox.StandardButton.Yes, "desligar"),
                ("Usar o banco deste computador", QMessageBox.StandardButton.No, "tentar")):
            with patch.object(QMessageBox, "exec", clicar(rotulo)), \
                    patch.object(QMessageBox, "clickedButton", lambda caixa: caixa._escolhido), \
                    patch.object(QMessageBox, "question", return_value=confirma):
                self.assertEqual(perguntar_sem_ligacao(None, rede.ErroLigacao("Sem ligação")), esperado, rotulo)


if __name__ == "__main__":
    unittest.main()
