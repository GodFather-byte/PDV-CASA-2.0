"""Importação Qt de produtos; leitura, validação e gravação pertencem ao controlador."""
from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFileDialog, QLineEdit,
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QRadioButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers.importacao_produtos import ImportacaoProdutos, Previa, ler_tabela
from src.controllers.config_controller import modulos_desligados
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto


ROTULOS_ACAO = {"criar": "Criar", "atualizar": "Atualizar", "recusar": "Recusado"}
FILTRO_PLANILHAS = "Planilhas (Excel ou CSV) (*.xlsx *.xlsm *.csv *.txt)"


class JanelaImportarProdutos(QDialog):
    """Prévia transacional dos produtos da planilha, sem escrita feita pela interface."""

    COLUNAS = (
        "Linha", "Ação", "Código", "Produto", "Preço", "Comissão",
        "Grupo", "Estoque", "Observação",
    )

    def __init__(self, ctx, parent=None, ao_importar=None):
        super().__init__(parent)
        self.ctx = ctx
        self.ao_importar = ao_importar
        self._exigir_acesso()
        self.imp = ImportacaoProdutos(ctx.banco, ctx.operador_id)
        self.caminho = None
        self.tabela = None
        self.previa: Previa | None = None
        self.setWindowTitle("Importar produtos • Qt")
        self.resize(1120, 760)

        layout = QVBoxLayout(self)
        layout.addWidget(texto("Importar produtos por planilha", "titulo"))
        layout.addWidget(texto(
            "Escolha CSV ou Excel, confira a prévia e confirme para gravar. "
            "As linhas recusadas não serão importadas; os preços são mantidos em centavos.",
            "suave"))

        arquivos = QHBoxLayout()
        self.btn_escolher = QPushButton("Escolher planilha…")
        self.btn_escolher.clicked.connect(self.escolher_arquivo)
        arquivos.addWidget(self.btn_escolher)
        self.arquivo = QLabel("Nenhuma planilha escolhida")
        self.arquivo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        arquivos.addWidget(self.arquivo, 1)
        self.btn_modelo = QPushButton("Salvar modelo…")
        self.btn_modelo.clicked.connect(self.salvar_modelo)
        arquivos.addWidget(self.btn_modelo)
        self.btn_exportar = QPushButton("Exportar produtos…")
        self.btn_exportar.clicked.connect(self.exportar)
        arquivos.addWidget(self.btn_exportar)
        layout.addLayout(arquivos)

        opcoes = QHBoxLayout()
        self.atualizar_existentes = QCheckBox(
            "Atualizar produtos existentes (por código ou nome)")
        self.atualizar_existentes.setChecked(True)
        opcoes.addWidget(self.atualizar_existentes)
        opcoes.addSpacing(12)
        self.codigo_planilha = QRadioButton("Usar código da planilha")
        self.codigo_planilha.setChecked(True)
        self.codigo_sequencial = QRadioButton("Numerar em sequência a partir de:")
        opcoes.addWidget(self.codigo_planilha)
        opcoes.addWidget(self.codigo_sequencial)
        self.inicio = QLineEdit(str(max(1, self.imp.numero_inicial_sugerido())))
        self.inicio.setMaximumWidth(110)
        self.inicio.setEnabled(False)
        opcoes.addWidget(self.inicio)
        opcoes.addStretch()
        layout.addLayout(opcoes)

        self.maiusculas = QCheckBox("Escrever nomes em MAIÚSCULAS")
        self.maiusculas.setChecked(True)
        layout.addWidget(self.maiusculas)

        self.resumo = texto("Escolha uma planilha para analisar.", "suave")
        self.resumo.setWordWrap(True)
        layout.addWidget(self.resumo)
        self.grade = QTableWidget(0, len(self.COLUNAS))
        self.grade.setHorizontalHeaderLabels(self.COLUNAS)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setAlternatingRowColors(True)
        self.grade.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.grade.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.grade, 1)
        self.mensagem = texto("", "aviso")
        self.mensagem.setWordWrap(True)
        layout.addWidget(self.mensagem)

        botoes = QHBoxLayout()
        botoes.addStretch()
        self.btn_importar = QPushButton("Importar")
        self.btn_importar.setEnabled(False)
        self.btn_importar.clicked.connect(self.importar)
        botoes.addWidget(self.btn_importar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        botoes.addWidget(fechar)
        layout.addLayout(botoes)

        self.atualizar_existentes.toggled.connect(self.analisar)
        self.codigo_planilha.toggled.connect(self._modo_codigo_alterado)
        self.codigo_sequencial.toggled.connect(self._modo_codigo_alterado)
        self.inicio.textChanged.connect(self.analisar)
        self.maiusculas.toggled.connect(self.analisar)
        QShortcut(QKeySequence("Escape"), self, activated=self.reject)

    def _exigir_acesso(self):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre no sistema para importar produtos.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        entidade = self.ctx.cadastros.entidade("produtos")
        if entidade.modulo in modulos_desligados(self.ctx.banco):
            raise ErroPermissao("O cadastro de produtos está desativado.")
        self.ctx.acesso.exigir(self.ctx.operador, entidade.modulo)

    def _modo_codigo_alterado(self, _marcado):
        self.inicio.setEnabled(self.codigo_sequencial.isChecked())
        self.analisar()

    def escolher_arquivo(self):
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Planilha de produtos", "", FILTRO_PLANILHAS)
        if caminho:
            self.carregar(caminho)

    def carregar(self, caminho):
        try:
            self._exigir_acesso()
            tabela = ler_tabela(caminho)
        except (ErroNegocio, OSError, ValueError) as erro:
            self.mensagem.setText(str(erro))
            return False
        self.caminho = str(caminho)
        self.tabela = tabela
        self.arquivo.setText(f"{Path(caminho).name}  ({len(tabela)} linhas)")
        self.mensagem.clear()
        return self.analisar()

    def analisar(self, *_args):
        if self.tabela is None:
            return False
        try:
            self._exigir_acesso()
            inicio = None
            if self.codigo_sequencial.isChecked():
                texto_inicio = self.inicio.text().strip()
                try:
                    inicio = max(int(texto_inicio), 1)
                except ValueError:
                    raise ValueError(
                        "Digite somente números para iniciar a sequência.") from None
            previa = self.imp.analisar(
                self.tabela,
                atualizar_existentes=self.atualizar_existentes.isChecked(),
                sequencia_a_partir_de=inicio,
                usar_codigo_da_planilha=self.codigo_planilha.isChecked(),
                maiusculas=self.maiusculas.isChecked(),
            )
        except (ErroNegocio, OSError, ValueError) as erro:
            self.previa = None
            self.grade.setRowCount(0)
            self.btn_importar.setEnabled(False)
            self.resumo.setText("Não foi possível analisar a planilha.")
            self.mensagem.setText(str(erro))
            return False

        self.previa = previa
        self.grade.setRowCount(len(previa.linhas))
        for linha, item in enumerate(previa.linhas):
            codigo = str(int(item.codigo)) if item.codigo.isdigit() else item.codigo
            preco = fmt.fmt_num(item.preco_cent) if item.acao != "recusar" or item.preco_cent else ""
            comissao = (fmt.fmt_num(round(item.preco_cent * item.comissao_pct / 100))
                        if item.comissao_pct else "")
            estoque = (fmt.fmt_qtd(item.quantidade).rstrip("0").rstrip(",")
                       if item.quantidade is not None else "")
            observacao = item.motivo or " ".join(item.avisos)
            valores = (
                str(item.linha), ROTULOS_ACAO[item.acao], codigo, item.nome,
                preco, comissao, item.grupo, estoque, observacao,
            )
            for coluna, valor in enumerate(valores):
                celula = QTableWidgetItem(valor)
                if coluna in (0, 2, 4, 5, 7):
                    celula.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.grade.setItem(linha, coluna, celula)
        recusados = previa.contar("recusar")
        self.resumo.setText(
            f"Prévia: {previa.resumo()}." +
            (" Os recusados NÃO serão importados; consulte a observação."
             if recusados else ""))
        self.mensagem.clear()
        self.btn_importar.setText(f"Importar {len(previa.importaveis)} produto(s)")
        self.btn_importar.setEnabled(bool(previa.importaveis))
        return True

    def importar(self):
        previa = self.previa
        if previa is None or not previa.importaveis:
            return False
        try:
            self._exigir_acesso()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        n = len(previa.importaveis)
        resposta = QMessageBox.question(
            self, "Confirmar importação",
            f"Importar {n} produto(s) agora?\n\n{previa.resumo()}.\n"
            "Se algo falhar, nada será gravado.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return False
        try:
            resultado = self.imp.importar(previa)
        except (ErroNegocio, OSError, ValueError, sqlite3.Error) as erro:
            self.mensagem.setText(f"Importação não concluída: {erro}")
            return False

        QMessageBox.information(
            self, "Importação concluída",
            f"Pronto: {resultado['criados']} produto(s) criado(s), "
            f"{resultado['atualizados']} atualizado(s)" +
            (f" e {resultado['estoque']} com estoque lançado."
             if resultado["estoque"] else "."),
        )
        if self.ao_importar:
            try:
                self.ao_importar()
            except (ErroNegocio, OSError, ValueError, sqlite3.Error) as erro:
                self.mensagem.setText(
                    f"Importação concluída; não foi possível atualizar a lista: {erro}")
        self.tabela = None
        self.previa = None
        self.caminho = None
        self.grade.setRowCount(0)
        self.arquivo.setText("Nenhuma planilha escolhida")
        self.resumo.setText("Importação concluída. Escolha outra planilha se precisar.")
        self.btn_importar.setText("Importar")
        self.btn_importar.setEnabled(False)
        return True

    def _salvar_csv(self, titulo, nome, conteudo):
        caminho, _ = QFileDialog.getSaveFileName(
            self, titulo, nome, "Planilha CSV (abre no Excel) (*.csv)")
        if not caminho:
            return False
        if not Path(caminho).suffix:
            caminho += ".csv"
        try:
            Path(caminho).write_text(conteudo, encoding="utf-8-sig", newline="")
        except OSError as erro:
            QMessageBox.critical(self, "Falha ao salvar", f"Não consegui salvar o arquivo: {erro}")
            return False
        QMessageBox.information(self, "Arquivo salvo", f"Arquivo salvo em:\n{caminho}")
        return True

    def salvar_modelo(self):
        try:
            self._exigir_acesso()
            return self._salvar_csv("Salvar planilha modelo", "modelo_produtos.csv",
                                    self.imp.modelo())
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False

    def exportar(self):
        try:
            self._exigir_acesso()
            return self._salvar_csv("Exportar produtos", "produtos.csv",
                                    self.imp.exportar())
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
