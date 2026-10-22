"""Etiquetas de produtos e preços no Qt: seleção, prévia, impressão e CSV, sem hardware obrigatório."""
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers.etiqueta_controller import MAX_COPIAS_ITEM, TEMPERATURAS, EtiquetaController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto
from src.ui_qt.visualizador import JanelaVisualizador

MODULO = "lanc_estoque"


class JanelaEtiquetas(QDialog):
    """Nada é impresso sem o clique do operador; a prévia abre o visualizador (imprime/salva texto)."""

    def __init__(self, ctx, produtos, selecionados=None, parent=None):
        super().__init__(parent)
        self.ctx, self.produtos = ctx, list(produtos)
        self._operador_id = ctx.operador_id
        self._exigir_acesso()
        self.ctrl = EtiquetaController(ctx.banco)
        self.setWindowTitle("Etiquetas de produtos e preços")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Selecione os produtos (Ctrl/Shift para vários).", "suave"))
        precos = {r["id"]: r["preco_cent"] for r in ctx.banco.todos("SELECT id, preco_cent FROM produtos")}
        self.grade = QTableWidget(len(self.produtos), 3)
        self.grade.setHorizontalHeaderLabels(["Código", "Produto", "Preço cadastro"])
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.horizontalHeader().setStretchLastSection(True)
        for i, p in enumerate(self.produtos):
            for j, valor in enumerate((p["codigo"], p["nome"], fmt.fmt_brl(precos.get(p["id"], 0)))):
                self.grade.setItem(i, j, QTableWidgetItem(str(valor)))
            if p["id"] in (selecionados or []):
                self.grade.selectRow(i)
        layout.addWidget(self.grade)
        opcoes = QHBoxLayout()
        opcoes.addWidget(texto("Cópias por produto", "suave"))
        self.copias = QSpinBox()
        self.copias.setRange(1, MAX_COPIAS_ITEM)
        opcoes.addWidget(self.copias)
        opcoes.addWidget(texto("Temperatura", "suave"))
        self.temperatura = QComboBox()
        for chave, rotulo in TEMPERATURAS.items():
            self.temperatura.addItem(rotulo, chave)
        opcoes.addWidget(self.temperatura)
        opcoes.addStretch(1)
        layout.addLayout(opcoes)
        botoes = QHBoxLayout()
        self.btn_previa = QPushButton("Prévia / Imprimir")
        self.btn_previa.clicked.connect(lambda: self.previa())
        self.btn_csv = QPushButton("Exportar CSV...")
        self.btn_csv.clicked.connect(lambda: self.exportar_csv())
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        for botao in (self.btn_previa, self.btn_csv, fechar):
            botao.setAutoDefault(False)
            botoes.addWidget(botao)
        layout.addLayout(botoes)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)

    def _exigir_acesso(self):
        if self.ctx.operador is None or self.ctx.operador_id != self._operador_id:
            raise ErroPermissao("A sessão mudou. Abra as etiquetas novamente.")
        self.ctx.acesso.exigir(self.ctx.acesso.operador(self._operador_id), MODULO)

    def itens(self):
        linhas = sorted({i.row() for i in self.grade.selectedIndexes()})
        return [{"produto_id": self.produtos[l]["id"], "copias": self.copias.value(),
                 "temperatura": self.temperatura.currentData()} for l in linhas]

    def _montar(self):
        try:
            self._exigir_acesso()
            self.mensagem.clear()
            return self.ctrl.etiquetas(self.itens())
        except (ErroNegocio, ErroPermissao) as erro:
            self.mensagem.setText(str(erro))
            return None

    def previa(self):
        etiquetas = self._montar()
        if etiquetas is None:
            return False
        try:
            janela = JanelaVisualizador(self.ctx, "Etiquetas - prévia", self.ctrl.texto(etiquetas), parent=self,
                                        modulo=MODULO, nome="etiquetas", tipo="etiquetas")
        except (ErroNegocio, ErroPermissao) as erro:
            self.mensagem.setText(str(erro))
            return False
        janela.exec()
        return True

    def exportar_csv(self, caminho=None):
        etiquetas = self._montar()
        if etiquetas is None:
            return False
        if not caminho:
            caminho, _ = QFileDialog.getSaveFileName(self, "Exportar etiquetas", "etiquetas.csv", "CSV (*.csv)")
        if not caminho:
            return False
        try:
            self._exigir_acesso()
            with Path(caminho).open("w", encoding="utf-8-sig", newline="") as arquivo:
                arquivo.write(self.ctrl.csv(etiquetas))
        except (ErroNegocio, ErroPermissao, OSError) as erro:
            self.mensagem.setText(f"Não foi possível exportar: {erro}")
            return False
        self.mensagem.setText("CSV exportado.")
        return True