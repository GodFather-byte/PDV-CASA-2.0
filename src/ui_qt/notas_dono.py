"""Notas de compra que o dono enviou pelo painel: a fila de conferência do caixa."""
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QInputDialog, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto

SITUACOES = {"lancada": "Lançada no estoque", "recusada": "Recusada"}


def _data_hora(texto_iso) -> str:
    """'2026-11-10 21:40:00' vira '10/11 21:40'."""
    t = str(texto_iso or "")
    return f"{t[8:10]}/{t[5:7]} {t[11:16]}" if len(t) >= 16 else "-"


class JanelaNotasDono(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Notas enviadas pelo dono")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Notas enviadas pelo dono", "titulo"))
        layout.addWidget(texto(
            "O dono subiu estas notas de compra pelo painel. Confira os itens e confirme para dar entrada no estoque. "
            "Nada entra sozinho. O que você decidir aqui aparece para ele no painel.", "suave"))
        self.grade = QTableWidget(0, 4)
        self.grade.setHorizontalHeaderLabels(["Fornecedor", "Nota", "Enviada em", "Situação"])
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade.verticalHeader().setVisible(False)
        cabecalho = self.grade.horizontalHeader()
        for coluna, modo in enumerate((QHeaderView.ResizeMode.Stretch, QHeaderView.ResizeMode.ResizeToContents,
                                       QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch)):
            cabecalho.setSectionResizeMode(coluna, modo)
        self.grade.itemSelectionChanged.connect(self._habilitar)
        self.grade.itemDoubleClicked.connect(lambda *_: self.conferir())
        layout.addWidget(self.grade, 1)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        barra = QHBoxLayout()
        self.btn_conferir = QPushButton("Conferir e lançar")
        self.btn_conferir.setObjectName("primario")
        self.btn_conferir.clicked.connect(self.conferir)
        self.btn_recusar = QPushButton("Recusar…")
        self.btn_recusar.clicked.connect(self.recusar)
        self.btn_buscar = QPushButton("Buscar agora")
        self.btn_buscar.setToolTip("Consulta a nuvem agora, sem esperar a próxima sincronização.")
        self.btn_buscar.clicked.connect(self.buscar_agora)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.close)
        for botao in (self.btn_conferir, self.btn_recusar, self.btn_buscar, fechar):
            barra.addWidget(botao)
        layout.addLayout(barra)
        self.ids = []
        self.atualizar()

    # ------------------------------------------------------------------ tela
    def atualizar(self):
        notas = self.ctx.notas_dono
        pendentes, recentes = notas.pendentes(), notas.recentes(15)
        self.ids = [n["id"] for n in pendentes] + [None] * len(recentes)
        self.grade.setRowCount(len(pendentes) + len(recentes))
        for linha, nota in enumerate(pendentes + recentes):
            situacao = "Esperando conferência" if nota["situacao"] == "pendente" else SITUACOES[nota["situacao"]]
            if nota["situacao"] == "recusada" and nota["detalhe"]:
                situacao += f": {nota['detalhe']}"
            for coluna, valor in enumerate((nota["emitente"] or "Fornecedor não informado", nota["numero"] or "-",
                                            _data_hora(nota["enviada_em"] or nota["recebida_em"]), situacao)):
                self.grade.setItem(linha, coluna, QTableWidgetItem(valor))
        if pendentes:
            self.grade.selectRow(0)
            self.mensagem.setText(f"{len(pendentes)} nota(s) esperando conferência.")
        else:
            self.mensagem.setText("Nenhuma nota esperando. Quando o dono enviar pelo painel, ela aparece aqui.")
        self._habilitar()

    def _selecionada(self):
        linha = self.grade.currentRow()
        return self.ids[linha] if 0 <= linha < len(self.ids) else None

    def _habilitar(self):
        tem = self._selecionada() is not None
        self.btn_conferir.setEnabled(tem)
        self.btn_recusar.setEnabled(tem)

    def _exigir(self, com_custo: bool = True):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre com um operador para conferir as notas.")
        self.ctx.acesso.exigir(self.ctx.acesso.operador(self.ctx.operador_id), "lanc_estoque")
        if com_custo and not self.ctx.pode("rel_custo"):
            raise ErroPermissao("A nota traz os custos da compra: só o gerente confere e lança.")

    # ----------------------------------------------------------------- ações
    def conferir(self):
        """Abre a mesma conferência do XML importado pelo arquivo; confirmada, a nota sai da fila."""
        nota_id = self._selecionada()
        if nota_id is None:
            return False
        try:
            self._exigir()
            previa = self.ctx.notas_dono.previa(nota_id)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            self.ctx.notas_dono.conciliar()
            return False
        from src.ui_qt.importar_produtos import JanelaImportarNFe
        aceito = JanelaImportarNFe(self, previa).exec() == QDialog.DialogCode.Accepted
        if aceito:
            self.ctx.notas_dono.marcar_lancada(nota_id)
        self.atualizar()
        if aceito:
            self.mensagem.setText(f"NF-e {previa.numero} lançada no estoque. O dono vê isso no painel na próxima sincronização.")
        return aceito

    def recusar(self):
        nota_id = self._selecionada()
        if nota_id is None:
            return False
        motivo, aceito = QInputDialog.getText(
            self, "Recusar nota", "Motivo da recusa (aparece para o dono no painel):")
        if not aceito:
            return False
        try:
            self._exigir(com_custo=False)
            self.ctx.notas_dono.recusar(nota_id, motivo)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        self.atualizar()
        self.mensagem.setText("Nota recusada. O dono vê o motivo no painel na próxima sincronização.")
        return True

    def buscar_agora(self, http=None):
        from src.sync import notas_dono
        try:
            resultado = notas_dono.sincronizar(self.ctx.banco, http or None, forcar=True)
        except (RuntimeError, ValueError) as erro:
            self.mensagem.setText(str(erro))
            return False
        self.atualizar()
        if resultado is None:
            self.mensagem.setText("O painel do dono está desligado nesta loja (Configurações > Conexão com a nuvem).")
            return False
        if resultado["novas"]:
            self.mensagem.setText(f"{resultado['novas']} nota(s) nova(s) chegaram.")
        elif not self.ctx.notas_dono.quantidade():
            self.mensagem.setText(f"Nenhuma nota nova na nuvem ({fmt.agora()[11:16]}).")
        return True
