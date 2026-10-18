"""Pré-visualização Qt de documentos texto, sem envio automático à impressora."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3

from PySide6.QtGui import QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto as rotulo


class JanelaVisualizador(QDialog):
    """Documento imutável; chame ``exec()`` ou ``show()`` para abrir.

    ``modulo`` é a permissão da origem, obrigatória. A sessão que abriu o
    documento e seu acesso atual são revalidados antes de salvar/imprimir,
    inclusive após os diálogos. ``tipo`` é repassado a ``ctx.impressao.enviar``.
    Os métodos de saída retornam bool e preservam o documento em caso de erro.
    """

    def __init__(self, ctx, titulo: str, texto: str, parent=None, *,
                 modulo: str, nome: str = "documento", tipo: str | None = None):
        super().__init__(parent)
        self.ctx, self.texto, self.nome, self.tipo = ctx, texto, nome, tipo
        self.modulo = modulo
        self._operador_id = ctx.operador_id
        self._exigir_acesso()
        self.setWindowTitle(titulo)
        self.resize(1000, 700)
        layout = QVBoxLayout(self)
        barra = QHBoxLayout()
        self.imprimir_botao = QPushButton("Imprimir (Ctrl+P)")
        self.imprimir_botao.clicked.connect(self.imprimir)
        self.salvar_botao = QPushButton("Salvar texto...")
        self.salvar_botao.clicked.connect(lambda: self.salvar())
        fechar = QPushButton("Fechar (Esc)")
        fechar.clicked.connect(self.reject)
        for botao in (self.imprimir_botao, self.salvar_botao, fechar):
            botao.setAutoDefault(False)
            barra.addWidget(botao)
        layout.addLayout(barra)
        self.caixa = QPlainTextEdit()
        self.caixa.setReadOnly(True)
        self.caixa.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.caixa.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.caixa.setPlainText(texto)
        layout.addWidget(self.caixa)
        self.mensagem = rotulo("", "aviso")
        layout.addWidget(self.mensagem)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self.imprimir)

    def _exigir_acesso(self):
        if self.ctx.operador is None or self.ctx.operador_id != self._operador_id:
            raise ErroPermissao("A sessão mudou. Abra o documento novamente.")
        cadastro = self.ctx.cadastros.obter("operadores", self._operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        if not self.modulo:
            raise ErroPermissao("Informe o módulo de origem do documento.")
        operador = self.ctx.acesso.operador(self._operador_id)
        self.ctx.acesso.exigir(operador, self.modulo)

    def salvar(self, caminho=None) -> bool:
        try:
            self._exigir_acesso()
            self.mensagem.clear()
            if not caminho:
                caminho, _ = QFileDialog.getSaveFileName(
                    self, "Salvar texto", self.nome + ".txt", "Texto (*.txt)")
            if not caminho:
                return False
            self._exigir_acesso()
            with Path(caminho).open("w", encoding="utf-8", newline="") as arquivo:
                arquivo.write(self.texto)
        except (ErroNegocio, OSError, ValueError, KeyError, sqlite3.Error) as erro:
            self.mensagem.setText(f"Não foi possível salvar: {erro}")
            return False
        self.mensagem.setText("Texto salvo.")
        return True

    def imprimir(self) -> bool:
        try:
            self._exigir_acesso()
            self.mensagem.clear()
            resposta = QMessageBox.question(
                self, "Imprimir documento", "Enviar este documento para impressão?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if resposta != QMessageBox.StandardButton.Yes:
                return False
            self._exigir_acesso()
            modo = self.ctx.impressao.modo()
            caminho = self.ctx.impressao.enviar(self.texto, self.nome, tipo=self.tipo)
            if modo == "termica":
                mensagem = "Enviado para a fila da impressora térmica."
            elif modo == "windows" and hasattr(os, "startfile"):
                mensagem = "Enviado para a impressora padrão do Windows."
            elif modo != "windows" and hasattr(os, "startfile"):
                os.startfile(caminho, "print")
                mensagem = "Enviado para impressão pelo Windows."
            else:
                self.mensagem.setText(
                    f"Não foi possível imprimir neste sistema. Documento salvo em:\n{caminho}")
                return False
        except (ErroNegocio, OSError, ValueError, KeyError, sqlite3.Error) as erro:
            self.mensagem.setText(f"Não foi possível imprimir: {erro}")
            return False
        self.mensagem.setText(mensagem)
        return True
