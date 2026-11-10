"""Logotipo da casa como papel de parede do caixa: uma marca d'água por cima da tela, que não recebe clique nem foco."""
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget

from src.core.erros import ErroNegocio
from src.core.identidade_visual import _imagem

OPACIDADE = 0.07            # discreta: aparece no fundo, não disputa com os números da venda
FRACAO_LARGURA = 0.46
FRACAO_ALTURA = 0.52


def silhueta(caminho, cor: QColor) -> QImage | None:
    """O desenho do logotipo em uma cor só, com o fundo transparente. O logotipo guardado tem fundo chapado (branco,
    ou a cor de fundo da arte): o que difere do fundo vira o desenho. Arquivo ausente ou inválido devolve None."""
    if not caminho:
        return None
    try:
        cinza = _imagem(caminho).convert("L")
    except ErroNegocio:
        return None
    from PIL import Image, ImageOps
    largura, altura = cinza.size
    borda = [cinza.getpixel(p) for p in ((0, 0), (largura - 1, 0), (0, altura - 1), (largura - 1, altura - 1),
                                         (largura // 2, 0), (largura // 2, altura - 1))]
    fundo_claro = sum(borda) / len(borda) >= 128
    alfa = ImageOps.invert(cinza) if fundo_claro else cinza          # fundo claro: o desenho é a parte escura
    alfa = ImageOps.autocontrast(alfa)
    if alfa.getextrema()[1] == 0:                                     # imagem lisa: não há desenho para mostrar
        return None
    pintada = Image.new("RGBA", cinza.size, (cor.red(), cor.green(), cor.blue(), 0))
    pintada.putalpha(alfa)
    dados = pintada.tobytes()
    return QImage(dados, largura, altura, largura * 4, QImage.Format.Format_RGBA8888).copy()


class MarcaDagua(QWidget):
    """Cobre a janela inteira e desenha o logotipo no centro, quase transparente."""

    def __init__(self, pai: QWidget, imagem: QImage, opacidade: float = OPACIDADE):
        super().__init__(pai)
        self.imagem, self.opacidade = imagem, opacidade
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.acompanhar()

    def acompanhar(self) -> None:
        """Cobre a janela dona inteira e fica por cima. A janela chama isto quando muda de tamanho."""
        self.setGeometry(self.parentWidget().rect())
        self.raise_()

    def area_do_desenho(self) -> QRect:
        tamanho = self.imagem.size()
        tamanho.scale(int(self.width() * FRACAO_LARGURA), int(self.height() * FRACAO_ALTURA),
                      Qt.AspectRatioMode.KeepAspectRatio)
        area = QRect(0, 0, tamanho.width(), tamanho.height())
        area.moveCenter(self.rect().center())
        return area

    def paintEvent(self, _evento):
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pintor.setOpacity(self.opacidade)
        pintor.drawImage(self.area_do_desenho(), self.imagem)
        pintor.end()


def aplicar(pai: QWidget, caminho, tema_claro: bool) -> MarcaDagua | None:
    """Cria a marca d'água sobre `pai` (ou None se não há logotipo válido). Tema escuro: desenho claro; claro: escuro."""
    imagem = silhueta(caminho, QColor("#1e2a3c") if tema_claro else QColor("#ffffff"))
    return MarcaDagua(pai, imagem) if imagem is not None else None
