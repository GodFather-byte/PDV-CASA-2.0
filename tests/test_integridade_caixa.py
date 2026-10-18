"""O que o caixa não pode perder nem reescrever: desconto ao juntar mesas, observação de cupom já emitido e a
numeração dos cupons depois da limpeza do movimento."""
from __future__ import annotations

import tempfile

from src.controllers.utilitario_controller import UtilitarioController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from tests.test_caixa import BaseCaixa


class TesteDescontoAoJuntarMesas(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("cobra_servico_mesa", "N")
        self.banco.cfg_set("usar_desconto", "S")

    def test_desconto_em_valor_da_origem_vai_para_o_destino(self):
        m12 = self.vender((self.skol, 5), mesa=12)                     # R$ 40,00
        self.caixa.definir_desconto(m12, valor_cent=1000)              # R$ 10,00 de desconto
        m25 = self.vender((self.agua, 1), mesa=25)                     # R$ 3,50
        self.caixa.transferir_mesa(12, 25)
        v = self.caixa.obter(m25)
        self.assertEqual((v["subtotal_cent"], v["desconto_cent"], v["total_cent"]), (4350, 1000, 3350))

    def test_descontos_das_duas_se_somam_mesmo_em_percentual(self):
        m12 = self.vender((self.skol, 5), mesa=12)                     # R$ 40,00
        self.caixa.definir_desconto(m12, pct=10)                       # R$ 4,00
        m25 = self.vender((self.skol, 5), mesa=25)                     # R$ 40,00
        self.caixa.definir_desconto(m25, valor_cent=500)               # R$ 5,00
        self.caixa.transferir_varias([12], 25)
        v = self.caixa.obter(m25)
        self.assertEqual((v["desconto_cent"], v["total_cent"]), (900, 8000 - 900))

    def test_sem_desconto_nada_muda(self):
        self.vender((self.skol, 1), mesa=12)
        m25 = self.vender((self.skol, 1), mesa=25)
        self.caixa.definir_desconto(m25, pct=50)
        self.caixa.transferir_mesa(12, 25)
        v = self.caixa.obter(m25)
        self.assertEqual((v["desconto_pct"], v["desconto_cent"]), (50, 800))     # o percentual do destino continua valendo


class TesteObservacaoDeCupomEmitido(BaseCaixa):
    def test_nao_altera_item_de_venda_fechada(self):
        v = self.vender((self.skol, 1))
        item = self.caixa.itens(v)[0]["id"]
        self.caixa.definir_observacao(item, "sem gelo")                # venda aberta: pode
        self.pagar(v, "Dinheiro", 800)
        self.caixa.fechar(v)
        with self.assertRaises(ErroNegocio):
            self.caixa.definir_observacao(item, "alterado depois")
        self.assertEqual(self.banco.valor("SELECT observacao FROM itens_venda WHERE id = ?", (item,)), "sem gelo")

    def test_item_inexistente(self):
        with self.assertRaises(ErroNegocio):
            self.caixa.definir_observacao(999, "x")


class TesteNumeracaoDosCupons(BaseCaixa):
    def setUp(self):
        super().setUp()
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.banco.cfg_set("pasta_backup", pasta.name)

    def fechar_venda(self):
        v = self.vender((self.skol, 1))
        self.pagar(v, "Dinheiro", 800)
        return self.caixa.fechar(v)["cupom"]

    def test_limpeza_nao_reinicia_a_numeracao(self):
        self.turnos.fechar(self.turno, self.adm, 10000)
        self.avancar(days=-10)
        antigo = self.turnos.abrir(self.adm, 2, 0)
        self.assertEqual([self.fechar_venda() for _ in range(3)], [1, 2, 3])
        self.turnos.fechar(antigo, self.adm, 2400)
        self.avancar(days=10)
        UtilitarioController(self.banco, self.adm).limpar_movimento(fmt.fmt_data(fmt.somar_dias(fmt.hoje(), -2)))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas"), 0)
        novo = self.turnos.abrir(self.adm, 3, 0)
        self.assertEqual(self.turnos.obter(novo)["cupom_inicial"], 4)
        self.assertEqual(self.fechar_venda(), 4)
