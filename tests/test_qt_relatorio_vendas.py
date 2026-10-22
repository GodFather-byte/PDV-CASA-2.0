"""Consulta Qt de vendas com controladores reais e banco isolado em memória."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QAbstractItemView

from src.core.erros import ErroPermissao
from src.controllers.contexto import Contexto
from src.ui_qt.relatorio_vendas import JanelaRelatorioVendas
from tests.base import BaseTeste


class TestRelatorioVendasQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.banco.cfg_set("virada_dia_hora", 6)
        self.banco.cfg_set("cobrar_servico", "N")
        self.produto = self.novo_produto("AGUA", 351)
        self.ctx.turnos.abrir(self.ctx.operador_id, 1, 0)
        self.janelas = []
        self.addCleanup(self._fechar_janelas)

    def _fechar_janelas(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        janela = JanelaRelatorioVendas(self.ctx)
        self.janelas.append(janela)
        return janela

    def vender(self, quando="2026-10-03 21:00:00", quantidade=1, cancelar=False):
        self._hora["t"] = datetime.fromisoformat(quando)
        venda = self.ctx.caixa.abrir_balcao()
        self.ctx.caixa.adicionar_item(venda, self.produto, quantidade)
        total = self.ctx.caixa.obter(venda)["total_cent"]
        self.ctx.caixa.adicionar_pagamento(venda, self.tipo(), total)
        self.ctx.caixa.fechar(venda)
        if cancelar:
            self.ctx.caixa.cancelar_venda(venda, "Teste de relatório")
        return venda

    def periodo(self, janela, inicio, fim):
        janela.inicio.setText(inicio)
        janela.fim.setText(fim)
        janela.aplicar.click()

    def valores_grade(self, grade):
        return [[grade.item(linha, coluna).text() for coluna in range(grade.columnCount())]
                for linha in range(grade.rowCount())]

    def test_resultados_reutilizam_relatorio_e_centavos_sem_gravar(self):
        self.vender(quantidade=2)
        self.vender()
        antes = list(self.banco.conexao.iterdump())
        alteracoes = self.banco.conexao.total_changes
        self.banco.executar("PRAGMA query_only = ON")
        janela = self.janela()
        self.periodo(janela, "03/10/2026", "2026-10-03")
        esperado = self.ctx.relatorios.vendas_periodo({"de": "2026-10-03", "ate": "2026-10-03"})
        self.assertEqual(self.valores_grade(janela.grade), esperado.linhas)
        self.assertEqual(self.valores_grade(janela.totais), [list(par) for par in esperado.rodape])
        totais = dict(esperado.rodape)
        self.assertEqual(totais["Total apurado"], "10,53")
        self.assertEqual(totais["Cupons (TC)"], "2")
        self.assertEqual(totais["Ticket médio (TM)"], "5,27")
        self.assertEqual(esperado.linhas[0][3:], ["3,000", "3,51", "10,53"])
        self.assertEqual(janela.mensagem.text(), "")
        for grade in (janela.grade, janela.totais):
            self.assertEqual(grade.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
        self.assertEqual(self.banco.conexao.total_changes, alteracoes)
        self.assertEqual(list(self.banco.conexao.iterdump()), antes)

    def test_periodo_respeita_limites_e_madrugada_operacional(self):
        for quando in ("2026-10-03 05:59:59", "2026-10-03 06:00:00",
                       "2026-10-04 05:59:59", "2026-10-04 06:00:00"):
            self.vender(quando)
        janela = self.janela()
        with patch.object(self.ctx.relatorios, "vendas_periodo",
                          wraps=self.ctx.relatorios.vendas_periodo) as consultar:
            self.periodo(janela, "03/10/2026", "03/10/2026")
        consultar.assert_called_once_with({"de": "2026-10-03", "ate": "2026-10-03"})
        totais = dict(self.valores_grade(janela.totais))
        self.assertEqual(totais["Cupons (TC)"], "2")
        self.assertEqual(totais["Total apurado"], "7,02")
        self.assertIn("06:00", janela.criterios.text())

    def test_padrao_e_dia_operacional_na_madrugada(self):
        self._hora["t"] = datetime(2026, 10, 4, 2)
        janela = self.janela()
        self.assertEqual(janela.inicio.text(), "03/10/2026")
        self.assertEqual(janela.fim.text(), "03/10/2026")

    def test_vazio_mostra_totais_zerados(self):
        janela = self.janela()
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertIn("Nenhuma venda", janela.mensagem.text())
        totais = dict(self.valores_grade(janela.totais))
        self.assertEqual(totais["Total apurado"], "0,00")
        self.assertEqual(totais["Cupons (TC)"], "0")

    def test_periodo_sem_resultado_limpa_consulta_anterior(self):
        self.vender()
        janela = self.janela()
        self.assertEqual(janela.grade.rowCount(), 1)
        self.periodo(janela, "01/01/2020", "01/01/2020")
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertEqual(dict(self.valores_grade(janela.totais))["Total apurado"], "0,00")
        self.assertIn("Nenhuma venda", janela.mensagem.text())

    def test_datas_invalidas_ou_invertidas_nao_consultam_nem_exibem_dados_antigos(self):
        self.vender()
        janela = self.janela()
        for inicio, fim in (("31/02/2026", "03/10/2026"), ("04/10/2026", "03/10/2026")):
            with self.subTest(inicio=inicio), patch.object(self.ctx.relatorios, "vendas_periodo") as consultar:
                self.periodo(janela, inicio, fim)
                consultar.assert_not_called()
                self.assertIsNone(janela.rel)
                self.assertEqual(janela.grade.rowCount(), 0)
                self.assertEqual(janela.totais.rowCount(), 0)
                self.assertTrue(janela.mensagem.text())

    def test_sem_limites_inclui_fechadas_mas_nao_abertas_ou_canceladas(self):
        self.vender("2026-10-02 21:00:00")
        self.vender(cancelar=True)
        aberta = self.ctx.caixa.abrir_balcao()
        self.ctx.caixa.adicionar_item(aberta, self.produto, 10)
        janela = self.janela()
        self.periodo(janela, "", "")
        self.assertEqual(dict(self.valores_grade(janela.totais))["Cupons (TC)"], "1")
        self.assertEqual(janela.rel.linhas[0][3:], ["1,000", "3,51", "3,51"])

    def test_sem_sessao_ou_nivel_insuficiente_bloqueia_antes_da_consulta(self):
        for nivel in (None, 0, 1):
            with self.subTest(nivel=nivel):
                if nivel is None:
                    self.ctx.operador = None
                else:
                    self.banco.executar("UPDATE operadores SET nivel = ? WHERE nome = 'ADM'", (nivel,))
                    self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
                with patch.object(self.ctx.relatorios, "vendas_periodo") as consultar:
                    with self.assertRaises(ErroPermissao):
                        self.janela()
                    consultar.assert_not_called()

    def test_nivel_configuravel_autoriza_operador_nao_administrador(self):
        self.banco.executar("UPDATE operadores SET nivel = 2 WHERE nome = 'ADM'")
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        janela = self.janela()
        self.assertIsNotNone(janela.rel)
        self.ctx.acesso.alterar_nivel_modulo("rel_vendas", 3)
        with patch.object(self.ctx.relatorios, "vendas_periodo") as consultar:
            self.assertFalse(janela.atualizar())
            consultar.assert_not_called()
        self.assertIsNone(janela.rel)

    def test_revogacao_ou_inativacao_limpa_dados_e_revalida_operador(self):
        self.vender()
        janela = self.janela()
        for coluna in ("nivel", "ativo"):
            with self.subTest(coluna=coluna):
                self.banco.executar(f"UPDATE operadores SET {coluna} = 0 WHERE nome = 'ADM'")
                with patch.object(self.ctx.relatorios, "vendas_periodo") as consultar:
                    self.assertFalse(janela.atualizar())
                    consultar.assert_not_called()
                self.assertIsNone(janela.rel)
                self.assertEqual(janela.grade.rowCount(), 0)
                self.assertEqual(janela.totais.rowCount(), 0)
                self.assertTrue(janela.mensagem.text())
                self.banco.executar("UPDATE operadores SET nivel = 4, ativo = 1 WHERE nome = 'ADM'")
                self.assertTrue(janela.atualizar())
