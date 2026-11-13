"""Produtos prontos (catálogo de adega) e vínculo de código de barras pelo leitor. As regras ficam em CatalogoController."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers.catalogo import SUBGRUPOS, CatalogoController
from src.controllers.config_controller import modulos_desligados
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao, ErroValidacao
from src.ui_qt.tema import texto

TODOS = "Todos"


def exigir_cadastro_produtos(ctx) -> None:
    if ctx.operador is None:
        raise ErroPermissao("Entre no sistema para cadastrar produtos.")
    cadastro = ctx.cadastros.obter("operadores", ctx.operador_id)
    if cadastro is None or not cadastro["ativo"]:
        raise ErroPermissao("Operador inativo. Encerre a sessão.")
    ctx.operador = ctx.acesso.operador(ctx.operador_id)
    entidade = ctx.cadastros.entidade("produtos")
    if entidade.modulo in modulos_desligados(ctx.banco):
        raise ErroPermissao("O cadastro de produtos está desativado.")
    ctx.acesso.exigir(ctx.operador, entidade.modulo)


class JanelaCatalogo(QDialog):
    """Marque o que a loja vende, digite o preço e adicione. Itens já cadastrados aparecem, mas não podem ser marcados."""

    COL_PRODUTO, COL_SUBGRUPO, COL_PRECO = 0, 1, 2

    def __init__(self, ctx, parent=None, ao_adicionar=None):
        super().__init__(parent)
        self.ctx = ctx
        self.ao_adicionar = ao_adicionar
        exigir_cadastro_produtos(ctx)
        self.setWindowTitle("Produtos prontos")
        self.resize(900, 640)
        self.escolhidos: dict[int, int] = {}          # índice do catálogo -> preço em centavos
        self._carregando = False
        layout = QVBoxLayout(self)
        titulo = texto("Produtos prontos de adega", "titulo")
        layout.addWidget(titulo)
        ajuda = texto("Digite o preço dos produtos que a loja vende: eles ficam marcados. Depois clique em "
                      "\"Adicionar\". Nome, subgrupo e NCM já vêm prontos. O código de barras você grava depois, "
                      "passando o produto no leitor.", "aviso")
        ajuda.setWordWrap(True)
        layout.addWidget(ajuda)
        filtros = QHBoxLayout()
        self.cmb_subgrupo = QComboBox()
        self.cmb_subgrupo.addItems((TODOS, *SUBGRUPOS))
        self.cmb_subgrupo.currentIndexChanged.connect(self.atualizar)
        self.ent_busca = QLineEdit()
        self.ent_busca.setPlaceholderText("Procurar: skol, lata, whisky...")
        self.ent_busca.textChanged.connect(self.atualizar)
        filtros.addWidget(QLabel("Subgrupo:"))
        filtros.addWidget(self.cmb_subgrupo)
        filtros.addWidget(self.ent_busca, 1)
        layout.addLayout(filtros)
        self.tabela = QTableWidget(0, 3)
        self.tabela.setHorizontalHeaderLabels(("Produto", "Subgrupo", "Preço (R$)"))
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        cab = self.tabela.horizontalHeader()
        cab.setSectionResizeMode(self.COL_PRODUTO, QHeaderView.Stretch)
        cab.setSectionResizeMode(self.COL_SUBGRUPO, QHeaderView.ResizeToContents)
        self.tabela.setColumnWidth(self.COL_PRECO, 120)
        self.tabela.itemChanged.connect(self._preco_alterado)
        layout.addWidget(self.tabela, 1)
        self.mensagem = texto("", "aviso")
        self.mensagem.setWordWrap(True)
        layout.addWidget(self.mensagem)
        barra = QHBoxLayout()
        self.lbl_marcados = QLabel("")
        barra.addWidget(self.lbl_marcados, 1)
        self.btn_codigos = QPushButton("Gravar códigos de barras…")
        self.btn_codigos.clicked.connect(self.abrir_codigos)
        self.btn_adicionar = QPushButton("Adicionar")
        self.btn_adicionar.setObjectName("primario")
        self.btn_adicionar.clicked.connect(self.adicionar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        for botao in (self.btn_codigos, self.btn_adicionar, fechar):
            barra.addWidget(botao)
        layout.addLayout(barra)
        self.atualizar()

    def controlador(self) -> CatalogoController:
        return CatalogoController(self.ctx.banco, self.ctx.operador_id)

    def atualizar(self, *_):
        subgrupo = self.cmb_subgrupo.currentText()
        itens = self.controlador().itens(None if subgrupo == TODOS else subgrupo, self.ent_busca.text())
        self._carregando = True
        self.tabela.setRowCount(len(itens))
        for linha, item in enumerate(itens):
            nome = QTableWidgetItem(item["nome"] + ("   (já cadastrado)" if item["ja_cadastrado"] else ""))
            nome.setData(Qt.UserRole, item["indice"])
            sub = QTableWidgetItem(item["subgrupo"])
            preco_cent = self.escolhidos.get(item["indice"])
            preco = QTableWidgetItem(fmt.fmt_num(preco_cent) if preco_cent else "")
            preco.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            for celula in (nome, sub):
                celula.setFlags(celula.flags() & ~Qt.ItemIsEditable)
            if item["ja_cadastrado"]:
                preco.setFlags(preco.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsEnabled)
                nome.setFlags(nome.flags() & ~Qt.ItemIsEnabled)
            self.tabela.setItem(linha, self.COL_PRODUTO, nome)
            self.tabela.setItem(linha, self.COL_SUBGRUPO, sub)
            self.tabela.setItem(linha, self.COL_PRECO, preco)
        self._carregando = False
        self._contar()

    def _preco_alterado(self, celula: QTableWidgetItem):
        if self._carregando or celula.column() != self.COL_PRECO:
            return
        indice = self.tabela.item(celula.row(), self.COL_PRODUTO).data(Qt.UserRole)
        bruto = celula.text().strip()
        if not bruto:
            self.escolhidos.pop(indice, None)
            self._contar()
            return
        try:
            centavos = fmt.para_centavos(bruto)
        except ValueError:
            centavos = 0
        self._carregando = True
        if centavos > 0:
            self.escolhidos[indice] = centavos
            celula.setText(fmt.fmt_num(centavos))
            self.mensagem.setText("")
        else:
            self.escolhidos.pop(indice, None)
            celula.setText("")
            self.mensagem.setText(f"Preço inválido: '{bruto}'. Use, por exemplo, 7,50.")
        self._carregando = False
        self._contar()

    def _contar(self):
        n = len(self.escolhidos)
        self.lbl_marcados.setText(f"{n} produto(s) com preço, prontos para adicionar." if n else "Nenhum produto marcado.")
        self.btn_adicionar.setEnabled(bool(n))

    def adicionar(self):
        try:
            exigir_cadastro_produtos(self.ctx)
            resultado = self.controlador().adicionar(dict(self.escolhidos))
        except (ErroNegocio, ErroPermissao, ErroValidacao) as erro:
            self.mensagem.setText(str(erro))
            return False
        self.escolhidos.clear()
        partes = [f"{resultado['criados']} produto(s) cadastrado(s)."]
        if resultado["ja_tinha"]:
            partes.append(f"{resultado['ja_tinha']} já existia(m) e ficou(aram) como estava(m).")
        partes.append("Para gravar o código de barras, use \"Gravar códigos de barras\".")
        self.mensagem.setText(" ".join(partes))
        self.atualizar()
        if self.ao_adicionar:
            self.ao_adicionar()
        return True

    def abrir_codigos(self):
        try:
            exigir_cadastro_produtos(self.ctx)
        except ErroPermissao as erro:
            self.mensagem.setText(str(erro))
            return None
        janela = JanelaCodigosBarras(self.ctx, self)
        janela.show()
        return janela


class JanelaCodigosBarras(QDialog):
    """Escolha o produto na lista (ou procure pelo nome) e passe a embalagem no leitor: o código fica gravado."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Gravar códigos de barras")
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        ajuda = texto("1. Procure e clique no produto.  2. Passe a embalagem no leitor (ou digite o código e tecle "
                      "Enter). A lista mostra só os produtos ainda sem código.", "aviso")
        ajuda.setWordWrap(True)
        layout.addWidget(ajuda)
        self.ent_busca = QLineEdit()
        self.ent_busca.setPlaceholderText("Procurar produto pelo nome")
        self.ent_busca.textChanged.connect(self.atualizar)
        layout.addWidget(self.ent_busca)
        self.lista = QListWidget()
        self.lista.currentItemChanged.connect(lambda *_: self.ent_codigo.setFocus())
        layout.addWidget(self.lista, 1)
        linha = QHBoxLayout()
        linha.addWidget(QLabel("Código de barras:"))
        self.ent_codigo = QLineEdit()
        self.ent_codigo.setPlaceholderText("Passe o produto no leitor")
        self.ent_codigo.returnPressed.connect(self.gravar)
        linha.addWidget(self.ent_codigo, 1)
        layout.addLayout(linha)
        self.mensagem = texto("", "aviso")
        self.mensagem.setWordWrap(True)
        layout.addWidget(self.mensagem)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        layout.addWidget(fechar, 0, Qt.AlignRight)
        self.atualizar()

    def atualizar(self, *_):
        self.lista.clear()
        for produto in CatalogoController(self.ctx.banco, self.ctx.operador_id).sem_codigo_barras(self.ent_busca.text()):
            item = QListWidgetItem(produto["nome"])
            item.setData(Qt.UserRole, produto["id"])
            self.lista.addItem(item)
        if self.lista.count():
            self.lista.setCurrentRow(0)

    def gravar(self):
        item = self.lista.currentItem()
        if item is None:
            self.mensagem.setText("Escolha o produto na lista primeiro.")
            return False
        try:
            exigir_cadastro_produtos(self.ctx)
            CatalogoController(self.ctx.banco, self.ctx.operador_id).vincular_codigo_barras(
                item.data(Qt.UserRole), self.ent_codigo.text())
        except (ErroNegocio, ErroPermissao, ErroValidacao) as erro:
            self.mensagem.setText(str(erro))
            self.ent_codigo.selectAll()
            return False
        self.mensagem.setText(f"Gravado: {item.text()}.")
        self.ent_codigo.clear()
        self.atualizar()
        self.ent_busca.setFocus()
        self.ent_busca.selectAll()
        return True
