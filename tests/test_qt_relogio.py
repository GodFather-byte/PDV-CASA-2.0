"""Relógio do topo do caixa (em tela cheia a barra do Windows some e o operador fica sem a hora)."""
from __future__ import annotations

import unittest
from datetime import datetime

from src.ui_qt.relogio import textos
from tests.test_qt_caixa import BaseCaixaQt


class TesteTextosDoRelogio(unittest.TestCase):
    def test_hora_segundos_e_data_com_o_dia_em_portugues(self):
        self.assertEqual(textos(datetime(2026, 10, 26, 23, 7, 5)), ("23:07", "05", "SEG · 26/10/2026"))
        self.assertEqual(textos(datetime(2026, 11, 1, 0, 0, 0))[2], "DOM · 01/11/2026")
        self.assertEqual(textos(datetime(2026, 10, 31, 9, 30, 59))[2], "SÁB · 31/10/2026")


class TesteRelogioNoCaixa(BaseCaixaQt):
    def test_caixa_mostra_o_relogio_no_topo_e_ele_anda(self):
        j = self.janela()
        self.assertTrue(j.relogio.isVisibleTo(j))
        self.assertTrue(j.relogio.timer.isActive())
        self.assertEqual(j.relogio.timer.interval(), 1000)
        instantes = iter([datetime(2026, 10, 26, 23, 59, 59), datetime(2026, 10, 27, 0, 0, 0)])
        j.relogio._agora = lambda: next(instantes)
        j.relogio.atualizar()
        self.assertEqual((j.relogio.lbl_hora.text(), j.relogio.lbl_seg.text()), ("23:59", "59"))
        j.relogio.atualizar()                                                  # virou o dia
        self.assertEqual((j.relogio.lbl_hora.text(), j.relogio.lbl_data.text()), ("00:00", "TER · 27/10/2026"))

    def test_relogio_segue_o_modo_claro_e_escuro(self):
        for modo in ("claro", "escuro"):
            self.banco.cfg_set("tema_visual", modo)
            j = self.janela()
            self.assertIn("QLabel#relogio_hora", j.styleSheet())


if __name__ == "__main__":
    unittest.main()
