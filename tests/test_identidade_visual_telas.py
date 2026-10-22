"""Preview e aplicação do logotipo nas duas interfaces, com os controladores reais."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tests import test_qt_caixa


class ComLogotipo:
    def preparar_logo(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.pasta = Path(pasta.name)
        raiz = patch("src.core.identidade_visual.RAIZ", self.pasta)
        raiz.start()
        self.addCleanup(raiz.stop)
        self.origem = self.pasta / "adega.jpg"
        Image.new("RGB", (800, 200), "black").save(self.origem)


class TesteLogotipoQt(ComLogotipo, test_qt_caixa.BaseCaixaQt):
    def configuracoes(self):
        from src.ui_qt.configuracoes import JanelaConfiguracoes
        janela = JanelaConfiguracoes(self.ctx)
        self.addCleanup(janela.deleteLater)
        self.addCleanup(janela.close)
        return janela

    def test_selecionar_preview_salvar_descartar_e_remover(self):
        self.preparar_logo()
        janela = self.configuracoes()
        with patch("src.ui_qt.configuracoes.QFileDialog.getOpenFileName", return_value=(str(self.origem), "")):
            janela.btn_logo.click()
        self.assertFalse(janela.preview_logo.pixmap().isNull())
        self.assertFalse(self.ctx.config.loja()["logotipo"])
        self.assertTrue(janela.recarregar())
        self.assertIn("padrão", janela.preview_logo.text())
        janela.campos["loja"]["logotipo"].setText(str(self.origem))
        self.assertTrue(janela.salvar())
        salvo = self.ctx.config.loja()["logotipo"]
        self.assertEqual(janela.campos["loja"]["logotipo"].text(), salvo)
        self.origem.unlink()
        janela.btn_remover_logo.click()
        self.assertIn("padrão", janela.preview_logo.text())
        self.assertTrue(janela.recarregar())
        self.assertFalse(janela.preview_logo.pixmap().isNull())
        janela.btn_remover_logo.click()
        self.assertTrue(janela.salvar())
        self.assertFalse(self.ctx.config.loja()["logotipo"])

    def test_cancelar_selecao_e_erro_amigavel(self):
        self.preparar_logo()
        janela = self.configuracoes()
        with patch("src.ui_qt.configuracoes.QFileDialog.getOpenFileName", return_value=("", "")):
            janela.btn_logo.click()
        self.assertFalse(janela.campos["loja"]["logotipo"].text())
        with patch("src.ui_qt.configuracoes.QFileDialog.getOpenFileName",
                   return_value=(str(self.pasta / "ausente"), "")):
            janela.btn_logo.click()
        self.assertIn("5 MiB", janela.mensagem.text())
        self.assertFalse(janela.campos["loja"]["logotipo"].text())

    def test_cabecalho_com_logo_e_fallback(self):
        self.preparar_logo()
        self.ctx.config.salvar_loja({"logotipo": self.origem})
        janela = self.janela()
        self.assertFalse(janela.logo_loja.pixmap().isNull())
        Path(self.ctx.config.loja()["logotipo"]).unlink()
        janela = self.janela()
        self.assertTrue(janela.logo_loja.pixmap().isNull())
        self.assertEqual(janela.windowTitle(), f"Caixa - {self.ctx.config.nome_loja()}")
