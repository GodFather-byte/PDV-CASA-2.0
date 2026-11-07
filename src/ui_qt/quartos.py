"""Controle de quartos em Qt: painel completo (menu) e linha de cartões no caixa.

Somente o QuartosController decide estados e grava; aqui só se mostra, avisa e chama o controlador. O cliente paga
antes no caixa; nada é lançado na comanda.

No caixa, os quartos aparecem numa linha de cartões embaixo dos produtos e do pagamento (`PainelQuartosCaixa`).

Os avisos (bipe, campainha do quarto e repetição a cada minuto) ficam em `AvisosQuartos`, um por banco: com o caixa e o
painel abertos ao mesmo tempo, a campainha não toca em dobro.
"""
from __future__ import annotations

import math
import threading

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
    QLabel, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QLineEdit,
    QTableWidget, QTableWidgetItem,
)

from src.controllers.config_controller import modulos_desligados
from src.controllers.quartos_controller import MAX_BLOCOS, QuartosController, fmt_duracao, fmt_relogio
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.hardware import campainha
from src.ui_qt.painel_mesas import CORES as CORES_MESAS, ESTADOS as ESTADOS_MESAS, _fonte
from src.ui_qt.tema import texto, ajustar_janela

REPETIR_TOQUE_SEG = 60      # tempo esgotado: toca de novo a cada minuto até liberar
VERIFICAR_CAMPAINHAS_SEG = 30
COLUNAS = 4

# estado -> (fundo, texto)
CORES = {
    "livre": ("#1e7d32", "#ffffff"),        # verde: disponível
    "uso": ("#1e4fa3", "#ffffff"),          # azul: ocupado (como a comanda aberta)
    "alerta": ("#f9a825", "#000000"),
    "estourou": ("#c62828", "#ffffff"),
    "piscar": ("#ff8a80", "#000000"),
    "arrumacao": ("#5e35b1", "#ffffff"),    # roxo: em arrumação, não inicia
}


# ------------------------------------------------------------------ avisos
# Som no caixa (no Windows, bipes pelo alto-falante do PC; fora dele, o bipe do sistema). Tons diferentes para
# "faltam 5 minutos" e "tempo esgotado", para o operador reconhecer sem olhar.
SONS = {"alerta": ((880, 250), (880, 250)), "estourou": ((1200, 300), (900, 300), (1200, 300))}


def tocar_som(tipo: str) -> None:
    try:
        import winsound
    except ImportError:
        QApplication.beep()
        return

    def tocar():
        for frequencia, duracao in SONS[tipo]:
            winsound.Beep(frequencia, duracao)

    threading.Thread(target=tocar, name="som-quarto", daemon=True).start()


class AvisosQuartos(QObject):
    """Decide quando avisar (tela, som no caixa e campainha) em cada uso; um por banco, compartilhado pelas telas."""
    resultado = Signal(int, bool)          # quarto, campainha respondeu?
    aviso = Signal(int, str, str)          # quarto, tipo ('alerta' | 'estourou'), texto para a tela
    resolvido = Signal(int)                # quarto iniciado, com mais tempo ou liberado: o aviso some

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
                minutos = max(1, math.ceil(item["restante_seg"] / 60))
                tocar_som("alerta")
                self.aviso.emit(item["quarto"], "alerta",
                                f"QUARTO {item['quarto']}  —  falta{'m' if minutos > 1 else ''} {minutos} "
                                f"minuto{'s' if minutos > 1 else ''} (sai às {item['fim']:%H:%M})")
                self.enviar(ctrl, item["quarto"], "alerta")
            elif item["estado"] == "estourou":
                ultimo = self._ultimo_toque.get(uso)
                if ultimo is None or (agora - ultimo).total_seconds() >= REPETIR_TOQUE_SEG:
                    self._ultimo_toque[uso] = agora
                    tocar_som("estourou")
                    self.aviso.emit(item["quarto"], "estourou",
                                    f"QUARTO {item['quarto']}  —  TEMPO ESGOTADO "
                                    f"(passou {fmt_relogio(item['restante_seg'])})")
                    self.enviar(ctrl, item["quarto"], "tocar")
                    tocaram.append(item["quarto"])
        return tocaram

    def mudou(self, ctrl: QuartosController, quarto: int, uso_id: int | None):
        """Iniciou, ganhou tempo ou foi liberado: os avisos recomeçam e a campainha desliga."""
        self._alertou.discard(uso_id)
        self._ultimo_toque.pop(uso_id, None)
        self.resolvido.emit(quarto)
        self.enviar(ctrl, quarto, "parar")


def avisos_de(banco) -> AvisosQuartos:
    avisos = getattr(banco, "_avisos_quartos", None)
    if avisos is None:
        avisos = AvisosQuartos()
        banco._avisos_quartos = avisos
    return avisos


class AvisoNaTela(QFrame):
    """Aviso grande sobreposto no alto da janela (não é modal: o caixa continua funcionando). Uma linha por quarto;
    some quando o operador clica em OK ou quando o quarto ganha tempo ou é liberado."""
    LARGURA = 600
    ESTILO = {"alerta": ("#f9a825", "#1a1200"), "estourou": ("#c62828", "#ffffff")}

    def __init__(self, janela: QWidget, avisos: AvisosQuartos):
        super().__init__(janela)
        self.janela = janela
        self.linhas: dict[int, tuple[str, str]] = {}
        self.setObjectName("aviso_quartos")
        self.setFixedWidth(self.LARGURA)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 10, 10)
        self.texto = QLabel("")
        self.texto.setWordWrap(True)
        lay.addWidget(self.texto, 1)
        self.ok = QPushButton("OK")
        self.ok.setFocusPolicy(Qt.FocusPolicy.NoFocus)     # não rouba o Enter do caixa
        self.ok.setFixedWidth(70)
        self.ok.clicked.connect(self.dispensar)
        lay.addWidget(self.ok)
        self.hide()
        avisos.aviso.connect(self.mostrar)
        avisos.resolvido.connect(self.remover)
        janela.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self.janela and ev.type() == ev.Type.Resize and self.isVisible():
            self._posicionar()
        return False

    def _posicionar(self):
        self.adjustSize()
        self.move(max(0, (self.janela.width() - self.width()) // 2), 64)
        self.raise_()

    def mostrar(self, quarto: int, tipo: str, texto: str):
        self.linhas[quarto] = (tipo, texto)
        self._desenhar()

    def remover(self, quarto: int):
        if self.linhas.pop(quarto, None) is not None:
            self._desenhar()

    def dispensar(self):
        self.linhas.clear()
        self._desenhar()

    def _desenhar(self):
        if not self.linhas:
            self.hide()
            return
        grave = any(tipo == "estourou" for tipo, _ in self.linhas.values())
        fundo, letra = self.ESTILO["estourou" if grave else "alerta"]
        self.setStyleSheet(
            f"QFrame#aviso_quartos {{ background: {fundo}; border: 2px solid #ffffff66; border-radius: 12px; }}"
            f"QFrame#aviso_quartos QLabel {{ color: {letra}; background: transparent; font-size: 20px; font-weight: 800; }}"
            f"QFrame#aviso_quartos QPushButton {{ font-size: 16px; font-weight: 700; padding: 6px; }}")
        self.texto.setText("\n".join(texto for _, texto in sorted(self.linhas.values(), key=lambda l: l[0] != "estourou")))
        self.show()
        self._posicionar()


def modulo_disponivel(ctx) -> bool:
    return (ctx.operador is not None and "util_quartos" not in modulos_desligados(ctx.banco)
            and ctx.pode("util_quartos"))


# ------------------------------------------------------------- ações comuns
class DialogoTempo(QDialog):
    """Escolha do tempo em blocos (1 bloco = 30 min por padrão), com atalhos e o valor informativo."""

    def __init__(self, ctrl: QuartosController, titulo: str, maximo: int = MAX_BLOCOS, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.iniciando = titulo.startswith('Iniciar')
        self.setWindowTitle(titulo)
        form = QFormLayout(self)
        minutos = ctrl.config()["minutos_bloco"]
        self.profissional = QLineEdit()
        self.profissional.setPlaceholderText('Ex.: 167')
        if titulo.startswith('Iniciar'):
            form.addRow('Código profissional:', self.profissional)
            self.nome_profissional = QLabel('Digite a comanda da profissional')
            form.addRow('Nome:', self.nome_profissional)
            self.profissional.textChanged.connect(self._atualizar_profissional)
            self.profissional.setFocus()
        self.tempo = QComboBox()
        self.tempo.setPlaceholderText("Escolha o tempo do quarto")
        for blocos in range(1, max(1, maximo) + 1):
            self.tempo.addItem(fmt_duracao(blocos * minutos), blocos)
        # Iniciar exige uma escolha explícita: Enter não lança meia hora por padrão.
        self.tempo.setCurrentIndex(-1 if titulo.startswith('Iniciar') else 0)
        form.addRow("Tempo:", self.tempo)
        self.resumo = QLabel()
        self.resumo.setStyleSheet("font-size: 20px; font-weight: bold;")
        form.addRow(self.resumo)
        self.mensagem = QLabel()
        self.mensagem.setWordWrap(True)
        form.addRow(self.mensagem)
        atalhos = QHBoxLayout()
        for b in (1, 2, 3, 4, 6):
            if b <= maximo:
                botao = QPushButton(fmt_duracao(b * minutos))
                botao.setAutoDefault(False)
                botao.clicked.connect(lambda _=False, v=b: self.tempo.setCurrentIndex(v - 1))
                atalhos.addWidget(botao)
        form.addRow(atalhos)
        self.botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botoes.button(QDialogButtonBox.StandardButton.Ok).setText("Confirmar tempo")
        self.botoes.accepted.connect(self.accept)
        self.botoes.rejected.connect(self.reject)
        form.addRow(self.botoes)
        self.tempo.currentIndexChanged.connect(self._atualizar)
        self._atualizar()

    def accept(self):
        codigo = self.profissional.text().strip()
        if self.iniciando and (not codigo.isdigit() or not self.ctrl.nome_profissional(codigo)):
            self.mensagem.setText("Informe o código da profissional cadastrada para vincular os shows à comanda dela.")
            self.profissional.setFocus()
            return
        if self.tempo.currentData() is not None:
            super().accept()

    def _atualizar_profissional(self):
        codigo = self.profissional.text().strip()
        nome = self.ctrl.nome_profissional(codigo) if codigo.isdigit() else None
        self.nome_profissional.setText(nome or 'Não cadastrada em Comissões')

    def _atualizar(self):
        blocos = self.tempo.currentData()
        self.botoes.button(QDialogButtonBox.StandardButton.Ok).setEnabled(blocos is not None)
        self.resumo.setText(
            f"Tempo escolhido: {fmt_duracao(blocos * self.ctrl.config()['minutos_bloco'])}"
            if blocos is not None else "Escolha o tempo e depois confirme.")
        if blocos is not None:
            shows = blocos * self.ctrl.config()['minutos_bloco'] // 30
            self.resumo.setText(self.resumo.text() + f" · {shows} show(s) de 30 minutos")


def pedir_iniciar(pai, ctrl: QuartosController, quarto: int):
    """Mostra a escolha do tempo; devolve a ação para executar ou None se desistiu."""
    dlg = DialogoTempo(ctrl, f"Iniciar quarto {quarto}", parent=pai)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        blocos = dlg.tempo.currentData()
        return lambda: ctrl.iniciar(quarto, blocos, codigo_profissional=dlg.profissional.text())
    return None


def pedir_mais_tempo(pai, ctrl: QuartosController, item: dict):
    maximo = MAX_BLOCOS - int(item.get("blocos") or 0)
    if maximo < 1:
        raise ErroNegocio(f"O quarto {item['quarto']} já está no tempo máximo.")
    dlg = DialogoTempo(ctrl, f"Adicionar tempo — quarto {item['quarto']}", maximo, parent=pai)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        blocos = dlg.tempo.currentData()
        return lambda: ctrl.adicionar_tempo(item["quarto"], blocos)
    return None


ROTULO_ESTADO = {"livre": "LIVRE", "uso": "OCUPADO", "alerta": "ACABANDO", "estourou": "ESGOTADO",
                 "arrumacao": "EM ARRUMAÇÃO"}


def contagem_quartos(situacao: list[dict]) -> dict:
    """Quantos quartos em cada situação e quais estão livres, para ver de longe o que tem para usar."""
    c = {e: 0 for e in ROTULO_ESTADO}
    for item in situacao:
        c[item["estado"]] = c.get(item["estado"], 0) + 1
    c["livres"] = [i["quarto"] for i in situacao if i["estado"] == "livre"]
    c["ocupados"] = c["uso"] + c["alerta"] + c["estourou"]
    return c


def texto_contagem(c: dict) -> str:
    """'LIVRES: 2, 5, 7  ·  OCUPADOS: 4 (1 acabando, 1 esgotado)  ·  ARRUMANDO: 1'."""
    partes = ["LIVRES: " + (", ".join(map(str, c["livres"])) if c["livres"] else "nenhum")]
    detalhe = [f"{c['alerta']} acabando"] * bool(c["alerta"]) + [f"{c['estourou']} esgotado(s)"] * bool(c["estourou"])
    partes.append(f"OCUPADOS: {c['ocupados']}" + (f" ({', '.join(detalhe)})" if detalhe else ""))
    if c["arrumacao"]:
        partes.append(f"ARRUMANDO: {c['arrumacao']}")
    return "  ·  ".join(partes)


def fracao_usada(item: dict) -> float:
    """Quanto do tempo pago já passou (0 a 1); esgotado = 1."""
    total = (item.get("minutos") or 0) * 60
    if not total:
        return 0.0
    return max(0.0, min(1.0, 1 - item.get("restante_seg", 0) / total))


def escolher_liberacao(pai, quarto: int) -> str | None:
    """'liberar', 'arrumar' (libera e deixa em arrumação) ou None (desistiu)."""
    caixa = QMessageBox(QMessageBox.Icon.Question, "Liberar quarto", f"Liberar o quarto {quarto}?",
                        QMessageBox.StandardButton.NoButton, pai)
    liberar = caixa.addButton("Liberar", QMessageBox.ButtonRole.AcceptRole)
    arrumar = caixa.addButton("Liberar e pôr em arrumação", QMessageBox.ButtonRole.AcceptRole)
    cancelar = caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
    caixa.setDefaultButton(liberar)
    caixa.setEscapeButton(cancelar)
    caixa.exec()
    return {liberar: "liberar", arrumar: "arrumar"}.get(caixa.clickedButton())


def texto_excedido(r: dict) -> str:
    """Depois de liberar: quanto passou do tempo e quantos blocos cobrar ('' se saiu no tempo ou na tolerância)."""
    if not r.get("blocos_a_mais"):
        return ""
    quem = f"{r['nome_profissional']} ({r['codigo_profissional']})" if r.get("nome_profissional") else "o cliente"
    return (f"Quarto {r['quarto']}: passou {fmt_relogio(r['excedeu_seg'])} do tempo.\n"
            f"Cobre {r['blocos_a_mais']} bloco(s) a mais de {quem}.")


def pedir_liberar(pai, ctrl: QuartosController, quarto: int):
    escolha = escolher_liberacao(pai, quarto)
    if escolha is None:
        return None

    def acao():
        resultado = ctrl.liberar(quarto, arrumar=escolha == "arrumar")
        aviso = texto_excedido(resultado)
        if aviso:
            QMessageBox.information(pai, "Tempo excedido", aviso)
        if escolha != "arrumar":
            oferecer_fila(pai, ctrl, quarto)
        return resultado
    return acao


def pedir_trocar(pai, ctrl: QuartosController, quarto: int):
    """Passa quem está no quarto para outro livre (mesmo tempo, horário e shows)."""
    livres = ctrl.quartos_livres()
    if not livres:
        raise ErroNegocio("Nenhum quarto livre para trocar.")
    escolha, ok = QInputDialog.getItem(pai, f"Trocar o quarto {quarto}", "Passar para o quarto:",
                                       [str(n) for n in livres], 0, False)
    if not ok:
        return None
    return lambda: ctrl.trocar_quarto(quarto, int(escolha))


def pedir_arrumacao(pai, ctrl: QuartosController, quarto: int, arrumando: bool):
    return lambda: ctrl.marcar_arrumacao(quarto, arrumando)


class DialogoGarotasNoite(QDialog):
    """Garotas da noite: entradas, tempo, shows e tempo passado (para conferir o acerto e cobrar o excedido)."""

    def __init__(self, ctrl: QuartosController, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Garotas da noite")
        self.resize(720, 460)
        lay = QVBoxLayout(self)
        linhas = ctrl.garotas_da_noite()
        self.tabela = QTableWidget(len(linhas), 6)
        self.tabela.setHorizontalHeaderLabels(["Código", "Garota", "Entradas", "Tempo", "Shows", "Passou do tempo"])
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for i, r in enumerate(linhas):
            valores = [r["codigo"], r["nome"] + ("  (no quarto)" if r["no_quarto"] else ""), r["entradas"], r["tempo"],
                       r["shows"], fmt_relogio(r["excedeu_seg"]) if r["excedeu_seg"] else "—"]
            for j, v in enumerate(valores):
                self.tabela.setItem(i, j, QTableWidgetItem(str(v)))
        self.tabela.resizeColumnsToContents()
        lay.addWidget(self.tabela)
        total = sum(r["shows"] or 0 for r in linhas)
        lay.addWidget(QLabel(f"{len(linhas)} garota(s) · {total} show(s) na noite" if linhas
                             else "Nenhuma garota entrou no quarto nesta noite."))
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        lay.addWidget(fechar)


def oferecer_fila(pai, ctrl: QuartosController, quarto: int) -> bool:
    """Quarto liberado e alguém já pagou esperando quarto: oferece começar ali (o primeiro da fila)."""
    fila = ctrl.fila()
    if not fila:
        return False
    vez = fila[0]
    resposta = QMessageBox.question(
        pai, "Quarto livre",
        f"O quarto {quarto} ficou livre. Iniciar agora para {vez['nome'] or 'a garota'} ({vez['garota']}) — "
        f"{vez['duracao']} já pago?" + (f"\n(Mais {len(fila) - 1} na fila.)" if len(fila) > 1 else ""))
    if resposta != QMessageBox.StandardButton.Yes:
        return False
    ctrl.iniciar_da_fila(vez["id"], quarto)
    return True


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
        self.etiqueta = QLabel("LIVRE")
        self.etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.etiqueta.setStyleSheet("font-size: 13px; font-weight: 900; letter-spacing: 2px;")
        lay.addWidget(self.etiqueta)
        self.tempo = QLabel("LIVRE")
        self.tempo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tempo.setStyleSheet("font-size: 34px; font-weight: bold;")
        lay.addWidget(self.tempo)
        self.info = QLabel("")
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.barra = QProgressBar()
        self.barra.setRange(0, 100)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(8)
        self.barra.setToolTip("Quanto do tempo pago já passou")
        lay.addWidget(self.barra)
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
        self.b_extra = QPushButton("Arrumação")
        self.b_extra.setMinimumHeight(30)
        self.b_extra.setStyleSheet("padding: 2px;")
        self.b_extra.setAutoDefault(False)
        self.b_extra.clicked.connect(self.extra)
        lay.addWidget(self.b_extra)

    def extra(self):
        """Livre: pôr em arrumação · em arrumação: quarto pronto · ocupado: trocar de quarto."""
        estado = self.item.get("estado", "livre")
        if estado == "livre":
            self.painel.pedir(lambda ctrl: pedir_arrumacao(self, ctrl, self.numero, True), self.numero)
        elif estado == "arrumacao":
            self.painel.pedir(lambda ctrl: pedir_arrumacao(self, ctrl, self.numero, False), self.numero)
        else:
            self.painel.pedir(lambda ctrl: pedir_trocar(self, ctrl, self.numero), self.numero)

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
        arrumando = estado == "arrumacao"
        self.b_iniciar.setEnabled(livre)
        self.b_mais.setEnabled(not livre and not arrumando)
        self.b_liberar.setEnabled(not livre and not arrumando)
        self.b_extra.setText("Pôr em arrumação" if livre else "Quarto pronto" if arrumando else "Trocar de quarto")
        self.etiqueta.setText(ROTULO_ESTADO.get(estado, estado.upper()))
        self.etiqueta.setVisible(not livre and not arrumando)    # livre/arrumando: o letreiro grande já diz
        self.barra.setVisible(not livre and not arrumando)
        if not livre and not arrumando:
            self.barra.setValue(int(round(fracao_usada(item) * 100)))
        if livre or arrumando:
            self._cor(estado)
            self.tempo.setText("LIVRE" if livre else "ARRUMANDO")
            self.info.setText("" if livre else "Clique em Quarto pronto quando terminar")
            return
        self.info.setText(
            f"{item.get('nome_profissional') or 'Profissional não identificada'} · {item.get('codigo_profissional') or '—'}\n"
            f"{fmt_duracao(item['minutos'])}\n"
            f"Entrou {item['inicio']:%H:%M} · Sai {item['fim']:%H:%M}")
        if estado == "estourou":
            self.piscar = not self.piscar
            self._cor("piscar" if self.piscar else "estourou")
            self.tempo.setText("+" + fmt_relogio(item["restante_seg"]))
        else:
            self._cor(estado)
            self.tempo.setText(fmt_relogio(item["restante_seg"]))


class DialogoHistoricoQuartos(QDialog):
    """Histórico por quarto ou comanda, sem valores financeiros."""
    def __init__(self, ctrl: QuartosController, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWindowTitle("Histórico de quartos")
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        filtros = QHBoxLayout()
        self.codigo = QLineEdit()
        self.codigo.setPlaceholderText("Buscar código da profissional")
        filtros.addWidget(self.codigo)
        botao = QPushButton("Buscar")
        botao.clicked.connect(self.atualizar)
        filtros.addWidget(botao)
        lay.addLayout(filtros)
        self.tabela = QTableWidget(0, 6)
        self.tabela.setHorizontalHeaderLabels(
            ["Quarto", "Código", "Profissional", "Entrada", "Saída", "Operador"])
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.tabela)
        self.atualizar()

    def atualizar(self):
        try:
            registros = self.ctrl.historico(codigo=self.codigo.text().strip() or None)
        except ErroNegocio as erro:
            QMessageBox.warning(self, "Histórico", str(erro))
            return
        self.tabela.setRowCount(len(registros))
        for linha, r in enumerate(registros):
            valores = [r["quarto"], r["codigo_profissional"] or "—",
                       r["nome_profissional"] or "—", r["inicio"],
                       r["liberado_em"] or "Em uso", r["operador_id"] or "—"]
            for coluna, valor in enumerate(valores):
                self.tabela.setItem(linha, coluna, QTableWidgetItem(str(valor)))
        self.tabela.resizeColumnsToContents()


class JanelaQuartos(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._operador_id = ctx.operador_id
        self.exigir_acesso()
        self.avisos = avisos_de(ctx.banco)
        self.avisos.resultado.connect(self._resultado_campainha)
        self.aviso_tela = AvisoNaTela(self, self.avisos)
        self.setWindowTitle("Controle de Quartos • Qt")
        self.resize(1050, 620)
        self._pagina = 0
        self._pagina_mostrada = None
        self.cartoes: dict[int, CartaoQuarto] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Controle de Quartos", "titulo"))
        layout.addWidget(texto(
            "Verde: livre · Azul: ocupado · Amarelo: acabando · Vermelho: tempo esgotado (o caixa e a campainha avisam "
            "até liberar) · Roxo: em arrumação.", "suave"))
        self.faixa = QLabel("")
        self.faixa.setObjectName("faixa_quartos")
        self.faixa.setWordWrap(True)
        self.faixa.setStyleSheet("font-size: 20px; font-weight: bold; padding: 8px 12px; border-radius: 8px;"
                                 "background: #1e7d32; color: #ffffff;")
        layout.addWidget(self.faixa)
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
        self.anterior = QPushButton("◀ Quartos anteriores")
        self.proxima = QPushButton("Próximos quartos ▶")
        self.anterior.clicked.connect(lambda: self.mudar_pagina(-1))
        self.proxima.clicked.connect(lambda: self.mudar_pagina(1))
        barra.addWidget(self.anterior)
        barra.addWidget(self.proxima)
        historico = QPushButton("Histórico de quartos")
        historico.clicked.connect(self.abrir_historico)
        barra.addWidget(historico)
        garotas = QPushButton("Garotas da noite")
        garotas.clicked.connect(self.abrir_garotas)
        barra.addWidget(garotas)
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

    def abrir_garotas(self):
        self.exigir_acesso()
        DialogoGarotasNoite(self.controlador(), self).exec()

    def abrir_historico(self):
        self.exigir_acesso()
        DialogoHistoricoQuartos(self.controlador(), self).exec()

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
            self._dispor_cartoes()
            return
        for cartao in self.cartoes.values():
            cartao.setParent(None)
            cartao.deleteLater()
        self.cartoes = {}
        self._pagina_mostrada = None
        for i, n in enumerate(numeros):
            cartao = CartaoQuarto(n, self)
            cartao.setParent(self.grade_widget)
            self.cartoes[n] = cartao
        self._dispor_cartoes()

    def mudar_pagina(self, passo):
        self._pagina = max(0, min(self._pagina + passo, (len(self.cartoes) - 1) // 8))
        self._dispor_cartoes()

    def _dispor_cartoes(self):
        self._pagina = min(self._pagina, max(0, (len(self.cartoes) - 1) // 8))
        if self._pagina_mostrada == self._pagina:
            return
        self._pagina_mostrada = self._pagina
        for i, cartao in enumerate(self.cartoes.values()):
            self.grade.removeWidget(cartao)
            visivel = self._pagina * 8 <= i < (self._pagina + 1) * 8
            cartao.setVisible(visivel)
            if visivel:
                self.grade.addWidget(cartao, (i % 8) // COLUNAS, i % COLUNAS)
        self.anterior.setVisible(len(self.cartoes) > 8)
        self.proxima.setVisible(len(self.cartoes) > 8)
        self.anterior.setEnabled(self._pagina > 0)
        self.proxima.setEnabled((self._pagina + 1) * 8 < len(self.cartoes))

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
        c = contagem_quartos(situacao)
        self.faixa.setText(texto_contagem(c))
        fundo = CORES["livre"][0] if c["livres"] else CORES["estourou"][0]   # vermelho: nenhum quarto livre
        self.faixa.setStyleSheet("font-size: 20px; font-weight: bold; padding: 8px 12px; border-radius: 8px;"
                                 f"background: {fundo}; color: #ffffff;")
        self.resumo.setText(
            f"Livres: {livres} de {len(situacao)}  ·  Noite: {resumo['usos']} entradas  ·  "
            f"{fmt_duracao(resumo['minutos']) if resumo['minutos'] else '0 min'}  ·  "
            f"{resumo['estouros']} passaram do tempo")


# ------------------------------------------------- quartos no caixa
# Cartões no mesmo desenho dos das comandas (painel_mesas.py): mesmas cores por situação, cantos, pílula e fontes.
_ESTADO_CARTAO = {"livre": "balcao", "uso": "consumindo", "alerta": "conta", "estourou": "parada",
                  "arrumacao": "parcial"}   # livre verde, ocupado azul
_PILULA = {"livre": "Livre", "uso": "Em uso", "alerta": "Acabando", "estourou": "Esgotado", "arrumacao": "Arrumando"}


class GradeQuartos(QWidget):
    """Grade de cartões compactos dos quartos; o clique devolve o número do quarto."""
    clicado = Signal(int)
    ALTURA = 90
    POR_PAGINA = 8
    MIN_COLUNAS, MAX_COLUNAS = 2, 4          # cartões maiores em até quatro colunas

    def __init__(self, parent=None):
        super().__init__(parent)
        self.itens: list[dict] = []
        self.colunas = self.MIN_COLUNAS
        self.pagina = 0
        self.modo = "escuro"
        self.piscar = False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)       # o teclado continua no caixa
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def definir(self, itens: list[dict], modo: str) -> None:
        self.itens = itens
        self.modo = modo
        self.piscar = not self.piscar
        self.colunas = max(self.MIN_COLUNAS, min(self.MAX_COLUNAS, len(itens)))
        self.pagina = min(self.pagina, max(0, (len(itens) - 1) // self.POR_PAGINA))
        linhas = max(1, math.ceil(min(len(itens), self.POR_PAGINA) / self.colunas))
        self.setFixedHeight(linhas * self.ALTURA)
        self.update()

    def celula(self, i: int) -> tuple[float, float, float, float]:
        i %= self.POR_PAGINA
        largura = self.width() / self.colunas
        return (i % self.colunas) * largura, (i // self.colunas) * self.ALTURA, largura, self.ALTURA

    def indice_em(self, pos) -> int | None:
        for i in range(self.pagina * self.POR_PAGINA, min((self.pagina + 1) * self.POR_PAGINA, len(self.itens))):
            x, y, w, h = self.celula(i)
            if x <= pos.x() < x + w and y <= pos.y() < y + h:
                return i
        return None

    def mousePressEvent(self, ev) -> None:
        i = self.indice_em(ev.position() if hasattr(ev, "position") else ev.pos())
        if i is not None:
            self.clicado.emit(self.itens[i]["quarto"])

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cores = CORES_MESAS[self.modo]
        for i in range(self.pagina * self.POR_PAGINA, min((self.pagina + 1) * self.POR_PAGINA, len(self.itens))):
            item = self.itens[i]
            x, y, w, h = self.celula(i)
            x1, y1, x2, y2 = x + 3, y + 3, x + w - 3, y + h - 3
            estado = item["estado"]
            e = ESTADOS_MESAS[self.modo][_ESTADO_CARTAO[estado]]
            fundo, borda, cor_pilula = e["fundo"], e["borda"], e["texto"]
            largura = 1
            if estado == "estourou" and self.piscar:          # pisca a borda: chama o olho sem poluir
                borda, largura = cores["vermelho"], 3
            elif estado == "livre":                            # livre salta aos olhos: borda verde grossa
                largura = 3
            p.setPen(QPen(QColor(borda), largura))
            p.setBrush(QColor(fundo))
            p.drawRoundedRect(QRectF(x1, y1, x2 - x1, y2 - y1), 12, 12)
            pad = 9
            if estado in ("uso", "alerta", "estourou"):       # barra do tempo já usado, na base do cartão
                usado = fracao_usada(item)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(borda))
                p.drawRoundedRect(QRectF(x1 + pad, y2 - 5, (x2 - x1 - 2 * pad) * usado, 3), 1.5, 1.5)
            fm_rotulo = QFontMetrics(_fonte(7, True))
            p.setFont(_fonte(7, True))
            p.setPen(QColor(cores["suave"]))
            p.drawText(QPointF(x1 + pad, y1 + 4 + fm_rotulo.ascent()), "QUARTO")
            p.setFont(_fonte(15, True))
            p.setPen(QColor(cores["texto"]))
            fm_num = QFontMetrics(_fonte(15, True))
            p.drawText(QPointF(x1 + pad, y1 + 38), str(item["quarto"]))
            if estado == "arrumacao":
                p.setFont(_fonte(9))
                p.setPen(QColor(cores["suave"]))
                p.drawText(QPointF(x1 + pad, y1 + 59), "Em arrumação")
            elif estado != "livre":
                nome = item.get("nome_profissional") or "Sem identificação"
                codigo = item.get("codigo_profissional") or "—"
                p.setFont(_fonte(10, True))
                p.setPen(QColor(cores["texto"]))
                nome = QFontMetrics(p.font()).elidedText(
                    f"{nome} · {codigo}", Qt.TextElideMode.ElideRight, int(x2 - x1 - 2 * pad))
                p.drawText(QPointF(x1 + pad, y1 + 59), nome)
            else:
                p.setFont(_fonte(9))
                p.setPen(QColor(cores["suave"]))
                p.drawText(QPointF(x1 + pad, y1 + 59), "Clique para iniciar")
            espaco = x2 - pad - (x1 + pad + fm_num.horizontalAdvance(str(item["quarto"])) + 6)
            if estado in ("livre", "arrumacao"):
                rotulo, fonte = _PILULA[estado], _fonte(10, True)
            else:
                rotulo = ("+" if estado == "estourou" else "") + fmt_relogio(item["restante_seg"])
                for tamanho in (12, 11, 10, 9, 8):          # o tempo cabe inteiro: diminui a fonte, não corta
                    fonte = _fonte(tamanho, True)
                    if QFontMetrics(fonte).horizontalAdvance(rotulo) <= espaco:
                        break
            p.setFont(fonte)
            p.setPen(QColor(cor_pilula))
            fm = QFontMetrics(fonte)
            rotulo = fm.elidedText(rotulo, Qt.TextElideMode.ElideRight, int(max(10, espaco)))
            p.drawText(QPointF(x2 - pad - fm.horizontalAdvance(rotulo), y2 - 9), rotulo)
        p.end()


class PainelQuartosCaixa(QFrame):
    """Linha "Quartos" do caixa, embaixo dos produtos e do pagamento. Some sozinho com o módulo desligado ou sem permissão.

    O operador inicia o tempo depois que o cliente paga: clique no cartão livre (ou Q + número no campo da comanda,
    ex.: Q3) abre a escolha do tempo; no ocupado, + Tempo ou Liberar."""

    def __init__(self, ctx, janela: QWidget | None = None, modo: str = "escuro"):
        super().__init__()
        self.ctx = ctx
        self.janela = janela
        self.modo = modo
        self.avisos = avisos_de(ctx.banco)
        self.aviso_tela = AvisoNaTela(janela, self.avisos) if janela is not None else None
        self.itens: dict[int, dict] = {}
        self.setObjectName("painel_quartos_caixa")
        # Título, resumo e botão do painel na lateral: a linha fica com a altura de um cartão só.
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 5, 8, 5)
        lay.setSpacing(8)
        lateral = QVBoxLayout()
        lateral.setSpacing(0)
        self.titulo = QLabel("Quartos")
        self.titulo.setStyleSheet("font-size: 15px; font-weight: 700;")
        lateral.addWidget(self.titulo)
        self.resumo = QLabel("")
        self.resumo.setStyleSheet("font-size: 11px;")
        lateral.addWidget(self.resumo)
        lateral.addStretch(1)
        self.btn_painel = QPushButton("Painel completo")
        self.btn_painel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_painel.setToolTip("Abrir o painel completo dos quartos")
        self.btn_painel.setStyleSheet("padding: 1px 8px; font-size: 11px;")
        self.btn_painel.clicked.connect(self.abrir_painel)
        lateral.addWidget(self.btn_painel)
        navegacao = QHBoxLayout()
        self.anterior = QPushButton("◀")
        self.proxima = QPushButton("▶")
        for botao, passo in ((self.anterior, -1), (self.proxima, 1)):
            botao.setFocusPolicy(Qt.NoFocus)
            botao.setStyleSheet("padding: 2px;")
            botao.clicked.connect(lambda _=False, p=passo: self.mudar_pagina(p))
            navegacao.addWidget(botao)
        lateral.addLayout(navegacao)
        caixa_lateral = QWidget()
        caixa_lateral.setObjectName("quartos_lateral")
        caixa_lateral.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        caixa_lateral.setStyleSheet("QWidget#quartos_lateral { background: transparent; }")
        caixa_lateral.setLayout(lateral)
        caixa_lateral.setFixedWidth(112)
        lay.addWidget(caixa_lateral)
        self.grade = GradeQuartos()
        self.grade.clicado.connect(self.acionar)
        lay.addWidget(self.grade, 1)
        self._estilizar()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.atualizar)
        self.timer_campainhas = QTimer(self)
        self.timer_campainhas.setInterval(VERIFICAR_CAMPAINHAS_SEG * 1000)
        self.timer_campainhas.timeout.connect(lambda: self.avisos.verificar(self.ctx.quartos, list(self.itens)))
        self.atualizar()
        self.timer.start()
        self.timer_campainhas.start()

    def definir_modo(self, modo: str) -> None:
        self.modo = modo
        self._estilizar()
        self.atualizar()

    def _estilizar(self) -> None:
        c = CORES_MESAS[self.modo]
        self.setStyleSheet(
            f"QFrame#painel_quartos_caixa {{ background: {c['quadro']}; border: 1px solid {c['quadro_borda']};"
            f" border-radius: 12px; }}"
            f"QFrame#painel_quartos_caixa QLabel {{ background: transparent; color: {c['texto']}; }}")

    def texto_do_quarto(self, numero: int) -> str:
        """O que o cartão mostra, em texto (para conferência e testes): '3 · 2:54:00', '1 · livre', '4 · +02:00'."""
        item = self.itens[numero]
        if item["estado"] in ("livre", "arrumacao"):
            return f"{numero} · " + ("livre" if item["estado"] == "livre" else "arrumando")
        return f"{numero} · " + ("+" if item["estado"] == "estourou" else "") + fmt_relogio(item["restante_seg"])

    def mudar_pagina(self, passo):
        self.grade.pagina = max(0, min(self.grade.pagina + passo, (len(self.grade.itens) - 1) // self.grade.POR_PAGINA))
        self.atualizar()

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
        self.itens = {i["quarto"]: i for i in situacao}
        self.grade.definir(situacao, self.modo)
        self.anterior.setVisible(len(situacao) > self.grade.POR_PAGINA)
        self.proxima.setVisible(len(situacao) > self.grade.POR_PAGINA)
        self.anterior.setEnabled(self.grade.pagina > 0)
        self.proxima.setEnabled((self.grade.pagina + 1) * self.grade.POR_PAGINA < len(situacao))
        livres = sum(i["estado"] == "livre" for i in situacao)
        esgotados = sum(i["estado"] == "estourou" for i in situacao)
        c = contagem_quartos(situacao)
        if not c["livres"]:
            livres_txt = "Nenhum livre"
        elif len(c["livres"]) <= 4:                       # poucos: diz quais (cabe na lateral)
            livres_txt = "Livres: " + ", ".join(map(str, c["livres"]))
        else:
            livres_txt = f"{len(c['livres'])} livres"
        self.resumo.setText(f"{livres_txt}\n{c['ocupados']} ocupado{'s' if c['ocupados'] != 1 else ''}")   # o esgotado já pisca em vermelho no cartão
        self.resumo.setToolTip(f"{esgotados} com tempo esgotado" if esgotados else "")
        if self.avisos.processar(ctrl, situacao, fmt.agora_dt()) and self.janela is not None:
            _trazer_para_frente(self.janela)

    def acoes_do_quarto(self, numero: int) -> list[tuple[str, object]]:
        item = self.itens.get(numero, {"estado": "livre", "quarto": numero})
        if item["estado"] == "livre":
            return [("Iniciar tempo…", lambda c: pedir_iniciar(self, c, numero)),
                    ("Pôr em arrumação", lambda c: pedir_arrumacao(self, c, numero, True))]
        if item["estado"] == "arrumacao":
            return [("Quarto pronto", lambda c: pedir_arrumacao(self, c, numero, False))]
        return [("+ Tempo…", lambda c: pedir_mais_tempo(self, c, item)),
                ("Trocar de quarto…", lambda c: pedir_trocar(self, c, numero)),
                ("Liberar quarto", lambda c: pedir_liberar(self, c, numero))]

    def acionar(self, numero: int):
        """Clique no cartão ou Q + número no caixa: livre já abre a escolha do tempo; ocupado mostra as opções."""
        self.atualizar()
        if numero not in self.itens:
            self._avisar_erro(f"Quarto {numero} não existe.")
            return
        acoes = self.acoes_do_quarto(numero)
        if self.itens[numero]["estado"] == "livre":
            self.pedir(acoes[0][1], numero)
            return
        menu = QMenu(self)
        for rotulo, montar in acoes:
            menu.addAction(rotulo, lambda m=montar: self.pedir(m, numero))
        menu.addSeparator()
        menu.addAction("Abrir painel dos quartos", self.abrir_painel)
        i = list(self.itens).index(numero)
        x, y, w, h = self.grade.celula(i)
        menu.popup(self.grade.mapToGlobal(QPoint(int(x + 6), int(y + h))))
        self._menu = menu                                    # testes acessam o último menu aberto

    def pedir(self, montar, numero: int):
        uso_id = self.itens.get(numero, {}).get("uso_id")
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
            self.avisos.mudou(ctrl, numero, uso_id)
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
        ajustar_janela(janela)
        janela.show()
        self._painel = janela


def ler_atalho_quarto(texto: str) -> int | None:
    """'Q3' ou 'q 3' digitado no campo da comanda -> 3; qualquer outra coisa -> None (segue como comanda/mesa)."""
    s = (texto or "").strip().replace(" ", "").upper()
    if len(s) >= 2 and s[0] == "Q" and s[1:].isdigit():
        return int(s[1:])
    return None
