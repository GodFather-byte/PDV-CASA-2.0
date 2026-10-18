"""Consumação mínima por comanda: a diferença até o mínimo é cobrada na saída, só de comanda com consumo e dentro da faixa."""
from __future__ import annotations

from src.controllers.config_controller import ConfigController
from src.core.erros import ErroValidacao
from src.core import formatacao as fmt
from tests.test_regras_caixa import BaseRegras


class TesteConsumacaoMinima(BaseRegras):
    def setUp(self):
        super().setUp()
        self.skol = self.novo_produto("SKOL", 1000)          # R$ 10,00
        self.banco.cfg_set("cobra_servico_comanda", "N")     # só o mínimo: o serviço tem testes próprios
        self.banco.cfg_set("cobra_servico_mesa", "N")

    def comanda(self, numero, qtd=1):
        v, _ = self.caixa.abrir_mesa(numero, comanda=True)
        if qtd:
            self.caixa.adicionar_item(v, self.skol, qtd)
        return v

    def test_desligada_de_fabrica(self):
        v = self.comanda(5)
        self.assertEqual(self.caixa.obter(v)["total_cent"], 1000)

    def test_cobra_a_diferenca_ate_o_minimo(self):
        self.banco.cfg_set("consumacao_minima", "50")
        v = self.comanda(5)
        c = self.caixa.obter(v)
        self.assertEqual((c["subtotal_cent"], c["taxa_cent"], c["total_cent"]), (1000, 4000, 5000))
        self.caixa.adicionar_item(v, self.skol, 2)                           # R$ 30: faltam R$ 20
        self.assertEqual(self.caixa.obter(v)["total_cent"], 5000)
        self.caixa.adicionar_item(v, self.skol, 3)                           # R$ 60: passou do mínimo
        c = self.caixa.obter(v)
        self.assertEqual((c["taxa_cent"], c["total_cent"]), (0, 6000))

    def test_cancelar_item_volta_a_cobrar_o_complemento(self):
        self.banco.cfg_set("consumacao_minima", "50")
        v = self.comanda(5, qtd=2)
        extra = self.caixa.adicionar_item(v, self.novo_produto("VODKA", 4000), 1)      # R$ 60 no total
        self.assertEqual(self.caixa.obter(v)["total_cent"], 6000)
        self.caixa.cancelar_item(extra)
        self.assertEqual(self.caixa.obter(v)["total_cent"], 5000)

    def test_comanda_vazia_nao_e_cobrada(self):
        self.banco.cfg_set("consumacao_minima", "50")
        v = self.comanda(180, qtd=0)
        self.assertEqual(self.caixa.obter(v)["total_cent"], 0)

    def test_so_vale_na_faixa_de_comandas(self):
        self.banco.cfg_set("consumacao_minima", "50")
        self.banco.cfg_set("consumacao_minima_de", "1")
        self.banco.cfg_set("consumacao_minima_ate", "100")
        self.assertEqual(self.caixa.obter(self.comanda(50))["total_cent"], 5000)
        self.assertEqual(self.caixa.obter(self.comanda(156))["total_cent"], 1000)      # comanda de garota: fora da faixa

    def test_mesa_e_balcao_nao_sao_cobrados(self):
        self.banco.cfg_set("consumacao_minima", "50")
        mesa, _ = self.caixa.abrir_mesa(5)
        self.caixa.adicionar_item(mesa, self.skol, 1)
        self.assertEqual(self.caixa.obter(mesa)["total_cent"], 1000)
        balcao = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(balcao, self.skol, 1)
        self.assertEqual(self.caixa.obter(balcao)["total_cent"], 1000)

    def test_desconto_nao_burla_o_minimo(self):
        self.banco.cfg_set("consumacao_minima", "50")
        self.banco.cfg_set("usar_desconto", "S")
        v = self.comanda(5, qtd=4)                                          # R$ 40 + R$ 10 de complemento
        self.caixa.definir_desconto(v, pct=50)                              # consumo líquido R$ 20: complemento R$ 30
        self.assertEqual(self.caixa.obter(v)["total_cent"], 5000)

    def test_fecha_e_paga_o_total_com_o_complemento(self):
        self.banco.cfg_set("consumacao_minima", "50")
        v = self.comanda(5)
        self.caixa.adicionar_pagamento(v, self.tipo("Dinheiro"), 5000)
        fechada = self.caixa.fechar(v)
        self.assertEqual((fechada["total_cent"], fechada["troco_cent"]), (5000, 0))
        self.assertEqual(self.turnos.resumo(self.turno)["total_recebido"], 5000)

    def test_total_na_fita_mostra_o_complemento(self):
        from src.controllers.impressao_controller import ImpressaoController
        self.banco.cfg_set("consumacao_minima", "50")
        v = self.comanda(5)
        linhas = ImpressaoController(self.banco)._totais(self.caixa.obter(v), 42)
        self.assertTrue(any("consumação" in l and "40,00" in l for l in linhas), linhas)

    def test_configuracao_aceita_so_numero_nao_negativo(self):
        cfg = ConfigController(self.banco)
        cfg.salvar_config({"consumacao_minima": "50"})
        self.assertEqual(self.banco.cfg_int("consumacao_minima"), 50)
        with self.assertRaises(ErroValidacao):
            cfg.salvar_config({"consumacao_minima": "-5"})


class TesteSangriaPorHorario(BaseRegras):
    """Lembrete: o horário combinado passou neste turno e ninguém fez sangria depois dele."""

    def agora_em(self, texto):
        from datetime import datetime
        return datetime.fromisoformat(texto)

    def test_sem_horarios_nao_lembra(self):
        self.assertIsNone(self.turnos.sangria_do_horario(self.turno, self.agora_em("2026-10-04 03:00:00")))

    def test_lembra_depois_do_horario_e_para_apos_a_sangria(self):
        self.banco.cfg_set("sangria_horarios", "02:00, 04:30")
        self.assertIsNone(self.turnos.sangria_do_horario(self.turno, self.agora_em("2026-10-03 23:00:00")))   # nada venceu
        self.assertEqual(self.turnos.sangria_do_horario(self.turno, self.agora_em("2026-10-04 02:10:00")), "02:00")
        self.avancar(hours=5, minutes=15)                                  # 02:15 do dia 04
        self.turnos.movimentar(self.turno, self.adm, "saida", 5000, "sangria")
        self.assertIsNone(self.turnos.sangria_do_horario(self.turno, self.agora_em("2026-10-04 02:30:00")))   # já fez
        self.assertEqual(self.turnos.sangria_do_horario(self.turno, self.agora_em("2026-10-04 04:40:00")), "04:30")

    def test_horario_invalido_e_ignorado(self):
        from src.controllers.turno_controller import _horarios
        self.assertEqual(_horarios("02:00; 4h30, 25:00, abc 12:99"), [(2, 0), (4, 30)])


class TesteAuditoriaPorOperador(BaseRegras):
    def test_quadro_por_operador_com_cancelamentos_e_sangrias(self):
        from src.controllers.relatorio_controller import RelatorioController
        skol = self.novo_produto("SKOL", 1000)
        self.vender(skol, 2, [("Dinheiro", 2000)])                    # R$ 20 vendidos
        v = self.caixa.abrir_balcao()
        item = self.caixa.adicionar_item(v, skol, 1)
        self.caixa.cancelar_item(item, "errado")
        self.caixa.cancelar_venda(v, "desistiu")
        self.turnos.movimentar(self.turno, self.adm, "saida", 5000, "sangria")
        hoje = fmt.hoje()
        rel = RelatorioController(self.banco).auditoria_operadores({"de": hoje, "ate": hoje})
        linha = rel.linhas[0]
        self.assertEqual((linha[0], linha[1], linha[2]), ("ADM", "1", "20,00"))
        self.assertEqual((linha[5], linha[6], linha[7]), ("1", "1", "50,00"))       # cupom, item e sangria
        self.assertEqual(rel.linhas[-1][0], "TOTAL")
