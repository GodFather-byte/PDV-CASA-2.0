"""Contagem de estoque: o contado contra o teórico, e a perda em unidades e reais."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QMessageBox,
)

from src.controllers.estoque_controller import EstoqueController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio


class JanelaContagem(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Contagem de estoque")
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Digite a quantidade contada. A perda é o que falta em relação ao saldo do sistema, "
            "valorizada pelo último custo. Só grava ao aplicar."
        ))
        self.tabela = QTableWidget(0, 6)
        self.tabela.setHorizontalHeaderLabels(
            ["Produto", "Teórico", "Contado", "Diferença", "Perda (un)", "Perda (R$)"])
        layout.addWidget(self.tabela)
        botoes = QHBoxLayout()
        calcular = QPushButton("Calcular perdas")
        calcular.clicked.connect(self.calcular)
        aplicar = QPushButton("Aplicar contagem")
        aplicar.clicked.connect(self.aplicar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        botoes.addWidget(calcular)
        botoes.addWidget(aplicar)
        botoes.addStretch(1)
        botoes.addWidget(fechar)
        layout.addLayout(botoes)
        self._carregar()

    def _produtos(self):
        return self.ctx.banco.todos(
            """SELECT id, nome, qt_atual FROM produtos
               WHERE ativo = 1 AND controla_estoque = 1 ORDER BY nome""")

    def _carregar(self) -> None:
        linhas = self._produtos()
        self.tabela.setRowCount(len(linhas))
        for i, p in enumerate(linhas):
            nome = QTableWidgetItem(p["nome"])
            nome.setData(32, p["id"])
            nome.setFlags(nome.flags() & ~Qt.ItemFlag.ItemIsEditable)
            teorico = QTableWidgetItem(fmt.fmt_qtd(p["qt_atual"]))
            teorico.setFlags(teorico.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tabela.setItem(i, 0, nome)
            self.tabela.setItem(i, 1, teorico)
            self.tabela.setItem(i, 2, QTableWidgetItem(""))
            for coluna in (3, 4, 5):
                celula = QTableWidgetItem("")
                celula.setFlags(celula.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.tabela.setItem(i, coluna, celula)

    def _contados(self) -> list[tuple[int, float]]:
        pares = []
        for i in range(self.tabela.rowCount()):
            texto = (self.tabela.item(i, 2).text() if self.tabela.item(i, 2) else "").strip()
            if not texto:
                continue
            try:
                qtd = fmt.para_qtd(texto)
            except ValueError as exc:
                raise ErroNegocio(str(exc)) from exc
            pares.append((int(self.tabela.item(i, 0).data(32)), qtd))
        return pares

    def calcular(self) -> None:
        try:
            linhas = {l["produto_id"]: l for l in EstoqueController(
                self.ctx.banco, getattr(self.ctx.operador, "id", None)).simular_contagem(self._contados())}
        except ErroNegocio as exc:
            QMessageBox.warning(self, "Contagem", str(exc))
            return
        for i in range(self.tabela.rowCount()):
            pid = int(self.tabela.item(i, 0).data(32))
            linha = linhas.get(pid)
            if not linha:
                continue
            self.tabela.item(i, 3).setText(fmt.fmt_qtd(linha["diferenca"]))
            self.tabela.item(i, 4).setText(fmt.fmt_qtd(linha["perda_unidades"]))
            self.tabela.item(i, 5).setText(fmt.fmt_num(linha["perda_cent"]))

    def aplicar(self) -> None:
        try:
            resultado = EstoqueController(self.ctx.banco, getattr(self.ctx.operador, "id", None)).aplicar_contagem(self._contados())
        except ErroNegocio as exc:
            QMessageBox.warning(self, "Contagem", str(exc))
            return
        QMessageBox.information(
            self, "Contagem",
            f"Contagem gravada. Perda estimada: R$ {fmt.fmt_num(resultado['perda_cent'])}.")
        self._carregar()
