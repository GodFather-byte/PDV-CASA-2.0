"""Fechamento para passar o caixa: tudo o que aconteceu no turno, do que vendeu às saídas sem consumo."""
from __future__ import annotations

from src.controllers.comissao_controller import ComissaoController
from src.controllers.impressao_controller import ImpressaoController
from tests.test_caixa import BaseCaixa


class TesteFechamentoCompleto(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("cobra_servico_mesa", "N")
        self.banco.cfg_set("cobra_servico_comanda", "N")

    def fechar(self, vid, valor):
        self.pagar(vid, "Dinheiro", valor)
        self.caixa.fechar(vid)

    def montar_turno(self):
        self.fechar(self.vender((self.skol, 3)), 2400)                              # balcão: 3 SKOL
        c, _ = self.caixa.abrir_mesa(180, comanda=True)
        self.caixa.adicionar_item(c, self.skol, 2)
        self.caixa.adicionar_item(c, self.agua, 1)
        self.fechar(c, 1950)                                                         # comanda: 2 SKOL + 1 AGUA
        cancelado = self.vender((self.agua, 4))
        self.fechar(cancelado, 1400)
        self.caixa.cancelar_venda(cancelado, "erro")                                 # não conta nos produtos
        self.caixa.liberar_saida(True, 77)                                           # 1002
        ComissaoController(self.banco).lancar(180, 1500, self.turno, self.adm)

    def test_resumo_traz_produtos_tipos_e_saidas(self):
        self.montar_turno()
        r = self.turnos.resumo(self.turno)
        self.assertEqual([(p["produto"], p["quantidade"], p["total_cent"]) for p in r["produtos_vendidos"]],
                         [("SKOL", 5, 4000), ("AGUA", 1, 350)])
        self.assertEqual([(t["tipo"], t["cupons"], t["total_cent"]) for t in r["vendas_por_tipo"]],
                         [("Balcão", 1, 2400), ("Comandas", 1, 1950)])
        self.assertEqual([s["local"] for s in r["saidas_liberadas"]], ["Comanda 77"])

    def test_fita_do_fechamento_tem_tudo(self):
        self.banco.atualizar("loja", 1, {"nome_fantasia": "Boate Estrela"})
        self.montar_turno()
        res = self.turnos.fechar(self.turno, self.adm, 10000 + 2400 + 1950)
        fita = ImpressaoController(self.banco).fechamento(res)
        for trecho in ("BOATE ESTRELA", "FECHAMENTO DE TURNO", "VENDAS POR TIPO (2)", "Comandas (1 cupons)",
                       "PRODUTOS VENDIDOS (2)", "5x SKOL", "1x AGUA", "Total dos produtos", "CUPONS CANCELADOS (1)",
                       "SAÍDAS SEM CONSUMO (1002) (1)", "C77", "COMISSÕES DAS GAROTAS", "CAIXA CONFERIDO"):
            self.assertIn(trecho, fita)

    def test_turno_vazio_nao_imprime_secoes_vazias(self):
        res = self.turnos.fechar(self.turno, self.adm, 10000)
        fita = ImpressaoController(self.banco).fechamento(res)
        for ausente in ("PRODUTOS VENDIDOS", "VENDAS POR TIPO", "SAÍDAS SEM CONSUMO", "Desconto (-)"):
            self.assertNotIn(ausente, fita)
        self.banco.cfg_set("usar_desconto", "S")
        self.assertIn("Desconto (-)", ImpressaoController(self.banco).fechamento(res))
