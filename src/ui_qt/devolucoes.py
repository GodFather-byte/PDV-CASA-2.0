"""Devolução/troca de venda fechada pelo cupom original (Qt). Regras em docs/DEVOLUCOES.md."""
from __future__ import annotations

import uuid as _uuid

from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers.devolucoes_controller import MODULO, MODOS, DevolucoesController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.ui_qt.tema import texto

COLUNAS = ["Produto", "Vendida", "Devolvida", "Saldo", "Líquido", "A devolver", "Estoque"]
TENTATIVAS_SUPERVISOR = 3


class JanelaDevolucoes(QDialog):
    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        self.exigir_acesso()
        super().__init__(parent)
        self.setWindowTitle("Devolução / troca de venda")
        self.resize(1100, 760)
        self.situacao = None
        self.escolhas: dict[int, dict] = {}
        self.formas: list[tuple[int, str]] = []
        self.ultima = None
        self._novo_uuid()
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Devolução / troca de venda fechada", "titulo"))
        busca = QHBoxLayout()
        self.cupom = QLineEdit()
        self.cupom.setPlaceholderText("Cupom original")
        self.cupom.returnPressed.connect(self.buscar)
        busca.addWidget(self.cupom)
        botao = QPushButton("Buscar")
        botao.clicked.connect(self.buscar)
        busca.addWidget(botao)
        self.cabecalho = texto("", "suave")
        busca.addWidget(self.cabecalho, 1)
        layout.addLayout(busca)

        self.grade = QTableWidget(0, len(COLUNAS))
        self.grade.setHorizontalHeaderLabels(COLUNAS)
        self.grade.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.grade.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grade.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.grade.itemSelectionChanged.connect(self._carregar_linha)
        layout.addWidget(self.grade, 1)

        linha = QHBoxLayout()
        self.quantidade = QLineEdit()
        self.quantidade.setPlaceholderText("Quantidade (até 4 casas)")
        self.estoque = QCheckBox("Volta ao estoque")
        linha.addWidget(self.quantidade)
        linha.addWidget(self.estoque)
        for rotulo, acao in (("Aplicar ao item", self.aplicar), ("Devolver tudo", self.tudo),
                             ("Limpar", self.limpar_escolhas)):
            b = QPushButton(rotulo)
            b.clicked.connect(acao)
            linha.addWidget(b)
        linha.addStretch()
        layout.addLayout(linha)

        form = QFormLayout()
        self.modo = QComboBox()
        self.modo.currentIndexChanged.connect(lambda _i: self._carregar_formas())
        self.forma = QComboBox()
        self.referencia = QLineEdit()
        self.motivo = QLineEdit()
        form.addRow("Reembolso", self.modo)
        form.addRow("Forma", self.forma)
        form.addRow("Referência do estorno externo (NSU/Pix)", self.referencia)
        form.addRow("Motivo (obrigatório)", self.motivo)
        layout.addLayout(form)
        opcoes = QHBoxLayout()
        self.troca = QCheckBox("É troca (abre nova venda depois)")
        self.extras = QCheckBox("Devolver taxa/acréscimo se completar a venda")
        self.extras.setChecked(True)
        self.extras.toggled.connect(lambda _v: self.atualizar_previa())
        opcoes.addWidget(self.troca)
        opcoes.addWidget(self.extras)
        opcoes.addStretch()
        layout.addLayout(opcoes)
        self.previa = texto("", "subtitulo")
        self.previa.setWordWrap(True)
        layout.addWidget(self.previa)
        acoes = QHBoxLayout()
        self.btn_registrar = QPushButton("Registrar devolução")
        self.btn_registrar.clicked.connect(self.registrar)
        self.btn_reimprimir = QPushButton("Reimprimir comprovante")
        self.btn_reimprimir.clicked.connect(self.reimprimir)
        self.btn_reimprimir.setEnabled(False)
        self.btn_troca = QPushButton("Abrir venda da troca")
        self.btn_troca.clicked.connect(self.abrir_troca)
        self.btn_troca.setEnabled(False)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.close)
        for b in (self.btn_registrar, self.btn_reimprimir, self.btn_troca):
            acoes.addWidget(b)
        acoes.addStretch()
        acoes.addWidget(fechar)
        layout.addLayout(acoes)
        self.mensagem = texto("", "aviso")
        self.mensagem.setWordWrap(True)
        layout.addWidget(self.mensagem)

    # ------------------------------------------------------------ apoio
    def _controller(self) -> DevolucoesController:
        return DevolucoesController(self.ctx.banco, self.ctx.operador_id)

    def exigir_acesso(self) -> None:
        self._controller().exigir_acesso()

    def _novo_uuid(self) -> None:
        self.uuid = str(_uuid.uuid4())

    def buscar(self):
        try:
            self.exigir_acesso()
            v = self._controller().venda_por_cupom(self.cupom.text())
            self.situacao = self._controller().situacao(v["id"])
        except ErroNegocio as e:
            self.situacao = None
            self._preencher()
            self.mensagem.setText(str(e))
            return False
        self.escolhas = {}
        self._novo_uuid()
        self._preencher()
        self.mensagem.setText("")
        return True

    def _preencher(self):
        self.grade.blockSignals(True)
        self.grade.setRowCount(0)
        s = self.situacao
        if s is None:
            self.grade.blockSignals(False)
            self.cabecalho.setText("")
            self.modo.clear()
            self.previa.setText("")
            return
        v = s["venda"]
        self.cabecalho.setText(f"Cupom {v['cupom']} — {fmt.fmt_datahora(v['fechada_em'])} — total "
                               f"{fmt.fmt_brl(s['total_cent'])} — já devolvido {fmt.fmt_brl(s['devolvido_cent'])}")
        for linha, it in enumerate(s["itens"]):
            e = self.escolhas.get(it["item_id"])
            self.grade.insertRow(linha)
            valores = (it["nome"], fmt.fmt_qtd(it["quantidade"], 4), fmt.fmt_qtd(it["devolvida"], 4),
                       fmt.fmt_qtd(it["saldo"], 4), fmt.fmt_brl(it["liquido_cent"]),
                       fmt.fmt_qtd(e["quantidade"], 4) if e else "",
                       ("Sim" if e["retorna_estoque"] else "Não") if e else "")
            for col, valor in enumerate(valores):
                self.grade.setItem(linha, col, QTableWidgetItem(valor))
        self.grade.blockSignals(False)
        atual = self._modo()
        self.modo.blockSignals(True)
        self.modo.clear()
        for m in s["modos"]:
            self.modo.addItem(MODOS[m], m)
        if atual in s["modos"]:
            self.modo.setCurrentIndex(s["modos"].index(atual))
        self.modo.blockSignals(False)
        self._carregar_formas()
        self.atualizar_previa()

    def _modo(self) -> str | None:
        return self.modo.currentData() if self.situacao is not None else None

    def _carregar_formas(self):
        modo = self._modo()
        if modo == "dinheiro_gaveta":
            self.formas = [(f["id"], f["tipo"]) for f in self._controller().formas_dinheiro()]
        elif modo == "externo" and self.situacao is not None:
            self.formas = [(f["tipo_pagamento_id"], f"{f['tipo']} (pago {fmt.fmt_brl(f['pago_cent'])}, estornado "
                            f"{fmt.fmt_brl(f['estornado_externo_cent'])})")
                           for f in self.situacao["formas"] if not f["na_gaveta"]]
        else:
            self.formas = []
        self.forma.clear()
        for fid, rotulo in self.formas:
            self.forma.addItem(rotulo, fid)

    def _item_selecionado(self) -> dict | None:
        linha = self.grade.currentRow()
        if self.situacao is None or not 0 <= linha < len(self.situacao["itens"]):
            return None
        return self.situacao["itens"][linha]

    def _carregar_linha(self):
        it = self._item_selecionado()
        if it is None:
            return
        e = self.escolhas.get(it["item_id"])
        self.quantidade.setText(fmt.fmt_qtd(e["quantidade"] if e else it["saldo"], 4))
        self.estoque.setChecked(e["retorna_estoque"] if e else it["sugere_estoque"])

    def aplicar(self):
        it = self._item_selecionado()
        if it is None:
            self.mensagem.setText("Escolha o item na lista.")
            return False
        try:
            q = fmt.para_qtd(self.quantidade.text())
        except (ErroNegocio, ValueError) as e:
            self.mensagem.setText(str(e) or "Quantidade inválida.")
            return False
        if q <= 0:
            self.escolhas.pop(it["item_id"], None)
        else:
            self.escolhas[it["item_id"]] = {"item_id": it["item_id"], "quantidade": q,
                                            "retorna_estoque": self.estoque.isChecked()}
        self._preencher()
        return True

    def tudo(self):
        if self.situacao is None:
            return
        self.escolhas = {i["item_id"]: {"item_id": i["item_id"], "quantidade": i["saldo"],
                                        "retorna_estoque": i["sugere_estoque"]}
                         for i in self.situacao["itens"] if i["saldo"] > 0}
        self._preencher()

    def limpar_escolhas(self):
        self.escolhas = {}
        self._preencher()

    def atualizar_previa(self):
        if self.situacao is None or not self.escolhas:
            self.previa.setText("Escolha os itens e as quantidades a devolver." if self.situacao else "")
            return None
        try:
            p = self._controller().previa(self.situacao["venda"]["id"], list(self.escolhas.values()),
                                          self.extras.isChecked())
        except ErroNegocio as e:
            self.previa.setText(str(e))
            return None
        self.previa.setText(
            f"Itens {fmt.fmt_brl(p['itens_bruto_cent'])}  − desconto rateado {fmt.fmt_brl(p['desconto_rateado_cent'])}"
            f"  + serviço rateado {fmt.fmt_brl(p['servico_rateado_cent'])}  + taxa/acréscimo "
            f"{fmt.fmt_brl(p['extras_cent'])}\nA DEVOLVER: {fmt.fmt_brl(p['valor_cent'])}"
            + ("  (completa a venda)" if p["completa"] else ""))
        return p
    # ------------------------------------------------------------ gravação
    def _confirmar(self, pergunta: str) -> bool:
        return QMessageBox.question(self, "Devolução", pergunta) == QMessageBox.Yes

    def _autorizador(self) -> int | None:
        if self._controller().operador_autoriza():
            return self.ctx.operador_id
        for _ in range(TENTATIVAS_SUPERVISOR):
            senha, ok = QInputDialog.getText(self, "Autorização", "Devolução de venda\nDigite uma senha válida:",
                                             QLineEdit.Password)
            if not ok:
                return None
            try:
                sup = self.ctx.acesso.validar_supervisor(senha, MODULO)
            except ErroNegocio as e:
                QMessageBox.warning(self, "Autorização", str(e))
                return None
            if sup is not None:
                return sup.id
            QMessageBox.warning(self, "Autorização", "Senha inválida ou sem permissão para esta operação.")
        return None

    def registrar(self):
        try:
            self.exigir_acesso()
        except ErroNegocio as e:
            self.mensagem.setText(str(e))
            return None
        if self.situacao is None:
            self.mensagem.setText("Busque o cupom original.")
            return None
        if not self.escolhas:
            self.mensagem.setText("Escolha pelo menos um item a devolver.")
            return None
        if not " ".join(self.motivo.text().split()):
            self.mensagem.setText("Informe o motivo da devolução.")
            return None
        modo = self._modo()
        forma = self.forma.currentData()
        p = self.atualizar_previa()
        if p is None:
            return None
        if not self._confirmar(f"Registrar devolução de {fmt.fmt_brl(p['valor_cent'])} como '{MODOS[modo]}'?\n"
                               "O registro não pode ser desfeito."):
            return None
        autorizado = self._autorizador()
        if autorizado is None:
            self.mensagem.setText("Devolução não autorizada.")
            return None
        try:
            dev = self.ctx.caixa.devolver(
                self.situacao["venda"]["id"], list(self.escolhas.values()), self.motivo.text(), autorizado, modo,
                self.uuid, tipo_pagamento_id=forma, referencia_externa=self.referencia.text(),
                troca=self.troca.isChecked(), reembolsar_extras=self.extras.isChecked())
        except ErroNegocio as e:
            self.mensagem.setText(str(e))
            return None                     # mesmo uuid na próxima tentativa: nada é gravado em dobro
        self.ultima = dev
        self._novo_uuid()
        self.motivo.clear()
        self.referencia.clear()
        self.escolhas = {}
        self.btn_reimprimir.setEnabled(True)
        self.btn_troca.setEnabled(bool(dev["troca"]))
        aviso = " (já estava registrada)" if dev.get("repetida") else ""
        self.mensagem.setText(f"Devolução registrada{aviso}: {fmt.fmt_brl(dev['valor_cent'])}.")
        try:
            self.situacao = self._controller().situacao(dev["venda_id"])
        except ErroNegocio:
            self.situacao = None
        self._preencher()
        if not dev.get("repetida"):
            self._imprimir(abrir_gaveta=dev["reembolso_modo"] == "dinheiro_gaveta" and dev["valor_cent"] > 0)
        return dev

    def _imprimir(self, abrir_gaveta: bool = False) -> bool:
        """Falha de impressão nunca refaz a devolução: o registro já está gravado; resta reimprimir."""
        if self.ultima is None:
            return False
        try:
            txt = self._controller().comprovante(self.ultima["id"], self.ctx.impressao.largura())
            self.ctx.impressao.enviar(txt, nome=f"devolucao_{self.ultima['id']}", abrir_gaveta=abrir_gaveta)
            return True
        except Exception as e:  # noqa: BLE001 - a devolução já foi gravada
            QMessageBox.warning(self, "Impressão", f"A devolução foi gravada, mas o comprovante não imprimiu:\n{e}\n"
                                                   "Use 'Reimprimir comprovante'. Não registre de novo.")
            return False

    def reimprimir(self):
        return self._imprimir(abrir_gaveta=False)

    def abrir_troca(self):
        if self.ultima is None:
            return None
        try:
            venda_id = self.ctx.caixa.abrir_troca(self.ultima["id"])
        except ErroNegocio as e:
            self.mensagem.setText(str(e))
            return None
        self.mensagem.setText("Venda da troca aberta no balcão: lance o produto novo pelo caixa.")
        return venda_id