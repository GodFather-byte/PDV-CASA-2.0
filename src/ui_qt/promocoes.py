"""Gestão Qt das regras existentes; não importa nem instancia a interface Tk."""
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from src.controllers.promocoes_controller import AVISO, CAMPOS, PromocoesController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio


class JanelaPromocoes(QDialog):
    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        self.controller = PromocoesController(ctx)
        self.controller.exigir_acesso()
        super().__init__(parent)
        self.setWindowTitle("Promoções e faixas — sem acúmulo")
        self.resize(930, 720)
        self.produto_id = None
        self.campos = {}
        layout = QVBoxLayout(self)
        aviso = QLabel(AVISO)
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        busca = QHBoxLayout()
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar produto por nome, código, barras ou atalho")
        self.busca.returnPressed.connect(self.pesquisar)
        busca.addWidget(self.busca)
        pesquisar = QPushButton("Pesquisar / recarregar")
        pesquisar.clicked.connect(self.pesquisar)
        busca.addWidget(pesquisar)
        layout.addLayout(busca)
        self.produto = QComboBox()
        self.produto.currentIndexChanged.connect(self.carregar)
        layout.addWidget(self.produto)
        abas = QTabWidget()
        secoes = {}
        for campo in CAMPOS:
            secao = "Promoções" if campo.secao == "Promoções" else "Preços e faixas"
            if secao not in secoes:
                pagina = QWidget()
                secoes[secao] = QFormLayout(pagina)
                abas.addTab(pagina, secao)
            if campo.tipo == "escolha":
                editor = QComboBox()
                editor.addItem("", None)
                for valor, rotulo in campo.opcoes:
                    editor.addItem(rotulo, valor)
            else:
                editor = QLineEdit()
                if campo.tipo == "dinheiro":
                    editor.setPlaceholderText("R$ 0,00")
            self.campos[campo.nome] = editor
            secoes[secao].addRow(campo.rotulo + (" (R$)" if campo.tipo == "dinheiro" else ""), editor)
        layout.addWidget(abas)
        salvar = QPushButton("Salvar regras do produto")
        salvar.clicked.connect(self.salvar)
        layout.addWidget(salvar)
        simulacao = QFormLayout()
        self.quantidade = QLineEdit("1")
        self.temperatura = QComboBox()
        self.temperatura.addItems(["natural", "gelada"])
        self.quando = QLineEdit(fmt.agora())
        simulacao.addRow("Quantidade (até 4 casas)", self.quantidade)
        simulacao.addRow("Temperatura", self.temperatura)
        simulacao.addRow("Data/hora local (YYYY-MM-DD HH:MM:SS)", self.quando)
        layout.addLayout(simulacao)
        simular = QPushButton("Simular campos acima (não salva)")
        simular.clicked.connect(self.simular)
        layout.addWidget(simular)
        self.resultado = QTextEdit()
        self.resultado.setReadOnly(True)
        layout.addWidget(self.resultado)
        self.pesquisar()

    def exigir_acesso(self):
        self.controller.exigir_acesso()

    def pesquisar(self):
        try:
            produtos = self.controller.listar(self.busca.text())
            self.produto.blockSignals(True)
            self.produto.clear()
            self.produto_id = None
            for produto in produtos:
                self.produto.addItem(f"{produto['codigo']} — {produto['nome']}", produto["id"])
            self.produto.blockSignals(False)
            self.resultado.setPlainText("Selecione um produto. Recarregar descarta alterações não salvas.")
            self.carregar()
        except ErroNegocio as erro:
            self.resultado.setPlainText(str(erro))

    def carregar(self, _indice=None):
        self.produto_id = None
        try:
            produto_id = self.produto.currentData()
            if produto_id is None:
                return
            p = self.controller.obter(produto_id)
            self.produto_id = produto_id
            valores = self.ctx.cadastros.exibir("produtos", p)
            for nome, editor in self.campos.items():
                if isinstance(editor, QComboBox):
                    editor.setCurrentIndex(max(0, editor.findData(p[nome])))
                else:
                    editor.setText(valores.get(nome, "") or "")
            self.resultado.setPlainText("Cadastro carregado. Simular avalia os campos atuais, sem salvar.")
        except ErroNegocio as erro:
            self.resultado.setPlainText(str(erro))

    def valores(self):
        return {nome: editor.currentData() if isinstance(editor, QComboBox) else editor.text()
                for nome, editor in self.campos.items()}

    def salvar(self):
        try:
            if self.produto_id is None:
                return
            self.controller.salvar(self.produto_id, self.valores())
            self.resultado.setPlainText("Regras salvas. Vendas e retratos existentes não foram alterados.")
        except ErroNegocio as erro:
            self.resultado.setPlainText(str(erro))

    def simular(self):
        try:
            if self.produto_id is None:
                return
            resultado = self.controller.simular(self.produto_id, self.quantidade.text(),
                                                self.temperatura.currentText(), self.quando.text(), self.valores())
            self.resultado.setPlainText(self.controller.descrever(resultado))
        except ErroNegocio as erro:
            self.resultado.setPlainText(str(erro))
