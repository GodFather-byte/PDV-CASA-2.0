"""Identidade visual compartilhada pelas telas do piloto Qt."""
import os
import sys
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel


ESTILO = """
QWidget { background: #101827; color: #e6edf7; font-family: 'Segoe UI'; font-size: 14px; }
QMainWindow, QDialog { background: #101827; }
QFrame#cartao { background: #1b2739; border: 1px solid #324158; border-radius: 12px; }
QLabel { background: transparent; }
QLabel#titulo { font-size: 28px; font-weight: 700; }
QLabel#marca { color: #5ee2bb; font-size: 24px; font-weight: 800; }
QLabel#suave { color: #afbdd1; }
QLabel#aviso { color: #ffd28a; }
QPushButton { background: #24364d; border: 1px solid #405570; border-radius: 7px;
              padding: 11px 18px; text-align: left; }
QPushButton:hover { background: #304864; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus { border: 2px solid #5ee2bb; }
QPushButton#primario { background: #187e65; border-color: #32b38e; font-weight: 700; }
QPushButton:disabled { color: #8190a6; background: #1b2534; }
QLineEdit, QComboBox { background: #182437; border: 1px solid #405570;
                       border-radius: 6px; padding: 9px; min-height: 20px; }
QComboBox QAbstractItemView { background: #182437; selection-background-color: #187e65; }
QTableWidget { background: #182437; alternate-background-color: #1d2d43;
               gridline-color: #324158; selection-background-color: #187e65; }
QHeaderView::section { background: #24364d; color: #e6edf7; padding: 9px; border: 0; }
QTabWidget::pane { border: 1px solid #324158; }
QTabBar::tab { background: #24364d; padding: 10px; }
QTabBar::tab:selected { background: #187e65; }
QScrollArea { border: 0; }
QFrame#kpi { background: #1b2739; border: 1px solid #32b38e; border-radius: 12px; }
QLabel#kpi_valor { font-size: 30px; font-weight: 800; color: #5ee2bb; }
QLabel#kpi_alerta { font-size: 30px; font-weight: 800; color: #ffd28a; }
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
            "#324158": "#c8d1dd", "#5ee2bb": "#0b6b53", "#afbdd1": "#4d5c74",
            "#ffd28a": "#7d4b00", "#24364d": "#dde4ed", "#405570": "#b4c0cf",
            "#304864": "#cfd9e6", "#187e65": "#bfe3d3", "#32b38e": "#2f9a7c",
            "#8190a6": "#66748a", "#1b2534": "#dfe4eb", "#182437": "#fbfcfd",
            "#1d2d43": "#eef1f5",
        }
        for original, nova in cores.items():
            estilo = estilo.replace(original, nova)
    aplicacao.setStyleSheet(estilo)
    aplicacao.setApplicationName("WillPDV • Qt piloto")


def texto(conteudo: str, nome: str = "", quebra: bool = True) -> QLabel:
    rotulo = QLabel(conteudo)
    rotulo.setObjectName(nome)
    rotulo.setWordWrap(quebra)
    return rotulo
