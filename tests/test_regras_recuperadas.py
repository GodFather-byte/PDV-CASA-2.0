"""Regras de configuração e de alerta de gaveta, testadas direto no controlador e no Qt."""
from __future__ import annotations

import unittest

from src.controllers.config_controller import ConfigController
from src.core.erros import ErroValidacao
from tests.base import BaseTeste

try:
    from tests.test_qt_caixa import BaseCaixaQt
except ImportError:                                   # sem PySide6 só rodam as regras de controlador
    BaseCaixaQt = None


class TesteConfiguracaoRecuperada(BaseTeste):
    def setUp(self):
        super().setUp()
        self.cfg = ConfigController(self.banco)

    def test_vias_do_fechamento_ficam_entre_1_e_3(self):
        for valida in ("1", "2", "3"):
            self.cfg.salvar_config({"vias_fechamento": valida})
            self.assertEqual(self.banco.cfg("vias_fechamento"), valida)
        for invalida in ("0", "4", "-1"):
            with self.subTest(vias=invalida), self.assertRaises(ErroValidacao):
                self.cfg.salvar_config({"vias_fechamento": invalida})
        self.assertEqual(self.banco.cfg("vias_fechamento"), "3")

    def test_limite_da_gaveta_tem_teto(self):
        with self.assertRaises(ErroValidacao):
            self.cfg.salvar_config({"limite_gaveta": "1000001"})

    def test_cadastro_da_casa_exige_o_nome(self):
        for vazio in ("", "   ", None):
            with self.subTest(nome=vazio), self.assertRaises(ErroValidacao):
                self.cfg.cadastrar_loja({"nome_fantasia": vazio})
        self.assertFalse(self.cfg.loja_cadastrada())

    def test_nome_da_casa_cadastrado_sai_no_cabecalho(self):
        self.cfg.cadastrar_loja({"nome_fantasia": "  Boate Estrela  "})
        self.assertTrue(self.cfg.loja_cadastrada())
        self.assertEqual(self.cfg.nome_loja(), "Boate Estrela")


@unittest.skipIf(BaseCaixaQt is None, "PySide6 indisponível")
class TesteAlertaDeGavetaQt(BaseCaixaQt if BaseCaixaQt else object):
    def setUp(self):
        super().setUp()
        self.turno = self.abrir_turno(10000)                 # fundo de R$ 100,00 na gaveta
        self.caixa = self.janela()

    def test_sem_limite_configurado_nunca_avisa(self):
        self.assertEqual(self.caixa._alerta_gaveta(), "")

    def test_no_limite_nao_avisa_e_acima_pede_sangria_sem_revelar_o_saldo(self):
        self.banco.cfg_set("limite_gaveta", "100")
        self.assertEqual(self.caixa._alerta_gaveta(), "")
        self.banco.cfg_set("limite_gaveta", "99")
        alerta = self.caixa._alerta_gaveta()
        self.assertIn("passou de R$ 99,00", alerta)
        self.assertIn("sangria", alerta)
        self.assertNotIn("100,00", alerta)                   # o dinheiro esperado não é revelado

    def test_a_sangria_derruba_o_alerta(self):
        self.banco.cfg_set("limite_gaveta", "99")
        self.assertNotEqual(self.caixa._alerta_gaveta(), "")
        self.ctx.turnos.movimentar(self.turno, self.ctx.operador_id, "saida", 5000, "sangria")
        self.assertEqual(self.caixa._alerta_gaveta(), "")


if __name__ == "__main__":
    unittest.main()
