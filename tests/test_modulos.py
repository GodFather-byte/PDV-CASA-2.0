"""Módulos que a boate não usa (delivery, caderneta e contas a pagar) vêm desligados e se ligam em
Configurações > Módulos: desligados, somem dos menus, da barra do caixa e das linhas zeradas do fechamento."""
from __future__ import annotations

import unittest

from src.controllers.config_controller import CAMPOS_CONFIG, modulos_desligados
from src.controllers.impressao_controller import ImpressaoController
from tests.test_caixa import BaseCaixa
from tests.test_ui import BaseUI


class TesteModulosNoBanco(BaseCaixa):
    def test_vem_desligados(self):
        for chave in ("usar_delivery", "usar_caderneta", "usar_contas"):
            self.assertFalse(self.banco.cfg_bool(chave, True), chave)

    def test_estao_na_aba_modulos_das_configuracoes(self):
        secoes = {c[0]: c[3] for c in CAMPOS_CONFIG}
        for chave in ("usar_delivery", "usar_caderneta", "usar_contas", "taxa_entrega_padrao"):
            self.assertEqual(secoes[chave], "Módulos")

    def test_desligados_somem_dos_menus(self):
        fora = modulos_desligados(self.banco)
        for mod in ("lanc_contas", "rel_financeiro", "cad_plano_contas", "cad_subplanos", "cad_bairros",
                    "cad_clientes", "rel_clientes"):
            self.assertIn(mod, fora)
        self.assertNotIn("lanc_estoque", fora)          # o lançamento de estoque fica sempre
        self.assertNotIn("rel_estoque", fora)

    def test_ligar_cada_um_devolve_os_seus_menus(self):
        self.banco.cfg_set("usar_contas", "S")
        fora = modulos_desligados(self.banco)
        self.assertNotIn("lanc_contas", fora)
        self.assertIn("cad_clientes", fora)
        self.banco.cfg_set("usar_caderneta", "S")
        fora = modulos_desligados(self.banco)
        self.assertNotIn("cad_clientes", fora)          # caderneta precisa do cadastro de clientes
        self.assertIn("cad_bairros", fora)               # bairros são só do delivery
        self.banco.cfg_set("usar_delivery", "S")
        self.assertEqual(modulos_desligados(self.banco), set())

    def test_fita_do_fechamento_sem_linhas_de_caderneta(self):
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Dinheiro", 800)
        self.caixa.fechar(vid)
        imp = ImpressaoController(self.banco)
        texto = imp.fechamento(self.turnos.resumo(self.turno))
        self.assertNotIn("caderneta", texto.lower())
        self.banco.cfg_set("usar_caderneta", "S")
        self.assertIn("Venda caderneta", imp.fechamento(self.turnos.resumo(self.turno)))


class TesteModulosNaTela(BaseUI):
    def setUp(self):
        super().setUp()
        for chave in ("usar_delivery", "usar_caderneta", "usar_contas"):
            self.banco.cfg_set(chave, "N")               # o padrão da boate
        self.abrir_turno()

    def abrir_caixa(self):
        from src.ui.caixa_ui import JanelaCaixa
        cx = JanelaCaixa(self.root, self.ctx)
        cx.update()
        self.addCleanup(lambda: cx.winfo_exists() and cx.destroy())
        return cx

    def test_barra_do_caixa_sem_delivery_e_caderneta(self):
        nomes = [t[0] for t in self.abrir_caixa().tarefas]
        self.assertNotIn("Delivery (F6)", nomes)
        self.assertNotIn("Caderneta (F5)", nomes)
        self.assertIn("Pagar (F12)", nomes)

    def test_f5_e_f6_nao_abrem_nada(self):
        cx = self.abrir_caixa()
        for classe in ("Dialogo", "JanelaClientes"):      # se algo abrisse, o robô fecha (e o teste acusa)
            self.robo.quando(classe, lambda w: w.destroy(), vezes=2)
        cx.caderneta()
        cx.entrega()
        self.assertEqual(self.robo.log, [])
        self.assertIsNone(cx.venda_id)

    def test_ligados_voltam_para_a_barra(self):
        self.banco.cfg_set("usar_delivery", "S")
        self.banco.cfg_set("usar_caderneta", "S")
        nomes = [t[0] for t in self.abrir_caixa().tarefas]
        self.assertIn("Delivery (F6)", nomes)
        self.assertIn("Caderneta (F5)", nomes)


if __name__ == "__main__":
    unittest.main()
