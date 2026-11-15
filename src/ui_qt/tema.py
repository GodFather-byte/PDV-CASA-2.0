"""Identidade visual compartilhada pelas telas do piloto Qt."""
import atexit
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt
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
QCheckBox, QRadioButton { background: transparent; spacing: 7px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #405570; border-radius: 5px; background: #182437; }
QCheckBox::indicator:hover { border-color: #5ee2bb; }
QCheckBox::indicator:checked { background: #5ee2bb; border: 3px solid #187e65; }
QCheckBox::indicator:disabled { background: #1b2534; }
QProgressBar { background: #24364d; border: 0; border-radius: 5px; }
QProgressBar::chunk { background: #5ee2bb; border-radius: 5px; }
QLabel#secao { color: #5ee2bb; font-size: 14px; font-weight: 700; }
QLabel#aviso { color: #ffd28a; }
QPushButton { background: #24364d; border: 1px solid #405570; border-radius: 8px;
              padding: 6px 11px; min-height: 20px; font-weight: 600; }
QPushButton:hover { background: #304864; border-color: #5b7393; }
QPushButton:pressed { background: #1b2739; }
QToolBox QPushButton { text-align: left; font-weight: 400; padding: 4px 10px; min-height: 16px; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus,
QPlainTextEdit:focus, QTextEdit:focus { border: 2px solid #5ee2bb; }
QPushButton#primario { background: #187e65; border-color: #32b38e; font-weight: 700; }
QPushButton#primario:hover { background: #1f9476; }
QPushButton#perigo { background: transparent; color: #ff9b9b; border-color: #8a3b46; }
QPushButton#perigo:hover { background: #3a1f2a; }
QPushButton:disabled, QPushButton#primario:disabled, QPushButton#perigo:disabled {
              color: #8190a6; background: #1b2534; border-color: #324158; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit { background: #182437; border: 1px solid #405570;
                       border-radius: 7px; padding: 5px 8px; min-height: 20px; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover { border-color: #5b7393; }
QLineEdit:disabled, QComboBox:disabled { color: #8190a6; background: #1b2534; }
QPlainTextEdit, QTextEdit, QListWidget { background: #182437; border: 1px solid #324158; border-radius: 8px; }
QComboBox QAbstractItemView { background: #182437; border: 1px solid #405570; selection-background-color: #187e65;
                              outline: 0; padding: 4px; }
QTableWidget, QTableView { background: #182437; alternate-background-color: #1d2d43; border: 1px solid #324158;
               border-radius: 8px; gridline-color: #24364d; selection-background-color: #187e65;
               selection-color: #e6edf7; }
QTableView::item:hover { background: #24364d; }
QHeaderView { background: transparent; }
QHeaderView::section { background: #24364d; color: #e6edf7; padding: 6px 8px; border: 0;
                       border-right: 1px solid #324158; font-weight: 600; }
QHeaderView::section:vertical { color: #8190a6; font-weight: 400; padding: 2px 6px; border-right: 0; }
QTableCornerButton::section { background: #24364d; border: 0; }
QTabWidget::pane { border: 1px solid #324158; border-radius: 8px; top: -1px; }
QTabBar::tab { background: #1b2739; color: #afbdd1; padding: 7px 14px; margin-right: 2px;
               border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:hover { background: #24364d; color: #e6edf7; }
QTabBar::tab:selected { background: #187e65; color: #e6edf7; font-weight: 600; }
QGroupBox { border: 1px solid #324158; border-radius: 10px; margin-top: 12px; padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #5ee2bb; font-weight: 700; }
QScrollArea { border: 0; }
QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: #405570; border-radius: 4px; min-height: 32px; }
QScrollBar::handle:horizontal { background: #405570; border-radius: 4px; min-width: 32px; }
QScrollBar::handle:hover { background: #5b7393; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QToolTip { background: #24364d; color: #e6edf7; border: 1px solid #405570; border-radius: 6px; padding: 5px; }
QMenu { background: #1b2739; border: 1px solid #405570; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: #187e65; }
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
            "#1d2d43": "#eef1f5", "#5b7393": "#6f7f96", "#ff9b9b": "#a3222f", "#8a3b46": "#c9858d",
            "#3a1f2a": "#f6dfe1", "#1f9476": "#a9d8c3",
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
    # Cresce até o tamanho que o conteúdo pede (sizeHint): o tamanho fixo do código costuma ser menor que os campos
    # e as colunas, e a janela abria cortada, com rolagem de lado. Nunca encolhe o que o código pediu.
    desejado = janela.size().expandedTo(janela.sizeHint())
    janela.resize(min(desejado.width(), largura_max), min(desejado.height(), altura_max))
    ajustar_tabelas(janela)
    if type(janela).__module__.startswith("src."):
        realcar_botoes(janela)
    # Posição: centro da janela dona (ou da tela), sem passar das bordas.
    dona = janela.parentWidget().window() if janela.parentWidget() is not None else None
    base = dona.frameGeometry() if dona is not None and dona.isVisible() else area
    x = base.center().x() - janela.width() // 2
    y = base.center().y() - (janela.height() + RESERVA_ALTURA) // 2
    x = max(area.left() + RESERVA_LARGURA // 2, min(x, area.right() - janela.width() - RESERVA_LARGURA // 2 + 1))
    y = max(area.top() + RESERVA_ALTURA - 8, min(y, area.bottom() - janela.height() - 8 + 1))
    janela.move(x, y)


LIMITE_LINHAS_AJUSTE = 300
LARGURA_MAXIMA_COLUNA = 360


def ajustar_tabelas(janela) -> None:
    """Colunas do tamanho do cabeçalho e do conteúdo na primeira exibição, e a última ocupando a sobra.

    Só mexe em tabela que o código deixou no padrão (todas as colunas "Interactive"): a que já escolheu largura fixa,
    esticada ou pelo conteúdo fica como está. Tabela grande (mais de 300 linhas) mede só pelo cabeçalho, para não
    pesar."""
    from PySide6.QtWidgets import QHeaderView, QTableView
    for tabela in janela.findChildren(QTableView):
        cabecalho = tabela.horizontalHeader()
        modelo = tabela.model()
        if modelo is None or cabecalho.count() == 0 or tabela.property("_will_colunas"):
            continue
        if any(cabecalho.sectionResizeMode(i) != QHeaderView.ResizeMode.Interactive for i in range(cabecalho.count())):
            continue
        tabela.setProperty("_will_colunas", True)
        if modelo.rowCount() <= LIMITE_LINHAS_AJUSTE:
            tabela.resizeColumnsToContents()
        else:
            for i in range(cabecalho.count()):
                cabecalho.resizeSection(i, max(cabecalho.sectionSize(i), cabecalho.sectionSizeHint(i)))
        for i in range(cabecalho.count()):
            if cabecalho.sectionSize(i) > LARGURA_MAXIMA_COLUNA:
                cabecalho.resizeSection(i, LARGURA_MAXIMA_COLUNA)
        cabecalho.setStretchLastSection(True)
        if tabela.verticalHeader().defaultSectionSize() < 28:
            tabela.verticalHeader().setDefaultSectionSize(28)     # linhas mais altas: leitura e toque mais fáceis


PRIMARIOS = ("salvar", "gravar", "confirmar", "registrar", "aplicar", "incluir", "conferir e", "importar", "consultar")
PERIGOSOS = ("excluir", "remover", "recusar", "cancelar nota", "cancelar selecionad", "desinstalar", "liberar o número")
FECHAR = ("fechar", "sair")


def _texto_botao(botao) -> str:
    return botao.text().replace("&", "").strip().casefold()


def _layout_com(layout, widget):
    """O layout (dentro de `layout`) que tem `widget` como item direto, e o índice dele."""
    if layout is None:
        return None, -1
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is widget:
            return layout, i
        achado = _layout_com(item.layout(), widget)
        if achado[0] is not None:
            return achado
    return None, -1


def realcar_botoes(janela) -> None:
    """Hierarquia visual sem mexer em cada tela: a ação principal fica verde (se a tela não escolheu uma), as que
    apagam ficam em vermelho discreto, e o "Fechar" sozinho numa linha deixa de esticar de ponta a ponta."""
    from PySide6.QtWidgets import QBoxLayout, QPushButton
    botoes = [b for b in janela.findChildren(QPushButton) if not b.objectName()]
    if not any(b.objectName() == "primario" for b in janela.findChildren(QPushButton)):
        for prefixo in PRIMARIOS:
            principal = next((b for b in botoes if _texto_botao(b).startswith(prefixo)), None)
            if principal is not None:
                principal.setObjectName("primario")
                break
    for botao in botoes:
        texto = _texto_botao(botao)
        if not botao.objectName() and texto.startswith(PERIGOSOS):
            botao.setObjectName("perigo")
        if texto.startswith(FECHAR) and botao.parentWidget() is not None:
            layout, _ = _layout_com(botao.parentWidget().layout(), botao)
            if isinstance(layout, QBoxLayout) and layout.direction() in (QBoxLayout.TopToBottom, QBoxLayout.BottomToTop):
                botao.setMinimumWidth(max(botao.minimumWidth(), 130))
                layout.setAlignment(botao, Qt.AlignRight)
        botao.style().unpolish(botao)
        botao.style().polish(botao)


_ajuste = {"ativo": False, "ligado": False}


def ajustar_na_primeira_exibicao(janela) -> bool:
    """Ajusta a janela uma vez só; depois disso vale o tamanho e o lugar que o operador escolher."""
    if (janela is None or not janela.isWindow() or janela.property(_MARCA_AJUSTE)
            or janela.windowType() not in (Qt.WindowType.Window, Qt.WindowType.Dialog)):
        return False
    janela.setProperty(_MARCA_AJUSTE, True)
    ajustar_janela(janela)
    return True


def _foco_mudou(janela_do_sistema=None) -> None:
    """Toda janela ou diálogo que recebe o foco pela primeira vez passa pelo ajuste (inclusive os abertos com exec)."""
    if not _ajuste["ativo"] or janela_do_sistema is None:
        return
    try:
        for janela in QApplication.topLevelWidgets():
            if janela.windowHandle() is janela_do_sistema or janela.windowHandle() == janela_do_sistema:
                ajustar_na_primeira_exibicao(janela)
                return
    except RuntimeError:                    # janela já destruída pelo Qt
        pass


def _desligar_ajuste() -> None:
    """No encerramento o Qt ainda emite mudanças de foco; sem desligar, chamaria o Python já finalizado."""
    _ajuste["ativo"] = False
    aplicacao = QApplication.instance()
    if _ajuste["ligado"] and aplicacao is not None:
        try:
            aplicacao.focusWindowChanged.disconnect(_foco_mudou)
        except (RuntimeError, TypeError):
            pass
    _ajuste["ligado"] = False


def encerrar_janelas_restantes() -> None:
    """Destrói as janelas que sobraram enquanto o QApplication ainda existe.

    Janela viva quando o Python finaliza é destruída fora de ordem (depois da aplicação) e derruba o processo na
    saída. O PDV fecha as suas em `App.finalizar`; isto é a rede de proteção para o que escapar, inclusive janelas
    que um teste deixou abertas.
    """
    _desligar_ajuste()
    aplicacao = QApplication.instance()
    if aplicacao is None:
        return
    try:
        for janela in list(aplicacao.topLevelWidgets()):
            janela.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    except RuntimeError:                    # aplicação já em destruição: não há mais o que fazer
        pass


def instalar_ajuste_de_janelas(aplicacao: QApplication, forcar: bool = False) -> None:
    """Liga o ajuste automático pela mudança de foco (um sinal por janela aberta, sem filtrar cada evento do caixa).
    Na plataforma "offscreen" não há monitor de verdade (a tela é fictícia, 800x800), então só entra se `forcar` pedir."""
    if not _ajuste["ligado"]:
        aplicacao.focusWindowChanged.connect(_foco_mudou)
        atexit.register(encerrar_janelas_restantes)
        _ajuste["ligado"] = True
    _ajuste["ativo"] = forcar or QGuiApplication.platformName() != "offscreen"
