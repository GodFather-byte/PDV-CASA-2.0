"""Entrada Qt com as mesmas regras de acesso e licença do PDV."""
from __future__ import annotations

import logging
from queue import Empty, Queue
from threading import Event, Thread

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QInputDialog, QLineEdit, QPushButton, QVBoxLayout,
)

from src.core import edicao, licenca
from src.core.erros import ErroNegocio
from src.sync import licenca_nuvem
from src.ui_qt.tema import texto


class TrocaSenha(QDialog):
    def __init__(self, ctx, operador, parent=None):
        super().__init__(parent)
        self.ctx, self.operador = ctx, operador
        self.setWindowTitle("Troque a senha de fábrica")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Antes de continuar, escolha uma senha diferente do nome do operador.", "titulo"))
        formulario = QFormLayout()
        self.nova, self.confirmacao = QLineEdit(), QLineEdit()
        for campo in (self.nova, self.confirmacao):
            campo.setEchoMode(QLineEdit.EchoMode.Password)
            campo.setMaxLength(10)
        formulario.addRow("Nova senha", self.nova)
        formulario.addRow("Repita a senha", self.confirmacao)
        layout.addLayout(formulario)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        botoes = QDialogButtonBox()
        botoes.addButton("Salvar senha", QDialogButtonBox.ButtonRole.AcceptRole)
        botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.salvar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def salvar(self):
        try:
            nova = self.ctx.acesso.validar_nova_senha(self.operador, self.nova.text())
            if nova.upper() != self.confirmacao.text().strip().upper():
                raise ErroNegocio("As senhas não conferem.")
            self.ctx.acesso.trocar_senha(self.operador, nova)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return
        self.nova.clear()
        self.confirmacao.clear()
        self.accept()


class JanelaLogin(QDialog):
    """Rede em thread sem banco/widgets; resultados aplicados só pela thread Qt."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, self.operador = ctx, None
        self._ocupada = False
        self._fechada = False
        self._fila = None
        self._cancelamento = Event()
        self._thread = None
        ed = edicao.atual()
        self.setWindowTitle(f"{ed.nome} • {ed.titulo_entrada}")
        self.setMinimumSize(680, 470)
        layout = QHBoxLayout(self)
        marca = QVBoxLayout()
        marca.addWidget(texto(ed.marca, "marca"))
        marca.addWidget(texto("Seu atendimento\ncomeça aqui.", "titulo"))
        marca.addWidget(texto(ctx.config.nome_loja(), "suave"))
        marca.addStretch()
        if ed.aviso_entrada:
            marca.addWidget(texto(ed.aviso_entrada, "aviso"))
        layout.addLayout(marca, 1)
        formulario = QVBoxLayout()
        formulario.addWidget(texto("Bem-vindo de volta", "titulo"))
        formulario.addWidget(texto("Usuário"))
        self.usuario = QComboBox()
        self.usuario.setEditable(True)
        self.usuario.addItems(ctx.acesso.nomes_login())
        formulario.addWidget(self.usuario)
        formulario.addWidget(texto("Senha"))
        self.senha = QLineEdit()
        self.senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.senha.returnPressed.connect(self.entrar)
        formulario.addWidget(self.senha)
        mostrar = QCheckBox("Mostrar senha")
        mostrar.toggled.connect(lambda ativo: self.senha.setEchoMode(
            QLineEdit.EchoMode.Normal if ativo else QLineEdit.EchoMode.Password))
        formulario.addWidget(mostrar)
        self.mensagem = texto("", "aviso")
        formulario.addWidget(self.mensagem)
        self.btn_entrar = QPushButton("Entrar no PDV")
        self.btn_entrar.setObjectName("primario")
        self.btn_entrar.clicked.connect(self.entrar)
        formulario.addWidget(self.btn_entrar)
        self.btn_esqueci = QPushButton("Esqueci a senha")
        self.btn_esqueci.setToolTip("Gerente sem a senha: gera um pedido para o fornecedor liberar a troca")
        self.btn_esqueci.clicked.connect(self.esqueci_a_senha)
        formulario.addWidget(self.btn_esqueci)
        self.btn_licenca = QPushButton("Ativar licença ou instalar loja")
        self.btn_licenca.setToolTip("Cole o código de licença ou o código de instalação (WILL1-...) da central")
        self.btn_licenca.clicked.connect(self.pedir_licenca)
        self.btn_licenca.setVisible(licenca.exigida(ctx.banco))
        formulario.addWidget(self.btn_licenca)
        self.btn_rede = QPushButton(
            f"Caixa {ctx.banco.cfg_int('terminal', 1)} • desligar do caixa principal" if ctx.banco.remoto
            else "Ligar a outro caixa da loja")
        self.btn_rede.setToolTip("Dois ou mais computadores vendendo no mesmo estoque (código em Caixas da loja)")
        self.btn_rede.clicked.connect(self.ligar_a_outro_caixa)
        self.btn_rede.setVisible(ctx.banco.caminho != ":memory:")
        formulario.addWidget(self.btn_rede)
        formulario.addStretch()
        layout.addLayout(formulario, 1)
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._receber_licenca)

    def _ocupar(self, valor):
        self._ocupada = valor
        for campo in (self.btn_entrar, self.usuario, self.senha, self.btn_licenca, self.btn_esqueci):
            campo.setEnabled(not valor)

    def entrar(self):
        if self._fechada or self._ocupada:
            return
        self._ocupar(True)
        try:
            estado = licenca.estado(self.ctx.banco)
            if self._consultar_nuvem(forcar=estado.bloqueia):
                return
            self._continuar_entrada()
        except Exception as erro:
            self._falha(erro)

    def _consultar_nuvem(self, forcar=False):
        banco = self.ctx.banco
        url, token = banco.cfg("api_url"), banco.cfg("api_token")
        if not url.strip() or not token.strip() or not licenca_nuvem.iniciar_consulta(banco, forcar=forcar):
            return False
        self.mensagem.setText("Verificando licença na nuvem…")
        fila = self._fila = Queue()
        cancelar = self._cancelamento

        def consultar():
            try:
                resultado = licenca_nuvem.consultar_resultado(url, token, timeout=(3, 5))
            except Exception:
                logging.getLogger("pdv.licenca").exception("Falha na consulta Qt.")
                resultado = licenca_nuvem.ResultadoConsulta(False, erro="Falha ao consultar a nuvem.")
            if not cancelar.is_set():
                fila.put(resultado)

        self._thread = Thread(target=consultar, name="licenca-qt", daemon=True)
        self._thread.start()
        self._timer.start()
        return True

    def _receber_licenca(self):
        if self._fechada or self._fila is None:
            return
        try:
            resultado = self._fila.get_nowait()
        except Empty:
            return
        self._timer.stop()
        self._fila = None
        try:
            licenca_nuvem.registrar_resultado(self.ctx.banco, resultado)
            licenca_nuvem.aplicar(self.ctx.banco, resultado.codigo)
            self._continuar_entrada()
        except Exception as erro:
            self._falha(erro)

    def _continuar_entrada(self):
        banco = self.ctx.banco
        estado = licenca.estado(banco)
        turno = self.ctx.turnos.atual()
        if estado.bloqueia and not licenca.turno_vale_como_isencao(banco, turno):
            banco.log("licenca_bloqueio", estado.mensagem)
            self.mensagem.setText(estado.mensagem + "\nAtive um código de licença para entrar.")
            self._ocupar(False)
            return
        senha = self.senha.text()
        operador = self.ctx.acesso.autenticar(self.usuario.currentText(), senha)
        if self.ctx.acesso.precisa_trocar_senha(operador, senha):
            dialogo = TrocaSenha(self.ctx, operador, self)
            resultado = dialogo.exec()
            dialogo.deleteLater()
            if resultado != QDialog.DialogCode.Accepted:
                self.mensagem.setText("Troque a senha de fábrica para entrar no sistema.")
                self.senha.clear()
                self._ocupar(False)
                return
        if licenca.exigida(banco):
            licenca.registrar_uso(banco)
        self.operador = operador
        self.senha.clear()
        self.accept()

    def _falha(self, erro):
        if not isinstance(erro, ErroNegocio):
            logging.getLogger("pdv.qt").exception("Falha na entrada Qt.")
        self.mensagem.setText(str(erro))
        self.senha.clear()
        self._ocupar(False)

    def ligar_a_outro_caixa(self):
        """Faz deste computador um caixa adicional (ou desfaz). Depois da troca o programa fecha: o banco é outro."""
        if self._ocupada or self._fechada:
            return
        from src.ui_qt.rede_caixas import ligar_este_computador
        if ligar_este_computador(self, self.ctx.banco):
            self.reject()

    def esqueci_a_senha(self):
        """Abre a recuperação; trocada a senha, o nome do gerente já fica no campo de usuário."""
        if self._ocupada or self._fechada:
            return None
        from src.ui_qt.esqueci_senha import DialogoEsqueciSenha
        dialogo = DialogoEsqueciSenha(self.ctx, self)
        if dialogo.exec() == QDialog.DialogCode.Accepted and dialogo.operador:
            indice = self.usuario.findText(dialogo.operador)
            if indice >= 0:
                self.usuario.setCurrentIndex(indice)
            else:
                self.usuario.setEditText(dialogo.operador)
            self.senha.clear()
            self.senha.setFocus()
            self.mensagem.setText(f"Senha de {dialogo.operador} trocada. Entre com a senha nova.")
        return dialogo

    def pedir_licenca(self):
        if self._ocupada or self._fechada:
            return
        codigo, aceito = QInputDialog.getMultiLineText(
            self, "Ativar licença ou instalar loja",
            "Cole o código de licença ou o código de instalação (começa com WILL1-) que veio da central:")
        if not aceito or not codigo.strip():
            return
        from src.core import codigo_instalacao
        if codigo_instalacao.parece_codigo(codigo):
            return self.instalar_loja(codigo)
        try:
            licenca.ativar(self.ctx.banco, codigo)
            self.mensagem.setText(licenca.estado(self.ctx.banco).mensagem)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def instalar_loja(self, codigo, http=None):
        """Código de instalação: configura a nuvem do caixa e já busca a licença."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QMessageBox
        from src.sync import instalacao_nuvem
        trocar = False
        while True:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                resultado = instalacao_nuvem.instalar(self.ctx.banco, codigo, http, trocar_loja=trocar)
            except instalacao_nuvem.OutraLoja as erro:
                QApplication.restoreOverrideCursor()
                resposta = QMessageBox.question(
                    self, "Trocar a loja deste caixa?",
                    f"{erro}\n\nTrocar faz este caixa passar a enviar vendas e buscar licença como {erro.nova}. "
                    "Continuar?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if resposta != QMessageBox.StandardButton.Yes:
                    self.mensagem.setText("Instalação cancelada: o caixa continua com a loja atual.")
                    return False
                trocar = True
                continue
            except ErroNegocio as erro:
                QApplication.restoreOverrideCursor()
                self.mensagem.setText(str(erro))
                return False
            QApplication.restoreOverrideCursor()
            self.mensagem.setText(resultado["mensagem"])
            return resultado["licenca_ativa"]

    def cancelar_consulta(self):
        self._fechada = True
        self._cancelamento.set()
        self._timer.stop()
        self._fila = None
        self.senha.clear()

    def done(self, resultado):
        self.cancelar_consulta()
        super().done(resultado)

    def closeEvent(self, evento):
        self.cancelar_consulta()
        super().closeEvent(evento)
