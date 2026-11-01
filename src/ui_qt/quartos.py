"""Controle de quartos em Qt: painel completo (menu) e faixa compacta na tela do caixa.

Somente o QuartosController decide estados e grava; aqui só se mostra, avisa e chama o controlador. O cliente paga
antes no caixa; nada é lançado na comanda.

Os avisos (bipe, campainha do quarto e repetição a cada minuto) ficam em `AvisosQuartos`, um por banco: com o caixa e o
painel abertos ao mesmo tempo, a campainha não toca em dobro.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
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


# ------------------------------------------------------------------ avisos
class AvisosQuartos(QObject):
    """Decide quando bipar e acionar a campainha de cada uso; compartilhado por todas as telas do mesmo banco."""
    resultado = Signal(int, bool)          # quarto, campainha respondeu?

    def __init__(self):
        super().__init__()
        self._alertou: set[int] = set()
        self._ultimo_toque: dict[int, object] = {}
        self.campainha_ok: dict[int, bool] = {}
        self.resultado.connect(self._guardar)

    def _guardar(self, quarto: int, ok: bool):
        self.campainha_ok[quarto] = ok

    def enviar(self, ctrl: QuartosController, quarto: int, comando: str):
        endereco = ctrl.campainhas().get(quarto)
        if endereco:
            campainha.enviar_em_segundo_plano(
                endereco, comando, lambda ok, q=quarto: self.resultado.emit(q, ok))

    def verificar(self, ctrl: QuartosController, quartos):
        for quarto in quartos:
            self.enviar(ctrl, quarto, "ping")

    def processar(self, ctrl: QuartosController, situacao: list[dict], agora) -> list[int]:
        """Dispara os avisos devidos agora e devolve os quartos que tocaram (a tela que chamou vem para a frente)."""
        ativos = {i["uso_id"] for i in situacao if i["uso_id"]}
        self._alertou &= ativos
        for uso in list(self._ultimo_toque):
            if uso not in ativos:
                del self._ultimo_toque[uso]
        tocaram = []
        for item in situacao:
            uso = item["uso_id"]
            if item["estado"] == "alerta" and uso not in self._alertou:
                self._alertou.add(uso)
                QApplication.beep()
                self.enviar(ctrl, item["quarto"], "alerta")
            elif item["estado"] == "estourou":
                ultimo = self._ultimo_toque.get(uso)
                if ultimo is None or (agora - ultimo).total_seconds() >= REPETIR_TOQUE_SEG:
                    self._ultimo_toque[uso] = agora
                    QApplication.beep()
                    self.enviar(ctrl, item["quarto"], "tocar")
                    tocaram.append(item["quarto"])
        return tocaram

    def mudou(self, ctrl: QuartosController, quarto: int, uso_id: int | None):
        """Iniciou, ganhou tempo ou foi liberado: os avisos recomeçam e a campainha desliga."""
        self._alertou.discard(uso_id)
        self._ultimo_toque.pop(uso_id, None)
        self.enviar(ctrl, quarto, "parar")


def avisos_de(banco) -> AvisosQuartos:
    avisos = getattr(banco, "_avisos_quartos", None)
    if avisos is None:
        avisos = AvisosQuartos()
        banco._avisos_quartos = avisos
    return avisos


def modulo_disponivel(ctx) -> bool:
    return (ctx.operador is not None and "util_quartos" not in modulos_desligados(ctx.banco)
            and ctx.pode("util_quartos"))


# ------------------------------------------------------------- ações comuns
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


def pedir_iniciar(pai, ctrl: QuartosController, quarto: int):
    """Mostra a escolha do tempo; devolve a ação para executar ou None se desistiu."""
    dlg = DialogoTempo(ctrl, f"Iniciar quarto {quarto}", parent=pai)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        blocos = dlg.blocos.value()
        return lambda: ctrl.iniciar(quarto, blocos)
    return None


def pedir_mais_tempo(pai, ctrl: QuartosController, item: dict):
    maximo = MAX_BLOCOS - int(item.get("blocos") or 0)
    if maximo < 1:
        raise ErroNegocio(f"O quarto {item['quarto']} já está no tempo máximo.")
    dlg = DialogoTempo(ctrl, f"Adicionar tempo — quarto {item['quarto']}", maximo, parent=pai)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        blocos = dlg.blocos.value()
        return lambda: ctrl.adicionar_tempo(item["quarto"], blocos)
    return None


def pedir_liberar(pai, ctrl: QuartosController, quarto: int):
    resposta = QMessageBox.question(pai, "Liberar quarto", f"Liberar o quarto {quarto}?")
    if resposta == QMessageBox.StandardButton.Yes:
        return lambda: ctrl.liberar(quarto)
    return None


def _trazer_para_frente(janela: QWidget):
    if janela.isMinimized():
        janela.showNormal()
    janela.raise_()
    janela.activateWindow()


# ------------------------------------------------------------ painel grande
class CartaoQuarto(QFrame):
    def __init__(self, numero: int, painel: "JanelaQuartos"):
        super().__init__()
        self.numero = numero
        self.painel = painel
        self.item: dict = {"estado": "livre", "uso_id": None}
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

    def iniciar(self):
        self.painel.pedir(lambda ctrl: pedir_iniciar(self, ctrl, self.numero), self.numero)

    def mais_tempo(self):
        self.painel.pedir(lambda ctrl: pedir_mais_tempo(self, ctrl, self.item), self.numero)

    def liberar(self):
        self.painel.pedir(lambda ctrl: pedir_liberar(self, ctrl, self.numero), self.numero)

    def definir_campainha(self, tem: bool, ok: bool | None):
        if not tem:
            self.sino.setText("")
        elif ok is None:
            self.sino.setText("🔔 ?")
        else:
            self.sino.setText("🔔 ok" if ok else "🔕 off")
            self.sino.setToolTip("Campainha ligada" if ok else "Campainha fora do ar: confira o aparelho e o Wi-Fi")

    def _cor(self, chave: str):
        fundo, letra = CORES[chave]
        self.setStyleSheet(
            f"QFrame#cartao_quarto {{ background: {fundo}; border-radius: 10px; }}"
            f"QFrame#cartao_quarto QLabel {{ color: {letra}; background: transparent; }}")

    def mostrar(self, item: dict):
        self.item = item
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
        if estado == "estourou":
            self.piscar = not self.piscar
            self._cor("piscar" if self.piscar else "estourou")
            self.tempo.setText("+" + fmt_relogio(item["restante_seg"]))
        else:
            self._cor(estado)
            self.tempo.setText(fmt_relogio(item["restante_seg"]))


class JanelaQuartos(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._operador_id = ctx.operador_id
        self.exigir_acesso()
        self.avisos = avisos_de(ctx.banco)
        self.avisos.resultado.connect(self._resultado_campainha)
        self.setWindowTitle("Controle de Quartos • Qt")
        self.resize(1050, 620)
        self.cartoes: dict[int, CartaoQuarto] = {}
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

    def pedir(self, montar, quarto: int):
        """`montar(ctrl)` mostra a pergunta e devolve a ação (ou None se o operador desistiu)."""
        try:
            self.exigir_acesso()
            acao = montar(self.controlador())
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return
        if acao is not None:
            self.executar(acao, quarto)

    def executar(self, acao, quarto: int):
        try:
            self.exigir_acesso()
            acao()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
        else:
            self.mensagem.setText("")
            cartao = self.cartoes.get(quarto)
            self.avisos.mudou(self.controlador(), quarto, cartao.item.get("uso_id") if cartao else None)
        self.atualizar()

    def verificar_campainhas(self):
        self.avisos.verificar(self.controlador(), list(self.cartoes))

    def _resultado_campainha(self, quarto: int, ok: bool):
        cartao = self.cartoes.get(quarto)
        if cartao is not None:
            cartao.definir_campainha(True, ok)

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
        for item in situacao:
            cartao = self.cartoes[item["quarto"]]
            cartao.mostrar(item)
            cartao.definir_campainha(item["quarto"] in campainhas, self.avisos.campainha_ok.get(item["quarto"]))
        if self.avisos.processar(ctrl, situacao, fmt.agora_dt()):
            _trazer_para_frente(self)
        livres = sum(i["estado"] == "livre" for i in situacao)
        self.resumo.setText(
            f"Livres: {livres} de {len(situacao)}  ·  Noite: {resumo['usos']} entradas  ·  "
            f"{fmt_duracao(resumo['minutos']) if resumo['minutos'] else '0 min'}  ·  "
            f"{fmt.fmt_brl(resumo['valor_cent'])}  ·  {resumo['estouros']} passaram do tempo")


# ------------------------------------------------------- faixa no caixa
class ChipQuarto(QPushButton):
    """Botão compacto de um quarto na faixa do caixa: número e tempo na cor do estado."""

    def __init__(self, numero: int, faixa: "FaixaQuartos"):
        super().__init__()
        self.numero = numero
        self.faixa = faixa
        self.item: dict = {"estado": "livre", "uso_id": None}
        self.piscar = False
        self.setObjectName("chip_quarto")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)       # o foco fica no código do produto do caixa
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(104)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.clicked.connect(lambda: self.faixa.menu_do_quarto(self))

    def mostrar(self, item: dict):
        self.item = item
        estado = item["estado"]
        if estado == "livre":
            rotulo, cor = "livre", "livre"
            self.setToolTip(f"Quarto {self.numero}: livre. Clique para iniciar.")
        elif estado == "estourou":
            self.piscar = not self.piscar
            rotulo, cor = "+" + fmt_relogio(item["restante_seg"]), "piscar" if self.piscar else "estourou"
            self.setToolTip(f"Quarto {self.numero}: tempo esgotado (saída prevista {item['fim']:%H:%M}).")
        else:
            rotulo, cor = fmt_relogio(item["restante_seg"]), estado
            self.setToolTip(f"Quarto {self.numero}: {fmt_duracao(item['minutos'])}, sai às {item['fim']:%H:%M}.")
        self.setText(f"{self.numero}  ·  {rotulo}")
        if estado == "livre":       # livre fica discreto (só o contorno): o olho vai para o que está correndo
            fundo, letra, borda, peso = "transparent", "#8b95a7", "1px solid #3b4558", "600"
        else:
            fundo, letra = CORES[cor]
            borda, peso = "none", "800"
        self.setStyleSheet(
            f"QPushButton#chip_quarto {{ background: {fundo}; color: {letra}; border: {borda}; border-radius: 8px;"
            f" padding: 2px 8px; font-size: 15px; font-weight: {peso}; }}"
            f"QPushButton#chip_quarto:hover {{ border: 2px solid #ffffff55; }}")


class FaixaQuartos(QFrame):
    """Faixa fina no alto da tela de venda do caixa. Some sozinha com o módulo desligado ou sem permissão."""

    def __init__(self, ctx, janela: QWidget | None = None):
        super().__init__()
        self.ctx = ctx
        self.janela = janela
        self.avisos = avisos_de(ctx.banco)
        self.chips: dict[int, ChipQuarto] = {}
        self.setObjectName("faixa_quartos")
        self.setStyleSheet("QFrame#faixa_quartos { background: transparent; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 2, 10, 2)
        lay.setSpacing(6)
        self.titulo = QLabel("QUARTOS")
        self.titulo.setObjectName("mudo")
        self.titulo.setStyleSheet("font-weight: 700; letter-spacing: 1px;")
        lay.addWidget(self.titulo)
        self.linha = QHBoxLayout()
        self.linha.setSpacing(6)
        lay.addLayout(self.linha, 1)
        self.resumo = QLabel("")
        self.resumo.setObjectName("mudo")
        lay.addWidget(self.resumo)
        self.btn_painel = QPushButton("Painel")
        self.btn_painel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_painel.setFixedHeight(34)
        self.btn_painel.setToolTip("Abrir o painel completo dos quartos")
        self.btn_painel.clicked.connect(self.abrir_painel)
        lay.addWidget(self.btn_painel)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.atualizar)
        self.timer_campainhas = QTimer(self)
        self.timer_campainhas.setInterval(VERIFICAR_CAMPAINHAS_SEG * 1000)
        self.timer_campainhas.timeout.connect(lambda: self.avisos.verificar(self.ctx.quartos, list(self.chips)))
        self.atualizar()
        self.timer.start()
        self.timer_campainhas.start()

    def _montar(self, numeros: list[int]):
        if list(self.chips) == numeros:
            return
        for chip in self.chips.values():
            chip.setParent(None)
            chip.deleteLater()
        self.chips = {}
        for n in numeros:
            chip = ChipQuarto(n, self)
            self.chips[n] = chip
            self.linha.addWidget(chip)

    def atualizar(self):
        try:
            if not modulo_disponivel(self.ctx):
                self.setVisible(False)
                return
            ctrl = self.ctx.quartos
            situacao = ctrl.situacao()
        except ErroNegocio:
            self.setVisible(False)
            return
        self.setVisible(True)
        self._montar([i["quarto"] for i in situacao])
        for item in situacao:
            self.chips[item["quarto"]].mostrar(item)
        livres = sum(i["estado"] == "livre" for i in situacao)
        self.resumo.setText(f"{livres} livre{'s' if livres != 1 else ''}")
        if self.avisos.processar(ctrl, situacao, fmt.agora_dt()) and self.janela is not None:
            _trazer_para_frente(self.janela)

    def menu_do_quarto(self, chip: ChipQuarto):
        menu = QMenu(self)
        if chip.item["estado"] == "livre":
            acoes = [("Iniciar tempo…", lambda c: pedir_iniciar(self, c, chip.numero))]
        else:
            acoes = [("+ Tempo…", lambda c: pedir_mais_tempo(self, c, chip.item)),
                     ("Liberar quarto", lambda c: pedir_liberar(self, c, chip.numero))]
        for rotulo, montar in acoes:
            menu.addAction(rotulo, lambda m=montar: self.pedir(m, chip))
        menu.addSeparator()
        menu.addAction("Abrir painel dos quartos", self.abrir_painel)
        menu.popup(chip.mapToGlobal(chip.rect().bottomLeft()))
        self._menu = menu                                    # testes acessam o último menu aberto

    def pedir(self, montar, chip: ChipQuarto):
        try:
            if not modulo_disponivel(self.ctx):
                raise ErroPermissao("O módulo Quartos está desligado ou o seu nível não permite.")
            ctrl = self.ctx.quartos
            acao = montar(ctrl)
            if acao is None:
                return
            acao()
        except ErroNegocio as erro:
            self._avisar_erro(str(erro))
        else:
            self.avisos.mudou(ctrl, chip.numero, chip.item.get("uso_id"))
        self.atualizar()

    def _avisar_erro(self, texto_erro: str):
        status = getattr(self.janela, "lbl_status", None)
        if isinstance(status, QLabel):
            status.setText(texto_erro)
        else:
            QMessageBox.warning(self, "Quartos", texto_erro)

    def abrir_painel(self):
        try:
            janela = JanelaQuartos(self.ctx, self.janela)
        except ErroNegocio as erro:
            self._avisar_erro(str(erro))
            return
        janela.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        janela.show()
        self._painel = janela
