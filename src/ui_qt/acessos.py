"""Níveis mínimos de módulos Qt, exclusivamente pelo AcessoController."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto


class JanelaAcessos(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._exigir()
        self.setWindowTitle("Acessos ao sistema • Qt")
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Acessos ao sistema", "titulo"))
        layout.addWidget(texto(
            "Cada módulo exige um nível mínimo de 1 a 4. Níveis maiores herdam "
            "os menores. O nível 0 é exclusivo do caixa. Esta tela não altera "
            "operadores, senhas ou níveis individuais.", "suave"))
        self.grade = QTableWidget(0, 3)
        self.grade.setHorizontalHeaderLabels(("Grupo", "Módulo", "Nível mínimo"))
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.horizontalHeader().setStretchLastSection(True)
        self.grade.itemSelectionChanged.connect(self._selecionar)
        layout.addWidget(self.grade)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        barra = QHBoxLayout()
        self.nivel = QComboBox()
        for valor in range(1, 5):
            self.nivel.addItem(str(valor), valor)
        self.btn_salvar = QPushButton("Salvar nível do módulo")
        self.btn_recarregar = QPushButton("Recarregar")
        self.btn_salvar.clicked.connect(self.salvar)
        self.btn_recarregar.clicked.connect(self.recarregar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        for widget in (self.nivel, self.btn_salvar, self.btn_recarregar, fechar):
            barra.addWidget(widget)
        layout.addLayout(barra)
        self._carregar()

    def _exigir(self):
        operador_id = self.ctx.operador_id
        if operador_id is None:
            raise ErroPermissao("Entre novamente para configurar os acessos.")
        cadastro = self.ctx.cadastros.obter("operadores", operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        operador = self.ctx.acesso.operador(operador_id)
        self.ctx.acesso.exigir(operador, "cfg_acessos")
        return operador_id

    def _autorizar(self):
        try:
            operador_id = self._exigir()
        except ErroPermissao:
            self.grade.setRowCount(0)
            self.grade.setEnabled(False)
            self.nivel.setCurrentIndex(-1)
            self.nivel.setEnabled(False)
            self.btn_salvar.setEnabled(False)
            self.btn_recarregar.setEnabled(False)
            raise
        for widget in (self.grade, self.nivel, self.btn_salvar, self.btn_recarregar):
            widget.setEnabled(True)
        return operador_id

    def _modulo(self):
        linhas = self.grade.selectionModel().selectedRows()
        if not linhas:
            return None
        return self.grade.item(linhas[0].row(), 1).data(Qt.ItemDataRole.UserRole)

    def _selecionar(self):
        linha = self.grade.currentRow()
        if self._modulo() is not None:
            self.nivel.setCurrentIndex(self.nivel.findData(
                int(self.grade.item(linha, 2).text())))

    def _carregar(self, manter=None):
        modulos = self.ctx.acesso.modulos()
        self.grade.setRowCount(0)
        self.grade.setRowCount(len(modulos))
        selecionada = 0
        for linha, modulo in enumerate(modulos):
            for coluna, chave in enumerate(("grupo", "descricao", "nivel")):
                item = QTableWidgetItem(str(modulo[chave]))
                item.setData(Qt.ItemDataRole.UserRole, modulo["modulo"])
                self.grade.setItem(linha, coluna, item)
            if modulo["modulo"] == manter:
                selecionada = linha
        if modulos:
            self.grade.selectRow(selecionada)
            self._selecionar()

    def showEvent(self, evento):
        super().showEvent(evento)
        try:
            self.exigir_acesso()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def exigir_acesso(self):
        """Revalida cfg_acessos sem descartar a seleção ou o nível em edição."""
        operador_id = self._autorizar()
        if not self.grade.rowCount():
            self._carregar()
        return operador_id

    def recarregar(self):
        try:
            self._autorizar()
            self._carregar(self._modulo())
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        self.mensagem.setText("Níveis recarregados; edição não salva descartada.")
        return True

    def salvar(self):
        try:
            operador_id = self._autorizar()
            modulo, nivel = self._modulo(), self.nivel.currentData()
            if modulo is None:
                raise ErroNegocio("Selecione um módulo.")
            if type(nivel) is not int or not 1 <= nivel <= 4:
                raise ErroNegocio("Escolha um nível de 1 a 4.")
            if self.ctx.acesso.nivel_modulo(modulo) == nivel:
                return True
            resposta = QMessageBox.question(
                self, "Confirmar alteração de acesso",
                f"Alterar o nível mínimo de '{modulo}' para {nivel}? "
                "A alteração vale imediatamente e pode retirar seu acesso a esta tela.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            atual = self._autorizar()
            if resposta != QMessageBox.StandardButton.Yes:
                return False
            if atual != operador_id:
                raise ErroPermissao("A sessão mudou. Confirme novamente a alteração.")
            self.ctx.acesso.alterar_nivel_modulo(modulo, nivel)
            try:
                self._autorizar()
            except ErroPermissao as erro:
                self.mensagem.setText(f"Nível salvo. {erro}")
                return True
            self._carregar(modulo)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        self.mensagem.setText("Nível do módulo salvo.")
        return True
