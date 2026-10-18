"""Pagamentos lançados antes do fechamento da conta (adiantamentos): não podem sumir numa transferência
de mesa, e contam no turno em que o dinheiro entrou, não no turno em que a conta foi fechada."""
from __future__ import annotations

import os
import tempfile
import unittest

from src.controllers.caixa_controller import CaixaController
from src.controllers.cadastro_controller import CadastroController
from src.controllers.turno_controller import TurnoController
from src.controllers.utilitario_controller import UtilitarioController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.database.esquema import VERSAO_ESQUEMA
from tests.base import BaseTeste
from tests.test_caixa import BaseCaixa

FUNDO = 10000   # fundo de caixa de R$ 100,00 dos turnos abertos em BaseCaixa e nestes testes


class BaseAdiantamento(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("cobra_servico_mesa", "N")      # sem os 10%: os valores dos testes ficam redondos

    def pagos(self, vid) -> int:
        return sum(p["valor_cent"] for p in self.caixa.pagamentos(vid))

    def trocar_turno(self, entregue: int, numero: int = 2) -> dict:
        """Fecha o turno atual declarando `entregue` e abre o próximo com o fundo padrão."""
        res = self.turnos.fechar(self.turno, self.adm, entregue)
        self.turno = self.turnos.abrir(self.adm, numero, FUNDO)
        return res


class TesteTransferenciaComPagamento(BaseAdiantamento):
    def test_juntar_mesas_leva_o_pagamento_para_o_destino(self):
        m12 = self.vender((self.skol, 2), mesa=12)          # R$ 16,00
        m25 = self.vender((self.agua, 1), mesa=25)          # R$ 3,50
        self.pagar(m12, "Dinheiro", 1000)                   # adiantou R$ 10,00 e o operador saiu com Esc
        destino = self.caixa.transferir_mesa(12, 25)
        self.assertEqual(destino, m25)
        self.assertEqual(self.pagos(m25), 1000)
        self.assertEqual(self.caixa.liquidar(m25)["falta"], 950)
        self.pagar(m25, "Dinheiro", 950)
        v = self.caixa.fechar(m25)
        self.assertEqual((v["status"], v["total_cent"], v["pago_cent"]), ("fechada", 1950, 1950))
        self.assertEqual(self.turnos.resumo(self.turno)["esperado"], FUNDO + 1950)

    def test_transferir_varias_leva_os_pagamentos(self):
        m12 = self.vender((self.skol, 1), mesa=12)          # R$ 8,00
        m13 = self.vender((self.agua, 1), mesa=13)          # R$ 3,50
        self.pagar(m12, "Dinheiro", 500)
        self.pagar(m13, "Pix", 350)
        destino = self.caixa.transferir_varias([12, 13], 30)
        self.assertEqual(sorted(p["valor_cent"] for p in self.caixa.pagamentos(destino)), [350, 500])
        self.assertEqual(self.caixa.liquidar(destino)["falta"], 300)

    def test_mover_mesa_para_posicao_livre_mantem_o_pagamento(self):
        m12 = self.vender((self.skol, 1), mesa=12)
        self.pagar(m12, "Dinheiro", 500)
        destino = self.caixa.transferir_mesa(12, 40)
        self.assertEqual(self.pagos(destino), 500)

    def test_repique_da_mesa_de_origem_nao_trava_a_transferencia(self):
        self.vender((self.skol, 1), mesa=12)
        m25 = self.vender((self.agua, 1), mesa=25)
        rid = self.turnos.repique(self.turno, self.adm, 12, 500)     # fica ligado à venda aberta da mesa 12
        self.caixa.transferir_mesa(12, 25)
        self.assertEqual(self.banco.valor("SELECT venda_id FROM repiques WHERE id = ?", (rid,)), m25)
        self.assertEqual(self.turnos.resumo(self.turno)["repique"], 500)


class TesteAdiantamentoEntreTurnos(BaseAdiantamento):
    def test_adiantamento_conta_no_turno_em_que_entrou(self):
        m = self.vender((self.skol, 5), mesa=7)                       # R$ 40,00
        self.pagar(m, "Dinheiro", 2000)                               # R$ 20 entram na gaveta do turno 1
        r1 = self.trocar_turno(FUNDO + 2000)                          # o operador entrega o fundo + os R$ 20
        self.assertEqual((r1["esperado"], r1["resultado"]), (FUNDO + 2000, 0))
        self.pagar(m, "Dinheiro", 2000)                               # o resto é pago no turno 2
        self.caixa.fechar(m)
        r2 = self.turnos.fechar(self.turno, self.adm, FUNDO + 2000)
        self.assertEqual((r2["esperado"], r2["resultado"]), (FUNDO + 2000, 0))

    def test_resumo_explica_adiantamentos_e_o_que_foi_pago_antes(self):
        from src.controllers.impressao_controller import ImpressaoController
        m = self.vender((self.skol, 5), mesa=7)                       # R$ 40,00
        self.pagar(m, "Dinheiro", 1500)
        r1 = self.turnos.resumo(self.turno)
        self.assertEqual((r1["adiantamentos_abertos"], r1["recebido_turno_anterior"]), (1500, 0))
        self.assertIn("Adiant. contas abertas", ImpressaoController(self.banco).fechamento(r1))
        self.trocar_turno(FUNDO + 1500)
        self.pagar(m, "Dinheiro", 2500)
        self.caixa.fechar(m)
        r2 = self.turnos.resumo(self.turno)
        self.assertEqual((r2["adiantamentos_abertos"], r2["recebido_turno_anterior"], r2["venda"]), (0, 1500, 4000))
        fita = ImpressaoController(self.banco).fechamento(r2)
        self.assertIn("Pago em turno anterior", fita)
        self.assertNotIn("Adiant. contas abertas", fita)               # zerado: a linha não aparece

    def test_esperado_ja_conta_o_adiantamento_da_mesa_aberta(self):
        m = self.vender((self.skol, 5), mesa=7)
        self.pagar(m, "Dinheiro", 2000)
        self.assertEqual(self.turnos.dinheiro_esperado(self.turno), FUNDO + 2000)
        self.assertEqual(self.turnos.resumo(self.turno)["esperado"], FUNDO + 2000)

    def test_troco_sai_do_turno_que_fecha_a_conta(self):
        m = self.vender((self.skol, 5), mesa=7)                       # R$ 40,00
        self.pagar(m, "Dinheiro", 2000)
        t1 = self.turno
        self.trocar_turno(FUNDO + 2000)
        self.pagar(m, "Dinheiro", 5000)                               # paga o resto com R$ 50 e leva R$ 30 de troco
        v = self.caixa.fechar(m)
        self.assertEqual(v["troco_cent"], 3000)
        troco_por_turno = {p["turno_id"]: p["troco_cent"] for p in self.caixa.pagamentos(m)}
        self.assertEqual(troco_por_turno, {t1: 0, self.turno: 3000})
        r2 = self.turnos.fechar(self.turno, self.adm, FUNDO + 2000)
        self.assertEqual(r2["resultado"], 0)
        self.assertEqual(self.turnos.resumo(t1)["esperado"], FUNDO + 2000)    # o turno fechado não mudou

    def test_pagamento_de_turno_fechado_nao_pode_ser_removido(self):
        m = self.vender((self.skol, 5), mesa=7)
        self.pagar(m, "Dinheiro", 2000)
        antigo = self.caixa.pagamentos(m)[0]["id"]
        self.trocar_turno(FUNDO + 2000)
        with self.assertRaises(ErroNegocio):
            self.caixa.remover_pagamento(antigo)
        self.pagar(m, "Dinheiro", 1000)
        novo = self.caixa.pagamentos(m)[-1]["id"]
        self.caixa.remover_pagamento(novo)                            # o do turno atual pode ser corrigido
        self.assertEqual(self.pagos(m), 2000)

    def test_cancelar_mesa_com_adiantamento_do_turno_anterior_registra_a_devolucao(self):
        m = self.vender((self.skol, 5), mesa=7)
        self.pagar(m, "Dinheiro", 2000)
        t1 = self.turno
        self.trocar_turno(FUNDO + 2000)
        self.pagar(m, "Dinheiro", 500)                                # este é devolvido da própria gaveta do turno 2
        self.caixa.cancelar_venda(m, "cliente desistiu")
        self.assertEqual(self.caixa.obter(m)["status"], "cancelada")
        r2 = self.turnos.resumo(self.turno)
        self.assertEqual((r2["saidas"], r2["esperado"]), (2000, FUNDO - 2000))
        self.assertIn(f"venda {m}", self.turnos.movimentos(self.turno)[0]["descricao"])
        self.assertEqual(self.turnos.resumo(t1)["esperado"], FUNDO + 2000)    # o turno fechado não mudou

    def test_cancelar_cupom_fechado_com_adiantamento_do_turno_anterior(self):
        m = self.vender((self.skol, 5), mesa=7)
        self.pagar(m, "Dinheiro", 2000)
        t1 = self.turno
        self.trocar_turno(FUNDO + 2000)
        self.pagar(m, "Dinheiro", 2000)
        self.caixa.fechar(m)
        self.caixa.cancelar_venda(m, "erro de lançamento")
        r2 = self.turnos.resumo(self.turno)
        self.assertEqual((r2["saidas"], r2["esperado"]), (2000, FUNDO - 2000))
        self.assertEqual(self.turnos.resumo(t1)["esperado"], FUNDO + 2000)

    def test_adiantamento_fora_da_gaveta_nao_gera_saida(self):
        m = self.vender((self.skol, 5), mesa=7)
        self.pagar(m, "Pix", 2000)
        t1 = self.turno
        self.trocar_turno(FUNDO)
        self.caixa.cancelar_venda(m, "cliente desistiu")
        self.assertEqual(self.turnos.resumo(self.turno)["saidas"], 0)       # o Pix é estornado fora do caixa
        self.assertEqual(self.turnos.resumo(t1)["fora_da_gaveta"], 2000)

    def test_cancelar_no_mesmo_turno_continua_como_antes(self):
        m = self.vender((self.skol, 5), mesa=7)
        self.pagar(m, "Dinheiro", 2000)
        self.caixa.cancelar_venda(m, "cliente desistiu")
        r = self.turnos.resumo(self.turno)
        self.assertEqual((r["saidas"], r["esperado"]), (0, FUNDO))
        self.assertEqual(self.pagos(m), 0)

    def test_sem_turno_aberto_nao_recebe_pagamento(self):
        m = self.vender((self.skol, 5), mesa=7)
        self.turnos.fechar(self.turno, self.adm, FUNDO)
        with self.assertRaises(ErroNegocio):
            self.pagar(m, "Dinheiro", 2000)


class TesteLimpezaComAdiantamento(BaseAdiantamento):
    def setUp(self):
        super().setUp()
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.banco.cfg_set("pasta_backup", self.pasta.name)

    def test_limpeza_mantem_o_turno_antigo_que_recebeu_um_adiantamento(self):
        self.turnos.fechar(self.turno, self.adm, FUNDO)
        self.avancar(days=-10)
        self.turno = self.turnos.abrir(self.adm, 2, FUNDO)
        antigo = self.turno
        m = self.vender((self.skol, 5), mesa=7)
        self.pagar(m, "Dinheiro", 2000)
        self.avancar(days=10)
        self.trocar_turno(FUNDO + 2000, numero=3)
        self.pagar(m, "Dinheiro", 2000)
        self.caixa.fechar(m)
        res = UtilitarioController(self.banco, self.adm).limpar_movimento(fmt.fmt_data(fmt.somar_dias(fmt.hoje(), -2)))
        self.assertEqual(res["vendas"], 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM turnos WHERE id = ?", (antigo,)), 1)
        self.assertEqual(self.turnos.resumo(antigo)["esperado"], FUNDO + 2000)


class TesteMigracaoV9(unittest.TestCase):
    """Bancos v8 não sabiam em que turno cada pagamento entrou: ele herda o turno da venda."""

    def test_v8_ganha_o_turno_do_pagamento(self):
        fmt.definir_relogio(lambda: BaseTeste.agora)
        self.addCleanup(fmt.definir_relogio, None)
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "v8.db")
            b = BancoDados(caminho)
            b.cfg_set("cobra_servico_mesa", "N")
            adm = b.valor("SELECT id FROM operadores WHERE nome = 'ADM'")
            sub = b.valor("SELECT id FROM subgrupos LIMIT 1")
            un = b.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'")
            skol = CadastroController(b).salvar("produtos", {
                "codigo": "1", "nome": "SKOL", "subgrupo_id": sub, "unidade_id": un, "preco_cent": "8,00",
                "controla_estoque": "N"})
            turno = TurnoController(b).abrir(adm, 1, FUNDO)
            caixa = CaixaController(b, adm)
            fechada = caixa.abrir_balcao()
            caixa.adicionar_item(fechada, skol, 1)
            caixa.adicionar_pagamento(fechada, b.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Dinheiro'"), 800)
            caixa.fechar(fechada)
            aberta, _ = caixa.abrir_mesa(3)
            caixa.adicionar_item(aberta, skol, 1)
            caixa.adicionar_pagamento(aberta, b.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Dinheiro'"), 300)
            b.executar("UPDATE pagamentos_venda SET turno_id = NULL")     # como ficava no banco v8
            b.executar("PRAGMA user_version = 8")
            b.fechar()

            b = BancoDados(caminho)
            try:
                self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
                por_venda = {r["venda_id"]: r["turno_id"] for r in b.todos("SELECT venda_id, turno_id FROM pagamentos_venda")}
                # A venda fechada dá o turno ao pagamento; o da mesa aberta segue sem turno e conta onde ela fechar,
                # exatamente como antes da v9.
                self.assertEqual(por_venda, {fechada: turno, aberta: None})
                caixa = CaixaController(b, adm)
                caixa.adicionar_pagamento(aberta, b.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Dinheiro'"), 500)
                caixa.fechar(aberta)
                self.assertEqual({r["turno_id"] for r in b.todos("SELECT turno_id FROM pagamentos_venda")}, {turno})
                self.assertEqual(TurnoController(b).resumo(turno)["esperado"], FUNDO + 1600)
            finally:
                b.fechar()


if __name__ == "__main__":
    unittest.main()
