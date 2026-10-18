"""Relatório Qt opt-in: produtos e totais do período, sem operações de escrita.

Instancie ``JanelaRelatorioVendas(ctx, parent)`` explicitamente. Não altera o menu
nem substitui a consulta de cupons do caixa clássico.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers.relatorio_vendas import virada_dia
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto


class JanelaRelatorioVendas(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._exigir_acesso()
        self.rel = None
        self.setWindowTitle("Relatório de vendas • somente leitura")
        self.resize(1050, 760)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Relatório de vendas", "titulo"))
        layout.addWidget(texto(
            "Somente leitura • produtos de vendas fechadas • valores em R$. "
            "O período considera a virada do dia configurada no PDV.", "suave"))
        filtros = QHBoxLayout()
        hoje = fmt.fmt_data(fmt.dia_operacional(virada=virada_dia(ctx.banco)))
        self.inicio, self.fim = QLineEdit(hoje), QLineEdit(hoje)
        for rotulo, campo in (("Data inicial", self.inicio), ("Data final", self.fim)):
            campo.setPlaceholderText("DD/MM/AAAA ou AAAA-MM-DD; vazio = sem limite")
            campo.returnPressed.connect(self.atualizar)
            formulario = QFormLayout()
            formulario.addRow(rotulo, campo)
            filtros.addLayout(formulario)
        self.aplicar = QPushButton("Consultar")
        self.aplicar.clicked.connect(self.atualizar)
        filtros.addWidget(self.aplicar)
        layout.addLayout(filtros)
        self.criterios = texto("", "suave")
        self.criterios.setWordWrap(True)
        layout.addWidget(self.criterios)
        self.grade = self._grade()
        layout.addWidget(self.grade, 2)
        layout.addWidget(texto("Totalizações do período", "titulo"))
        self.totais = self._grade()
        layout.addWidget(self.totais, 1)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        layout.addWidget(fechar)
        self.atualizar()

    @staticmethod
    def _grade():
        grade = QTableWidget()
        grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        grade.setAlternatingRowColors(True)
        grade.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        grade.horizontalHeader().setStretchLastSection(True)
        return grade

    def _exigir_acesso(self):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre no sistema para consultar o relatório de vendas.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        operador = self.ctx.acesso.operador(self.ctx.operador_id)
        self.ctx.acesso.exigir(operador, "rel_vendas")

    def atualizar(self):
        try:
            self._exigir_acesso()
            inicio = fmt.para_data_iso(self.inicio.text())
            fim = fmt.para_data_iso(self.fim.text())
            if inicio and fim and inicio > fim:
                raise ValueError("A data inicial deve ser anterior ou igual à data final.")
            rel = self.ctx.relatorios.vendas_periodo({"de": inicio, "ate": fim})
        except (ErroNegocio, ValueError) as erro:
            self.rel = None
            self.grade.setRowCount(0)
            self.totais.setRowCount(0)
            self.criterios.clear()
            self.mensagem.setText(str(erro))
            return False
        self.rel = rel
        self.criterios.setText("\n".join(rel.criterios))
        self.grade.setColumnCount(len(rel.colunas))
        self.grade.setHorizontalHeaderLabels([coluna.titulo for coluna in rel.colunas])
        self.grade.setRowCount(len(rel.linhas))
        for linha, valores in enumerate(rel.linhas):
            for coluna, valor in enumerate(valores):
                item = QTableWidgetItem(str(valor))
                if rel.colunas[coluna].alinha == "d":
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.grade.setItem(linha, coluna, item)
        self.totais.setColumnCount(2)
        self.totais.setHorizontalHeaderLabels(["Indicador", "Valor"])
        self.totais.setRowCount(len(rel.rodape))
        for linha, (rotulo, valor) in enumerate(rel.rodape):
            self.totais.setItem(linha, 0, QTableWidgetItem(rotulo))
            self.totais.setItem(linha, 1, QTableWidgetItem(str(valor)))
        self.mensagem.setText("Nenhuma venda encontrada no período." if rel.vazio() else "")
        return True
