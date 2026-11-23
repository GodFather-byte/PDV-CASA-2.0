"""A casa do cliente em destaque: o nome e o logotipo de Dados da Loja no alto do menu, no título e na tela de entrada;
a marca do programa fica pequena no rodapé. Loja sem cadastro continua com a marca da edição."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
from pathlib import Path

from PySide6.QtGui import QColor, QImage

from tests.test_qt_app import BaseQt


class TesteMarcaDaLoja(BaseQt):
    def setUp(self):
        super().setUp()
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.logo = str(Path(pasta.name) / "logo.png")
        imagem = QImage(300, 120, QImage.Format.Format_RGB32)
        imagem.fill(QColor("#1a7a3a"))
        imagem.save(self.logo)

    def principal(self):
        from src.ui_qt.app import JanelaPrincipal
        app = self.app()
        self.ctx = app.ctx
        self.admin()
        janela = self.janela(JanelaPrincipal(app))
        app.principal = janela
        return janela

    def cadastrar(self, nome="", razao="", logo=""):
        self.banco.executar("UPDATE loja SET nome_fantasia = ?, razao_social = ?, logotipo = ? WHERE id = 1",
                            (nome, razao, logo or None))

    def test_sem_cadastro_fica_a_marca_da_edicao(self):
        self.cadastrar()
        janela = self.principal()
        self.assertEqual(janela.lbl_marca.text(), janela.edicao.marca)
        self.assertTrue(janela.logo_loja.isHidden())
        self.assertIn(janela.edicao.nome, janela.lbl_credito.text())

    def test_nome_e_logotipo_da_loja_no_alto_e_a_nossa_marca_no_rodape(self):
        self.cadastrar("CASA VERDE", "Casa Verde Bar Ltda", self.logo)
        janela = self.principal()
        self.assertEqual(janela.lbl_marca.text(), "CASA VERDE")
        self.assertEqual(janela.lbl_marca.objectName(), "marca_loja")
        self.assertFalse(janela.logo_loja.isHidden())
        self.assertLessEqual(janela.logo_loja.pixmap().height(), 40)
        self.assertTrue(janela.windowTitle().startswith("CASA VERDE • "))
        self.assertEqual(janela.lbl_credito.text(), f"{janela.edicao.nome} · WB Sistemas")

    def test_razao_social_quando_nao_ha_nome_fantasia_e_e_comercial_aparece(self):
        self.cadastrar("", "E&A SUPERAÇÕES")
        janela = self.principal()
        self.assertEqual(janela.lbl_marca.text(), "E&A SUPERAÇÕES")          # texto puro: o & não some

    def test_mudar_o_cadastro_troca_a_marca_na_atualizacao(self):
        self.cadastrar()
        janela = self.principal()
        self.cadastrar("CASA VERDE", logo=self.logo)
        janela.atualizar()
        self.assertEqual(janela.lbl_marca.text(), "CASA VERDE")
        self.assertFalse(janela.logo_loja.isHidden())
        self.cadastrar("CASA VERDE", logo=str(Path(self.logo).with_name("sumiu.png")))
        janela.atualizar()
        self.assertTrue(janela.logo_loja.isHidden())                        # logotipo apagado não quebra o menu

    def test_tela_de_entrada_mostra_a_loja_e_o_credito(self):
        from src.ui_qt.login import JanelaLogin
        self.cadastrar("CASA VERDE", logo=self.logo)
        app = self.app()
        entrada = self.janela(JanelaLogin(app.ctx))
        textos = [w.text() for w in entrada.findChildren(type(entrada.credito))]
        self.assertIn("CASA VERDE", textos)
        self.assertFalse(entrada.logo_loja.isHidden())
        self.assertIn("WB Sistemas", entrada.credito.text())
