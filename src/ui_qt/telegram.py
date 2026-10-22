"""Configurações do Telegram em Qt, sem carregar nenhuma interface Tk."""
from __future__ import annotations

import re
import threading
import webbrowser

from PySide6.QtCore import QRunnable, QThreadPool, QTimer, Qt, Signal, QObject
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers.telegram_controller import TECLADO
from src.core.erros import ErroNegocio, ErroPermissao
from src.sync.telegram_api import ErroTelegram
from src.ui_qt.tema import texto


_MENSAGEM_TESTE = (
    "✅ Teste do PDV: o Telegram está funcionando! Use os botões abaixo para acompanhar a casa."
)
_FORMATO_TOKEN = re.compile(r"\d{5,}:[\w-]{20,}")


class _SinaisTarefa(QObject):
    concluida = Signal(int, object, object)


class _TarefaRede(QRunnable):
    """Executa somente HTTP; nunca recebe contexto, banco ou widgets."""

    def __init__(self, identificador, operacao, sinais):
        super().__init__()
        self.identificador = identificador
        self.operacao = operacao
        self.sinais = sinais

    def run(self):
        try:
            resultado = self.operacao()
        except Exception as erro:
            self.sinais.concluida.emit(self.identificador, None, erro)
        else:
            self.sinais.concluida.emit(self.identificador, resultado, None)


class JanelaTelegram(QDialog):
    """Paridade Qt da janela Telegram existente; gravação local permanece na thread da GUI."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.tg = ctx.telegram
        self._autorizado = False
        self.exigir_acesso()
        self._sequencia = 0
        self._solicitacao = None
        self._fechado = False
        self._cancelamento = threading.Event()
        self._erro_rede = ""

        self.setWindowTitle("Telegram do dono — acompanhar a casa pelo celular")
        self.resize(780, 700)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Receba no celular o que acontece na casa", "titulo"))
        layout.addWidget(texto(
            "Caixa, cancelamentos e sangrias chegam sozinhos; os botões do bot mostram "
            "vendas, caixa e estoque na hora.", "suave"))

        linha_ativo = QHBoxLayout()
        linha_ativo.addStretch(1)
        self.var_ativo = QCheckBox("Telegram ligado")
        self.var_ativo.toggled.connect(self._alternar)
        linha_ativo.addWidget(self.var_ativo)
        layout.addLayout(linha_ativo)

        caixa_bot = QVBoxLayout()
        caixa_bot.addWidget(texto("1. Crie o bot", "subtitulo"))
        caixa_bot.addWidget(texto(
            "No Telegram, fale com @BotFather: envie /newbot, escolha um nome e um "
            "usuário terminado em “bot”. Copie o TOKEN devolvido e cole aqui:", "normal"))
        linha_token = QHBoxLayout()
        self.ent_token = QLineEdit(self.tg.token)
        self.ent_token.setObjectName("tokenTelegram")
        self.ent_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.ent_token.setPlaceholderText("Token fornecido pelo @BotFather")
        self.var_mostrar = QCheckBox("mostrar")
        self.var_mostrar.toggled.connect(self._mostrar_token)
        self.btn_conectar = QPushButton("Conectar")
        self.btn_conectar.clicked.connect(self.conectar)
        self.btn_botfather = QPushButton("Abrir @BotFather")
        self.btn_botfather.clicked.connect(
            lambda: webbrowser.open("https://t.me/BotFather"))
        for widget in (self.ent_token, self.var_mostrar, self.btn_conectar, self.btn_botfather):
            linha_token.addWidget(widget)
        caixa_bot.addLayout(linha_token)
        self.lbl_bot = texto("", "ok")
        caixa_bot.addWidget(self.lbl_bot)
        layout.addLayout(caixa_bot)

        caixa_codigo = QVBoxLayout()
        caixa_codigo.addWidget(texto("2. Conecte o celular do dono", "subtitulo"))
        caixa_codigo.addWidget(texto(
            "Gere o código e envie ao bot a mensagem exibida. Vale 10 minutos; só quem "
            "digita o código fica autorizado.", "normal"))
        linha_codigo = QHBoxLayout()
        self.btn_codigo = QPushButton("Gerar código")
        self.btn_codigo.clicked.connect(self.gerar_codigo)
        self.btn_abrir_bot = QPushButton("Abrir meu bot")
        self.btn_abrir_bot.clicked.connect(self.abrir_bot)
        linha_codigo.addWidget(self.btn_codigo)
        linha_codigo.addWidget(self.btn_abrir_bot)
        linha_codigo.addStretch(1)
        caixa_codigo.addLayout(linha_codigo)
        self.lbl_codigo = texto("", "titulo")
        self.lbl_instrucao = texto("", "normal")
        caixa_codigo.addWidget(self.lbl_codigo)
        caixa_codigo.addWidget(self.lbl_instrucao)
        layout.addLayout(caixa_codigo)

        agenda = QHBoxLayout()
        self.var_resumo_ativo = QCheckBox("Resumo diário")
        self.var_resumo_ativo.setChecked(self.ctx.banco.cfg_bool("telegram_resumo_ativo", True))
        self.ent_resumo_hora = QLineEdit(self.ctx.banco.cfg("telegram_resumo_hora", "23:00"))
        self.ent_resumo_hora.setMaximumWidth(80)
        self.ent_resumo_hora.setPlaceholderText("hh:mm")
        self.btn_salvar_resumo = QPushButton("Salvar resumo")
        self.btn_salvar_resumo.clicked.connect(self.salvar_resumo)
        agenda.addWidget(self.var_resumo_ativo)
        agenda.addWidget(self.ent_resumo_hora)
        agenda.addWidget(texto("horário local (hh:mm)", "suave"))
        agenda.addWidget(self.btn_salvar_resumo)
        layout.addLayout(agenda)
        self.lbl_agendamento = texto("", "suave")
        self.lbl_agendamento.setWordWrap(True)
        layout.addWidget(self.lbl_agendamento)

        layout.addWidget(texto("3. Celulares conectados", "subtitulo"))
        self.grade = QTableWidget(0, 2)
        self.grade.setHorizontalHeaderLabels(("Quem", "Conectado em"))
        self.grade.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.grade.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.grade.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.grade, 1)

        linha_acoes = QHBoxLayout()
        self.btn_testar = QPushButton("Enviar mensagem de teste")
        self.btn_testar.clicked.connect(self.testar)
        self.btn_remover = QPushButton("Remover selecionado")
        self.btn_remover.clicked.connect(self.remover)
        self.btn_fechar = QPushButton("Fechar")
        self.btn_fechar.clicked.connect(self.close)
        for botao in (self.btn_testar, self.btn_remover, self.btn_fechar):
            linha_acoes.addWidget(botao)
        layout.addLayout(linha_acoes)
        layout.addWidget(texto(
            "O PDV precisa estar ligado e com internet para responder; sem internet os "
            "avisos esperam na fila. As mensagens passam pelos servidores do Telegram: "
            "pareie só quem pode ver o faturamento. Um bot por loja, em um único computador.",
            "suave"))
        self.lbl_status = texto("", "suave")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.atualizar)
        self._timer.start()
        self.atualizar()

    def exigir_acesso(self):
        """Revalida a sessão real; preserva edições locais se o acesso continuar permitido."""
        try:
            operador_id = self.ctx.operador_id
            if operador_id is None:
                raise ErroPermissao("Entre novamente para acessar o Telegram.")
            cadastro = self.ctx.cadastros.obter("operadores", operador_id)
            ativo = cadastro is not None and str(cadastro.get("ativo", "")).strip().upper() in (
                "1", "S", "SIM", "TRUE")
            if not ativo:
                raise ErroPermissao("Operador inativo. Encerre a sessão.")
            operador = self.ctx.acesso.operador(operador_id)
            self.ctx.operador = operador
            self.ctx.acesso.exigir(operador, "cfg_telegram")
        except ErroPermissao as erro:
            if hasattr(self, "ent_token"):
                self._bloquear(str(erro))
            raise
        self._autorizado = True
        return True

    def _autorizar_acao(self):
        try:
            self.exigir_acesso()
        except ErroPermissao as erro:
            QMessageBox.warning(self, "Acesso não permitido", str(erro))
            return False
        return True

    def _bloquear(self, mensagem):
        self._autorizado = False
        self._descartar_rede()
        self._limpar_segredos()
        self.var_ativo.blockSignals(True)
        self.var_ativo.setChecked(False)
        self.var_ativo.blockSignals(False)
        self.grade.setRowCount(0)
        self.lbl_bot.clear()
        self.lbl_codigo.clear()
        self.lbl_instrucao.clear()
        self.lbl_agendamento.clear()
        self.lbl_status.setText(self._mensagem_segura(mensagem))
        for widget in (
            self.var_ativo, self.ent_token, self.var_mostrar, self.btn_conectar,
            self.btn_botfather, self.btn_codigo, self.btn_abrir_bot,
            self.btn_testar, self.btn_remover, self.var_resumo_ativo,
            self.ent_resumo_hora, self.btn_salvar_resumo,
        ):
            widget.setEnabled(False)

    def _habilitar(self):
        for widget in (
            self.var_ativo, self.ent_token, self.var_mostrar, self.btn_conectar,
            self.btn_botfather, self.btn_codigo, self.btn_abrir_bot,
            self.btn_testar, self.btn_remover, self.var_resumo_ativo,
            self.ent_resumo_hora, self.btn_salvar_resumo,
        ):
            widget.setEnabled(True)

    def _mostrar_token(self, mostrar):
        self.ent_token.setEchoMode(
            QLineEdit.EchoMode.Normal if mostrar else QLineEdit.EchoMode.Password)

    def _alternar(self, ligado):
        if not self._autorizado or not self._autorizar_acao():
            return
        if ligado and not (self.tg.token and self.tg.chats()):
            self.var_ativo.blockSignals(True)
            self.var_ativo.setChecked(False)
            self.var_ativo.blockSignals(False)
            QMessageBox.warning(
                self, "Telegram",
                "Primeiro cole o token e conecte o celular do dono (passos 1 e 2).")
            return
        try:
            self.ctx.banco.cfg_set("telegram_ativo", "S" if ligado else "N")
        except Exception as erro:
            self.lbl_status.setText(self._mensagem_segura(erro))
            self.atualizar()

    def salvar_resumo(self):
        if not self._autorizar_acao():
            return False
        try:
            self.tg.salvar_agendamento(self.var_resumo_ativo.isChecked(), self.ent_resumo_hora.text())
        except ErroNegocio as erro:
            QMessageBox.warning(self, "Telegram", str(erro))
            return False
        self.atualizar()
        return True

    def conectar(self):
        if self._fechado or not self._autorizar_acao() or self._solicitacao is not None:
            return False
        token = self.ent_token.text().strip()
        if not _FORMATO_TOKEN.fullmatch(token):
            QMessageBox.warning(
                self, "Telegram",
                "Esse token não parece certo. Ele é como 123456789:ABCdefGhIJK... "
                "(copie inteiro do @BotFather).")
            return False
        cliente = self.tg.cliente(token)
        self._iniciar_rede("conectar", cliente.quem_sou, token)
        return True

    def gerar_codigo(self):
        if not self._autorizar_acao():
            return False
        try:
            self.tg.gerar_codigo()
        except ErroNegocio as erro:
            QMessageBox.warning(self, "Telegram", self._mensagem_segura(erro))
            return False
        self.atualizar()
        return True

    def abrir_bot(self):
        if not self._autorizar_acao():
            return
        if self.tg.bot_usuario():
            webbrowser.open(f"https://t.me/{self.tg.bot_usuario()}")

    def testar(self):
        if self._fechado or not self._autorizar_acao() or self._solicitacao is not None:
            return False
        chats = self.tg.chats()
        if not chats:
            QMessageBox.warning(
                self, "Telegram",
                "Nenhum celular pareado ainda. Gere o código e mande /start CÓDIGO para o bot.")
            return False
        token = self.tg.token
        cliente = self.tg.cliente(token)
        ids_chats = tuple(chat["chat_id"] for chat in chats)
        cancelamento = threading.Event()

        def requisitar():
            enviados = 0
            for chat_id in ids_chats:
                if cancelamento.is_set():
                    break
                cliente.enviar(chat_id, _MENSAGEM_TESTE, TECLADO)
                enviados += 1
            return enviados

        self._iniciar_rede("testar", requisitar, token, cancelamento)
        return True

    def remover(self):
        if not self._autorizar_acao():
            return False
        selecionada = self._chat_selecionado()
        if selecionada is None:
            QMessageBox.warning(self, "Telegram", "Selecione um celular conectado.")
            return False
        resposta = QMessageBox.question(
            self, "Telegram",
            "Remover este celular? Ele deixa de receber os avisos e de consultar o bot.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if resposta != QMessageBox.StandardButton.Yes:
            return False
        if not self._autorizar_acao():
            return False
        try:
            self.tg.remover_chat(selecionada)
        except ErroNegocio as erro:
            QMessageBox.warning(self, "Telegram", self._mensagem_segura(erro))
            return False
        self.atualizar()
        return True

    def _iniciar_rede(self, tipo, operacao, segredo, cancelamento=None):
        self._sequencia += 1
        self._cancelamento = cancelamento or threading.Event()
        identificador = self._sequencia
        self._solicitacao = (identificador, tipo, segredo)
        self.btn_conectar.setEnabled(False)
        self.btn_testar.setEnabled(False)
        sinais = _SinaisTarefa()
        sinais.concluida.connect(
            self._concluir_rede, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(_TarefaRede(identificador, operacao, sinais))

    def _concluir_rede(self, identificador, resultado, erro):
        solicitacao = self._solicitacao
        if self._fechado or solicitacao is None or solicitacao[0] != identificador:
            return
        if not self._autorizar_acao():
            return
        self._solicitacao = None
        _id, tipo, segredo = solicitacao
        self.btn_conectar.setEnabled(True)
        self.btn_testar.setEnabled(True)
        if erro is not None:
            if tipo == "conectar" and isinstance(erro, ErroTelegram) and erro.codigo in (401, 404):
                mensagem = "O Telegram não aceitou esse token: confira se copiou inteiro."
            else:
                mensagem = self._mensagem_segura(erro, segredo)
            self._erro_rede = mensagem
            self.lbl_status.setText(f"⚠ {mensagem}")
            QMessageBox.warning(self, "Telegram", mensagem)
            return
        if tipo == "conectar":
            try:
                self.tg.salvar_token_validado(segredo, resultado)
            except Exception as erro_gravacao:
                mensagem = self._mensagem_segura(erro_gravacao, segredo)
                self._erro_rede = mensagem
                self.lbl_status.setText(f"⚠ {mensagem}")
                QMessageBox.warning(self, "Telegram", mensagem)
                return
            self._erro_rede = ""
            self.atualizar()
        elif tipo == "testar":
            self._erro_rede = ""
            QMessageBox.information(
                self, "Telegram",
                f"Mensagem de teste enviada para {resultado} celular(es).\n"
                "Confira no Telegram.")
            self.atualizar()

    def _mensagem_segura(self, erro, segredo=""):
        mensagem = str(erro)
        for token in (segredo, self.ent_token.text().strip(), self.tg.token):
            if token:
                mensagem = mensagem.replace(token, "[token oculto]")
        return re.sub(r"\d{5,}:[\w-]{20,}", "[token oculto]", mensagem)

    def _chat_selecionado(self):
        itens = self.grade.selectionModel().selectedRows()
        if not itens:
            return None
        item = self.grade.item(itens[0].row(), 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def atualizar(self):
        if self._fechado:
            return False
        try:
            self.exigir_acesso()
        except ErroPermissao as erro:
            self._bloquear(str(erro))
            return False
        self._habilitar()
        self.btn_conectar.setEnabled(self._solicitacao is None)
        selecao = self._chat_selecionado()
        tg = self.tg
        usuario = tg.bot_usuario()
        self.lbl_bot.setText(
            f"✔ Bot reconhecido: @{usuario}" if tg.token and usuario else "")
        self.btn_codigo.setEnabled(bool(tg.token) and self._solicitacao is None)
        self.btn_abrir_bot.setEnabled(bool(usuario))
        codigo = tg.codigo_pendente()
        if codigo:
            self.lbl_codigo.setText(f"/start {codigo}")
            self.lbl_instrucao.setText(
                f"No celular, abra a conversa com @{usuario} e envie exatamente a mensagem acima.")
        else:
            self.lbl_codigo.clear()
            self.lbl_instrucao.clear()

        chats = tg.chats()
        self.grade.setRowCount(len(chats))
        linha_selecionada = None
        for linha, chat in enumerate(chats):
            nome = chat["nome"] or f"(chat {chat['chat_id']})"
            criado = (chat["criado_em"] or "")[:16]
            quem = QTableWidgetItem(nome)
            quem.setData(Qt.ItemDataRole.UserRole, chat["chat_id"])
            self.grade.setItem(linha, 0, quem)
            self.grade.setItem(linha, 1, QTableWidgetItem(criado))
            if chat["chat_id"] == selecao:
                linha_selecionada = linha
        if linha_selecionada is not None:
            self.grade.selectRow(linha_selecionada)
        self.var_ativo.blockSignals(True)
        self.var_ativo.setChecked(tg.ligado())
        self.var_ativo.blockSignals(False)
        self.lbl_agendamento.setText(tg.texto_agendamento())
        self.btn_remover.setEnabled(bool(chats))
        self.btn_testar.setEnabled(bool(chats) and self._solicitacao is None)
        erro = self._erro_rede or tg.ultimo_erro()
        if erro:
            self.lbl_status.setText(f"⚠ {self._mensagem_segura(erro)}")
        elif tg.ligado() and chats:
            self.lbl_status.setText(
                f"● Ligado: {len(chats)} celular(es) pareado(s). "
                "Use a mensagem de teste para conferir o recebimento.")
        elif chats:
            self.lbl_status.setText(
                '● Desligado: marque "Telegram ligado" para voltar a avisar.')
        else:
            self.lbl_status.setText("Ainda não há celular conectado.")
        return True

    def showEvent(self, evento):
        super().showEvent(evento)
        if self._fechado:
            try:
                self.exigir_acesso()
            except ErroPermissao:
                return
            self.ent_token.setText(self.tg.token)
        self._fechado = False
        self._timer.start()
        self.atualizar()

    def closeEvent(self, evento):
        self._encerrar()
        super().closeEvent(evento)

    def done(self, resultado):
        self._encerrar()
        super().done(resultado)

    def _descartar_rede(self):
        self._cancelamento.set()
        self._sequencia += 1
        self._solicitacao = None

    def _limpar_segredos(self):
        self.ent_token.clear()
        self.var_mostrar.setChecked(False)
        self.ent_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.lbl_codigo.clear()
        self.lbl_instrucao.clear()
        self._erro_rede = ""

    def _encerrar(self):
        self._fechado = True
        self._descartar_rede()
        self._timer.stop()
        self._limpar_segredos()
        self.lbl_status.clear()


def abrir(ctx, parent=None):
    return JanelaTelegram(ctx, parent)
