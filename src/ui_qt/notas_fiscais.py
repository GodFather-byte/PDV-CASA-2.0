"""Notas fiscais (NFC-e): a lista do que foi emitido, com reenviar, cancelar, CPF na nota e reimpressão.

A emissão em si roda no `ServicoFiscal`, em segundo plano. Esta janela só mostra a situação e dá as ações do
gerente. Ligar a emissão (homologação ou produção) também é por aqui, para gravar a hora em que começou.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QGridLayout, QHBoxLayout, QInputDialog, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers.fiscal_controller import FiscalController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.ui_qt.tema import texto

SITUACOES = {
    "pendente": "Aguardando envio", "processando": "Na SEFAZ", "autorizada": "Autorizada",
    "rejeitada": "Rejeitada", "erro": "Cadastro incompleto", "cancelada": "Cancelada",
}
AMBIENTES = {"desligada": "Desligada", "homologacao": "Homologação (teste, sem valor fiscal)",
             "producao": "Produção (vale como nota)"}


class JanelaNotasFiscais(QDialog):
    def __init__(self, ctx, parent=None, controller=None):
        super().__init__(parent)
        self.ctx = ctx
        self.ctx.acesso.exigir(self.ctx.acesso.operador(ctx.operador_id), "fiscal_nfce")
        self.fiscal = controller or FiscalController(ctx.banco, operador_id=ctx.operador_id)
        self.setWindowTitle("Notas fiscais (NFC-e)")
        self.resize(1150, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Notas fiscais (NFC-e)", "titulo"))
        self.estado = texto("")
        layout.addWidget(self.estado)
        linha = QHBoxLayout()
        self.filtro = QComboBox()
        self.filtro.addItem("Todas", None)
        for chave, nome in SITUACOES.items():
            self.filtro.addItem(nome, chave)
        self.filtro.currentIndexChanged.connect(self.atualizar)
        linha.addWidget(texto("Mostrar:", quebra=False))
        linha.addWidget(self.filtro)
        linha.addStretch(1)
        layout.addLayout(linha)
        self.grade = QTableWidget(0, 8)
        self.grade.setHorizontalHeaderLabels(("Cupom", "Venda em", "Total", "Situação", "Nº NFC-e", "CPF",
                                              "Tentativas", "Mensagem"))
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
            ("btn_reenviar", "Reenviar selecionada", self.reenviar),
            ("btn_cpf", "CPF na nota", self.informar_cpf),
            ("btn_reimprimir", "Reimprimir cupom fiscal", self.reimprimir),
            ("btn_cancelar", "Cancelar nota", self.cancelar),
            ("btn_ligar", "Ligar / desligar emissão", self.ligar),
            ("btn_fechar", "Fechar (Esc)", self.close),
        )):
            botao = QPushButton(rotulo)
            botao.clicked.connect(acao)
            setattr(self, atributo, botao)
            barra.addWidget(botao, indice // 4, indice % 4)
        layout.addLayout(barra)
        QShortcut(QKeySequence("F5"), self, activated=self.atualizar)
        self.atualizar()

    # ------------------------------------------------------------ lista
    def atualizar(self):
        ambiente = self.fiscal.ambiente() or "desligada"
        resumo = self.fiscal.resumo()
        partes = [f"{SITUACOES[s]}: {resumo[s]}" for s in SITUACOES if resumo.get(s)]
        self.estado.setText(f"Emissão: {AMBIENTES.get(ambiente, ambiente)}"
                            + (" • " + " • ".join(partes) if partes else ""))
        try:
            notas = self.fiscal.notas(self.filtro.currentData())
        except Exception as erro:
            self.mensagem.setText(f"Não foi possível ler as notas: {erro}")
            return False
        self.grade.setRowCount(len(notas))
        for linha, nota in enumerate(notas):
            valores = (nota["cupom"] or "", fmt.fmt_datahora(nota["fechada_em"]), fmt.fmt_num(nota["total_cent"]),
                       SITUACOES.get(nota["situacao"], nota["situacao"]),
                       f"{nota['numero'] or ''}/{nota['serie'] or ''}".strip("/"), nota["cpf"] or "",
                       nota["tentativas"], nota["mensagem"] or "")
            for coluna, valor in enumerate(valores):
                celula = QTableWidgetItem(str(valor))
                celula.setData(Qt.ItemDataRole.UserRole, nota["id"])
                self.grade.setItem(linha, coluna, celula)
        self.mensagem.setText(f"{len(notas)} nota(s), das mais novas para as mais antigas.")
        return True

    def _selecionada(self):
        linhas = self.grade.selectionModel().selectedRows()
        if not linhas:
            QMessageBox.warning(self, "Notas fiscais", "Selecione uma nota da lista.")
            return None
        return self.grade.item(linhas[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def _executar(self, acao, *args):
        try:
            resultado = acao(*args)
        except ErroNegocio as erro:
            QMessageBox.warning(self, "Notas fiscais", str(erro))
            return None
        self.atualizar()
        return resultado

    # ------------------------------------------------------------ ações
    def reenviar(self):
        nota_id = self._selecionada()
        if nota_id is not None:
            situacao = self._executar(self.fiscal.reenviar, nota_id)
            if situacao:
                self.mensagem.setText(f"Nota reenviada: {SITUACOES.get(situacao, situacao)}.")

    def informar_cpf(self):
        nota_id = self._selecionada()
        if nota_id is None:
            return
        cpf, ok = QInputDialog.getText(self, "CPF na nota", "CPF do consumidor (só para nota ainda não autorizada):")
        if ok:
            self._executar(self.fiscal.informar_cpf, nota_id, cpf)

    def reimprimir(self):
        nota_id = self._selecionada()
        if nota_id is not None and self._executar(self.fiscal.reimprimir, nota_id):
            self.mensagem.setText("Cupom fiscal mandado para a impressora.")

    def cancelar(self):
        nota_id = self._selecionada()
        if nota_id is None:
            return
        motivo, ok = QInputDialog.getText(
            self, "Cancelar NFC-e",
            "Motivo do cancelamento (15 a 255 letras). Só dá até 30 minutos depois da autorização:")
        if ok and self._executar(self.fiscal.cancelar, nota_id, motivo):
            self.mensagem.setText("Nota cancelada na SEFAZ.")

    def ligar(self):
        opcoes = list(AMBIENTES.values())
        atual = list(AMBIENTES).index(self.fiscal.ambiente() or "desligada")
        escolha, ok = QInputDialog.getItem(self, "Emissão de NFC-e", "Emissão:", opcoes, atual, False)
        if not ok:
            return
        ambiente = list(AMBIENTES)[opcoes.index(escolha)]
        if ambiente == "producao" and QMessageBox.question(
                self, "Emissão de NFC-e",
                "Em produção cada venda vira nota fiscal de verdade. Já testou em homologação e o contador conferiu?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._executar(self.fiscal.ligar, ambiente)
