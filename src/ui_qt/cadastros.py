"""Cadastros Qt dirigidos pelas entidades e pelo CadastroController existentes."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from src.controllers.config_controller import modulos_desligados
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.core.relatorio import Coluna, Relatorio, para_csv, para_texto
from src.ui_qt.tema import texto


def exigir_acesso(ctx, chave):
    entidade = ctx.cadastros.entidade(chave)
    if ctx.operador is not None:
        cadastro = ctx.cadastros.obter("operadores", ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        ctx.operador = ctx.acesso.operador(ctx.operador_id)
    if ctx.operador is None or entidade.modulo in modulos_desligados(ctx.banco) or not ctx.pode(entidade.modulo):
        raise ErroPermissao("Seu acesso não permite este cadastro.")
    return entidade


class FormularioCadastro(QDialog):
    def __init__(self, ctx, chave, id_=None, parent=None):
        super().__init__(parent)
        self.ctx, self.chave, self.id_ = ctx, chave, id_
        self._operador_id = ctx.operador_id
        self.entidade = exigir_acesso(ctx, chave)
        self.setWindowTitle(("Novo • " if id_ is None else "Editar • ") + self.entidade.titulo)
        self.resize(620, 650)
        self.campos = {}
        linha = ctx.cadastros.obter(chave, id_) if id_ is not None else None
        valores = ctx.cadastros.exibir(chave, linha) if linha else ctx.cadastros.valores_iniciais(chave)
        layout = QVBoxLayout(self)
        abas = QTabWidget()
        secoes = {}
        for campo in self.entidade.campos:
            if campo.secao not in secoes:
                pagina = QWidget()
                formulario = QFormLayout(pagina)
                formulario.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                rolagem = QScrollArea()
                rolagem.setWidgetResizable(True)
                rolagem.setWidget(pagina)
                abas.addTab(rolagem, campo.secao)
                secoes[campo.secao] = formulario
            valor = valores.get(campo.nome, "")
            if campo.tipo == "sn":
                editor = QCheckBox("Sim")
                editor.setChecked(str(valor).upper() in ("S", "1", "SIM"))
            elif campo.tipo in ("lookup", "escolha"):
                editor = QComboBox()
                opcoes = (ctx.cadastros.opcoes(campo.lookup) if campo.tipo == "lookup" else campo.opcoes) or []
                editor.addItem("Selecione…", None)
                for identificador, rotulo in opcoes:
                    editor.addItem(str(rotulo), identificador)
                bruto = (linha or {}).get(campo.nome, campo.padrao)
                indice = editor.findData(bruto)
                editor.setCurrentIndex(max(indice, 0))
            else:
                editor = QLineEdit(str(valor or ""))
                if campo.tipo == "senha":
                    editor.setEchoMode(QLineEdit.EchoMode.Password)
                    if id_ is not None:
                        editor.setPlaceholderText("Em branco mantém a senha")
                if campo.tamanho:
                    editor.setMaxLength(campo.tamanho)
                if campo.tipo == "dinheiro":
                    editor.setPlaceholderText("0,00")
            editor.setEnabled(not campo.somente_leitura)
            self.campos[campo.nome] = editor
            secoes[campo.secao].addRow(campo.rotulo + (" *" if campo.obrigatorio else ""), editor)
        layout.addWidget(abas)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        botoes = QDialogButtonBox()
        botoes.addButton("Salvar", QDialogButtonBox.ButtonRole.AcceptRole)
        botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.salvar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def valores(self):
        dados = {}
        for campo in self.entidade.campos:
            if campo.somente_leitura:
                continue
            editor = self.campos[campo.nome]
            if isinstance(editor, QCheckBox):
                dados[campo.nome] = editor.isChecked()
            elif isinstance(editor, QComboBox):
                dados[campo.nome] = editor.currentData()
            else:
                dados[campo.nome] = editor.text()
        return dados

    def exigir_acesso(self):
        if self.ctx.operador_id != self._operador_id:
            raise ErroPermissao("A sessão mudou. Abra o formulário novamente.")
        return exigir_acesso(self.ctx, self.chave)

    def salvar(self):
        try:
            self.exigir_acesso()
            self.id_ = self.ctx.cadastros.salvar(self.chave, self.valores(), self.id_)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return
        for campo in self.entidade.campos:
            if campo.tipo == "senha":
                self.campos[campo.nome].clear()
        self.accept()


class FormularioEmbalagem(QDialog):
    def __init__(self, ctx, unitario_id, parent=None):
        super().__init__(parent)
        exigir_acesso(ctx, "produtos")
        self.ctx, self.unitario_id = ctx, unitario_id
        self.id_ = None
        produto = ctx.produtos.por_id(unitario_id)
        if produto is None:
            raise ErroNegocio("Produto não encontrado.")
        self.setWindowTitle("Criar fardo / caixa fechada")
        self.resize(560, 320)
        layout = QVBoxLayout(self)
        layout.addWidget(texto(f"Embalagem de: {produto['nome']}", "titulo"))
        layout.addWidget(texto("Vender 1 fardo ou caixa baixa do estoque as unidades deste produto."))
        formulario = QFormLayout()
        self.quantidade = QLineEdit("12")
        self.nome = QLineEdit(f"{produto['nome']} - FARDO")
        self.nome.setMaxLength(50)
        self.preco = QLineEdit()
        self.preco.setPlaceholderText("0,00")
        self.cbarra = QLineEdit()
        self.cbarra.setMaxLength(14)
        for rotulo, editor in (
            ("Unidades no fardo/caixa *", self.quantidade), ("Nome *", self.nome),
            ("Preço do fardo/caixa (R$) *", self.preco), ("Código de barras da embalagem", self.cbarra),
        ):
            formulario.addRow(rotulo, editor)
        layout.addLayout(formulario)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        botoes = QDialogButtonBox()
        botoes.addButton("Criar fardo", QDialogButtonBox.ButtonRole.AcceptRole)
        botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.salvar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def salvar(self):
        try:
            exigir_acesso(self.ctx, "produtos")
            quantidade = fmt.para_qtd(self.quantidade.text() or "0")
            preco = fmt.para_centavos(self.preco.text() or "0")
            self.id_ = self.ctx.produtos.criar_embalagem(
                self.unitario_id, quantidade, self.nome.text().strip(), preco,
                self.cbarra.text().strip() or None, self.ctx.operador_id)
        except ValueError:
            self.mensagem.setText("Quantidade ou preço inválidos.")
            return
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return
        self.accept()


class JanelaCadastro(QDialog):
    def __init__(self, ctx, chave, parent=None):
        super().__init__(parent)
        self.ctx, self.chave = ctx, chave
        self._operador_id = ctx.operador_id
        self.entidade = exigir_acesso(ctx, chave)
        self.filtros = {}
        self.apenas_ativos = False
        self.ordem = self.entidade.ordem
        self.setWindowTitle(self.entidade.titulo + " • Qt")
        self.resize(1000, 680)
        layout = QVBoxLayout(self)
        layout.addWidget(texto(self.entidade.titulo, "titulo"))
        barra = QHBoxLayout()
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Pesquisar e pressionar Enter")
        self.busca.returnPressed.connect(self.atualizar)
        barra.addWidget(self.busca, 1)
        for titulo, acao in (("Pesquisar", self.atualizar), ("Novo", self.novo),
                             ("Editar", self.editar), ("Excluir", self.excluir)):
            botao = QPushButton(titulo)
            botao.clicked.connect(acao)
            barra.addWidget(botao)
        if chave == "produtos":
            botao = QPushButton("Criar fardo")
            botao.clicked.connect(self.criar_embalagem)
            barra.addWidget(botao)
        layout.addLayout(barra)
        extras = QHBoxLayout()
        for rotulo, acao in (("Filtrar", self.filtrar), ("Ordenar", self.ordenar),
                              ("Visualizar / imprimir", self.visualizar),
                              ("Exportar CSV", lambda: self.exportar_csv())):
            botao = QPushButton(rotulo)
            botao.clicked.connect(acao)
            extras.addWidget(botao)
        if chave == "produtos":
            for rotulo, acao in (
                ("Tabela de preços", self.tabela_precos),
                ("Observações", lambda: self.abrir_cadastro_relacionado("observacoes")),
            ):
                botao = QPushButton(rotulo)
                botao.clicked.connect(acao)
                extras.addWidget(botao)
        elif chave == "clientes":
            botao = QPushButton("Gerar arquivo de clientes")
            botao.clicked.connect(lambda: self.gerar_clientes())
            extras.addWidget(botao)
        elif chave == "planos_contas":
            botao = QPushButton("Sub Planos")
            botao.clicked.connect(lambda: self.abrir_cadastro_relacionado("subplanos"))
            extras.addWidget(botao)
        layout.addLayout(extras)
        self.colunas = [c for c in self.entidade.campos if c.na_grade and c.tipo != "senha"]
        self.grade = QTableWidget(0, len(self.colunas))
        self.grade.setHorizontalHeaderLabels([c.rotulo for c in self.colunas])
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.setAlternatingRowColors(True)
        self.grade.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.grade.horizontalHeader().setStretchLastSection(True)
        self.grade.cellDoubleClicked.connect(lambda *_: self.editar())
        layout.addWidget(self.grade)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        self.atualizar()

    def exigir_acesso(self):
        if self.ctx.operador_id != self._operador_id:
            raise ErroPermissao("A sessão mudou. Abra o cadastro novamente.")
        return exigir_acesso(self.ctx, self.chave)

    def atualizar(self):
        try:
            selecionado = self.selecionado()
            linhas = self._listar()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            self.grade.setRowCount(0)
            return False
        self.grade.setRowCount(len(linhas))
        for numero, linha in enumerate(linhas):
            valores = self.ctx.cadastros.exibir(self.chave, linha)
            for coluna, campo in enumerate(self.colunas):
                item = QTableWidgetItem(valores.get(campo.nome, ""))
                item.setData(Qt.ItemDataRole.UserRole, linha["id"])
                self.grade.setItem(numero, coluna, item)
            if linha["id"] == selecionado:
                self.grade.selectRow(numero)
        ordem = ("padrão do cadastro" if self.ordem == self.entidade.ordem else "de cadastramento")
        self.mensagem.setText(
            f"{len(linhas)} registro(s). Ordem {ordem}; "
            f"{len(self.filtros)} filtro(s)" + ("; somente ativos." if self.apenas_ativos else "."))
        return True

    def _listar(self):
        self.exigir_acesso()
        return self.ctx.cadastros.listar(
            self.chave, self.busca.text(), ordem=self.ordem,
            apenas_ativos=self.apenas_ativos, filtros=self.filtros)

    def ordenar(self):
        try:
            self.exigir_acesso()
            self.ordem = "id" if self.ordem == self.entidade.ordem else self.entidade.ordem
            return self.atualizar()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False

    def aplicar_filtros(self, filtros, apenas_ativos=False):
        try:
            self.exigir_acesso()
            campos = {c.nome: c for c in self.entidade.campos if c.tipo == "lookup"}
            for nome, valor in filtros.items():
                if nome not in campos or valor not in dict(self.ctx.cadastros.opcoes(campos[nome].lookup)):
                    raise ErroNegocio("Filtro inválido para este cadastro.")
            self.filtros = dict(filtros)
            self.apenas_ativos = bool(apenas_ativos and self.entidade.tem_ativo)
            return self.atualizar()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False

    def filtrar(self):
        dialogo = None
        try:
            self.exigir_acesso()
            dialogo = QDialog(self)
            dialogo.setWindowTitle("Filtrar cadastro")
            layout = QVBoxLayout(dialogo)
            layout.addWidget(texto("Mostrar somente registros com:"))
            formulario = QFormLayout()
            combos = {}
            for campo in self.entidade.campos:
                if campo.tipo != "lookup":
                    continue
                combo = QComboBox()
                combo.addItem("Todos", None)
                for id_, rotulo in self.ctx.cadastros.opcoes(campo.lookup):
                    combo.addItem(str(rotulo), id_)
                combo.setCurrentIndex(max(0, combo.findData(self.filtros.get(campo.nome))))
                combos[campo.nome] = combo
                formulario.addRow(campo.rotulo, combo)
            layout.addLayout(formulario)
            ativos = QCheckBox("Somente ativos")
            ativos.setChecked(self.apenas_ativos)
            if self.entidade.tem_ativo:
                layout.addWidget(ativos)
            elif not combos:
                layout.addWidget(texto("Este cadastro não tem filtros. Use Pesquisar."))
            botoes = QDialogButtonBox()
            botoes.addButton("Aplicar", QDialogButtonBox.ButtonRole.AcceptRole)
            botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
            botoes.accepted.connect(dialogo.accept)
            botoes.rejected.connect(dialogo.reject)
            layout.addWidget(botoes)
            if dialogo.exec() != QDialog.DialogCode.Accepted:
                return False
            return self.aplicar_filtros(
                {nome: combo.currentData() for nome, combo in combos.items()
                 if combo.currentData() is not None}, ativos.isChecked())
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        finally:
            if dialogo is not None:
                dialogo.deleteLater()

    def _relatorio(self):
        linhas = self._listar()
        relatorio = Relatorio(self.entidade.titulo, [
            Coluna(c.rotulo, c.largura, "d" if c.tipo in ("dinheiro", "decimal", "int") else "e")
            for c in self.colunas])
        for linha in linhas:
            valores = self.ctx.cadastros.exibir(self.chave, linha)
            relatorio.add(*[valores.get(c.nome, "") for c in self.colunas])
        relatorio.rodape = [("Registros", str(len(linhas)))]
        return relatorio

    def _documento(self, titulo, conteudo, nome):
        from src.ui_qt.visualizador import JanelaVisualizador
        janela = JanelaVisualizador(
            self.ctx, titulo, conteudo, self, modulo=self.entidade.modulo, nome=nome)
        janela.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        janela.show()
        return janela

    def visualizar(self):
        try:
            relatorio = self._relatorio()
            return self._documento(relatorio.titulo, para_texto(relatorio, 100), self.chave)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return None

    def tabela_precos(self):
        try:
            self.exigir_acesso()
            if self.chave != "produtos":
                raise ErroNegocio("A tabela de preços pertence ao cadastro de produtos.")
            return self._documento("Tabela de preços", self.ctx.impressao.tabela_precos(), "tabela_precos")
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return None

    def abrir_cadastro_relacionado(self, chave):
        try:
            self.exigir_acesso()
            janela = JanelaCadastro(self.ctx, chave, self)
            janela.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            janela.show()
            return janela
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return None

    def _salvar_arquivo(self, caminho, nome, conteudo):
        self.exigir_acesso()
        if not caminho:
            caminho, _ = QFileDialog.getSaveFileName(
                self, "Exportar cadastro", nome, "Texto / CSV (*.txt *.csv)")
        if not caminho:
            return False
        self.exigir_acesso()
        with Path(caminho).open("w", encoding="utf-8-sig", newline="") as arquivo:
            arquivo.write(conteudo)
        self.mensagem.setText("Arquivo exportado. Nenhum dado foi enviado pela rede.")
        return True

    def exportar_csv(self, caminho=None):
        try:
            return self._salvar_arquivo(
                caminho, self.chave + ".csv", para_csv(self._relatorio()))
        except (ErroNegocio, OSError, ValueError) as erro:
            self.mensagem.setText(str(erro))
            return False

    def gerar_clientes(self, caminho=None):
        try:
            self.exigir_acesso()
            if self.chave != "clientes":
                raise ErroNegocio("A geração de clientes pertence ao cadastro de clientes.")
            campos = ("numero_consulta", "nome", "endereco", "complemento", "cep",
                      "cidade", "telefone", "rg", "cpf", "email", "obs")
            clientes = self.ctx.cadastros.listar("clientes", ordem="nome")
            linhas = [";".join(campos)]
            for cliente in clientes:
                linhas.append(";".join(
                    str(cliente.get(c) or "").replace(";", ",").replace("\r", " ").replace("\n", " ")
                    for c in campos))
            return self._salvar_arquivo(caminho, "clientes.txt", "\r\n".join(linhas) + "\r\n")
        except (ErroNegocio, OSError, ValueError) as erro:
            self.mensagem.setText(str(erro))
            return False

    def selecionado(self):
        linha = self.grade.currentRow()
        return self.grade.item(linha, 0).data(Qt.ItemDataRole.UserRole) if linha >= 0 else None

    def _formulario(self, id_=None):
        try:
            self.exigir_acesso()
            dialogo = FormularioCadastro(self.ctx, self.chave, id_, self)
            dialogo.exec()
            dialogo.deleteLater()
            self.atualizar()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def novo(self):
        self._formulario()

    def editar(self):
        id_ = self.selecionado()
        if id_ is not None:
            self._formulario(id_)

    def criar_embalagem(self):
        try:
            self.exigir_acesso()
            id_ = self.selecionado()
            if id_ is None:
                self.mensagem.setText("Selecione o produto unitário para criar o fardo ou a caixa.")
                return
            dialogo = FormularioEmbalagem(self.ctx, id_, self)
            try:
                if dialogo.exec() == QDialog.DialogCode.Accepted:
                    self.atualizar()
                    self.mensagem.setText("Fardo/caixa criado: vender 1 baixa as unidades do produto no estoque.")
            finally:
                dialogo.deleteLater()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def excluir(self):
        id_ = self.selecionado()
        if id_ is None:
            return
        try:
            self.exigir_acesso()
            if QMessageBox.question(self, "Excluir registro", "Excluir definitivamente o registro selecionado?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            self.exigir_acesso()
            mensagem = self.ctx.cadastros.excluir(self.chave, id_)
            self.atualizar()
            if mensagem:
                self.mensagem.setText(mensagem)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
