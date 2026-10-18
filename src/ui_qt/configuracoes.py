"""Configurações Qt pelos mesmos campos e validações do controlador.

JanelaConfiguracoes(ctx, parent) usa as APIs do ConfigController e os acessos
cfg_loja/cfg_configuracoes. Cada aba grava separadamente, apenas alterações.
Equipamentos, acessos e Telegram possuem janelas próprias.
"""
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from src.controllers.config_controller import CAMPOS_CONFIG, CAMPOS_LOJA
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto


CHAVES_LOJA = tuple(c[0] for c in CAMPOS_LOJA)
CHAVES_PREFERENCIAS = (
    "posicao_padrao", "tempo_inatividade_min", "pergunta_pessoas",
    "painel_mesas_fixo", "painel_mostra_garotas",
)
SECOES = ("loja", "preferencias", "parametros", "nuvem")
MODULOS = {secao: "cfg_loja" if secao == "loja" else "cfg_configuracoes"
           for secao in SECOES}
CAMPOS = {
    "loja": tuple(CAMPOS_LOJA),
    "preferencias": tuple(c for c in CAMPOS_CONFIG if c[0] in CHAVES_PREFERENCIAS),
    "parametros": tuple(c for c in CAMPOS_CONFIG
                        if c[0] not in CHAVES_PREFERENCIAS and c[3] not in ("Nuvem", "Telegram")),
    "nuvem": tuple(c for c in CAMPOS_CONFIG if c[3] == "Nuvem"),
}


class JanelaConfiguracoes(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        permissoes = self._permissoes()
        if not any(permissoes.values()):
            raise ErroPermissao("Seu acesso não permite as configurações gerais.")
        self.campos = {secao: {} for secao in SECOES}
        self._originais = {secao: {} for secao in SECOES}
        self.setWindowTitle("Configurações gerais da loja • Qt")
        self.resize(850, 700)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Configurações gerais da loja", "titulo"))
        layout.addWidget(texto(
            "Cada aba salva somente suas alterações pelas regras existentes. "
            "Parâmetros incluem serviço, módulos e autorizações do caixa; revise antes de salvar. "
            "Reabra as telas operacionais para reler as configurações. Nuvem não inicia "
            "sincronização de vendas nem contrata serviços automaticamente.",
            "suave"))
        self.abas = QTabWidget()
        for secao, titulo in (("loja", "Identificação e contatos"),
                              ("preferencias", "Preferências de venda/caixa"),
                              ("parametros", "Parâmetros e módulos"),
                              ("nuvem", "Conexão com a nuvem")):
            pagina = QWidget()
            formulario = QFormLayout(pagina)
            formulario.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for campo in CAMPOS[secao]:
                chave, rotulo, tipo = campo[:3]
                if tipo == "sn":
                    editor = QCheckBox("Sim")
                elif tipo == "escolha":
                    editor = QComboBox()
                    for valor, descricao in campo[4]:
                        editor.addItem(descricao, valor)
                else:
                    # Texto também para inteiros: validação e limites são do controller.
                    editor = QLineEdit()
                    if chave == "api_token":
                        editor.setEchoMode(QLineEdit.EchoMode.Password)
                        editor.setPlaceholderText("Vazio mantém o token atual")
                self.campos[secao][chave] = editor
                formulario.addRow(rotulo, editor)
            if secao == "nuvem":
                self.apagar_token = QCheckBox("Apagar o token salvo ao salvar esta aba")
                formulario.addRow(self.apagar_token)
            rolagem = QScrollArea()
            rolagem.setWidgetResizable(True)
            rolagem.setWidget(pagina)
            self.abas.addTab(rolagem, titulo)
        layout.addWidget(self.abas)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        barra = QHBoxLayout()
        self.btn_salvar = QPushButton("Salvar esta aba")
        self.btn_recarregar = QPushButton("Descartar alterações desta aba")
        self.btn_salvar.clicked.connect(self.salvar)
        self.btn_recarregar.clicked.connect(self.recarregar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.close)
        for botao in (self.btn_salvar, self.btn_recarregar, fechar):
            barra.addWidget(botao)
        layout.addLayout(barra)
        self._aplicar_permissoes(permissoes)
        for secao in SECOES:
            if permissoes[secao]:
                self._carregar(secao)
        self.abas.setCurrentIndex(next(i for i, s in enumerate(SECOES) if permissoes[s]))
        self.abas.currentChanged.connect(self._trocar_aba)

    def _permissoes(self):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre novamente para acessar as configurações.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        operador = self.ctx.acesso.operador(self.ctx.operador_id)
        permissoes = {}
        for secao, modulo in MODULOS.items():
            try:
                self.ctx.acesso.exigir(operador, modulo)
            except ErroPermissao:
                permissoes[secao] = False
            else:
                permissoes[secao] = True
        return permissoes

    def _aplicar_permissoes(self, permissoes):
        for secao in SECOES:
            for editor in self.campos[secao].values():
                editor.setEnabled(permissoes[secao])
                if not permissoes[secao]:
                    self._definir(editor, None)
            if not permissoes[secao]:
                self._originais[secao] = {}
        self.btn_salvar.setEnabled(permissoes[SECOES[self.abas.currentIndex()]])
        self.apagar_token.setEnabled(permissoes["nuvem"])
        if not permissoes["nuvem"]:
            self.apagar_token.setChecked(False)

    def _autorizar(self, secao):
        try:
            permissoes = self._permissoes()
        except ErroPermissao:
            self._aplicar_permissoes(dict.fromkeys(SECOES, False))
            raise
        self._aplicar_permissoes(permissoes)
        if not permissoes[secao]:
            raise ErroPermissao("Seu acesso não permite esta aba de configurações.")
        if not self._originais[secao]:
            self._carregar(secao)

    def showEvent(self, evento):
        super().showEvent(evento)
        self._trocar_aba(self.abas.currentIndex())

    @staticmethod
    def _definir(editor, valor):
        if isinstance(editor, QCheckBox):
            editor.setChecked(str(valor).strip().upper() in ("S", "1", "SIM", "TRUE"))
        elif isinstance(editor, QComboBox):
            editor.setCurrentIndex(editor.findData(valor))
        else:
            editor.setText("" if valor is None else str(valor))

    def _valores(self, secao):
        valores = {}
        for campo in CAMPOS[secao]:
            chave = campo[0]
            editor = self.campos[secao][chave]
            if isinstance(editor, QCheckBox):
                valor = "S" if editor.isChecked() else "N"
            elif isinstance(editor, QComboBox):
                valor = editor.currentData()
            else:
                valor = editor.text()
            valores[chave] = valor
        return valores

    def _carregar(self, secao):
        carregar = self.ctx.config.loja if secao == "loja" else self.ctx.config.todas
        dados = carregar()
        for chave, editor in self.campos[secao].items():
            self._definir(editor, "" if chave == "api_token" else dados.get(chave))
        if secao == "nuvem":
            self.apagar_token.setChecked(False)
        # O retorno de todas() inclui segredos: nunca o conservamos na janela.
        self._originais[secao] = self._valores(secao)

    def _trocar_aba(self, _indice):
        try:
            self._autorizar(SECOES[self.abas.currentIndex()])
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
        else:
            self.mensagem.clear()

    def recarregar(self):
        secao = SECOES[self.abas.currentIndex()]
        try:
            self._autorizar(secao)
            self._carregar(secao)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        self.mensagem.setText("Aba recarregada; alterações não salvas foram descartadas.")
        return True

    def salvar(self):
        secao = SECOES[self.abas.currentIndex()]
        try:
            self._autorizar(secao)
            alterados = {k: v for k, v in self._valores(secao).items()
                         if v != self._originais[secao].get(k)}
            if secao == "nuvem" and self.apagar_token.isChecked():
                alterados["api_token"] = ""
            if not alterados:
                self.mensagem.setText("Nenhuma alteração nesta aba.")
                return True
            salvar = self.ctx.config.salvar_loja if secao == "loja" else self.ctx.config.salvar_config
            salvar(alterados)
            if "tema_visual" in alterados:
                from src.ui_qt import tema
                tema.aplicar(QApplication.instance(), self.ctx.banco.cfg("tema_visual"))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        # Normalizações são relidas do controller, não reproduzidas pela interface.
        if secao == "nuvem":
            self.campos["nuvem"]["api_token"].clear()
            self.apagar_token.setChecked(False)
        self._originais[secao] = self._valores(secao)
        try:
            self._carregar(secao)
        except ErroNegocio:
            self.mensagem.setText("Aba salva, mas não foi possível reler os valores. Recarregue a aba.")
            return True
        self.mensagem.setText("Configurações desta aba salvas.")
        return True

    def closeEvent(self, evento):
        self.campos["nuvem"]["api_token"].clear()
        super().closeEvent(evento)


class JanelaCadastroLoja(JanelaConfiguracoes):
    """Convite do primeiro uso; fechar adia para a próxima entrada, como no Tk."""

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._autorizar("loja")
        self.setWindowTitle("Cadastro inicial da casa")
        for indice in range(1, self.abas.count()):
            self.abas.setTabVisible(indice, False)
        self.abas.setCurrentIndex(0)
        self.btn_salvar.setText("Cadastrar a casa")
        self.mensagem.setText(
            "Informe o nome que sairá nos comprovantes. Fechar adia o cadastro para a próxima entrada.")

    def salvar(self):
        try:
            self._autorizar("loja")
            self.ctx.config.cadastrar_loja(self._valores("loja"))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        self.accept()
        return True
