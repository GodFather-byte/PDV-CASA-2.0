"""Foto do produto nas telas Qt: o quadro que se ajusta ao espaço (caixa e cadastro) e o editor do cadastro."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from src.controllers import foto_produto_controller as fotos
from src.core.erros import ErroNegocio
from src.ui_qt.tema import texto


class QuadroFoto(QLabel):
    """Mostra a foto inteira, sem distorcer, no tamanho que sobrar. Nunca aumenta a altura mínima da tela."""

    def __init__(self, maximo: int = 220, parent=None):
        super().__init__(parent)
        self._original = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(1, 1)
        self.setMaximumHeight(maximo)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)

    def definir(self, dados: bytes | None) -> bool:
        """Carrega o JPEG; False (e quadro vazio) se não houver foto ou ela não abrir."""
        pixmap = QPixmap()
        if not dados or not pixmap.loadFromData(dados):
            self._original = QPixmap()
            self.clear()
            return False
        self._original = pixmap
        self._ajustar()
        return True

    def tem_foto(self) -> bool:
        return not self._original.isNull()

    def _ajustar(self) -> None:
        if self._original.isNull():
            return
        largura, altura = max(self.width(), 1), max(min(self.height(), self.maximumHeight()), 1)
        self.setPixmap(self._original.scaled(largura, altura, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, evento):  # noqa: N802 - nome do Qt
        super().resizeEvent(evento)
        self._ajustar()


class EditorFoto(QWidget):
    """Aba "Foto" do cadastro: escolher arquivo, buscar pelo código de barras ou remover. Só grava ao salvar."""

    def __init__(self, ctx, produto_id: int | None, codigo_barras, parent=None):
        super().__init__(parent)
        self.ctx, self.produto_id = ctx, produto_id
        self._codigo_barras = codigo_barras          # função que devolve o código de barras digitado no formulário
        self.controle = fotos.FotoProdutoController(ctx.banco)
        self.pendente: fotos.FotoPreparada | None = None
        self.remover_ao_salvar = False
        layout = QVBoxLayout(self)
        layout.addWidget(texto(
            "A foto aparece no caixa quando o produto é lançado e no cardápio online. Escolha uma imagem do computador "
            "ou busque pelo código de barras numa base pública (Open Food Facts); confira se é o produto certo antes "
            "de salvar.", "suave"))
        self.quadro = QuadroFoto(240)
        self.quadro.setMinimumHeight(200)
        self.quadro.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.quadro, 1)
        self.situacao = texto("", "suave")
        layout.addWidget(self.situacao)
        botoes = QHBoxLayout()
        self.btn_arquivo = QPushButton("Escolher arquivo…")
        self.btn_arquivo.clicked.connect(lambda: self.escolher_arquivo())
        botoes.addWidget(self.btn_arquivo)
        self.btn_internet = QPushButton("Buscar pelo código de barras")
        self.btn_internet.clicked.connect(lambda: self.buscar_na_internet())
        botoes.addWidget(self.btn_internet)
        self.btn_remover = QPushButton("Remover foto")
        self.btn_remover.clicked.connect(self.remover)
        botoes.addWidget(self.btn_remover)
        layout.addLayout(botoes)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        atual = self.controle.imagem(produto_id) if produto_id is not None else None
        self.quadro.definir(atual)
        self._situacao("Foto atual" + (" (veio da internet)" if atual and self.controle.origem(produto_id) else "")
                       if atual else "Sem foto")

    def _situacao(self, frase: str) -> None:
        self.situacao.setText(frase)
        self.btn_remover.setEnabled(self.quadro.tem_foto())

    def _mostrar(self, foto: fotos.FotoPreparada, frase: str) -> None:
        self.pendente, self.remover_ao_salvar = foto, False
        self.quadro.definir(foto.imagem)
        self.mensagem.setText("")
        self._situacao(frase + " Clique em Salvar para guardar.")

    def escolher_arquivo(self, caminho: str | None = None) -> bool:
        if caminho is None:
            caminho, _ = QFileDialog.getOpenFileName(
                self, "Foto do produto", "", "Imagens (*.jpg *.jpeg *.png *.bmp *.webp)")
            if not caminho:
                return False
        try:
            foto = fotos.preparar(fotos.ler_arquivo(caminho))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        self._mostrar(foto, "Foto escolhida do computador.")
        return True

    def buscar_na_internet(self, http=None) -> bool:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            foto = fotos.buscar_na_internet(self._codigo_barras(), http)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self._mostrar(foto, "Foto encontrada na internet (Open Food Facts). Confira se é o produto certo.")
        return True

    def remover(self) -> None:
        self.pendente, self.remover_ao_salvar = None, True
        self.quadro.definir(None)
        self.mensagem.setText("")
        self._situacao("A foto será removida ao salvar.")

    def aplicar(self, produto_id: int) -> None:
        """Depois que o cadastro foi salvo: grava a foto nova ou remove a antiga."""
        if self.pendente is not None:
            self.controle.gravar(produto_id, self.pendente)
        elif self.remover_ao_salvar:
            self.controle.remover(produto_id)
        self.pendente, self.remover_ao_salvar, self.produto_id = None, False, produto_id


class JanelaFotosEmLote(QDialog):
    """Busca a foto de todos os produtos sem foto pelo código de barras; a pessoa aprova uma a uma antes de gravar.

    A busca roda numa thread (a tela não trava) com uma pausa entre produtos, para não sobrecarregar a base pública.
    Os resultados voltam por uma fila lida pela thread da tela; nada é gravado sem clicar em "Salvar aprovadas"."""

    PAUSA_SEGUNDOS = 0.7

    def __init__(self, ctx, parent=None, buscar=None):
        super().__init__(parent)
        from queue import Queue
        from threading import Event
        from PySide6.QtCore import QTimer
        self.ctx = ctx
        self.controle = fotos.FotoProdutoController(ctx.banco)
        self._buscar = buscar or fotos.buscar_na_internet
        self._fila: Queue = Queue()
        self._parar = Event()
        self._thread = None
        self.achadas: dict[int, fotos.FotoPreparada] = {}
        self.setWindowTitle("Buscar fotos dos produtos")
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        self.pendentes = self.controle.sem_foto_com_codigo()
        layout.addWidget(texto(
            f"{len(self.pendentes)} produto(s) à venda sem foto e com código de barras. A busca usa a base pública "
            "Open Food Facts e precisa de internet. Desmarque as fotos que não forem do produto certo antes de salvar.",
            "suave"))
        self.lista = QListWidget()
        self.lista.setIconSize(QSize(72, 72))
        layout.addWidget(self.lista, 1)
        self.situacao = texto("", "suave")
        layout.addWidget(self.situacao)
        botoes = QHBoxLayout()
        self.btn_buscar = QPushButton("Buscar fotos")
        self.btn_buscar.clicked.connect(lambda: self.buscar_todos())
        self.btn_parar = QPushButton("Parar")
        self.btn_parar.setEnabled(False)
        self.btn_parar.clicked.connect(self._parar.set)
        self.btn_salvar = QPushButton("Salvar aprovadas")
        self.btn_salvar.setEnabled(False)
        self.btn_salvar.clicked.connect(self.salvar_aprovadas)
        for botao in (self.btn_buscar, self.btn_parar, self.btn_salvar):
            botoes.addWidget(botao)
        layout.addLayout(botoes)
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._receber)
        if not self.pendentes:
            self.btn_buscar.setEnabled(False)
            self.situacao.setText("Todos os produtos com código de barras já têm foto.")

    def _trabalhar(self, pendentes, pausa):
        import time
        for indice, produto in enumerate(pendentes):
            if self._parar.is_set():
                break
            try:
                self._fila.put(("achou", produto, self._buscar(produto["cbarra"])))
            except ErroNegocio as erro:
                self._fila.put(("nao", produto, str(erro)))
            except Exception as erro:  # noqa: BLE001 - qualquer falha de rede vira linha "não achou"
                self._fila.put(("nao", produto, type(erro).__name__))
            if pausa and indice + 1 < len(pendentes) and self._parar.wait(pausa):
                break
        self._fila.put(("fim", None, None))

    def buscar_todos(self, sincrono: bool = False) -> None:
        if self._thread is not None:
            return
        self.lista.clear()
        self.achadas.clear()
        self._parar.clear()
        self.btn_buscar.setEnabled(False)
        self.btn_parar.setEnabled(True)
        self.situacao.setText("Buscando…")
        if sincrono:                                  # testes: sem thread e sem pausa
            self._trabalhar(self.pendentes, 0)
            self._receber()
            return
        from threading import Thread
        self._thread = Thread(target=self._trabalhar, args=(list(self.pendentes), self.PAUSA_SEGUNDOS), daemon=True)
        self._thread.start()
        self._timer.start()

    def _receber(self) -> None:
        from queue import Empty
        from PySide6.QtGui import QIcon
        while True:
            try:
                tipo, produto, dado = self._fila.get_nowait()
            except Empty:
                return
            if tipo == "fim":
                self._timer.stop()
                self._thread = None
                self.btn_buscar.setEnabled(True)
                self.btn_parar.setEnabled(False)
                self.btn_salvar.setEnabled(bool(self.achadas))
                self.situacao.setText(f"{len(self.achadas)} foto(s) encontrada(s) de {self.lista.count()} produto(s) "
                                      "consultado(s). Confira e salve as aprovadas.")
                continue
            item = QListWidgetItem()
            item.setData(Qt.UserRole, produto["id"])
            if tipo == "achou":
                self.achadas[produto["id"]] = dado
                pixmap = QPixmap()
                pixmap.loadFromData(dado.miniatura)
                item.setIcon(QIcon(pixmap))
                item.setText(f"{produto['nome']}  ·  {produto['cbarra']}")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
            else:
                item.setText(f"{produto['nome']}  ·  {produto['cbarra']}  —  sem foto: {dado}")
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            self.lista.addItem(item)
            self.situacao.setText(f"Consultados {self.lista.count()} de {len(self.pendentes)}…")

    def aprovadas(self) -> list[int]:
        ids = []
        for i in range(self.lista.count()):
            item = self.lista.item(i)
            pid = item.data(Qt.UserRole)
            if pid in self.achadas and item.checkState() == Qt.Checked:
                ids.append(pid)
        return ids

    def salvar_aprovadas(self) -> int:
        gravadas = 0
        for pid in self.aprovadas():
            try:
                self.controle.gravar(pid, self.achadas[pid])
                gravadas += 1
            except ErroNegocio:
                continue                              # produto apagado no meio do caminho: segue com os outros
        self.situacao.setText(f"{gravadas} foto(s) salva(s).")
        self.btn_salvar.setEnabled(False)
        return gravadas

    def done(self, resultado):
        self._parar.set()
        self._timer.stop()
        super().done(resultado)
