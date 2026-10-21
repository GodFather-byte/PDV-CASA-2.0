"""Fluxo Qt de importação com APIs reais e banco isolado em memória."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from src.core.erros import ErroNegocio, ErroPermissao
from src.ui.contexto import Contexto
from src.ui_qt.importar_produtos import JanelaImportarNFe, JanelaImportarProdutos
from tests.base import BaseTeste


class TestImportarProdutosQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.janelas = []
        self.addCleanup(self._fechar_janelas)
        self.arquivos = []
        self.addCleanup(self._remover_arquivos)

    def _remover_arquivos(self):
        for caminho in self.arquivos:
            caminho.unlink(missing_ok=True)

    def _fechar_janelas(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self, ao_importar=None):
        janela = JanelaImportarProdutos(self.ctx, ao_importar=ao_importar)
        self.janelas.append(janela)
        return janela

    def planilha(self, conteudo):
        caminho = Path(__file__).parent / f".qt-importar-{uuid4().hex}.csv"
        caminho.write_text(conteudo, encoding="utf-8-sig", newline="")
        self.arquivos.append(caminho)
        return caminho

    def test_prevê_validações_e_preserva_preço_em_centavos(self):
        janela = self.janela()
        arquivo = self.planilha(
            "Código;Produto;Preço;Quantidade\n"
            "1;CERVEJA;10,25;2\n"
            "50;RESERVADO;5,00;\n"
            ";SEM PREÇO;;\n")

        self.assertTrue(janela.carregar(str(arquivo)))
        self.assertEqual(janela.grade.rowCount(), 3)
        self.assertEqual(janela.grade.item(0, 1).text(), "Criar")
        self.assertEqual(janela.grade.item(0, 4).text(), "10,25")
        self.assertEqual(janela.grade.item(0, 7).text(), "2")
        self.assertEqual(janela.grade.item(1, 1).text(), "Recusado")
        self.assertIn("reservado", janela.grade.item(1, 8).text())
        self.assertEqual(janela.grade.item(2, 1).text(), "Recusado")
        self.assertIn("Falta o preço", janela.grade.item(2, 8).text())
        self.assertTrue(janela.btn_importar.isEnabled())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), 0)

    def test_importa_somente_apos_confirmacao_e_atualiza_lista(self):
        recarregamentos = []
        janela = self.janela(lambda: recarregamentos.append(True))
        arquivo = self.planilha("Produto;Preço\nDOSE;7,35\n")
        janela.carregar(str(arquivo))

        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes) as confirmar, \
             patch.object(QMessageBox, "information") as informar:
            self.assertTrue(janela.importar())

        confirmar.assert_called_once()
        informar.assert_called_once()
        self.assertEqual(self.banco.valor(
            "SELECT preco_cent FROM produtos WHERE nome = 'DOSE'"), 735)
        self.assertEqual(recarregamentos, [True])
        self.assertIsNone(janela.previa)
        self.assertFalse(janela.btn_importar.isEnabled())

    def test_cancelamento_na_confirmacao_nao_grava_nem_anuncia_sucesso(self):
        janela = self.janela()
        janela.carregar(str(self.planilha("Produto;Preço\nDOSE;7,35\n")))

        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No), \
             patch.object(QMessageBox, "information") as informar:
            self.assertFalse(janela.importar())

        informar.assert_not_called()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), 0)
        self.assertIsNotNone(janela.previa)

    def test_falha_transacional_nao_anuncia_sucesso_nem_recarrega(self):
        recarregamentos = []
        janela = self.janela(lambda: recarregamentos.append(True))
        janela.carregar(str(self.planilha("Produto;Preço\nDOSE;7,35\n")))

        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QMessageBox, "information") as informar, \
             patch.object(janela.imp, "importar",
                          side_effect=ErroNegocio("falhou na transação")):
            self.assertFalse(janela.importar())

        informar.assert_not_called()
        self.assertEqual(recarregamentos, [])
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), 0)
        self.assertIn("falhou na transação", janela.mensagem.text())

    def test_falha_ao_ler_arquivo_mantem_importacao_desabilitada(self):
        janela = self.janela()

        self.assertFalse(janela.carregar(str(Path(__file__).parent / "nao-existe-produtos.csv")))

        self.assertFalse(janela.btn_importar.isEnabled())
        self.assertIn("Não consegui ler", janela.mensagem.text())

    def test_cancelar_selecao_de_arquivo_nao_altera_estado(self):
        janela = self.janela()
        with patch("src.ui_qt.importar_produtos.QFileDialog.getOpenFileName",
                   return_value=("", "")):
            janela.escolher_arquivo()

        self.assertIsNone(janela.tabela)
        self.assertIsNone(janela.previa)
        self.assertFalse(janela.btn_importar.isEnabled())

    def test_modelo_e_exportacao_usam_os_metodos_do_controlador(self):
        self.novo_produto("CAMPARI", 1025, codigo="7")
        janela = self.janela()
        modelo = Path(__file__).parent / f".qt-modelo-{uuid4().hex}.csv"
        exportado = Path(__file__).parent / f".qt-exportado-{uuid4().hex}.csv"
        self.arquivos.extend((modelo, exportado))

        with patch("src.ui_qt.importar_produtos.QFileDialog.getSaveFileName",
                   side_effect=[(str(modelo), ""), (str(exportado), "")]), \
             patch.object(QMessageBox, "information") as informar:
            self.assertTrue(janela.salvar_modelo())
            self.assertTrue(janela.exportar())

        informar.assert_called()
        self.assertIn("Produto;Preço", modelo.read_text(encoding="utf-8-sig"))
        self.assertIn("7;CAMPARI;10,25", exportado.read_text(encoding="utf-8-sig"))

    def test_previa_nfe_permite_preco_manual_e_confirma_entrada(self):
        recarregamentos = []
        janela = self.janela(lambda: recarregamentos.append(True))
        xml = """<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe123">
          <ide><mod>55</mod><nNF>123</nNF><dhEmi>2026-10-03T10:00:00-03:00</dhEmi></ide>
          <emit><CNPJ>12345678000199</CNPJ><xNome>Fornecedor UI</xNome></emit>
          <det nItem="1"><prod><cProd>A1</cProd><cEAN>SEM GTIN</cEAN><xProd>PRODUTO SEM EAN</xProd>
          <uCom>UN</uCom><qCom>2</qCom><vUnCom>3.50</vUnCom><vProd>7.00</vProd></prod></det>
        </infNFe></NFe></nfeProc>"""
        arquivo = Path(__file__).parent / f".qt-nfe-{uuid4().hex}.xml"
        arquivo.write_text(xml, encoding="utf-8")
        self.arquivos.append(arquivo)
        previa = janela.imp_nfe.analisar(arquivo)
        dialogo = JanelaImportarNFe(janela, previa)
        self.janelas.append(dialogo)
        dialogo.grupo.setCurrentText("ADEGA")
        dialogo.precos_venda[0].setText("12,50")
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QMessageBox, "information"):
            self.assertTrue(dialogo.confirmar())
        produto = self.banco.um("SELECT p.* FROM produtos p WHERE p.nome = 'PRODUTO SEM EAN'")
        self.assertEqual((produto["preco_cent"], produto["ult_preco_cent"], produto["qt_atual"]), (1250, 350, 2))
        self.assertEqual(self.banco.valor(
            "SELECT g.nome FROM produtos p JOIN subgrupos s ON s.id=p.subgrupo_id "
            "JOIN grupos g ON g.id=s.grupo_id WHERE p.id=?", (produto["id"],)), "ADEGA")
        self.assertEqual(recarregamentos, [True])

    def test_exige_permissao_de_cadastro_de_produtos(self):
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            JanelaImportarProdutos(self.ctx)

        self.banco.executar(
            "UPDATE operadores SET nivel = 1 WHERE id = ?", (self.operador_adm(),))
        self.banco.executar(
            "UPDATE acessos SET nivel = 4 WHERE modulo = 'cad_produtos'")
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        with self.assertRaises(ErroPermissao):
            JanelaImportarProdutos(self.ctx)


if __name__ == "__main__":
    unittest.main()
