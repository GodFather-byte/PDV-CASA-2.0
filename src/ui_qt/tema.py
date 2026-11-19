"""Identidade visual compartilhada pelas telas do piloto Qt."""
import atexit
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QRect, QSize, Qt
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLayout, QScrollArea, QVBoxLayout, QWidget


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
              padding: 5px 10px; min-height: 20px; }
QPushButton:hover { background: #304864; border-color: #5b7393; }
QPushButton:pressed { background: #1b2739; }
QToolBox QPushButton { text-align: left; font-weight: 400; padding: 4px 10px; min-height: 16px; }
QDialogButtonBox QPushButton { min-width: 64px; }
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


class LinhaFluida(QLayout):
    """Linha de botões que continua na linha de baixo quando a janela é estreita.

    No lugar do QHBoxLayout em fileiras compridas: com ele a janela era obrigada a ter a largura de todos os botões
    somados, e num monitor de 1024 pontos a ponta da fileira ficava para fora. Aqui a largura mínima é a do botão
    mais largo; na tela larga tudo continua numa linha só.

    `preencher`: os botões dividem a sobra da linha (como no QHBoxLayout); a última linha de uma fileira quebrada
    fica no tamanho natural. Widget adicionado com `addWidget(w, 1)` fica sozinho com a sobra da linha dele."""

    def __init__(self, preencher: bool = True, espaco: int = 6):
        super().__init__()
        self._itens: list = []
        self._elasticos: list = []
        self._preencher = preencher
        self.setSpacing(espaco)
        self.setContentsMargins(0, 0, 0, 0)

    def addWidget(self, widget, elastico: int = 0) -> None:
        super().addWidget(widget)
        if elastico:
            self._elasticos.append(widget)

    def addItem(self, item) -> None:
        self._itens.append(item)

    def count(self) -> int:
        return len(self._itens)

    def itemAt(self, indice: int):
        return self._itens[indice] if 0 <= indice < len(self._itens) else None

    def takeAt(self, indice: int):
        return self._itens.pop(indice) if 0 <= indice < len(self._itens) else None

    def expandingDirections(self):
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, largura: int) -> int:
        return self._distribuir(QRect(0, 0, largura, 0), aplicar=False)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._distribuir(rect, aplicar=True)

    def _visiveis(self) -> list:
        return [item for item in self._itens if item.widget() is None or not item.widget().isHidden()]

    def sizeHint(self) -> QSize:
        """Tudo numa linha só: é o que a janela pede quando a tela dá."""
        itens, margens = self._visiveis(), self.contentsMargins()
        largura = sum(item.sizeHint().width() for item in itens) + self.spacing() * max(0, len(itens) - 1)
        altura = max((item.sizeHint().height() for item in itens), default=0)
        return QSize(largura + margens.left() + margens.right(), altura + margens.top() + margens.bottom())

    def minimumSize(self) -> QSize:
        itens, margens = self._visiveis(), self.contentsMargins()
        largura = max((item.minimumSize().width() for item in itens), default=0)
        altura = max((item.minimumSize().height() for item in itens), default=0)
        return QSize(largura + margens.left() + margens.right(), altura + margens.top() + margens.bottom())

    def _distribuir(self, rect, aplicar: bool) -> int:
        """Reparte os itens em linhas dentro de `rect` e devolve a altura total. Só posiciona se `aplicar`."""
        margens, espaco = self.contentsMargins(), self.spacing()
        area = rect.adjusted(margens.left(), margens.top(), -margens.right(), -margens.bottom())
        linhas, atual, usado = [], [], 0
        for item in self._visiveis():
            largura = item.sizeHint().width()
            if atual and usado + espaco + largura > area.width():
                linhas.append(atual)
                atual, usado = [], 0
            usado += largura + (espaco if atual else 0)
            atual.append(item)
        if atual:
            linhas.append(atual)
        y = area.y()
        for numero, linha in enumerate(linhas):
            altura = max(item.sizeHint().height() for item in linha)
            if aplicar:
                natural = sum(item.sizeHint().width() for item in linha) + espaco * (len(linha) - 1)
                sobra = max(0, area.width() - natural)
                elasticos = [item for item in linha if item.widget() in self._elasticos]
                ultima_de_varias = len(linhas) > 1 and numero == len(linhas) - 1
                if elasticos:
                    ganham = elasticos
                elif self._preencher and not ultima_de_varias:
                    ganham = linha
                else:
                    ganham = []
                x = area.x()
                for item in linha:
                    largura = min(item.sizeHint().width(), area.width())
                    if item in ganham:
                        largura += sobra // len(ganham)
                    item.setGeometry(QRect(x, y, largura, altura))
                    x += largura + espaco
            y += altura + espaco
        return y - (espaco if linhas else 0) - rect.y() + margens.bottom()


# Reserva para a moldura do Windows: a barra de título e as bordas não entram no tamanho pedido.
RESERVA_LARGURA = 16
RESERVA_ALTURA = 40
_MARCA_AJUSTE = "_will_janela_ajustada"


def _area_util(janela):
    tela = janela.screen() or QGuiApplication.primaryScreen()
    return tela.availableGeometry() if tela is not None else None


def _rolar_conteudo(janela, largura_max: int) -> None:
    """Conteúdo maior que a tela ganha rolagem em vez de ficar cortado."""
    antigo = janela.layout()
    if antigo is None or getattr(janela, "_will_rolagem", None) is not None:
        return
    miolo = QWidget()
    miolo.setLayout(antigo)                 # o Qt transfere o layout e os campos para o miolo
    rolagem = QScrollArea()
    rolagem.setWidgetResizable(True)
    rolagem.setWidget(miolo)
    # A barra de rolagem para baixo ocupa largura: sem contá-la, o conteúdo passava alguns pontos e rolava de lado também.
    precisa = (miolo.minimumSizeHint().width() + rolagem.verticalScrollBar().sizeHint().width()
               + 2 * rolagem.frameWidth())
    rolagem.setMinimumWidth(min(precisa, largura_max))
    externo = QVBoxLayout(janela)
    externo.setContentsMargins(0, 0, 0, 0)
    externo.addWidget(rolagem)
    janela._will_rolagem = rolagem


def _aliviar_largura(janela, largura_max: int) -> None:
    """Janela mais larga que a tela por causa do conteúdo: a lista de opções deixa de exigir a largura do seu item
    mais comprido (o item aparece com reticências; aberta, a lista mostra inteiro) e o texto corrido passa a quebrar
    em linhas."""
    from PySide6.QtWidgets import QComboBox
    politica = QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    for lista in janela.findChildren(QComboBox):
        if lista.sizeAdjustPolicy() != politica:
            lista.setSizeAdjustPolicy(politica)
            lista.setMinimumContentsLength(max(lista.minimumContentsLength(), 10))
            # O Qt guarda o mínimo já calculado da lista e não o refaz ao trocar a política; o aviso de estilo refaz.
            QApplication.sendEvent(lista, QEvent(QEvent.Type.StyleChange))
    for rotulo in janela.findChildren(QLabel):
        if not rotulo.wordWrap() and rotulo.pixmap().isNull() and rotulo.sizeHint().width() > largura_max // 2:
            rotulo.setWordWrap(True)
    if janela.layout() is not None:
        janela.layout().invalidate()
        janela.layout().activate()          # com a janela já na tela, o mínimo antigo só sai ao refazer o layout


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
    if minimo.width() > largura_max and type(janela).__module__.startswith("src."):
        _aliviar_largura(janela, largura_max)           # o que pode ceder cede antes de a janela rolar de lado
        minimo = janela.minimumSizeHint().expandedTo(janela.minimumSize())
    if minimo.width() > largura_max or minimo.height() > altura_max:
        if isinstance(janela, QDialog) and type(janela).__module__.startswith("src."):
            _rolar_conteudo(janela, largura_max)
        janela.setMinimumSize(min(minimo.width(), largura_max), min(minimo.height(), altura_max))
    # Cresce até o tamanho que o conteúdo pede (sizeHint): o tamanho fixo do código costuma ser menor que os campos
    # e as colunas, e a janela abria cortada, com rolagem de lado. Nunca encolhe o que o código pediu.
    desejado = janela.size().expandedTo(janela.sizeHint())
    janela.resize(min(desejado.width(), largura_max), min(desejado.height(), altura_max))
    ajustar_tabelas(janela)
    if janela.isVisible():                  # só com a janela montada dá para medir o que rola de lado
        tirar_rolagem_de_lado(janela, largura_max)
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


PISO_COLUNA = 120


def _largura_pedida(tabela) -> int:
    """A largura que as colunas pedem. A última coluna, quando é a que estica, não é medida pelo Qt (fica com 100
    pontos se não sobra espaço): aqui ela entra pelo que o título e os dados precisam."""
    cabecalho = tabela.horizontalHeader()
    total = cabecalho.length()
    if cabecalho.stretchLastSection():
        visiveis = [cabecalho.logicalIndex(v) for v in range(cabecalho.count())
                    if not cabecalho.isSectionHidden(cabecalho.logicalIndex(v))]
        if visiveis:
            ultima = visiveis[-1]
            precisa = max(cabecalho.sectionSizeHint(ultima), tabela.sizeHintForColumn(ultima))
            total += max(0, precisa - cabecalho.sectionSize(ultima))
    return total


def _falta_de_largura(janela) -> int:
    """Quantos pontos de largura faltam para nenhuma tabela nem formulário da janela rolar de lado. Olha o que está
    à vista e também as outras abas (que ainda não foram montadas: aí vale a largura que o conteúdo pede)."""
    from PySide6.QtWidgets import QTabWidget, QTableView
    desligada = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    falta = 0
    for tabela in janela.findChildren(QTableView):
        if tabela.isVisibleTo(janela) and tabela.horizontalScrollBarPolicy() != desligada:
            falta = max(falta, _largura_pedida(tabela) - tabela.viewport().width())
    for area in janela.findChildren(QScrollArea):
        if area.isVisibleTo(janela) and area.horizontalScrollBarPolicy() != desligada:
            falta = max(falta, area.horizontalScrollBar().maximum())
    for abas in janela.findChildren(QTabWidget):
        atual = abas.currentWidget()
        if atual is None or not abas.isVisibleTo(janela):
            continue
        for i in range(abas.count()):
            pagina = abas.widget(i)
            if pagina is atual or not isinstance(pagina, QScrollArea) or pagina.widget() is None \
                    or pagina.horizontalScrollBarPolicy() == desligada:
                continue
            precisa = (pagina.widget().minimumSizeHint().width() + 2 * pagina.frameWidth()
                       + pagina.verticalScrollBar().sizeHint().width())
            falta = max(falta, precisa - atual.width())
    return falta


LARGURAS_TITULO = (110, 80)             # primeiro só os títulos bem largos; se a tabela ainda não couber, os médios
LINHAS_TITULO = 3


def quebrar_titulo(titulo: str, medir, largura_dados: int, largura_titulo: int = LARGURAS_TITULO[0]) -> str:
    """Título de coluna bem mais largo que os dados (ex.: "Mostrar no cardápio digital" sobre um S/N) vira duas ou
    três linhas equilibradas. `medir(texto)` devolve a largura em pontos."""
    palavras = titulo.split()
    alvo = max(largura_dados, largura_titulo)
    inteiro = medir(titulo)
    if "\n" in titulo or len(palavras) < 2 or inteiro <= alvo:
        return titulo
    linhas_pedidas = min(LINHAS_TITULO, len(palavras), -(-inteiro // alvo))
    limite = max(alvo, -(-inteiro // linhas_pedidas))
    linhas, atual = [], ""
    for palavra in palavras:
        tentativa = f"{atual} {palavra}".strip()
        if atual and medir(tentativa) > limite and len(linhas) < linhas_pedidas - 1:
            linhas.append(atual)
            atual = palavra
        else:
            atual = tentativa
    linhas.append(atual)
    return "\n".join(linhas)


def _quebrar_titulos(tabela) -> None:
    """Quebra em linhas os títulos mais largos que os dados da coluna, só até a tabela caber. O título inteiro
    continua na dica (passar o mouse)."""
    cabecalho, modelo = tabela.horizontalHeader(), tabela.model()
    if modelo is None or tabela.property("_will_titulos"):
        return
    tabela.setProperty("_will_titulos", True)
    medida = cabecalho.fontMetrics()
    originais = {i: modelo.headerData(i, Qt.Orientation.Horizontal) for i in range(cabecalho.count())
                 if not cabecalho.isSectionHidden(i)}
    for largura_titulo in LARGURAS_TITULO:
        if _largura_pedida(tabela) <= tabela.viewport().width():
            return
        for i, titulo in originais.items():
            if not isinstance(titulo, str):
                continue
            quebrado = quebrar_titulo(titulo, medida.horizontalAdvance, tabela.sizeHintForColumn(i), largura_titulo)
            if quebrado != titulo and modelo.setHeaderData(i, Qt.Orientation.Horizontal, quebrado):
                modelo.setHeaderData(i, Qt.Orientation.Horizontal, titulo, Qt.ItemDataRole.ToolTipRole)


def _encolher_colunas(tabela) -> None:
    """Tabela que ainda não cabe na largura. Nas colunas de largura livre, as mais largas cedem na mesma proporção
    (o texto ganha reticências), nunca abaixo do título nem de `PISO_COLUNA`. Na tabela que se mede sozinha pelo
    conteúdo, a coluna mais larga (o nome) passa a ocupar o que sobra, desde que não perca mais da metade; se uma só
    não basta, as duas ou três mais largas dividem a sobra."""
    from PySide6.QtWidgets import QHeaderView
    cabecalho = tabela.horizontalHeader()
    excesso = _largura_pedida(tabela) - tabela.viewport().width()
    if excesso <= 0:
        return
    visiveis = [i for i in range(cabecalho.count()) if not cabecalho.isSectionHidden(i)]
    modos = {cabecalho.sectionResizeMode(i) for i in visiveis}
    if modos == {QHeaderView.ResizeMode.ResizeToContents}:
        largas = sorted(visiveis, key=cabecalho.sectionSize, reverse=True)
        cabecalho.setStretchLastSection(False)          # a última passa a ter o tamanho do que mostra (título inteiro)
        for quantas in (1, 2, 3):                       # uma coluna elástica; se não bastar, as duas ou três mais largas
            escolhidas = largas[:quantas]
            cada = (sum(cabecalho.sectionSize(i) for i in escolhidas) - excesso) / len(escolhidas)
            if cada >= max(PISO_COLUNA, cabecalho.sectionSize(escolhidas[0]) / 2):
                for i in escolhidas:
                    cabecalho.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
                break
        else:                                           # não coube: fica a rolagem, mas com todo título inteiro
            cabecalho.resizeSections(QHeaderView.ResizeMode.ResizeToContents)
        return
    if not tabela.property("_will_colunas"):
        return
    folgas = {}
    for i in visiveis:
        if cabecalho.sectionResizeMode(i) != QHeaderView.ResizeMode.Interactive:
            continue
        piso = max(PISO_COLUNA, cabecalho.sectionSizeHint(i))
        if cabecalho.sectionSize(i) > piso:
            folgas[i] = cabecalho.sectionSize(i) - piso
    total = sum(folgas.values())
    if total <= 0:
        return
    fator = min(1.0, excesso / total)
    for i, folga in folgas.items():
        cabecalho.resizeSection(i, cabecalho.sectionSize(i) - int(folga * fator + 0.999))


def _tabelas_a_vista(janela) -> list:
    from PySide6.QtWidgets import QTableView
    return [tabela for tabela in janela.findChildren(QTableView)
            if tabela.isVisibleTo(janela) and tabela.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff]


def tirar_rolagem_de_lado(janela, largura_max: int) -> None:
    """A lista e o formulário abrem sem rolar de lado quando a tela dá: títulos de coluna largos demais quebram em
    linhas, a janela alarga até o limite da tela e, se ainda faltar, as colunas mais largas cedem. Rolagem para
    baixo continua normal."""
    for tabela in _tabelas_a_vista(janela):
        if _largura_pedida(tabela) > tabela.viewport().width():
            _quebrar_titulos(tabela)
    for _ in range(3):                      # o layout pode dividir a largura nova com outros painéis: confere de novo
        falta = _falta_de_largura(janela)
        if falta <= 0 or janela.width() >= largura_max:
            break
        janela.resize(min(janela.width() + falta, largura_max), janela.height())
    for tabela in _tabelas_a_vista(janela):
        _encolher_colunas(tabela)


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
