"""Alterar a quantidade de uma linha no caixa: aumenta na mesma linha, diminui como cancelamento parcial, atacado recalculado."""
from __future__ import annotations

import json

from src.controllers.perfil_controller import PerfilController
from src.core.erros import ErroNegocio
from tests.test_caixa import BaseCaixa
from tests.test_caixa_cancelamento_parcial import criar_vinculos


class TesteAlterarQuantidade(BaseCaixa):
    def setUp(self):
        super().setUp()
        criar_vinculos(self.banco)
        PerfilController(self.banco, self.adm).aplicar("adega")
        self.banco.executar("UPDATE produtos SET atacado_qtd = 6, preco_atacado_cent = 650 WHERE id = ?", (self.skol,))
        self.vid = self.caixa.abrir_balcao()

    def linha(self, item_id):
        return dict(self.banco.um("SELECT * FROM itens_venda WHERE id = ?", (item_id,)))

    def test_aumentar_atinge_o_atacado_e_diminuir_sai_dele(self):
        item = self.caixa.adicionar_item(self.vid, self.skol, 4)
        self.assertEqual(self.caixa.alterar_quantidade(item, 6), item)
        linha = self.linha(item)
        self.assertEqual((linha["quantidade"], linha["preco_unit_cent"], linha["total_cent"]), (6, 650, 3900))
        self.assertEqual(self.caixa.obter(self.vid)["total_cent"], 3900)
        regra = json.loads(linha["regra_preco_json"])
        self.assertEqual(regra["leituras"][-1]["quantidade"], 2)
        self.assertTrue(regra["faixa_atingida"])
        with self.assertRaises(ErroNegocio):
            self.caixa.alterar_quantidade(item, 4)                          # diminuir sem motivo
        self.caixa.alterar_quantidade(item, 4, "cliente desistiu de 2")
        linha = self.linha(item)
        self.assertEqual((linha["quantidade"], linha["preco_unit_cent"], linha["total_cent"]), (4, 800, 3200))
        cancelada = self.banco.um("SELECT quantidade FROM itens_venda WHERE venda_id = ? AND cancelado = 1", (self.vid,))
        self.assertEqual(cancelada["quantidade"], 2)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM auditoria_eventos WHERE acao = 'quantidade_aumentada'"), 1)

    def test_mesma_quantidade_zero_e_fracao(self):
        item = self.caixa.adicionar_item(self.vid, self.skol, 2)
        self.assertEqual(self.caixa.alterar_quantidade(item, 2), item)
        for invalida in (0, -1, 2.5):
            with self.assertRaises(ErroNegocio):
                self.caixa.alterar_quantidade(item, invalida, "x")
        self.assertEqual(self.linha(item)["quantidade"], 2)

    def test_casco_e_item_pago_por_item_nao_aumentam(self):
        casco = self.novo_produto("CASCO 600ML", 300)
        self.banco.executar("UPDATE produtos SET casco_produto_id = ? WHERE id = ?", (casco, self.skol))
        item = self.caixa.adicionar_item(self.vid, self.skol, 2)
        with self.assertRaisesRegex(ErroNegocio, "lance o produto de novo"):
            self.caixa.alterar_quantidade(item, 3)
        self.caixa.alterar_quantidade(item, 1, "quebrou")                   # diminuir continua valendo
        self.assertEqual(self.linha(item)["quantidade"], 1)

    def test_venda_fechada_nao_muda(self):
        item = self.caixa.adicionar_item(self.vid, self.agua, 1)
        self.pagar(self.vid, "Dinheiro", 350)
        self.caixa.fechar(self.vid)
        with self.assertRaises(ErroNegocio):
            self.caixa.alterar_quantidade(item, 2)


class TesteAlterarQuantidadeNaMesa(BaseCaixa):
    def test_mesa_aumenta_com_total_proporcional(self):
        vid = self.vender((self.agua, 1), mesa=5)
        item = self.caixa.itens(vid)[0]["id"]
        self.caixa.alterar_quantidade(item, 3)
        linha = self.banco.um("SELECT quantidade, total_cent FROM itens_venda WHERE id = ?", (item,))
        self.assertEqual((linha["quantidade"], linha["total_cent"]), (3, 1050))


try:
    from tests.test_qt_caixa import BaseCaixaQt
except ImportError:                                   # pragma: no cover - sem PySide6
    BaseCaixaQt = None

if BaseCaixaQt is not None:
    class TesteAlterarQuantidadeNaTela(BaseCaixaQt):
        def setUp(self):
            super().setUp()
            self.abrir_turno()
            self.novo_produto("SKOL", 800, codigo="101")
            self.j = self.janela()
            self.lancar(self.j, "101", "4")
            self.j.tabela.selectRow(0)

        def test_aumenta_sem_senha_e_diminui_com_motivo(self):
            self.j.dialogos.textos = ["6"]
            self.j.alterar_quantidade()
            self.assertEqual(self.j.tabela.item(0, 4).text(), "6")
            self.j.tabela.selectRow(0)
            self.j.dialogos.textos = ["5", "uma lata amassada"]
            self.j.alterar_quantidade()
            self.assertEqual(self.j.tabela.item(0, 4).text(), "5")
            self.assertIn("6 → 5", self.j.lbl_status.text())
            self.assertIn("Operações", self.j.btn_operacoes.text())
            self.assertIn("quantidade", self.j.acoes)

        def test_sem_item_selecionado_avisa(self):
            self.j.tabela.clearSelection()
            self.j.tabela.setCurrentCell(-1, -1)
            self.j.alterar_quantidade()
            self.assertTrue(self.j.dialogos.avisos)
