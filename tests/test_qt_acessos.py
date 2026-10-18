"""Níveis de módulos Qt com controlador real e SQLite isolado."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from src.core.erros import ErroPermissao
from src.ui.contexto import Contexto
from src.ui_qt.acessos import JanelaAcessos
from tests.base import BaseTeste


class TestAcessosQt(BaseTeste):
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

    def _fechar(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        janela = JanelaAcessos(self.ctx)
        self.janelas.append(janela)
        return janela

    def selecionar(self, janela, modulo, nivel):
        for linha in range(janela.grade.rowCount()):
            if janela.grade.item(linha, 1).data(Qt.ItemDataRole.UserRole) == modulo:
                janela.grade.selectRow(linha)
                janela.nivel.setCurrentIndex(janela.nivel.findData(nivel))
                return
        self.fail(f"Módulo não encontrado: {modulo}")

    def revogar(self):
        self.banco.executar("UPDATE operadores SET nivel = 0 WHERE id = ?",
                            (self.ctx.operador_id,))

    def test_lista_apenas_modulos_reais_sem_alterar_banco(self):
        antes = self.ctx.acesso.modulos()
        with patch.object(self.ctx.acesso, "alterar_nivel_modulo") as alterar:
            janela = self.janela()
            self.assertEqual(janela.grade.rowCount(), len(antes))
            for linha, modulo in enumerate(antes):
                self.assertEqual(janela.grade.item(linha, 0).text(), modulo["grupo"])
                self.assertEqual(janela.grade.item(linha, 1).text(), modulo["descricao"])
                self.assertEqual(janela.grade.item(linha, 2).text(), str(modulo["nivel"]))
            self.assertEqual([janela.nivel.itemData(i) for i in range(4)], [1, 2, 3, 4])
            self.assertTrue(janela.salvar())
            alterar.assert_not_called()
        self.assertEqual(antes, self.ctx.acesso.modulos())

    def test_salva_unico_modulo_pela_api_sem_tocar_operadores_ou_config(self):
        janela = self.janela()
        antes = {m["modulo"]: m["nivel"] for m in self.ctx.acesso.modulos()}
        operadores = [tuple(r) for r in self.banco.todos("SELECT * FROM operadores")]
        config = [tuple(r) for r in self.banco.todos("SELECT * FROM config")]
        novo = 1 if antes["cfg_maquinas"] != 1 else 2
        self.selecionar(janela, "cfg_maquinas", novo)
        with patch("src.ui_qt.acessos.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes), \
                patch.object(self.ctx.acesso, "alterar_nivel_modulo",
                             wraps=self.ctx.acesso.alterar_nivel_modulo) as alterar:
            self.assertTrue(janela.salvar())
            alterar.assert_called_once_with("cfg_maquinas", novo)
        antes["cfg_maquinas"] = novo
        self.assertEqual(antes, {m["modulo"]: m["nivel"] for m in self.ctx.acesso.modulos()})
        self.assertEqual(operadores, [tuple(r) for r in self.banco.todos("SELECT * FROM operadores")])
        self.assertEqual(config, [tuple(r) for r in self.banco.todos("SELECT * FROM config")])

    def test_cancelar_descartar_e_fechar_nao_gravam(self):
        janela = self.janela()
        antes = self.ctx.acesso.modulos()
        nivel = self.ctx.acesso.nivel_modulo("cfg_maquinas")
        self.selecionar(janela, "cfg_maquinas", 1 if nivel != 1 else 2)
        with patch("src.ui_qt.acessos.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.No) as confirmar:
            self.assertFalse(janela.salvar())
            self.assertEqual(confirmar.call_args.args[4], QMessageBox.StandardButton.No)
        self.assertTrue(janela.recarregar())
        self.assertEqual(janela.nivel.currentData(), nivel)
        janela.nivel.setCurrentIndex(-1)
        janela.reject()
        self.assertEqual(antes, self.ctx.acesso.modulos())

    def test_nivel_invalido_e_sem_selecao_nao_abrem_confirmacao(self):
        janela = self.janela()
        antes = self.ctx.acesso.modulos()
        with patch("src.ui_qt.acessos.QMessageBox.question") as confirmar:
            for valor in (0, 5, "2", None):
                janela.nivel.addItem("Inválido", valor)
                janela.nivel.setCurrentIndex(janela.nivel.count() - 1)
                self.assertFalse(janela.salvar())
            janela.grade.clearSelection()
            self.assertFalse(janela.salvar())
            confirmar.assert_not_called()
        self.assertEqual(antes, self.ctx.acesso.modulos())

    def test_revogacao_antes_da_acao_limpa_dados(self):
        janela = self.janela()
        antes = self.ctx.acesso.modulos()
        self.revogar()
        with patch("src.ui_qt.acessos.QMessageBox.question") as confirmar:
            self.assertFalse(janela.salvar())
            self.assertFalse(janela.recarregar())
            confirmar.assert_not_called()
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertFalse(janela.btn_salvar.isEnabled())
        self.assertEqual(antes, self.ctx.acesso.modulos())

    def test_revogacao_durante_dialogo_impede_gravacao(self):
        janela = self.janela()
        antes = self.ctx.acesso.modulos()
        self.selecionar(janela, "cfg_maquinas", 1)
        def confirmar(*args):
            self.revogar()
            return QMessageBox.StandardButton.Yes
        with patch("src.ui_qt.acessos.QMessageBox.question", side_effect=confirmar), \
                patch.object(self.ctx.acesso, "alterar_nivel_modulo") as alterar:
            self.assertFalse(janela.salvar())
            alterar.assert_not_called()
        self.assertEqual(antes, self.ctx.acesso.modulos())
        self.assertFalse(janela.nivel.isEnabled())

    def test_inativacao_durante_dialogo_impede_gravacao(self):
        janela = self.janela()
        self.selecionar(janela, "cfg_maquinas", 1)
        def confirmar(*args):
            self.banco.executar("UPDATE operadores SET ativo = 0")
            return QMessageBox.StandardButton.Yes
        with patch("src.ui_qt.acessos.QMessageBox.question", side_effect=confirmar), \
                patch.object(self.ctx.acesso, "alterar_nivel_modulo") as alterar:
            self.assertFalse(janela.salvar())
            alterar.assert_not_called()
        self.assertIn("inativo", janela.mensagem.text())

    def test_mudar_proprio_acesso_bloqueia_tela_apos_salvar(self):
        self.ctx.acesso.alterar_nivel_modulo("cfg_acessos", 2)
        self.banco.executar("UPDATE operadores SET nivel = 2 WHERE id = ?",
                            (self.ctx.operador_id,))
        janela = self.janela()
        self.selecionar(janela, "cfg_acessos", 4)
        with patch("src.ui_qt.acessos.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(janela.salvar())
        self.assertEqual(self.ctx.acesso.nivel_modulo("cfg_acessos"), 4)
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertFalse(janela.btn_salvar.isEnabled())
        self.assertIn("salvo", janela.mensagem.text())
        self.assertFalse(janela.salvar())
        self.assertFalse(janela.recarregar())

    def test_nivel_atual_do_banco_e_nao_da_sessao_autoriza(self):
        janela = self.janela()
        self.assertEqual(self.ctx.operador.nivel, 4)
        self.banco.executar("UPDATE operadores SET nivel = 1 WHERE id = ?",
                            (self.ctx.operador_id,))
        self.assertFalse(janela.recarregar())
        self.assertEqual(janela.grade.rowCount(), 0)

    def test_sem_sessao_inativo_ou_sem_nivel_nao_abrem(self):
        self.revogar()
        with self.assertRaises(ErroPermissao):
            self.janela()
        self.banco.executar("UPDATE operadores SET nivel = 4, ativo = 0")
        with self.assertRaises(ErroPermissao):
            self.janela()
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_exibir_revalida_permissao(self):
        janela = self.janela()
        self.revogar()
        janela.show()
        self.aplicacao.processEvents()
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertFalse(janela.btn_salvar.isEnabled())

    def test_contrato_publico_preserva_edicao_e_revalida_sessao(self):
        janela = self.janela()
        self.selecionar(janela, "cfg_maquinas", 1)
        self.assertEqual(janela.exigir_acesso(), self.ctx.operador_id)
        self.assertEqual(janela._modulo(), "cfg_maquinas")
        self.assertEqual(janela.nivel.currentData(), 1)
        self.revogar()
        with self.assertRaises(ErroPermissao):
            janela.exigir_acesso()
        self.assertEqual(janela.grade.rowCount(), 0)
        self.banco.executar("UPDATE operadores SET nivel = 4")
        janela.exigir_acesso()
        self.assertGreater(janela.grade.rowCount(), 0)
        self.assertTrue(janela.btn_salvar.isEnabled())

    def test_sessao_encerrada_no_cancelamento_limpa_tela(self):
        janela = self.janela()
        antes = self.ctx.acesso.modulos()
        self.selecionar(janela, "cfg_maquinas", 1)
        def confirmar(*args):
            self.ctx.operador = None
            return QMessageBox.StandardButton.No
        with patch("src.ui_qt.acessos.QMessageBox.question", side_effect=confirmar):
            self.assertFalse(janela.salvar())
        self.assertEqual(antes, self.ctx.acesso.modulos())
        self.assertEqual(janela.grade.rowCount(), 0)

    def test_troca_de_operador_durante_dialogo_nao_grava(self):
        janela = self.janela()
        antes = self.ctx.acesso.modulos()
        outro = self.ctx.cadastros.salvar("operadores", {
            "nome": "SUPERVISOR", "senha": "segredo1", "nivel": "4", "ativo": "S",
        })
        self.selecionar(janela, "cfg_maquinas", 1)
        def confirmar(*args):
            self.ctx.operador = self.ctx.acesso.operador(outro)
            return QMessageBox.StandardButton.Yes
        with patch("src.ui_qt.acessos.QMessageBox.question", side_effect=confirmar):
            self.assertFalse(janela.salvar())
        self.assertEqual(antes, self.ctx.acesso.modulos())
        self.assertIn("sessão mudou", janela.mensagem.text())
