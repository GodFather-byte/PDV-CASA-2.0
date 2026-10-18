"""Avisos de atualização em Qt; nada é instalado ou aberto automaticamente.

Integração: mantenha uma JanelaAtualizacoes(ctx, parent) e ligue o timer da
aplicação a consultar_automaticamente(). Ela permanece invisível, respeita o
intervalo do serviço e emite aviso_alterado(aviso ou None) sem popup. O menu
pode chamar exigir_acesso(), show() e raise_() na mesma instância.
Ao sair da sessão, pare o timer e chame cancelar_consulta(); fechar/reject
também descarta respostas em trânsito. Uma próxima chamada pode iniciar nova
consulta invisível. consultar() força a consulta manual.
"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from src.core.erros import ErroPermissao
from src.sync import atualizacoes
from src.ui_qt.tema import texto


class _Sinais(QObject):
    concluida = Signal(int, object, object)


class _Consulta(QRunnable):
    """Recebe apenas cópias da configuração e o canal de retorno."""

    def __init__(self, numero, url, token, sinais):
        super().__init__()
        self.numero, self.url, self.token, self.sinais = numero, url, token, sinais

    def run(self):
        try:
            dados = atualizacoes.consultar(self.url, self.token)
        except Exception:
            self.sinais.concluida.emit(
                self.numero, None,
                "Erro inesperado ao consultar atualizações. Tente novamente.")
        else:
            self.sinais.concluida.emit(self.numero, dados, None)


class JanelaAtualizacoes(QDialog):
    aviso_alterado = Signal(object)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._sequencia = 0
        self._solicitacao = None
        self._fechado = False
        self.aviso = None
        self.exigir_acesso()
        self.setWindowTitle("Atualizações do PDV")
        self.resize(660, 480)
        layout = QVBoxLayout(self)
        self.titulo = texto("Atualizações do PDV", "titulo")
        self.titulo.setWordWrap(True)
        layout.addWidget(self.titulo)
        self.notas = QPlainTextEdit()
        self.notas.setReadOnly(True)
        layout.addWidget(self.notas)
        self.mensagem = texto("", "aviso")
        self.mensagem.setWordWrap(True)
        layout.addWidget(self.mensagem)
        barra = QHBoxLayout()
        self.btn_consultar = QPushButton("Consultar agora")
        self.btn_consultar.clicked.connect(lambda: self.consultar())
        self.btn_baixar = QPushButton("Baixar a atualização")
        self.btn_baixar.clicked.connect(self.baixar)
        self.btn_dispensar = QPushButton("Não avisar desta versão")
        self.btn_dispensar.clicked.connect(self.dispensar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        for botao in (self.btn_consultar, self.btn_baixar, self.btn_dispensar, fechar):
            barra.addWidget(botao)
        layout.addLayout(barra)
        self._sinais = _Sinais()
        self._sinais.concluida.connect(
            self._receber, Qt.ConnectionType.QueuedConnection)
        self._limite = QTimer(self)
        self._limite.setSingleShot(True)
        self._limite.setInterval(15000)
        self._limite.timeout.connect(self._expirar)
        self._mostrar_pendente()

    def exigir_acesso(self):
        """O aviso Tk não exige módulo: basta uma sessão ativa, de qualquer nível."""
        try:
            operador_id = self.ctx.operador_id
            cadastro = (self.ctx.cadastros.obter("operadores", operador_id)
                        if operador_id is not None else None)
            if cadastro is None or not cadastro["ativo"]:
                raise ErroPermissao("Entre novamente para consultar as atualizações.")
            return operador_id
        except ErroPermissao:
            if hasattr(self, "notas"):
                self.cancelar_consulta()
                self.aviso = None
                self.notas.clear()
                self.titulo.setText("Atualizações do PDV")
                self.btn_baixar.setEnabled(False)
                self.btn_dispensar.setEnabled(False)
                self.btn_consultar.setEnabled(False)
            raise

    def _mostrar_pendente(self):
        self.aviso = atualizacoes.pendente(self.ctx.banco)
        aviso = self.aviso
        self.btn_baixar.setEnabled(bool(aviso and aviso.get("url_download")))
        self.btn_dispensar.setEnabled(bool(aviso and not aviso["critica"]))
        if aviso is None:
            self.titulo.setText("Nenhuma atualização pendente.")
            self.notas.clear()
        else:
            self.titulo.setText(
                f"Versão {aviso['ultima']} disponível. Você usa a {aviso['versao_instalada']}."
                + ("\nEsta atualização é IMPORTANTE: corrige problemas de dinheiro ou de dados."
                   if aviso["critica"] else ""))
            partes = [
                f"Versão {v['versao']}{' (importante)' if v.get('critica') else ''}\n"
                f"{v.get('notas') or ''}" for v in aviso["versoes"][:5]
            ]
            if not aviso.get("url_download"):
                partes.append("Peça o arquivo da atualização ao fornecedor do sistema.")
            self.notas.setPlainText("\n\n".join(partes))
        self.aviso_alterado.emit(aviso)

    def consultar_automaticamente(self):
        """Callback de timer: consulta silenciosa, no máximo a cada seis horas."""
        return self.consultar(forcar=False)

    def consultar(self, forcar=True):
        try:
            operador_id = self.exigir_acesso()
        except ErroPermissao as erro:
            self.mensagem.setText(str(erro))
            return False
        if self._solicitacao is not None:
            return False
        banco = self.ctx.banco
        url, token = banco.cfg("api_url"), banco.cfg("api_token")
        if not url.strip() or not token.strip():
            self.mensagem.setText("Configure o endereço da nuvem e o token da loja.")
            return False
        if not forcar and not atualizacoes.precisa_consultar(banco):
            self._mostrar_pendente()
            return False
        self._sequencia += 1
        self._fechado = False
        self._solicitacao = (self._sequencia, operador_id, url, token)
        self.btn_consultar.setEnabled(False)
        self.mensagem.setText("Consultando atualizações…")
        self._limite.start()
        QThreadPool.globalInstance().start(
            _Consulta(self._sequencia, url, token, self._sinais))
        return True

    @Slot(int, object, object)
    def _receber(self, numero, dados, erro=None):
        pedido = self._solicitacao
        if self._fechado or pedido is None or pedido[0] != numero:
            return
        self.cancelar_consulta()
        try:
            operador_id = self.exigir_acesso()
        except ErroPermissao as erro:
            self.mensagem.setText(str(erro))
            return
        banco = self.ctx.banco
        if (operador_id, banco.cfg("api_url"), banco.cfg("api_token")) != pedido[1:]:
            self.mensagem.setText("A sessão ou a configuração mudou; consulte novamente.")
            return
        if erro is not None:
            self.mensagem.setText(erro)
            return
        atualizacoes.gravar(banco, dados)
        self._mostrar_pendente()
        self.mensagem.setText(
            "Consulta concluída." if dados is not None else
            "Não foi possível consultar a nuvem. O aviso anterior foi preservado.")

    def cancelar_consulta(self):
        """Invalida o retorno, sem aguardar a rede (timeout HTTP permanece 3/10 s)."""
        self._solicitacao = None
        self._limite.stop()
        self.btn_consultar.setEnabled(True)

    def _expirar(self):
        self.cancelar_consulta()
        self.mensagem.setText("A consulta demorou demais. Tente novamente.")

    def baixar(self):
        try:
            self.exigir_acesso()
        except ErroPermissao as erro:
            self.mensagem.setText(str(erro))
            return False
        self._mostrar_pendente()
        if self.aviso and self.aviso.get("url_download"):
            webbrowser.open(self.aviso["url_download"])
            return True
        return False

    def dispensar(self):
        try:
            self.exigir_acesso()
        except ErroPermissao as erro:
            self.mensagem.setText(str(erro))
            return False
        self._mostrar_pendente()
        if not self.aviso or self.aviso["critica"]:
            return False
        atualizacoes.dispensar(self.ctx.banco, self.aviso)
        self._mostrar_pendente()
        return True

    def showEvent(self, evento):
        super().showEvent(evento)
        self._fechado = False
        try:
            self.exigir_acesso()
        except ErroPermissao as erro:
            self.mensagem.setText(str(erro))
            return
        self.btn_consultar.setEnabled(self._solicitacao is None)
        self._mostrar_pendente()

    def done(self, resultado):
        self.cancelar_consulta()
        self._fechado = True
        super().done(resultado)

    def closeEvent(self, evento):
        self.cancelar_consulta()
        self._fechado = True
        super().closeEvent(evento)
