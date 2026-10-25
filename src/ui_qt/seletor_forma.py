"""Seletor da forma de pagamento: um botão grande por forma (Dinheiro, Débito, Crédito, Pix...), com o número de cada uma.

Substitui a lista suspensa. A forma escolhida fica destacada; o número (1 a 9), a inicial ou as setas escolhem pelo teclado
(tratadas pelo caixa, que filtra os eventos deste widget), e o clique escolhe e já leva ao valor. Tem os mesmos métodos que o
caixa usava da lista suspensa (`addItem`, `currentText`, `setCurrentIndex`, `findText`...), então o resto do caixa não muda.
Os botões ficam só no `QButtonGroup` (sem lista de widgets nem funções anônimas guardadas em Python).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QPushButton, QWidget


class SeletorForma(QWidget):
    currentIndexChanged = Signal(int)
    escolhida = Signal(int)                 # clique do mouse numa forma: o caixa leva o foco ao valor

    def __init__(self, parent: QWidget | None = None, colunas: int = 2):
        super().__init__(parent)
        self.colunas = max(1, colunas)
        self._textos: list[str] = []
        self._dados: list = []
        self._indice = -1
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(False)     # a marcação é feita aqui: clicar de novo na atual não a desmarca
        self._grupo.idClicked.connect(self._clicou)
        self._grade = QGridLayout(self)
        self._grade.setContentsMargins(0, 0, 0, 0)
        self._grade.setSpacing(6)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setObjectName("seletor_forma")
        self.setAttribute(Qt.WA_StyledBackground, True)     # a borda do foco vem do estilo (sem repolir botões por código)

    # ------------------------------------------------------------ como a lista suspensa
    def addItem(self, texto: str, dado=None) -> None:
        i = len(self._textos)
        botao = QPushButton(f"{i + 1}  ·  {texto}" if i < 9 else texto, self)
        botao.setObjectName("forma")
        botao.setCheckable(True)
        botao.setFocusPolicy(Qt.NoFocus)            # o foco fica no seletor, que recebe o teclado
        botao.setCursor(Qt.PointingHandCursor)
        self._grupo.addButton(botao, i)
        self._textos.append(texto)
        self._dados.append(dado)
        self._grade.addWidget(botao, i // self.colunas, i % self.colunas)
        if self._indice < 0:
            self.setCurrentIndex(0)

    def clear(self) -> None:
        for botao in self._grupo.buttons():
            self._grupo.removeButton(botao)
            self._grade.removeWidget(botao)
            botao.setParent(None)
            botao.deleteLater()
        self._textos, self._dados, self._indice = [], [], -1

    def count(self) -> int:
        return len(self._textos)

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
        if 0 <= i < len(self._textos):
            mudou = i != self._indice
            self._indice = i
            for botao in self._grupo.buttons():
                botao.setChecked(self._grupo.id(botao) == i)
            if mudou:
                self.currentIndexChanged.emit(i)
        else:                                          # índice inválido: só reafirma a marcação atual
            for botao in self._grupo.buttons():
                botao.setChecked(self._grupo.id(botao) == self._indice)

    def mover(self, passo: int) -> None:
        """Setas: um passo na grade (±1 na linha, ±colunas entre linhas); não passa das pontas."""
        novo = self._indice + passo
        if 0 <= novo < len(self._textos):
            self.setCurrentIndex(novo)

    # ------------------------------------------------------------ mouse
    def _clicou(self, i: int) -> None:
        self.setCurrentIndex(i)
        self.escolhida.emit(i)
