"""Contas Qt com Contexto real e SQLite isolado em memória."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QAbstractItemView, QMessageBox

from src.controllers.contas_controller import ContasController
from src.core.erros import ErroNegocio, ErroPermissao
from src.controllers.contexto import Contexto
from src.ui_qt.contas import JanelaContas
from tests.base import BaseTeste


class TestContasQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.sub = self.banco.valor("SELECT id FROM subplanos WHERE nome = 'Aluguel'")
        self.janelas = []
        self.addCleanup(self._fechar)

    def _fechar(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        janela = JanelaContas(self.ctx)
        self.janelas.append(janela)
        return janela

    def conta(self, descricao="Aluguel", valor=12345, **campos):
        dados = dict(dt_entrada="01/10/2026", dt_vencimento="10/10/2026")
        dados.update(campos)
        return self.ctx.contas.incluir(self.sub, descricao, self.tipo(), valor, **dados)[0]

    def preencher(self, janela):
        janela.subplano.setCurrentIndex(janela.subplano.findData(self.sub))
        janela.tipo.setCurrentIndex(janela.tipo.findData(self.tipo()))
        janela.descricao.setText("Aluguel")
        janela.valor.setText("1.234,56")
        janela.entrada.setText("01/10/2026")
        janela.vencimento.setText("31/10/2026")

    def selecionar(self, janela, identificador):
        janela.grade.selectRow(next(
            i for i, conta in enumerate(janela.linhas) if conta["id"] == identificador))
        self.assertEqual(janela.id_atual, identificador)

    def confirmar(self):
        return patch("src.ui_qt.contas.QMessageBox.question",
                     return_value=QMessageBox.StandardButton.Yes)

    def test_vazia_campos_e_sem_selecao(self):
        janela = self.janela()
        self.assertEqual(janela.linhas, [])
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertIn("R$ 0,00", janela.resumo.text())
        self.assertIn("Nenhuma conta", janela.mensagem.text())
        self.assertEqual(janela.f_de.text(), "01/10/2026")
        self.assertEqual(janela.f_ate.text(), "01/11/2026")
        self.assertTrue(janela.quitacao.isReadOnly())
        self.assertEqual(janela.meses.minimum(), 1)
        self.assertEqual(janela.meses.maximum(), 120)
        self.assertEqual(janela.grade.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
        with patch("src.ui_qt.contas.QMessageBox.question") as confirmar:
            self.assertFalse(janela.quitar())
            self.assertFalse(janela.desquitar())
            self.assertFalse(janela.excluir())
            confirmar.assert_not_called()

    def test_incluir_centavos_campos_ids_e_operador(self):
        fornecedor = self.ctx.cadastros.salvar("fornecedores", {"nome": "FORNECEDOR"})
        janela = self.janela()
        self.preencher(janela)
        janela.fornecedor.setCurrentIndex(janela.fornecedor.findData(fornecedor))
        janela.documento.setText("DOC-1")
        janela.nota.setText("NF-2")
        janela.mercadoria.setChecked(True)
        janela.previsao.setChecked(True)
        with patch.object(ContasController, "incluir", autospec=True,
                          side_effect=ContasController.incluir) as incluir:
            janela.btn_gravar.click()
        incluir.assert_called_once()
        conta = self.ctx.contas.listar()[0]
        self.assertEqual(conta["valor_cent"], 123456)
        self.assertIsInstance(conta["valor_cent"], int)
        self.assertEqual(conta["subplano_id"], self.sub)
        self.assertEqual(conta["tipo_pagamento_id"], self.tipo())
        self.assertEqual(conta["fornecedor_id"], fornecedor)
        self.assertEqual((conta["documento"], conta["nota"]), ("DOC-1", "NF-2"))
        self.assertEqual((conta["mercadoria"], conta["previsao"]), (1, 1))
        self.assertEqual(conta["operador_id"], self.operador_adm())
        self.assertIsNone(conta["dt_quitacao"])
        self.assertEqual(janela.grade.item(0, 6).text(), "1.234,56")
        self.assertEqual(janela.grade.item(0, 8).text(), "Sim")
        self.assertIsNone(janela.id_atual)
        self.assertEqual(janela.descricao.text(), "")
        self.assertTrue(janela.meses.isEnabled())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 0)

    def test_mensal_repete_valor_inteiro_e_ajusta_fim_do_mes(self):
        janela = self.janela()
        self.preencher(janela)
        janela.entrada.setText("01/01/2026")
        janela.vencimento.setText("31/01/2026")
        janela.meses.setValue(3)
        self.assertTrue(janela.gravar())
        contas = self.ctx.contas.listar()
        self.assertEqual([c["valor_cent"] for c in contas], [123456] * 3)
        self.assertEqual([c["dt_vencimento"] for c in contas],
                         ["2026-01-31", "2026-02-28", "2026-03-31"])
        self.assertEqual([c["parcela"] for c in contas], ["1/3", "2/3", "3/3"])

    def test_editar_apenas_uma_parcela_e_cancelar_recupera_banco(self):
        ids = self.ctx.contas.incluir(
            self.sub, "Mensal", self.tipo(), 100, "10/10/2026", "01/10/2026", meses=2)
        janela = self.janela()
        self.selecionar(janela, ids[0])
        self.assertFalse(janela.meses.isEnabled())
        janela.descricao.setText("Descartada")
        janela.valor.setText("999,99")
        janela.btn_cancelar.click()
        self.assertEqual(janela.descricao.text(), "Mensal")
        self.assertEqual(janela.valor.text(), "1,00")
        janela.descricao.setText("Alterada")
        janela.valor.setText("0,01")
        janela.vencimento.setText("20/10/2026")
        with patch.object(ContasController, "atualizar", autospec=True,
                          side_effect=ContasController.atualizar) as atualizar:
            self.assertTrue(janela.gravar())
        atualizar.assert_called_once()
        self.assertEqual(self.ctx.contas.obter(ids[0])["descricao"], "Alterada")
        self.assertEqual(self.ctx.contas.obter(ids[0])["valor_cent"], 1)
        self.assertEqual(self.ctx.contas.obter(ids[0])["parcela"], "1/2")
        self.assertEqual(self.ctx.contas.obter(ids[1])["descricao"], "Mensal")
        self.assertEqual(self.ctx.contas.obter(ids[1])["valor_cent"], 100)

    def test_cancelar_inclusao_e_novo_nao_gravam(self):
        identificador = self.conta()
        janela = self.janela()
        self.selecionar(janela, identificador)
        janela.btn_novo.click()
        self.assertIsNone(janela.id_atual)
        self.preencher(janela)
        janela.btn_cancelar.click()
        self.assertEqual(janela.descricao.text(), "")
        self.assertEqual(len(self.ctx.contas.listar()), 1)
        self.assertFalse(janela.btn_excluir.isEnabled())
        self.assertFalse(janela.btn_quitar.isEnabled())

    def test_validacoes_inclusao_nao_gravam_e_preservam_formulario(self):
        janela = self.janela()
        for campo, valor, aviso in (
            ("subplano", None, "Escolha"),
            ("valor", "inválido", "monetário"),
            ("valor", "0", "maior que zero"),
            ("descricao", " ", "descrição"),
            ("vencimento", "31/02/2026", "Data inválida"),
        ):
            with self.subTest(campo=campo, valor=valor):
                self.preencher(janela)
                if campo == "subplano":
                    janela.subplano.setCurrentIndex(-1)
                else:
                    getattr(janela, campo).setText(valor)
                self.assertFalse(janela.gravar())
                self.assertIn(aviso, janela.mensagem.text())
                self.assertEqual(self.ctx.contas.listar(), [])

    def test_filtros_datas_inclusivas_criterios_situacao_e_previsao(self):
        antes = self.conta("Anterior", dt_vencimento="30/09/2026")
        aberto = self.conta("Aberto", dt_vencimento="01/10/2026", previsao=True)
        quitado = self.conta("Quitado", dt_vencimento="01/11/2026")
        self.ctx.contas.quitar(quitado, "03/10/2026")
        depois = self.conta("Posterior", dt_vencimento="02/11/2026")
        janela = self.janela()
        self.assertEqual([c["id"] for c in janela.linhas], [aberto, quitado])
        for situacao, esperado in ((False, [aberto]), (True, [quitado]), (None, [aberto, quitado])):
            janela.f_situacao.setCurrentIndex(janela.f_situacao.findData(situacao))
            self.assertTrue(janela.listar())
            self.assertEqual([c["id"] for c in janela.linhas], esperado)
        for previsao, esperado in ((True, [aberto]), (False, [quitado]), (None, [aberto, quitado])):
            janela.f_previsao.setCurrentIndex(janela.f_previsao.findData(previsao))
            janela.listar()
            self.assertEqual([c["id"] for c in janela.linhas], esperado)
        janela.f_por.setCurrentIndex(janela.f_por.findData("dt_entrada"))
        janela.listar()
        self.assertEqual([c["id"] for c in janela.linhas], [antes, aberto, quitado, depois])
        janela.f_por.setCurrentIndex(janela.f_por.findData("dt_quitacao"))
        janela.listar()
        self.assertEqual([c["id"] for c in janela.linhas], [quitado])
        janela.f_de.clear()
        janela.f_ate.clear()
        janela.f_por.setCurrentIndex(0)
        janela.listar()
        self.assertEqual(len(janela.linhas), 4)

    def test_busca_controller_documento_nota_descricao_e_sem_resultados(self):
        identificador = self.conta("Locação", documento="REC-42", nota="NOTA-99")
        self.conta("Outros")
        janela = self.janela()
        for busca in ("locacao", "REC-42", "NOTA-99"):
            janela.busca.setText(busca)
            janela.busca.returnPressed.emit()
            self.assertEqual([c["id"] for c in janela.linhas], [identificador])
        janela.busca.setText("' OR 1=1 --")
        janela.btn_listar.click()
        self.assertEqual(janela.linhas, [])
        self.assertIn("Nenhuma conta", janela.mensagem.text())

    def test_filtro_invalido_nao_chama_controller(self):
        janela = self.janela()
        with patch.object(ContasController, "listar") as listar:
            janela.f_de.setText("31/02/2026")
            self.assertFalse(janela.listar())
            self.assertIn("inválida", janela.mensagem.text())
            janela.f_de.setText("10/11/2026")
            janela.f_ate.setText("01/10/2026")
            self.assertFalse(janela.listar())
            self.assertIn("posterior", janela.mensagem.text())
            listar.assert_not_called()

    def test_saldo_creditos_menos_debitos_e_situacoes(self):
        self.conta("Débito", valor=201, dt_vencimento="01/10/2026")
        credito = self.banco.inserir("planos_contas", {
            "nome": "Crédito teste", "codigo": "9.99", "debito": 0,
        })
        sub = self.banco.inserir("subplanos", {"nome": "Crédito", "plano_id": credito})
        self.ctx.contas.incluir(sub, "Receber", self.tipo(), 1001,
                               "10/10/2026", "01/10/2026")
        janela = self.janela()
        self.assertIn("R$ 8,00", janela.resumo.text())
        self.assertEqual(janela.grade.item(0, 10).text(), "Vencida")
        self.assertEqual(janela.grade.item(1, 10).text(), "Em aberto")

    def test_quitar_controller_desfaz_previsao_e_desquitar_preserva_confirmada(self):
        identificador = self.conta(previsao=True)
        janela = self.janela()
        self.selecionar(janela, identificador)
        with patch("src.ui_qt.contas.QInputDialog.getText", return_value=("05/10/2026", True)), \
                self.confirmar(), patch.object(ContasController, "quitar", autospec=True,
                                               side_effect=ContasController.quitar) as quitar:
            janela.btn_quitar.click()
        quitar.assert_called_once()
        conta = self.ctx.contas.obter(identificador)
        self.assertEqual(conta["dt_quitacao"], "2026-10-05")
        self.assertEqual(conta["previsao"], 0)
        self.assertEqual(janela.quitacao.text(), "05/10/2026")
        self.assertFalse(janela.previsao.isChecked())
        self.assertEqual(janela.grade.item(0, 10).text(), "Quitada")
        self.assertTrue(janela.btn_desquitar.isEnabled())
        with self.confirmar(), patch.object(
                ContasController, "desfazer_quitacao", autospec=True,
                side_effect=ContasController.desfazer_quitacao) as desfazer:
            janela.btn_desquitar.click()
        desfazer.assert_called_once()
        conta = self.ctx.contas.obter(identificador)
        self.assertIsNone(conta["dt_quitacao"])
        self.assertEqual(conta["previsao"], 0)
        self.assertEqual(janela.quitacao.text(), "")
        self.assertFalse(janela.btn_desquitar.isEnabled())

    def test_quitacao_data_invalida_e_anterior_bloqueadas_pelo_controller(self):
        identificador = self.conta()
        janela = self.janela()
        self.selecionar(janela, identificador)
        for data in ("31/02/2026", "30/09/2026"):
            with self.subTest(data=data), \
                    patch("src.ui_qt.contas.QInputDialog.getText", return_value=(data, True)), \
                    self.confirmar():
                self.assertFalse(janela.quitar())
                self.assertIsNone(self.ctx.contas.obter(identificador)["dt_quitacao"])
                self.assertTrue(janela.mensagem.text())

    def test_cancelar_dialogos_nao_muda_dados_e_confirmacao_padrao_nao(self):
        identificador = self.conta(previsao=True)
        janela = self.janela()
        self.selecionar(janela, identificador)
        with patch("src.ui_qt.contas.QInputDialog.getText", return_value=("", False)), \
                patch("src.ui_qt.contas.QMessageBox.question") as perguntar:
            self.assertFalse(janela.quitar())
            perguntar.assert_not_called()
        with patch("src.ui_qt.contas.QInputDialog.getText", return_value=("03/10/2026", True)), \
                patch("src.ui_qt.contas.QMessageBox.question",
                      return_value=QMessageBox.StandardButton.No) as perguntar:
            for acao in (janela.quitar, janela.desquitar, janela.excluir):
                self.assertFalse(acao())
                self.assertEqual(perguntar.call_args.args[-1], QMessageBox.StandardButton.No)
        conta = self.ctx.contas.obter(identificador)
        self.assertIsNone(conta["dt_quitacao"])
        self.assertEqual(conta["previsao"], 1)

    def test_excluir_quitada_afeta_so_selecionada_como_controller_permite(self):
        identificador = self.conta()
        outra = self.conta("Outra")
        self.ctx.contas.quitar(identificador)
        janela = self.janela()
        self.selecionar(janela, identificador)
        with self.confirmar(), patch.object(ContasController, "excluir", autospec=True,
                                            side_effect=ContasController.excluir) as excluir:
            self.assertTrue(janela.excluir())
        excluir.assert_called_once()
        self.assertEqual([c["id"] for c in self.ctx.contas.listar()], [outra])
        self.assertIsNone(janela.id_atual)
        self.assertEqual(janela.descricao.text(), "")

    def test_edicao_quitada_nao_reabre_nem_muda_data(self):
        identificador = self.conta()
        self.ctx.contas.quitar(identificador, "03/10/2026")
        janela = self.janela()
        self.selecionar(janela, identificador)
        janela.descricao.setText("Conferida")
        self.assertTrue(janela.gravar())
        self.assertEqual(self.ctx.contas.obter(identificador)["dt_quitacao"], "2026-10-03")

    def test_edicao_nao_desfaz_quitacao_feita_depois_da_selecao(self):
        identificador = self.conta()
        janela = self.janela()
        self.selecionar(janela, identificador)
        self.ctx.contas.quitar(identificador, "03/10/2026")
        janela.descricao.setText("Conferida")
        self.assertTrue(janela.gravar())
        self.assertEqual(self.ctx.contas.obter(identificador)["dt_quitacao"], "2026-10-03")
        self.assertEqual(janela.quitacao.text(), "03/10/2026")

    def test_edicao_validacao_campos_obrigatorios_e_datas_vazias(self):
        identificador = self.conta()
        janela = self.janela()
        self.selecionar(janela, identificador)
        for campo, invalido in (("descricao", " "), ("valor", "-1"),
                                ("vencimento", "31/02/2026")):
            with self.subTest(campo=campo):
                janela.cancelar()
                getattr(janela, campo).setText(invalido)
                self.assertFalse(janela.gravar())
                self.assertEqual(self.ctx.contas.obter(identificador)["descricao"], "Aluguel")
                self.assertEqual(self.ctx.contas.obter(identificador)["valor_cent"], 12345)
        janela.cancelar()
        janela.entrada.clear()
        janela.vencimento.clear()
        self.assertTrue(janela.gravar())
        conta = self.ctx.contas.obter(identificador)
        self.assertEqual(conta["dt_entrada"], "2026-10-03")
        self.assertEqual(conta["dt_vencimento"], "2026-10-03")

    def test_filtro_retira_quitada_e_limpa_selecao(self):
        identificador = self.conta()
        janela = self.janela()
        janela.f_situacao.setCurrentIndex(janela.f_situacao.findData(False))
        janela.listar()
        self.selecionar(janela, identificador)
        with patch("src.ui_qt.contas.QInputDialog.getText", return_value=("", True)), \
                self.confirmar():
            self.assertTrue(janela.quitar())
        self.assertEqual(self.ctx.contas.obter(identificador)["dt_quitacao"], "2026-10-03")
        self.assertEqual(janela.linhas, [])
        self.assertIsNone(janela.id_atual)
        self.assertFalse(janela.btn_excluir.isEnabled())

    def test_cancelar_recupera_estado_atual_do_controller(self):
        identificador = self.conta(previsao=True)
        janela = self.janela()
        self.selecionar(janela, identificador)
        self.ctx.contas.quitar(identificador)
        janela.previsao.setChecked(True)
        janela.descricao.setText("Descartar")
        self.assertTrue(janela.cancelar())
        self.assertEqual(janela.quitacao.text(), "03/10/2026")
        self.assertFalse(janela.previsao.isChecked())
        self.assertEqual(janela.descricao.text(), "Aluguel")

    def test_selecao_desatualizada_e_operacao_com_conta_excluida(self):
        identificador = self.conta()
        janela = self.janela()
        self.ctx.contas.excluir(identificador)
        janela.grade.selectRow(0)
        self.assertIsNone(janela.id_atual)
        self.assertIn("não encontrada", janela.mensagem.text())
        identificador = self.conta()
        janela.listar()
        self.selecionar(janela, identificador)
        self.ctx.contas.excluir(identificador)
        with self.confirmar():
            self.assertFalse(janela.excluir())
        self.assertIn("não encontrada", janela.mensagem.text())

    def test_lookup_inativo_nao_perde_id_ao_editar(self):
        fornecedor = self.banco.inserir("fornecedores", {"nome": "Antigo", "ativo": 0})
        identificador = self.conta(fornecedor_id=fornecedor)
        self.banco.executar("UPDATE tipos_pagamento SET ativo = 0 WHERE id = ?", (self.tipo(),))
        janela = self.janela()
        self.selecionar(janela, identificador)
        self.assertEqual(janela.fornecedor.currentData(), fornecedor)
        self.assertEqual(janela.tipo.currentData(), self.tipo())
        self.assertTrue(janela.gravar())
        self.assertEqual(self.ctx.contas.obter(identificador)["fornecedor_id"], fornecedor)
        self.assertEqual(self.ctx.contas.obter(identificador)["tipo_pagamento_id"], self.tipo())

    def test_construcao_sem_operador_inativo_e_nivel_insuficiente(self):
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            self.janela()
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.operador_adm(),))
        with self.assertRaisesRegex(ErroPermissao, "inativo"):
            self.janela()
        self.banco.executar("UPDATE operadores SET ativo = 1, nivel = 1 WHERE id = ?",
                           (self.operador_adm(),))
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_acesso_revalidado_em_todas_as_acoes_sem_reabrir_janela(self):
        identificador = self.conta()
        janela = self.janela()
        self.banco.executar("UPDATE operadores SET nivel = 2 WHERE id = ?", (self.operador_adm(),))
        for nome in ("listar", "gravar", "quitar", "desquitar", "excluir", "cancelar", "novo", "selecionar"):
            with self.subTest(acao=nome):
                self.ctx.acesso.alterar_nivel_modulo("lanc_contas", 2)
                janela.listar()
                self.selecionar(janela, identificador)
                self.ctx.acesso.alterar_nivel_modulo("lanc_contas", 3)
                with patch("src.ui_qt.contas.QMessageBox.question") as perguntar, \
                        patch.object(ContasController, "incluir") as incluir, \
                        patch.object(ContasController, "atualizar") as atualizar:
                    self.assertFalse(getattr(janela, nome)())
                    perguntar.assert_not_called()
                    incluir.assert_not_called()
                    atualizar.assert_not_called()
                self.assertEqual(janela.linhas, [])
                self.assertEqual(janela.grade.rowCount(), 0)
                self.assertEqual(janela.descricao.text(), "")
                self.assertIsNone(janela.id_atual)
                self.assertIn("acesso", janela.mensagem.text())
                self.assertEqual(self.ctx.contas.obter(identificador)["descricao"], "Aluguel")

    def test_inativacao_e_logout_com_janela_aberta(self):
        self.conta()
        janela = self.janela()
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.operador_adm(),))
        self.assertFalse(janela.listar())
        self.assertIn("inativo", janela.mensagem.text())
        self.ctx.operador = None
        self.assertFalse(janela.gravar())
        self.assertIn("Entre", janela.mensagem.text())

    def test_revalida_acesso_apos_confirmacao_modal(self):
        identificador = self.conta()
        janela = self.janela()
        self.selecionar(janela, identificador)

        def revogar(*_):
            self.banco.executar("UPDATE operadores SET nivel = 1 WHERE id = ?",
                               (self.operador_adm(),))
            return QMessageBox.StandardButton.Yes

        with patch("src.ui_qt.contas.QMessageBox.question", side_effect=revogar):
            self.assertFalse(janela.excluir())
        self.assertEqual(self.ctx.contas.obter(identificador)["descricao"], "Aluguel")
        self.assertEqual(janela.linhas, [])

    def test_quitar_e_desquitar_revalidam_acesso_apos_dialogos(self):
        identificador = self.conta()
        janela = self.janela()

        def revogar(*_):
            self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?",
                               (self.operador_adm(),))
            return QMessageBox.StandardButton.Yes

        for nome in ("quitar", "desquitar"):
            with self.subTest(acao=nome):
                self.banco.executar("UPDATE operadores SET ativo = 1 WHERE id = ?",
                                   (self.operador_adm(),))
                self.ctx.contas.quitar(identificador)
                janela.listar()
                self.selecionar(janela, identificador)
                with patch("src.ui_qt.contas.QInputDialog.getText",
                           return_value=("04/10/2026", True)), \
                        patch("src.ui_qt.contas.QMessageBox.question", side_effect=revogar):
                    self.assertFalse(getattr(janela, nome)())
                self.assertEqual(self.ctx.contas.obter(identificador)["dt_quitacao"], "2026-10-03")
                self.assertEqual(janela.linhas, [])

    def test_erro_controller_exposto_sem_mutacao(self):
        identificador = self.conta()
        janela = self.janela()
        self.selecionar(janela, identificador)
        with self.confirmar(), patch.object(ContasController, "excluir",
                                            side_effect=ErroNegocio("Operação bloqueada.")):
            self.assertFalse(janela.excluir())
        self.assertEqual(janela.mensagem.text(), "Operação bloqueada.")
        self.assertEqual(self.ctx.contas.obter(identificador)["descricao"], "Aluguel")
