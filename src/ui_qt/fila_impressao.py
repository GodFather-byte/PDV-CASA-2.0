"""Gestão Qt independente da fila, com atualização manual e sem envio automático."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QGridLayout, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.core import formatacao as fmt
from src.core.erros import ErroPermissao
from src.ui_qt.tema import texto


STATUS = {
    "pendente": "Aguardando", "enviado": "Enviado (sem confirmação física)",
    "erro": "Erro", "cancelado": "Cancelado",
    "enviando": "Em envio", "incerto": "Interrompido: conferir papel",
}
DESTINO = {"caixa": "Caixa", "remota": "Cozinha/bar"}


class JanelaFilaImpressao(QDialog):
    LIMITE = 300

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._exigir_acesso()
        self.fila = ctx.impressao.fila
        self.setWindowTitle("Fila de impressão")
        self.resize(1200, 580)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Fila de impressão", "titulo"))
        layout.addWidget(texto(
            "Enfileiramento e status de envio não confirmam a saída do papel. "
            "Confira fisicamente a impressão antes de reenviar para evitar duplicatas. "
            "Cancelar não recolhe documentos já enviados ou em processamento. "
            "Atualização manual (F5); esta janela não processa a fila.", "suave"))
        self.indicador = texto("")
        layout.addWidget(self.indicador)
        self.grade = QTableWidget(0, 8)
        self.grade.setHorizontalHeaderLabels((
            "Nº", "Gerado em", "Destino", "Documento", "Situação",
            "Tentativas", "Próxima tentativa", "Último erro",
        ))
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.setAlternatingRowColors(True)
        self.grade.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.grade)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        barra = QGridLayout()
        for indice, (atributo, rotulo, acao) in enumerate((
            ("btn_atualizar", "Atualizar (F5)", self.atualizar),
            ("btn_reenviar", "Reenviar selecionado", self.reenviar),
            ("btn_reenviar_todos", "Reenviar pendentes e erros", self.reenviar_todos),
            ("btn_cancelar", "Cancelar selecionado", self.cancelar),
            ("btn_limpar", "Limpar enviados/cancelados", self.limpar),
            ("btn_teste", "Enviar página de teste", self.teste),
            ("btn_confirmar_papel", "Confirmar papel interrompido", lambda: self.conferir(True)),
            ("btn_autorizar_reenvio", "Autorizar reenvio interrompido", lambda: self.conferir(False)),
            ("btn_fechar", "Fechar (Esc)", self.close),
        )):
            botao = QPushButton(rotulo)
            botao.clicked.connect(acao)
            setattr(self, atributo, botao)
            barra.addWidget(botao, indice // 3, indice % 3)
        layout.addLayout(barra)
        QShortcut(QKeySequence("F5"), self, activated=self.atualizar)
        self.atualizar()

    def _exigir_acesso(self):
        operador_id = self.ctx.operador_id
        if operador_id is None:
            raise ErroPermissao("Entre novamente para acessar a fila de impressão.")
        cadastro = self.ctx.cadastros.obter("operadores", operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo ou removido. Encerre a sessão.")
        operador = self.ctx.acesso.operador(operador_id)
        self.ctx.acesso.exigir(operador, "util_fila_impressao")

    def _autorizar(self):
        try:
            self._exigir_acesso()
        except ErroPermissao as erro:
            self.grade.setRowCount(0)
            self.indicador.clear()
            self.mensagem.setText(str(erro))
            QMessageBox.warning(self, "Acesso não permitido", str(erro))
            return False
        return True

    def _id_selecionado(self):
        linhas = self.grade.selectionModel().selectedRows()
        if not linhas:
            return None
        return self.grade.item(linhas[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def _selecionado(self):
        item_id = self._id_selecionado()
        if item_id is None:
            QMessageBox.warning(self, "Fila de impressão", "Selecione um item da lista.")
        return item_id

    def atualizar(self):
        if not self._autorizar():
            return False
        selecionado = self._id_selecionado()
        try:
            itens = self.fila.listar(self.LIMITE)
            indicador, nivel = self.fila.texto_indicador()
        except Exception as erro:
            self.grade.setRowCount(0)
            self.indicador.clear()
            self.mensagem.setText(f"Não foi possível atualizar a fila: {erro}")
            return False
        self.grade.clearSelection()
        self.grade.setRowCount(len(itens))
        for linha, item in enumerate(itens):
            valores = (
                item["id"], fmt.fmt_datahora(item["criado_em"]),
                DESTINO.get(item["destino"], item["destino"]), item["nome"],
                STATUS.get(item["status"], item["status"]), item["tentativas"],
                fmt.fmt_hora(item["proxima_tentativa"])
                if item["status"] == "pendente" else "", item["ultimo_erro"] or "",
            )
            for coluna, valor in enumerate(valores):
                celula = QTableWidgetItem(str(valor))
                celula.setData(Qt.ItemDataRole.UserRole, item["id"])
                self.grade.setItem(linha, coluna, celula)
            if item["id"] == selecionado:
                self.grade.selectRow(linha)
        rotulo = {"ok": "OK", "aviso": "ATENÇÃO", "erro": "ERRO"}.get(nivel, "INFO")
        self.indicador.setText(f"{rotulo} • {indicador}")
        self.mensagem.setText(f"{len(itens)} registro(s) • até {self.LIMITE} mais recentes.")
        return True

    def _confirmar(self, mensagem):
        return QMessageBox.question(
            self, "Fila de impressão", mensagem,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def _executar(self, acao, *args, **kwargs):
        if not self._autorizar():
            return
        try:
            resultado = acao(*args, **kwargs)
        except Exception as erro:
            detalhe = str(erro).replace(
                "Este item já foi impresso.",
                "Este item não está disponível para reenvio; atualize a lista.")
            QMessageBox.warning(self, "Fila de impressão", f"Operação não concluída: {detalhe}")
            return
        self.atualizar()
        return resultado

    def reenviar(self):
        if not self._autorizar():
            return
        item_id = self._selecionado()
        if item_id is not None:
            self._executar(self.fila.reenviar, item_id)

    def reenviar_todos(self):
        quantidade = self._executar(self.fila.reenviar_todos)
        if quantidade is not None:
            QMessageBox.information(
                self, "Fila de impressão",
                f"{quantidade} registro(s) devolvido(s) à fila. "
                "Isso não confirma a impressão física.")

    def conferir(self, impresso):
        if not self._autorizar():
            return
        item_id = self._selecionado()
        mensagem = ("Confirma que este documento saiu completo no papel? Não será reenviado."
                    if impresso else
                    "Conferiu fisicamente e autoriza um novo envio? Se o anterior saiu, haverá duplicata.")
        if item_id is not None and self._confirmar(mensagem):
            self._executar(self.fila.conferir_interrompido, item_id, impresso=impresso,
                           operador_id=self.ctx.operador_id)

    def cancelar(self):
        if not self._autorizar():
            return
        item_id = self._selecionado()
        if item_id is not None and self._confirmar(
                "Cancelar este documento na fila? Isso não interrompe um envio em andamento "
                "nem recolhe papel já emitido."):
            self._executar(self.fila.cancelar, item_id)

    def limpar(self):
        if self._autorizar() and self._confirmar(
                "Remover todos os registros com status enviado ou cancelado? "
                "Pendentes e erros serão preservados. Esta limpeza não confirma saída de papel."):
            quantidade = self._executar(self.fila.limpar_antigos, 0)
            if quantidade is not None:
                QMessageBox.information(
                    self, "Fila de impressão", f"{quantidade} registro(s) removido(s).")

    def teste(self):
        if not self._autorizar() or not self._confirmar(
                "Solicitar uma página de teste à impressora térmica configurada? "
                "Isso pode gerar impressão real; confira o papel na impressora."):
            return
        if not self._autorizar():
            return
        try:
            self.ctx.impressao.imprimir_teste()
        except Exception as erro:
            QMessageBox.warning(self, "Teste de impressão",
                                f"O envio do teste não foi confirmado: {erro}")
            return
        QMessageBox.information(
            self, "Teste de impressão",
            "Solicitação de teste concluída. Confira fisicamente se o papel saiu; "
            "o retorno da API não confirma a impressão.")
