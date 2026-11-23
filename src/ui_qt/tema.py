"""Identidade visual compartilhada pelas telas do piloto Qt."""
import atexit
import os
import sys
from pathlib import Path
from string import Template

from PySide6.QtCore import QCoreApplication, QEvent, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QLabel, QLayout, QScrollArea, QVBoxLayout, QWidget


# Cores por função; o mesmo componente recebe a mesma hierarquia nos dois modos.
_CORES = {
    # função                 escuro      claro
    "fundo":               ("#101c20", "#f3f3ed"),
    "painel":              ("#192a2e", "#fffefa"),
    "campo":               ("#132226", "#ffffff"),
    "controle":            ("#24373b", "#f0f2ec"),
    "sobre":               ("#30494c", "#e2e9e2"),
    "borda":               ("#34494c", "#c5d0c8"),
    "borda_forte":         ("#587174", "#889e96"),
    "texto":               ("#edf5f1", "#172923"),
    "suave":               ("#b0c4c0", "#50645d"),
    "acao":                ("#55dfb0", "#11694f"),
    "sobre_acao":          ("#85eac5", "#0c5842"),
    "texto_acao":          ("#0a3026", "#ffffff"),
    "destaque":            ("#69e3b8", "#11694f"),
    "selecao":             ("#235a4c", "#c8e9d8"),
    "texto_selecao":       ("#e3fff1", "#103d30"),
    "linha_par":           ("#1a2b2e", "#f3f6f1"),
    "inativo":             ("#93a5a3", "#617069"),
    "fundo_inativo":       ("#202e32", "#e7ebe5"),
    "alerta":              ("#ffcc86", "#85490b"),
    "perigo":              ("#ffa8a5", "#9c302e"),
    "borda_perigo":        ("#965753", "#c39189"),
    "fundo_perigo":        ("#442b2b", "#f9e5dd"),
}

_FOLHA = Template("""
QWidget { background: $fundo; color: $texto; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
QMainWindow, QDialog { background: $fundo; }
QFrame#cartao, QFrame#kpi, QFrame#entrada_formulario {
    background: $painel; border: 1px solid $borda; border-radius: 12px; }
QFrame#kpi[financeiro="true"] { border-color: $destaque; }
QLabel, QCheckBox, QRadioButton, QWidget#linha { background: transparent; }
QLabel#titulo, QLabel#titulo_painel { font-weight: 700; font-size: 22px; }
QLabel#titulo_painel { font-size: 26px; }
QLabel#marca { color: $destaque; font-size: 22px; font-weight: 800; }
QLabel#suave, QLabel#linha_porteiro, QLabel[tom="suave"] { color: $suave; }
QLabel#secao, QLabel#subtitulo { color: $texto; font-size: 15px; font-weight: 700; }
QLabel#legenda { color: $suave; font-size: 12px; font-weight: 600; }
QLabel[tom="sucesso"] { color: $destaque; }
QLabel[tom="perigo"] { color: $perigo; }
QLabel#aviso, QLabel[tom="alerta"] { color: $alerta; }
QLabel#kpi_valor, QLabel#kpi_alerta { font-size: 24px; font-weight: 700; color: $destaque; }
QLabel#kpi_alerta { color: $alerta; }
QLabel#foto_titulo { color: #ffffff; font-size: 29px; font-weight: 700; }
QLabel#foto_marca { color: #ffffff; font-size: 19px; font-weight: 800; }
QLabel#foto_detalhe { color: #ddf6e9; font-size: 13px; font-weight: 600; }
QLabel#foto_aviso { color: #ffe3b5; font-size: 12px; }
QCheckBox, QRadioButton { spacing: 7px; }
QCheckBox::indicator, QRadioButton::indicator { width: 17px; height: 17px; }
QProgressBar { background: $controle; border: 0; border-radius: 4px; }
QProgressBar::chunk { background: $acao; border-radius: 4px; }
QPushButton { background: $controle; color: $texto; border: 1px solid $borda; border-radius: 7px;
              padding: 5px 10px; min-height: 20px; }
QPushButton:hover { background: $sobre; border-color: $borda_forte; }
QPushButton:pressed { background: $selecao; }
QPushButton#primario, QPushButton#tutorial_novo, QPushButton#tutorial_salvar {
    background: $acao; color: $texto_acao; border-color: $acao; font-weight: 700; }
QPushButton#primario:hover, QPushButton#tutorial_novo:hover, QPushButton#tutorial_salvar:hover {
    background: $sobre_acao; border-color: $sobre_acao; }
QPushButton#primario:pressed, QPushButton#tutorial_novo:pressed, QPushButton#tutorial_salvar:pressed {
    background: $selecao; color: $texto_selecao; border-color: $destaque; }
QPushButton#perigo { background: transparent; color: $perigo; border-color: $borda_perigo; }
QPushButton#perigo:hover { background: $fundo_perigo; }
QPushButton#discreto { color: $suave; background: transparent; border-color: transparent; }
QPushButton#discreto:hover { color: $texto; background: $controle; }
QPushButton:disabled, QPushButton#primario:disabled, QPushButton#tutorial_novo:disabled,
QPushButton#tutorial_salvar:disabled, QPushButton#perigo:disabled {
    color: $inativo; background: $fundo_inativo; border-color: $borda; }
QDialogButtonBox QPushButton { min-width: 64px; }
QWidget#navegacao, QToolBox, QToolBox QWidget#grupo_menu { background: $painel; }
QToolBox::tab { background: $painel; color: $suave; padding: 3px 8px; font-weight: 600; }
QToolBox::tab:selected { background: $selecao; color: $texto_selecao; border-left: 3px solid $acao; }
QToolBox QPushButton { text-align: left; font-weight: 400; background: $painel;
                      border: 1px solid transparent; padding: 3px 10px; min-height: 16px; }
QToolBox QPushButton:hover { background: $sobre; }
QToolBox QPushButton:disabled { color: $inativo; background: $painel; border: 1px solid transparent; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
    background: $campo; color: $texto; border: 1px solid $borda_forte;
    border-radius: 7px; padding: 5px 8px; min-height: 20px;
    selection-color: $texto_selecao; selection-background-color: $selecao; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover { border-color: $destaque; }
QLineEdit:disabled, QComboBox:disabled { color: $inativo; background: $fundo_inativo; }
QPlainTextEdit, QTextEdit, QListWidget { background: $campo; border: 1px solid $borda; border-radius: 8px; }
QComboBox QAbstractItemView { background: $painel; border: 1px solid $borda_forte; selection-color: $texto_selecao;
                              selection-background-color: $selecao; outline: 0; padding: 4px; }
QTableWidget, QTableView { background: $campo; alternate-background-color: $linha_par; border: 1px solid $borda;
    border-radius: 8px; gridline-color: $borda; selection-background-color: $selecao; selection-color: $texto_selecao; }
QTableView::item:hover { background: $sobre; }
QHeaderView { background: transparent; }
QHeaderView::section { background: $controle; color: $suave; padding: 6px 8px; border: 0;
                       border-right: 1px solid $borda; font-weight: 600; }
QHeaderView::section:vertical { font-weight: 400; padding: 2px 6px; border-right: 0; }
QTableCornerButton::section { background: $controle; border: 0; }
QTabWidget::pane { border: 1px solid $borda; border-radius: 8px; }
QTabBar::tab { background: $fundo; color: $suave; padding: 6px 12px; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: $texto; background: $controle; }
QTabBar::tab:selected { color: $destaque; border-bottom: 2px solid $acao; font-weight: 600; }
QGroupBox { border: 1px solid $borda; border-radius: 10px; margin-top: 12px; padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: $destaque; font-weight: 700; }
QScrollArea { border: 0; }
QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: $borda_forte; border-radius: 4px; min-height: 32px; }
QScrollBar::handle:horizontal { background: $borda_forte; border-radius: 4px; min-width: 32px; }
QScrollBar::handle:hover { background: $suave; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QToolTip { background: $painel; color: $texto; border: 1px solid $borda_forte; padding: 5px; }
QMenu { background: $painel; border: 1px solid $borda; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 5px; }
QMenu::item:selected { background: $selecao; color: $texto_selecao; }
QPushButton:focus, QToolBox QPushButton:focus, QPushButton#discreto:focus, QPushButton#perigo:focus,
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus,
QPlainTextEdit:focus, QTextEdit:focus { border: 2px solid $destaque; }
QPushButton#primario:focus, QPushButton#tutorial_novo:focus, QPushButton#tutorial_salvar:focus {
    border: 2px solid $texto_acao; }
""")
ESTILO = _FOLHA.substitute({chave: par[0] for chave, par in _CORES.items()})
ESTILO_CLARO = _FOLHA.substitute({chave: par[1] for chave, par in _CORES.items()})


def aplicar(aplicacao: QApplication, aparencia: str = "escuro") -> None:
    # O plugin offscreen do Windows não enumera fontes do sistema por conta própria.
    if sys.platform == "win32" and "Segoe UI" not in QFontDatabase.families():
        pasta = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for nome in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
            caminho = pasta / nome
            if caminho.is_file():
                QFontDatabase.addApplicationFont(str(caminho))
    aplicacao.setStyle("Fusion")
    # Calendários, indicadores de seleção e ícones de controles nativos também acompanham o tema.
    indice = 1 if aparencia == "claro" else 0
    cores = {chave: QColor(par[indice]) for chave, par in _CORES.items()}
    paleta = aplicacao.style().standardPalette()
    papeis = QPalette.ColorRole
    for papel, chave in (
        (papeis.Window, "fundo"), (papeis.WindowText, "texto"), (papeis.Base, "campo"),
        (papeis.AlternateBase, "linha_par"), (papeis.Text, "texto"), (papeis.PlaceholderText, "suave"),
        (papeis.Button, "controle"), (papeis.ButtonText, "texto"), (papeis.Highlight, "selecao"),
        (papeis.HighlightedText, "texto_selecao"), (papeis.Link, "destaque"),
    ):
        paleta.setColor(papel, cores[chave])
    for papel in (papeis.Text, papeis.ButtonText, papeis.WindowText):
        paleta.setColor(QPalette.ColorGroup.Disabled, papel, cores["inativo"])
    aplicacao.setPalette(paleta)
    aplicacao.setStyleSheet(ESTILO_CLARO if aparencia == "claro" else ESTILO)
    instalar_ajuste_de_janelas(aplicacao)
    from src.core import edicao
    ed = edicao.atual()
    aplicacao.setApplicationName(f"{ed.nome}{ed.sufixo_titulo}")


def texto(conteudo: str, nome: str = "", quebra: bool = True) -> QLabel:
    rotulo = QLabel(conteudo)
    rotulo.setObjectName(nome)
    rotulo.setWordWrap(quebra)
    return rotulo


class CapaBalcao(QFrame):
    """Foto local reenquadrada conforme o painel, com fundo legível durante todo o redimensionamento."""

    def __init__(self, vertical=False):
        super().__init__()
        from src.core import edicao
        self._vertical = vertical
        self._foto = QPixmap(str(edicao.pasta_recursos() / "balcao-pdv.jpg"))

    def paintEvent(self, evento):
        area = QRectF(self.rect())
        pintor = QPainter(self)
        pintor.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        contorno = QPainterPath()
        contorno.addRoundedRect(area, 14, 14)
        pintor.setClipPath(contorno)
        fundo = QColor("#12382f")
        pintor.fillRect(area, fundo)
        if self._foto.isNull() or area.isEmpty():
            return
        destino = QRectF(area)
        if not self._vertical:
            destino.setLeft(area.width() * 0.35)
        escala = max(destino.width() / self._foto.width(), destino.height() / self._foto.height())
        largura, altura = destino.width() / escala, destino.height() / escala
        origem = QRectF((self._foto.width() - largura) * 0.74, (self._foto.height() - altura) * 0.60,
                        largura, altura)
        pintor.drawPixmap(destino, self._foto, origem)
        if self._vertical:
            sombra = QLinearGradient(area.topLeft(), area.bottomLeft())
            sombra.setColorAt(0, QColor(5, 23, 18, 155))
            sombra.setColorAt(0.45, QColor(5, 23, 18, 12))
            sombra.setColorAt(1, QColor(5, 23, 18, 235))
        else:
            sombra = QLinearGradient(destino.topLeft(), destino.topRight())
            sombra.setColorAt(0, fundo)
            sombra.setColorAt(0.45, QColor(18, 56, 47, 160))
            sombra.setColorAt(1, QColor(18, 56, 47, 12))
        pintor.fillRect(destino, sombra)


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
    if not any(b.objectName() in ("primario", "tutorial_novo", "tutorial_salvar")
               for b in janela.findChildren(QPushButton)):
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
