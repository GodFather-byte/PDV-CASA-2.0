"""Consulta de backups locais e preparação para o próximo início, sem restauração imediata.

``JanelaVerificarBackup(ctx, parent)``: teste de restauração ISOLADO (integridade, esquema e contagens) numa
pasta temporária. ``exigir_acesso()`` revalida sessão, operador ativo e ``util_backup`` na abertura e antes de
cada ação. Não troca nem marca restauração do banco em uso; a senha de ``.pdvbkp`` só fica em memória.
"""
from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.core.erros import ErroNegocio, ErroPermissao
from src.database import protecao
from src.ui_qt.tema import texto


class JanelaRestaurarBackup(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._controlador()
        self.setWindowTitle("Preparar restauração de backup • Qt")
        self.resize(850, 570)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Preparar restauração de backup local", "titulo"))
        aviso = texto(
            "Escolha um backup válido, dos mais novos para os mais antigos "
            "(até 60). O banco aberto não será substituído nesta janela. "
            "A restauração só acontece no próximo início do programa.", "suave")
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        self.resumo = texto("", "suave")
        layout.addWidget(self.resumo)
        self.grade = QTableWidget(0, 2)
        self.grade.setHorizontalHeaderLabels(("Data e hora / arquivo", "Pasta"))
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.grade.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.grade)
        self.status = texto("Nenhuma restauração preparada nesta janela.", "suave")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.mensagem = texto("", "aviso")
        self.mensagem.setWordWrap(True)
        layout.addWidget(self.mensagem)
        botoes = QHBoxLayout()
        self.btn_atualizar = QPushButton("Atualizar lista")
        self.btn_atualizar.clicked.connect(self.carregar)
        botoes.addWidget(self.btn_atualizar)
        botoes.addStretch()
        self.btn_preparar = QPushButton("Preparar para o próximo início…")
        self.btn_preparar.setEnabled(False)
        self.btn_preparar.clicked.connect(self.preparar)
        botoes.addWidget(self.btn_preparar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        botoes.addWidget(fechar)
        layout.addLayout(botoes)
        self.grade.itemSelectionChanged.connect(
            lambda: self.btn_preparar.setEnabled(bool(self.grade.selectedItems())))
        self.carregar()

    def _controlador(self):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre no sistema para consultar e preparar restauração.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        self.ctx.acesso.exigir(self.ctx.operador, "util_backup")
        if self.ctx.banco.caminho == ":memory:":
            raise ErroNegocio("A restauração exige um banco salvo no computador.")
        return self.ctx.utilitarios

    def carregar(self):
        try:
            controlador = self._controlador()
            atual = Path(self.ctx.banco.caminho).resolve()
            backups = [
                p for p in controlador.listar_backups()
                if p.resolve() != atual and protecao.backup_valido(p)
            ][:60]
        except (ErroNegocio, OSError, ValueError, sqlite3.Error) as erro:
            self.mensagem.setText(str(erro))
            return False
        self.grade.setRowCount(0)
        for caminho in backups:
            linha = self.grade.rowCount()
            self.grade.insertRow(linha)
            item = QTableWidgetItem(
                caminho.name.removeprefix("loja_offline-").removesuffix(".db"))
            item.setData(Qt.ItemDataRole.UserRole, str(caminho))
            item.setToolTip(str(caminho))
            self.grade.setItem(linha, 0, item)
            self.grade.setItem(linha, 1, QTableWidgetItem(str(caminho.parent)))
        self.btn_preparar.setEnabled(False)
        self.resumo.setText(
            f"{len(backups)} backup(s) válido(s). Selecione um para preparar."
            if backups else "Não há backups locais válidos nas pastas configuradas.")
        self.mensagem.clear()
        return True

    def preparar(self):
        linha = self.grade.currentRow()
        if linha < 0 or not self.grade.selectedItems():
            return False
        caminho = self.grade.item(linha, 0).data(Qt.ItemDataRole.UserRole)
        try:
            self._controlador()
            resposta = QMessageBox.question(
                self, "Confirmar preparação de restauração",
                f"Backup escolhido:\n{caminho}\n\n"
                "O sistema voltará ao estado deste backup: tudo o que foi lançado "
                "DEPOIS dele será perdido.\n"
                "Uma cópia do estado de agora será guardada antes.\n"
                "Esta marcação substitui uma eventual restauração já pendente.\n\n"
                "O banco aberto NÃO será substituído agora. A restauração acontecerá "
                "quando o programa for aberto de novo.\n"
                "Preparar a restauração para o próximo início?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if resposta != QMessageBox.StandardButton.Yes:
                return False
            # Revalida a sessão depois da confirmação; o controller valida o backup.
            self._controlador().pedir_restauracao(caminho)
        except (ErroNegocio, OSError, ValueError, sqlite3.Error) as erro:
            self.mensagem.setText(str(erro))
            return False
        self.status.setText(
            f"Restauração marcada: {caminho}\n"
            "FECHE o programa e abra de novo para concluir. O banco aberto não foi substituído.")
        self.mensagem.clear()
        return True


MODULO_VERIFICAR = "util_backup"


class JanelaVerificarBackup(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.exigir_acesso()
        self.setWindowTitle("Verificar backup (teste de restauração) • Qt")
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Verificar backup: integridade e teste de restauração", "titulo"))
        aviso = texto(
            "O backup escolhido é copiado para uma pasta temporária, restaurado ali e conferido "
            "(integridade, esquema e contagens). O banco em uso NÃO é alterado e nenhuma restauração "
            "é marcada.", "suave")
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        self.ultima = texto("", "suave")
        self.ultima.setWordWrap(True)
        layout.addWidget(self.ultima)
        self.grade = QTableWidget(0, 2)
        self.grade.setHorizontalHeaderLabels(("Backup local", "Pasta"))
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.grade.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.grade)
        self.resultado = QPlainTextEdit()
        self.resultado.setReadOnly(True)
        self.resultado.setPlaceholderText("O diagnóstico da verificação aparece aqui.")
        layout.addWidget(self.resultado)
        self.mensagem = texto("", "aviso")
        self.mensagem.setWordWrap(True)
        layout.addWidget(self.mensagem)
        botoes = QHBoxLayout()
        self.btn_recente = QPushButton("Verificar o mais recente")
        self.btn_recente.clicked.connect(lambda: self.verificar())
        self.btn_selecionado = QPushButton("Verificar selecionado")
        self.btn_selecionado.setEnabled(False)
        self.btn_selecionado.clicked.connect(self.verificar_selecionado)
        self.btn_externo = QPushButton("Verificar arquivo criptografado…")
        self.btn_externo.clicked.connect(self.verificar_externo)
        self.btn_atualizar = QPushButton("Atualizar lista")
        self.btn_atualizar.clicked.connect(self.carregar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        for botao in (self.btn_recente, self.btn_selecionado, self.btn_externo, self.btn_atualizar):
            botoes.addWidget(botao)
        botoes.addStretch()
        botoes.addWidget(fechar)
        layout.addLayout(botoes)
        self.grade.itemSelectionChanged.connect(
            lambda: self.btn_selecionado.setEnabled(bool(self.grade.selectedItems())))
        self.carregar()

    def exigir_acesso(self):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre no sistema para verificar backups.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        self.ctx.acesso.exigir(self.ctx.operador, MODULO_VERIFICAR)
        return True

    def _controlador(self):
        self.exigir_acesso()
        return self.ctx.utilitarios

    def _mostrar_ultima(self):
        nivel, situacao = self.ctx.utilitarios.situacao_teste_restauracao()
        self.ultima.setText(situacao)
        self.ultima.setProperty("nivel", nivel)

    def carregar(self):
        try:
            controlador = self._controlador()
            atual = None if self.ctx.banco.caminho == ":memory:" else Path(self.ctx.banco.caminho).resolve()
            backups = [p for p in controlador.listar_backups() if p.resolve() != atual][:60]
        except (ErroNegocio, OSError, ValueError, sqlite3.Error) as erro:
            self.mensagem.setText(str(erro))
            return False
        self.grade.setRowCount(0)
        for caminho in backups:
            linha = self.grade.rowCount()
            self.grade.insertRow(linha)
            item = QTableWidgetItem(caminho.name)
            item.setData(Qt.ItemDataRole.UserRole, str(caminho))
            item.setToolTip(str(caminho))
            self.grade.setItem(linha, 0, item)
            self.grade.setItem(linha, 1, QTableWidgetItem(str(caminho.parent)))
        self.btn_selecionado.setEnabled(False)
        self.btn_recente.setEnabled(bool(backups))
        self._mostrar_ultima()
        self.mensagem.setText("" if backups else "Não há backups locais nas pastas configuradas.")
        return True

    def verificar(self, caminho=None, senha=None):
        """Executa o ensaio; True só quando aprovado. O resultado (aprovado ou não) fica em ``resultado``."""
        self.mensagem.clear()
        try:
            resultado = self._controlador().testar_recuperacao(caminho, senha)
        except (ErroNegocio, OSError, ValueError, sqlite3.Error) as erro:
            self.mensagem.setText(str(erro))
            return False
        self.resultado.setPlainText(self.ctx.utilitarios.texto_teste_restauracao(resultado))
        self._mostrar_ultima()
        if not resultado["ok"]:
            self.mensagem.setText("Backup REPROVADO no teste de restauração. Gere um novo backup e confira o disco.")
        elif resultado.get("avisos"):
            self.mensagem.setText("Backup APROVADO COM AVISOS: restaura, mas há registros sem vínculo. "
                                  "Confira os avisos e chame o suporte antes de depender dele.")
        return resultado["ok"]

    def verificar_selecionado(self):
        linha = self.grade.currentRow()
        if linha < 0 or not self.grade.selectedItems():
            return False
        return self.verificar(self.grade.item(linha, 0).data(Qt.ItemDataRole.UserRole))

    def verificar_externo(self):
        try:
            self._controlador()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        arquivo, _ = QFileDialog.getOpenFileName(
            self, "Escolha o backup criptografado", self.ctx.banco.cfg("backup_externo_pasta"),
            "Backup seguro WillPDV (*.pdvbkp)")
        if not arquivo:
            return False
        senha, aceito = QInputDialog.getText(
            self, "Senha de recuperação", "Informe a senha usada neste arquivo:", QLineEdit.EchoMode.Password)
        if not aceito:
            return False
        return self.verificar(arquivo, senha)
