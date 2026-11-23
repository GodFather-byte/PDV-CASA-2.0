"""Etiquetas de produtos e preços no Qt: seleção, prévia, impressão e CSV, sem hardware obrigatório.

"Com código de barras" abre no navegador a folha de etiquetas adesivas (A4 ou rolo); produto sem código de barras pode
ganhar um código próprio da loja na hora (precisa do acesso ao cadastro de produtos)."""
import os
import tempfile
import webbrowser
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers.etiqueta_controller import MAX_COPIAS_ITEM, MODELOS, TEMPERATURAS, EtiquetaController
from src.core import edicao, formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto
from src.ui_qt.visualizador import JanelaVisualizador

MODULO = "lanc_estoque"


class JanelaEtiquetas(QDialog):
    """Nada é impresso sem o clique do operador; a prévia abre o visualizador (imprime/salva texto)."""

    def __init__(self, ctx, produtos, selecionados=None, parent=None):
        super().__init__(parent)
        self.ctx, self.produtos = ctx, list(produtos)
        self._operador_id = ctx.operador_id
        self._exigir_acesso()
        self.ctrl = EtiquetaController(ctx.banco)
        self.setWindowTitle("Etiquetas de produtos e preços")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Selecione os produtos (Ctrl/Shift para vários).", "suave"))
        precos = {r["id"]: r["preco_cent"] for r in ctx.banco.todos("SELECT id, preco_cent FROM produtos")}
        self.grade = QTableWidget(len(self.produtos), 3)
        self.grade.setHorizontalHeaderLabels(["Código", "Produto", "Preço cadastro"])
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.horizontalHeader().setStretchLastSection(True)
        for i, p in enumerate(self.produtos):
            for j, valor in enumerate((p["codigo"], p["nome"], fmt.fmt_brl(precos.get(p["id"], 0)))):
                self.grade.setItem(i, j, QTableWidgetItem(str(valor)))
            if p["id"] in (selecionados or []):
                self.grade.selectRow(i)
        layout.addWidget(self.grade)
        opcoes = QHBoxLayout()
        opcoes.addWidget(texto("Cópias por produto", "suave"))
        self.copias = QSpinBox()
        self.copias.setRange(1, MAX_COPIAS_ITEM)
        opcoes.addWidget(self.copias)
        self.rotulo_temperatura = texto("Temperatura", "suave")
        opcoes.addWidget(self.rotulo_temperatura)
        self.temperatura = QComboBox()
        for chave, rotulo in TEMPERATURAS.items():
            self.temperatura.addItem(rotulo, chave)
        opcoes.addWidget(self.temperatura)
        if edicao.atual().sem_gelada:                 # loja sem bebida: só existe o preço natural
            self.rotulo_temperatura.hide()
            self.temperatura.hide()
        opcoes.addStretch(1)
        layout.addLayout(opcoes)
        barras = QHBoxLayout()
        barras.addWidget(texto("Etiqueta adesiva", "suave"))
        self.modelo = QComboBox()
        for chave, (rotulo, _medidas) in MODELOS.items():
            self.modelo.addItem(rotulo, chave)
        self.modelo.currentIndexChanged.connect(self._modelo_mudou)
        barras.addWidget(self.modelo)
        self.rotulo_pular = texto("Pular (folha já usada)", "suave")
        barras.addWidget(self.rotulo_pular)
        self.pular = QSpinBox()
        barras.addWidget(self.pular)
        barras.addStretch(1)
        layout.addLayout(barras)
        self._modelo_mudou()
        botoes = QHBoxLayout()
        self.btn_previa = QPushButton("Prévia / Imprimir")
        self.btn_previa.clicked.connect(lambda: self.previa())
        self.btn_barras = QPushButton("Com código de barras...")
        self.btn_barras.setToolTip("Abre no navegador a folha de etiquetas com nome, código de barras e preço.")
        self.btn_barras.clicked.connect(lambda: self.folha_barras())
        self.btn_csv = QPushButton("Exportar CSV...")
        self.btn_csv.clicked.connect(lambda: self.exportar_csv())
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        for botao in (self.btn_previa, self.btn_barras, self.btn_csv, fechar):
            botao.setAutoDefault(False)
            botoes.addWidget(botao)
        layout.addLayout(botoes)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)

    def _exigir_acesso(self):
        if self.ctx.operador is None or self.ctx.operador_id != self._operador_id:
            raise ErroPermissao("A sessão mudou. Abra as etiquetas novamente.")
        self.ctx.acesso.exigir(self.ctx.acesso.operador(self._operador_id), MODULO)

    def itens(self):
        linhas = sorted({i.row() for i in self.grade.selectedIndexes()})
        return [{"produto_id": self.produtos[l]["id"], "copias": self.copias.value(),
                 "temperatura": self.temperatura.currentData()} for l in linhas]

    def _montar(self):
        try:
            self._exigir_acesso()
            self.mensagem.clear()
            return self.ctrl.etiquetas(self.itens())
        except (ErroNegocio, ErroPermissao) as erro:
            self.mensagem.setText(str(erro))
            return None

    def previa(self):
        etiquetas = self._montar()
        if etiquetas is None:
            return False
        try:
            janela = JanelaVisualizador(self.ctx, "Etiquetas - prévia", self.ctrl.texto(etiquetas), parent=self,
                                        modulo=MODULO, nome="etiquetas", tipo="etiquetas")
        except (ErroNegocio, ErroPermissao) as erro:
            self.mensagem.setText(str(erro))
            return False
        janela.exec()
        return True

    def _modelo_mudou(self, *_):
        medidas = MODELOS[self.modelo.currentData()][1]
        rolo = bool(medidas.get("rolo"))
        self.pular.setRange(0, 0 if rolo else medidas["colunas"] * medidas["linhas"] - 1)
        self.pular.setEnabled(not rolo)
        self.rotulo_pular.setEnabled(not rolo)

    def _perguntar_codigos(self, faltando):
        """True gera, False segue sem barras nesses produtos, None desiste."""
        nomes = ", ".join(p["nome"] for p in faltando[:3]) + ("..." if len(faltando) > 3 else "")
        resposta = QMessageBox.question(
            self, "Código de barras",
            f"{len(faltando)} produto(s) sem código de barras ({nomes}).\n\nGerar um código próprio da loja para eles? "
            "O código fica gravado no cadastro e o leitor do caixa passa a ler a etiqueta.\n\n"
            "\"Não\" imprime esses produtos sem as barras.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
        if resposta == QMessageBox.StandardButton.Cancel:
            return None
        return resposta == QMessageBox.StandardButton.Yes

    def folha_barras(self, caminho=None, gerar=None, abrir=True):
        """Folha de etiquetas com código de barras. `gerar` (True/False) responde à pergunta do código próprio; None pergunta."""
        try:
            self._exigir_acesso()
            self.mensagem.clear()
            itens = self.itens()
            if not itens:
                raise ErroNegocio("Selecione ao menos um produto para as etiquetas.")
            faltando = self.ctrl.sem_codigo([i["produto_id"] for i in itens])
            if faltando:
                if gerar is None:
                    gerar = self._perguntar_codigos(faltando)
                if gerar is None:
                    return False
                if gerar:
                    from src.ui_qt.catalogo import exigir_cadastro_produtos
                    exigir_cadastro_produtos(self.ctx)
                    self.ctrl.gerar_codigos([p["id"] for p in faltando], self.ctx.operador_id)
            html = self.ctrl.folha_html(self.ctrl.etiquetas(itens), self.modelo.currentData(), self.pular.value())
            caminho = caminho or os.path.join(tempfile.gettempdir(), "etiquetas-codigo-de-barras.html")
            with open(caminho, "w", encoding="utf-8") as arquivo:
                arquivo.write(html)
        except (ErroNegocio, ErroPermissao, OSError) as erro:
            self.mensagem.setText(str(erro))
            return False
        if abrir and not webbrowser.open(caminho):
            self.mensagem.setText("Não abri o navegador. A folha está em: " + caminho)
            return True
        self.mensagem.setText("A folha abriu no navegador. Imprima em tamanho real (escala 100%, sem ajustar à página).")
        return True

    def exportar_csv(self, caminho=None):
        etiquetas = self._montar()
        if etiquetas is None:
            return False
        if not caminho:
            caminho, _ = QFileDialog.getSaveFileName(self, "Exportar etiquetas", "etiquetas.csv", "CSV (*.csv)")
        if not caminho:
            return False
        try:
            self._exigir_acesso()
            with Path(caminho).open("w", encoding="utf-8-sig", newline="") as arquivo:
                arquivo.write(self.ctrl.csv(etiquetas))
        except (ErroNegocio, ErroPermissao, OSError) as erro:
            self.mensagem.setText(f"Não foi possível exportar: {erro}")
            return False
        self.mensagem.setText("CSV exportado.")
        return True