"""Catálogo Qt com banco em memória; paridade com declarações Tk sem importá-las."""
import ast
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QAbstractItemView

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.core.relatorio import para_csv, para_texto
from src.ui.contexto import Contexto
from src.ui_qt.relatorios import FILTROS, SPECS, JanelaRelatorios
from tests.base import BaseTeste


RAIZ = Path(__file__).resolve().parents[1]


def declaracoes_tk():
    def spec(titulo, filtros, executar, padrao="hoje", **kwargs):
        return SimpleNamespace(titulo=titulo, filtros=filtros, executar=executar,
                               padrao=padrao, mais=kwargs.get("mais", []))

    arvore = ast.parse((RAIZ / "src" / "ui" / "relatorios_ui.py").read_text(encoding="utf-8"))
    nomes = {"FILTROS", "VENDAS", "VENDAS_CATEGORIA", "VENDAS_MAIS", "PERIODO", "PERIODO_TURNO", "SPECS"}
    corpo = []
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(
                isinstance(alvo, ast.Name) and alvo.id in nomes for alvo in no.targets):
            corpo.append(no)
        elif isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name) and no.target.id in nomes:
            corpo.append(ast.Assign(targets=[no.target], value=no.value))
    ambiente = {"Spec": spec, "fmt": fmt}
    exec(compile(ast.fix_missing_locations(ast.Module(body=corpo, type_ignores=[])),
                 "<declarações Tk sem imports>", "exec"), ambiente)
    return ambiente


class TestRelatoriosQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.banco.cfg_set("virada_dia_hora", 6)
        self.janelas = []
        self.addCleanup(self._fechar_janelas)

    def _fechar_janelas(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self, chave="caixa_mov"):
        janela = JanelaRelatorios(self.ctx, chave=chave)
        self.janelas.append(janela)
        return janela

    def selecionar(self, janela, chave):
        janela.selecao.setCurrentIndex(janela.selecao.findData(chave))

    def periodo(self, janela, inicio, fim):
        janela.painel.campos["de"].setText(inicio)
        janela.painel.campos["ate"].setText(fim)
        return janela.atualizar()

    def escolha(self, janela, chave, valor):
        campo = janela.painel.campos[chave]
        indice = campo.findData(valor)
        self.assertGreaterEqual(indice, 0)
        campo.setCurrentIndex(indice)

    def valores_grade(self, grade):
        return [[grade.item(l, c).text() for c in range(grade.columnCount())]
                for l in range(grade.rowCount())]

    def comparar(self, janela, esperado):
        self.assertIsNotNone(janela.rel, janela.mensagem.text())
        self.assertEqual(janela.rel, esperado)
        self.assertEqual(self.valores_grade(janela.grade), esperado.linhas)
        self.assertEqual(self.valores_grade(janela.totais), [list(par) for par in esperado.rodape])
        self.assertEqual([janela.grade.horizontalHeaderItem(i).text()
                          for i in range(janela.grade.columnCount())],
                         [c.titulo for c in esperado.colunas])

    def movimentar_caixa(self):
        turno = self.ctx.turnos.abrir(self.ctx.operador_id, 1, 0)
        self.ctx.turnos.movimentar(turno, self.ctx.operador_id, "entrada", 1053, "Suprimento")
        self.ctx.turnos.movimentar(turno, self.ctx.operador_id, "saida", 351, "Sangria")
        return turno

    def test_catalogo_filtros_padroes_e_modulos_espelham_tk_sem_importar_tk(self):
        tk = declaracoes_tk()
        self.assertEqual(set(SPECS), set(tk["SPECS"]))
        self.assertEqual(len(SPECS), 24)
        self.assertEqual(FILTROS, tk["FILTROS"])
        arvore = ast.parse((RAIZ / "src" / "ui" / "app.py").read_text(encoding="utf-8"))
        grupos = next(ast.literal_eval(no.value) for no in arvore.body
                      if isinstance(no, ast.Assign) and any(
                          isinstance(alvo, ast.Name) and alvo.id == "RELATORIOS" for alvo in no.targets))
        modulos = {chave: modulo for _, itens in grupos for chave, _, modulo in itens}
        for chave, spec in SPECS.items():
            with self.subTest(chave=chave):
                original = tk["SPECS"][chave]
                self.assertEqual(spec.titulo, original.titulo)
                self.assertEqual(list(spec.filtros), original.filtros)
                self.assertEqual(list(spec.mais), original.mais)
                self.assertEqual(spec.padrao, original.padrao)
                self.assertEqual(spec.modulo, modulos[chave])

    def test_todos_os_23_relatorios_consultam_controlador_real_com_paridade_tk(self):
        self.movimentar_caixa()
        produto = self.novo_produto("AGUA", 351, estoque=True)
        lancamento = self.ctx.estoque.criar_lancamento("entrada")
        self.ctx.estoque.adicionar_item(lancamento, produto, 1.2345)
        sub = self.banco.valor("SELECT id FROM subplanos WHERE nome = 'Aluguel'")
        self.ctx.contas.incluir(sub, "Aluguel", self.tipo(), 1053,
                               "03/10/2026", "03/10/2026", "03/10/2026")
        janela = self.janela()
        originais = declaracoes_tk()["SPECS"]
        antes = list(self.banco.conexao.iterdump())
        alteracoes = self.banco.conexao.total_changes
        self.banco.executar("PRAGMA query_only = ON")
        for chave, spec in SPECS.items():
            with self.subTest(chave=chave):
                self.selecionar(janela, chave)
                filtros = janela.painel.valores()
                with patch.object(self.ctx.relatorios, spec.metodo,
                                  wraps=getattr(self.ctx.relatorios, spec.metodo)) as executar:
                    self.assertTrue(janela.atualizar(), janela.mensagem.text())
                    executar.assert_called_once()
                esperado = originais[chave].executar(self.ctx, filtros)
                self.comparar(janela, esperado)
                self.assertEqual(para_csv(janela.rel), para_csv(esperado))
                for grade in (janela.grade, janela.totais):
                    self.assertEqual(grade.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
        self.assertEqual(self.banco.conexao.total_changes, alteracoes)
        self.assertEqual(list(self.banco.conexao.iterdump()), antes)

    def test_caixa_preserva_centavos_lookup_inteiro_e_alias_tipo(self):
        self.movimentar_caixa()
        janela = self.janela()
        janela.painel.campos["turno"].setText("1")
        self.escolha(janela, "operador_id", self.ctx.operador_id)
        self.escolha(janela, "tipo_caixa", "saida")
        filtros = {"de": "2026-10-03", "ate": "2026-10-03", "turno": 1,
                   "operador_id": self.ctx.operador_id, "tipo_caixa": "saida", "tipo": "saida"}
        with patch.object(self.ctx.relatorios, "caixa_movimentos",
                          wraps=self.ctx.relatorios.caixa_movimentos) as consultar:
            self.assertTrue(janela.atualizar())
            consultar.assert_called_once_with(filtros)
        self.assertIs(type(filtros["turno"]), int)
        self.assertEqual(janela.rel.linhas[0][-1], "3,51")
        self.assertEqual(dict(janela.rel.rodape)["Total de saídas (sangrias)"], "3,51")
        self.assertEqual(self.banco.valor("SELECT valor_cent FROM movimentos_caixa WHERE tipo = 'saida'"), 351)

    def test_caixa_respeita_dia_operacional_nos_limites_do_periodo(self):
        turno = self.ctx.turnos.abrir(self.ctx.operador_id, 1, 0)
        for quando in ("2026-10-03 05:59:59", "2026-10-03 06:00:00",
                       "2026-10-04 05:59:59", "2026-10-04 06:00:00"):
            self._hora["t"] = datetime.fromisoformat(quando)
            self.ctx.turnos.movimentar(turno, self.ctx.operador_id, "entrada", 351)
        janela = self.janela()
        self.assertTrue(self.periodo(janela, "03/10/2026", "2026-10-03"))
        self.assertEqual(janela.grade.rowCount(), 2)
        self.assertEqual(dict(janela.rel.rodape)["Total de entradas"], "7,02")
        self.assertIn("06:00", janela.criterios.text())

    def test_financeiro_choices_booleans_planos_e_subplanos(self):
        sub = self.banco.um("SELECT id, plano_id FROM subplanos WHERE nome = 'Aluguel'")
        self.ctx.contas.incluir(sub["id"], "Aluguel", self.tipo(), 1053,
                               "03/10/2026", "01/10/2026", previsao=True)
        janela = self.janela("resultado_financeiro")
        self.assertEqual(janela.painel.campos["por"].currentData(), "dt_quitacao")
        self.escolha(janela, "por", "dt_vencimento")
        self.escolha(janela, "plano_id", sub["plano_id"])
        self.escolha(janela, "subplano_id", sub["id"])
        for chave in ("apenas_resultado", "apenas_debitos", "incluir_previsao"):
            janela.painel.campos[chave].setChecked(True)
        self.assertTrue(self.periodo(janela, "03/10/2026", "03/10/2026"))
        filtros = janela.painel.valores()
        self.assertIs(filtros["incluir_previsao"], True)
        self.assertIs(type(filtros["plano_id"]), int)
        self.comparar(janela, self.ctx.relatorios.resultado_financeiro(filtros))
        self.assertTrue(any("10,53" in linha for linha in janela.rel.linhas))
        janela.painel.campos["incluir_previsao"].setChecked(False)
        self.assertTrue(janela.atualizar())
        self.assertFalse(any("10,53" in linha for linha in janela.rel.linhas))

    def test_estoque_por_periodo_preserva_quantidade_e_sem_recalcular_final(self):
        produto = self.novo_produto("GELO", 351, estoque=True)
        for quando, tipo, quantidade in (("2026-10-02 21:00:00", "entrada", 2),
                                        ("2026-10-03 21:00:00", "entrada", 1.2345),
                                        ("2026-10-04 21:00:00", "saida", 0.1)):
            self._hora["t"] = datetime.fromisoformat(quando)
            lancamento = self.ctx.estoque.criar_lancamento(tipo)
            self.ctx.estoque.adicionar_item(lancamento, produto, quantidade)
        janela = self.janela("posicao_estoque")
        self.assertTrue(self.periodo(janela, "03/10/2026", "03/10/2026"))
        esperado = self.ctx.relatorios.posicao_estoque_periodo({"de": "2026-10-03", "ate": "2026-10-03"})
        self.comparar(janela, esperado)
        self.assertEqual(janela.rel.linhas[0][1], fmt.fmt_qtd(3.1345))
        self.assertEqual(janela.rel.linhas[0][4], fmt.fmt_qtd(1.2345))
        self.assertEqual(janela.rel.linhas[0][5], fmt.fmt_qtd(0))
        self.assertEqual(janela.grade.item(0, 4).data(Qt.ItemDataRole.UserRole), esperado.linhas[0][4])

    def test_movimento_estoque_fornecedor_e_alias(self):
        fornecedor = self.banco.inserir("fornecedores", {"nome": "Fornecedor"})
        produto = self.novo_produto("GELO", 351, estoque=True)
        lancamento = self.ctx.estoque.criar_lancamento("compra", fornecedor_id=fornecedor)
        self.ctx.estoque.adicionar_item(lancamento, produto, 2, 1053)
        janela = self.janela("mov_estoque")
        self.escolha(janela, "tipo_estoque", "compra")
        self.escolha(janela, "fornecedor_id", fornecedor)
        with patch.object(self.ctx.relatorios, "movimento_estoque",
                          wraps=self.ctx.relatorios.movimento_estoque) as consultar:
            self.assertTrue(janela.atualizar())
            consultar.assert_called_once_with({"de": "2026-10-01", "ate": "2026-10-03",
                                               "tipo_estoque": "compra", "tipo": "compra",
                                               "fornecedor_id": fornecedor})
        self.assertEqual(janela.rel.linhas[0][-1], "10,53")

    def test_filtros_adicionais_hora_int_boolean_choice_e_lookup(self):
        cliente = self.banco.inserir("clientes", {"nome": "Cliente", "numero_consulta": 1})
        janela = self.janela("vendas_grupo")
        for chave, valor in (("hora_ini", "22:00"), ("hora_fim", "02:00"),
                             ("cupom_ini", "2"), ("cupom_fim", "12")):
            janela.painel.campos[chave].setText(valor)
        janela.painel.campos["turno_atual"].setChecked(True)
        for chave in ("garcom_id", "vendedor_id", "entregador_id"):
            self.escolha(janela, chave, self.ctx.operador_id)
        self.escolha(janela, "cliente_id", cliente)
        self.escolha(janela, "modalidade", "caderneta")
        filtros = janela.painel.valores()
        self.assertEqual(filtros["hora_ini"], "22:00")
        self.assertEqual(filtros["hora_fim"], "02:00")
        self.assertEqual(filtros["cupom_ini"], 2)
        self.assertEqual(filtros["cliente_id"], cliente)
        self.assertIs(filtros["turno_atual"], True)
        self.assertTrue(janela.atualizar())
        self.selecionar(janela, "comissao_garotas")
        janela.painel.campos["garota"].setText("7")
        janela.painel.campos["detalhar"].setChecked(True)
        self.escolha(janela, "situacao_comissao", "paga")
        self.assertTrue(janela.atualizar())

    def test_padroes_limpar_e_clientes_inativos_sem_datas(self):
        janela = self.janela()
        self.assertEqual(janela.painel.campos["de"].text(), "03/10/2026")
        self.selecionar(janela, "informativo")
        self.assertEqual(janela.painel.campos["de"].text(), "01/10/2026")
        janela.painel.campos["de"].setText("02/10/2026")
        janela.limpar_botao.click()
        self.assertEqual(janela.painel.campos["de"].text(), "01/10/2026")
        self.selecionar(janela, "clientes_inativos")
        self.assertEqual(janela.painel.valores(), {})
        with patch.object(self.ctx.relatorios, "clientes_inativos",
                          wraps=self.ctx.relatorios.clientes_inativos) as consultar:
            self.assertTrue(janela.atualizar())
            consultar.assert_called_once_with("2026-09-03", None)

    def test_datas_invalidas_invertidas_hora_e_inteiro_nao_consultam(self):
        self.movimentar_caixa()
        janela = self.janela("vendas_grupo")
        casos = ({"de": "31/02/2026"}, {"de": "04/10/2026", "ate": "03/10/2026"},
                 {"hora_ini": "25:00"}, {"cupom_ini": "abc"})
        for valores in casos:
            with self.subTest(valores=valores):
                janela.limpar()
                for chave, valor in valores.items():
                    janela.painel.campos[chave].setText(valor)
                with patch.object(self.ctx.relatorios, "vendas_por_grupo") as consultar:
                    self.assertFalse(janela.atualizar())
                    consultar.assert_not_called()
                self.assertIsNone(janela.rel)
                self.assertEqual(janela.grade.rowCount(), 0)
                self.assertEqual(janela.totais.rowCount(), 0)
                self.assertFalse(janela.csv_botao.isEnabled())
                self.assertTrue(janela.mensagem.text())

    def test_vazio_erro_negocio_e_erro_banco_limpam_dados_antigos(self):
        janela = self.janela()
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertIn("Nada encontrado", janela.mensagem.text())
        self.assertEqual(dict(janela.rel.rodape)["Total de entradas"], "0,00")
        self.movimentar_caixa()
        self.assertTrue(janela.atualizar())
        self.assertEqual(janela.grade.rowCount(), 2)
        self.assertTrue(self.periodo(janela, "01/01/2020", "01/01/2020"))
        self.assertEqual(janela.grade.rowCount(), 0)
        for erro in (ErroNegocio("Falha de consulta"), sqlite3.OperationalError("Banco indisponível")):
            with self.subTest(erro=erro), patch.object(
                    self.ctx.relatorios, "caixa_movimentos", side_effect=erro):
                self.assertFalse(janela.atualizar())
                self.assertIsNone(janela.rel)
                self.assertEqual(janela.totais.rowCount(), 0)
                self.assertEqual(janela.mensagem.text(), str(erro))

    def test_sem_sessao_inativo_ou_nivel_insuficiente_bloqueia_consulta_e_lookups(self):
        for estado in ("sem_sessao", "inativo", "sem_nivel"):
            self.banco.executar("UPDATE operadores SET ativo = 1, nivel = 4 WHERE nome = 'ADM'")
            self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
            if estado == "sem_sessao":
                self.ctx.operador = None
            elif estado == "inativo":
                self.banco.executar("UPDATE operadores SET ativo = 0 WHERE nome = 'ADM'")
            else:
                self.banco.executar("UPDATE operadores SET nivel = 0 WHERE nome = 'ADM'")
            with self.subTest(estado=estado), patch.object(
                    self.ctx.relatorios, "caixa_movimentos") as consultar, patch.object(
                    self.ctx.cadastros, "opcoes", wraps=self.ctx.cadastros.opcoes) as lookup:
                with self.assertRaises(ErroPermissao):
                    self.janela()
                consultar.assert_not_called()
                self.assertTrue(all(chamada.args == ("cargos",) for chamada in lookup.call_args_list))

    def test_cada_modulo_e_revalidado_inclusive_custo_medio(self):
        self.banco.executar("UPDATE operadores SET nivel = 3 WHERE nome = 'ADM'")
        for modulo in {s.modulo for s in SPECS.values()}:
            self.ctx.acesso.alterar_nivel_modulo(modulo, 1)
        janela = self.janela()
        for chave, spec in SPECS.items():
            with self.subTest(chave=chave):
                self.selecionar(janela, chave)
                self.assertIsNotNone(janela.rel)
                self.ctx.acesso.alterar_nivel_modulo(spec.modulo, 4)
                with patch.object(self.ctx.relatorios, spec.metodo) as consultar:
                    self.assertFalse(janela.atualizar())
                    consultar.assert_not_called()
                self.assertIsNone(janela.rel)
                self.ctx.acesso.alterar_nivel_modulo(spec.modulo, 1)
                self.assertTrue(janela.atualizar())

    def test_selecao_sem_acesso_nao_carrega_lookup_nem_mantem_relatorio(self):
        janela = self.janela()
        self.banco.executar("UPDATE operadores SET nivel = 1 WHERE nome = 'ADM'")
        self.ctx.acesso.alterar_nivel_modulo("rel_financeiro", 4)
        with patch.object(self.ctx.cadastros, "opcoes", wraps=self.ctx.cadastros.opcoes) as lookup, patch.object(
                self.ctx.relatorios, "resultado_financeiro") as consultar:
            self.selecionar(janela, "resultado_financeiro")
            self.assertTrue(all(chamada.args == ("cargos",) for chamada in lookup.call_args_list))
            consultar.assert_not_called()
        self.assertIsNone(janela.painel)
        self.assertIsNone(janela.rel)
        self.ctx.acesso.alterar_nivel_modulo("rel_financeiro", 1)
        self.assertTrue(janela.atualizar())

    def test_csv_usa_conversor_comum_e_nao_dobra_quebras_de_linha(self):
        self.movimentar_caixa()
        janela = self.janela()
        caminho = RAIZ / "tests" / "_qt_relatorios_exportacao.csv"
        self.addCleanup(caminho.unlink, missing_ok=True)
        esperado = para_csv(janela.rel)
        with patch("src.ui_qt.relatorios.QFileDialog.getSaveFileName",
                   return_value=(str(caminho), "CSV (*.csv)")):
            janela.csv_botao.click()
        conteudo = caminho.read_bytes()
        self.assertEqual(conteudo.decode("utf-8-sig"), esperado)
        self.assertTrue(conteudo.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r\r\n", conteudo)
        self.assertIn("10,53", esperado)

    def test_visualizacao_textual_usa_conversor_e_modulo_de_cada_relatorio(self):
        janela = self.janela()
        for chave, spec in SPECS.items():
            with self.subTest(chave=chave):
                self.selecionar(janela, chave)
                self.assertTrue(janela.visualizar_botao.isEnabled())
                with patch("src.ui_qt.relatorios.JanelaVisualizador") as visualizador, patch.object(
                        self.ctx.impressao, "enviar") as enviar:
                    janela.visualizar_botao.click()
                    visualizador.assert_called_once_with(
                        self.ctx, janela.rel.titulo, para_texto(janela.rel, 100),
                        parent=janela, modulo=spec.modulo, nome=chave, tipo="relatorio")
                    visualizador.return_value.exec.assert_called_once_with()
                    enviar.assert_not_called()

    def test_visualizacao_bloqueia_filtros_pendentes_e_permissao_revogada(self):
        janela = self.janela()
        janela.painel.campos["de"].setText("")
        self.assertFalse(janela.visualizar_botao.isEnabled())
        with patch("src.ui_qt.relatorios.JanelaVisualizador") as visualizador:
            self.assertFalse(janela.visualizar())
            visualizador.assert_not_called()
        self.assertTrue(janela.atualizar())
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE nome = 'ADM'")
        with patch("src.ui_qt.relatorios.JanelaVisualizador") as visualizador:
            self.assertFalse(janela.visualizar())
            visualizador.assert_not_called()
        self.assertFalse(janela.visualizar_botao.isEnabled())

    def test_exportacao_revalida_revogacao_inativacao_e_troca_sessao(self):
        janela = self.janela()
        for estado in ("sem_sessao", "inativo", "rebaixado", "modulo", "outra_sessao"):
            self.banco.executar("UPDATE operadores SET ativo = 1, nivel = 3 WHERE nome = 'ADM'")
            self.ctx.acesso.alterar_nivel_modulo("rel_caixa", 1)
            self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
            self.assertTrue(janela.atualizar())
            if estado == "sem_sessao":
                self.ctx.operador = None
            elif estado == "inativo":
                self.banco.executar("UPDATE operadores SET ativo = 0 WHERE nome = 'ADM'")
            elif estado == "rebaixado":
                self.banco.executar("UPDATE operadores SET nivel = 0 WHERE nome = 'ADM'")
            elif estado == "modulo":
                self.ctx.acesso.alterar_nivel_modulo("rel_caixa", 4)
            else:
                outro = self.banco.inserir("operadores", {"nome": "OUTRO", "senha": "", "nivel": 4})
                self.ctx.operador = self.ctx.acesso.operador(outro)
            with self.subTest(estado=estado), patch("src.ui_qt.relatorios.Path.open") as abrir:
                self.assertFalse(janela.exportar_csv("nao_deve_existir.csv"))
                abrir.assert_not_called()
                self.assertIsNone(janela.rel)

    def test_exportacao_revalida_apos_dialogo_e_rejeita_filtros_pendentes(self):
        janela = self.janela()

        def revogar(*_):
            self.banco.executar("UPDATE operadores SET ativo = 0 WHERE nome = 'ADM'")
            return "nao_deve_existir.csv", ""

        with patch("src.ui_qt.relatorios.QFileDialog.getSaveFileName", side_effect=revogar), patch(
                "src.ui_qt.relatorios.Path.open") as abrir:
            self.assertFalse(janela.exportar_csv())
            abrir.assert_not_called()
        self.banco.executar("UPDATE operadores SET ativo = 1 WHERE nome = 'ADM'")
        self.assertTrue(janela.atualizar())
        janela.painel.campos["de"].setText("")
        self.assertIsNone(janela.rel)
        with patch("src.ui_qt.relatorios.Path.open") as abrir:
            self.assertFalse(janela.exportar_csv("nao_deve_existir.csv"))
            abrir.assert_not_called()

    def test_exportacao_cancelada_ou_erro_de_escrita(self):
        janela = self.janela()
        with patch("src.ui_qt.relatorios.QFileDialog.getSaveFileName", return_value=("", "")), patch(
                "src.ui_qt.relatorios.Path.open") as abrir:
            self.assertFalse(janela.exportar_csv())
            abrir.assert_not_called()
        with patch("src.ui_qt.relatorios.Path.open", side_effect=OSError("Sem espaço")):
            self.assertFalse(janela.exportar_csv("nao_deve_existir.csv"))
        self.assertEqual(janela.mensagem.text(), "Sem espaço")

    def test_importacao_e_janela_funcionam_com_tkinter_proibido(self):
        codigo = """
import builtins
original = builtins.__import__
def sem_tk(nome, *args, **kwargs):
    if nome == 'tkinter' or nome.startswith('tkinter.'):
        raise AssertionError('Dependência Tk proibida')
    return original(nome, *args, **kwargs)
builtins.__import__ = sem_tk
from PySide6.QtWidgets import QApplication
from src.database.conexao import BancoDados
from src.ui.contexto import Contexto
from src.ui_qt.relatorios import JanelaRelatorios
from src.ui_qt.visualizador import JanelaVisualizador
from unittest.mock import patch
app = QApplication([])
banco = BancoDados(':memory:')
ctx = Contexto(banco)
ctx.operador = ctx.acesso.operador(banco.valor('SELECT id FROM operadores LIMIT 1'))
janela = JanelaRelatorios(ctx)
assert janela.rel is not None, janela.mensagem.text()
with patch.object(JanelaVisualizador, 'exec', return_value=0):
    assert janela.visualizar()
janela.close()
banco.fechar()
"""
        resultado = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ,
                                   capture_output=True, text=True, timeout=60)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
