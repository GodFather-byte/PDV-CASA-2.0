"""Relatório Qt opt-in: produtos e totais do período, sem operações de escrita.

Instancie ``JanelaRelatorioVendas(ctx, parent)`` explicitamente. Não altera o menu
nem substitui a consulta de cupons do caixa clássico.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
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
        layout.addWidget(texto("Vendas fechadas no período, conforme a virada do dia configurada no caixa.", "suave"))
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
        self.aplicar.setObjectName("primario")
        self.aplicar.clicked.connect(self.atualizar)
        filtros.addWidget(self.aplicar)
        layout.addLayout(filtros)
        indicadores = QHBoxLayout()
        self.valores = {}
        for chave, rotulo in (("Total apurado", "Total apurado (R$)"), ("Cupons (TC)", "Cupons"),
                              ("Ticket médio (TM)", "Ticket médio (R$)")):
            cartao = QFrame()
            cartao.setObjectName("cartao")
            coluna = QVBoxLayout(cartao)
            coluna.addWidget(texto(rotulo, "suave"))
            valor = texto("—", "kpi_valor")
            valor.setAccessibleName(rotulo)
            coluna.addWidget(valor)
            self.valores[chave] = valor
            indicadores.addWidget(cartao, 1)
        layout.addLayout(indicadores)
        self.criterios = texto("", "suave")
        self.criterios.setWordWrap(True)
        layout.addWidget(self.criterios)
        self.grade = self._grade()
        self.totais = self._grade()
        abas = QTabWidget()
        abas.addTab(self.grade, "Produtos vendidos")
        abas.addTab(self.totais, "Totalizações do período")
        layout.addWidget(abas, 1)
        self.mensagem = texto("", "aviso")
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        rodape = QHBoxLayout()
        rodape.addWidget(self.mensagem, 1)
        rodape.addWidget(fechar)
        layout.addLayout(rodape)
        self.atualizar()

    @staticmethod
    def _grade():
        grade = QTableWidget()
        grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        grade.setAlternatingRowColors(True)
        grade.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
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
            for valor in self.valores.values():
                valor.setText("—")
            self.mensagem.setText(str(erro))
            return False
        self.rel = rel
        rodape = dict(rel.rodape)
        for chave, valor in self.valores.items():
            valor.setText(str(rodape.get(chave, "—")))
        self.criterios.setText("\n".join(rel.criterios))
        self.grade.setColumnCount(len(rel.colunas))
        self.grade.setHorizontalHeaderLabels([coluna.titulo for coluna in rel.colunas])
        for indice, coluna in enumerate(rel.colunas):
            if coluna.titulo == "Produto":
                self.grade.horizontalHeader().setSectionResizeMode(indice, QHeaderView.ResizeMode.Stretch)
            alinhamento = Qt.AlignmentFlag.AlignRight if coluna.alinha == "d" else Qt.AlignmentFlag.AlignLeft
            self.grade.horizontalHeaderItem(indice).setTextAlignment(alinhamento | Qt.AlignmentFlag.AlignVCenter)
        self.grade.setRowCount(len(rel.linhas))
        for linha, valores in enumerate(rel.linhas):
            for coluna, valor in enumerate(valores):
                item = QTableWidgetItem(str(valor))
                if rel.colunas[coluna].alinha == "d":
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.grade.setItem(linha, coluna, item)
        self.totais.setColumnCount(2)
        self.totais.setHorizontalHeaderLabels(["Indicador", "Valor"])
        self.totais.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.totais.horizontalHeaderItem(0).setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        direita = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        self.totais.horizontalHeaderItem(1).setTextAlignment(direita)
        self.totais.setRowCount(len(rel.rodape))
        for linha, (rotulo, valor) in enumerate(rel.rodape):
            self.totais.setItem(linha, 0, QTableWidgetItem(rotulo))
            item = QTableWidgetItem(str(valor))
            item.setTextAlignment(direita)
            self.totais.setItem(linha, 1, item)
        self.mensagem.setText("Nenhuma venda encontrada no período." if rel.vazio() else "")
        return True
