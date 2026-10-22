"""Painel Qt da cozinha usa banco em memória, sem impressão nem rede reais."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from src.core.erros import ErroPermissao
from src.ui.contexto import Contexto
from src.ui_qt.cozinha import JanelaCozinha
from tests.test_caixa import BaseCaixa


class TestCozinhaQt(BaseCaixa):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.adm)
        self.banco.cfg_set("usar_cozinha_bar", "S")
        self.banco.executar("UPDATE subgrupos SET impressora_remota = 1")
        self.banco.executar("UPDATE produtos SET aceita_decimal = 1 WHERE id = ?", (self.skol,))
        self.janelas = []
        self.addCleanup(self._fechar)

    def _fechar(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        janela = JanelaCozinha(self.ctx)
        self.janelas.append(janela)
        return janela

    def item(self):
        venda = self.caixa.abrir_balcao()
        return self.caixa.adicionar_item(venda, self.skol, 1.25)

    def test_lista_avanca_e_registra_operador_sem_impressao(self):
        item = self.item()
        with patch.object(self.ctx.impressao, "enviar") as enviar:
            janela = self.janela()
            self.assertEqual(janela.grade.rowCount(), 1)
            self.assertEqual(janela.grade.item(0, 0).text(), "Balcão")
            self.assertEqual(janela.grade.item(0, 5).text(), "Pendente")
            janela.grade.selectRow(0)
            self.assertTrue(janela.avancar())
            self.assertEqual(janela.selecionado(), item)
            self.assertEqual(janela.grade.item(0, 5).text(), "Em preparo")
            self.assertTrue(janela.marcar("entregue"))
            self.assertEqual(janela.grade.rowCount(), 0)
            enviar.assert_not_called()
        linha = self.banco.um(
            "SELECT status_preparo, preparo_operador_id, preparo_atualizado_em FROM itens_venda WHERE id = ?", (item,))
        self.assertEqual(linha["status_preparo"], "entregue")
        self.assertEqual(linha["preparo_operador_id"], self.adm)
        self.assertTrue(linha["preparo_atualizado_em"])

    def test_filtra_setor_e_rele_cadastro_de_setores(self):
        self.item()
        cozinha = self.banco.inserir(
            "setores_impressao", {"nome": "Cozinha", "conexao": "pasta", "ativo": 1, "ordem": 0})
        bar = self.banco.inserir(
            "setores_impressao", {"nome": "Bar", "conexao": "pasta", "ativo": 1, "ordem": 1})
        self.banco.executar("UPDATE subgrupos SET setor_impressao_id = ?", (cozinha,))
        janela = self.janela()
        janela.setor.setCurrentIndex(janela.setor.findData(bar))
        self.assertEqual(janela.grade.rowCount(), 0)
        janela.setor.setCurrentIndex(janela.setor.findData(cozinha))
        self.assertEqual(janela.grade.rowCount(), 1)
        self.banco.executar("UPDATE setores_impressao SET ativo = 0 WHERE id = ?", (cozinha,))
        self.assertTrue(janela.atualizar())
        self.assertEqual(janela.setor.findData(cozinha), -1)
        self.assertIsNone(janela.setor.currentData())

    def test_modulo_desligado_bloqueia_abertura(self):
        self.banco.cfg_set("usar_cozinha_bar", "N")
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_revogacao_inativacao_e_sessao_encerrada_bloqueiam_acao(self):
        for alteracao in ("nivel", "ativo", "sessao", "modulo"):
            with self.subTest(alteracao=alteracao):
                self.banco.executar("UPDATE operadores SET nivel = 4, ativo = 1 WHERE id = ?", (self.adm,))
                self.ctx.operador = self.ctx.acesso.operador(self.adm)
                self.banco.cfg_set("usar_cozinha_bar", "S")
                item = self.item()
                janela = self.janela()
                janela.grade.selectRow(janela.grade.rowCount() - 1)
                if alteracao in ("nivel", "ativo"):
                    self.banco.executar(
                        f"UPDATE operadores SET {alteracao} = 0 WHERE id = ?", (self.adm,))
                elif alteracao == "sessao":
                    self.ctx.operador = None
                else:
                    self.banco.cfg_set("usar_cozinha_bar", "N")
                self.assertFalse(janela.marcar("entregue"))
                self.assertEqual(janela.grade.rowCount(), 0)
                self.assertFalse(janela.timer.isActive())
                self.assertEqual(self.banco.valor(
                    "SELECT status_preparo FROM itens_venda WHERE id = ?", (item,)), "pendente")

    def test_cancelado_entre_consulta_e_acao_nao_e_alterado(self):
        item = self.item()
        janela = self.janela()
        janela.grade.selectRow(0)
        self.caixa.cancelar_item(item, "teste")
        self.assertFalse(janela.avancar())
        self.assertIn("não está mais", janela.mensagem.text())
        self.assertEqual(self.banco.valor(
            "SELECT status_preparo FROM itens_venda WHERE id = ?", (item,)), "pendente")

    def test_timer_para_ao_fechar_e_esc(self):
        janela = self.janela()
        janela.show()
        self.aplicacao.processEvents()
        self.assertTrue(janela.timer.isActive())
        janela.reject()
        self.assertFalse(janela.timer.isActive())
        janela.show()
        self.aplicacao.processEvents()
        self.assertTrue(janela.timer.isActive())
        janela.close()
        self.assertFalse(janela.timer.isActive())

    def test_sem_selecao_nao_muda_preparo(self):
        item = self.item()
        janela = self.janela()
        self.assertFalse(janela.avancar())
        self.assertIn("Selecione", janela.mensagem.text())
        self.assertEqual(self.banco.valor(
            "SELECT status_preparo FROM itens_venda WHERE id = ?", (item,)), "pendente")
