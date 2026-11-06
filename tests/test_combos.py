"""Combos com preço fixo: produto com composição; os itens não ganham nem contam para o atacado; estoque baixa cada item."""
from __future__ import annotations

import os

from src.controllers.perfil_controller import PerfilController
from src.core.erros import ErroNegocio
from tests.test_caixa import BaseCaixa


class TesteCombos(BaseCaixa):
    def setUp(self):
        super().setUp()
        PerfilController(self.banco, self.adm).aplicar("adega")
        self.banco.executar("UPDATE produtos SET atacado_qtd = 6, preco_atacado_cent = 650 WHERE id = ?", (self.skol,))
        self.gelo = self.novo_produto("GELO 2KG", 1000, estoque=True, qt=20)

    def test_combo_tem_preco_fixo_baixa_cada_item_e_nao_mexe_no_atacado_dos_avulsos(self):
        combo = self.prod.criar_combo("BALDE 6 SKOL", 4000, [(self.skol, 6), (self.gelo, 1)], "7890000000017")
        self.assertEqual(self.prod.preco_avulso([(self.skol, 6), (self.gelo, 1)]), 5800)
        self.assertEqual({c["insumo_id"]: c["quantidade"] for c in self.prod.composicao(combo)},
                         {self.skol: 6, self.gelo: 1})
        vid = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(vid, combo, 1)
        avulsa = self.caixa.adicionar_item(vid, self.skol, 2)
        precos = {i["produto_id"]: i["preco_unit_cent"] for i in self.caixa.itens(vid)}
        self.assertEqual(precos, {combo: 4000, self.skol: 800})              # 2 avulsas não viram atacado pelo combo
        self.caixa.adicionar_item(vid, self.skol, 4)
        self.assertEqual(self.banco.valor("SELECT preco_unit_cent FROM itens_venda WHERE id = ?", (avulsa,)), 650)
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 4000 + 6 * 650)
        self.pagar(vid, "Dinheiro", self.caixa.obter(vid)["total_cent"])
        self.caixa.fechar(vid)
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 100 - 12)
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.gelo,)), 19)
        self.assertEqual(self.banco.valor("SELECT cbarra FROM produtos WHERE id = ?", (combo,)), "7890000000017")

    def test_item_sem_controle_de_estoque_passa_a_controlar(self):
        self.assertEqual(self.banco.valor("SELECT controla_estoque FROM produtos WHERE id = ?", (self.agua,)), 0)
        self.prod.criar_combo("KIT AGUA", 900, [(self.agua, 3)])
        self.assertEqual(self.banco.valor("SELECT controla_estoque FROM produtos WHERE id = ?", (self.agua,)), 1)

    def test_validacoes(self):
        casco = self.novo_produto("CASCO", 300)
        retornavel = self.novo_produto("BRAHMA 600", 900, estoque=True, qt=10)
        self.banco.executar("UPDATE produtos SET casco_produto_id = ? WHERE id = ?", (casco, retornavel))
        inativo = self.novo_produto("VELHO", 100, estoque=True)
        self.banco.executar("UPDATE produtos SET ativo = 0 WHERE id = ?", (inativo,))
        for nome, preco, itens, trecho in (
                ("", 1000, [(self.skol, 2)], "nome"), ("X", 0, [(self.skol, 2)], "preço"),
                ("X", 1000, [], "Inclua"), ("X", 1000, [(self.skol, 1)], "pelo menos 2"),
                ("X", 1000, [(self.skol, 1), (self.skol, 1)], "duas vezes"),
                ("X", 1000, [(retornavel, 2)], "casco"), ("X", 1000, [(inativo, 2)], "inativo"),
                ("X", 1000, [(self.skol, 1.5)], "inválida")):
            with self.assertRaisesRegex(ErroNegocio, trecho):
                self.prod.criar_combo(nome, preco, itens)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos WHERE nome = 'X'"), 0)


def _descartar(janela):
    """Fecha e destrói a janela agora (sobra para o fim do Python derruba o processo no Qt)."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    janela.close()
    janela.deleteLater()
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton
    from src.controllers.contexto import Contexto
    from src.ui_qt.cadastros import FormularioCombo, JanelaCadastro
except ImportError:                                   # pragma: no cover - sem PySide6
    FormularioCombo = None

if FormularioCombo is not None:
    class TesteCombosNaTela(TesteCombos):
        def test_formulario_soma_repetidos_mostra_economia_e_cria(self):
            QApplication.instance() or QApplication([])
            ctx = Contexto(self.banco)
            ctx.operador = ctx.acesso.autenticar("ADM", "ADM")
            lista = JanelaCadastro(ctx, "produtos")
            self.addCleanup(_descartar, lista)
            self.assertIn("Criar combo", [b.text() for b in lista.findChildren(QPushButton)])
            f = FormularioCombo(ctx)
            self.addCleanup(_descartar, f)
            f.nome.setText("BALDE")
            self.assertTrue(f.incluir(self.skol, "4"))
            self.assertTrue(f.incluir(self.skol, "2"))
            self.assertTrue(f.incluir(self.gelo, "1"))
            self.assertEqual(f.itens, [(self.skol, 6), (self.gelo, 1)])
            self.assertFalse(f.incluir(self.gelo, "0"))
            f.preco.setText("40,00")
            f._resumo()
            self.assertIn("Separados: R$ 58,00", f.resumo.text())
            self.assertIn("Economia do cliente: R$ 18,00", f.resumo.text())
            f.salvar()
            self.assertEqual(f.result(), QDialog.DialogCode.Accepted, f.mensagem.text())
            self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (f.id_,)), 4000)

    for _nome in [n for n in dir(TesteCombos) if n.startswith("test_")]:
        setattr(TesteCombosNaTela, _nome, None)
