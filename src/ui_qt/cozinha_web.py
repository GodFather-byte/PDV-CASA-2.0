"""Configuração da cozinha no tablet/TV pelo caixa principal."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout)
from src.cozinha.servico import PORTA_PADRAO, configurar, urls
from src.core.erros import ErroNegocio
from src.ui_qt.tema import texto


class DialogoCozinhaWeb(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Cozinha no tablet / TV")
        self.resize(620, 450)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Cozinha na rede local", "titulo"))
        layout.addWidget(texto("O caixa principal precisa ficar aberto. Use o mesmo Wi-Fi/rede; não precisa de internet. "
                               "O PIN é exclusivo da cozinha. Não há pagamento nesta página.", "suave"))
        form = QFormLayout()
        self.ativo = QCheckBox("Ligado")
        self.ativo.setChecked(ctx.banco.cfg_bool("cozinha_web_ativo"))
        self.porta = QLineEdit(ctx.banco.cfg("cozinha_web_porta", str(PORTA_PADRAO)))
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin.setPlaceholderText("6 a 8 números; vazio mantém o atual")
        self.operador = QComboBox()
        for r in ctx.banco.todos("SELECT id, nome FROM operadores WHERE ativo = 1 ORDER BY nome"):
            self.operador.addItem(r["nome"], r["id"])
        self.operador.setCurrentIndex(max(0, self.operador.findData(ctx.banco.cfg_int("cozinha_web_operador_id", 0))))
        form.addRow("Página no tablet/TV", self.ativo)
        form.addRow("Porta", self.porta)
        form.addRow("PIN da cozinha", self.pin)
        form.addRow("Identificar ações como", self.operador)
        layout.addLayout(form)
        self.endereco = texto("")
        self.endereco.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.endereco)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.qr)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        linha = QHBoxLayout()
        salvar, fechar = QPushButton("Salvar"), QPushButton("Fechar")
        salvar.clicked.connect(self.salvar)
        fechar.clicked.connect(self.accept)
        linha.addWidget(salvar)
        linha.addWidget(fechar)
        layout.addLayout(linha)
        pode = not ctx.banco.remoto and ctx.operador is not None and ctx.pode("cfg_configuracoes")
        for campo in (self.ativo, self.porta, self.pin, self.operador, salvar):
            campo.setEnabled(pode)
        if not pode:
            self.mensagem.setText("Altere esta configuração no caixa principal com acesso de configuração.")
        self.mostrar_endereco()

    def mostrar_endereco(self):
        self.qr.clear()
        if self.ctx.banco.remoto:
            self.endereco.setText("Abra esta configuração no caixa principal para obter o endereço da cozinha.")
            return
        if self.ctx.banco.cfg_bool("cozinha_web_ativo"):
            porta = self.ctx.banco.cfg_int("cozinha_web_porta", PORTA_PADRAO)
            enderecos = urls(porta)
            from src.porteiro.servico import png_qr
            imagem = QPixmap()
            imagem.loadFromData(png_qr(enderecos[0]))
            self.qr.setPixmap(imagem.scaledToWidth(180, Qt.TransformationMode.SmoothTransformation))
            self.endereco.setText("\n".join(enderecos) + "\nModo TV: acrescente ?tv=1 ao endereço. "
                                  "Aguarde até 2 segundos para o servidor aplicar a configuração.")
        else:
            self.endereco.setText("Cozinha web desligada.")

    def salvar(self):
        try:
            configurar(self.ctx.banco, self.ativo.isChecked(), self.porta.text(), self.pin.text(),
                       self.operador.currentData(), self.ctx.operador_id)
        except ErroNegocio as exc:
            self.mensagem.setText(str(exc))
            return
        self.pin.clear()
        self.mensagem.setText("Salvo. Abra o endereço abaixo no tablet/TV da mesma rede.")
        self.mostrar_endereco()
