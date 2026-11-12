"""Aviso curto na abertura quando a atualização já foi disparada: o programa reabre sozinho quando terminar."""
from __future__ import annotations


def mostrar(segundos: int = 8) -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([])
    aviso = QLabel("Atualizando o programa.\n\nEle abre sozinho em alguns minutos. As vendas estão salvas.")
    aviso.setWindowTitle("Atualização")
    aviso.setAlignment(Qt.AlignCenter)
    aviso.setMargin(28)
    aviso.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    aviso.setStyleSheet("font-size: 15px;")
    aviso.show()
    QTimer.singleShot(segundos * 1000, app.quit)
    return app.exec()
