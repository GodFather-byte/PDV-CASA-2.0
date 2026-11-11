"""Tela "Esqueci a senha": mostra o pedido, recebe a liberação do fornecedor e grava a senha nova de um gerente."""
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from src.core import recuperacao_senha
from src.core.erros import ErroNegocio
from src.sync import recuperacao_senha as nuvem
from src.ui_qt.tema import texto


class DialogoEsqueciSenha(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.liberacao = ""                     # o código já conferido
        self.operador = None                    # nome do gerente que recebeu a senha nova
        self.setWindowTitle("Esqueci a senha")
        self.resize(640, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Esqueci a senha do gerente", "titulo"))
        layout.addWidget(texto(
            "Só o fornecedor do sistema libera a troca. Nada é apagado: vendas, estoque e cadastros continuam como estão.",
            "suave"))

        passo1 = self._cartao(layout, "1. Envie este pedido ao fornecedor")
        self.pedido = recuperacao_senha.pedido_atual(ctx.banco)
        loja = recuperacao_senha.loja_desta_instalacao(ctx.banco)
        self.rotulo_pedido = texto(recuperacao_senha.formatar_pedido(self.pedido), "kpi_valor", quebra=False)
        passo1.addWidget(self.rotulo_pedido)
        passo1.addWidget(texto(f"Loja: {loja or 'sem chave de loja (informe o nome da casa)'}. "
                               f"O pedido vale {recuperacao_senha.HORAS_PEDIDO} horas.", "suave"))
        self.btn_copiar = QPushButton("Copiar pedido")
        self.btn_copiar.clicked.connect(self.copiar_pedido)
        passo1.addWidget(self.btn_copiar)

        passo2 = self._cartao(layout, "2. Receba a liberação")
        linha = QHBoxLayout()
        self.btn_nuvem = QPushButton("Buscar liberação na nuvem")
        self.btn_nuvem.setToolTip("Com internet, o caixa busca sozinho o que o fornecedor liberou na central.")
        self.btn_nuvem.clicked.connect(self.buscar_na_nuvem)
        self.btn_nuvem.setVisible(nuvem.disponivel(ctx.banco))
        linha.addWidget(self.btn_nuvem)
        self.btn_conferir = QPushButton("Conferir o código colado")
        self.btn_conferir.clicked.connect(self.conferir)
        linha.addWidget(self.btn_conferir)
        passo2.addLayout(linha)
        self.codigo = QPlainTextEdit()
        self.codigo.setPlaceholderText("Sem internet: cole aqui o código que o fornecedor enviar (começa com PDVR1.)")
        self.codigo.setFixedHeight(74)
        passo2.addWidget(self.codigo)

        passo3 = self._cartao(layout, "3. Cadastre a senha nova")
        self.gerente = QComboBox()
        for operador in recuperacao_senha.gerentes(ctx.banco):
            self.gerente.addItem(operador["nome"], operador["id"])
        passo3.addWidget(self.gerente)
        self.nova = QLineEdit()
        self.nova.setEchoMode(QLineEdit.EchoMode.Password)
        self.nova.setMaxLength(10)
        self.nova.setPlaceholderText("Senha nova (até 10 letras ou números)")
        self.confirmar = QLineEdit()
        self.confirmar.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirmar.setMaxLength(10)
        self.confirmar.setPlaceholderText("Repita a senha nova")
        self.confirmar.returnPressed.connect(self.gravar)
        passo3.addWidget(self.nova)
        passo3.addWidget(self.confirmar)
        self.btn_gravar = QPushButton("Gravar senha nova")
        self.btn_gravar.setObjectName("primario")
        self.btn_gravar.clicked.connect(self.gravar)
        passo3.addWidget(self.btn_gravar)

        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        layout.addWidget(fechar)
        self._liberar_passo3(False)
        if not self.gerente.count():
            self.mensagem.setText("Não há gerente ativo nesta loja. Fale com o fornecedor.")

    @staticmethod
    def _cartao(layout, titulo):
        quadro = QFrame()
        quadro.setObjectName("cartao")
        corpo = QVBoxLayout(quadro)
        corpo.addWidget(texto(titulo, "secao"))
        layout.addWidget(quadro)
        return corpo

    def _liberar_passo3(self, liberado):
        for campo in (self.gerente, self.nova, self.confirmar, self.btn_gravar):
            campo.setEnabled(liberado and self.gerente.count() > 0)

    def copiar_pedido(self):
        QApplication.clipboard().setText(recuperacao_senha.formatar_pedido(self.pedido))
        self.mensagem.setText("Pedido copiado. Envie ao fornecedor pelo WhatsApp.")

    def buscar_na_nuvem(self, http=None):
        try:
            codigo = nuvem.buscar_liberacao(self.ctx.banco, self.pedido, http or None)
        except RuntimeError as erro:
            self.mensagem.setText(str(erro))
            return False
        if not codigo:
            self.mensagem.setText("O fornecedor ainda não liberou este pedido. Envie o pedido a ele e tente de novo.")
            return False
        self.codigo.setPlainText(codigo)
        return self.conferir()

    def conferir(self):
        try:
            recuperacao_senha.conferir(self.ctx.banco, self.codigo.toPlainText())
        except ErroNegocio as erro:
            self.liberacao = ""
            self._liberar_passo3(False)
            self.mensagem.setText(str(erro))
            return False
        self.liberacao = self.codigo.toPlainText()
        self._liberar_passo3(True)
        self.mensagem.setText("Liberação confirmada. Escolha o gerente e cadastre a senha nova.")
        self.nova.setFocus()
        return True

    def gravar(self):
        if not self.liberacao:
            self.mensagem.setText("Primeiro receba a liberação do fornecedor.")
            return False
        if self.nova.text() != self.confirmar.text():
            self.mensagem.setText("As duas senhas não são iguais. Digite de novo.")
            return False
        try:
            self.operador = recuperacao_senha.redefinir(self.ctx.banco, self.liberacao, self.gerente.currentData(),
                                                        self.nova.text())
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        self.accept()
        return True
