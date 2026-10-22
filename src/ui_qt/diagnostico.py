"""Diagnóstico de equipamentos (Qt): impressora, gaveta, balança e leitor.

Abrir não aciona nada. Testes físicos pedem confirmação (padrão: Não), revalidam `cfg_maquinas` depois do diálogo e
separam "comando enviado" de "resultado confirmado pelo operador". O teste do leitor só lê o cadastro.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from src.controllers.diagnostico_controller import DISPOSITIVOS, DiagnosticoController
from src.core.erros import ErroNegocio
from src.ui_qt.tema import texto

LARGURA_MINIMA, ALTURA_MINIMA = 560, 420
COR_ESTADO = {"erro": "#d9534f", "nao_confirmado": "#d9534f", "indisponivel": "#e0a800",
              "confirmado": "#28a745", "enviado": "#17a2b8", "lido": "#17a2b8", "configurado": ""}


class JanelaDiagnostico(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.diag = DiagnosticoController(ctx)
        self.diag.exigir()
        self.setWindowTitle("Diagnóstico de equipamentos • Qt")
        self.status = {}
        self.resultados = {}
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Diagnóstico de equipamentos", "titulo"))
        layout.addWidget(texto(
            "Abrir esta tela não aciona nenhum equipamento. Os testes físicos pedem confirmação e só contam como "
            "funcionando quando você confirmar o que viu. Nada aqui lança venda, estoque ou movimento de caixa.",
            "aviso"))
        pagina = QWidget()
        corpo = QVBoxLayout(pagina)
        self.btn_verificar = self._botao("Verificar impressora (sem imprimir)", self.verificar_impressora)
        self.btn_impressora = self._botao("Imprimir página de teste…", self.testar_impressora)
        corpo.addWidget(self._grupo("impressora", self.btn_verificar, self.btn_impressora))
        self.btn_gaveta = self._botao("Abrir gaveta para teste…", self.testar_gaveta)
        corpo.addWidget(self._grupo("gaveta", self.btn_gaveta))
        self.btn_balanca = self._botao("Ler peso agora…", self.ler_balanca)
        corpo.addWidget(self._grupo("balanca", self.btn_balanca))
        self.campo_leitor = QLineEdit()
        self.campo_leitor.setObjectName("campo_leitor")
        self.campo_leitor.setPlaceholderText("Clique aqui e passe um código no leitor")
        self.campo_leitor.setClearButtonEnabled(True)
        self.campo_leitor.returnPressed.connect(self.conferir_leitura)
        self.btn_leitor = self._botao("Conferir código", self.conferir_leitura)
        corpo.addWidget(self._grupo("leitor", (self.campo_leitor, self.btn_leitor)))
        corpo.addStretch(1)
        self.rolagem = QScrollArea()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setWidget(pagina)
        layout.addWidget(self.rolagem, 1)
        self.mensagem = texto("", "aviso")
        self.mensagem.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.mensagem)
        barra = QHBoxLayout()
        self.btn_atualizar = self._botao("Atualizar (F5)", self.atualizar)
        self.btn_fechar = self._botao("Fechar (Esc)", self.reject)
        barra.addWidget(self.btn_atualizar)
        barra.addStretch(1)
        barra.addWidget(self.btn_fechar)
        layout.addLayout(barra)
        QShortcut(QKeySequence("F5"), self, activated=self.atualizar)
        self._acoes = (self.btn_verificar, self.btn_impressora, self.btn_gaveta, self.btn_balanca,
                       self.btn_leitor, self.campo_leitor, self.btn_atualizar)
        self._dimensionar()
        self.atualizar()
        self.campo_leitor.setFocus()

    def _botao(self, rotulo, acao):
        botao = QPushButton(rotulo)
        # Enter do leitor (ou de qualquer campo) nunca dispara um teste físico.
        botao.setAutoDefault(False)
        botao.setDefault(False)
        botao.clicked.connect(lambda _=False: acao())
        return botao

    def _grupo(self, chave, *widgets):
        grupo = QGroupBox(DISPOSITIVOS[chave])
        grupo.setObjectName(f"grupo_{chave}")
        grade = QGridLayout(grupo)
        estado = texto("", f"status_{chave}")
        estado.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status[chave] = estado
        grade.addWidget(estado, 0, 0, 1, 2)
        # Um botão por linha: em notebook ou com fonte ampliada nada fica cortado na horizontal.
        for linha, item in enumerate(widgets, start=1):
            if isinstance(item, tuple):
                for coluna, widget in enumerate(item):
                    grade.addWidget(widget, linha, coluna)
            else:
                grade.addWidget(item, linha, 0, 1, 2)
        grade.setColumnStretch(0, 1)
        return grupo

    def _dimensionar(self):
        self.setMinimumSize(LARGURA_MINIMA, ALTURA_MINIMA)
        largura, altura = 820, 640
        tela = self.screen() or QGuiApplication.primaryScreen()
        if tela is not None:
            area = tela.availableGeometry()
            largura = max(LARGURA_MINIMA, min(largura, area.width() - 40))
            altura = max(ALTURA_MINIMA, min(altura, area.height() - 60))
        self.resize(largura, altura)

    # ------------------------------------------------------------ estado
    def _mostrar(self, resultado):
        self.resultados[resultado.dispositivo] = resultado
        rotulo = self.status[resultado.dispositivo]
        rotulo.setText(f"<b>{resultado.rotulo}</b><br>{_escapar(resultado.mensagem)}")
        cor = COR_ESTADO.get(resultado.estado, "")
        rotulo.setStyleSheet(f"color: {cor};" if cor else "")

    def _liberar(self, ligado):
        for widget in self._acoes:
            widget.setEnabled(ligado)

    def exigir_acesso(self):
        """Revalida `cfg_maquinas`; sem acesso, desliga os testes e levanta."""
        try:
            operador_id = self.diag.exigir()
        except ErroNegocio as erro:
            self._liberar(False)
            self.mensagem.setText(str(erro))
            raise
        self._liberar(True)
        return operador_id

    def showEvent(self, evento):
        super().showEvent(evento)
        try:
            self.exigir_acesso()
        except ErroNegocio:
            pass

    def atualizar(self):
        try:
            self.exigir_acesso()
        except ErroNegocio:
            return False
        for resultado in self.diag.resumo().values():
            self._mostrar(resultado)
        self.mensagem.setText("Configuração relida. Nenhum equipamento foi acionado.")
        return True

    # ------------------------------------------------------------ diálogos (separados para teste)
    def _perguntar(self, titulo, pergunta):
        resposta = QMessageBox.question(
            self, titulo, pergunta,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        return resposta == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------ ações
    def verificar_impressora(self):
        try:
            achados = self.diag.verificar_impressora()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return None
        except Exception as erro:  # noqa: BLE001 - consulta ao Windows falhou: mostrar, não derrubar
            self.mensagem.setText(f"Não foi possível consultar o Windows: {erro}")
            return None
        linhas = [f"[{a.nivel.upper()}] {a.texto}" + (f" Solução: {a.solucao}" if a.solucao else "") for a in achados]
        self.mensagem.setText("\n".join(linhas) + "\nNada foi impresso.")
        return achados

    def _testar(self, funcao, titulo, aviso, conferencia):
        try:
            operador_id = self.exigir_acesso()
        except ErroNegocio:
            return None
        if not self._perguntar(titulo, aviso):
            self.mensagem.setText("Teste cancelado. Nada foi enviado.")
            return None
        try:
            resultado = funcao(operador_id)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            try:
                self.exigir_acesso()
            except ErroNegocio:
                pass
            return None
        self._mostrar(resultado)
        self.mensagem.setText(resultado.mensagem)
        if resultado.aguarda_conferencia:
            ok = self._perguntar("Conferir resultado", conferencia)
            try:
                resultado = self.diag.confirmar(resultado, ok, operador_id)
            except ErroNegocio as erro:
                self.mensagem.setText(str(erro))
                return resultado
            self._mostrar(resultado)
            self.mensagem.setText(resultado.mensagem)
        return resultado

    def testar_impressora(self):
        return self._testar(
            self.diag.testar_impressora, "Confirmar teste físico",
            "Vai imprimir uma página de teste na impressora configurada. Confira papel e conexão. Continuar?",
            "O papel saiu, com acentos legíveis e corte?")

    def testar_gaveta(self):
        return self._testar(
            self.diag.testar_gaveta, "Confirmar teste físico",
            "Vai ABRIR FISICAMENTE a gaveta de dinheiro. Nenhum movimento de caixa será lançado. "
            "Confira se é seguro abrir agora. Continuar?",
            "A gaveta abriu?")

    def ler_balanca(self):
        return self._testar(
            self.diag.ler_balanca, "Confirmar leitura da balança",
            "Vai consultar a balança pela porta configurada. Coloque um peso conhecido no prato. "
            "Nenhum item será lançado. Continuar?",
            "O peso mostrado confere com o visor da balança?")

    def conferir_leitura(self):
        try:
            self.exigir_acesso()
        except ErroNegocio:
            return None
        resultado = self.diag.avaliar_leitura(self.campo_leitor.text())
        self._mostrar(resultado)
        self.mensagem.setText(resultado.mensagem)
        self.campo_leitor.selectAll()
        self.campo_leitor.setFocus()
        return resultado


def _escapar(conteudo):
    return conteudo.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")