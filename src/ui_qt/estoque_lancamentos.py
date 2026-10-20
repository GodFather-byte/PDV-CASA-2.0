"""Lista e edição operacional dos lançamentos de estoque no Qt."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QInputDialog, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers.estoque_controller import TIPOS
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto


LIMITE_LANCAMENTOS = 300


class JanelaLancamentosEstoque(QDialog):
    """Consulta lançamentos, adiciona/remove itens e confirma entregas de pedidos."""

    def __init__(self, ctx, parent=None, lancamento_id=None):
        super().__init__(parent)
        self.ctx = ctx
        self.lancamento_id = None
        self.lancamento = None
        self.itens = []
        self._exigir_acesso()
        self.setWindowTitle("Lançamentos de estoque")
        self.resize(1120, 760)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Lançamentos de estoque", "titulo"))
        layout.addWidget(texto(
            "Pedidos não alteram o saldo até a confirmação da entrega. "
            "Compras registram os custos em centavos.", "suave"))

        barra = QHBoxLayout()
        self.btn_novo = QPushButton("Novo lançamento")
        self.btn_novo.clicked.connect(self.novo)
        barra.addWidget(self.btn_novo)
        self.btn_atualizar = QPushButton("Atualizar (F5)")
        self.btn_atualizar.clicked.connect(self.atualizar)
        barra.addWidget(self.btn_atualizar)
        barra.addStretch(1)
        layout.addLayout(barra)

        self.grade_lancamentos = self._tabela(
            ["Data", "Tipo", "Fornecedor", "Documento", "Total dos itens"])
        self.grade_lancamentos.itemSelectionChanged.connect(self._selecionar_lancamento)
        layout.addWidget(self.grade_lancamentos, 1)

        self.formulario = QFormLayout()
        self.tipo = QComboBox()
        for chave, rotulo in TIPOS.items():
            self.tipo.addItem(rotulo, chave)
        self.tipo.currentIndexChanged.connect(
            lambda *_: self._habilitar_lancamento(self.lancamento_id is not None))
        self.fornecedor = QComboBox()
        self.descricao = QLineEdit()
        self.data = QLineEdit(fmt.fmt_data(fmt.hoje()))
        self.valor_nota = QLineEdit()
        self.documento = QLineEdit()
        self.nota_fiscal = QLineEdit()
        self.formulario.addRow("Tipo", self.tipo)
        self.formulario.addRow("Fornecedor", self.fornecedor)
        self.formulario.addRow("Descrição", self.descricao)
        self.formulario.addRow("Data (dd/mm/aaaa)", self.data)
        self.formulario.addRow("Valor da nota (R$)", self.valor_nota)
        self.formulario.addRow("Documento", self.documento)
        self.formulario.addRow("Nota fiscal", self.nota_fiscal)
        layout.addLayout(self.formulario)
        self.btn_iniciar = QPushButton("Lançar cabeçalho")
        self.btn_iniciar.clicked.connect(self.iniciar)
        layout.addWidget(self.btn_iniciar)

        layout.addWidget(texto("Itens do lançamento selecionado", "subtitulo"))
        self.grade_itens = self._tabela([
            "Código", "Produto", "Unidade", "Quantidade", "Preço unitário",
            "Desconto", "Total do item", "Diferença",
        ])
        self.grade_itens.itemSelectionChanged.connect(
            lambda: self.btn_remover.setEnabled(
                self.lancamento_id is not None
                and self.grade_itens.currentRow() >= 0))
        layout.addWidget(self.grade_itens, 2)

        item_form = QHBoxLayout()
        self.produto = QComboBox()
        self.produto.setEditable(True)
        self.produto.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.quantidade = QLineEdit()
        self.quantidade.setPlaceholderText("Quantidade")
        self.valor_item = QLineEdit()
        self.valor_item.setPlaceholderText("Valor total do item (R$)")
        self.desconto_item = QLineEdit()
        self.desconto_item.setPlaceholderText("Desconto (R$)")
        self.minimo_item = QLineEdit()
        self.minimo_item.setPlaceholderText("Estoque mínimo")
        for widget in (self.produto, self.quantidade, self.valor_item,
                       self.desconto_item, self.minimo_item):
            item_form.addWidget(widget)
        layout.addLayout(item_form)

        acoes = QHBoxLayout()
        self.btn_adicionar = QPushButton("Adicionar item")
        self.btn_adicionar.clicked.connect(self.adicionar_item)
        acoes.addWidget(self.btn_adicionar)
        self.btn_remover = QPushButton("Excluir item selecionado")
        self.btn_remover.clicked.connect(self.remover_item)
        acoes.addWidget(self.btn_remover)
        self.btn_excluir = QPushButton("Excluir lançamento")
        self.btn_excluir.clicked.connect(self.excluir_lancamento)
        acoes.addWidget(self.btn_excluir)
        self.btn_confirmar = QPushButton("Confirmar entrega do pedido")
        self.btn_confirmar.clicked.connect(self.confirmar_entrega)
        acoes.addWidget(self.btn_confirmar)
        layout.addLayout(acoes)

        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        layout.addWidget(fechar)

        self._carregar_opcoes()
        self._limpar_cabecalho()
        self._habilitar_lancamento(False)
        self.atualizar()
        if lancamento_id is not None:
            self.carregar(lancamento_id)

    @staticmethod
    def _tabela(cabecalhos):
        tabela = QTableWidget(0, len(cabecalhos))
        tabela.setHorizontalHeaderLabels(cabecalhos)
        tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabela.setAlternatingRowColors(True)
        tabela.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        tabela.horizontalHeader().setStretchLastSection(True)
        return tabela

    def _exigir_acesso(self):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre com um operador para acessar os lançamentos de estoque.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.acesso.exigir(
            self.ctx.acesso.operador(self.ctx.operador_id), "lanc_estoque")

    def _erro(self, erro):
        if isinstance(erro, ErroPermissao):
            self.lancamento_id = None
            self.lancamento = None
            self.itens = []
            self.grade_lancamentos.setRowCount(0)
            self.grade_itens.setRowCount(0)
            self._habilitar_lancamento(False)
        self.mensagem.setText(str(erro))
        return False

    def _carregar_opcoes(self):
        fornecedores = self.ctx.cadastros.opcoes("fornecedores")
        self.fornecedor.clear()
        self.fornecedor.addItem("", None)
        for identificador, rotulo in fornecedores:
            self.fornecedor.addItem(str(rotulo), identificador)
        produtos = self.ctx.cadastros.listar("produtos", apenas_ativos=True)
        self.produto.clear()
        for registro in produtos:
            self.produto.addItem(
                f"{registro['codigo']} • {registro['nome']}", registro["id"])

    def _limpar_cabecalho(self):
        self.tipo.setCurrentIndex(max(self.tipo.findData("compra"), 0))
        self.fornecedor.setCurrentIndex(0)
        self.descricao.setText(TIPOS["compra"])
        self.data.setText(fmt.fmt_data(fmt.hoje()))
        for campo in (self.valor_nota, self.documento, self.nota_fiscal):
            campo.clear()

    def _habilitar_lancamento(self, existe):
        tipo = self.tipo.currentData()
        self.tipo.setEnabled(not existe)
        self.fornecedor.setEnabled(not existe)
        self.descricao.setEnabled(not existe)
        self.data.setEnabled(not existe)
        compra = tipo == "compra"
        self.valor_nota.setEnabled(not existe and compra)
        self.documento.setEnabled(not existe)
        self.nota_fiscal.setEnabled(not existe)
        self.btn_iniciar.setEnabled(not existe)
        self.produto.setEnabled(existe)
        self.quantidade.setEnabled(existe)
        self.valor_item.setEnabled(existe and compra)
        self.desconto_item.setEnabled(existe and compra)
        self.minimo_item.setEnabled(existe and tipo == "inicial")
        self.btn_adicionar.setEnabled(existe)
        self.btn_remover.setEnabled(existe and self.grade_itens.currentRow() >= 0)
        self.btn_excluir.setEnabled(existe)
        self.btn_confirmar.setEnabled(
            existe and self.lancamento is not None
            and self.lancamento["tipo"] == "pedido")

    def novo(self):
        try:
            self._exigir_acesso()
        except ErroNegocio as erro:
            return self._erro(erro)
        self.lancamento_id = None
        self.lancamento = None
        self.itens = []
        self.grade_itens.setRowCount(0)
        self._limpar_cabecalho()
        self._habilitar_lancamento(False)
        self.mensagem.setText("Preencha os dados e lance o cabeçalho.")
        return True

    def atualizar(self):
        try:
            self._exigir_acesso()
            controlador = self.ctx.estoque
            todos = controlador.lancamentos()
            registros = todos[:LIMITE_LANCAMENTOS]
        except ErroNegocio as erro:
            return self._erro(erro)
        selecionado = self.lancamento_id
        self.grade_lancamentos.blockSignals(True)
        try:
            self.grade_lancamentos.setRowCount(len(registros))
            for linha, registro in enumerate(registros):
                valores = (
                    fmt.fmt_data(registro["data"]), TIPOS[registro["tipo_perda"] or registro["tipo"]],
                    registro["fornecedor"] or "", registro["documento"] or "",
                    fmt.fmt_brl(registro["total_itens"]),
                )
                for coluna, valor in enumerate(valores):
                    item = QTableWidgetItem(str(valor))
                    if coluna == 0:
                        item.setData(Qt.ItemDataRole.UserRole, registro["id"])
                    self.grade_lancamentos.setItem(linha, coluna, item)
            if selecionado is not None:
                for linha, registro in enumerate(registros):
                    if registro["id"] == selecionado:
                        self.grade_lancamentos.selectRow(linha)
                        break
        finally:
            self.grade_lancamentos.blockSignals(False)
        self.mensagem.setText(
            f"Mostrando os {len(registros)} lançamentos mais recentes de "
            f"{len(todos)}." if len(todos) > len(registros) else
            f"{len(registros)} lançamento(s).")
        return True

    def _selecionar_lancamento(self):
        linha = self.grade_lancamentos.currentRow()
        if linha < 0:
            return
        item = self.grade_lancamentos.item(linha, 0)
        if item is not None:
            self.carregar(item.data(Qt.ItemDataRole.UserRole))

    def carregar(self, lancamento_id):
        try:
            self._exigir_acesso()
            controlador = self.ctx.estoque
            lancamento = controlador.lancamento(lancamento_id)
            itens = controlador.itens(lancamento_id)
        except ErroNegocio as erro:
            return self._erro(erro)
        self.lancamento_id = lancamento_id
        self.lancamento = lancamento
        self.tipo.setCurrentIndex(max(self.tipo.findData(lancamento["tipo_perda"] or lancamento["tipo"]), 0))
        indice = self.fornecedor.findData(lancamento["fornecedor_id"])
        self.fornecedor.setCurrentIndex(max(indice, 0))
        self.descricao.setText(lancamento["descricao"] or "")
        self.data.setText(fmt.fmt_data(lancamento["data"]))
        self.valor_nota.setText(fmt.fmt_num(lancamento["valor_cent"]))
        self.documento.setText(lancamento["documento"] or "")
        self.nota_fiscal.setText(lancamento["nota_fiscal"] or "")
        self.itens = itens
        self._preencher_itens()
        self._habilitar_lancamento(True)
        self.mensagem.setText(
            f"Lançamento {lancamento_id} • total dos itens: "
            f"{fmt.fmt_brl(controlador.total_itens(lancamento_id))}.")
        return True

    def iniciar(self):
        try:
            self._exigir_acesso()
            tipo = self.tipo.currentData()
            try:
                valor_nota = (fmt.para_centavos(self.valor_nota.text())
                              if tipo == "compra" and self.valor_nota.text().strip()
                              else 0)
            except ValueError:
                raise ErroNegocio("Valor da nota inválido.")
            lancamento_id = self.ctx.estoque.criar_lancamento(
                tipo, self.data.text(), self.descricao.text(),
                self.documento.text() or None, self.nota_fiscal.text() or None,
                self.fornecedor.currentData(), valor_nota)
            self.atualizar()
            return self.carregar(lancamento_id)
        except ErroNegocio as erro:
            return self._erro(erro)

    def _produto_selecionado(self):
        identificador = self.produto.currentData()
        if identificador is not None:
            return identificador
        texto_produto = self.produto.currentText().strip()
        for registro in self.ctx.cadastros.listar(
                "produtos", texto=texto_produto, apenas_ativos=True):
            if registro["nome"].casefold() == texto_produto.casefold():
                return registro["id"]
        return None

    def adicionar_item(self):
        if self.lancamento_id is None:
            return False
        try:
            self._exigir_acesso()
            produto_id = self._produto_selecionado()
            if produto_id is None:
                raise ErroNegocio("Escolha um produto ativo.")
            try:
                quantidade = fmt.para_qtd(self.quantidade.text())
                valor = (fmt.para_centavos(self.valor_item.text())
                         if self.valor_item.text().strip() else 0)
                desconto = (fmt.para_centavos(self.desconto_item.text())
                            if self.desconto_item.text().strip() else 0)
                minimo = (fmt.para_qtd(self.minimo_item.text())
                          if self.minimo_item.text().strip() else None)
            except ValueError:
                raise ErroNegocio("Quantidade ou valor inválido.")
            produto = self.ctx.produtos.por_id(produto_id)
            tipo = self.lancamento["tipo"]
            ligar = False
            if (produto is not None and not produto["controla_estoque"]
                    and tipo in ("compra", "entrada", "contagem")):
                resposta = QMessageBox.question(
                    self, "Controlar estoque",
                    f"'{produto['nome']}' ainda não controla estoque.\n"
                    f"Ligar o controle de estoque deste produto e lançar "
                    f"{fmt.fmt_qtd(quantidade)}?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                self._exigir_acesso()
                if resposta != QMessageBox.StandardButton.Yes:
                    return False
                ligar = True
            self.ctx.estoque.adicionar_item(
                self.lancamento_id, produto_id, quantidade, valor, desconto,
                minimo, ligar, self.descricao.text().strip() or None
                if self.tipo.currentData() in ("quebra", "oxidacao", "devolucao") else None)
            self.quantidade.clear()
            self.valor_item.clear()
            self.desconto_item.clear()
            self.minimo_item.clear()
            self._carregar_opcoes()
            self.atualizar()
            return self.carregar(self.lancamento_id)
        except ErroNegocio as erro:
            return self._erro(erro)

    def _preencher_itens(self):
        self.grade_itens.setRowCount(len(self.itens))
        for linha, registro in enumerate(self.itens):
            valores = (
                registro["codigo"], registro["nome"], registro["unidade"],
                fmt.fmt_qtd(registro["quantidade"]),
                fmt.fmt_num(registro["preco_unit_cent"]),
                fmt.fmt_num(registro["desconto_cent"]),
                fmt.fmt_num(registro["valor_cent"]),
                fmt.fmt_qtd(registro["diferenca"]),
            )
            for coluna, valor in enumerate(valores):
                item = QTableWidgetItem(str(valor))
                if coluna == 0:
                    item.setData(Qt.ItemDataRole.UserRole, registro["id"])
                self.grade_itens.setItem(linha, coluna, item)

    def remover_item(self):
        linha = self.grade_itens.currentRow()
        if linha < 0:
            return False
        item = self.grade_itens.item(linha, 0)
        if item is None:
            return False
        resposta = QMessageBox.question(
            self, "Excluir item",
            "Excluir o item selecionado? O efeito no estoque será desfeito.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        try:
            self._exigir_acesso()
            if resposta != QMessageBox.StandardButton.Yes:
                return False
            self.ctx.estoque.remover_item(item.data(Qt.ItemDataRole.UserRole))
            self.atualizar()
            return self.carregar(self.lancamento_id)
        except ErroNegocio as erro:
            return self._erro(erro)

    def excluir_lancamento(self):
        if self.lancamento_id is None:
            return False
        resposta = QMessageBox.question(
            self, "Excluir lançamento",
            "Excluir o lançamento inteiro? O efeito no estoque será desfeito.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        try:
            self._exigir_acesso()
            if resposta != QMessageBox.StandardButton.Yes:
                return False
            self.ctx.estoque.excluir_lancamento(self.lancamento_id)
            self.novo()
            self.atualizar()
            self.mensagem.setText("Lançamento excluído e estoque estornado.")
            return True
        except ErroNegocio as erro:
            return self._erro(erro)

    def confirmar_entrega(self):
        if (self.lancamento is None
                or self.lancamento["tipo"] != "pedido"):
            return False
        valores = {}
        try:
            self._exigir_acesso()
            if not self.itens:
                raise ErroNegocio("O pedido não tem itens.")
            for item in self.itens:
                self._exigir_acesso()
                texto_valor, aceitou = QInputDialog.getText(
                    self, "Confirmar entrega",
                    f"Valor total de '{item['nome']}' "
                    f"({fmt.fmt_qtd(item['quantidade'])}):",
                    QLineEdit.EchoMode.Normal, fmt.fmt_num(item["valor_cent"]))
                self._exigir_acesso()
                if not aceitou:
                    return False
                try:
                    valores[item["id"]] = fmt.para_centavos(texto_valor)
                except ValueError:
                    raise ErroNegocio("Valor do item inválido.")
            confirmar = QMessageBox.question(
                self, "Confirmar entrega",
                "Confirmar a entrega? Depois disso o pedido vira COMPRA "
                "e não pode ser alterado.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            self._exigir_acesso()
            if confirmar != QMessageBox.StandardButton.Yes:
                return False
            self.ctx.estoque.confirmar_pedido(self.lancamento_id, valores)
            self.atualizar()
            return self.carregar(self.lancamento_id)
        except ErroNegocio as erro:
            return self._erro(erro)
