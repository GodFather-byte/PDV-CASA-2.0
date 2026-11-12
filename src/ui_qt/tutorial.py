"""Camada visual não modal: a operação continua recebendo cliques normalmente."""
from PySide6.QtCore import QObject, QTimer, Qt, QRect, QEvent
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QScrollArea, QTabWidget
from src.controllers.tutoriais import PRODUTO, Tutoriais

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
    def __init__(self, janelas, passos=PRODUTO, aviso=None):
        super().__init__()
        self.janelas, self.passos = janelas, passos
        self.aviso = aviso or (lambda mensagem: None)
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
        self.ativo = False
        self.timer.stop()
        QApplication.instance().removeEventFilter(self)
        self._limpar()
        if mensagem:
            self.aviso(mensagem)

    def _limpar(self):
        for janela in (self.sombra, self.balao):
            if janela is not None:
                janela.hide()
                janela.deleteLater()
        self.sombra = self.balao = None
        self.alvo = None

    def eventFilter(self, objeto, evento):
        janela = self.janelas.get(self.passos[self.indice].janela)
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
        if janela is None or not janela.isVisible():
            self.encerrar("Tutorial encerrado: a janela foi fechada.")
            return
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
            self.balao.setStyleSheet("QFrame {background: #fff; color: #18222c; border: 1px solid #888; border-radius: 6px;} QPushButton {color: #18222c; background: #eee; padding: 5px;}")
            layout = QVBoxLayout(self.balao)
            texto = QLabel(f"{self.indice + 1}/{len(self.passos)} — {passo.texto}")
            texto.setWordWrap(True)
            layout.addWidget(texto)
            linha = QHBoxLayout()
            self.voltar = QPushButton("Voltar")
            self.voltar.clicked.connect(lambda: self.mover(-1))
            self.proximo = QPushButton("Próximo")
            self.proximo.clicked.connect(lambda: self.mover(1))
            pular = QPushButton("Pular")
            pular.clicked.connect(lambda: self.encerrar())
            for botao in (self.voltar, self.proximo, pular):
                linha.addWidget(botao)
            layout.addLayout(linha)
            self.balao.setFixedWidth(min(340, janela.width() - 16))
            self.balao.adjustSize()
            self.sombra.show()
            self.balao.show()
        valor = alvo.text() if hasattr(alvo, "text") else ""
        self.proximo.setEnabled(Tutoriais.permite(passo, valor, bool(self.janelas.get("formulario"))))
        pode_voltar = self.indice > 0 and self.passos[self.indice - 1].janela == passo.janela
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
        self.indice = 2
        self._limpar()
        formulario.accepted.connect(lambda: self.encerrar("Produto cadastrado. Tutorial concluído!"))
        formulario.rejected.connect(lambda: self.encerrar())
        QTimer.singleShot(0, self.atualizar)


def iniciar_produto(principal):
    anterior = getattr(principal, "tutorial", None)
    if anterior and anterior.ativo:
        anterior.encerrar()
    janela = principal.abrir_cadastro("produtos")
    if janela is None:
        return
    def avisar(mensagem):
        janela.mensagem.setText(mensagem)
        principal.mensagem.setText(mensagem)
    motor = MotorTutorial({"lista": janela}, aviso=avisar)
    principal.tutorial = motor
    def aberto(formulario):
        if not motor.ativo:
            return
        if formulario.id_ is not None:
            motor.encerrar("Para este tutorial, use Novo em vez de Editar.")
            return
        formulario.preparar_tutorial()
        formulario.tutorial_ativo = lambda: motor.ativo
        motor.formulario(formulario)
    janela.formulario_aberto.connect(aberto)
    janela.finished.connect(lambda: motor.encerrar())
