"""Indicador da fila de envio no caixa, com relógio que acompanha a visibilidade da janela."""
import sqlite3

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel
from src.sync.painel_status import situacao


class EstadoNuvem(QLabel):
    def __init__(self, banco, parent=None):
        super().__init__(parent)
        self.banco = banco
        self.setAccessibleName("Estado do envio à nuvem")
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.atualizar)
        self.atualizar()

    def atualizar(self):
        try:
            r = situacao(self.banco)
        except sqlite3.Error:
            self.timer.stop()
            self.setText("Estado da nuvem indisponível")
            return
        self.setText(f"{r['texto']} · {r['vendas_pendentes']} venda(s) e {r['devolucoes_pendentes']} devolução(ões) pendente(s)")
        self.setToolTip("Último envio confirmado: " + (r["ultimo_envio"] or "nenhum") +
                        ("\n" + r["erro"] if r["erro"] else ""))
        self.setStyleSheet("color: " + ("#198754" if r["estado"] == "em_dia" else "#b45309") + ";")

    def showEvent(self, evento):
        self.atualizar()
        self.timer.start()
        super().showEvent(evento)

    def hideEvent(self, evento):
        self.timer.stop()
        super().hideEvent(evento)
