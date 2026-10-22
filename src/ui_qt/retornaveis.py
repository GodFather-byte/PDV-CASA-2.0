"""Consulta e registro explícito de posse de retornáveis por cliente (Qt)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers.retornaveis_controller import AVISO, TIPOS, RetornaveisController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto


class JanelaRetornaveis(QDialog):
    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        self.exigir_acesso()
        super().__init__(parent)
        self.setWindowTitle("Retornáveis por cliente")
        self.resize(1080, 760)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Retornáveis por cliente", "titulo"))
        aviso = texto(AVISO, "suave")
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        formulario = QFormLayout()
        self.cliente = QComboBox()
        self.produto = QComboBox()
        self.tipo = QComboBox()
        for chave, rotulo in TIPOS.items():
            self.tipo.addItem(rotulo, chave)
        self.quantidade = QLineEdit()
        self.motivo = QLineEdit()
        for rotulo, campo in (
                ("Cliente (inativos: somente consulta)", self.cliente),
                ("Produto", self.produto), ("Movimento", self.tipo),
                ("Quantidade (até 4 casas)", self.quantidade), ("Motivo obrigatório", self.motivo)):
            formulario.addRow(rotulo, campo)
        layout.addLayout(formulario)
        acoes = QHBoxLayout()
        self.btn_registrar = QPushButton("Registrar movimento")
        self.btn_registrar.clicked.connect(self.registrar)
        acoes.addWidget(self.btn_registrar)
        atualizar = QPushButton("Atualizar")
        atualizar.clicked.connect(self.atualizar)
        acoes.addWidget(atualizar)
        acoes.addStretch()
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.close)
        acoes.addWidget(fechar)
        layout.addLayout(acoes)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        layout.addWidget(texto("Saldo em posse do cliente, por produto", "subtitulo"))
        self.grade_saldos = self._tabela(["Código", "Produto", "Saldo"])
        layout.addWidget(self.grade_saldos, 1)
        layout.addWidget(texto("Histórico permanente — movimentos mais recentes primeiro", "subtitulo"))
        self.grade_historico = self._tabela(
            ["Data", "Produto", "Movimento", "Quantidade", "Saldo após", "Motivo", "Operador"])
        layout.addWidget(self.grade_historico, 2)
        self.cliente.currentIndexChanged.connect(self.atualizar)
        self.atualizar()

    @staticmethod
    def _tabela(cabecalhos):
        tabela = QTableWidget(0, len(cabecalhos))
        tabela.setHorizontalHeaderLabels(cabecalhos)
        tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tabela.horizontalHeader().setStretchLastSection(True)
        return tabela

    def _controller(self):
        return RetornaveisController(self.ctx.banco, self.ctx.operador_id)

    def exigir_acesso(self):
        self._controller().exigir_acesso()

    def _carregar_opcoes(self):
        cliente_id, produto_id = self.cliente.currentData(), self.produto.currentData()
        self.cliente.blockSignals(True)
        try:
            self.cliente.clear()
            self.cliente.addItem("Selecione um cliente", None)
            for c in self.ctx.banco.todos("SELECT id, nome, ativo FROM clientes ORDER BY nome, id"):
                self.cliente.addItem(
                    f"{c['id']} — {c['nome']}" + (" (inativo)" if not c["ativo"] else ""), c["id"])
            self.cliente.setCurrentIndex(max(0, self.cliente.findData(cliente_id)))
        finally:
            self.cliente.blockSignals(False)
        self.produto.clear()
        self.produto.addItem("Selecione um produto", None)
        for p in self.ctx.banco.todos(
                "SELECT id, codigo, nome FROM produtos WHERE ativo = 1 ORDER BY nome"):
            self.produto.addItem(f"{p['codigo']} — {p['nome']}", p["id"])
        self.produto.setCurrentIndex(max(0, self.produto.findData(produto_id)))

    def _erro(self, erro):
        if isinstance(erro, ErroPermissao):
            self.grade_saldos.setRowCount(0)
            self.grade_historico.setRowCount(0)
            self.cliente.blockSignals(True)
            try:
                self.cliente.clear()
                self.produto.clear()
            finally:
                self.cliente.blockSignals(False)
        self.mensagem.setText(str(erro))
        return False

    @staticmethod
    def _preencher(grade, linhas):
        grade.setRowCount(len(linhas))
        for linha, valores in enumerate(linhas):
            for coluna, valor in enumerate(valores):
                grade.setItem(linha, coluna, QTableWidgetItem(str(valor)))

    def atualizar(self, *_):
        try:
            self.exigir_acesso()
            self._carregar_opcoes()
            self.grade_saldos.setRowCount(0)
            self.grade_historico.setRowCount(0)
            cliente_id = self.cliente.currentData()
            if cliente_id is None:
                self.mensagem.setText("Selecione um cliente para consultar seu saldo e histórico.")
                return True
            controle = self._controller()
            self._preencher(self.grade_saldos, [
                (s["codigo"], s["produto"], fmt.fmt_qtd(s["saldo"], 4))
                for s in controle.saldos(cliente_id)])
            self._preencher(self.grade_historico, [
                (m["criado_em"], m["produto"], TIPOS[m["tipo"]], fmt.fmt_qtd(m["quantidade"], 4),
                 fmt.fmt_qtd(m["saldo_apos"], 4), m["motivo"], m["operador"])
                for m in controle.historico(cliente_id)])
            self.mensagem.setText("Saldos somente de empréstimos e devoluções registrados aqui.")
            return True
        except ErroNegocio as erro:
            return self._erro(erro)

    def registrar(self):
        try:
            self.exigir_acesso()
            self._controller().registrar(
                self.cliente.currentData(), self.produto.currentData(), self.tipo.currentData(),
                self.quantidade.text(), self.motivo.text())
            self.quantidade.clear()
            self.motivo.clear()
            self.atualizar()
            self.mensagem.setText("Movimento registrado. Nenhuma venda, cobrança ou alteração de estoque.")
            return True
        except ErroNegocio as erro:
            return self._erro(erro)
