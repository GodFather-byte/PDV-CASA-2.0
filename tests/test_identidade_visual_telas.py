"""Preview e aplicação do logotipo nas duas interfaces, com os controladores reais."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tests import test_ui, test_qt_caixa
from tests.ui_robo import clicar


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


class TesteLogotipoTk(ComLogotipo, test_ui.BaseUI):
    def test_selecionar_preview_salvar_cancelar_e_remover(self):
        from src.ui import config_ui
        self.preparar_logo()
        janela = config_ui.abrir(self.root, self.ctx, "loja")
        self.assertIsNone(janela._foto_logo)
        with patch.object(config_ui.filedialog, "askopenfilename", return_value=str(self.origem)):
            clicar(janela, "Selecionar")
        self.assertIsNotNone(janela._foto_logo)
        self.assertFalse(self.ctx.config.loja()["logotipo"])
        janela.recarregar()
        self.assertIsNone(janela._foto_logo)
        janela.definir("logotipo", str(self.origem))
        with patch.object(config_ui.tema, "mensagem"):
            janela.gravar()
        salvo = self.ctx.config.loja()["logotipo"]
        self.assertEqual(janela.valor("logotipo"), salvo)
        self.origem.unlink()
        clicar(janela, "Remover / padrão")
        self.assertIsNone(janela._foto_logo)
        janela.recarregar()
        self.assertIsNotNone(janela._foto_logo)
        clicar(janela, "Remover / padrão")
        with patch.object(config_ui.tema, "mensagem"):
            janela.gravar()
        self.assertFalse(self.ctx.config.loja()["logotipo"])
        janela.destroy()

    def test_cancelar_selecao_ou_arquivo_invalido_nao_muda_logo(self):
        from src.ui import config_ui
        self.preparar_logo()
        janela = config_ui.abrir(self.root, self.ctx, "loja")
        janela.definir("logotipo", str(self.origem))
        with patch.object(config_ui.filedialog, "askopenfilename", return_value=""):
            clicar(janela, "Selecionar")
        self.assertEqual(janela.valor("logotipo"), str(self.origem))
        with patch.object(config_ui.filedialog, "askopenfilename", return_value=str(self.pasta / "ausente")), \
                patch.object(config_ui.tema, "erro") as erro:
            clicar(janela, "Selecionar")
            erro.assert_called_once()
        self.assertEqual(janela.valor("logotipo"), str(self.origem))
        janela.destroy()

    def test_cabecalho_com_logo_e_fallback(self):
        from src.ui.caixa_ui import JanelaCaixa
        self.preparar_logo()
        self.abrir_turno()
        self.ctx.config.salvar_loja({"logotipo": self.origem})
        for disponivel in (True, False):
            if not disponivel:
                Path(self.ctx.config.loja()["logotipo"]).unlink()
            janela = JanelaCaixa(self.root, self.ctx)
            janela.update()
            self.assertEqual(janela._foto_logo is not None, disponivel)
            self.assertEqual(janela.lbl_loja.cget("text"), self.ctx.config.nome_loja().upper())
            janela.destroy()


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
