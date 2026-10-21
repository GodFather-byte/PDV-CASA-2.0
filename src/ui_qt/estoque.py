"""Painel Qt de estoque, com consulta e operações rápidas do EstoqueController."""
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QHeaderView, QInputDialog, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto


SITUACOES = (
    (None, "Todos os controlados"), ("sem", "Sem estoque"), ("ponto", "Repor"),
    ("normal", "Normal"), ("livre", "Sem controle"),
)
ROTULOS = dict(SITUACOES)


def _curta(quantidade):
    valor = fmt.fmt_qtd(quantidade, fmt.CASAS_QTD)
    return valor.rstrip("0").rstrip(",") if "," in valor else valor


class _DialogoQuantidade(QDialog):
    """Entrada rápida de quantidade com a mesma validação e prévia do painel Tk."""

    def __init__(self, produto, tipo, parent=None):
        super().__init__(parent)
        self.produto, self.tipo = produto, tipo
        self.quantidade = None
        self.observacao = None
        titulo, pergunta = {
            "entrada": ("Chegou mercadoria", "Quantas unidades entraram?"),
            "saida": ("Saiu mercadoria", "Quantas unidades saíram (sem ser venda)?"),
            "descarte": ("Perda ou quebra", "Quantas unidades foram perdidas?"),
            "quebra": ("Perda por quebra", "Quantas unidades quebraram?"),
            "oxidacao": ("Perda por oxidação", "Quantas unidades oxidaram?"),
            "devolucao": ("Devolução", "Quantas unidades foram devolvidas?"),
            "contagem": ("Contagem na prateleira", "Quantas unidades existem de verdade agora?"),
        }[tipo]
        self.setWindowTitle(titulo)
        layout = QVBoxLayout(self)
        layout.addWidget(texto(produto["nome"], "titulo"))
        hoje = ("Ainda não controla estoque (vai passar a controlar)"
                if produto["situacao"] == "livre" else
                f"Hoje há {_curta(produto['qt_atual'])} {produto['unidade']}")
        layout.addWidget(texto(hoje, "suave"))
        formulario = QFormLayout()
        self.entrada = QLineEdit()
        self.entrada.setPlaceholderText("Ex.: 2,5")
        formulario.addRow(pergunta, self.entrada)
        self.nota = QLineEdit()
        if tipo in ("quebra", "oxidacao", "devolucao"):
            self.nota.setPlaceholderText("Observação (opcional)")
            formulario.addRow("Observação (opcional)", self.nota)
        layout.addLayout(formulario)
        self.previa = texto("", "suave")
        layout.addWidget(self.previa)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(self.confirmar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)
        self.entrada.textChanged.connect(self._atualizar_previa)
        self.setMinimumWidth(380)

    def _quantidade(self):
        try:
            quantidade = fmt.para_qtd(self.entrada.text())
        except ValueError:
            return None
        if quantidade < 0 or (quantidade == 0 and self.tipo != "contagem"):
            return None
        return quantidade

    def _atualizar_previa(self):
        quantidade = self._quantidade()
        if quantidade is None:
            self.previa.clear()
            return
        if self.tipo == "entrada":
            depois = self.produto["qt_atual"] + quantidade
        elif self.tipo == "contagem":
            depois = quantidade
        else:
            depois = self.produto["qt_atual"] - quantidade
        self.previa.setText(
            f"Vai ficar com {_curta(depois)} {self.produto['unidade']}")

    def confirmar(self):
        quantidade = self._quantidade()
        if quantidade is None:
            self.mensagem.setText("Digite uma quantidade válida.")
            return
        self.quantidade = quantidade
        self.observacao = self.nota.text().strip() or None
        self.accept()

    def executar(self):
        return self.quantidade if self.exec() == QDialog.DialogCode.Accepted else None


class JanelaEstoque(QDialog):
    LIMITE_HISTORICO = 30

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._exigir_acesso()
        self.linhas = []
        self.movimentos = []
        self.produto = None
        self._visao_atual = False
        self._filtros_visao = {}
        self.setWindowTitle("Estoque")
        self.resize(1200, 780)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Estoque", "titulo"))
        layout.addWidget(texto(
            "Consulte os saldos e movimentos. A busca por nome/código também inclui produtos sem controle.",
            "suave"))
        self.resumo = texto("", "suave")
        layout.addWidget(self.resumo)
        acoes = QHBoxLayout()
        self.btn_pedido = QPushButton("Gerar pedido do que falta")
        self.btn_pedido.clicked.connect(self.gerar_pedido)
        acoes.addWidget(self.btn_pedido)
        self.btn_lista = QPushButton("Lista de compras")
        self.btn_lista.clicked.connect(self.lista_de_compras)
        acoes.addWidget(self.btn_lista)
        self.btn_lancamentos = QPushButton("Lançamentos de estoque")
        self.btn_lancamentos.clicked.connect(self.abrir_lancamentos)
        acoes.addWidget(self.btn_lancamentos)
        acoes.addStretch(1)
        layout.addLayout(acoes)
        filtros = QHBoxLayout()
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Nome ou código • pressione Enter")
        self.busca.returnPressed.connect(self.atualizar)
        self.situacao, self.grupo = QComboBox(), QComboBox()
        self.visao = QComboBox()
        self.visao.addItem("Geral", False)
        self.visao.addItem("Adega", True)
        for valor, rotulo in SITUACOES:
            self.situacao.addItem(rotulo, valor)
        self.grupo.addItem("Todos os grupos", None)
        for rotulo, campo in (("Visão", self.visao), ("Busca", self.busca),
                              ("Situação", self.situacao), ("Grupo", self.grupo)):
            formulario = QFormLayout()
            formulario.addRow(rotulo, campo)
            filtros.addLayout(formulario)
        self.btn_atualizar = QPushButton("Consultar / atualizar (F5)")
        self.btn_atualizar.clicked.connect(self.atualizar)
        filtros.addWidget(self.btn_atualizar)
        layout.addLayout(filtros)
        layout.addWidget(texto(
            "Adega: categorias típicas e produtos configurados. Alta = sem estoque; média = repor. "
            "Pedido/lista Adega seguem os filtros; Geral mantém compras gerais.", "suave"))
        self.aviso_cobertura = texto(
            "Cobertura indicativa = saldo ÷ (vendas líquidas de estornos nos últimos 30 dias ÷ 30). "
            "Sem consumo líquido: indisponível. Reposição mantém dobro do mínimo; revise antes de comprar.",
            "suave")
        layout.addWidget(self.aviso_cobertura)
        self.grade = self._tabela([
            "Situação", "Código", "Produto", "Grupo", "Saldo", "Mínimo",
            "Reposição sugerida", "Último custo", "Valor em estoque", "Última atualização",
            "Categoria", "Prioridade de reposição", "Cobertura (30 dias)",
        ])
        self.grade.itemSelectionChanged.connect(self._selecionou)
        layout.addWidget(self.grade, 2)
        self.botoes = {}
        acoes_produto = QHBoxLayout()
        for tipo, rotulo in (
            ("entrada", "＋ Entrada"), ("saida", "－ Saída"),
            ("descarte", "Perda / quebra"), ("quebra", "Quebra"),
            ("oxidacao", "Oxidação"), ("devolucao", "Devolução"), ("contagem", "Contei e ajustar"),
        ):
            botao = QPushButton(rotulo)
            botao.clicked.connect(lambda _=False, t=tipo: self.registrar_dialogo(t))
            self.botoes[tipo] = botao
            acoes_produto.addWidget(botao)
        self.btn_minimo = QPushButton("Definir estoque mínimo")
        self.btn_minimo.clicked.connect(self.definir_minimo)
        acoes_produto.addWidget(self.btn_minimo)
        self.btn_editar = QPushButton("Editar cadastro do produto")
        self.btn_editar.clicked.connect(self.editar_cadastro)
        acoes_produto.addWidget(self.btn_editar)
        self.btn_novo_produto = QPushButton("Cadastrar produto")
        self.btn_novo_produto.clicked.connect(self.cadastrar_produto)
        acoes_produto.addWidget(self.btn_novo_produto)
        layout.addLayout(acoes_produto)
        self._habilitar_acoes(False)
        self._janela_lancamentos = None
        self.detalhe = texto("Selecione um produto para consultar os últimos movimentos.", "suave")
        layout.addWidget(self.detalhe)
        self.historico = self._tabela(["Quando", "Movimento", "Quantidade", "Saldo após"])
        layout.addWidget(self.historico, 1)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        layout.addWidget(fechar)
        QShortcut(QKeySequence("F5"), self, activated=self.atualizar)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.busca.setFocus)
        self.visao.currentIndexChanged.connect(lambda _: self._trocar_visao())
        self.atualizar()

    @staticmethod
    def _tabela(cabecalhos):
        tabela = QTableWidget(0, len(cabecalhos))
        tabela.setHorizontalHeaderLabels(cabecalhos)
        tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabela.setAlternatingRowColors(True)
        tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tabela.horizontalHeader().setStretchLastSection(True)
        return tabela

    def _exigir_acesso(self):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre com um operador para consultar o estoque.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.acesso.exigir(self.ctx.acesso.operador(self.ctx.operador_id), "lanc_estoque")

    @staticmethod
    def _preencher(tabela, linhas):
        tabela.clearSelection()
        tabela.setRowCount(len(linhas))
        for linha, valores in enumerate(linhas):
            for coluna, valor in enumerate(valores):
                tabela.setItem(linha, coluna, QTableWidgetItem(str(valor)))

    def _limpar_historico(self):
        self.movimentos = []
        self.historico.setRowCount(0)
        self.detalhe.setText("Selecione um produto para consultar os últimos movimentos.")

    def _limpar(self):
        self.linhas = []
        self.produto = None
        self.grade.setRowCount(0)
        self.resumo.clear()
        self._limpar_historico()
        self._habilitar_acoes(False)

    def _habilitar_acoes(self, habilitado):
        for botao in (*self.botoes.values(), self.btn_minimo, self.btn_editar):
            botao.setEnabled(habilitado)
        livre = habilitado and self.produto["situacao"] == "livre"
        self.botoes["saida"].setEnabled(habilitado and not livre)
        self.botoes["descarte"].setEnabled(habilitado and not livre)

    def _tratar_erro(self, erro, limpar=False):
        if limpar or isinstance(erro, ErroPermissao):
            self._limpar()
        self.mensagem.setText(str(erro))
        return False

    def _trocar_visao(self):
        self._filtros_visao[self._visao_atual] = (
            self.situacao.currentData(), self.busca.text(), self.grupo.currentData())
        self._visao_atual = self.visao.currentData()
        situacao, busca, grupo = self._filtros_visao.get(self._visao_atual, (None, "", None))
        self.situacao.setCurrentIndex(self.situacao.findData(situacao))
        self.busca.setText(busca)
        indice = self.grupo.findData(grupo)
        if indice < 0:
            self.grupo.addItem(grupo, grupo)
            indice = self.grupo.count() - 1
        self.grupo.setCurrentIndex(indice)
        self.atualizar()

    def _recorte_compras(self):
        if not self.visao.currentData():
            return {}
        return {"adega": True, "situacao": self.situacao.currentData(),
                "texto": self.busca.text(), "grupo": self.grupo.currentData()}

    def atualizar(self, preservar_produto=False):
        produto_id = (self.produto["id"] if preservar_produto and self.produto
                      else None)
        try:
            self._exigir_acesso()
            estoque = self.ctx.estoque
            adega = self.visao.currentData()
            resumo = estoque.resumo(adega=adega)
            grupos = estoque.grupos()
            grupo = self.grupo.currentData()
            linhas = estoque.painel(
                situacao=self.situacao.currentData(), texto=self.busca.text(), grupo=grupo, adega=adega)
        except ErroNegocio as erro:
            self._tratar_erro(erro, limpar=True)
            return False
        self.grupo.clear()
        self.grupo.addItem("Todos os grupos", None)
        for nome in grupos:
            self.grupo.addItem(nome, nome)
        if grupo is not None:
            # Preserva o filtro mesmo se o grupo tiver sido removido durante a consulta.
            indice = self.grupo.findData(grupo)
            if indice < 0:
                self.grupo.addItem(grupo, grupo)
                indice = self.grupo.count() - 1
            self.grupo.setCurrentIndex(indice)
        self.linhas = linhas
        self.grade.setColumnHidden(12, not adega)
        self.aviso_cobertura.setVisible(adega)
        self.btn_pedido.setText("Gerar pedido Adega (filtros)" if adega else "Gerar pedido do que falta")
        self.btn_lista.setText("Lista de compras Adega (filtros)" if adega else "Lista de compras")
        self.grade.blockSignals(True)
        try:
            self._preencher(self.grade, [
                (ROTULOS[p["situacao"]], p["codigo"], p["nome"], p["grupo"],
                 "—" if p["situacao"] == "livre" else
                 f"{fmt.fmt_qtd(p['qt_atual'], fmt.CASAS_QTD)} {p['unidade']}",
                 fmt.fmt_qtd(p["estoque_minimo"], fmt.CASAS_QTD),
                 fmt.fmt_qtd(p["repor"], fmt.CASAS_QTD),
                 fmt.fmt_brl(p["ult_preco_cent"]),
                 "—" if p["situacao"] == "livre" else fmt.fmt_brl(p["valor_cent"]),
                 fmt.fmt_datahora(p["ult_atualizacao"]) or "—", p["categoria"], p["prioridade"],
                 p.get("cobertura_rotulo", ""))
                for p in linhas
            ])
        finally:
            self.grade.blockSignals(False)
        self._limpar_historico()
        self.produto = None
        self._habilitar_acoes(False)
        if produto_id is not None:
            for indice, produto in enumerate(linhas):
                if produto["id"] == produto_id:
                    self.grade.selectRow(indice)
                    break
        self.resumo.setText(
            f"Resumo {'Adega' if adega else 'geral'} (ativos) • {resumo['total']} controlado(s) • "
            f"{resumo['sem']} sem estoque • {resumo['ponto']} para repor • "
            f"{resumo['normal']} normal(is) • {resumo['livre']} sem controle • "
            f"Valor: {fmt.fmt_brl(resumo['valor_cent'])} (saldo × último custo).")
        self.mensagem.setText(
            f"{len(linhas)} produto(s) encontrado(s)." if linhas else
            "Nenhum produto encontrado. Consulte também o filtro Sem controle.")
        return True

    def _selecionou(self):
        linha = self.grade.currentRow()
        self.produto = (self.linhas[linha] if self.grade.selectedItems()
                        and 0 <= linha < len(self.linhas) else None)
        self._habilitar_acoes(self.produto is not None)
        self.mostrar_historico()

    def mostrar_historico(self):
        self._limpar_historico()
        linha = self.grade.currentRow()
        if not self.grade.selectedItems() or not 0 <= linha < len(self.linhas):
            return
        try:
            self._exigir_acesso()
            produto = self.linhas[linha]
            movimentos = self.ctx.estoque.historico(produto["id"], limite=self.LIMITE_HISTORICO)
        except ErroNegocio as erro:
            self._tratar_erro(erro, limpar=True)
            return
        self.movimentos = movimentos
        self._preencher(self.historico, [
            (fmt.fmt_datahora(m["criado_em"]), m["rotulo"],
             fmt.fmt_qtd(m["quantidade"], fmt.CASAS_QTD),
             fmt.fmt_qtd(m["qt_apos"], fmt.CASAS_QTD))
            for m in movimentos
        ])
        self.detalhe.setText(
            f"{produto['nome']} • até {self.LIMITE_HISTORICO} movimentos, mais recentes primeiro "
            f"• unidade: {produto['unidade']}" +
            (f" • Consumo líquido 30 dias: {_curta(produto['consumo_30_dias'])}; "
             f"cobertura: {produto['cobertura_rotulo']}; "
             f"recorte indicativo: {produto['classificacao_adega']}."
             if "cobertura_rotulo" in produto else "") +
            (" • nenhum movimento registrado." if not movimentos else ""))

    def registrar(self, tipo, quantidade, observacao=None):
        """Registra um movimento rápido e recarrega o produto e seu histórico."""
        if self.produto is None:
            return False
        try:
            self._exigir_acesso()
            produto_id = self.produto["id"]
            self.ctx.estoque.registrar_rapido(produto_id, tipo, quantidade, observacao)
        except ErroNegocio as erro:
            return self._tratar_erro(erro)
        self.atualizar(preservar_produto=True)
        self.mensagem.setText({
            "entrada": "Entrada registrada.",
            "saida": "Saída registrada.",
            "descarte": "Perda / quebra registrada.",
            "quebra": "Perda por quebra registrada.",
            "oxidacao": "Perda por oxidação registrada.",
            "devolucao": "Devolução registrada.",
            "contagem": "Contagem registrada.",
        }[tipo])
        return True

    def _pedir_quantidade(self, tipo):
        if self.produto is None:
            return None
        dialogo = _DialogoQuantidade(self.produto, tipo, self)
        quantidade = dialogo.executar()
        self._observacao_perda = dialogo.observacao
        return quantidade

    def registrar_dialogo(self, tipo):
        if self.produto is None:
            return False
        try:
            self._exigir_acesso()
        except ErroNegocio as erro:
            return self._tratar_erro(erro)
        quantidade = self._pedir_quantidade(tipo)
        if quantidade is None:
            return False
        return self.registrar(tipo, quantidade, getattr(self, "_observacao_perda", None))

    def definir_minimo(self):
        if self.produto is None:
            return False
        try:
            self._exigir_acesso()
            valor, aceitou = QInputDialog.getText(
                self, "Estoque mínimo",
                f"Avisar quando '{self.produto['nome']}' chegar a quantas unidades?",
                QLineEdit.EchoMode.Normal,
                _curta(self.produto["estoque_minimo"])
                if self.produto["estoque_minimo"] else "")
            if not aceitou:
                return False
            self._exigir_acesso()
            try:
                minimo = fmt.para_qtd(valor)
            except ValueError:
                raise ErroNegocio("Digite uma quantidade válida.")
            if minimo < 0:
                raise ErroNegocio("O mínimo não pode ser negativo.")
            produto_id = self.produto["id"]
            self.ctx.estoque.definir_minimo(produto_id, minimo)
        except ErroNegocio as erro:
            return self._tratar_erro(erro)
        self.atualizar(preservar_produto=True)
        self.mensagem.setText("Estoque mínimo atualizado.")
        return True

    def editar_cadastro(self):
        if self.produto is None:
            return False
        return self._abrir_formulario_produto(self.produto["id"])

    def cadastrar_produto(self):
        return self._abrir_formulario_produto()

    def _abrir_formulario_produto(self, produto_id=None):
        try:
            from src.ui_qt.cadastros import FormularioCadastro, exigir_acesso
            self._exigir_acesso()
            exigir_acesso(self.ctx, "produtos")
            formulario = FormularioCadastro(
                self.ctx, "produtos", produto_id, self)
            resultado = formulario.exec()
            formulario.deleteLater()
            self._exigir_acesso()
            exigir_acesso(self.ctx, "produtos")
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        if resultado == QDialog.DialogCode.Accepted:
            self.atualizar()
            self.mensagem.setText("Cadastro de produto atualizado.")
            return True
        return False

    def gerar_pedido(self):
        try:
            self._exigir_acesso()
            recorte = self._recorte_compras()
            falta = self.ctx.estoque.lista_de_compras(**recorte)
            if not falta:
                self.mensagem.setText(
                    "Nenhum produto precisa de reposição agora. "
                    "(Produtos sem estoque mínimo definido não entram na sugestão.)")
                return False
            fornecedores = self.ctx.cadastros.opcoes("fornecedores")
            if not fornecedores:
                self.mensagem.setText(
                    "Cadastre um fornecedor primeiro (Manutenção de Cadastros > Fornecedores).")
                return False
            rotulos = [nome for _, nome in fornecedores]
            escopo = "Adega (filtros atuais)" if recorte else "Geral (todos os produtos a repor)"
            nome, aceitou = QInputDialog.getItem(
                self, "Gerar pedido",
                f"{escopo}: {len(falta)} produto(s). Para qual fornecedor é o pedido?",
                rotulos, 0, False)
            self._exigir_acesso()
            if not aceitou:
                return False
            fornecedor_id = next(fid for fid, rotulo in fornecedores if rotulo == nome)
            lancamento_id = self.ctx.estoque.pedido_sugerido(fornecedor_id, **recorte)
        except ErroNegocio as erro:
            return self._tratar_erro(erro)
        self.atualizar()
        self.mensagem.setText(
            f"Pedido {lancamento_id} criado com {len(falta)} produto(s). "
            "O estoque só muda quando a entrega for confirmada.")
        self.abrir_lancamentos(lancamento_id)
        return True

    def abrir_lancamentos(self, lancamento_id=None):
        try:
            self._exigir_acesso()
            from src.ui_qt.estoque_lancamentos import JanelaLancamentosEstoque
            janela = JanelaLancamentosEstoque(
                self.ctx, self, lancamento_id=lancamento_id)
            self._janela_lancamentos = janela
            janela.show()
            janela.raise_()
            janela.activateWindow()
            return janela
        except ErroNegocio as erro:
            return self._tratar_erro(erro)

    def lista_de_compras(self):
        try:
            self._exigir_acesso()
            recorte = self._recorte_compras()
            itens = self.ctx.estoque.lista_de_compras(**recorte)
        except ErroNegocio as erro:
            return self._tratar_erro(erro)
        if not itens:
            self.mensagem.setText("Nenhum produto precisa de reposição agora.")
            return False
        linhas = [
            f"LISTA DE COMPRAS - {fmt.fmt_data(fmt.hoje())}", "-" * 64,
            "ADEGA — filtros atuais" if recorte else "GERAL — todos os produtos a repor",
            f"{'Produto':<32}{'Tem':>9}{'Mínimo':>9}{'Comprar':>10}", "-" * 64,
        ]
        for produto in itens:
            linhas.append(
                f"{produto['nome'][:31]:<32}"
                f"{_curta(produto['qt_atual']):>9}"
                f"{_curta(produto['estoque_minimo']):>9}"
                f"{_curta(produto['repor']):>10}")
        QMessageBox.information(self, "Lista de compras", "\n".join(linhas))
        return True
