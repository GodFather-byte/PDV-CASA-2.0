"""Tela de recuperação da loja pelo backup da nuvem (regra em src/sync/backup_nuvem.py)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.sync import backup_nuvem
from src.ui_qt.tema import texto


class JanelaBackupNuvem(QDialog):
    """Lista os backups da loja na nuvem e marca a recuperação do escolhido para o próximo início do programa."""

    def __init__(self, ctx, parent=None, http=None, perguntar=None):
        super().__init__(parent)
        self.ctx, self._http = ctx, http
        self._perguntar = perguntar or self._perguntar_qt
        self.backups: list[dict] = []
        self.setWindowTitle("Recuperar a loja pelo backup da nuvem")
        self.resize(640, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(texto(
            "Use quando o computador do caixa foi trocado, queimou ou o banco se perdeu. O backup traz produtos, "
            "cadastros, vendas e configurações. O banco atual é guardado antes e o programa precisa ser reaberto.",
            "suave"))
        nivel, situacao = backup_nuvem.situacao(ctx.banco)
        layout.addWidget(texto(situacao, "aviso" if nivel != "ok" else "suave"))
        self.tabela = QTableWidget(0, 3)
        self.tabela.setHorizontalHeaderLabels(["Backup de", "Tamanho", "Versão"])
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.tabela)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        botoes = QHBoxLayout()
        self.btn_recuperar = QPushButton("Recuperar este backup")
        self.btn_recuperar.clicked.connect(self.recuperar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        botoes.addWidget(self.btn_recuperar)
        botoes.addWidget(fechar)
        layout.addLayout(botoes)
        self.carregar()

    def carregar(self) -> None:
        try:
            self.backups = backup_nuvem.listar(self.ctx.banco, self._http)
        except ErroNegocio as erro:
            self.backups = []
            self.mensagem.setText(str(erro))
        self.tabela.setRowCount(len(self.backups))
        for i, b in enumerate(self.backups):
            mb = (b.get("tamanho_banco") or 0) / (1024 * 1024)
            for col, valor in enumerate((fmt.fmt_datahora(b.get("feito_em") or ""), f"{mb:.1f} MB",
                                         str(b.get("esquema") or ""))):
                self.tabela.setItem(i, col, QTableWidgetItem(valor))
        if self.backups:
            self.tabela.selectRow(0)
        elif not self.mensagem.text():
            self.mensagem.setText("Ainda não há backup desta loja na nuvem.")
        self.btn_recuperar.setEnabled(bool(self.backups))

    def _perguntar_qt(self, texto_pergunta: str) -> bool:
        return QMessageBox.question(self, "Recuperar backup", texto_pergunta) == QMessageBox.StandardButton.Yes

    def recuperar(self) -> str | None:
        linhas = self.tabela.selectionModel().selectedRows() if self.tabela.selectionModel() else []
        if not linhas:
            self.mensagem.setText("Escolha um backup da lista.")
            return None
        escolhido = self.backups[linhas[0].row()]
        quando = fmt.fmt_datahora(escolhido.get("feito_em") or "")
        if not self._perguntar(f"Recuperar a loja como estava em {quando}?\nO que foi feito neste caixa depois disso "
                               "fica só na cópia de segurança. O programa precisa ser fechado e aberto de novo."):
            return None
        try:
            feito = backup_nuvem.restaurar(self.ctx.banco, escolhido["id"], self.ctx.operador_id, self._http)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return None
        self.mensagem.setText(f"Pronto: a loja volta como estava em {fmt.fmt_datahora(feito)}. Feche e abra o "
                              "programa para concluir.")
        self.btn_recuperar.setEnabled(False)
        return feito
