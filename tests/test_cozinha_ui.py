"""Painel da Cozinha/Bar (módulo usar_cozinha_bar): tela src/ui/cozinha_ui.py."""
from __future__ import annotations

import unittest

from src.controllers.config_controller import modulos_desligados
from tests.test_ui import BaseUI
from tests.ui_robo import clicar


class TesteJanelaCozinha(BaseUI):
    def setUp(self):
        super().setUp()
        self.banco.executar("UPDATE subgrupos SET impressora_remota = 1")
        self.abrir_turno()

    def item_pendente(self) -> int:
        vid = self.ctx.caixa.abrir_balcao()
        return self.ctx.caixa.adicionar_item(vid, self.skol, 1)

    def test_lista_item_pendente_e_marca_pronto(self):
        from src.ui.cozinha_ui import JanelaCozinha
        item = self.item_pendente()
        j = JanelaCozinha(self.root, self.ctx)
        j.update()
        self.assertEqual(j.grade.total(), 1)
        j.grade.selecionar(item)
        clicar(j, "Marcar pronto")
        j.update()
        self.assertEqual(j.grade.total(), 0)
        self.assertEqual(self.banco.valor("SELECT status_preparo FROM itens_venda WHERE id = ?", (item,)), "entregue")
        j.destroy()
        self.sem_travar()

    def test_duplo_clique_avanca_um_estagio(self):
        from src.ui.cozinha_ui import JanelaCozinha
        item = self.item_pendente()
        j = JanelaCozinha(self.root, self.ctx)
        j.update()
        j.grade.selecionar(item)
        j.avancar()
        j.update()
        self.assertEqual(self.banco.valor("SELECT status_preparo FROM itens_venda WHERE id = ?", (item,)), "em_preparo")
        j.destroy()
        self.sem_travar()


class TesteModuloCozinhaNoMenu(BaseUI):
    def test_desligado_some_e_ligado_aparece(self):
        self.banco.cfg_set("usar_cozinha_bar", "N")
        fora = modulos_desligados(self.banco)
        self.assertIn("util_cozinha", fora)
        self.assertIn("cad_setores_impressao", fora)
        self.banco.cfg_set("usar_cozinha_bar", "S")
        fora = modulos_desligados(self.banco)
        self.assertNotIn("util_cozinha", fora)
        self.assertNotIn("cad_setores_impressao", fora)


if __name__ == "__main__":
    unittest.main()
