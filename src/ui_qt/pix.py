"""Janela do Pix integrado: QR Code com o valor, espera a confirmação do banco e fecha sozinha quando paga.

A consulta ao Mercado Pago roda numa thread (a tela não trava); o resultado é gravado na thread principal.
Esc ou Cancelar desiste do Pix (cancela a cobrança no Mercado Pago). Se o cliente pagou no meio, vale o pagamento.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

INTERVALO_MS = 2500


class DialogoPix(QDialog):
    def __init__(self, pix, venda_id: int, valor_cent: int, parent=None, imprimir=None):
        super().__init__(parent)
        self.pix = pix
        self.imprimir_qr = imprimir
        self.situacao = "pendente"
        self._consulta = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self.setWindowTitle("Pix")
        self.setModal(True)
        layout = QVBoxLayout(self)
        titulo = QLabel(f"Pix de {fmt.fmt_brl(valor_cent)}")
        titulo.setObjectName("titulo")
        titulo.setAlignment(Qt.AlignCenter)
        layout.addWidget(titulo)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.cobranca = pix.iniciar(venda_id, valor_cent)      # ErroNegocio sobe para quem abriu a janela
        finally:
            QApplication.restoreOverrideCursor()
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignCenter)
        imagem = QPixmap()
        if self.cobranca.get("imagem_base64") and imagem.loadFromData(base64.b64decode(self.cobranca["imagem_base64"])):
            self.qr.setPixmap(imagem.scaled(320, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.qr.setText("QR Code indisponível: use o copia e cola ou imprima.")
        layout.addWidget(self.qr)
        self.estado = QLabel("Aguardando o pagamento… a venda só recebe quando o banco confirmar.")
        self.estado.setWordWrap(True)
        self.estado.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.estado)
        copia = QLabel(self.cobranca.get("copia_cola") or "")
        copia.setObjectName("mudo")
        copia.setWordWrap(True)
        copia.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(copia)
        botoes = QHBoxLayout()
        self.btn_conferir = QPushButton("Conferir agora")
        self.btn_conferir.clicked.connect(self.conferir)
        botoes.addWidget(self.btn_conferir)
        self.btn_imprimir = QPushButton("Imprimir QR")
        self.btn_imprimir.clicked.connect(self.imprimir)
        self.btn_imprimir.setVisible(imprimir is not None)
        botoes.addWidget(self.btn_imprimir)
        self.btn_cancelar = QPushButton("Cancelar Pix (Esc)")
        self.btn_cancelar.clicked.connect(self.reject)
        botoes.addWidget(self.btn_cancelar)
        layout.addLayout(botoes)
        self.relogio = QTimer(self)
        self.relogio.timeout.connect(self._tique)
        self.relogio.start(INTERVALO_MS)

    # ------------------------------------------------------------ consulta
    def _tique(self) -> None:
        if self._consulta is None:
            self._consulta = self._executor.submit(self.pix.consultar_provedor, self.cobranca["provedor_id"])
            return
        if not self._consulta.done():
            return
        consulta, self._consulta = self._consulta, None
        try:
            resposta = consulta.result()
        except Exception as erro:  # noqa: BLE001 - rede: tenta de novo no próximo tique
            self.estado.setText(f"Sem resposta do Mercado Pago ({type(erro).__name__}). Tentando de novo…")
            return
        self._receber(self.pix.aplicar(self.cobranca["id"], resposta), resposta.mensagem)

    def conferir(self) -> str:
        """Consulta já (sem thread): o botão e os testes usam."""
        try:
            situacao = self.pix.verificar(self.cobranca["id"])
        except ErroNegocio as erro:
            self.estado.setText(str(erro))
            return self.situacao
        self._receber(situacao)
        return situacao

    def _receber(self, situacao: str, mensagem: str = "") -> None:
        self.situacao = situacao
        if situacao == "aprovado":
            self._parar()
            self.estado.setText("Pix confirmado pelo banco.")
            self.accept()
        elif situacao in ("cancelado", "expirado"):
            self._parar()
            self.estado.setText("O QR Code venceu. Feche e gere outro." if situacao == "expirado"
                                else "O Pix foi cancelado ou recusado. Feche e tente de novo.")
            self.btn_conferir.setEnabled(False)
            self.btn_cancelar.setText("Fechar (Esc)")

    def imprimir(self) -> None:
        if self.imprimir_qr is not None:
            try:
                self.imprimir_qr(self.cobranca)
                self.estado.setText("QR Code mandado para a impressora. Aguardando o pagamento…")
            except ErroNegocio as erro:
                self.estado.setText(str(erro))

    # ------------------------------------------------------------ saída
    def _parar(self) -> None:
        self.relogio.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def reject(self) -> None:
        """Desistiu: cancela no Mercado Pago. Se já estava pago, fica com o pagamento (accept)."""
        if self.situacao == "pendente":
            try:
                self.situacao = self.pix.cancelar(self.cobranca["id"])
            except ErroNegocio:
                self.situacao = "cancelado"
            if self.situacao == "aprovado":
                self._parar()
                return super().accept()
        self._parar()
        super().reject()


def cobrar(pix, venda_id: int, valor_cent: int, parent=None, imprimir=None) -> int | None:
    """Abre a janela. Devolve o id da cobrança aprovada, ou None se desistiu (ErroNegocio se não deu para gerar)."""
    dialogo = DialogoPix(pix, venda_id, valor_cent, parent, imprimir)
    aprovado = dialogo.exec() == QDialog.DialogCode.Accepted and dialogo.situacao == "aprovado"
    return dialogo.cobranca["id"] if aprovado else None
