"""Configurações Qt pelos mesmos campos e validações do controlador.

JanelaConfiguracoes(ctx, parent) usa as APIs do ConfigController e os acessos
cfg_loja/cfg_configuracoes. Cada aba grava separadamente, apenas alterações.
Equipamentos, acessos e Telegram possuem janelas próprias.
"""
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QInputDialog,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from src.controllers.config_controller import CAMPOS_CONFIG, CAMPOS_LOJA
from src.controllers.integracoes_controller import IntegracoesController
from src.core.erros import ErroNegocio, ErroPermissao
from src.sync import painel_envio
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


class _SinaisSenha(QObject):
    concluida = Signal(object, object)          # (senha gerada pela nuvem ou None, mensagem de erro ou None)


class _TrocaSenha(QRunnable):
    """A rede fora da thread da tela: recebe só cópias do endereço, do token e da senha."""

    def __init__(self, url, token, senha, sinais):
        super().__init__()
        self.url, self.token, self.senha, self.sinais = url, token, senha, sinais

    def run(self):
        try:
            gerada = painel_envio.trocar_senha_na_nuvem(self.url, self.token, self.senha)
        except ErroNegocio as erro:
            self.sinais.concluida.emit(None, str(erro))
        except Exception:
            self.sinais.concluida.emit(None, "Erro inesperado ao falar com a nuvem. A senha NÃO foi trocada.")
        else:
            self.sinais.concluida.emit(gerada, None)


class JanelaConfiguracoes(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._trocando_senha = False
        self._sinais_senha = _SinaisSenha()
        self._sinais_senha.concluida.connect(self._senha_trocada)
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
            if secao == "parametros":
                self.btn_integracoes = QPushButton("Pendências das integrações…")
                self.btn_integracoes.clicked.connect(self.mostrar_integracoes)
                formulario.addRow(self.btn_integracoes)
            if secao == "nuvem":
                self.apagar_token = QCheckBox("Apagar o token salvo ao salvar esta aba")
                formulario.addRow(self.apagar_token)
                self.btn_senha_painel = QPushButton("Trocar a senha do painel do dono…")
                self.btn_senha_painel.setToolTip(
                    "Muda a senha que o dono usa no celular (painel da nuvem). Usa o endereço e o token já salvos.")
                self.btn_senha_painel.clicked.connect(self.trocar_senha_painel)
                formulario.addRow(self.btn_senha_painel)
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
        self.btn_integracoes.setEnabled(permissoes["parametros"])
        self.btn_senha_painel.setEnabled(permissoes["nuvem"] and not self._trocando_senha)
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

    def mostrar_integracoes(self):
        try:
            self._autorizar("parametros")
            resumo = IntegracoesController(self.ctx.banco).resumo()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        QMessageBox.information(self, "Integrações — configuração salva", resumo)
        return True

    # ------------------------------------------------ senha do painel do dono
    def trocar_senha_painel(self):
        """O dono troca a senha do painel do celular pelo próprio PDV, sem depender do fornecedor. Endereço e token são os
        SALVOS (por isso exige a aba salva) e a rede roda em outra thread. Em branco, a nuvem gera a senha e ela aparece uma vez."""
        if self._trocando_senha:
            return False
        try:
            self._autorizar("nuvem")
            if self._valores("nuvem") != self._originais["nuvem"] or self.apagar_token.isChecked():
                raise ErroNegocio("Salve as alterações desta aba antes de trocar a senha do painel: o endereço e o token "
                                  "usados são os que estão salvos.")
            url, token = self.ctx.banco.cfg("api_url").strip(), self.ctx.banco.cfg("api_token").strip()
            if not url or not token:
                raise ErroNegocio("Preencha o endereço da nuvem e o token da API e salve a aba antes de trocar a senha do painel.")
            nova = self._pedir_senha_nova()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        if nova is None:
            return False
        self._trocando_senha = True
        self.btn_senha_painel.setEnabled(False)
        self.mensagem.setText("Trocando a senha na nuvem… isto pode levar alguns segundos.")
        QThreadPool.globalInstance().start(_TrocaSenha(url, token, nova or None, self._sinais_senha))
        return True

    def _pedir_senha_nova(self):
        """None = cancelou; "" = pediu para a nuvem gerar; senão a senha escolhida, já conferida."""
        senha, aceito = QInputDialog.getText(
            self, "Senha do painel do dono",
            f"Senha nova do painel (mínimo {painel_envio.SENHA_MINIMA} caracteres).\n"
            "Deixe em branco para a nuvem gerar uma:", QLineEdit.EchoMode.Password)
        if not aceito:
            return None
        senha = senha.strip()
        if not senha:
            return ""
        painel_envio.validar_senha(senha)
        repetida, aceito = QInputDialog.getText(
            self, "Senha do painel do dono", "Digite a senha nova de novo:", QLineEdit.EchoMode.Password)
        if not aceito:
            return None
        if repetida.strip() != senha:
            raise ErroNegocio("As senhas não conferem.")
        return senha

    @Slot(object, object)
    def _senha_trocada(self, gerada, erro):
        self._trocando_senha = False
        try:
            self._aplicar_permissoes(self._permissoes())
        except ErroNegocio:
            self._aplicar_permissoes(dict.fromkeys(SECOES, False))
        if erro is not None:
            self.mensagem.setText(erro)
            return
        painel_envio.registrar_troca_de_senha(self.ctx.banco, bool(gerada), self.ctx.operador_id)
        aviso = "O celular do dono precisa entrar de novo com a senha nova."
        if gerada:
            self.mensagem.setText("Senha do painel trocada (a nova aparece uma única vez).")
            QMessageBox.information(
                self, "Senha do painel do dono",
                f"Senha do painel trocada.\n\nA senha nova é:\n\n        {gerada}\n\nAnote agora: ela não aparece de novo. {aviso}")
        else:
            self.mensagem.setText(f"Senha do painel trocada. {aviso}")

    def reject(self):
        if self._trocando_senha:                 # a resposta da nuvem ainda vai chegar: não fecha antes de mostrá-la
            self.mensagem.setText("Aguarde a nuvem responder antes de fechar.")
            return
        super().reject()

    def closeEvent(self, evento):
        if self._trocando_senha:
            self.mensagem.setText("Aguarde a nuvem responder antes de fechar.")
            evento.ignore()
            return
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
