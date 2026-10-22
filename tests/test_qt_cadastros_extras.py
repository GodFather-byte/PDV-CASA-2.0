"""Saídas e cadastro de setores Qt sem hardware e sem banco de loja."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import io
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog, QMessageBox

from src.core.erros import ErroPermissao
from src.ui.contexto import Contexto
from src.ui_qt.cadastros import FormularioCadastro, JanelaCadastro
from tests.base import BaseTeste


class ArquivoSimulado(io.StringIO):
    def close(self):
        self.conteudo = self.getvalue()
        super().close()


class TestCadastrosExtrasQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.banco.cfg_set("usar_caderneta", "S")
        self.janelas = []
        self.addCleanup(self._fechar)

    def _fechar(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self, chave):
        janela = JanelaCadastro(self.ctx, chave)
        self.janelas.append(janela)
        return janela

    def test_cadastro_setor_e_lookup_no_subgrupo(self):
        self.banco.cfg_set("usar_cozinha_bar", "S")
        formulario = FormularioCadastro(self.ctx, "setores_impressao")
        self.janelas.append(formulario)
        formulario.campos["nome"].setText("COZINHA")
        formulario.campos["conexao"].setCurrentIndex(
            formulario.campos["conexao"].findData("rede"))
        formulario.campos["endereco"].setText("192.0.2.10:9100")
        formulario.campos["ordem"].setText("2")
        formulario.salvar()
        self.assertEqual(formulario.result(), QDialog.DialogCode.Accepted)
        setor = self.ctx.cadastros.obter("setores_impressao", formulario.id_)
        self.assertEqual(setor["nome"], "COZINHA")
        self.assertEqual(setor["endereco"], "192.0.2.10:9100")
        self.assertEqual(setor["ordem"], 2)
        janela = self.janela("setores_impressao")
        self.assertEqual(janela.grade.rowCount(), 1)
        subgrupo = self.banco.valor("SELECT id FROM subgrupos LIMIT 1")
        formulario_sub = FormularioCadastro(self.ctx, "subgrupos", subgrupo)
        self.janelas.append(formulario_sub)
        combo = formulario_sub.campos["setor_impressao_id"]
        combo.setCurrentIndex(combo.findData(formulario.id_))
        formulario_sub.salvar()
        self.assertEqual(self.ctx.cadastros.obter("subgrupos", subgrupo)["setor_impressao_id"],
                         formulario.id_)

    def test_setores_desligados_bloqueiam_salvar_e_consultar(self):
        self.banco.cfg_set("usar_cozinha_bar", "S")
        janela = self.janela("setores_impressao")
        formulario = FormularioCadastro(self.ctx, "setores_impressao")
        self.janelas.append(formulario)
        formulario.campos["nome"].setText("BAR")
        self.banco.cfg_set("usar_cozinha_bar", "N")
        with self.assertRaises(ErroPermissao):
            janela.exigir_acesso()
        formulario.salvar()
        self.assertIn("não permite", formulario.mensagem.text())
        self.assertEqual(self.ctx.cadastros.listar("setores_impressao"), [])

    def test_relatorio_de_produtos_filtrado_e_csv_sem_senha(self):
        self.novo_produto("AGUA", preco=350)
        self.novo_produto("SUCO", preco=500)
        janela = self.janela("produtos")
        janela.busca.setText("AGUA")
        relatorio = janela._relatorio()
        self.assertEqual(len(relatorio.linhas), 1)
        self.assertIn("AGUA", relatorio.linhas[0])
        self.assertIn("3,50", relatorio.linhas[0])
        arquivo = ArquivoSimulado()
        with patch.object(Path, "open", return_value=arquivo):
            self.assertTrue(janela.exportar_csv(Path("produtos_teste.csv")))
        self.assertIn("AGUA", arquivo.conteudo)
        self.assertNotIn("SUCO", arquivo.conteudo)
        operadores = self.janela("operadores")
        self.assertNotIn("senha", [c.nome for c in operadores.colunas])

    def test_tabela_precos_visualiza_sem_enviar(self):
        self.novo_produto("AGUA", preco=350)
        janela = self.janela("produtos")
        with patch.object(self.ctx.impressao, "enviar") as enviar:
            documento = janela.tabela_precos()
            self.assertIsNotNone(documento)
            self.janelas.append(documento)
            self.assertIn("AGUA", documento.texto)
            self.assertEqual(documento.modulo, "cad_produtos")
            enviar.assert_not_called()

    def test_arquivo_clientes_equivalente_tk_escolhe_destino(self):
        self.ctx.cadastros.salvar("clientes", {
            "numero_consulta": "1", "nome": "ANA", "obs": "PORTA;LADO\nAZUL"})
        janela = self.janela("clientes")
        arquivo = ArquivoSimulado()
        with patch("src.ui_qt.cadastros.QFileDialog.getSaveFileName",
                   return_value=("clientes_teste.txt", "")), patch.object(
                       Path, "open", return_value=arquivo) as abrir:
            self.assertTrue(janela.gerar_clientes())
        abrir.assert_called_once_with("w", encoding="utf-8-sig", newline="")
        self.assertTrue(arquivo.conteudo.startswith("numero_consulta;nome;endereco;"))
        self.assertIn("ANA", arquivo.conteudo)
        self.assertIn("PORTA,LADO AZUL", arquivo.conteudo)

    def test_cancelar_exportacao_nao_cria_arquivo(self):
        janela = self.janela("clientes")
        with patch("src.ui_qt.cadastros.QFileDialog.getSaveFileName",
                   return_value=("", "")), patch.object(Path, "open") as abrir:
            self.assertFalse(janela.gerar_clientes())
            abrir.assert_not_called()

    def test_revalida_depois_do_dialogo_antes_de_exportar(self):
        janela = self.janela("clientes")

        def revogar(*args):
            self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?",
                                (self.ctx.operador_id,))
            return "clientes_teste.txt", ""

        with patch("src.ui_qt.cadastros.QFileDialog.getSaveFileName",
                   side_effect=revogar), patch.object(Path, "open") as abrir:
            self.assertFalse(janela.gerar_clientes())
            abrir.assert_not_called()
        self.assertIn("inativo", janela.mensagem.text())

    def test_sessao_trocada_bloqueia_documento_e_formulario(self):
        janela = self.janela("clientes")
        formulario = FormularioCadastro(self.ctx, "clientes")
        self.janelas.append(formulario)
        formulario.campos["numero_consulta"].setText("2")
        formulario.campos["nome"].setText("ANA")
        self.ctx.operador = None
        self.assertIsNone(janela.visualizar())
        formulario.salvar()
        self.assertIn("sessão mudou", formulario.mensagem.text())
        self.assertEqual(self.ctx.cadastros.listar("clientes"), [])

    def test_revoga_permissao_antes_de_excluir_apos_confirmacao(self):
        self.ctx.cadastros.salvar("clientes", {"numero_consulta": "1", "nome": "ANA"})
        janela = self.janela("clientes")
        janela.grade.selectRow(0)

        def revogar(*args):
            self.banco.executar("UPDATE operadores SET nivel = 0 WHERE id = ?",
                                (self.ctx.operador_id,))
            return QMessageBox.StandardButton.Yes

        with patch("src.ui_qt.cadastros.QMessageBox.question", side_effect=revogar):
            janela.excluir()
        self.assertEqual(len(self.ctx.cadastros.listar("clientes")), 1)
        self.assertIn("não permite", janela.mensagem.text())

    def _clientes_para_filtro(self):
        bairro = self.banco.inserir("bairros", {"nome": "CENTRO"})
        outro = self.banco.inserir("bairros", {"nome": "VILA"})
        ids = []
        for numero, nome, bairro_id, ativo in (
            ("1", "ZELIA", bairro, "S"), ("2", "ANA", bairro, "S"),
            ("3", "MARIA", bairro, "N"), ("4", "ANA VILA", outro, "S"),
        ):
            ids.append(self.ctx.cadastros.salvar("clientes", {
                "numero_consulta": numero, "nome": nome, "bairro_id": bairro_id, "ativo": ativo}))
        return bairro, ids

    def test_filtros_lookup_ativos_pesquisa_e_exportacao_combinados(self):
        bairro, ids = self._clientes_para_filtro()
        janela = self.janela("clientes")
        janela.busca.setText("A")
        self.assertTrue(janela.aplicar_filtros({"bairro_id": bairro}, True))
        self.assertEqual(janela.grade.rowCount(), 2)
        self.assertEqual(janela.filtros, {"bairro_id": bairro})
        relatorio = janela._relatorio()
        self.assertEqual([linha[1] for linha in relatorio.linhas], ["ANA", "ZELIA"])
        arquivo = ArquivoSimulado()
        with patch.object(Path, "open", return_value=arquivo):
            self.assertTrue(janela.exportar_csv("clientes_filtrados.csv"))
        self.assertIn("ZELIA", arquivo.conteudo)
        self.assertNotIn("MARIA", arquivo.conteudo)
        self.assertNotIn("ANA VILA", arquivo.conteudo)
        self.assertTrue(janela.aplicar_filtros({}))
        self.assertEqual(janela.grade.rowCount(), 4)

    def test_ordenacao_alterna_padrao_e_cadastramento_preservando_selecao(self):
        bairro, ids = self._clientes_para_filtro()
        janela = self.janela("clientes")
        self.assertTrue(janela.aplicar_filtros({"bairro_id": bairro}, True))
        janela.grade.selectRow(0)
        selecionado = janela.selecionado()
        self.assertEqual(selecionado, ids[1])
        self.assertTrue(janela.ordenar())
        self.assertEqual(janela.ordem, "id")
        self.assertEqual(janela.selecionado(), selecionado)
        self.assertEqual([linha[1] for linha in janela._relatorio().linhas], ["ZELIA", "ANA"])
        self.assertEqual(janela.filtros, {"bairro_id": bairro})
        self.assertTrue(janela.apenas_ativos)
        self.assertTrue(janela.ordenar())
        self.assertEqual(janela.ordem, janela.entidade.ordem)
        self.assertEqual([linha[1] for linha in janela._relatorio().linhas], ["ANA", "ZELIA"])

    def test_dialogo_de_filtros_por_metadados_aplica_e_reabre_valores(self):
        bairro, _ = self._clientes_para_filtro()
        janela = self.janela("clientes")

        def aplicar(dialogo):
            combos = dialogo.findChildren(QComboBox)
            self.assertEqual(len(combos), 1)
            self.assertIsNone(combos[0].currentData())
            combos[0].setCurrentIndex(combos[0].findData(bairro))
            dialogo.findChild(QCheckBox).setChecked(True)
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, "exec", new=aplicar):
            self.assertTrue(janela.filtrar())

        def cancelar(dialogo):
            self.assertEqual(dialogo.findChild(QComboBox).currentData(), bairro)
            self.assertTrue(dialogo.findChild(QCheckBox).isChecked())
            dialogo.findChild(QComboBox).setCurrentIndex(0)
            dialogo.findChild(QCheckBox).setChecked(False)
            return QDialog.DialogCode.Rejected

        with patch.object(QDialog, "exec", new=cancelar):
            self.assertFalse(janela.filtrar())
        self.assertEqual(janela.filtros, {"bairro_id": bairro})
        self.assertTrue(janela.apenas_ativos)

    def test_revalida_permissao_apos_dialogo_filtros(self):
        bairro, _ = self._clientes_para_filtro()
        janela = self.janela("clientes")

        def revogar(dialogo):
            combo = dialogo.findChild(QComboBox)
            combo.setCurrentIndex(combo.findData(bairro))
            self.banco.executar("UPDATE operadores SET nivel = 0 WHERE id = ?",
                                (self.ctx.operador_id,))
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, "exec", new=revogar):
            self.assertFalse(janela.filtrar())
        self.assertEqual(janela.filtros, {})
        self.assertIn("não permite", janela.mensagem.text())
        self.assertFalse(janela.ordenar())
        self.assertEqual(janela.ordem, janela.entidade.ordem)

    def test_recusa_filtro_fora_metadados_sem_mudar_estado(self):
        bairro, _ = self._clientes_para_filtro()
        janela = self.janela("clientes")
        self.assertTrue(janela.aplicar_filtros({"bairro_id": bairro}, True))
        self.assertFalse(janela.aplicar_filtros({"nome": "ANA"}))
        self.assertFalse(janela.aplicar_filtros({"bairro_id": 999999}))
        self.assertEqual(janela.filtros, {"bairro_id": bairro})
        self.assertTrue(janela.apenas_ativos)

    def test_cadastro_sem_lookup_ou_ativo_oferece_pesquisa(self):
        janela = self.janela("unidades")

        def cancelar(dialogo):
            self.assertEqual(dialogo.findChildren(QComboBox), [])
            self.assertFalse(any(c.isVisibleTo(dialogo) for c in dialogo.findChildren(QCheckBox)))
            return QDialog.DialogCode.Rejected

        with patch.object(QDialog, "exec", new=cancelar):
            self.assertFalse(janela.filtrar())
        self.assertEqual(janela.filtros, {})
