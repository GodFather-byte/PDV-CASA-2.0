"""O indicador acompanha a fila real e interrompe seu timer quando deixa de estar visível."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from tests.base import BaseTeste
from src.ui_qt.estado_nuvem import EstadoNuvem


class TesteEstadoNuvemQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_mostra_estado_e_para_timer_ao_fechar(self):
        widget = EstadoNuvem(self.banco)
        self.addCleanup(widget.close)
        self.assertIn("desligado", widget.text())
        self.assertFalse(widget.timer.isActive())
        widget.show()
        self.app.processEvents()
        self.assertTrue(widget.timer.isActive())
        self.banco.cfg_set("painel_dono", "S")
        widget.atualizar()
        self.assertIn("Configure", widget.text())
        widget.close()
        self.app.processEvents()
        self.assertFalse(widget.timer.isActive())
