"""Foto do produto nas telas Qt: o quadro que se ajusta ao espaço (caixa e cadastro) e o editor do cadastro."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
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
