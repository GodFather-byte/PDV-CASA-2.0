"""Consulta administrativa Qt, somente leitura, da auditoria estruturada."""
import json

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLineEdit, QPlainTextEdit, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.core.erros import ErroNegocio
from src.ui_qt.tema import texto


ACOES = (
    ("cadastro", "Cadastro"), ("alteracao", "Alteração"), ("exclusao", "Exclusão"),
    ("preco_alterado", "Preço alterado"), ("desconto_alterado", "Desconto alterado"),
    ("estoque_alterado", "Estoque alterado"), ("venda_cancelada", "Venda cancelada"),
    ("item_cancelado", "Item cancelado"), ("permissao_alterada", "Permissão alterada"),
    ("credencial_alterada", "Credencial alterada"),
)


class JanelaAuditoria(QDialog):
    TAMANHO_PAGINA = 100

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        # A autorização é do controlador e consulta o nível/estado atual do operador.
        iniciais = ctx.auditoria.listar(limite=self.TAMANHO_PAGINA, offset=0)
        self.offset = 0
        self.eventos = []
        self._filtros = {"inicio": None, "fim": None, "acao": None}
        self.setWindowTitle("Auditoria administrativa • somente leitura")
        self.resize(1100, 760)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Auditoria administrativa", "titulo"))
        layout.addWidget(texto(
            "Somente leitura • administrador • mais recentes primeiro. "
            "Datas locais inclusivas; valores monetários nos retratos estão em centavos.", "suave"))
        filtros = QHBoxLayout()
        self.inicio, self.fim = QLineEdit(), QLineEdit()
        for campo in (self.inicio, self.fim):
            campo.setPlaceholderText("AAAA-MM-DD ou AAAA-MM-DD HH:MM:SS")
            campo.returnPressed.connect(self.filtrar)
        self.acao = QComboBox()
        self.acao.setEditable(True)
        self.acao.addItem("Todas as ações", None)
        for valor, rotulo in ACOES:
            self.acao.addItem(rotulo, valor)
        self.acao.setToolTip("Selecione uma ação ou digite seu código exato.")
        for rotulo, campo in (("De", self.inicio), ("Até", self.fim), ("Ação", self.acao)):
            formulario = QFormLayout()
            formulario.addRow(rotulo, campo)
            filtros.addLayout(formulario)
        aplicar = QPushButton("Aplicar filtros")
        aplicar.clicked.connect(self.filtrar)
        filtros.addWidget(aplicar)
        layout.addLayout(filtros)
        self.grade = QTableWidget(0, 7)
        self.grade.setHorizontalHeaderLabels(
            ["Evento", "Quando", "Operador (ID)", "Origem", "Entidade", "Registro", "Ação"])
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.setAlternatingRowColors(True)
        self.grade.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.grade.horizontalHeader().setStretchLastSection(True)
        self.grade.itemSelectionChanged.connect(self.mostrar_detalhes)
        layout.addWidget(self.grade, 2)
        detalhes = QSplitter()
        self.antes, self.depois = QPlainTextEdit(), QPlainTextEdit()
        for titulo, campo in (("Antes", self.antes), ("Depois", self.depois)):
            campo.setReadOnly(True)
            quadro = QWidget()
            coluna = QVBoxLayout(quadro)
            coluna.addWidget(texto(titulo, "suave"))
            coluna.addWidget(campo)
            detalhes.addWidget(quadro)
        layout.addWidget(detalhes, 1)
        rodape = QHBoxLayout()
        self.anterior, self.proxima = QPushButton("Página anterior"), QPushButton("Próxima página")
        self.anterior.clicked.connect(self.pagina_anterior)
        self.proxima.clicked.connect(self.proxima_pagina)
        self.paginacao = texto("")
        rodape.addWidget(self.anterior)
        rodape.addWidget(self.paginacao, 1)
        rodape.addWidget(self.proxima)
        layout.addLayout(rodape)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        self._preencher(iniciais)

    def _preencher(self, eventos):
        self.grade.blockSignals(True)
        self.eventos = eventos
        self.grade.clearSelection()
        self.grade.setRowCount(len(eventos))
        for linha, evento in enumerate(eventos):
            valores = (evento["id"], evento["quando"], evento["operador_id"],
                       evento["origem"], evento["entidade"], evento["entidade_id"], evento["acao"])
            for coluna, valor in enumerate(valores):
                self.grade.setItem(linha, coluna, QTableWidgetItem("—" if valor is None else str(valor)))
        self.grade.blockSignals(False)
        self.antes.clear()
        self.depois.clear()
        self.anterior.setEnabled(self.offset > 0)
        self.proxima.setEnabled(len(eventos) == self.TAMANHO_PAGINA)
        pagina = self.offset // self.TAMANHO_PAGINA + 1
        self.paginacao.setText(f"Página {pagina} • {len(eventos)} evento(s) • até 100 por página")
        self.mensagem.setText(
            "Página cheia: pode existir outra página; não foi calculado um total."
            if len(eventos) == self.TAMANHO_PAGINA else "")

    def atualizar(self):
        try:
            eventos = self.ctx.auditoria.listar(
                **self._filtros, limite=self.TAMANHO_PAGINA, offset=self.offset)
        except ErroNegocio as erro:
            self._preencher([])
            self.mensagem.setText(str(erro))
            return False
        self._preencher(eventos)
        return True

    def filtrar(self):
        indice = self.acao.currentIndex()
        codigo = (self.acao.currentData() if indice >= 0 and self.acao.currentText() == self.acao.itemText(indice)
                  else self.acao.currentText().strip() or None)
        self._filtros = {"inicio": self.inicio.text().strip() or None,
                         "fim": self.fim.text().strip() or None, "acao": codigo}
        self.offset = 0
        self.atualizar()

    def pagina_anterior(self):
        self.offset = max(0, self.offset - self.TAMANHO_PAGINA)
        self.atualizar()

    def proxima_pagina(self):
        if len(self.eventos) == self.TAMANHO_PAGINA:
            self.offset += self.TAMANHO_PAGINA
            self.atualizar()

    def mostrar_detalhes(self):
        linha = self.grade.currentRow()
        if not self.grade.selectedItems() or not 0 <= linha < len(self.eventos):
            self.antes.clear()
            self.depois.clear()
            return
        try:
            self.ctx.auditoria.listar(limite=1)
        except ErroNegocio as erro:
            self._preencher([])
            self.mensagem.setText(str(erro))
            return
        evento = self.eventos[linha]
        for chave, campo in (("antes", self.antes), ("depois", self.depois)):
            valor = evento[chave]
            campo.setPlainText("Sem retrato" if valor is None else
                               json.dumps(valor, ensure_ascii=False, indent=2, sort_keys=True))
