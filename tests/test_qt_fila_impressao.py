"""Fila Qt: controladores e impressão sempre mockados, sem trabalhos reais."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.fila_impressao import JanelaFilaImpressao


def registro(item_id, status="pendente", **campos):
    dados = dict(
        id=item_id, criado_em="2026-10-17 10:20:30", destino="caixa",
        nome=f"cupom_{item_id}", status=status, tentativas=2,
        proxima_tentativa="2026-10-17 10:21:00", ultimo_erro=None,
    )
    dados.update(campos)
    return dados


class TestFilaImpressaoQt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.fila = Mock(spec=[
            "listar", "reenviar", "reenviar_todos", "cancelar",
            "limpar_antigos", "texto_indicador",
            "conferir_interrompido",
        ])
        self.fila.listar.return_value = [
            registro(4, "pendente"), registro(3, "erro", destino="remota"),
            registro(2, "enviado"), registro(1, "cancelado"),
        ]
        self.fila.texto_indicador.return_value = ("Impressora: 1 com erro (reenviar)", "erro")
        self.fila.reenviar_todos.return_value = 2
        self.fila.limpar_antigos.return_value = 2
        self.fila.reenviar.return_value = None
        self.fila.cancelar.return_value = None
        self.impressao = Mock(spec=["fila", "imprimir_teste"])
        self.impressao.fila = self.fila
        self.ctx = SimpleNamespace(
            operador_id=7, operador=object(), acesso=Mock(), cadastros=Mock(),
            impressao=self.impressao,
        )
        self.ctx.cadastros.obter.return_value = {"ativo": 1}
        self.janelas = []
        self.addCleanup(self._fechar)
        for nome, valor in (
            ("warning", None), ("information", None),
            ("question", QMessageBox.StandardButton.Yes),
        ):
            remendo = patch.object(QMessageBox, nome, return_value=valor)
            setattr(self, nome, remendo.start())
            self.addCleanup(remendo.stop)

    def _fechar(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        janela = JanelaFilaImpressao(self.ctx)
        self.janelas.append(janela)
        return janela

    def test_lista_status_dados_indicador_e_nenhum_envio_ao_abrir(self):
        janela = self.janela()
        self.fila.listar.assert_called_once_with(300)
        self.fila.texto_indicador.assert_called_once_with()
        self.assertEqual(janela.grade.rowCount(), 4)
        self.assertEqual(janela.grade.item(0, 1).text(), "17/10/2026 10:20:30")
        self.assertEqual(janela.grade.item(1, 2).text(), "Cozinha/bar")
        self.assertEqual(
            [janela.grade.item(i, 4).text() for i in range(4)],
            ["Aguardando", "Erro", "Enviado (sem confirmação física)", "Cancelado"],
        )
        self.assertEqual(janela.grade.item(0, 5).text(), "2")
        self.assertEqual(janela.grade.item(0, 6).text(), "10:21:00")
        self.assertEqual(janela.grade.item(1, 6).text(), "")
        self.assertIn("ERRO", janela.indicador.text())
        self.assertIsNone(janela._id_selecionado())
        self.impressao.imprimir_teste.assert_not_called()
        self.fila.reenviar.assert_not_called()
        self.fila.reenviar_todos.assert_not_called()
        self.fila.cancelar.assert_not_called()
        self.fila.limpar_antigos.assert_not_called()
        self.ctx.acesso.exigir.assert_called_with(
            self.ctx.acesso.operador.return_value, "util_fila_impressao")

    def test_interrompido_requer_decisao_humana_sem_reenvio_comum(self):
        self.fila.listar.return_value = [registro(5, "incerto")]
        janela = self.janela()
        janela.grade.selectRow(0)
        self.assertIn("conferir", janela.grade.item(0, 4).text().lower())
        self.question.return_value = QMessageBox.StandardButton.No
        janela.conferir(False)
        self.fila.conferir_interrompido.assert_not_called()
        self.question.return_value = QMessageBox.StandardButton.Yes
        janela.conferir(True)
        self.fila.conferir_interrompido.assert_called_once_with(5, impresso=True, operador_id=7)
        self.fila.reenviar.assert_not_called()

    def test_revogacao_durante_conferencia_impede_reenvio_interrompido(self):
        self.fila.listar.return_value = [registro(5, "incerto")]
        janela = self.janela()
        janela.grade.selectRow(0)
        def revogar(*args):
            self.ctx.acesso.exigir.side_effect = ErroPermissao("Revogado")
            return QMessageBox.StandardButton.Yes
        self.question.side_effect = revogar
        janela.conferir(False)
        self.fila.conferir_interrompido.assert_not_called()

    def test_atualizar_preserva_id_nao_indice_e_remove_selecao_obsoleta(self):
        janela = self.janela()
        janela.grade.selectRow(1)
        self.fila.listar.return_value = [registro(3, "erro"), registro(4)]
        janela.btn_atualizar.click()
        self.assertEqual(janela._id_selecionado(), 3)
        self.assertEqual(janela.grade.currentRow(), 0)
        self.fila.listar.return_value = [registro(4)]
        janela.atualizar()
        self.assertIsNone(janela._id_selecionado())
        janela.reenviar()
        self.fila.reenviar.assert_not_called()

    def test_lista_vazia_status_desconhecido_e_falha_de_consulta(self):
        janela = self.janela()
        self.fila.listar.return_value = [registro(9, "novo", destino="outro", ultimo_erro="Falhou")]
        janela.atualizar()
        self.assertEqual(janela.grade.item(0, 4).text(), "novo")
        self.assertEqual(janela.grade.item(0, 2).text(), "outro")
        self.assertEqual(janela.grade.item(0, 7).text(), "Falhou")
        self.fila.listar.return_value = []
        janela.atualizar()
        self.assertEqual(janela.grade.rowCount(), 0)
        self.fila.listar.side_effect = OSError("Banco indisponível")
        self.assertFalse(janela.atualizar())
        self.assertEqual(janela.indicador.text(), "")
        self.assertIn("Banco indisponível", janela.mensagem.text())

    def test_selecao_obrigatoria_para_reenviar_e_cancelar(self):
        janela = self.janela()
        janela.reenviar()
        janela.cancelar()
        self.assertEqual(self.warning.call_count, 2)
        self.question.assert_not_called()
        self.fila.reenviar.assert_not_called()
        self.fila.cancelar.assert_not_called()

    def test_reenvio_individual_e_em_lote_usam_apenas_controlador(self):
        janela = self.janela()
        janela.grade.selectRow(1)
        janela.btn_reenviar.click()
        self.fila.reenviar.assert_called_once_with(3)
        janela.btn_reenviar_todos.click()
        self.fila.reenviar_todos.assert_called_once_with()
        self.assertIn("não confirma", self.information.call_args.args[2])
        self.impressao.imprimir_teste.assert_not_called()
        self.assertEqual(self.fila.listar.call_count, 3)

    def test_erro_controlador_nao_afirma_saida_fisica(self):
        janela = self.janela()
        janela.grade.selectRow(2)
        self.fila.reenviar.side_effect = ErroNegocio("Este item já foi impresso.")
        janela.reenviar()
        self.assertIn("não está disponível", self.warning.call_args.args[2])
        self.assertNotIn("já foi impresso", self.warning.call_args.args[2])
        self.information.assert_not_called()

    def test_cancelar_e_limpar_exigem_confirmacao_com_padrao_nao(self):
        janela = self.janela()
        janela.grade.selectRow(0)
        self.question.return_value = QMessageBox.StandardButton.No
        janela.cancelar()
        janela.limpar()
        self.fila.cancelar.assert_not_called()
        self.fila.limpar_antigos.assert_not_called()
        self.question.return_value = QMessageBox.StandardButton.Yes
        janela.btn_cancelar.click()
        janela.btn_limpar.click()
        self.fila.cancelar.assert_called_once_with(4)
        self.fila.limpar_antigos.assert_called_once_with(0)
        for chamada in self.question.call_args_list:
            self.assertEqual(chamada.args[4], QMessageBox.StandardButton.No)
        self.assertIn("Pendentes e erros serão preservados", self.question.call_args.args[2])

    def test_acesso_inicial_negado_nao_consulta_fila(self):
        for cadastro in (None, {"ativo": 0}):
            with self.subTest(cadastro=cadastro):
                self.ctx.cadastros.obter.return_value = cadastro
                with self.assertRaises(ErroPermissao):
                    self.janela()
        self.fila.listar.assert_not_called()

    def test_autorizacao_usa_operador_atual_nao_retrato_da_sessao(self):
        janela = self.janela()
        self.ctx.acesso.operador.reset_mock()
        operador_atual = object()
        self.ctx.acesso.operador.return_value = operador_atual
        janela.atualizar()
        self.ctx.cadastros.obter.assert_called_with("operadores", 7)
        self.ctx.acesso.operador.assert_called_once_with(7)
        self.ctx.acesso.exigir.assert_called_with(operador_atual, "util_fila_impressao")

    def test_falhas_em_acoes_nao_exibem_sucesso_nem_recarregam_lista(self):
        janela = self.janela()
        janela.grade.selectRow(0)
        for acao, controlador in (
            ("cancelar", self.fila.cancelar),
            ("limpar", self.fila.limpar_antigos),
            ("reenviar_todos", self.fila.reenviar_todos),
        ):
            with self.subTest(acao=acao):
                controlador.side_effect = ErroNegocio("Registro alterado")
                self.fila.listar.reset_mock()
                self.information.reset_mock()
                getattr(janela, acao)()
                self.assertIn("Registro alterado", self.warning.call_args.args[2])
                self.information.assert_not_called()
                self.fila.listar.assert_not_called()

    def test_sessao_permissao_e_atividade_revalidadas_em_todas_acoes(self):
        for revogacao in ("sessao", "inativo", "removido", "permissao"):
            for acao in ("atualizar", "reenviar", "reenviar_todos", "cancelar", "limpar", "teste"):
                with self.subTest(revogacao=revogacao, acao=acao):
                    self.ctx.operador_id = 7
                    self.ctx.cadastros.obter.return_value = {"ativo": 1}
                    self.ctx.acesso.exigir.side_effect = None
                    janela = self.janela()
                    janela.grade.selectRow(0)
                    self.fila.reset_mock()
                    if revogacao == "sessao":
                        self.ctx.operador_id = None
                    elif revogacao in ("inativo", "removido"):
                        self.ctx.cadastros.obter.return_value = (
                            {"ativo": 0} if revogacao == "inativo" else None)
                    else:
                        self.ctx.acesso.exigir.side_effect = ErroPermissao("Acesso revogado")
                    getattr(janela, acao)()
                    self.assertEqual(self.fila.mock_calls, [])
                    self.impressao.imprimir_teste.assert_not_called()
                    self.assertEqual(janela.grade.rowCount(), 0)
                    self.assertEqual(janela.indicador.text(), "")

    def test_revogacao_durante_confirmacao_impede_mutacao_ou_teste(self):
        janela = self.janela()
        for acao in ("cancelar", "limpar", "teste"):
            with self.subTest(acao=acao):
                self.ctx.operador_id = 7
                janela.atualizar()
                janela.grade.selectRow(0)
                self.fila.reset_mock()

                def confirmar(*args):
                    self.ctx.operador_id = None
                    return QMessageBox.StandardButton.Yes

                self.question.side_effect = confirmar
                getattr(janela, acao)()
                self.assertEqual(self.fila.mock_calls, [])
                self.impressao.imprimir_teste.assert_not_called()

    def test_pagina_teste_so_por_pedido_confirmado_e_impressao_mockada(self):
        janela = self.janela()
        self.question.return_value = QMessageBox.StandardButton.No
        janela.teste()
        self.impressao.imprimir_teste.assert_not_called()
        self.question.return_value = QMessageBox.StandardButton.Yes
        janela.btn_teste.click()
        self.impressao.imprimir_teste.assert_called_once_with()
        self.assertIn("não confirma", self.information.call_args.args[2])
        self.impressao.imprimir_teste.side_effect = OSError("Sem conexão")
        self.information.reset_mock()
        janela.teste()
        self.assertIn("não foi confirmado", self.warning.call_args.args[2])
        self.information.assert_not_called()

    def test_sem_timer_nem_consultas_apos_fechar(self):
        janela = self.janela()
        self.assertEqual(janela.findChildren(QTimer), [])
        self.fila.reset_mock()
        janela.close()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(self.fila.mock_calls, [])
        self.impressao.imprimir_teste.assert_not_called()


if __name__ == "__main__":
    unittest.main()
