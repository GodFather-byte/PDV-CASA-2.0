"""Tela para gerar a folha A4 com o QR de cada mesa. A impressão abre no navegador."""
from __future__ import annotations

import os
import tempfile
import webbrowser

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from src.cardapio.folha import cartoes, folha_html, intervalo_mesas
from src.controllers.config_controller import ConfigController
from src.core.erros import ErroNegocio


class JanelaCardapioQr(QDialog):
    def __init__(self, banco, parent=None):
        super().__init__(parent)
        self.banco = banco
        self.setWindowTitle("QR do cardápio")
        self.resize(460, 280)
        config = ConfigController(banco)
        self._loja = config.nome_loja()
        self._url = banco.cfg("api_url")
        self._chave = banco.cfg("chave_loja")
        self._com_mesa = banco.cfg_bool("usar_mesas", True)
        teto = max(min(banco.cfg_int("num_mesas", 50), 999), 1)
        layout = QVBoxLayout(self)
        texto = QLabel(
            "Cada QR abre o cardápio dessa mesa na nuvem. É só consulta: o cliente não faz pedido pelo celular.\n"
            "Ligue \"Cardápio digital\" nesta aba e salve, com a nuvem preenchida, para os preços subirem."
        )
        texto.setWordWrap(True)
        layout.addWidget(texto)
        formulario = QFormLayout()
        self.inicio = QSpinBox()
        self.fim = QSpinBox()
        for campo in (self.inicio, self.fim):
            campo.setRange(1, 999)
        self.inicio.setValue(1)
        self.fim.setValue(teto)
        if self._com_mesa:
            formulario.addRow("Da mesa", self.inicio)
            formulario.addRow("Até a mesa", self.fim)
        else:
            formulario.addRow(QLabel("Esta casa não usa mesas: a folha sai com um QR só do cardápio."))
            self.inicio.hide()
            self.fim.hide()
        layout.addLayout(formulario)
        self.aviso = QLabel("")
        self.aviso.setWordWrap(True)
        layout.addWidget(self.aviso)
        barra = QHBoxLayout()
        abrir = QPushButton("Abrir folha para imprimir")
        abrir.clicked.connect(self.abrir_folha)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.close)
        barra.addWidget(abrir)
        barra.addWidget(fechar)
        layout.addLayout(barra)

    def _itens(self) -> list[dict]:
        if not self._com_mesa:
            return cartoes(self._url, self._chave)
        return cartoes(self._url, self._chave, self.inicio.value(), self.fim.value())

    def abrir_folha(self) -> None:
        try:
            if self._com_mesa:
                intervalo_mesas(self.inicio.value(), self.fim.value())
            html = folha_html(self._loja, self._itens())
        except ErroNegocio as erro:
            QMessageBox.warning(self, "QR do cardápio", str(erro))
            return
        caminho = os.path.join(tempfile.gettempdir(), "cardapio-qr.html")
        with open(caminho, "w", encoding="utf-8") as arquivo:
            arquivo.write(html)
        if not webbrowser.open(caminho):
            self.aviso.setText("Não abri o navegador. A folha está em:\n" + caminho)
            return
        self.aviso.setText("A folha abriu no navegador. Use Imprimir e escolha o papel A4.")
