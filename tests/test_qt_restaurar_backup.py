"""Preparação Qt com banco e cópias isolados dentro da pasta de testes."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from contextlib import closing
import shutil
import sqlite3
from unittest.mock import patch
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from src.controllers.utilitario_controller import UtilitarioController
from src.core.erros import ErroNegocio, ErroPermissao
from src.database import protecao
from src.database.conexao import BancoDados
from src.ui.contexto import Contexto
from src.ui_qt.restaurar_backup import JanelaRestaurarBackup
from tests.base import BaseTeste


class TestRestaurarBackupQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.pasta = Path(__file__).parent / f".qt-restaurar-{uuid4().hex}"
        self.pasta.mkdir()
        self.addCleanup(shutil.rmtree, self.pasta)
        arquivo = self.pasta / "isolado.db"
        self.banco.copiar_para(str(arquivo))
        self.banco = BancoDados(str(arquivo))
        self.addCleanup(self.banco.fechar)
        self.backups = self.pasta / "backups"
        self.backups.mkdir()
        self.banco.cfg_set("pasta_backup", str(self.backups))
        self.banco.cfg_set("pasta_backup_extra", "")
        self.banco.cfg_set("backup_externo_pasta", "")
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.janelas = []
        self.addCleanup(self._fechar_janelas)

    def _fechar_janelas(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        janela = JanelaRestaurarBackup(self.ctx)
        self.janelas.append(janela)
        return janela

    def copia(self, nome="loja_offline-2026-01-01-120000.db"):
        caminho = self.backups / nome
        self.banco.copiar_para(str(caminho))
        return caminho

    def marca(self):
        return Path(self.banco.caminho + "." + protecao.PENDENTE)

    def test_sem_backups_e_sem_selecao_nao_prepara(self):
        janela = self.janela()
        status = janela.status.text()
        with patch.object(UtilitarioController, "pedir_restauracao") as pedir, \
             patch.object(QMessageBox, "question") as confirmar:
            self.assertFalse(janela.preparar())
        pedir.assert_not_called()
        confirmar.assert_not_called()
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertFalse(janela.btn_preparar.isEnabled())
        self.assertIn("Não há backups", janela.resumo.text())
        self.assertEqual(janela.status.text(), status)
        self.assertFalse(self.marca().exists())

    def test_lista_apenas_validos_mais_recentes_com_limite_e_caminho(self):
        caminhos = [
            self.backups / f"loja_offline-2026-01-{i:03d}-120000.db"
            for i in range(65)
        ]
        with patch.object(UtilitarioController, "listar_backups",
                          return_value=list(reversed(caminhos))), \
             patch.object(protecao, "backup_valido", return_value=True):
            janela = self.janela()
        self.assertEqual(janela.grade.rowCount(), 60)
        self.assertIn("064", janela.grade.item(0, 0).text())
        self.assertIn("005", janela.grade.item(59, 0).text())
        self.assertEqual(janela.grade.item(0, 1).text(), str(self.backups))
        self.assertFalse(janela.btn_preparar.isEnabled())

    def test_descarta_corrompido_outro_sqlite_e_banco_aberto(self):
        valido = self.copia()
        (self.backups / "loja_offline-ruim.db").write_bytes(b"danificado")
        outro = self.backups / "loja_offline-outro.db"
        with closing(sqlite3.connect(outro)) as con:
            con.execute("CREATE TABLE alheia (id INTEGER)")
            con.commit()
        janela = self.janela()
        self.assertEqual(janela.grade.rowCount(), 1)
        self.assertIn("2026-01-01", janela.grade.item(0, 0).text())
        with patch.object(UtilitarioController, "listar_backups",
                          return_value=[Path(self.banco.caminho), valido]):
            self.assertTrue(janela.carregar())
        self.assertEqual(janela.grade.rowCount(), 1)

    def test_cancelamento_preserva_status_selecao_e_pedido_anterior(self):
        self.copia()
        janela = self.janela()
        janela.grade.selectRow(0)
        self.assertTrue(janela.btn_preparar.isEnabled())
        janela.status.setText("Preparação anterior.")
        self.marca().write_text("pedido anterior", encoding="utf-8")
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No), \
             patch.object(UtilitarioController, "pedir_restauracao") as pedir:
            self.assertFalse(janela.preparar())
        pedir.assert_not_called()
        self.assertEqual(janela.status.text(), "Preparação anterior.")
        self.assertEqual(janela.grade.currentRow(), 0)
        self.assertEqual(self.marca().read_text(encoding="utf-8"), "pedido anterior")

    def test_prepara_pela_api_sem_restaurar_banco_aberto(self):
        produto = self.novo_produto("ANTES", 123)
        copia = self.copia()
        self.banco.executar("UPDATE produtos SET nome = 'AGORA' WHERE id = ?", (produto,))
        janela = self.janela()
        janela.grade.selectRow(0)
        conexao = self.banco.conexao
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes) as confirmar, \
             patch.object(protecao, "restaurar") as restaurar, \
             patch.object(protecao, "aplicar_restauracao_pendente") as aplicar:
            self.assertTrue(janela.preparar())
        restaurar.assert_not_called()
        aplicar.assert_not_called()
        self.assertIs(self.banco.conexao, conexao)
        self.assertEqual(self.banco.valor("SELECT nome FROM produtos WHERE id = ?", (produto,)), "AGORA")
        self.assertEqual(self.marca().read_text(encoding="utf-8"), str(copia.resolve()))
        self.assertIn("FECHE", janela.status.text())
        texto = confirmar.call_args.args[2]
        for consequencia in ("perdido", "cópia do estado de agora", "aberto de novo", str(copia)):
            self.assertIn(consequencia, texto)
        self.assertEqual(confirmar.call_args.args[-1], QMessageBox.StandardButton.No)
        seguranca = self.backups / "loja_offline-2026-10-03-210000.db"
        self.assertTrue(protecao.backup_valido(seguranca))
        with closing(sqlite3.connect(seguranca)) as con:
            self.assertEqual(con.execute("SELECT nome FROM produtos WHERE id = ?", (produto,)).fetchone()[0], "AGORA")

    def test_escolha_envia_caminho_exato_ao_controller_atual(self):
        mais_antigo = self.copia()
        self.copia("loja_offline-2026-02-01-120000.db")
        janela = self.janela()
        janela.grade.selectRow(1)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(UtilitarioController, "pedir_restauracao") as pedir:
            self.assertTrue(janela.preparar())
        pedir.assert_called_once_with(str(mais_antigo))
        status = janela.status.text()
        self.assertTrue(janela.carregar())
        self.assertEqual(janela.status.text(), status)

    def test_erros_preservam_status_e_nao_anunciam_sucesso(self):
        self.copia()
        janela = self.janela()
        janela.grade.selectRow(0)
        status = janela.status.text()
        for erro in (ErroNegocio("backup inválido"), OSError("sem acesso"), sqlite3.OperationalError("ocupado")):
            with self.subTest(erro=erro), \
                 patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                 patch.object(UtilitarioController, "pedir_restauracao", side_effect=erro):
                self.assertFalse(janela.preparar())
                self.assertEqual(janela.status.text(), status)
                self.assertEqual(janela.grade.currentRow(), 0)
                self.assertIn(str(erro), janela.mensagem.text())
        with patch.object(UtilitarioController, "listar_backups", side_effect=OSError("leitura falhou")):
            self.assertFalse(janela.carregar())
        self.assertEqual(janela.grade.rowCount(), 1)
        self.assertEqual(janela.status.text(), status)
        self.assertFalse(self.marca().exists())

    def test_backup_removido_depois_da_escolha_nao_marca(self):
        copia = self.copia()
        janela = self.janela()
        janela.grade.selectRow(0)
        copia.unlink()
        status = janela.status.text()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertFalse(janela.preparar())
        self.assertEqual(janela.status.text(), status)
        self.assertFalse(self.marca().exists())

    def test_exige_login_operador_ativo_e_util_backup(self):
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            self.janela()
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.operador_adm(),))
        with self.assertRaises(ErroPermissao):
            self.janela()
        self.banco.executar("UPDATE operadores SET ativo = 1, nivel = 1 WHERE id = ?", (self.operador_adm(),))
        self.banco.executar("UPDATE acessos SET nivel = 4 WHERE modulo = 'util_backup'")
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_revalida_permissao_apos_confirmacao(self):
        self.copia()
        janela = self.janela()
        janela.grade.selectRow(0)
        status = janela.status.text()

        def confirmar(*_args):
            self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.operador_adm(),))
            return QMessageBox.StandardButton.Yes

        with patch.object(QMessageBox, "question", side_effect=confirmar), \
             patch.object(UtilitarioController, "pedir_restauracao") as pedir:
            self.assertFalse(janela.preparar())
        pedir.assert_not_called()
        self.assertEqual(janela.status.text(), status)
        self.assertIn("inativo", janela.mensagem.text())

    def test_recusa_banco_em_memoria_sem_criar_marca(self):
        with patch.object(self.banco, "caminho", ":memory:"):
            with self.assertRaises(ErroNegocio):
                self.janela()
