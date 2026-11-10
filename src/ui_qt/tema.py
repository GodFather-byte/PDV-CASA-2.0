"""Identidade visual compartilhada pelas telas do piloto Qt."""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QScrollArea, QVBoxLayout, QWidget


ESTILO = """
QWidget { background: #101827; color: #e6edf7; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog { background: #101827; }
QFrame#cartao { background: #1b2739; border: 1px solid #324158; border-radius: 12px; }
QLabel { background: transparent; }
QLabel#titulo { font-size: 22px; font-weight: 700; }
QLabel#marca { color: #5ee2bb; font-size: 24px; font-weight: 800; }
QLabel#suave { color: #afbdd1; }
QWidget#linha { background: transparent; }
QCheckBox { background: transparent; spacing: 6px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #405570; border-radius: 4px; background: #182437; }
QCheckBox::indicator:checked { background: #5ee2bb; border: 3px solid #187e65; }
QCheckBox::indicator:disabled { background: #1b2534; }
QProgressBar { background: #24364d; border: 0; border-radius: 5px; }
QProgressBar::chunk { background: #5ee2bb; border-radius: 5px; }
QLabel#secao { color: #5ee2bb; font-size: 14px; font-weight: 700; }
QLabel#aviso { color: #ffd28a; }
QPushButton { background: #24364d; border: 1px solid #405570; border-radius: 7px;
              padding: 5px 10px; text-align: left; }
QPushButton:hover { background: #304864; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus { border: 2px solid #5ee2bb; }
QPushButton#primario { background: #187e65; border-color: #32b38e; font-weight: 700; }
QPushButton:disabled { color: #8190a6; background: #1b2534; }
QLineEdit, QComboBox { background: #182437; border: 1px solid #405570;
                       border-radius: 6px; padding: 5px; min-height: 20px; }
QComboBox QAbstractItemView { background: #182437; selection-background-color: #187e65; }
QTableWidget { background: #182437; alternate-background-color: #1d2d43;
               gridline-color: #324158; selection-background-color: #187e65; }
QHeaderView::section { background: #24364d; color: #e6edf7; padding: 5px; border: 0; }
QTabWidget::pane { border: 1px solid #324158; }
QTabBar::tab { background: #24364d; padding: 6px; }
QTabBar::tab:selected { background: #187e65; }
QScrollArea { border: 0; }
QFrame#kpi { background: #1b2739; border: 1px solid #32b38e; border-radius: 12px; }
QLabel#kpi_valor { font-size: 24px; font-weight: 800; color: #5ee2bb; }
QLabel#kpi_alerta { font-size: 24px; font-weight: 800; color: #ffd28a; }
"""


def aplicar(aplicacao: QApplication, aparencia: str = "escuro") -> None:
    # O plugin offscreen do Windows não enumera fontes do sistema por conta própria.
    if sys.platform == "win32" and "Segoe UI" not in QFontDatabase.families():
        pasta = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for nome in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
            caminho = pasta / nome
            if caminho.is_file():
                QFontDatabase.addApplicationFont(str(caminho))
    aplicacao.setStyle("Fusion")
    estilo = ESTILO
    if aparencia == "claro":
        # Claro confortável: fundo cinza-azulado suave e cartões em off-white (nada de branco puro em áreas grandes),
        # texto azul-grafite em vez de preto e bordas discretas, para cansar menos a vista em turnos longos.
        cores = {
            "#101827": "#e8ecf1", "#e6edf7": "#1e2a3c", "#1b2739": "#f5f7fa",
            "#324158": "#a9b6c7", "#5ee2bb": "#0b6b53", "#afbdd1": "#4d5c74",
            "#ffd28a": "#7d4b00", "#24364d": "#dde4ed", "#405570": "#8e9db2",
            "#304864": "#b9c6d8", "#187e65": "#bfe3d3", "#32b38e": "#2f9a7c",
            "#8190a6": "#66748a", "#1b2534": "#dfe4eb", "#182437": "#fbfcfd",
            "#1d2d43": "#eef1f5",
        }
        for original, nova in cores.items():
            estilo = estilo.replace(original, nova)
    aplicacao.setStyleSheet(estilo)
    instalar_ajuste_de_janelas(aplicacao)
    from src.core import edicao
    ed = edicao.atual()
    aplicacao.setApplicationName(f"{ed.nome}{ed.sufixo_titulo}")


def texto(conteudo: str, nome: str = "", quebra: bool = True) -> QLabel:
    rotulo = QLabel(conteudo)
    rotulo.setObjectName(nome)
    rotulo.setWordWrap(quebra)
    return rotulo


# Reserva para a moldura do Windows: a barra de título e as bordas não entram no tamanho pedido.
RESERVA_LARGURA = 16
RESERVA_ALTURA = 40
_MARCA_AJUSTE = "_will_janela_ajustada"


def _area_util(janela):
    tela = janela.screen() or QGuiApplication.primaryScreen()
    return tela.availableGeometry() if tela is not None else None


def _rolar_conteudo(janela) -> None:
    """Conteúdo maior que a tela ganha rolagem em vez de ficar cortado."""
    antigo = janela.layout()
    if antigo is None or getattr(janela, "_will_rolagem", None) is not None:
        return
    miolo = QWidget()
    miolo.setLayout(antigo)                 # o Qt transfere o layout e os campos para o miolo
    rolagem = QScrollArea()
    rolagem.setWidgetResizable(True)
    rolagem.setWidget(miolo)
    externo = QVBoxLayout(janela)
    externo.setContentsMargins(0, 0, 0, 0)
    externo.addWidget(rolagem)
    janela._will_rolagem = rolagem


def ajustar_janela(janela) -> None:
    """Abre a janela inteira dentro da área útil: limita o tamanho, rola o que não cabe e centraliza.

    Vale para qualquer resolução (1024x600, 1366x768) e para a escala de 125% ou 150% do Windows.
    """
    if janela.isMaximized() or janela.isFullScreen():
        return
    area = _area_util(janela)
    if area is None:
        return
    largura_max = max(320, area.width() - RESERVA_LARGURA)
    altura_max = max(240, area.height() - RESERVA_ALTURA)
    minimo = janela.minimumSizeHint().expandedTo(janela.minimumSize())
    if minimo.width() > largura_max or minimo.height() > altura_max:
        if isinstance(janela, QDialog) and type(janela).__module__.startswith("src."):
            _rolar_conteudo(janela)
        janela.setMinimumSize(min(minimo.width(), largura_max), min(minimo.height(), altura_max))
    janela.resize(min(janela.width(), largura_max), min(janela.height(), altura_max))
    # Posição: centro da janela dona (ou da tela), sem passar das bordas.
    dona = janela.parentWidget().window() if janela.parentWidget() is not None else None
    base = dona.frameGeometry() if dona is not None and dona.isVisible() else area
    x = base.center().x() - janela.width() // 2
    y = base.center().y() - (janela.height() + RESERVA_ALTURA) // 2
    x = max(area.left() + RESERVA_LARGURA // 2, min(x, area.right() - janela.width() - RESERVA_LARGURA // 2 + 1))
    y = max(area.top() + RESERVA_ALTURA - 8, min(y, area.bottom() - janela.height() - 8 + 1))
    janela.move(x, y)


class _AjusteDeJanelas(QObject):
    """Toda janela ou diálogo passa por `ajustar_janela` na primeira vez que aparece."""

    ativo = True

    def eventFilter(self, objeto, evento):
        if (self.ativo and evento.type() == QEvent.Type.Show and isinstance(objeto, QWidget) and objeto.isWindow()
                and objeto.windowType() in (Qt.WindowType.Window, Qt.WindowType.Dialog)
                and not objeto.property(_MARCA_AJUSTE)):
            objeto.setProperty(_MARCA_AJUSTE, True)
            try:
                ajustar_janela(objeto)
            except RuntimeError:            # janela já destruída pelo Qt
                pass
        return False


def instalar_ajuste_de_janelas(aplicacao: QApplication, forcar: bool = False) -> None:
    """Liga o ajuste automático. Na plataforma "offscreen" não há monitor de verdade (a tela é fictícia,
    800x800), então o ajuste só entra se `forcar` pedir."""
    filtro = getattr(aplicacao, "_will_ajuste_janelas", None)
    if filtro is None:
        filtro = aplicacao._will_ajuste_janelas = _AjusteDeJanelas(aplicacao)
        aplicacao.installEventFilter(filtro)
    filtro.ativo = forcar or QGuiApplication.platformName() != "offscreen"
