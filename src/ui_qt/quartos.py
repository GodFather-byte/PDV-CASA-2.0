"""Painel Qt do controle de quartos: um cartão por quarto com a contagem do tempo.

Somente o QuartosController decide estados e grava; aqui só se mostra, avisa (som, janela na frente e campainha do
quarto) e chama o controlador. O cliente paga antes no caixa; o painel não lança nada na comanda.
"""
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from src.controllers.config_controller import modulos_desligados
from src.controllers.quartos_controller import MAX_BLOCOS, QuartosController, fmt_duracao, fmt_relogio
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.hardware import campainha
from src.ui_qt.tema import texto

REPETIR_TOQUE_SEG = 60      # tempo esgotado: toca de novo a cada minuto até liberar
VERIFICAR_CAMPAINHAS_SEG = 30
COLUNAS = 4

# estado -> (fundo, texto)
CORES = {
    "livre": ("#3a3a3a", "#cfcfcf"),
    "uso": ("#1e7d32", "#ffffff"),
    "alerta": ("#f9a825", "#000000"),
    "estourou": ("#c62828", "#ffffff"),
    "piscar": ("#ff8a80", "#000000"),
}
ROTULO_ESTADO = {"livre": "LIVRE", "uso": "Em uso", "alerta": "Acabando", "estourou": "TEMPO ESGOTADO"}


class _Ponte(QObject):
    """Leva o resultado da campainha (thread de envio) para a thread da tela."""
    resultado = Signal(int, bool)


class DialogoTempo(QDialog):
    """Escolha do tempo em blocos (1 bloco = 30 min por padrão), com atalhos e o valor informativo."""

    def __init__(self, ctrl: QuartosController, titulo: str, maximo: int = MAX_BLOCOS, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWindowTitle(titulo)
        form = QFormLayout(self)
        minutos = ctrl.config()["minutos_bloco"]
        self.blocos = QSpinBox()
        self.blocos.setRange(1, max(1, maximo))
        self.blocos.setObjectName("quarto_blocos")
        self.blocos.setStyleSheet("font-size: 22px; padding: 6px;")
        form.addRow(f"Blocos de {fmt_duracao(minutos)}:", self.blocos)
        self.resumo = QLabel()
        self.resumo.setStyleSheet("font-size: 20px; font-weight: bold;")
        form.addRow(self.resumo)
        atalhos = QHBoxLayout()
        for b in (1, 2, 4, 6):
            if b <= maximo:
                botao = QPushButton(fmt_duracao(b * minutos))
                botao.setAutoDefault(False)
                botao.clicked.connect(lambda _=False, v=b: self.blocos.setValue(v))
                atalhos.addWidget(botao)
        form.addRow(atalhos)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        form.addRow(botoes)
        self.blocos.valueChanged.connect(self._atualizar)
        self._atualizar()

    def _atualizar(self):
        self.resumo.setText(self.ctrl.rotulo_blocos(self.blocos.value()))


class CartaoQuarto(QFrame):
    def __init__(self, numero: int, painel: "JanelaQuartos"):
        super().__init__()
        self.numero = numero
        self.painel = painel
        self.item: dict = {"estado": "livre"}
        self.avisou_alerta = False
        self.ultimo_toque = None
        self.piscar = False
        self.setObjectName("cartao_quarto")
        self.setMinimumSize(220, 200)
        lay = QVBoxLayout(self)
        topo = QHBoxLayout()
        self.titulo = QLabel(f"QUARTO {numero}")
        self.titulo.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.sino = QLabel("")
        self.sino.setToolTip("Campainha do quarto")
        topo.addWidget(self.titulo)
        topo.addStretch()
        topo.addWidget(self.sino)
        lay.addLayout(topo)
        self.tempo = QLabel("LIVRE")
        self.tempo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tempo.setStyleSheet("font-size: 34px; font-weight: bold;")
        lay.addWidget(self.tempo)
        self.info = QLabel("")
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        botoes = QHBoxLayout()
        self.b_iniciar = QPushButton("Iniciar")
        self.b_mais = QPushButton("+ Tempo")
        self.b_liberar = QPushButton("Liberar")
        for botao, acao in ((self.b_iniciar, self.iniciar), (self.b_mais, self.mais_tempo),
                            (self.b_liberar, self.liberar)):
            botao.setMinimumHeight(36)
            botao.setStyleSheet("padding: 4px 2px;")   # o padding do tema corta o texto no cartão
            botao.setAutoDefault(False)
            botao.clicked.connect(acao)
            botoes.addWidget(botao)
        lay.addLayout(botoes)

    # ---- ações (sempre pelo controlador) ----
    def iniciar(self):
        ctrl = self.painel.controlador()
        dlg = DialogoTempo(ctrl, f"Iniciar quarto {self.numero}", parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.painel.executar(lambda: ctrl.iniciar(self.numero, dlg.blocos.value()), self.numero)

    def mais_tempo(self):
        ctrl = self.painel.controlador()
        maximo = MAX_BLOCOS - int(self.item.get("blocos") or 0)
        if maximo < 1:
            self.painel.mensagem.setText(f"O quarto {self.numero} já está no tempo máximo.")
            return
        dlg = DialogoTempo(ctrl, f"Adicionar tempo — quarto {self.numero}", maximo, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.painel.executar(lambda: ctrl.adicionar_tempo(self.numero, dlg.blocos.value()), self.numero)

    def liberar(self):
        resposta = QMessageBox.question(self, "Liberar quarto", f"Liberar o quarto {self.numero}?")
        if resposta == QMessageBox.StandardButton.Yes:
            self.painel.executar(lambda: self.painel.controlador().liberar(self.numero), self.numero)

    def zerar_avisos(self):
        self.avisou_alerta = False
        self.ultimo_toque = None

    def definir_campainha(self, tem: bool, ok: bool | None):
        if not tem:
            self.sino.setText("")
        elif ok is None:
            self.sino.setText("🔔 ?")
        else:
            self.sino.setText("🔔 ok" if ok else "🔕 off")
            self.sino.setToolTip("Campainha ligada" if ok else "Campainha fora do ar: confira o aparelho e o Wi-Fi")

    # ---- desenho a cada segundo ----
    def _cor(self, chave: str):
        fundo, letra = CORES[chave]
        self.setStyleSheet(
            f"QFrame#cartao_quarto {{ background: {fundo}; border-radius: 10px; }}"
            f"QFrame#cartao_quarto QLabel {{ color: {letra}; background: transparent; }}")

    def mostrar(self, item: dict, agora):
        anterior = self.item.get("uso_id")
        self.item = item
        if item.get("uso_id") != anterior:
            self.zerar_avisos()
        estado = item["estado"]
        livre = estado == "livre"
        self.b_iniciar.setEnabled(livre)
        self.b_mais.setEnabled(not livre)
        self.b_liberar.setEnabled(not livre)
        if livre:
            self._cor("livre")
            self.tempo.setText("LIVRE")
            self.info.setText("")
            return
        self.info.setText(
            f"{fmt_duracao(item['minutos'])} ({fmt.fmt_brl(item['valor_cent'])})\n"
            f"Entrou {item['inicio']:%H:%M} · Sai {item['fim']:%H:%M}")
        if estado == "uso":
            self._cor("uso")
            self.tempo.setText(fmt_relogio(item["restante_seg"]))
        elif estado == "alerta":
            self._cor("alerta")
            self.tempo.setText(fmt_relogio(item["restante_seg"]))
            if not self.avisou_alerta:
                self.avisou_alerta = True
                self.painel.avisar(self.numero, "alerta")
        else:
            self.piscar = not self.piscar
            self._cor("piscar" if self.piscar else "estourou")
            self.tempo.setText("+" + fmt_relogio(item["restante_seg"]))
            if self.ultimo_toque is None or (agora - self.ultimo_toque).total_seconds() >= REPETIR_TOQUE_SEG:
                self.ultimo_toque = agora
                self.painel.avisar(self.numero, "tocar")


class JanelaQuartos(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._operador_id = ctx.operador_id
        self.exigir_acesso()
        self.setWindowTitle("Controle de Quartos • Qt")
        self.resize(1050, 620)
        self.cartoes: dict[int, CartaoQuarto] = {}
        self.campainha_ok: dict[int, bool | None] = {}
        self._ponte = _Ponte(self)
        self._ponte.resultado.connect(self._resultado_campainha)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Controle de Quartos", "titulo"))
        layout.addWidget(texto(
            "O cliente paga no caixa e depois o tempo começa aqui. Amarelo: tempo acabando; vermelho: tempo esgotado "
            "(o caixa e a campainha do quarto avisam até liberar).", "suave"))
        self.grade_widget = QWidget()
        self.grade = QGridLayout(self.grade_widget)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(self.grade_widget)
        layout.addWidget(rolagem, 1)
        self.resumo = texto("", "suave")
        layout.addWidget(self.resumo)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        barra = QHBoxLayout()
        barra.addStretch()
        fechar = QPushButton("Fechar (Esc)")
        fechar.setAutoDefault(False)
        fechar.clicked.connect(self.close)
        barra.addWidget(fechar)
        layout.addLayout(barra)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.atualizar)
        self.timer_campainhas = QTimer(self)
        self.timer_campainhas.setInterval(VERIFICAR_CAMPAINHAS_SEG * 1000)
        self.timer_campainhas.timeout.connect(self.verificar_campainhas)
        QShortcut(QKeySequence("F5"), self, activated=self.atualizar)
        self.atualizar()
        self.verificar_campainhas()
        self.timer.start()
        self.timer_campainhas.start()

    def exigir_acesso(self):
        if self.ctx.operador_id is None or self.ctx.operador_id != self._operador_id:
            raise ErroPermissao("A sessão mudou. Abra o painel novamente.")
        cadastro = self.ctx.cadastros.obter("operadores", self._operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.operador = self.ctx.acesso.operador(self._operador_id)
        if "util_quartos" in modulos_desligados(self.ctx.banco):
            raise ErroPermissao("O módulo Quartos está desligado.")
        self.ctx.acesso.exigir(self.ctx.operador, "util_quartos")

    def controlador(self) -> QuartosController:
        return self.ctx.quartos

    def executar(self, acao, quarto: int):
        try:
            self.exigir_acesso()
            acao()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
        else:
            self.mensagem.setText("")
            self._enviar(quarto, "parar")
            if quarto in self.cartoes:
                self.cartoes[quarto].zerar_avisos()
        self.atualizar()

    # ---- avisos ----
    def avisar(self, quarto: int, comando: str):
        """Aviso no caixa (som e janela na frente no tempo esgotado) e na campainha do quarto."""
        QApplication.beep()
        if comando == "tocar":
            if self.isMinimized():
                self.showNormal()
            self.raise_()
            self.activateWindow()
        self._enviar(quarto, comando)

    def _enviar(self, quarto: int, comando: str):
        endereco = self.controlador().campainhas().get(quarto)
        if endereco:
            campainha.enviar_em_segundo_plano(
                endereco, comando, lambda ok, q=quarto: self._ponte.resultado.emit(q, ok))

    def verificar_campainhas(self):
        for quarto in self.cartoes:
            self._enviar(quarto, "ping")

    def _resultado_campainha(self, quarto: int, ok: bool):
        self.campainha_ok[quarto] = ok
        cartao = self.cartoes.get(quarto)
        if cartao is not None:
            cartao.definir_campainha(True, ok)

    # ---- atualização ----
    def _montar(self, numeros: list[int]):
        if list(self.cartoes) == numeros:
            return
        for cartao in self.cartoes.values():
            cartao.setParent(None)
            cartao.deleteLater()
        self.cartoes = {}
        for i, n in enumerate(numeros):
            cartao = CartaoQuarto(n, self)
            self.cartoes[n] = cartao
            self.grade.addWidget(cartao, i // COLUNAS, i % COLUNAS)

    def atualizar(self):
        try:
            self.exigir_acesso()
            ctrl = self.controlador()
            situacao = ctrl.situacao()
            campainhas = ctrl.campainhas()
            resumo = ctrl.resumo_noite()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            if isinstance(erro, ErroPermissao):
                self.timer.stop()
                self.timer_campainhas.stop()
                for cartao in self.cartoes.values():
                    cartao.setEnabled(False)
            return
        self._montar([item["quarto"] for item in situacao])
        agora = fmt.agora_dt()
        for item in situacao:
            cartao = self.cartoes[item["quarto"]]
            cartao.mostrar(item, agora)
            cartao.definir_campainha(item["quarto"] in campainhas, self.campainha_ok.get(item["quarto"]))
        livres = sum(i["estado"] == "livre" for i in situacao)
        self.resumo.setText(
            f"Livres: {livres} de {len(situacao)}  ·  Noite: {resumo['usos']} entradas  ·  "
            f"{fmt_duracao(resumo['minutos']) if resumo['minutos'] else '0 min'}  ·  "
            f"{fmt.fmt_brl(resumo['valor_cent'])}  ·  {resumo['estouros']} passaram do tempo")
