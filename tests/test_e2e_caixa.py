"""Ponta a ponta do caixa como o operador usa: só teclado, na janela real, e o resultado conferido no banco.

Abre o turno digitando o fundo, bipa dois produtos, paga pelo teclado com troco e fecha. Se um atalho, o foco ou a
ordem dos Enter mudar, este teste quebra antes de chegar na loja.
"""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.test_qt_caixa import BaseCaixaQt


class TesteJornadaDoCaixa(BaseCaixaQt):
    def foco(self):
        return QApplication.focusWidget()

    def teclar(self, tecla, alvo=None):
        QTest.keyClick(alvo or self.foco() or self.j, tecla)
        self.aplicacao.processEvents()

    def digitar(self, texto, alvo=None):
        alvo = alvo or self.foco()
        alvo.selectAll()
        QTest.keyClicks(alvo, texto)
        self.aplicacao.processEvents()

    def setUp(self):
        super().setUp()
        self.cerveja = self.novo_produto("CERVEJA LATA", 800, codigo="71", estoque=True, qt=24)
        self.agua = self.novo_produto("AGUA 500ML", 400, codigo="72", estoque=True, qt=10)
        self.j = self.janela()
        self.j.activateWindow()
        self.aplicacao.processEvents()

    def test_turno_venda_com_troco_e_fechamento_so_no_teclado(self):
        # 1. Turno: digita o fundo e Enter
        self.assertIsNone(self.ctx.turnos.atual(), "o teste começa sem turno")
        self.j.ent_fundo.setFocus()
        self.digitar("150,00", self.j.ent_fundo)
        self.j.dialogos.confirmacoes = [True]          # "Abrir o turno 1 com R$ 150,00?" -> Enter no Sim
        self.teclar(Qt.Key_Return, self.j.ent_fundo)
        self.assertEqual(self.j.dialogos.erros, [])
        turno = self.ctx.turnos.atual()
        self.assertIsNotNone(turno, "Enter no fundo não abriu o turno")
        self.assertEqual(turno["valor_inicial_cent"], 15000)

        # 2. Bipa: código + Enter, quantidade + Enter (duas cervejas e uma água)
        for codigo, qtd in (("71", "2"), ("72", "1")):
            self.j.ent_codigo.setFocus()
            self.digitar(codigo, self.j.ent_codigo)
            self.teclar(Qt.Key_Return, self.j.ent_codigo)
            self.assertIs(self.foco(), self.j.ent_qtd, "depois do código o foco vai para a quantidade")
            self.digitar(qtd, self.j.ent_qtd)
            self.teclar(Qt.Key_Return, self.j.ent_qtd)
            self.assertIs(self.foco(), self.j.ent_codigo, "depois de lançar o foco volta ao código")
        venda = self.j.venda()
        self.assertEqual(venda["total_cent"], 2000)

        # 3. Paga: Enter com o código vazio vai à forma; Enter vai ao valor; digita 50 e Enter
        self.teclar(Qt.Key_Return, self.j.ent_codigo)
        self.teclar(Qt.Key_Return)
        self.assertIs(self.foco(), self.j.ent_valor, "Enter na forma leva ao valor")
        self.digitar("50", self.j.ent_valor)
        self.teclar(Qt.Key_Return, self.j.ent_valor)

        # 4. Fecha: F12 (a dica da tela) se ainda estiver aberta
        if self.banco.valor("SELECT status FROM vendas WHERE id = ?", (venda["id"],)) != "fechada":
            self.teclar(Qt.Key_F12, self.j)
        v = self.banco.um("SELECT status, total_cent, troco_cent, cupom FROM vendas WHERE id = ?", (venda["id"],))
        self.assertEqual((v["status"], v["total_cent"], v["troco_cent"]), ("fechada", 2000, 3000))
        self.assertTrue(v["cupom"])
        estoque = {r["id"]: r["qt_atual"] for r in self.banco.todos("SELECT id, qt_atual FROM produtos")}
        self.assertEqual((estoque[self.cerveja], estoque[self.agua]), (22, 9))
        self.assertIsNone(self.j.venda_id, "a tela fica livre para a próxima venda")
