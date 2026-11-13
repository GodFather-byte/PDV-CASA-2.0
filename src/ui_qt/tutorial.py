"""Camada visual não modal: a operação continua recebendo cliques normalmente."""
import shiboken6
from PySide6.QtCore import QObject, QTimer, Qt, QRect, QEvent
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (QApplication, QComboBox, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
                               QScrollArea, QTabWidget)
from src.controllers.tutoriais import PRODUTO, ROTEIROS, Tutoriais

# Letra grande e contraste alto: o balão tem de ser lido sem esforço por quem enxerga pouco ou nunca usou sistema.
ESTILO_BALAO = (
    "QFrame {background: #ffffff; color: #101820; border: 2px solid #1f6feb; border-radius: 8px;}"
    " QLabel {border: none; font-size: 16px;}"
    " QLabel#tutorial_passo {font-size: 13px; font-weight: bold; color: #1f6feb;}"
    " QLabel#tutorial_dica {font-size: 13px; color: #9a3412;}"
    " QPushButton {color: #101820; background: #e8eaed; border: 1px solid #9aa0a6; border-radius: 6px;"
    " padding: 8px 12px; font-size: 15px; min-height: 22px;}"
    " QPushButton#tutorial_proximo {background: #1f6feb; color: #ffffff; border: none; font-weight: bold;}"
    " QPushButton#tutorial_proximo:disabled {background: #c9d1d9; color: #57606a;}"
    " QPushButton:disabled {color: #8c959f;}"
)
DICA_TECLADO = "Faça no teclado o que está escrito. O tutorial segue sozinho."
# O que falta fazer para o botão Próximo acender, dito em palavras simples.
DICAS = {
    "formulario": "Clique no botão destacado para continuar.",
    "preenchido": "Escreva no campo destacado para continuar.",
    "escolhido": "Escolha uma opção no campo destacado para continuar.",
    "preco": "Digite um preço, como 12,50, para continuar.",
    "salvo": "Clique em Salvar para terminar.",
}

class Sombra(QWidget):
    def __init__(self, janela):
        super().__init__(janela)
        self.recorte = QRect()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, evento):
        pintor = QPainter(self)
        caminho = QPainterPath()
        caminho.addRect(self.rect())
        abertura = QPainterPath()
        abertura.addRect(self.recorte)
        pintor.fillPath(caminho.subtracted(abertura), QColor(0, 0, 0, 155))

class MotorTutorial(QObject):
    def __init__(self, janelas, passos=PRODUTO, aviso=None, fim="Produto cadastrado. Tutorial concluído!",
                 ao_encerrar=None, avaliar=None, ao_concluir=None):
        """`avaliar(condicao, janela)` responde condições que só a tela conhece (None = não é dela).
        `ao_concluir` é chamado quando a pessoa passa do último passo (tutoriais que não terminam num Salvar)."""
        super().__init__()
        self.janelas, self.passos = janelas, passos
        self.aviso = aviso or (lambda mensagem: None)
        self.fim = fim
        self.ao_encerrar = ao_encerrar
        self.avaliar = avaliar
        self.ao_concluir = ao_concluir
        self.indice = 0
        self.ativo = True
        self.sombra = self.balao = None
        self.alvo = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.atualizar)
        QApplication.instance().installEventFilter(self)
        self.timer.start(100)
        self.atualizar()

    def encerrar(self, mensagem=""):
        if not self.ativo:
            return
        self.ativo = False
        self.timer.stop()
        QApplication.instance().removeEventFilter(self)
        self._limpar()
        if mensagem:
            self.aviso(mensagem)
        if self.ao_encerrar is not None:
            self.ao_encerrar()

    def _limpar(self):
        for janela in (self.sombra, self.balao):
            if janela is not None and shiboken6.isValid(janela):
                janela.hide()
                janela.deleteLater()
        self.sombra = self.balao = None
        self.alvo = None

    def eventFilter(self, objeto, evento):
        janela = self.janelas.get(self.passos[self.indice].janela)
        if janela is not None and not shiboken6.isValid(janela):
            return False
        if (evento.type() == QEvent.Type.KeyPress and evento.key() == Qt.Key.Key_Escape
                and isinstance(objeto, QWidget) and objeto.window() is janela):
            self.encerrar()
            return True
        return False

    def mover(self, delta):
        if delta > 0 and not self.proximo.isEnabled():
            return
        novo = self.indice + delta
        # Voltar ao cadastro não descarta o formulário em edição.
        if novo < 0:
            return
        if novo >= len(self.passos):
            if self.ao_concluir is not None:
                self.ao_concluir()
                self.encerrar(self.fim)
            else:
                self.encerrar()
            return
        if self.passos[novo].janela == "lista" and self.janelas.get("formulario"):
            return
        self.indice = novo
        self._limpar()
        self.atualizar()

    def atualizar(self):
        if not self.ativo:
            return
        passo = self.passos[self.indice]
        janela = self.janelas.get(passo.janela)
        if janela is not None and not shiboken6.isValid(janela):     # a janela já foi destruída pelo Qt
            janela = None
        if janela is None or not janela.isVisible():
            self.encerrar("Tutorial encerrado: a janela foi fechada.")
            return
        alvo = getattr(janela, passo.widget, None)            # o caixa expõe os campos como atributos
        if not isinstance(alvo, QWidget):
            alvo = janela.findChild(QWidget, passo.widget)
        if alvo is None:
            self.encerrar(f"Tutorial indisponível: campo {passo.widget} não encontrado.")
            return
        if self.alvo is not alvo:
            self._limpar()
            self.alvo = alvo
            pai = alvo.parentWidget()
            while pai is not None and pai is not janela:
                if isinstance(pai, QTabWidget):
                    for i in range(pai.count()):
                        if pai.widget(i).isAncestorOf(alvo):
                            pai.setCurrentIndex(i)
                if isinstance(pai, QScrollArea):
                    pai.ensureWidgetVisible(alvo, 8, 8)
                pai = pai.parentWidget()
            self.sombra = Sombra(janela)
            self.balao = QFrame(janela)
            self.balao.setStyleSheet(ESTILO_BALAO)
            layout = QVBoxLayout(self.balao)
            numero = QLabel(f"Passo {self.indice + 1} de {len(self.passos)}")
            numero.setObjectName("tutorial_passo")
            layout.addWidget(numero)
            texto = QLabel(passo.texto)
            texto.setWordWrap(True)
            layout.addWidget(texto)
            self.dica = QLabel("")
            self.dica.setObjectName("tutorial_dica")
            self.dica.setWordWrap(True)
            self.dica.setVisible(False)
            layout.addWidget(self.dica)
            linha = QHBoxLayout()
            self.voltar = QPushButton("Voltar")
            self.voltar.clicked.connect(lambda: self.mover(-1))
            ultimo = self.indice == len(self.passos) - 1
            self.proximo = QPushButton("Concluir" if ultimo and self.ao_concluir is not None else "Próximo")
            self.proximo.setObjectName("tutorial_proximo")
            self.proximo.clicked.connect(lambda: self.mover(1))
            pular = QPushButton("Sair do tutorial")
            pular.clicked.connect(lambda: self.encerrar())
            for botao in (self.voltar, self.proximo, pular):
                botao.setFocusPolicy(Qt.FocusPolicy.NoFocus)      # o cursor fica no campo que a pessoa está usando
                linha.addWidget(botao)
            if passo.avanca:                                      # passo feito no teclado: segue sozinho
                self.voltar.hide()
                self.proximo.hide()
            layout.addLayout(linha)
            self.balao.setFixedWidth(min(420, janela.width() - 16))
            self.balao.adjustSize()
            self.sombra.show()
            self.balao.show()
        if isinstance(alvo, QComboBox):
            valor = "" if alvo.currentData() is None else "escolhido"
        else:
            valor = alvo.text() if hasattr(alvo, "text") else ""
        liberado = self.avaliar(passo.condicao, janela) if self.avaliar is not None and passo.condicao else None
        if liberado is None:
            liberado = Tutoriais.permite(passo, valor, bool(self.janelas.get("formulario")))
        self.proximo.setEnabled(liberado)
        if passo.avanca and liberado:
            self.mover(1)
            return
        dica = "" if liberado else (DICA_TECLADO if passo.avanca else DICAS.get(passo.condicao, ""))
        if self.dica.text() != dica:
            self.dica.setText(dica)
            self.dica.setVisible(bool(dica))
            self.balao.adjustSize()
        anterior = self.passos[self.indice - 1] if self.indice > 0 else None
        pode_voltar = anterior is not None and anterior.janela == passo.janela and not anterior.avanca
        self.voltar.setEnabled(pode_voltar)
        self.sombra.setGeometry(janela.rect())
        recorte = QRect(alvo.mapTo(janela, alvo.rect().topLeft()), alvo.size()).adjusted(-3, -3, 3, 3)
        self.sombra.recorte = recorte
        self.sombra.update()
        altura = self.balao.height()
        y = recorte.bottom() + 8
        if y + altura > janela.height():
            y = max(0, recorte.top() - altura - 8)
        self.balao.move(max(0, min(recorte.left(), janela.width() - self.balao.width())), y)
        self.sombra.raise_()
        self.balao.raise_()

    def formulario(self, formulario):
        self.janelas["formulario"] = formulario
        self.indice = next(i for i, passo in enumerate(self.passos) if passo.janela == "formulario")
        self._limpar()
        formulario.accepted.connect(lambda: self.encerrar(self.fim))
        formulario.rejected.connect(lambda: self.encerrar())
        QTimer.singleShot(0, self.atualizar)


def iniciar(principal, chave="produto"):
    """Abre o cadastro do roteiro e guia a pessoa até salvar um registro de verdade."""
    roteiro = ROTEIROS[chave]
    if roteiro.tipo == "treino":
        from src.ui_qt.treino import iniciar_venda
        return iniciar_venda(principal)
    anterior = getattr(principal, "tutorial", None)
    if anterior and anterior.ativo:
        anterior.encerrar()
    janela = principal.abrir_cadastro(roteiro.cadastro)
    if janela is None:
        return None
    def avisar(mensagem):
        janela.mensagem.setText(mensagem)
        principal.mensagem.setText(mensagem)
    motor = MotorTutorial({"lista": janela}, roteiro.passos, aviso=avisar, fim=roteiro.fim,
                          ao_encerrar=getattr(principal, "marcar_tutoriais", None))
    principal.tutorial = motor
    def aberto(formulario):
        if not motor.ativo:
            return
        if formulario.id_ is not None:
            motor.encerrar("Para este tutorial, use Novo em vez de Editar.")
            return
        if chave == "produto":
            formulario.preparar_tutorial()          # produto também lança o estoque inicial
        else:
            formulario.tutorial_chave = chave       # os outros concluem ao salvar
        formulario.tutorial_ativo = lambda: motor.ativo
        motor.formulario(formulario)
    janela.formulario_aberto.connect(aberto)
    janela.finished.connect(lambda: motor.encerrar())
    return motor


def iniciar_produto(principal):
    return iniciar(principal, "produto")
