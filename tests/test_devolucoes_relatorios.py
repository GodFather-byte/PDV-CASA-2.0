"""Reembolsos pela própria data/turno, sem reescrever bruto nem duplicar saída da gaveta."""
from uuid import uuid4

from src.controllers.relatorio_controller import RelatorioController
from tests.test_caixa import BaseCaixa


class TesteDevolucoesRelatorios(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.rel = RelatorioController(self.banco)

    def venda_fechada(self, forma="Dinheiro"):
        venda = self.vender((self.skol, 2))
        self.pagar(venda, forma, 1600)
        self.caixa.fechar(venda)
        return venda

    def devolver(self, venda, externo=False):
        item = self.caixa.itens(venda)[0]["id"]
        return self.caixa.devolver(
            venda, [{"item_id": item, "quantidade": 1, "retorna_estoque": True}],
            "Devolução de homologação", autorizado_por=self.adm,
            reembolso_modo="externo" if externo else "dinheiro_gaveta", uuid=str(uuid4()),
            tipo_pagamento_id=self.tipo("Pix") if externo else None,
            referencia_externa="PIX-HOMOLOGACAO-123" if externo else None)

    def test_bruto_preservado_reembolso_separado_e_gaveta_sem_dupla_deducao(self):
        venda = self.venda_fechada()
        self.devolver(venda)
        self.assertEqual(self.banco.valor("SELECT total_cent FROM vendas WHERE id = ?", (venda,)), 1600)
        vendas = self.rel.vendas_periodo({})
        self.assertEqual(dict(vendas.rodape)["Venda total"], "16,00")
        self.assertTrue(any("Bruto histórico" in nota for nota in vendas.criterios))
        devolucoes = self.rel.devolucoes({})
        self.assertEqual(len(devolucoes.linhas), 1)
        self.assertEqual(devolucoes.linhas[0][6], "8,00")
        self.assertEqual(dict(devolucoes.rodape)["Dinheiro da gaveta (já registrado em saídas)"], "8,00")
        movimentos = self.rel.caixa_movimentos({})
        self.assertEqual([r[2] for r in movimentos.linhas], ["Reembolso"])
        self.assertEqual(dict(movimentos.rodape)["Total de saídas (sangrias/reembolsos)"], "8,00")
        self.assertEqual(self.turnos.resumo(self.turno)["esperado"], 10800)

    def test_corte_operacional_e_data_do_reembolso_nao_data_da_venda(self):
        venda = self.venda_fechada()
        self.avancar(hours=9)  # 04/10 06:00, exatamente a virada operacional
        self.devolver(venda)
        self.assertEqual(self.rel.devolucoes({"de": "2026-10-03", "ate": "2026-10-03"}).linhas, [])
        self.assertEqual(len(self.rel.devolucoes({"de": "2026-10-04", "ate": "2026-10-04"}).linhas), 1)
        self.assertEqual(dict(self.rel.vendas_periodo(
            {"de": "2026-10-03", "ate": "2026-10-03"}).rodape)["Venda total"], "16,00")

    def test_externo_declarado_nao_gera_saida_da_gaveta(self):
        venda = self.venda_fechada("Pix")
        self.devolver(venda, externo=True)
        rel = self.rel.devolucoes({})
        self.assertEqual(rel.linhas[0][4], "Externo declarado")
        self.assertEqual(rel.linhas[0][8], "PIX-HOMOLOGACAO-123")
        self.assertEqual(dict(rel.rodape)["Externo declarado, sem comprovação bancária"], "8,00")
        self.assertEqual(self.rel.caixa_movimentos({}).linhas, [])
        self.assertEqual(self.turnos.resumo(self.turno)["esperado"], 10000)

    def test_filtro_turno_usa_turno_do_reembolso(self):
        venda = self.venda_fechada()
        self.turnos.fechar(self.turno, self.adm, 11600)
        self.turnos.abrir(self.adm, 2, 10000)
        self.devolver(venda)
        self.assertEqual(self.rel.devolucoes({"turno": 1}).linhas, [])
        linhas = self.rel.devolucoes({"turno": 2, "operador_id": self.adm}).linhas
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0][2], "2")
