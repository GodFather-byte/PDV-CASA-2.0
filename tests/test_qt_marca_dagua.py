"""Logotipo da casa como papel de parede do caixa."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from src.controllers.contexto import Contexto
from src.ui_qt import marca_dagua
from src.ui_qt.caixa import JanelaCaixa
from tests.base import BaseTeste


def criar_logo(pasta, fundo="white", desenho="black"):
    from PIL import Image, ImageDraw
    imagem = Image.new("RGB", (200, 100), fundo)
    ImageDraw.Draw(imagem).ellipse((60, 10, 140, 90), fill=desenho)
    caminho = Path(pasta) / f"logo_{fundo}.png"
    imagem.save(caminho)
    return str(caminho)


class TesteMarcaDagua(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.pasta = pasta.name
        self.janelas = []
        self.addCleanup(self._fechar)

    def _fechar(self):
        for janela in self.janelas:
            janela.hide()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_silhueta_deixa_o_fundo_transparente_e_pinta_so_o_desenho(self):
        for fundo, desenho in (("white", "black"), ("black", "white")):      # arte clara em fundo escuro também vale
            imagem = marca_dagua.silhueta(criar_logo(self.pasta, fundo, desenho), QColor("#ffffff"))
            self.assertEqual(imagem.pixelColor(2, 2).alpha(), 0, fundo)
            centro = imagem.pixelColor(imagem.width() // 2, imagem.height() // 2)
            self.assertEqual((centro.alpha(), centro.red()), (255, 255), fundo)

    def test_sem_logotipo_ou_arquivo_invalido_nao_ha_marca(self):
        liso = criar_logo(self.pasta, "white", "white")
        quebrado = Path(self.pasta) / "quebrado.png"
        quebrado.write_bytes(b"nao e imagem")
        for caminho in (None, "", str(Path(self.pasta) / "sumiu.png"), str(quebrado), liso):
            self.assertIsNone(marca_dagua.silhueta(caminho, QColor("#ffffff")), caminho)
        self.assertIsNone(marca_dagua.aplicar(QWidget(), None, False))

    def test_marca_cobre_a_janela_fica_no_centro_e_deixa_o_clique_passar(self):
        janela = QWidget()
        self.janelas.append(janela)
        botao = QPushButton("Receber")
        QVBoxLayout(janela).addWidget(botao)
        cliques = []
        botao.clicked.connect(lambda: cliques.append(1))
        marca = marca_dagua.aplicar(janela, criar_logo(self.pasta), False)
        janela.resize(600, 400)
        janela.show()
        self.aplicacao.processEvents()
        self.assertEqual(marca.geometry(), janela.rect())
        area = marca.area_do_desenho()
        self.assertEqual(area.center(), janela.rect().center())
        self.assertLessEqual(area.width(), 600 * marca_dagua.FRACAO_LARGURA + 1)
        self.assertLessEqual(area.height(), 400 * marca_dagua.FRACAO_ALTURA + 1)
        self.assertLess(marca.opacidade, 0.12)                              # discreta: não disputa com os números
        self.assertIs(janela.childAt(botao.geometry().center()), botao)      # a marca não intercepta o ponteiro
        QTest.mouseClick(botao, Qt.MouseButton.LeftButton)
        self.assertEqual(cliques, [1])
        janela.resize(900, 500)
        self.aplicacao.processEvents()
        self.assertEqual(marca.geometry(), janela.rect())

    def caixa(self, logo=True):
        ctx = Contexto(self.banco)
        ctx.operador = ctx.acesso.operador(self.operador_adm())
        ctx.config.cadastrar_loja({"nome_fantasia": "Casa"})
        if logo:
            self.banco.executar("UPDATE loja SET logotipo = ?", (criar_logo(self.pasta),))
        janela = JanelaCaixa(ctx)
        self.janelas.append(janela)
        return janela

    def test_caixa_com_logotipo_ganha_papel_de_parede_e_selo_no_topo(self):
        janela = self.caixa()
        self.assertIsInstance(janela.marca_dagua, marca_dagua.MarcaDagua)
        self.assertIs(janela.marca_dagua.parentWidget(), janela.centralWidget())
        self.assertFalse(janela.logo_loja.pixmap().isNull())
        self.assertEqual(janela.logo_loja.objectName(), "logo_loja")

    def test_sem_logotipo_ou_com_a_opcao_desligada_o_caixa_fica_sem_marca(self):
        self.assertIsNone(self.caixa(logo=False).marca_dagua)
        self.banco.cfg_set("caixa_papel_de_parede", "N")
        self.assertIsNone(self.caixa().marca_dagua)

    def test_trocar_o_modo_refaz_a_marca_na_cor_do_tema(self):
        janela = self.caixa()
        escura = janela.marca_dagua.imagem.pixelColor(100, 50)
        self.banco.cfg_set("tema_visual", "claro")
        janela._aplicar_estilo()
        clara = janela.marca_dagua.imagem.pixelColor(100, 50)
        self.assertNotEqual(escura.red(), clara.red())
        self.assertIs(janela.marca_dagua.parentWidget(), janela.centralWidget())
