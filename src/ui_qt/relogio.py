"""Relógio do topo do caixa: com o caixa em tela cheia a barra de tarefas some e o operador fica sem ver a hora.

Hora e minuto grandes, os segundos menores ao lado e, embaixo, o dia da semana e a data ("SEG · 26/10/2026"). Só rótulos e um
QTimer (filho do próprio quadro): nada de desenho próprio, o mesmo cuidado do resto do caixa. As cores vêm do estilo do caixa
(`QFrame#relogio`, `QLabel#relogio_hora`, `QLabel#relogio_seg`, `QLabel#relogio_data`), então segue o modo claro/escuro."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

DIAS = ("SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM")


def textos(agora: datetime) -> tuple[str, str, str]:
    """(hora:minuto, segundos, 'DIA · dd/mm/aaaa') do instante."""
    return agora.strftime("%H:%M"), agora.strftime("%S"), f"{DIAS[agora.weekday()]} · {agora.strftime('%d/%m/%Y')}"


class RelogioCaixa(QFrame):
    def __init__(self, parent=None, agora=datetime.now):
        super().__init__(parent)
        self.setObjectName("relogio")
        self._agora = agora                                 # troca dos testes: um relógio parado
        self.lbl_hora = QLabel()
        self.lbl_hora.setObjectName("relogio_hora")
        self.lbl_seg = QLabel()
        self.lbl_seg.setObjectName("relogio_seg")
        self.lbl_data = QLabel()
        self.lbl_data.setObjectName("relogio_data")
        self.lbl_data.setAlignment(Qt.AlignCenter)
        linha = QHBoxLayout()
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(3)
        linha.addStretch(1)
        linha.addWidget(self.lbl_hora, 0, Qt.AlignBottom)
        linha.addWidget(self.lbl_seg, 0, Qt.AlignBottom)
        linha.addStretch(1)
        caixa = QVBoxLayout(self)
        caixa.setContentsMargins(14, 2, 14, 4)
        caixa.setSpacing(0)
        caixa.addLayout(linha)
        caixa.addWidget(self.lbl_data)
        self.setToolTip("Hora do computador do caixa")
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.atualizar)
        self.atualizar()
        self.timer.start()

    def atualizar(self) -> None:
        hora, seg, data = textos(self._agora())
        self.lbl_hora.setText(hora)
        self.lbl_seg.setText(seg)
        self.lbl_data.setText(data)
