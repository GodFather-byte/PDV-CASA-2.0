"""Endereço do porteiro no celular: liga, define o PIN e mostra o QR para o Wi-Fi do clube.

A página em si não passa por esta janela. Ela sai do caixa, na rede local, e só consulta.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from src.core.erros import ErroNegocio
from src.porteiro.servico import PORTA_PADRAO, definir_pin, descrever, png_qr, porta_configurada, url_do_qr, urls_publicas
from src.ui_qt.tema import texto


class JanelaPorteiro(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._url = ""
        self._pode = bool(ctx.operador is not None and ctx.pode("cfg_configuracoes"))
        self.setWindowTitle("Porteiro no celular")
        self.resize(660, 610)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(9)
        layout.addWidget(texto("Porteiro no celular", "titulo"))
        layout.addWidget(texto(
            "Com o celular no Wi-Fi da casa, o porteiro usa o PIN para conferir os itens e o saldo "
            "da comanda antes da saída. A consulta local funciona sem internet.",
            "suave"))
        self.ativo = QCheckBox("Ligado")
        self.porta = QLineEdit()
        self.porta.setPlaceholderText(str(PORTA_PADRAO))
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin.setPlaceholderText("Vazio mantém o PIN atual")
        self.pin2 = QLineEdit()
        self.pin2.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin2.setPlaceholderText("Repita o PIN novo")
        acesso = QGroupBox("Acesso pela rede local")
        formulario = QFormLayout(acesso)
        formulario.addRow("Página na rede do clube", self.ativo)
        formulario.addRow("Porta", self.porta)
        formulario.addRow("PIN novo (4 a 8 números)", self.pin)
        formulario.addRow("Confirmar PIN", self.pin2)
        layout.addWidget(acesso)
        conexao = QGroupBox("Endereço da portaria")
        endereco = QHBoxLayout(conexao)
        self.lbl_enderecos = texto("")
        self.lbl_enderecos.setObjectName("enderecos_porteiro")
        self.lbl_enderecos.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        endereco.addWidget(self.lbl_enderecos, 1)
        self.qr = QLabel()
        self.qr.setObjectName("qr_porteiro")
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        endereco.addWidget(self.qr)
        layout.addWidget(conexao)
        layout.addStretch()
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        barra = QHBoxLayout()
        self.btn_salvar = QPushButton("Salvar")
        self.btn_salvar.setObjectName("primario")
        self.btn_copiar = QPushButton("Copiar endereço")
        fechar = QPushButton("Fechar")
        self.btn_salvar.clicked.connect(self.salvar)
        self.btn_copiar.clicked.connect(self.copiar)
        fechar.clicked.connect(self.accept)
        barra.addWidget(self.btn_copiar)
        barra.addStretch()
        barra.addWidget(fechar)
        barra.addWidget(self.btn_salvar)
        layout.addLayout(barra)
        self._carregar()
        if not self._pode:
            for campo in (self.ativo, self.porta, self.pin, self.pin2, self.btn_salvar):
                campo.setEnabled(False)
            self.mensagem.setText("Seu acesso vê o endereço, mas não altera o PIN nem liga a página.")

    def _erro_rede(self) -> str | None:
        principal = self.parent()
        app = getattr(principal, "app", None)
        for servico in getattr(app, "servicos", []):
            erro = getattr(servico, "erro_porteiro", None)
            if erro:
                return erro
        return None

    def _carregar(self) -> None:
        banco = self.ctx.banco
        self.ativo.setChecked(banco.cfg_bool("porteiro_ativo", False))
        self.porta.setText(banco.cfg("porteiro_porta", str(PORTA_PADRAO)) or str(PORTA_PADRAO))
        self.pin.clear()
        self.pin2.clear()
        self._mostrar_endereco()

    def _mostrar_endereco(self) -> None:
        banco = self.ctx.banco
        from src.porteiro.nuvem_envio import endereco_4g
        self.lbl_enderecos.setText(descrever(banco, self._erro_rede()) + "\n" + endereco_4g(banco))
        self._url = ""
        self.qr.clear()
        if not banco.cfg_bool("porteiro_ativo", False) or not (banco.cfg("porteiro_pin_hash") or "").strip():
            return
        porta = porta_configurada(banco.cfg("porteiro_porta", str(PORTA_PADRAO)))
        if porta is None:
            return
        self._url = url_do_qr(urls_publicas(porta))
        if not self._url:
            return
        imagem = QPixmap()
        imagem.loadFromData(png_qr(self._url))
        self.qr.setPixmap(imagem.scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))

    def salvar(self) -> None:
        if not self._pode:
            self.mensagem.setText("Seu acesso não altera o porteiro.")
            return
        pin, pin2 = self.pin.text(), self.pin2.text()
        if pin or pin2:
            if pin != pin2:
                self.mensagem.setText("Os PINs não conferem.")
                return
            if not pin.strip().isdigit() or not 4 <= len(pin.strip()) <= 8:
                self.mensagem.setText("O PIN do porteiro precisa ter de 4 a 8 números.")
                return
        elif self.ativo.isChecked() and not (self.ctx.banco.cfg("porteiro_pin_hash") or "").strip():
            self.mensagem.setText("Defina um PIN de 4 a 8 números.")
            return
        try:
            self.ctx.config.salvar_config({
                "porteiro_ativo": "S" if self.ativo.isChecked() else "N",
                "porteiro_porta": self.porta.text().strip() or str(PORTA_PADRAO),
            })
            if pin:
                definir_pin(self.ctx.banco, pin)
        except ErroNegocio as exc:
            self.mensagem.setText(str(exc))
            return
        self.pin.clear()
        self.pin2.clear()
        self._mostrar_endereco()
        self.mensagem.setText("Salvo. Com o programa aberto no caixa, o celular entra por este endereço.")

    def copiar(self) -> None:
        if not self._url:
            self.mensagem.setText("Ligue o porteiro e defina o PIN para ter o endereço.")
            return
        QApplication.clipboard().setText(self._url)
        self.mensagem.setText("Endereço copiado.")
