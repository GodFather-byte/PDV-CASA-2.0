"""Equipamentos Qt: configuração pelo controller e testes físicos confirmados."""
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from src.controllers.config_controller import CAMPOS_MAQUINA
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto


class JanelaMaquinas(QDialog):
    """Edita o terminal atual; abrir, recarregar e salvar não acionam hardware."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._exigir()
        self.campos = {}
        self._originais = {}
        self.setWindowTitle("Máquinas • Qt")
        self.resize(900, 720)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Máquinas e equipamentos", "titulo"))
        layout.addWidget(texto(
            "As alterações do equipamento podem exigir sair e entrar novamente. "
            "Salvar não imprime nem abre a gaveta. Os testes enviam comandos físicos "
            "e só ocorrem mediante confirmação; nenhuma instalação de driver é feita.",
            "aviso"))
        pagina = QWidget()
        formulario = QFormLayout(pagina)
        for campo in CAMPOS_MAQUINA:
            chave, rotulo, tipo = campo[:3]
            if tipo == "sn":
                editor = QCheckBox("Sim")
            elif tipo == "escolha":
                editor = QComboBox()
                for valor, descricao in campo[3]:
                    editor.addItem(descricao, valor)
            else:
                editor = QLineEdit()
                editor.setReadOnly(chave == "terminal")
            editor.setObjectName(chave)
            self.campos[chave] = editor
            formulario.addRow(rotulo, editor)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(pagina)
        layout.addWidget(rolagem)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        barra = QHBoxLayout()
        self.btn_salvar = QPushButton("Salvar")
        self.btn_recarregar = QPushButton("Descartar alterações")
        self.btn_teste = QPushButton("Imprimir página de teste")
        self.btn_gaveta = QPushButton("Testar abertura da gaveta")
        self._botoes = (self.btn_salvar, self.btn_recarregar,
                        self.btn_teste, self.btn_gaveta)
        for botao, acao in zip(self._botoes, (
                self.salvar, self.recarregar, self.testar_impressao, self.testar_gaveta)):
            botao.clicked.connect(acao)
            barra.addWidget(botao)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        barra.addWidget(fechar)
        layout.addLayout(barra)
        self._carregar()

    def _exigir(self):
        operador_id = self.ctx.operador_id
        if operador_id is None:
            raise ErroPermissao("Entre novamente para configurar as máquinas.")
        cadastro = self.ctx.cadastros.obter("operadores", operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        operador = self.ctx.acesso.operador(operador_id)
        self.ctx.acesso.exigir(operador, "cfg_maquinas")
        return operador_id

    def _autorizar(self):
        try:
            operador_id = self._exigir()
        except ErroPermissao:
            for editor in self.campos.values():
                editor.setEnabled(False)
                self._definir(editor, None)
            for botao in self._botoes:
                botao.setEnabled(False)
            self._originais = {}
            raise
        for editor in self.campos.values():
            editor.setEnabled(True)
        for botao in self._botoes:
            botao.setEnabled(True)
        if not self._originais:
            self._carregar()
        return operador_id

    @staticmethod
    def _definir(editor, valor):
        if isinstance(editor, QCheckBox):
            editor.setChecked(str(valor).upper() in ("S", "1", "SIM", "TRUE"))
        elif isinstance(editor, QComboBox):
            editor.setCurrentIndex(editor.findData(valor))
        else:
            editor.setText("" if valor is None else str(valor))

    def _valores(self):
        valores = {}
        for chave, editor in self.campos.items():
            if isinstance(editor, QCheckBox):
                valores[chave] = "S" if editor.isChecked() else "N"
            elif isinstance(editor, QComboBox):
                valores[chave] = editor.currentData()
            else:
                valores[chave] = editor.text()
        return valores

    def _carregar(self):
        dados = self.ctx.config.maquina()
        for chave, editor in self.campos.items():
            self._definir(editor, dados.get(chave))
        self._originais = self._valores()

    def showEvent(self, evento):
        super().showEvent(evento)
        try:
            self.exigir_acesso()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def exigir_acesso(self):
        """Revalida cfg_maquinas; preserva a edição quando o acesso permanece."""
        return self._autorizar()

    def recarregar(self):
        try:
            self._autorizar()
            self._carregar()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        self.mensagem.setText("Alterações não salvas descartadas.")
        return True

    def _salvar(self):
        valores = self._valores()
        for campo in CAMPOS_MAQUINA:
            if campo[2] == "escolha" and valores[campo[0]] not in dict(campo[3]):
                raise ErroNegocio(f"Escolha uma opção válida para {campo[1]}.")
        alterados = {k: v for k, v in valores.items()
                     if k != "terminal" and v != self._originais[k]}
        if alterados:
            self.ctx.config.salvar_maquina(alterados)
        self._carregar()

    def salvar(self):
        try:
            self._autorizar()
            self._salvar()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        self.mensagem.setText("Configurações salvas. Nenhum equipamento foi acionado.")
        return True

    def _testar(self, gaveta=False):
        try:
            operador_id = self._autorizar()
            acao = "abrir fisicamente a gaveta" if gaveta else "imprimir uma página física"
            resposta = QMessageBox.question(
                self, "Confirmar teste físico",
                f"Este teste vai {acao} no equipamento configurado. "
                "As alterações deste formulário serão salvas antes do envio. "
                "Confira conexões, papel e segurança do local. Continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            atual = self._autorizar()
            if resposta != QMessageBox.StandardButton.Yes:
                return False
            if atual != operador_id:
                raise ErroPermissao("A sessão mudou. Confirme novamente o teste.")
            self._salvar()
            self._autorizar()
            if gaveta:
                self.ctx.impressao.abrir_gaveta()
            else:
                self.ctx.impressao.imprimir_teste()
        except (ErroNegocio, OSError) as erro:
            self.mensagem.setText(str(erro))
            return False
        self.mensagem.setText(
            "Envio solicitado. Confira a abertura física da gaveta." if gaveta else
            "Envio solicitado. Confira se o papel realmente saiu.")
        return True

    def testar_impressao(self):
        return self._testar()

    def testar_gaveta(self):
        return self._testar(gaveta=True)
