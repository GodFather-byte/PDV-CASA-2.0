"""Escolha de adicionais no caixa e cadastro de grupos do produto."""
import uuid
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)
from src.controllers.opcoes_produto_controller import OpcoesProdutoController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.ui_qt.tema import texto


class DialogoEscolherOpcoes(QDialog):
    def __init__(self, banco, produto_id, parent=None):
        super().__init__(parent)
        self.ctrl, self.produto_id = OpcoesProdutoController(banco), produto_id
        self.setWindowTitle("Adicionais e opções")
        self.resize(520, 520)
        self.opcoes_ids = []
        self.caixas = []
        layout = QVBoxLayout(self)
        pagina, grupos = QWidget(), self.ctrl.grupos(produto_id)
        coluna = QVBoxLayout(pagina)
        for g in grupos:
            quadro = QGroupBox(f"{g['nome']} — escolha de {g['minimo']} a {g['maximo']}")
            lista = QVBoxLayout(quadro)
            for o in g["opcoes"]:
                caixa = QCheckBox(f"{o['nome']} · + {fmt.fmt_brl(o['preco_cent'])}")
                lista.addWidget(caixa)
                self.caixas.append((o["id"], caixa))
            coluna.addWidget(quadro)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(pagina)
        layout.addWidget(rolagem)
        self.erro = texto("", "aviso")
        layout.addWidget(self.erro)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(self.confirmar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def confirmar(self):
        ids = [uid for uid, c in self.caixas if c.isChecked()]
        try:
            self.ctrl.selecionar(self.produto_id, ids)
        except ErroNegocio as exc:
            self.erro.setText(str(exc))
            return
        self.opcoes_ids = ids
        self.accept()


class DialogoCadastroOpcoes(QDialog):
    def __init__(self, ctx, produto_id, parent=None):
        super().__init__(parent)
        from src.ui_qt.cadastros import exigir_acesso
        exigir_acesso(ctx, "produtos")
        self.ctx, self.produto_id = ctx, produto_id
        self.ctrl = OpcoesProdutoController(ctx.banco)
        self.grupos = []
        self.setWindowTitle("Adicionais do produto")
        self.resize(700, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Preços por unidade do produto. Ex.: bacon extra ou ponto da carne.", "suave"))
        pagina = QWidget()
        self.coluna = QVBoxLayout(pagina)
        for g in self.ctrl.grupos(produto_id):
            self.adicionar_grupo(g)
        novo = QPushButton("Adicionar grupo")
        novo.clicked.connect(lambda: self.adicionar_grupo())
        layout.addWidget(novo)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(pagina)
        layout.addWidget(rolagem)
        self.erro = texto("", "aviso")
        layout.addWidget(self.erro)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(self.salvar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def adicionar_grupo(self, dados=None):
        dados = dados or {"id": str(uuid.uuid4()), "nome": "", "minimo": 0, "maximo": 1, "opcoes": []}
        quadro = QGroupBox("Grupo de opções")
        coluna = QVBoxLayout(quadro)
        form = QFormLayout()
        nome = QLineEdit(dados["nome"])
        nome.setMaxLength(60)
        minimo, maximo = QSpinBox(), QSpinBox()
        for campo in (minimo, maximo):
            campo.setRange(0, 20)
        minimo.setValue(dados["minimo"])
        maximo.setValue(dados["maximo"])
        form.addRow("Nome do grupo", nome)
        form.addRow("Mínimo de escolhas", minimo)
        form.addRow("Máximo de escolhas", maximo)
        coluna.addLayout(form)
        tabela = QTableWidget(0, 2)
        tabela.setHorizontalHeaderLabels(["Opção", "Preço adicional (R$)"])
        tabela.setMinimumHeight(150)
        for o in dados["opcoes"]:
            self._linha(tabela, o)
        coluna.addWidget(tabela)
        grupo = (dados["id"], quadro, nome, minimo, maximo, tabela)
        acoes = QHBoxLayout()
        nova = QPushButton("Adicionar opção")
        nova.clicked.connect(lambda: self._linha(tabela))
        acoes.addWidget(nova)
        remover = QPushButton("Remover opção")
        remover.clicked.connect(lambda: tabela.removeRow(tabela.currentRow()) if tabela.currentRow() >= 0 else None)
        acoes.addWidget(remover)
        apagar = QPushButton("Remover grupo")
        apagar.clicked.connect(lambda: self._remover_grupo(grupo))
        acoes.addWidget(apagar)
        coluna.addLayout(acoes)
        self.coluna.addWidget(quadro)
        self.grupos.append(grupo)

    @staticmethod
    def _linha(tabela, opcao=None):
        opcao = opcao or {"id": str(uuid.uuid4()), "nome": "", "preco_cent": 0}
        i = tabela.rowCount()
        tabela.insertRow(i)
        nome = QTableWidgetItem(opcao["nome"])
        nome.setData(Qt.ItemDataRole.UserRole, opcao["id"])
        tabela.setItem(i, 0, nome)
        tabela.setItem(i, 1, QTableWidgetItem(fmt.fmt_num(opcao["preco_cent"])))

    def _remover_grupo(self, grupo):
        self.grupos.remove(grupo)
        grupo[1].setParent(None)
        grupo[1].deleteLater()

    def salvar(self):
        try:
            from src.ui_qt.cadastros import exigir_acesso
            exigir_acesso(self.ctx, "produtos")
            dados = []
            for uid, quadro, nome, minimo, maximo, tabela in self.grupos:
                opcoes = []
                for i in range(tabela.rowCount()):
                    a, b = tabela.item(i, 0), tabela.item(i, 1)
                    if a is None or b is None:
                        raise ValueError("Preencha nome e preço de cada opção.")
                    opcoes.append({"id": a.data(Qt.ItemDataRole.UserRole), "nome": a.text(),
                                   "preco_cent": fmt.para_centavos(b.text())})
                dados.append({"id": uid, "nome": nome.text(), "minimo": minimo.value(),
                              "maximo": maximo.value(), "opcoes": opcoes})
            self.ctrl.salvar(self.produto_id, dados)
        except (ErroNegocio, ValueError) as exc:
            self.erro.setText(str(exc))
            return
        self.accept()
