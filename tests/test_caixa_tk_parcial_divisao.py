"""Caixa Tk: cancelamento parcial por quantidade e divisão da conta por item (as perguntas são roteirizadas)."""
from __future__ import annotations

from unittest import mock

from src.ui import tema
from tests.test_caixa_cancelamento_parcial import criar_vinculos
from tests.test_ui import BaseUI


class Roteiro:
    """Respostas no lugar de tema.pedir_texto/confirmar/escolher; a validação da tela roda como no diálogo real."""

    def __init__(self, textos=(), confirmacoes=(), escolhas=()):
        self.textos, self.confirmacoes, self.escolhas = list(textos), list(confirmacoes), list(escolhas)
        self.rotulos, self.recusas, self.opcoes = [], [], []

    def pedir_texto(self, master, titulo, rotulo, inicial="", senha=False, largura=34, validar=None):
        self.rotulos.append((rotulo, inicial))
        while self.textos:
            v = self.textos.pop(0)
            if v is None or validar is None:
                return v
            try:
                return validar(v)
            except ValueError as e:
                self.recusas.append(str(e))
        raise AssertionError(f"Pergunta inesperada: {rotulo}")

    def confirmar(self, master, texto, *a, **k):
        self.rotulos.append((texto, ""))
        if not self.confirmacoes:
            raise AssertionError(f"Confirmação inesperada: {texto}")
        return self.confirmacoes.pop(0)

    def escolher(self, master, titulo, opcoes, *a, **k):
        self.opcoes.append(list(opcoes))
        return self.escolhas.pop(0) if self.escolhas else None

    def __enter__(self):
        self._patches = [mock.patch.object(tema, nome, getattr(self, nome))
                         for nome in ("pedir_texto", "confirmar", "escolher")]
        self._patches.append(mock.patch.object(tema, "erro", lambda m, t, *a, **k: self.recusas.append(t)))
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


class TesteCaixaTkParcialDivisao(BaseUI):
    def setUp(self):
        super().setUp()
        criar_vinculos(self.banco)
        self.abrir_turno()
        self.queijo = self.ctx.cadastros.salvar("produtos", {
            "codigo": "3", "nome": "QUEIJO", "subgrupo_id": self.banco.valor("SELECT id FROM subgrupos"),
            "unidade_id": self.banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'"),
            "preco_cent": "10,00", "aceita_decimal": "S"})
        from src.ui.caixa_ui import JanelaCaixa
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()

    def lancar(self, cod, qtd):
        self.cx.var_cod.set(cod); self.cx._enter_codigo(); self.cx.update()
        self.cx.var_qtd.set(str(qtd)); self.cx.confirmar_item(); self.cx.update()

    def cancelar(self, indice, **roteiro):
        self.cx.grade.selecionar_indice(indice)
        with Roteiro(**roteiro) as r:
            self.cx.cancelar_item_selecionado(); self.cx.update()
        return r

    def linhas(self):
        return [tuple(x) for x in self.banco.todos(
            "SELECT produto_id, quantidade, total_cent, cancelado FROM itens_venda ORDER BY id")]

    def test_cancelamento_parcial_pede_quantidade_e_motivo(self):
        self.lancar("1", 5)
        r = self.cancelar(0, textos=["9", "2", "", "cliente desistiu"], confirmacoes=[True])
        self.assertEqual(r.recusas, ["Informe de 0 a 5.", "Informe o motivo."])
        self.assertEqual(r.rotulos[1][1], "5")                       # sugere a quantidade lançada
        self.assertEqual(self.linhas(), [(self.skol, 3, 2400, 0), (self.skol, 2, 1600, 1)])
        self.assertEqual(self.cx.lbl_total.cget("text"), "24,00")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM auditoria_eventos WHERE acao = 'cancelamento_parcial'"), 1)
        self.sem_travar()

    def test_fracionado_e_quantidade_total(self):
        self.lancar("3", "1,5")
        r = self.cancelar(0, textos=["0,75", "estragou"], confirmacoes=[True])
        self.assertEqual(self.linhas(), [(self.queijo, 0.75, 750, 0), (self.queijo, 0.75, 750, 1)])
        self.lancar("1", 2)
        r = self.cancelar(1, textos=["1,5", "2"], confirmacoes=[True])   # SKOL não aceita fração; tudo: sem motivo
        self.assertIn("Este produto não aceita quantidade fracionada.", r.recusas)
        self.assertEqual(self.banco.valor("SELECT cancelado FROM itens_venda WHERE produto_id = ?", (self.skol,)), 1)
        self.lancar("2", 1)
        r = self.cancelar(1, confirmacoes=[True])                       # uma unidade: o fluxo antigo, sem perguntas
        self.assertEqual(len(r.rotulos), 1)
        self.assertEqual(self.banco.valor("SELECT cancelado FROM itens_venda WHERE produto_id = ?", (self.agua,)), 1)

    def test_desistir_da_quantidade_nao_cancela(self):
        self.lancar("1", 3)
        self.cancelar(0, textos=[None], confirmacoes=[True])
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda WHERE cancelado = 1"), 0)

    def test_pagar_itens_pela_janela_de_pagamento(self):
        self.lancar("1", 3); self.lancar("2", 1)                       # 24,00 + 3,50
        vid = self.cx.venda_id
        skol = self.ctx.caixa.itens(vid)[0]["id"]
        resultado = {}

        def acao(j):
            f = [i for i in j.grade_formas.tree.get_children() if j.grade_formas.valores(i)[0] == "Pix"][0]
            j.grade_formas.selecionar(f)
            with Roteiro(textos=["2"], confirmacoes=[True], escolhas=[skol, "ok"]) as r:
                j._pagar_itens()
            resultado["confirmacao"] = r.rotulos[-1][0]
            with Roteiro(escolhas=[skol, "ok"], confirmacoes=[True]) as r:     # a última SKOL: 1 unidade, sem perguntar
                j._pagar_itens()
            with Roteiro() as r:
                j._pagar_itens()
            resultado["opcoes"] = r.opcoes
            resultado["falta"] = j.lbl_troco.cget("text")
            j.destroy()
        self.robo.quando("JanelaPagamento", acao)
        self.cx.pagar(); self.cx.update()
        self.sem_travar()
        self.assertIn("2 x SKOL: R$ 16,00", resultado["confirmacao"])
        self.assertEqual([p["valor_cent"] for p in self.ctx.caixa.pagamentos(vid)], [1600, 800])
        self.assertEqual([[v for v, _ in o] for o in resultado["opcoes"]], [[self.ctx.caixa.itens(vid)[1]["id"]]])
        self.assertEqual(resultado["falta"], "3,50")
        r = self.cancelar(0, textos=["1", "x"], confirmacoes=[True])     # tudo pago: o controlador protege
        self.assertTrue(any("já foi pago" in t for t in r.recusas))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda WHERE cancelado = 1"), 0)
