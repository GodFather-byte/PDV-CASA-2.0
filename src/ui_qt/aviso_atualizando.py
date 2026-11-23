"""Aviso curto na abertura quando a atualização já foi disparada: o programa reabre sozinho quando terminar."""
from __future__ import annotations


def mostrar(segundos: int = 8) -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QProgressBar, QVBoxLayout
    from src.ui_qt import tema

    app = QApplication.instance() or QApplication([])
    if not app.styleSheet():
        tema.aplicar(app)
    aviso = QDialog()
    aviso.setWindowTitle("Atualização")
    aviso.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    caixa = QVBoxLayout(aviso)
    caixa.setContentsMargins(24, 20, 24, 20)
    caixa.setSpacing(12)
    caixa.addWidget(tema.texto("Atualizando o programa", "titulo"))
    caixa.addWidget(tema.texto("Ele abre sozinho em alguns minutos. As vendas estão salvas.", "suave"))
    atividade = QProgressBar()
    atividade.setRange(0, 0)
    atividade.setTextVisible(False)
    atividade.setAccessibleName("Atualização em andamento")
    atividade.setFixedHeight(6)
    caixa.addWidget(atividade)
    aviso.resize(370, 140)
    aviso.show()
    QTimer.singleShot(segundos * 1000, app.quit)
    return app.exec()
