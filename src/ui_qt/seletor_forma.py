"""Seletor da forma de pagamento: um botão grande por forma (Dinheiro, Débito, Crédito, Pix...), com o número de cada uma.

Substitui a lista suspensa. A forma escolhida fica destacada; o número (1 a 9), a inicial ou as setas escolhem pelo teclado, e o
clique escolhe e já leva ao valor. Tem os mesmos métodos que o caixa usava da lista suspensa (`addItem`, `currentText`,
`setCurrentIndex`, `findText`...), então o resto do caixa não muda.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QPushButton, QWidget


class SeletorForma(QWidget):
    currentIndexChanged = Signal(int)
    escolhida = Signal(int)                 # clique do mouse numa forma: o caixa leva o foco ao valor

    def __init__(self, parent: QWidget | None = None, colunas: int = 2):
        super().__init__(parent)
        self._colunas = max(1, colunas)
        self._botoes: list[QPushButton] = []
        self._textos: list[str] = []
        self._dados: list = []
        self._indice = -1
        self._grade = QGridLayout(self)
        self._grade.setContentsMargins(0, 0, 0, 0)
        self._grade.setSpacing(6)
        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------ como a lista suspensa
    def addItem(self, texto: str, dado=None) -> None:
        i = len(self._botoes)
        botao = QPushButton(f"{i + 1}  ·  {texto}" if i < 9 else texto)
        botao.setObjectName("forma")
        botao.setCheckable(True)
        botao.setFocusPolicy(Qt.NoFocus)            # o foco fica no seletor, que trata o teclado
        botao.setCursor(Qt.PointingHandCursor)
        botao.setProperty("foco", False)
        botao.clicked.connect(lambda _=False, k=i: self._clicou(k))
        self._botoes.append(botao)
        self._textos.append(texto)
        self._dados.append(dado)
        self._grade.addWidget(botao, i // self._colunas, i % self._colunas)
        if self._indice < 0:
            self.setCurrentIndex(0)

    def clear(self) -> None:
        for botao in self._botoes:
            self._grade.removeWidget(botao)
            botao.deleteLater()
        self._botoes, self._textos, self._dados, self._indice = [], [], [], -1

    def count(self) -> int:
        return len(self._botoes)

    def itemText(self, i: int) -> str:
        return self._textos[i] if 0 <= i < len(self._textos) else ""

    def itemData(self, i: int):
        return self._dados[i] if 0 <= i < len(self._dados) else None

    def currentIndex(self) -> int:
        return self._indice

    def currentText(self) -> str:
        return self.itemText(self._indice)

    def currentData(self):
        return self.itemData(self._indice)

    def findText(self, texto: str) -> int:
        return next((i for i, t in enumerate(self._textos) if t == texto), -1)

    def findData(self, dado) -> int:
        return next((i for i, d in enumerate(self._dados) if d == dado), -1)

    def setCurrentIndex(self, i: int) -> None:
        if not 0 <= i < len(self._botoes) or i == self._indice:
            for k, botao in enumerate(self._botoes):          # reafirma a marcação (ex.: o clique desmarcaria a atual)
                botao.setChecked(k == self._indice)
            return
        self._indice = i
        for k, botao in enumerate(self._botoes):
            botao.setChecked(k == i)
        self.currentIndexChanged.emit(i)

    # ------------------------------------------------------------ mouse e teclado
    def _clicou(self, i: int) -> None:
        self.setCurrentIndex(i)
        self.escolhida.emit(i)

    def keyPressEvent(self, ev) -> None:
        tecla = ev.key()
        passo = {Qt.Key_Left: -1, Qt.Key_Right: 1, Qt.Key_Up: -self._colunas, Qt.Key_Down: self._colunas}.get(tecla)
        if passo is None:
            ev.ignore()
            return
        novo = self._indice + passo
        if 0 <= novo < len(self._botoes):
            self.setCurrentIndex(novo)

    def _marcar_foco(self, com_foco: bool) -> None:
        for botao in self._botoes:
            botao.setProperty("foco", com_foco)
            botao.style().unpolish(botao)
            botao.style().polish(botao)

    def focusInEvent(self, ev) -> None:
        super().focusInEvent(ev)
        self._marcar_foco(True)

    def focusOutEvent(self, ev) -> None:
        super().focusOutEvent(ev)
        self._marcar_foco(False)
