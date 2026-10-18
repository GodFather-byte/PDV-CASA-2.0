"""Cadastros Qt dirigidos pelas entidades e pelo CadastroController existentes."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from src.controllers.config_controller import modulos_desligados
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto


def exigir_acesso(ctx, chave):
    entidade = ctx.cadastros.entidade(chave)
    if ctx.operador is not None:
        cadastro = ctx.cadastros.obter("operadores", ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        ctx.operador = ctx.acesso.operador(ctx.operador_id)
    if ctx.operador is None or entidade.modulo in modulos_desligados(ctx.banco) or not ctx.pode(entidade.modulo):
        raise ErroPermissao("Seu acesso não permite este cadastro.")
    return entidade


class FormularioCadastro(QDialog):
    def __init__(self, ctx, chave, id_=None, parent=None):
        super().__init__(parent)
        self.ctx, self.chave, self.id_ = ctx, chave, id_
        self.entidade = exigir_acesso(ctx, chave)
        self.setWindowTitle(("Novo • " if id_ is None else "Editar • ") + self.entidade.titulo)
        self.resize(620, 650)
        self.campos = {}
        linha = ctx.cadastros.obter(chave, id_) if id_ is not None else None
        valores = ctx.cadastros.exibir(chave, linha) if linha else ctx.cadastros.valores_iniciais(chave)
        layout = QVBoxLayout(self)
        abas = QTabWidget()
        secoes = {}
        for campo in self.entidade.campos:
            if campo.secao not in secoes:
                pagina = QWidget()
                formulario = QFormLayout(pagina)
                formulario.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                rolagem = QScrollArea()
                rolagem.setWidgetResizable(True)
                rolagem.setWidget(pagina)
                abas.addTab(rolagem, campo.secao)
                secoes[campo.secao] = formulario
            valor = valores.get(campo.nome, "")
            if campo.tipo == "sn":
                editor = QCheckBox("Sim")
                editor.setChecked(str(valor).upper() in ("S", "1", "SIM"))
            elif campo.tipo in ("lookup", "escolha"):
                editor = QComboBox()
                opcoes = (ctx.cadastros.opcoes(campo.lookup) if campo.tipo == "lookup" else campo.opcoes) or []
                editor.addItem("Selecione…", None)
                for identificador, rotulo in opcoes:
                    editor.addItem(str(rotulo), identificador)
                bruto = (linha or {}).get(campo.nome, campo.padrao)
                indice = editor.findData(bruto)
                editor.setCurrentIndex(max(indice, 0))
            else:
                editor = QLineEdit(str(valor or ""))
                if campo.tipo == "senha":
                    editor.setEchoMode(QLineEdit.EchoMode.Password)
                    if id_ is not None:
                        editor.setPlaceholderText("Em branco mantém a senha")
                if campo.tamanho:
                    editor.setMaxLength(campo.tamanho)
                if campo.tipo == "dinheiro":
                    editor.setPlaceholderText("0,00")
            editor.setEnabled(not campo.somente_leitura)
            self.campos[campo.nome] = editor
            secoes[campo.secao].addRow(campo.rotulo + (" *" if campo.obrigatorio else ""), editor)
        layout.addWidget(abas)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        botoes = QDialogButtonBox()
        botoes.addButton("Salvar", QDialogButtonBox.ButtonRole.AcceptRole)
        botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.salvar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def valores(self):
        dados = {}
        for campo in self.entidade.campos:
            if campo.somente_leitura:
                continue
            editor = self.campos[campo.nome]
            if isinstance(editor, QCheckBox):
                dados[campo.nome] = editor.isChecked()
            elif isinstance(editor, QComboBox):
                dados[campo.nome] = editor.currentData()
            else:
                dados[campo.nome] = editor.text()
        return dados

    def salvar(self):
        try:
            exigir_acesso(self.ctx, self.chave)
            self.id_ = self.ctx.cadastros.salvar(self.chave, self.valores(), self.id_)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return
        for campo in self.entidade.campos:
            if campo.tipo == "senha":
                self.campos[campo.nome].clear()
        self.accept()


class JanelaCadastro(QDialog):
    def __init__(self, ctx, chave, parent=None):
        super().__init__(parent)
        self.ctx, self.chave = ctx, chave
        self.entidade = exigir_acesso(ctx, chave)
        self.setWindowTitle(self.entidade.titulo + " • Qt")
        self.resize(1000, 680)
        layout = QVBoxLayout(self)
        layout.addWidget(texto(self.entidade.titulo, "titulo"))
        barra = QHBoxLayout()
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Pesquisar e pressionar Enter")
        self.busca.returnPressed.connect(self.atualizar)
        barra.addWidget(self.busca, 1)
        for titulo, acao in (("Pesquisar", self.atualizar), ("Novo", self.novo),
                             ("Editar", self.editar), ("Excluir", self.excluir)):
            botao = QPushButton(titulo)
            botao.clicked.connect(acao)
            barra.addWidget(botao)
        layout.addLayout(barra)
        self.colunas = [c for c in self.entidade.campos if c.na_grade and c.tipo != "senha"]
        self.grade = QTableWidget(0, len(self.colunas))
        self.grade.setHorizontalHeaderLabels([c.rotulo for c in self.colunas])
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.setAlternatingRowColors(True)
        self.grade.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.grade.horizontalHeader().setStretchLastSection(True)
        self.grade.cellDoubleClicked.connect(lambda *_: self.editar())
        layout.addWidget(self.grade)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        self.atualizar()

    def atualizar(self):
        try:
            exigir_acesso(self.ctx, self.chave)
            linhas = self.ctx.cadastros.listar(self.chave, self.busca.text())
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            self.grade.setRowCount(0)
            return
        self.grade.setRowCount(len(linhas))
        for numero, linha in enumerate(linhas):
            valores = self.ctx.cadastros.exibir(self.chave, linha)
            for coluna, campo in enumerate(self.colunas):
                item = QTableWidgetItem(valores.get(campo.nome, ""))
                item.setData(Qt.ItemDataRole.UserRole, linha["id"])
                self.grade.setItem(numero, coluna, item)
        self.mensagem.setText(f"{len(linhas)} registro(s). Regras e validações do cadastro original.")

    def selecionado(self):
        linha = self.grade.currentRow()
        return self.grade.item(linha, 0).data(Qt.ItemDataRole.UserRole) if linha >= 0 else None

    def _formulario(self, id_=None):
        try:
            dialogo = FormularioCadastro(self.ctx, self.chave, id_, self)
            dialogo.exec()
            dialogo.deleteLater()
            self.atualizar()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def novo(self):
        self._formulario()

    def editar(self):
        id_ = self.selecionado()
        if id_ is not None:
            self._formulario(id_)

    def excluir(self):
        id_ = self.selecionado()
        if id_ is None:
            return
        try:
            exigir_acesso(self.ctx, self.chave)
            if QMessageBox.question(self, "Excluir registro", "Excluir definitivamente o registro selecionado?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            mensagem = self.ctx.cadastros.excluir(self.chave, id_)
            self.atualizar()
            if mensagem:
                self.mensagem.setText(mensagem)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
