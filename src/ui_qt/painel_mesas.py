"""Painel de mesas e comandas do caixa: a coluna de cartões à esquerda da tela (o visual da boate).

Cada posição aberta é um cartão com o tipo (comanda, mesa ou garota), o número em destaque, uma linha de identificação (nome da
comanda, pessoas na mesa, itens ou drinks marcados da garota), a situação em uma pílula colorida e o total. O balcão é a primeira
posição, mas aparece como uma faixa fina acima dos cartões. A garota com comissão a pagar ganha o próprio cartão (ou um selo na
comanda dela, se tem consumo aberto). A busca e as abas (Todas, Abertas, Pago em parte, Aguardando acerto, Comissões) só
controlam o que aparece; não fecham, cancelam nem transferem nada. O modelo dos cartões fica em
`src/controllers/mesas_modelo.py`; aqui só há o desenho e a navegação por mouse e teclado.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from src.controllers.mesas_modelo import ABAS, GRUPOS_ABA, ROTULOS_PILULA, ROTULOS_TIPO, idade, montar_tiles
from src.core import formatacao as fmt

LARGURA, ALTURA, MARGEM = 184, 126, 8       # a célula de cada cartão (com o espaçamento)
ALTURA_FAIXA = 52                           # a célula da faixa do balcão, na largura toda acima dos cartões
RESERVA_BARRA = 18                          # espaço da barra de rolagem
FONTE = "Segoe UI"

ESTADOS = {
    "escuro": {
        "consumindo": {"fundo": "#1c313a", "borda": "#52788b", "texto": "#ace1ec"},
        "parada": {"fundo": "#372726", "borda": "#a7665e", "texto": "#ffb1a6"},
        "conta": {"fundo": "#352f22", "borda": "#9a8053", "texto": "#ffce82"},
        "balcao": {"fundo": "#18372f", "borda": "#438871", "texto": "#7ce8bd"},
        "garota": {"fundo": "#3b2734", "borda": "#a66c91", "texto": "#f2b1d4"},      # rosa: comanda com comissão
        "parcial": {"fundo": "#302c3c", "borda": "#8875a3", "texto": "#cfb9eb"},
        "acerto": {"fundo": "#352f22", "borda": "#9a8053", "texto": "#ffce82"},
    },
    "claro": {
        "consumindo": {"fundo": "#e3eaf7", "borda": "#7f96c8", "texto": "#2a4a8f"},
        "parada": {"fundo": "#f6e4e0", "borda": "#c0655a", "texto": "#9c3328"},
        "conta": {"fundo": "#f6ebd0", "borda": "#b88a1c", "texto": "#74500a"},
        "balcao": {"fundo": "#dcefe5", "borda": "#4a9a7a", "texto": "#0b6648"},
        "garota": {"fundo": "#f9cbe4", "borda": "#d23c8c", "texto": "#8e1452"},
        "parcial": {"fundo": "#e8e3f5", "borda": "#8470c8", "texto": "#54409e"},
        "acerto": {"fundo": "#f6ebd0", "borda": "#b88a1c", "texto": "#74500a"},
    },
}
CORES = {
    "escuro": {
        "fundo": "#101c20", "quadro": "#17272b", "quadro_borda": "#33474b", "campo": "#112125",
        "cartao": "#1d3034", "cartao2": "#293f43", "borda": "#4a6365",
        "texto": "#eef5ef", "suave": "#b4c6c4", "mudo": "#9cafac", "azul": "#8bc6e2",
        "verde": "#55dfb0", "ambar": "#ffce82", "vermelho": "#ff9a98", "rosa": "#efacd1",
        "sobre_marca": "#0d2a22", "sobre_botao": "#85edc5", "selecao": "#234c42",
    },
    "claro": {
        "fundo": "#eff1eb", "quadro": "#fffefa", "quadro_borda": "#cbd5ce", "campo": "#ffffff",
        "cartao": "#f5f7f1", "cartao2": "#e8eee6", "borda": "#94aaa0",
        "texto": "#162b28", "suave": "#425c55", "mudo": "#546b63", "azul": "#266280",
        "verde": "#11694f", "ambar": "#875310", "vermelho": "#a33437", "rosa": "#913969",
        "sobre_marca": "#ffffff", "sobre_botao": "#0b5943", "selecao": "#dceee3",
    },
}


def misturar(c1: str, c2: str, t: float) -> str:
    """Cor intermediária entre c1 e c2 (t=0 -> c1, t=1 -> c2)."""
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def detalhes(t: dict) -> tuple[str, str, str]:
    """(linha de identificação, aviso em destaque, tom do aviso: 'verde', 'vermelho', 'ambar' ou 'garota') do cartão."""
    if t["tipo"] == "balcao":
        return "Venda rápida", "", ""
    if t["tipo"] == "garota":
        n = t.get("marcacoes")
        if t.get("shows_quartos"):
            return f"{n or 0} drinks · {t['shows_quartos']} shows", "", ""
        if n:
            return (f"{n} drinks marcados" if n != 1 else "1 drink marcado"), "", ""
        return ("Comissão a pagar" if t.get("nome") else ""), "", ""
    if t.get("nome"):
        ident = t["nome"]
    elif t.get("pessoas"):
        ident = f"{t['pessoas']} pessoas" if t["pessoas"] != 1 else "1 pessoa"
    elif t.get("itens"):
        ident = f"{t['itens']} itens" if t["itens"] != 1 else "1 item"
    else:
        ident = ""
    if t.get("shows_quartos"):
        ident = f"{ident} · {t['shows_quartos']} shows".strip(" ·")
    if t.get("saldo") is not None:
        sem_credito = t["saldo"].startswith("-") or t["saldo"] == fmt.fmt_num(0)
        return ident, f"Saldo R$ {t['saldo']}", "vermelho" if sem_credito else "verde"
    if t.get("falta"):
        return ident, f"Falta R$ {t['falta']}", "ambar"
    if t["estado"] == "parada":
        return ident, f"{t['minutos']} min sem lançar", "vermelho"
    if t.get("garota"):
        return ident, f"Comissão R$ {t['garota']}", "garota"
    return ident, "", ""


def cores_do_cartao(t: dict, modo: str) -> dict:
    """Fundo, borda e texto do cartão: a comanda que recebeu comissão (a pagar) fica rosa, como o cartão da garota; a pílula
    continua mostrando a situação dela (aberta, parada, conta...)."""
    return ESTADOS[modo]["garota" if t.get("garota") else t["estado"]]


def _fonte(pontos: float, negrito: bool = False) -> QFont:
    f = QFont(FONTE)
    f.setPointSizeF(pontos)
    f.setBold(negrito)
    return f


class GradeCartoes(QWidget):
    """A área onde os cartões são desenhados; clique e teclado ficam aqui."""

    escolhida = Signal(str)
    transferir = Signal(str)
    voltar = Signal()
    digitou = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.modo = "escuro"
        self.tiles: list[dict] = []
        self.atual: str | None = None         # a posição que está na tela do caixa (borda grossa)
        self.cursor_chave: str | None = None  # onde o teclado está (pontilhado, só com o foco no painel)
        self.por_linha = 2
        self.area: QScrollArea | None = None
        self.setMinimumHeight(ALTURA)

    # ------------------------------------------------------------ geometria
    def _tem_faixa(self) -> bool:
        return bool(self.tiles) and self.tiles[0]["tipo"] == "balcao"

    def celula(self, i: int) -> tuple[int, int, int, int]:
        """(x, y, largura, altura) da célula do cartão `i`: o balcão ocupa a faixa do alto; os demais, a grade abaixo dela."""
        faixa = self._tem_faixa()
        if faixa and i == 0:
            return 0, 0, max(LARGURA, self.width()), ALTURA_FAIXA
        j = i - 1 if faixa else i
        sobra = max(0, self.width() - self.por_linha * LARGURA) // 2         # centraliza a grade na largura do painel
        return (sobra + (j % self.por_linha) * LARGURA, (ALTURA_FAIXA if faixa else 0) + (j // self.por_linha) * ALTURA,
                LARGURA, ALTURA)

    def reorganizar(self) -> None:
        self.por_linha = max(1, self.width() // LARGURA)
        faixa = self._tem_faixa()
        linhas = max(1, -(-(len(self.tiles) - (1 if faixa else 0)) // self.por_linha))
        self.setMinimumHeight((ALTURA_FAIXA if faixa else 0) + linhas * ALTURA + MARGEM)
        self.update()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self.reorganizar()

    def definir(self, tiles: list[dict], atual: str | None) -> None:
        self.tiles, self.atual = tiles, atual
        if self.cursor_chave not in {t["chave"] for t in tiles}:
            self.cursor_chave = None
        self.reorganizar()

    # ------------------------------------------------------------ desenho
    def _cor(self, nome: str) -> str:
        return CORES[self.modo][nome]

    def _cartao(self, p: QPainter, x1, y1, x2, y2, raio, fundo, borda, largura=1) -> None:
        p.setPen(QPen(QColor(borda), largura))
        p.setBrush(QColor(fundo))
        p.drawRoundedRect(QRectF(x1, y1, x2 - x1, y2 - y1), raio, raio)

    def _pilula(self, p: QPainter, x: float, meio: float, e: dict, estado: str) -> float:
        texto = ROTULOS_PILULA[estado]
        fonte = _fonte(8, True)
        largura = QFontMetrics(fonte).horizontalAdvance(texto) + 18
        self._cartao(p, x, meio - 10, x + largura, meio + 10, 10, misturar(e["borda"], e["fundo"], 0.62), e["borda"])
        p.setFont(fonte)
        p.setPen(QColor(e["texto"]))
        p.drawText(QRectF(x, meio - 10, largura, 20), Qt.AlignCenter, texto)
        return largura

    def _texto(self, p: QPainter, x: float, y: float, texto: str, fonte: QFont, cor: str,
               alinhar: str = "w", largura_max: float | None = None) -> None:
        """Texto com a linha de base centrada em `y`; `alinhar` 'w' (à esquerda de x) ou 'e' (à direita de x)."""
        fm = QFontMetrics(fonte)
        if largura_max:
            texto = fm.elidedText(texto, Qt.ElideRight, int(largura_max))
        larg = fm.horizontalAdvance(texto)
        p.setFont(fonte)
        p.setPen(QColor(cor))
        px = x if alinhar == "w" else x - larg
        p.drawText(QPointF(px, y + (fm.ascent() - fm.descent()) / 2), texto)

    def _relogio(self, p: QPainter, cx: float, cy: float) -> None:
        cor = QColor(self._cor("vermelho"))
        p.setPen(QPen(cor, 2))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(cx, cy), 7, 7)
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy - 4))
        p.drawLine(QPointF(cx, cy), QPointF(cx + 3, cy))

    def _selo_garota(self, p: QPainter, cx: float, cy: float) -> None:
        p.setPen(QPen(QColor("#8a1556"), 1))
        p.setBrush(QColor("#d6388a"))
        p.drawEllipse(QPointF(cx, cy), 8, 8)
        estrela = QPolygonF()
        for i in range(10):
            raio = 6.2 if i % 2 == 0 else 2.7
            ang = math.radians(-90 + i * 36)
            estrela.append(QPointF(cx + raio * math.cos(ang), cy + 0.3 + raio * math.sin(ang)))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffd84d"))
        p.drawPolygon(estrela)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for i, t in enumerate(self.tiles):
            self._tile(p, i, t)
        if not self.tiles:
            self._texto(p, 12, ALTURA / 2, "Nenhuma posição neste filtro.", _fonte(11), self._cor("suave"))
        if self.hasFocus() and self.cursor_chave in {t["chave"] for t in self.tiles}:
            chaves = [t["chave"] for t in self.tiles]
            x, y, w, h = self.celula(chaves.index(self.cursor_chave))
            pen = QPen(QColor(self._cor("ambar")), 2, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(x + 1, y + 1, w - 2, h - 2))
        p.end()

    def _faixa(self, p: QPainter, i: int, t: dict) -> None:
        x, y, w, h = self.celula(i)
        e = ESTADOS[self.modo][t["estado"]]
        atual = t["chave"] == self.atual
        x1, y1, x2, y2 = x + 4, y + 4, x + w - 4, y + h - 4
        self._cartao(p, x1, y1, x2, y2, 12, e["fundo"], self._cor("verde") if atual else e["borda"], 3 if atual else 1)
        meio = (y1 + y2) / 2
        esquerda, direita = x1 + 12, x2 - 12
        largura_pilula = self._pilula(p, esquerda, meio, e, t["estado"])
        ident = detalhes(t)[0]
        total = f"R$ {t['total'] or '0,00'}"
        fonte_total = _fonte(11, True)
        larg_total = QFontMetrics(fonte_total).horizontalAdvance(total)
        if ident:
            self._texto(p, esquerda + largura_pilula + 10, meio, ident, _fonte(9), self._cor("suave"),
                        largura_max=max(20, direita - larg_total - (esquerda + largura_pilula + 10) - 8))
        self._texto(p, direita, meio, total, fonte_total, self._cor("texto"), "e")

    def _tile(self, p: QPainter, i: int, t: dict) -> None:
        if t["tipo"] == "balcao":
            self._faixa(p, i, t)
            return
        x, y, w, h = self.celula(i)
        e = ESTADOS[self.modo][t["estado"]]
        rosa = cores_do_cartao(t, self.modo)
        atual = t["chave"] == self.atual
        x1, y1, x2, y2 = x + 4, y + 4, x + w - 4, y + h - 4
        self._cartao(p, x1, y1, x2, y2, 14, rosa["fundo"], self._cor("verde") if atual else rosa["borda"], 3 if atual else 1)
        pad = 12
        esquerda, direita = x1 + pad, x2 - pad
        rotulo_tipo = ROTULOS_TIPO[t["tipo"]] + (f" {t['rotulo']}" if t["tipo"] == "garota" and t.get("nome") else "")
        self._texto(p, esquerda, y1 + 15, rotulo_tipo, _fonte(8, True), self._cor("suave"))
        if t["estado"] == "parada":
            self._relogio(p, direita - 7, y1 + 15)
            direita -= 22
        if t.get("garota"):
            self._selo_garota(p, direita - 8, y1 + 15)
            direita -= 22
        if t["tipo"] in ("comanda", "mesa") and t["minutos"] is not None:
            self._texto(p, direita, y1 + 15, idade(t["minutos"]), _fonte(9),
                        self._cor("vermelho") if t["estado"] == "parada" else self._cor("suave"), "e")
        titulo = t["nome"] if t["tipo"] == "garota" and t.get("nome") else t["rotulo"]
        self._texto(p, esquerda, y1 + 39, titulo, _fonte(19 if len(titulo) <= 8 else 14, True), self._cor("texto"),
                    largura_max=x2 - pad - esquerda)
        ident, aviso, tom = detalhes(t)
        if ident:
            self._texto(p, esquerda, y1 + 64, ident, _fonte(9), self._cor("suave"), largura_max=x2 - pad - esquerda)
        if aviso:
            cor = rosa["texto"] if tom == "garota" else self._cor(tom)
            self._texto(p, esquerda, y1 + 79, aviso, _fonte(8, True), cor, largura_max=x2 - pad - esquerda)
        baixo = y2 - 17
        largura_pilula = self._pilula(p, esquerda, baixo, e, t["estado"])
        if t["total"]:
            self._texto(p, x2 - pad, baixo, f"R$ {t['total']}", _fonte(11, True), self._cor("texto"), "e")

    # ------------------------------------------------------------ mouse e teclado
    def chave_em(self, pos) -> str | None:
        for i, t in enumerate(self.tiles):
            x, y, w, h = self.celula(i)
            if x <= pos.x() < x + w and y <= pos.y() < y + h:
                return t["chave"]
        return None

    def mousePressEvent(self, ev) -> None:
        chave = self.chave_em(ev.position().toPoint())
        if chave is None:
            self.setFocus()                     # clicou no espaço vazio: leva o teclado para cá
            self.mover_cursor(0)
        else:
            self.escolhida.emit(chave)

    def mouseMoveEvent(self, ev) -> None:
        self.setCursor(Qt.PointingHandCursor if self.chave_em(ev.position().toPoint()) else Qt.ArrowCursor)

    def focusInEvent(self, ev) -> None:
        super().focusInEvent(ev)
        if self.cursor_chave is None:
            self.cursor_chave = self.atual
        self.update()

    def focusOutEvent(self, ev) -> None:
        super().focusOutEvent(ev)
        self.update()

    def mover_cursor(self, passo: int) -> None:
        chaves = [t["chave"] for t in self.tiles]
        if not chaves:
            return
        i = chaves.index(self.cursor_chave) if self.cursor_chave in chaves else 0
        self.cursor_chave = chaves[max(0, min(len(chaves) - 1, i + passo))]
        self.garantir_visivel()
        self.update()

    def garantir_visivel(self) -> None:
        chaves = [t["chave"] for t in self.tiles]
        if self.area is not None and self.cursor_chave in chaves:
            x, y, w, h = self.celula(chaves.index(self.cursor_chave))
            self.area.ensureVisible(x + w // 2, y + h // 2, w // 2, h // 2 + 4)

    def _vertical(self, i: int, sentido: int) -> int | None:
        """Índice do cartão uma linha abaixo (`sentido` 1) ou acima (-1) de `i`; None = saiu pelo alto do painel. A faixa do balcão
        é a primeira linha: dela se desce ao primeiro cartão, e do primeiro cartão de cada coluna se sobe até ela."""
        faixa = 1 if self._tem_faixa() else 0
        total = len(self.tiles)
        if faixa and i == 0:
            return 1 if sentido > 0 and total > 1 else (None if sentido < 0 else 0)
        j = i - faixa + sentido * self.por_linha
        if j < 0:
            return 0 if faixa else None
        return min(total - 1, j + faixa)

    def keyPressEvent(self, ev) -> None:
        k = ev.key()
        chaves = [t["chave"] for t in self.tiles]
        atual = chaves.index(self.cursor_chave) if self.cursor_chave in chaves else 0
        if k in (Qt.Key_Left, Qt.Key_Right):
            self.mover_cursor(-1 if k == Qt.Key_Left else 1)
        elif k in (Qt.Key_Down, Qt.Key_Up):
            destino = self._vertical(atual, 1 if k == Qt.Key_Down else -1)
            if destino is None:
                self.voltar.emit()              # no alto do painel, a seta para cima volta ao campo da posição
            else:
                self.mover_cursor(destino - atual)
        elif k in (Qt.Key_Home, Qt.Key_End):
            self.mover_cursor(-len(chaves) if k == Qt.Key_Home else len(chaves))
        elif k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if self.cursor_chave:
                self.escolhida.emit(self.cursor_chave)
        elif k == Qt.Key_Escape:
            self.voltar.emit()
        elif k == Qt.Key_T:
            tipo = next((t["tipo"] for t in self.tiles if t["chave"] == self.cursor_chave), None)
            if self.cursor_chave and self.cursor_chave != "0" and tipo != "garota":
                self.transferir.emit(self.cursor_chave)
        elif ev.text() and (ev.text().isdigit() or ev.text() in "cCmM"):
            self.digitou.emit(ev.text())
        else:
            ev.ignore()                         # as teclas F continuam valendo (são tratadas na janela)


class PainelMesas(QWidget):
    """A busca, as abas e os cartões. `colunas` é quantos cartões cabem por linha (3 na tela larga, 2 no notebook)."""

    escolhida = Signal(str)
    transferir = Signal(str)
    voltar = Signal()
    digitou = Signal(str)

    LARGURA_CARTAO = LARGURA
    RESERVA = RESERVA_BARRA + 8

    def __init__(self, parent=None, colunas: int = 2, com_comissoes: bool = True):
        super().__init__(parent)
        self.setObjectName("area_mesas")
        self.colunas = max(1, colunas)
        self._lista_abas = tuple(a for a in ABAS if com_comissoes or a[0] != "Comissões")
        self._todos_tiles: list[dict] = []
        self._tiles: list[dict] = []
        self._atual: str | None = None
        self._assinatura = None
        self.aba = "Todas"
        self.modo = "escuro"

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(6)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar nº (ex.: 12 ou M5)")
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(lambda _: self._filtrar(reiniciar=True))
        self.busca.returnPressed.connect(self.focar)
        raiz.addWidget(self.busca)
        # Com um cartão por linha (tela estreita) as cinco abas não cabem lado a lado e viravam pedaços de palavra;
        # `_arrumar_abas` distribui em quantas linhas a largura pedir.
        self._faixa_abas = QVBoxLayout()
        self._faixa_abas.setSpacing(4)
        self._abas: dict[str, QPushButton] = {}
        for valor, curto in self._lista_abas:
            botao = QPushButton(curto)
            botao.setCheckable(True)
            botao.setCursor(Qt.PointingHandCursor)
            botao.setFocusPolicy(Qt.NoFocus)
            botao.clicked.connect(lambda _=False, v=valor: self._escolher_aba(v))
            self._abas[valor] = botao
        raiz.addLayout(self._faixa_abas)
        self.grade = GradeCartoes()
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QScrollArea.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setWidget(self.grade)
        self.grade.area = self.area
        for sinal in ("escolhida", "transferir", "voltar", "digitou"):
            getattr(self.grade, sinal).connect(getattr(self, sinal))
        raiz.addWidget(self.area, 1)
        self.lbl_resumo = QLabel("")
        self.lbl_resumo.setWordWrap(True)             # no painel de um cartão a linha inteira não cabe: quebra em duas
        raiz.addWidget(self.lbl_resumo)
        self._estilizar()
        self.definir_colunas(colunas)

    # ------------------------------------------------------------ aparência
    def definir_modo(self, modo: str) -> None:
        modo = "claro" if modo == "claro" else "escuro"
        if modo != self.modo:
            self.modo = modo
            self.grade.modo = modo
            self._estilizar()
            self.grade.update()

    def _estilizar(self) -> None:
        c = CORES[self.modo]
        self.lbl_resumo.setStyleSheet(f"color: {c['suave']}; font-size: 12px;")
        for botao in self._abas.values():
            botao.setStyleSheet(
                f"QPushButton {{ background: {c['cartao']}; color: {c['texto']}; border: 1px solid {c['borda']};"
                f" border-radius: 7px; padding: 5px 8px; font-weight: 600; font-size: 12px; text-align: center; }}"
                f"QPushButton:hover {{ background: {c['cartao2']}; }}"
                f"QPushButton:checked {{ background: {c['verde']}; color: {c['sobre_marca']}; border-color: {c['verde']}; }}")
        self._marcar_abas()
        self._arrumar_abas()

    def _arrumar_abas(self) -> None:
        """Distribui as abas pelas linhas que a largura do painel pede, sem cortar o texto de nenhuma."""
        while self._faixa_abas.count():                # desmonta as linhas antigas (os botões continuam vivos)
            antiga = self._faixa_abas.takeAt(0).layout()
            if antiga is not None:
                while antiga.count():
                    antiga.takeAt(0)
                antiga.deleteLater()
        largura = self.colunas * LARGURA + self.RESERVA
        linha, usado = None, 0
        for botao in self._abas.values():
            precisa = botao.sizeHint().width()
            if linha is None or usado + linha.spacing() + precisa > largura:
                if linha is not None:
                    linha.addStretch(1)                # as abas ficam juntas à esquerda
                linha, usado = QHBoxLayout(), 0
                linha.setSpacing(4)
                self._faixa_abas.addLayout(linha)
            linha.addWidget(botao)
            usado += precisa + (linha.spacing() if linha.count() > 1 else 0)
        if linha is not None:
            linha.addStretch(1)

    def _marcar_abas(self) -> None:
        for valor, botao in self._abas.items():
            botao.setChecked(valor == self.aba)

    def definir_colunas(self, colunas: int) -> None:
        """Muda a largura do painel para `colunas` cartões por linha (a janela do caixa chama ao ser redimensionada)."""
        colunas = max(1, colunas)
        mudou = colunas != self.colunas or self.maximumWidth() != colunas * LARGURA + self.RESERVA
        self.colunas = colunas
        if mudou:                                     # a janela do caixa chama a cada redimensionamento: só mexe se mudou
            self.setFixedWidth(self.colunas * LARGURA + self.RESERVA)
            self._arrumar_abas()

    # ------------------------------------------------------------ dados
    def _escolher_aba(self, valor: str) -> None:
        self.aba = valor
        self._filtrar(reiniciar=True)

    def atualizar(self, mesas: list[dict], balcao: dict | None = None, atual: str | None = None, garotas=()) -> None:
        tiles = montar_tiles(mesas, balcao, garotas)
        assinatura = ([(t["chave"], t["tipo"], t["estado"], t["total"], t.get("garota"), t.get("falta"), t.get("saldo"), t.get("shows_quartos"),
                        t["minutos"], t.get("nome"), t.get("pessoas"), t.get("itens"), t.get("marcacoes")) for t in tiles],
                      atual, self.modo)
        if assinatura == self._assinatura:
            return
        self._assinatura = assinatura
        self._todos_tiles, self._atual = tiles, atual
        self._filtrar()

    def _filtrar(self, reiniciar: bool = False) -> None:
        busca = self.busca.text().strip().lower()
        estados = GRUPOS_ABA.get(self.aba)
        self._tiles = [t for t in self._todos_tiles
                       if (not busca or busca in t["rotulo"].lower() or busca in (t.get("nome") or "").lower())
                       and (estados is None or t["estado"] in estados or self.aba == "Comissões" and t.get("garota"))]
        parciais = sum(t["estado"] == "parcial" for t in self._todos_tiles)
        acertos = sum(t["estado"] in {"conta", "acerto", "garota"} for t in self._todos_tiles)
        self.lbl_resumo.setText(
            f"Posições: {max(0, len(self._todos_tiles) - 1)}  |  Parciais: {parciais}  |  Acertos: {acertos}")
        self._marcar_abas()
        self.grade.definir(self._tiles, self._atual)
        if reiniciar:
            self.area.verticalScrollBar().setValue(0)

    def tiles(self) -> list[dict]:
        return [dict(t) for t in self._tiles]

    def cursor(self) -> str | None:
        return self.grade.cursor_chave

    def vizinha(self, chave: str | None, passo: int) -> str | None:
        """A chave do cartão `passo` posições depois (ou antes, se negativo) de `chave`, na lista que está à vista (respeita a
        aba e a busca). Sem `chave` na lista, `passo` positivo dá o primeiro cartão e negativo, o último. Nas pontas não dá
        a volta: devolve a própria `chave`."""
        chaves = [t["chave"] for t in self._tiles]
        if not chaves:
            return None
        if chave not in chaves:
            return chaves[0] if passo > 0 else chaves[-1]
        return chaves[max(0, min(len(chaves) - 1, chaves.index(chave) + passo))]

    def focar(self, chave: str | None = None) -> None:
        """Põe o foco do teclado nos cartões, no `chave` (ou no atual, ou no primeiro)."""
        chaves = [t["chave"] for t in self._tiles]
        for candidata in (chave, self.grade.cursor_chave, self._atual):
            if candidata in chaves:
                self.grade.cursor_chave = candidata
                break
        else:
            self.grade.cursor_chave = chaves[0] if chaves else None
        self.grade.setFocus()
        self.grade.garantir_visivel()
        self.grade.update()
