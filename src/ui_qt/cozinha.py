"""Painel Qt de preparo; somente o controlador decide a fila e os estados."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers.config_controller import modulos_desligados
from src.core.erros import ErroNegocio, ErroPermissao
from src.core.formatacao import fmt_qtd
from src.ui_qt.tema import texto


SITUACOES = {"pendente": "Pendente", "em_preparo": "Em preparo", "entregue": "Entregue"}


class JanelaCozinha(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._operador_id = ctx.operador_id
        self.exigir_acesso()
        self.setWindowTitle("Painel da Cozinha/Bar • Qt")
        self.resize(1050, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Painel da Cozinha/Bar", "titulo"))
        layout.addWidget(texto(
            "Itens dos subgrupos com impressora remota. Atualização a cada 2 segundos. "
            "Marcar pronto altera o preparo, não imprime nem confirma saída física.", "suave"))
        barra = QHBoxLayout()
        barra.addWidget(texto("Setor:"))
        self.setor = QComboBox()
        barra.addWidget(self.setor, 1)
        layout.addLayout(barra)
        self.grade = QTableWidget(0, 6)
        self.grade.setHorizontalHeaderLabels(
            ("Posição", "Produto", "Quantidade", "Observação", "Minutos", "Situação"))
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.horizontalHeader().setStretchLastSection(True)
        self.grade.cellDoubleClicked.connect(lambda *_: self.avancar())
        layout.addWidget(self.grade)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        barra = QHBoxLayout()
        self.acoes = []
        for rotulo, acao in (
            ("Iniciar preparo", lambda: self.marcar("em_preparo")),
            ("Marcar pronto", lambda: self.marcar("entregue")),
            ("Avançar", self.avancar), ("Atualizar (F5)", self.atualizar),
            ("Fechar (Esc)", self.close),
        ):
            botao = QPushButton(rotulo)
            botao.setAutoDefault(False)
            botao.clicked.connect(acao)
            barra.addWidget(botao)
            self.acoes.append(botao)
        layout.addLayout(barra)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.atualizar)
        self.setor.currentIndexChanged.connect(self.atualizar)
        QShortcut(QKeySequence("F5"), self, activated=self.atualizar)
        self.atualizar()

    def exigir_acesso(self):
        if self.ctx.operador_id is None or self.ctx.operador_id != self._operador_id:
            raise ErroPermissao("A sessão mudou. Abra o painel novamente.")
        cadastro = self.ctx.cadastros.obter("operadores", self._operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.operador = self.ctx.acesso.operador(self._operador_id)
        if "util_cozinha" in modulos_desligados(self.ctx.banco):
            raise ErroPermissao("O módulo Cozinha/Bar está desligado.")
        self.ctx.acesso.exigir(self.ctx.operador, "util_cozinha")

    def selecionado(self):
        linhas = self.grade.selectionModel().selectedRows()
        return (self.grade.item(linhas[0].row(), 0).data(Qt.ItemDataRole.UserRole)
                if linhas else None)

    def _erro(self, erro):
        self.mensagem.setText(str(erro))
        if isinstance(erro, ErroPermissao):
            self.grade.setRowCount(0)
            self.timer.stop()
            for botao in self.acoes[:3]:
                botao.setEnabled(False)
        return False

    def atualizar(self):
        try:
            self.exigir_acesso()
            selecionado = self.selecionado()
            setor_id = self.setor.currentData()
            setores = [(None, "Todos")] + [
                (r["id"], r["nome"]) for r in self.ctx.banco.todos(
                    "SELECT id, nome FROM setores_impressao WHERE ativo = 1 ORDER BY ordem, nome")]
            self.setor.blockSignals(True)
            try:
                self.setor.clear()
                for id_, nome in setores:
                    self.setor.addItem(nome, id_)
                self.setor.setCurrentIndex(max(0, self.setor.findData(setor_id)))
            finally:
                self.setor.blockSignals(False)
            itens = self.ctx.preparo.fila(self.setor.currentData())
            self.grade.setRowCount(len(itens))
            for linha, item in enumerate(itens):
                valores = (
                    item["posicao_rotulo"], item["produto"], fmt_qtd(item["quantidade"]),
                    item["observacao"] or "", item["minutos"], SITUACOES[item["status_preparo"]],
                )
                for coluna, valor in enumerate(valores):
                    celula = QTableWidgetItem(str(valor))
                    celula.setData(Qt.ItemDataRole.UserRole, item["id"])
                    self.grade.setItem(linha, coluna, celula)
                if item["id"] == selecionado:
                    self.grade.selectRow(linha)
            self.mensagem.setText(f"{len(itens)} item(ns) aguardando preparo ou entrega.")
            for botao in self.acoes[:3]:
                botao.setEnabled(True)
            if self.isVisible():
                self.timer.start()
            return True
        except ErroNegocio as erro:
            return self._erro(erro)

    def _alterar(self, acao):
        try:
            self.exigir_acesso()
            item_id = self.selecionado()
            if item_id is None:
                raise ErroNegocio("Selecione um item da lista.")
            # A seleção pode ter ficado obsoleta desde o último pulso do painel.
            if item_id not in {i["id"] for i in self.ctx.preparo.fila(self.setor.currentData())}:
                raise ErroNegocio("O item não está mais na fila. Atualize o painel.")
            acao(self.ctx.preparo, item_id)
            return self.atualizar()
        except ErroNegocio as erro:
            return self._erro(erro)

    def marcar(self, status):
        return self._alterar(lambda preparo, item_id: preparo.marcar(item_id, status))

    def avancar(self):
        return self._alterar(lambda preparo, item_id: preparo.avancar(item_id))

    def showEvent(self, evento):
        super().showEvent(evento)
        self.atualizar()

    def hideEvent(self, evento):
        self.timer.stop()
        super().hideEvent(evento)

    def done(self, resultado):
        self.timer.stop()
        super().done(resultado)

    def closeEvent(self, evento):
        self.timer.stop()
        super().closeEvent(evento)
