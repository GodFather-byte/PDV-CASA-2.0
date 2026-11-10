"""Assistente Qt dos primeiros passos: mostra o que falta na instalação e abre a tela certa de cada passo."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from src.controllers.perfil_controller import PERFIS, PerfilController
from src.controllers.primeiros_passos import PrimeirosPassos
from src.core.erros import ErroNegocio
from src.ui_qt.tema import texto

# chave do passo -> (texto do botão, acesso exigido). Passo sem entrada aqui é só informativo.
ACOES = {
    "loja": ("Cadastrar a casa", "cfg_loja"),
    "perfil": ("Escolher o tipo", "cfg_configuracoes"),
    "impressora": ("Abrir o assistente", "cfg_maquinas"),
    "produtos": ("Importar planilha", "cad_produtos"),
    "nuvem": ("Abrir a conexão", "cfg_configuracoes"),
    "backup": ("Configurar backup", "util_backup"),
}


class DialogoPerfil(QDialog):
    """Escolha do tipo de negócio, com a lista do que muda antes de aplicar."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Tipo de negócio")
        self.resize(620, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Que tipo de negócio é esta loja?", "titulo"))
        layout.addWidget(texto(
            "O tipo liga e desliga de uma vez os módulos do caixa. Preços, códigos e cadastros não mudam, "
            "e cada opção continua ajustável depois em Configurações.", "suave"))
        self.escolha = QComboBox()
        from src.core import edicao
        permitidos = edicao.atual().perfis
        for chave, (nome, _descricao, _valores) in PERFIS.items():
            if not permitidos or chave in permitidos:
                self.escolha.addItem(nome, chave)
        self.escolha.setCurrentIndex(self.escolha.findData(PerfilController(ctx.banco).atual()))
        self.escolha.currentIndexChanged.connect(self._mostrar)
        layout.addWidget(self.escolha)
        self.descricao = texto("")
        layout.addWidget(self.descricao)
        self.mudancas = texto("", "suave")
        self.mudancas.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setWidget(self.mudancas)
        layout.addWidget(rolagem, 1)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        barra = QHBoxLayout()
        self.btn_aplicar = QPushButton("Aplicar este tipo")
        self.btn_aplicar.setObjectName("primario")
        self.btn_aplicar.clicked.connect(self.aplicar)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        barra.addWidget(self.btn_aplicar)
        barra.addWidget(cancelar)
        layout.addLayout(barra)
        self._mostrar()

    def _mostrar(self, *_):
        perfil = self.escolha.currentData()
        self.descricao.setText(PERFIS[perfil][1].capitalize() + ".")
        mudancas = PerfilController(self.ctx.banco).mudancas(perfil)
        self.mudancas.setText(
            "O que muda ao aplicar:\n" + "\n".join(f"• {m['item']}: {m['de']} → {m['para']}" for m in mudancas)
            if mudancas else "Nada muda: a loja já está configurada assim.")

    def aplicar(self):
        try:
            if not self.ctx.pode("cfg_configuracoes"):
                raise ErroNegocio("Seu acesso não permite mudar o tipo de negócio.")
            PrimeirosPassos(self.ctx.banco, self.ctx.operador_id).escolher_perfil(self.escolha.currentData())
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return
        self.accept()


class JanelaPrimeirosPassos(QDialog):
    """Lista de conferência da instalação. `principal` é a janela que sabe abrir cada tela."""

    def __init__(self, ctx, principal=None, parent=None):
        super().__init__(parent or principal)
        self.ctx, self.principal = ctx, principal
        self.passos = PrimeirosPassos(ctx.banco, ctx.operador_id)
        self.setWindowTitle("Primeiros passos")
        self.resize(760, 640)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Primeiros passos da loja", "titulo"))
        self.resumo = texto("", "suave")
        layout.addWidget(self.resumo)
        self.progresso = QProgressBar()
        self.progresso.setTextVisible(False)
        self.progresso.setFixedHeight(10)
        layout.addWidget(self.progresso)
        self.lista = QVBoxLayout()
        self.lista.setSpacing(8)
        miolo = QWidget()
        miolo.setLayout(self.lista)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setWidget(miolo)
        layout.addWidget(rolagem, 1)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        barra = QHBoxLayout()
        self.btn_atualizar = QPushButton("Conferir de novo")
        self.btn_atualizar.clicked.connect(self.atualizar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.close)
        barra.addWidget(self.btn_atualizar)
        barra.addWidget(fechar)
        layout.addLayout(barra)
        self.botoes = {}
        self.atualizar()

    def atualizar(self):
        while self.lista.count():
            item = self.lista.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.botoes = {}
        for passo in self.passos.passos():
            self.lista.addWidget(self._cartao(passo))
        self.lista.addStretch(1)
        resumo = self.passos.resumo()
        self.progresso.setMaximum(resumo["total"])
        self.progresso.setValue(resumo["feitos"])
        self.resumo.setText(
            "Tudo pronto. Esta loja está instalada por completo." if resumo["concluido"]
            else f"{resumo['feitos']} de {resumo['total']} passos prontos. Dá para vender antes de terminar; "
                 "volte aqui quando quiser pelo menu Configuração.")

    def _cartao(self, passo):
        cartao = QFrame()
        cartao.setObjectName("cartao")
        linha = QHBoxLayout(cartao)
        marca = texto("✔" if passo["feito"] else "○", "kpi_valor" if passo["feito"] else "kpi_alerta", quebra=False)
        marca.setFixedWidth(34)
        linha.addWidget(marca, 0, Qt.AlignmentFlag.AlignTop)
        coluna = QVBoxLayout()
        coluna.addWidget(texto(passo["titulo"], "secao"))
        coluna.addWidget(texto(passo["detalhe"], "suave"))
        linha.addLayout(coluna, 1)
        acao = ACOES.get(passo["chave"])
        if acao is not None:
            rotulo, modulo = acao
            botao = QPushButton(rotulo if not passo["feito"] else "Rever")
            if not passo["feito"]:
                botao.setObjectName("primario")
            botao.setEnabled(self.principal is not None and self.ctx.pode(modulo))
            if not botao.isEnabled() and self.principal is not None:
                botao.setToolTip("Seu acesso não permite este passo.")
            botao.clicked.connect(lambda _=False, chave=passo["chave"]: self.abrir(chave))
            linha.addWidget(botao, 0, Qt.AlignmentFlag.AlignVCenter)
            self.botoes[passo["chave"]] = botao
        return cartao

    def abrir(self, chave):
        """Abre a tela do passo. As telas ficam por cima; ao voltar para cá a lista se confere sozinha."""
        self.mensagem.setText("")
        p = self.principal
        if p is None:
            return None
        if chave == "perfil":
            dialogo = DialogoPerfil(self.ctx, self)
            dialogo.exec()
            self.atualizar()
            p.atualizar()
            return dialogo
        if chave == "loja":
            janela = p.oferecer_cadastro_loja() or p.abrir_configuracoes()
        elif chave == "impressora":
            janela = p.abrir_assistente_impressora()
        elif chave == "produtos":
            janela = p.abrir_importacao_produtos()
        elif chave == "backup":
            janela = p.abrir_backup()
        else:                                           # nuvem: Configurações já na aba da conexão
            janela = p.abrir_configuracoes()
            if janela is not None:
                from src.ui_qt.configuracoes import SECOES
                janela.abas.setCurrentIndex(SECOES.index("nuvem"))
        if janela is None and p.mensagem.text():
            self.mensagem.setText(p.mensagem.text())
        return janela

    def changeEvent(self, evento):
        if evento.type() == QEvent.Type.ActivationChange and self.isVisible() and self.isActiveWindow():
            try:
                self.atualizar()
            except Exception:  # noqa: BLE001 - conferir de novo nunca pode derrubar a janela (banco fechando, por exemplo)
                pass
        super().changeEvent(evento)
