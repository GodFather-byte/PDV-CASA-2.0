"""Janela Qt independente para editar a ficha técnica de produtos."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from src.controllers.config_controller import modulos_desligados
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto


class JanelaComposicao(QDialog):
    """Edita relações de composição somente através dos controladores existentes."""

    MODULO = "cad_composicao"

    def __init__(self, ctx, produto_id: int | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._exigir_acesso()
        self.setWindowTitle("Composição / ficha técnica • Qt")
        self.resize(1000, 680)

        layout = QVBoxLayout(self)
        layout.addWidget(texto("Composição / ficha técnica", "titulo"))
        layout.addWidget(texto(
            "Informe cada quantidade na unidade cadastrada para o insumo. "
            "A tela não converte unidades nem altera estoque ou dados do produto.", "suave"))

        busca = QHBoxLayout()
        self.busca_produto = QLineEdit()
        self.busca_produto.setPlaceholderText("Pesquisar produto por nome, código ou atalho")
        self.busca_produto.returnPressed.connect(self.buscar_produto)
        busca.addWidget(self.busca_produto, 1)
        self.btn_buscar = QPushButton("Buscar produto")
        self.btn_buscar.clicked.connect(self.buscar_produto)
        busca.addWidget(self.btn_buscar)
        layout.addLayout(busca)

        formulario = QFormLayout()
        self.produto = QComboBox()
        self.produto.currentIndexChanged.connect(self.carregar)
        formulario.addRow("Produto que terá a composição", self.produto)
        self.insumo = QComboBox()
        self.insumo.currentIndexChanged.connect(self._atualizar_rotulo_quantidade)
        formulario.addRow("Insumo (ativo e marcado como compõe)", self.insumo)
        linha_qtd = QHBoxLayout()
        self.rotulo_qtd = texto("Quantidade", "suave", False)
        linha_qtd.addWidget(self.rotulo_qtd)
        self.quantidade = QLineEdit()
        self.quantidade.setPlaceholderText("Ex.: 0,1000")
        self.quantidade.returnPressed.connect(self.incluir)
        linha_qtd.addWidget(self.quantidade, 1)
        self.btn_incluir = QPushButton("Incluir composição")
        self.btn_incluir.clicked.connect(self.incluir)
        linha_qtd.addWidget(self.btn_incluir)
        formulario.addRow(linha_qtd)
        layout.addLayout(formulario)

        acoes = QHBoxLayout()
        self.btn_excluir = QPushButton("Excluir selecionada")
        self.btn_excluir.clicked.connect(self.excluir)
        acoes.addWidget(self.btn_excluir)
        self.custo = texto("", "suave")
        acoes.addWidget(self.custo, 1)
        layout.addLayout(acoes)

        self.grade = QTableWidget(0, 5)
        self.grade.setHorizontalHeaderLabels(
            ["Código", "Insumo", "Unidade", "Quantidade", "Custo"])
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.setAlternatingRowColors(True)
        self.grade.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.grade.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.grade, 1)

        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        layout.addWidget(fechar)
        QShortcut(QKeySequence("Escape"), self, activated=self.reject)

        self._preencher_produtos(self._produtos_ativos(), produto_id)
        self._atualizar_insumos()
        self.carregar()

    def _exigir_acesso(self):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre com um operador para editar composições.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        if self.MODULO in modulos_desligados(self.ctx.banco):
            raise ErroPermissao("O cadastro de composição está desativado.")
        self.ctx.acesso.exigir(self.ctx.operador, self.MODULO)

    def _produtos_ativos(self):
        return self.ctx.cadastros.listar("produtos", apenas_ativos=True)

    def _preencher_produtos(self, produtos, selecionar_id=None):
        self.produto.blockSignals(True)
        self.produto.clear()
        self.produto.addItem("Selecione um produto…", None)
        for p in produtos:
            self.produto.addItem(f"{p['codigo']} • {p['nome']}", p["id"])
        indice = self.produto.findData(selecionar_id) if selecionar_id is not None else 0
        self.produto.setCurrentIndex(max(indice, 0))
        self.produto.blockSignals(False)

    def buscar_produto(self):
        try:
            self._exigir_acesso()
            termo = self.busca_produto.text().strip()
            if not termo:
                achados = self._produtos_ativos()
            else:
                direto = self.ctx.produtos.buscar_codigo(termo, apenas_venda=False)
                achados = [direto] if direto else self.ctx.produtos.pesquisar(
                    termo, apenas_venda=False)
                ativos = []
                vistos = set()
                for produto in achados:
                    atual = self.ctx.cadastros.obter("produtos", produto["id"])
                    if atual and atual["ativo"] and produto["id"] not in vistos:
                        ativos.append(atual)
                        vistos.add(produto["id"])
                achados = ativos
            if not achados:
                self.mensagem.setText("Nenhum produto ativo encontrado.")
                return False
            selecionado = self.produto.currentData()
            if not any(p["id"] == selecionado for p in achados):
                selecionado = achados[0]["id"]
            self._preencher_produtos(achados, selecionado)
            self.carregar()
            self.mensagem.setText(f"{len(achados)} produto(s) encontrado(s).")
            return True
        except ErroNegocio as erro:
            self._erro(erro)
            return False

    def _atualizar_insumos(self, selecionar_id=None):
        unidades = {
            unidade["id"]: unidade["abreviatura"]
            for unidade in self.ctx.cadastros.listar("unidades")
        }
        insumos = [
            p for p in self._produtos_ativos()
            if p["compoe"]
        ]
        self.insumo.blockSignals(True)
        self.insumo.clear()
        self.insumo.addItem("Selecione um insumo…", None)
        for p in insumos:
            self.insumo.addItem(
                f"{p['codigo']} • {p['nome']} ({unidades.get(p['unidade_id'], '')})",
                p["id"])
        indice = self.insumo.findData(selecionar_id) if selecionar_id is not None else 0
        self.insumo.setCurrentIndex(max(indice, 0))
        self.insumo.blockSignals(False)
        self._atualizar_rotulo_quantidade()

    def _atualizar_rotulo_quantidade(self, _indice=None):
        insumo_id = self.insumo.currentData()
        unidade = ""
        if insumo_id is not None:
            insumo = self.ctx.cadastros.obter("produtos", int(insumo_id))
            if insumo:
                unidade = self.ctx.cadastros.obter(
                    "unidades", insumo["unidade_id"])["abreviatura"]
        self.rotulo_qtd.setText(f"Quantidade ({unidade})" if unidade else "Quantidade")

    def _produto_selecionado(self):
        produto_id = self.produto.currentData()
        if produto_id is None:
            return None
        produto = self.ctx.cadastros.obter("produtos", int(produto_id))
        if produto is None or not produto["ativo"]:
            raise ErroNegocio("Escolha um produto ativo.")
        return int(produto_id)

    def carregar(self, _indice=None):
        try:
            self._exigir_acesso()
            produto_id = self._produto_selecionado()
            if produto_id is None:
                self.grade.setRowCount(0)
                self.custo.clear()
                return True
            composicao = self.ctx.produtos.composicao(produto_id)
            self.grade.setRowCount(len(composicao))
            for linha, item in enumerate(composicao):
                valores = (
                    item["codigo"], item["nome"], item["unidade"],
                    fmt.fmt_qtd(item["quantidade"], 4),
                    fmt.fmt_brl(fmt.mult_cent(item["ult_preco_cent"], item["quantidade"])),
                )
                for coluna, valor in enumerate(valores):
                    celula = QTableWidgetItem(str(valor))
                    if coluna == 0:
                        celula.setData(Qt.ItemDataRole.UserRole, item["id"])
                    self.grade.setItem(linha, coluna, celula)
            self.custo.setText(f"Custo total: {fmt.fmt_brl(self.ctx.produtos.custo(produto_id))}")
            return True
        except ErroNegocio as erro:
            self.grade.setRowCount(0)
            self.custo.clear()
            self._erro(erro)
            return False

    def incluir(self):
        try:
            self._exigir_acesso()
            produto_id = self._produto_selecionado()
            insumo_id = self.insumo.currentData()
            if produto_id is None:
                raise ErroNegocio("Escolha o produto que terá a composição.")
            if insumo_id is None:
                raise ErroNegocio("Escolha um insumo ativo marcado como compõe.")
            insumo = self.ctx.cadastros.obter("produtos", int(insumo_id))
            if insumo is None or not insumo["ativo"] or not insumo["compoe"]:
                raise ErroNegocio("Escolha um insumo ativo marcado como compõe.")
            try:
                quantidade = fmt.para_qtd(self.quantidade.text())
            except ValueError:
                raise ErroNegocio("Quantidade inválida.") from None
            self.ctx.produtos.incluir_composicao(produto_id, int(insumo_id), quantidade)
            self.quantidade.clear()
            self._atualizar_insumos(int(insumo_id))
            self.carregar()
            self.mensagem.setText("Composição incluída.")
            return True
        except ErroNegocio as erro:
            self._erro(erro)
            return False

    def excluir(self):
        try:
            self._exigir_acesso()
            produto_id = self._produto_selecionado()
            linha = self.grade.currentRow()
            if produto_id is None or linha < 0 or self.grade.item(linha, 0) is None:
                self.mensagem.setText("Selecione uma composição para excluir.")
                return False
            composicao_id = self.grade.item(linha, 0).data(Qt.ItemDataRole.UserRole)
            if not any(c["id"] == composicao_id
                       for c in self.ctx.produtos.composicao(produto_id)):
                self.carregar()
                self.mensagem.setText("A composição selecionada não pertence mais a este produto.")
                return False
            resposta = QMessageBox.question(
                self, "Excluir composição", "Excluir o insumo selecionado da ficha técnica?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if resposta != QMessageBox.StandardButton.Yes:
                return False
            self._exigir_acesso()
            if self._produto_selecionado() != produto_id or not any(
                    c["id"] == composicao_id
                    for c in self.ctx.produtos.composicao(produto_id)):
                self.carregar()
                self.mensagem.setText("A composição selecionada não está mais disponível.")
                return False
            self.ctx.produtos.excluir_composicao(int(composicao_id))
            self.carregar()
            self.mensagem.setText("Composição excluída.")
            return True
        except ErroNegocio as erro:
            self._erro(erro)
            return False

    def _erro(self, erro):
        if isinstance(erro, ErroPermissao):
            self.grade.setRowCount(0)
            self.custo.clear()
        self.mensagem.setText(str(erro))
