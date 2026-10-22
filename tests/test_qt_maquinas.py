"""Máquinas Qt com SQLite em memória e saídas físicas sempre simuladas."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from src.controllers.config_controller import CAMPOS_MAQUINA
from src.core.erros import ErroNegocio, ErroPermissao
from src.controllers.contexto import Contexto
from src.ui_qt.maquinas import JanelaMaquinas
from tests.base import BaseTeste


class TestMaquinasQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.janelas = []
        self.addCleanup(self._fechar)
        for atributo, metodo in (("imprimir", "imprimir_teste"), ("gaveta", "abrir_gaveta")):
            simulacao = patch.object(self.ctx.impressao, metodo)
            setattr(self, atributo, simulacao.start())
            self.addCleanup(simulacao.stop)

    def _fechar(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        janela = JanelaMaquinas(self.ctx)
        self.janelas.append(janela)
        return janela

    def revogar(self):
        self.banco.executar("UPDATE operadores SET nivel = 0 WHERE id = ?",
                            (self.ctx.operador_id,))

    def test_campos_reais_carregam_sem_hardware_ou_gravacao(self):
        self.ctx.config.salvar_maquina({
            "descricao": "Balcão", "balanca": "Toledo", "gaveta": "S",
            "impressora_remota_conexao": "rede",
            "impressora_remota_endereco": "192.0.2.1:9100",
        })
        antes = self.ctx.config.maquina()
        with patch.object(self.ctx.config, "salvar_maquina") as salvar:
            janela = self.janela()
            self.assertEqual(set(janela.campos), {c[0] for c in CAMPOS_MAQUINA})
            self.assertEqual(janela.campos["descricao"].text(), "Balcão")
            self.assertEqual(janela.campos["balanca"].currentData(), "Toledo")
            self.assertTrue(janela.campos["gaveta"].isChecked())
            self.assertTrue(janela.campos["terminal"].isReadOnly())
            self.assertTrue(janela.salvar())
            salvar.assert_not_called()
        self.assertEqual(antes, self.ctx.config.maquina())
        self.imprimir.assert_not_called()
        self.gaveta.assert_not_called()

    def test_salva_so_alterados_pelo_controller_preservando_externo(self):
        janela = self.janela()
        self.ctx.config.salvar_maquina({"descricao": "Externo"})
        janela.campos["colunas_fita"].setText("48")
        janela.campos["impressora_remota_conexao"].setCurrentIndex(
            janela.campos["impressora_remota_conexao"].findData("rede"))
        janela.campos["impressora_remota_endereco"].setText(" 192.0.2.2:9100 ")
        janela.campos["balanca"].setCurrentIndex(janela.campos["balanca"].findData("Filizola"))
        janela.campos["balanca_porta"].setText("COM7")
        janela.campos["gaveta"].setChecked(True)
        with patch.object(self.ctx.config, "salvar_maquina",
                          wraps=self.ctx.config.salvar_maquina) as salvar:
            self.assertTrue(janela.salvar())
            self.assertEqual(salvar.call_count, 1)
            self.assertNotIn("terminal", salvar.call_args.args[0])
            self.assertNotIn("descricao", salvar.call_args.args[0])
        dados = self.ctx.config.maquina()
        self.assertEqual(dados["descricao"], "Externo")
        self.assertEqual(dados["colunas_fita"], 48)
        self.assertEqual(dados["impressora_remota_endereco"], "192.0.2.2:9100")
        self.assertEqual(dados["balanca"], "Filizola")
        self.assertEqual(dados["balanca_porta"], "COM7")
        self.assertEqual(dados["gaveta"], 1)
        self.imprimir.assert_not_called()
        self.gaveta.assert_not_called()

    def test_validacao_real_de_colunas_pino_e_inteiro_sem_gravar(self):
        janela = self.janela()
        antes = self.ctx.config.maquina()
        for chave, valor in (("colunas_fita", "5"), ("impressora_termica_pino", "2"),
                              ("colunas_fita", "texto")):
            with self.subTest(chave=chave, valor=valor):
                janela.recarregar()
                janela.campos[chave].setText(valor)
                self.assertFalse(janela.salvar())
                self.assertEqual(antes, self.ctx.config.maquina())

    def test_opcao_desconhecida_nao_vira_padrao(self):
        self.ctx.config.salvar_maquina({"balanca": "Desconhecida"})
        janela = self.janela()
        self.assertEqual(janela.campos["balanca"].currentIndex(), -1)
        self.assertFalse(janela.salvar())
        self.assertEqual(self.ctx.config.maquina()["balanca"], "Desconhecida")

    def test_descartar_e_fechar_nao_gravam(self):
        janela = self.janela()
        antes = self.ctx.config.maquina()
        janela.campos["descricao"].setText("Não salvar")
        self.assertTrue(janela.recarregar())
        self.assertEqual(janela.campos["descricao"].text(), antes["descricao"] or "")
        janela.campos["descricao"].setText("Também não salvar")
        janela.reject()
        self.assertEqual(antes, self.ctx.config.maquina())

    def test_testes_cancelados_nao_salvam_nem_acionam(self):
        janela = self.janela()
        antes = self.ctx.config.maquina()
        janela.campos["descricao"].setText("Pendente")
        with patch("src.ui_qt.maquinas.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.No) as confirmar:
            self.assertFalse(janela.testar_impressao())
            self.assertFalse(janela.testar_gaveta())
            self.assertEqual(confirmar.call_count, 2)
        self.assertEqual(antes, self.ctx.config.maquina())
        self.assertEqual(janela.campos["descricao"].text(), "Pendente")
        self.imprimir.assert_not_called()
        self.gaveta.assert_not_called()

    def test_testes_explicitos_confirmados_salvam_antes_de_enviar(self):
        janela = self.janela()
        janela.campos["descricao"].setText("Confirmada")
        self.imprimir.side_effect = lambda: self.assertEqual(
            self.ctx.config.maquina()["descricao"], "Confirmada")
        with patch("src.ui_qt.maquinas.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes) as confirmar:
            self.assertTrue(janela.testar_impressao())
            self.imprimir.assert_called_once_with()
            self.gaveta.assert_not_called()
            self.assertIn("física", confirmar.call_args.args[2])
            self.assertEqual(confirmar.call_args.args[4], QMessageBox.StandardButton.No)
            self.assertTrue(janela.testar_gaveta())
            self.assertIn("fisicamente", confirmar.call_args.args[2])
        self.gaveta.assert_called_once_with()

    def test_validacao_e_falha_hardware_sao_exibidas(self):
        janela = self.janela()
        with patch("src.ui_qt.maquinas.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes):
            janela.campos["colunas_fita"].setText("0")
            self.assertFalse(janela.testar_impressao())
            self.imprimir.assert_not_called()
            janela.recarregar()
            self.imprimir.side_effect = OSError("Equipamento indisponível")
            self.assertFalse(janela.testar_impressao())
            self.assertIn("indisponível", janela.mensagem.text())
            self.gaveta.side_effect = ErroNegocio("Sem gaveta")
            self.assertFalse(janela.testar_gaveta())
            self.assertIn("Sem gaveta", janela.mensagem.text())

    def test_acesso_revogado_antes_das_acoes_limpa_tela_e_nao_confirma(self):
        janela = self.janela()
        antes = self.ctx.config.maquina()
        self.revogar()
        with patch("src.ui_qt.maquinas.QMessageBox.question") as confirmar:
            for acao in (janela.salvar, janela.recarregar,
                         janela.testar_impressao, janela.testar_gaveta):
                self.assertFalse(acao())
            confirmar.assert_not_called()
        self.assertFalse(janela.btn_salvar.isEnabled())
        self.assertEqual(janela.campos["descricao"].text(), "")
        self.assertEqual(antes, self.ctx.config.maquina())
        self.imprimir.assert_not_called()
        self.gaveta.assert_not_called()

    def test_revogacao_durante_confirmacao_impede_salvar_e_hardware(self):
        for gaveta in (False, True):
            with self.subTest(gaveta=gaveta):
                self.banco.executar("UPDATE operadores SET nivel = 4 WHERE id = ?",
                                    (self.ctx.operador_id,))
                janela = self.janela()
                antes = self.ctx.config.maquina()
                janela.campos["descricao"].setText("Não salvar")
                def confirmar(*args):
                    self.revogar()
                    return QMessageBox.StandardButton.Yes
                with patch("src.ui_qt.maquinas.QMessageBox.question", side_effect=confirmar):
                    self.assertFalse(janela._testar(gaveta))
                self.assertEqual(antes, self.ctx.config.maquina())
                self.assertFalse(janela.btn_teste.isEnabled())
        self.imprimir.assert_not_called()
        self.gaveta.assert_not_called()

    def test_inativo_sem_sessao_e_nivel_insuficiente_nao_abrem(self):
        self.revogar()
        with self.assertRaises(ErroPermissao):
            self.janela()
        self.banco.executar("UPDATE operadores SET nivel = 4, ativo = 0")
        with self.assertRaises(ErroPermissao):
            self.janela()
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_exibir_revalida_operador_ativo(self):
        janela = self.janela()
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?",
                            (self.ctx.operador_id,))
        janela.show()
        self.aplicacao.processEvents()
        self.assertFalse(janela.btn_salvar.isEnabled())
        self.assertIn("inativo", janela.mensagem.text())

    def test_contrato_publico_revalida_sem_descartar_edicao(self):
        janela = self.janela()
        janela.campos["descricao"].setText("Edição pendente")
        self.assertEqual(janela.exigir_acesso(), self.ctx.operador_id)
        self.assertEqual(janela.campos["descricao"].text(), "Edição pendente")
        self.revogar()
        with self.assertRaises(ErroPermissao):
            janela.exigir_acesso()
        self.assertEqual(janela.campos["descricao"].text(), "")
        self.banco.executar("UPDATE operadores SET nivel = 4")
        janela.exigir_acesso()
        self.assertTrue(janela.btn_salvar.isEnabled())

    def test_revogacao_apos_salvar_impede_envio(self):
        janela = self.janela()
        janela.campos["descricao"].setText("Configuração permitida")
        salvar = self.ctx.config.salvar_maquina
        def salvar_e_revogar(dados):
            salvar(dados)
            self.revogar()
        with patch("src.ui_qt.maquinas.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes), \
                patch.object(self.ctx.config, "salvar_maquina", side_effect=salvar_e_revogar):
            self.assertFalse(janela.testar_impressao())
        self.imprimir.assert_not_called()
        self.gaveta.assert_not_called()
        self.assertFalse(janela.btn_teste.isEnabled())

    def test_sessao_encerrada_durante_dialogo_mesmo_cancelado_limpa_tela(self):
        janela = self.janela()
        antes = self.ctx.config.maquina()
        def confirmar(*args):
            self.ctx.operador = None
            return QMessageBox.StandardButton.No
        with patch("src.ui_qt.maquinas.QMessageBox.question", side_effect=confirmar):
            self.assertFalse(janela.testar_gaveta())
        self.assertEqual(antes, self.ctx.config.maquina())
        self.assertFalse(janela.btn_gaveta.isEnabled())
        self.gaveta.assert_not_called()

    def test_troca_de_operador_durante_dialogo_exige_nova_confirmacao(self):
        janela = self.janela()
        outro = self.ctx.cadastros.salvar("operadores", {
            "nome": "SUPERVISOR", "senha": "segredo1", "nivel": "4", "ativo": "S",
        })
        def confirmar(*args):
            self.ctx.operador = self.ctx.acesso.operador(outro)
            return QMessageBox.StandardButton.Yes
        with patch("src.ui_qt.maquinas.QMessageBox.question", side_effect=confirmar), \
                patch.object(self.ctx.config, "salvar_maquina") as salvar:
            self.assertFalse(janela.testar_impressao())
            salvar.assert_not_called()
        self.imprimir.assert_not_called()
        self.assertIn("sessão mudou", janela.mensagem.text())
