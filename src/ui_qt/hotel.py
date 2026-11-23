"""Recepção do hotel (Will Hotel): o dia, o mapa de reservas, as reservas, os hóspedes, a arrumação, os relatórios e o
cadastro dos quartos e tarifas. As regras ficam em `src/controllers/hotel_controller.py`; o pagamento da conta é no caixa
(a conta da estadia é uma comanda)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QDate, QTime, QTimer, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget,
)

from src.controllers.config_controller import modulos_desligados
from src.controllers.hotel_controller import (
    DOCUMENTOS, GENEROS, LIMPEZA, MEIOS_TRANSPORTE, MOTIVOS_VIAGEM, ORIGENS, SITUACOES, UFS, fmt_cpf, fmt_duracao,
)
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao, ErroValidacao
from src.ui_qt import tema
from src.ui_qt.tema import texto

DIAS_SEMANA = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")

# Cores das situações (fundo no tema escuro, fundo no tema claro). O texto segue o tema.
CORES = {
    "reservada": ("#284d73", "#d3e3f6"),
    "hospedada": ("#245a43", "#cdebd9"),
    "encerrada": ("#363f42", "#e3e6e3"),
    "alerta": ("#5c4719", "#fbe7bf"),
    "estourou": ("#5a2b2b", "#f9d9d4"),
    "limpo": ("#245a43", "#cdebd9"),
    "sujo": ("#5c4719", "#fbe7bf"),
    "arrumando": ("#284d73", "#d3e3f6"),
    "manutencao": ("#5a2b2b", "#f9d9d4"),
}


def _claro(widget) -> bool:
    return widget.palette().window().color().lightness() > 128


def cor(widget, chave: str) -> QColor:
    escuro, claro = CORES[chave]
    return QColor(claro if _claro(widget) else escuro)


def _qdate(iso: str | date | None) -> QDate:
    if isinstance(iso, date):
        return QDate(iso.year, iso.month, iso.day)
    if not iso:
        hoje = fmt.agora_dt().date()
        return QDate(hoje.year, hoje.month, hoje.day)
    d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    return QDate(d.year, d.month, d.day)


def _iso(qdate: QDate) -> str:
    return f"{qdate.year():04d}-{qdate.month():02d}-{qdate.day():02d}"


def _campo_data(iso=None) -> QDateEdit:
    campo = QDateEdit(_qdate(iso))
    campo.setCalendarPopup(True)
    campo.setDisplayFormat("dd/MM/yyyy")
    return campo


def _tabela(cabecalhos, elastica: int | None = None) -> QTableWidget:
    t = QTableWidget(0, len(cabecalhos))
    t.setHorizontalHeaderLabels(cabecalhos)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    cabecalho = t.horizontalHeader()
    cabecalho.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if elastica is not None:
        cabecalho.setSectionResizeMode(elastica, QHeaderView.ResizeMode.Stretch)
    else:
        cabecalho.setStretchLastSection(True)
    return t


def _preencher(tabela: QTableWidget, linhas: list[tuple], dados: list | None = None, fundos: list | None = None) -> None:
    """Linhas de texto; `dados[i]` vai no papel UserRole da primeira coluna (o id); `fundos[i]` pinta a linha."""
    tabela.setRowCount(len(linhas))
    for i, valores in enumerate(linhas):
        for j, valor in enumerate(valores):
            item = QTableWidgetItem("" if valor is None else str(valor))
            if j == 0 and dados is not None:
                item.setData(Qt.ItemDataRole.UserRole, dados[i])
            if fundos is not None and fundos[i] is not None:
                item.setBackground(QBrush(fundos[i]))
            tabela.setItem(i, j, item)


def _selecionado(tabela: QTableWidget):
    """O id da linha escolhida; com uma linha só na lista, ela mesma."""
    linha = tabela.currentRow()
    if linha < 0 and tabela.rowCount() == 1:
        linha = 0
    if linha < 0 or tabela.item(linha, 0) is None:
        return None
    return tabela.item(linha, 0).data(Qt.ItemDataRole.UserRole)


def _botao(rotulo: str, acao, nome: str = "") -> QPushButton:
    b = QPushButton(rotulo)
    if nome:
        b.setObjectName(nome)
    b.clicked.connect(lambda _=False: acao())
    return b


def _noites(e: dict) -> str:
    return f"{e['noites']} noite(s)" if e["modalidade"] == "diaria" else (e.get("periodo") or "Período")


def _quando(e: dict) -> str:
    if e["modalidade"] == "diaria":
        return f"{fmt.fmt_data(e['entrada_prevista'])} a {fmt.fmt_data(e['saida_prevista'])}"
    inicio = e["entrada_em"] or e["entrada_prevista"]
    return f"{fmt.fmt_data(inicio)} {fmt.fmt_hora(inicio)[:5]}–{fmt.fmt_hora(e['saida_prevista'])[:5]}"


# ================================================================== hóspede
class DialogoHospede(QDialog):
    """Ficha do hóspede com os campos da FNRH."""

    def __init__(self, ctx, hospede_id: int | None = None, nome: str = "", parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.hospede_id = hospede_id
        self.setWindowTitle("Ficha do hóspede")
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Ficha do hóspede", "titulo"))
        layout.addWidget(texto("Os campos da Ficha Nacional de Registro de Hóspedes (FNRH). No check-in são obrigatórios o "
                               "documento e a data de nascimento; de brasileiro maior de idade, também o CPF.", "suave"))
        grade = QGridLayout()
        self.campos: dict[str, QWidget] = {}

        def linha(chave, rotulo, widget, lin, col, largura=1):
            grade.addWidget(QLabel(rotulo), lin, col * 2)
            grade.addWidget(widget, lin, col * 2 + 1, 1, largura)
            self.campos[chave] = widget

        def combo(opcoes, editavel=False):
            c = QComboBox()
            c.addItem("")
            c.addItems(list(opcoes))
            c.setEditable(editavel)
            return c

        linha("nome", "Nome completo", QLineEdit(nome), 0, 0, 3)
        linha("cpf", "CPF", QLineEdit(), 1, 0)
        linha("nascimento", "Nascimento", QLineEdit(), 1, 1)
        self.campos["nascimento"].setPlaceholderText("dd/mm/aaaa")
        linha("documento_tipo", "Documento", combo(DOCUMENTOS), 2, 0)
        linha("documento", "Número", QLineEdit(), 2, 1)
        linha("documento_emissor", "Órgão / país", QLineEdit(), 3, 0)
        linha("genero", "Gênero", combo(GENEROS), 3, 1)
        linha("nacionalidade", "Nacionalidade", QLineEdit("Brasileira"), 4, 0)
        linha("profissao", "Profissão", QLineEdit(), 4, 1)
        linha("telefone", "Telefone", QLineEdit(), 5, 0)
        linha("email", "E-mail", QLineEdit(), 5, 1)
        linha("cidade", "Cidade", QLineEdit(), 6, 0)
        linha("uf", "UF", combo(UFS, editavel=True), 6, 1)
        linha("pais", "País", QLineEdit("Brasil"), 7, 0)
        linha("observacao", "Observação", QLineEdit(), 7, 1)
        layout.addLayout(grade)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(self.salvar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)
        if hospede_id:
            self._carregar(ctx.hotel.hospede(hospede_id))

    def _carregar(self, h: dict) -> None:
        for chave, widget in self.campos.items():
            valor = h.get(chave) or ""
            if chave == "nascimento":
                valor = fmt.fmt_data(valor)
            elif chave == "cpf":
                valor = fmt_cpf(valor)
            if isinstance(widget, QComboBox):
                indice = widget.findText(valor)
                if indice >= 0:
                    widget.setCurrentIndex(indice)
                else:
                    widget.setEditText(valor)
            else:
                widget.setText(valor)

    def valores(self) -> dict:
        return {chave: (w.currentText() if isinstance(w, QComboBox) else w.text()) for chave, w in self.campos.items()}

    def salvar(self) -> None:
        try:
            self.hospede_id = self.ctx.hotel.salvar_hospede(self.valores(), self.hospede_id)
        except (ErroNegocio, ErroValidacao) as erro:
            self.mensagem.setText(str(erro))
            return
        self.accept()


class SeletorHospede(QWidget):
    """Busca de hóspede (nome, CPF, telefone) com o botão de cadastrar um novo."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        linha = QHBoxLayout()
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Procurar por nome, CPF ou telefone")
        self.busca.textChanged.connect(self.procurar)
        linha.addWidget(self.busca, 1)
        linha.addWidget(_botao("Novo hóspede", self.novo))
        linha.addWidget(_botao("Editar ficha", self.editar))
        layout.addLayout(linha)
        self.lista = QListWidget()
        self.lista.setMaximumHeight(110)
        layout.addWidget(self.lista)
        self.procurar()

    def procurar(self, *_):
        atual = self.hospede_id()
        self.lista.clear()
        for h in self.ctx.hotel.buscar_hospedes(self.busca.text(), limite=30):
            faltas = self.ctx.hotel._faltas_ficha(h)
            detalhe = fmt_cpf(h["cpf"]) or h["documento"] or "sem documento"
            item = QListWidgetItem(f"{h['nome']} — {detalhe}" + (f"  (falta {', '.join(faltas)})" if faltas else ""))
            item.setData(Qt.ItemDataRole.UserRole, h["id"])
            self.lista.addItem(item)
            if h["id"] == atual:
                self.lista.setCurrentItem(item)

    def hospede_id(self) -> int | None:
        item = self.lista.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def escolher(self, hospede_id: int) -> None:
        h = self.ctx.hotel.hospede(hospede_id)
        self.busca.blockSignals(True)
        self.busca.setText(h["nome"])
        self.busca.blockSignals(False)
        self.procurar()
        for i in range(self.lista.count()):
            if self.lista.item(i).data(Qt.ItemDataRole.UserRole) == hospede_id:
                self.lista.setCurrentRow(i)

    def novo(self) -> None:
        dialogo = DialogoHospede(self.ctx, nome=self.busca.text() if not any(c.isdigit() for c in self.busca.text())
                                 else "", parent=self)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            self.escolher(dialogo.hospede_id)

    def editar(self) -> None:
        hid = self.hospede_id()
        if hid is None:
            return
        dialogo = DialogoHospede(self.ctx, hid, parent=self)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            self.escolher(hid)


# ================================================================== reserva
class DialogoReserva(QDialog):
    """Nova reserva (ou o começo de um check-in sem reserva, com `agora=True`)."""

    def __init__(self, ctx, uh_id: int | None = None, entrada: str | None = None, agora: bool = False, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.agora = agora
        self.estadia_id = None
        self.setWindowTitle("Check-in sem reserva" if agora else "Nova reserva")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.addWidget(texto(self.windowTitle(), "titulo"))
        self.form = form = QFormLayout()
        self.modalidade = QComboBox()
        self.modalidade.addItem("Diária (por noite)", "diaria")
        self.modalidade.addItem("Período (por horas)", "periodo")
        form.addRow("Forma", self.modalidade)
        hoje = fmt.agora_dt().date()
        self.entrada = _campo_data(entrada or hoje)
        self.saida = _campo_data((datetime.strptime(entrada, "%Y-%m-%d").date() if entrada else hoje) + timedelta(days=1))
        self.entrada.setEnabled(not agora)
        datas = QHBoxLayout()
        datas.addWidget(self.entrada)
        datas.addWidget(QLabel("até"))
        datas.addWidget(self.saida)
        self.linha_datas = QWidget()
        self.linha_datas.setLayout(datas)
        datas.setContentsMargins(0, 0, 0, 0)
        form.addRow("Entrada e saída", self.linha_datas)
        self.periodo = QComboBox()
        for p in ctx.hotel.periodos():
            self.periodo.addItem(f"{p['nome']} ({p['duracao']}) — {fmt.fmt_brl(p['preco_cent'])}", p["id"])
        self.hora = QTimeEdit(QTime(fmt.agora_dt().hour, fmt.agora_dt().minute))
        self.hora.setDisplayFormat("HH:mm")
        self.hora.setEnabled(not agora)
        periodo = QHBoxLayout()
        periodo.setContentsMargins(0, 0, 0, 0)
        periodo.addWidget(self.periodo, 1)
        periodo.addWidget(QLabel("às"))
        periodo.addWidget(self.hora)
        self.linha_periodo = QWidget()
        self.linha_periodo.setLayout(periodo)
        form.addRow("Período", self.linha_periodo)
        pessoas = QHBoxLayout()
        pessoas.setContentsMargins(0, 0, 0, 0)
        self.adultos = QSpinBox()
        self.adultos.setRange(1, 20)
        self.criancas = QSpinBox()
        self.criancas.setRange(0, 20)
        pessoas.addWidget(QLabel("Adultos"))
        pessoas.addWidget(self.adultos)
        pessoas.addWidget(QLabel("Crianças"))
        pessoas.addWidget(self.criancas)
        pessoas.addStretch(1)
        form.addRow("Pessoas", pessoas)
        self.uh = QComboBox()
        form.addRow("Quarto livre", self.uh)
        self.nome = QLineEdit()
        self.nome.setPlaceholderText("Quem reserva (ou escolha o hóspede abaixo)")
        form.addRow("Nome", self.nome)
        self.telefone = QLineEdit()
        form.addRow("Telefone", self.telefone)
        self.origem = QComboBox()
        for chave, rotulo in ORIGENS.items():
            self.origem.addItem(rotulo, chave)
        form.addRow("Origem", self.origem)
        self.cafe = QCheckBox("Café da manhã incluso na diária")
        form.addRow("", self.cafe)
        self.observacao = QLineEdit()
        form.addRow("Observação", self.observacao)
        layout.addLayout(form)
        layout.addWidget(texto("Hóspede cadastrado (opcional na reserva, obrigatório no check-in)", "legenda"))
        self.seletor = SeletorHospede(ctx)
        self.seletor.lista.currentItemChanged.connect(self._hospede_escolhido)
        layout.addWidget(self.seletor)
        self.valor = texto("", "subtitulo")
        layout.addWidget(self.valor)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        botoes = QDialogButtonBox()
        self.btn_ok = botoes.addButton("Continuar para o check-in" if agora else "Reservar",
                                       QDialogButtonBox.ButtonRole.AcceptRole)
        botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.confirmar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)
        self._uh_pedida = uh_id
        for sinal in (self.modalidade.currentIndexChanged, self.entrada.dateChanged, self.saida.dateChanged,
                      self.periodo.currentIndexChanged, self.hora.timeChanged, self.adultos.valueChanged,
                      self.criancas.valueChanged):
            sinal.connect(self.atualizar)
        self.uh.currentIndexChanged.connect(self._mostrar_valor)
        self.atualizar()

    def _intervalo(self) -> tuple[str, str]:
        c = self.ctx.hotel.config()
        if self.modalidade.currentData() == "diaria":
            return f"{_iso(self.entrada.date())} {c['checkin']}", f"{_iso(self.saida.date())} {c['checkout']}"
        minutos = next((p["minutos"] for p in self.ctx.hotel.periodos() if p["id"] == self.periodo.currentData()), 60)
        inicio = datetime.combine(datetime.strptime(_iso(self.entrada.date()), "%Y-%m-%d").date(),
                                  datetime.strptime(self.hora.time().toString("HH:mm"), "%H:%M").time())
        if self.agora:
            inicio = fmt.agora_dt()
        return inicio.strftime("%Y-%m-%d %H:%M"), (inicio + timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M")

    def atualizar(self, *_):
        diaria = self.modalidade.currentData() == "diaria"
        self.saida.setVisible(diaria)
        self.form.setRowVisible(self.linha_periodo, not diaria)
        self.form.setRowVisible(self.cafe, diaria)
        escolhido = self.uh.currentData() or self._uh_pedida
        self.uh.blockSignals(True)
        self.uh.clear()
        try:
            inicio, fim = self._intervalo()
            livres = self.ctx.hotel.disponiveis(inicio, fim, self.adultos.value() + self.criancas.value())
        except (ErroNegocio, ErroValidacao) as erro:
            livres = []
            self.mensagem.setText(str(erro))
        for u in livres:
            sujo = "" if u["limpeza"] == "limpo" else f" ({u['limpeza_rotulo'].lower()})"
            self.uh.addItem(f"{u['numero']} — {u['tipo']} (até {u['capacidade']}){sujo}", u["id"])
        indice = self.uh.findData(escolhido)
        self.uh.setCurrentIndex(max(0, indice))
        self.uh.blockSignals(False)
        if not livres:
            self.mensagem.setText("Nenhum quarto livre para essas datas e pessoas.")
        self._mostrar_valor()

    def _mostrar_valor(self, *_):
        uh_id = self.uh.currentData()
        if uh_id is None:
            self.valor.setText("")
            return
        u = self.ctx.hotel.uh(uh_id)
        if self.modalidade.currentData() == "diaria":
            noites = max(1, self.entrada.date().daysTo(self.saida.date()))
            preco = self.ctx.hotel._preco(u["produto_diaria_id"])
            self.cafe.setChecked(bool(u["cafe_incluso"]))
            self.valor.setText(f"{noites} diária(s) × {fmt.fmt_brl(preco)} = {fmt.fmt_brl(noites * preco)}")
        else:
            p = next((p for p in self.ctx.hotel.periodos() if p["id"] == self.periodo.currentData()), None)
            self.valor.setText(f"Período {p['nome']}: {fmt.fmt_brl(p['preco_cent'])}" if p else "Cadastre um período.")
        self.mensagem.setText("")

    def _hospede_escolhido(self, *_):
        hid = self.seletor.hospede_id()
        if hid:
            h = self.ctx.hotel.hospede(hid)
            self.nome.setText(h["nome"])
            if h["telefone"] and not self.telefone.text():
                self.telefone.setText(h["telefone"])

    def confirmar(self) -> None:
        uh_id = self.uh.currentData()
        if uh_id is None:
            self.mensagem.setText("Escolha um quarto livre.")
            return
        diaria = self.modalidade.currentData() == "diaria"
        inicio, _ = self._intervalo()
        try:
            self.estadia_id = self.ctx.hotel.reservar(
                uh_id, self.nome.text(), _iso(self.entrada.date()) if diaria else inicio,
                _iso(self.saida.date()) if diaria else None, modalidade=self.modalidade.currentData(),
                periodo_id=None if diaria else self.periodo.currentData(), adultos=self.adultos.value(),
                criancas=self.criancas.value(), hospede_id=self.seletor.hospede_id(), telefone=self.telefone.text(),
                cafe_incluso=self.cafe.isChecked() if diaria else False, origem=self.origem.currentData(),
                observacao=self.observacao.text())
        except (ErroNegocio, ErroValidacao) as erro:
            self.mensagem.setText(str(erro))
            return
        self.accept()


# ================================================================== check-in
class DialogoCheckin(QDialog):
    def __init__(self, ctx, estadia_id: int, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.estadia_id = estadia_id
        e = ctx.hotel.estadia(estadia_id)
        self.setWindowTitle(f"Check-in • quarto {e['uh']}")
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        layout.addWidget(texto(f"Check-in no quarto {e['uh']} ({e['tipo']})", "titulo"))
        layout.addWidget(texto(f"{e['titular_nome']} · {_quando(e)} · {_noites(e)} · {e['adultos']} adulto(s)"
                               + (f", {e['criancas']} criança(s)" if e["criancas"] else ""), "suave"))
        layout.addWidget(texto("Titular (maior de idade, com a ficha completa)", "legenda"))
        self.titular = SeletorHospede(ctx)
        if e["hospede_id"]:
            self.titular.escolher(e["hospede_id"])
        else:
            self.titular.busca.setText(e["titular_nome"])
        layout.addWidget(self.titular)
        layout.addWidget(texto("Acompanhantes (menor de idade: diga o responsável e o parentesco)", "legenda"))
        acomp = QHBoxLayout()
        self.acompanhantes = _tabela(["Hóspede", "Idade", "Responsável (menor)"], elastica=0)
        self.acompanhantes.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.acompanhantes.setMaximumHeight(110)
        acomp.addWidget(self.acompanhantes, 1)
        lado = QVBoxLayout()
        lado.addWidget(_botao("Incluir o escolhido acima", self.incluir_acompanhante))
        lado.addWidget(_botao("Tirar", self.tirar_acompanhante))
        lado.addStretch(1)
        acomp.addLayout(lado)
        layout.addLayout(acomp)
        form = QFormLayout()
        self.motivo = QComboBox()
        self.motivo.addItem("")
        self.motivo.addItems(list(MOTIVOS_VIAGEM))
        self.transporte = QComboBox()
        self.transporte.addItem("")
        self.transporte.addItems(list(MEIOS_TRANSPORTE))
        self.procedencia = QLineEdit()
        self.procedencia.setPlaceholderText("Cidade/UF de onde vem")
        self.destino = QLineEdit()
        self.destino.setPlaceholderText("Cidade/UF para onde vai")
        form.addRow("Motivo da viagem", self.motivo)
        form.addRow("Meio de transporte", self.transporte)
        form.addRow("Vem de", self.procedencia)
        form.addRow("Vai para", self.destino)
        layout.addLayout(form)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        botoes = QDialogButtonBox()
        botoes.addButton("Fazer o check-in", QDialogButtonBox.ButtonRole.AcceptRole)
        botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.confirmar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def incluir_acompanhante(self) -> None:
        hid = self.titular.hospede_id()
        if hid is None:
            self.mensagem.setText("Procure e escolha o acompanhante na lista acima.")
            return
        for i in range(self.acompanhantes.rowCount()):
            if self.acompanhantes.item(i, 0).data(Qt.ItemDataRole.UserRole) == hid:
                return
        h = self.ctx.hotel.hospede(hid)
        linha = self.acompanhantes.rowCount()
        self.acompanhantes.insertRow(linha)
        nome = QTableWidgetItem(h["nome"])
        nome.setData(Qt.ItemDataRole.UserRole, hid)
        nome.setFlags(nome.flags() & ~Qt.ItemFlag.ItemIsEditable)
        idade = QTableWidgetItem("" if h["idade"] is None else str(h["idade"]))
        idade.setFlags(idade.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.acompanhantes.setItem(linha, 0, nome)
        self.acompanhantes.setItem(linha, 1, idade)
        self.acompanhantes.setItem(linha, 2, QTableWidgetItem(""))

    def tirar_acompanhante(self) -> None:
        if self.acompanhantes.currentRow() >= 0:
            self.acompanhantes.removeRow(self.acompanhantes.currentRow())

    def lista_acompanhantes(self) -> list[dict]:
        return [{"hospede_id": self.acompanhantes.item(i, 0).data(Qt.ItemDataRole.UserRole),
                 "responsavel": self.acompanhantes.item(i, 2).text() if self.acompanhantes.item(i, 2) else ""}
                for i in range(self.acompanhantes.rowCount())]

    def confirmar(self, permitir_quarto_sujo: bool = False) -> None:
        titular = self.titular.hospede_id()
        acompanhantes = [a for a in self.lista_acompanhantes() if a["hospede_id"] != titular]
        try:
            self.ctx.hotel.checkin(self.estadia_id, titular, acompanhantes, motivo_viagem=self.motivo.currentText(),
                                   meio_transporte=self.transporte.currentText(), procedencia=self.procedencia.text(),
                                   proximo_destino=self.destino.text(), permitir_quarto_sujo=permitir_quarto_sujo)
        except ErroValidacao as erro:
            self.mensagem.setText(str(erro))
            return
        except ErroNegocio as erro:
            if not permitir_quarto_sujo and "Confirme com a arrumação" in str(erro):
                resposta = QMessageBox.question(self, "Quarto não está pronto",
                                                f"{erro}\n\nFazer o check-in mesmo assim?")
                if resposta == QMessageBox.StandardButton.Yes:
                    self.confirmar(permitir_quarto_sujo=True)
                return
            self.mensagem.setText(str(erro))
            return
        self.accept()


# ================================================================== check-out
class DialogoCheckout(QDialog):
    def __init__(self, ctx, estadia_id: int, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.estadia_id = estadia_id
        self.resultado = None
        self.setWindowTitle("Check-out")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        self.titulo = texto("", "titulo")
        layout.addWidget(self.titulo)
        self.cobrar_extra = QCheckBox("Cobrar mais uma diária pelo atraso")
        self.cobrar_extra.toggled.connect(self.atualizar)
        self.atraso = texto("", "aviso")
        layout.addWidget(self.atraso)
        layout.addWidget(self.cobrar_extra)
        self.linhas = _tabela(["O check-out lança na conta", "Qtd.", "Valor"], elastica=0)
        self.linhas.setMaximumHeight(130)
        layout.addWidget(self.linhas)
        self.resumo = texto("", "subtitulo")
        layout.addWidget(self.resumo)
        layout.addWidget(texto("Depois do check-out, receba a conta no caixa (ela é uma comanda). O quarto fica sujo para a "
                               "arrumação.", "suave"))
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        botoes = QDialogButtonBox()
        botoes.addButton("Confirmar o check-out", QDialogButtonBox.ButtonRole.AcceptRole)
        botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.confirmar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)
        self.atualizar()

    def atualizar(self, *_):
        p = self.ctx.hotel.previa_checkout(self.estadia_id, self.cobrar_extra.isChecked())
        e = p["estadia"]
        self.titulo.setText(f"Check-out do quarto {e['uh']} · {e['titular_nome']} · conta {e['conta']}")
        diaria = e["modalidade"] == "diaria"
        self.cobrar_extra.setVisible(diaria and (p["atraso_min"] > 0 or self.cobrar_extra.isChecked()))
        if p["atraso_min"] > 0:
            self.atraso.setText(f"Saída {fmt_duracao(p['atraso_min'])} depois do horário"
                                + ("." if diaria else f": {p['horas_extras']} hora(s) adicional(is)."))
        else:
            self.atraso.setText("")
        _preencher(self.linhas, [(l["descricao"], fmt.fmt_qtd(l["quantidade"], 0), fmt.fmt_brl(l["valor_cent"]))
                                 for l in p["linhas"]] or [("Nada a lançar: a conta já tem as diárias.", "", "")])
        self.resumo.setText(f"Conta: {fmt.fmt_brl(p['total_cent'])} · já pago {fmt.fmt_brl(p['pago_cent'])} · "
                            f"a receber {fmt.fmt_brl(max(0, p['saldo_cent']))}")

    def confirmar(self) -> None:
        try:
            self.resultado = self.ctx.hotel.checkout(self.estadia_id, self.cobrar_extra.isChecked())
        except (ErroNegocio, ErroValidacao) as erro:
            self.mensagem.setText(str(erro))
            return
        self.accept()


# ================================================================== janela principal
class JanelaHotel(QDialog):
    ABAS = ("hoje", "mapa", "reservas", "hospedes", "governanca", "relatorios", "cadastro")

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        self._operador_id = ctx.operador_id
        self.exigir_acesso()
        super().__init__(parent)
        self.app = parent
        self.setWindowTitle("Hotel • recepção")
        self.resize(1260, 680)
        layout = QVBoxLayout(self)
        topo = QHBoxLayout()
        topo.addWidget(texto("Recepção do hotel", "titulo"), 1)
        self.resumo = texto("", "suave")
        topo.addWidget(self.resumo, 2)
        layout.addLayout(topo)
        acoes = tema.LinhaFluida()
        acoes.addWidget(_botao("Nova reserva", self.nova_reserva, "primario"))
        acoes.addWidget(_botao("Check-in sem reserva", self.checkin_sem_reserva))
        acoes.addWidget(_botao("Lançar diárias vencidas", self.lancar_diarias_vencidas))
        acoes.addWidget(_botao("Atualizar (F5)", self.atualizar))
        acoes.addWidget(_botao("Fechar", self.close))
        layout.addLayout(acoes)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        self.abas = QTabWidget()
        layout.addWidget(self.abas, 1)
        self._montar_hoje()
        self._montar_mapa()
        self._montar_reservas()
        self._montar_hospedes()
        self._montar_governanca()
        self._montar_relatorios()
        self.pode_cadastrar = ctx.pode("cfg_hotel")
        self._montar_cadastro()
        self.abas.currentChanged.connect(lambda _: self.atualizar())
        self.relogio = QTimer(self)
        self.relogio.setInterval(15000)
        self.relogio.timeout.connect(self._tique)
        self.relogio.start()
        self.atualizar()

    # ------------------------------------------------------------ acesso e utilidades
    def exigir_acesso(self):
        if self.ctx.operador_id is None or self.ctx.operador_id != getattr(self, "_operador_id", self.ctx.operador_id):
            raise ErroPermissao("A sessão mudou. Abra a recepção novamente.")
        if "util_hotel" in modulos_desligados(self.ctx.banco):
            raise ErroPermissao("O módulo Hotel está desligado (Configurações > Módulos).")
        self.ctx.acesso.exigir(self.ctx.operador, "util_hotel")

    def keyPressEvent(self, evento):
        if evento.key() == Qt.Key.Key_F5:
            self.atualizar()
            return
        super().keyPressEvent(evento)

    def avisar(self, texto_aviso: str) -> None:
        self.mensagem.setText(texto_aviso)

    def _executar(self, funcao, *args, **kwargs):
        try:
            resultado = funcao(*args, **kwargs)
        except (ErroNegocio, ErroValidacao) as erro:
            self.avisar(str(erro))
            return None
        self.atualizar()
        return resultado

    def _aba(self, rotulo: str) -> tuple[QWidget, QVBoxLayout]:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        self.abas.addTab(pagina, rotulo)
        return pagina, layout

    # ------------------------------------------------------------ Hoje
    def _montar_hoje(self):
        _, layout = self._aba("Hoje")
        layout.addWidget(texto("Chegadas de hoje (e reservas atrasadas)", "subtitulo"))
        self.tab_chegadas = _tabela(["Quarto", "Hóspede", "Quando", "Estadia", "Pessoas", "Telefone", "Origem"], elastica=1)
        self.tab_chegadas.doubleClicked.connect(lambda _: self.fazer_checkin())
        layout.addWidget(self.tab_chegadas, 1)
        linha = tema.LinhaFluida()
        linha.addWidget(_botao("Fazer check-in", self.fazer_checkin, "primario"))
        linha.addWidget(_botao("Não compareceu", self.marcar_nao_compareceu))
        linha.addWidget(_botao("Cancelar reserva", lambda: self.cancelar_reserva(self.tab_chegadas)))
        layout.addLayout(linha)
        layout.addWidget(texto("Hospedados agora (vermelho: passou da hora; amarelo: período acabando)", "subtitulo"))
        self.tab_hospedados = _tabela(["Quarto", "Hóspede", "Entrou", "Sai", "Tempo", "Conta", "Pessoas"], elastica=1)
        self.tab_hospedados.doubleClicked.connect(lambda _: self.fazer_checkout())
        layout.addWidget(self.tab_hospedados, 2)
        linha = tema.LinhaFluida()
        linha.addWidget(_botao("Check-out", self.fazer_checkout, "primario"))
        linha.addWidget(_botao("Conta no caixa", self.abrir_conta_no_caixa))
        linha.addWidget(_botao("Café avulso", self.lancar_cafe))
        linha.addWidget(_botao("Prorrogar / antecipar", self.prorrogar))
        linha.addWidget(_botao("Trocar de quarto", lambda: self.trocar_quarto(self.tab_hospedados)))
        layout.addLayout(linha)

    def _atualizar_hoje(self, painel: dict):
        _preencher(self.tab_chegadas, [
            (e["uh"], e["titular_nome"], _quando(e), _noites(e), e["adultos"] + e["criancas"], e["telefone"] or "",
             ORIGENS.get(e["origem"], e["origem"])) for e in painel["chegadas"]], [e["id"] for e in painel["chegadas"]])
        hospedados = painel["hospedados"]
        tempos = {e["id"]: e for e in painel["periodos"]}
        hoje = painel["hoje"]
        linhas, fundos = [], []
        for e in hospedados:
            p = tempos.get(e["id"])
            if p:
                tempo = ("passou " if p["restante_seg"] < 0 else "faltam ") + p["relogio"]
                fundos.append(cor(self, p["alerta"]) if p["alerta"] != "uso" else None)
            else:
                tempo = _noites(e)
                atrasado = e["saida_prevista"][:10] < hoje or (
                    e["saida_prevista"][:10] == hoje and fmt.agora() > e["saida_prevista"])
                fundos.append(cor(self, "estourou") if atrasado else None)
            linhas.append((e["uh"], e["titular_nome"], fmt.fmt_datahora(e["entrada_em"])[:16],
                           fmt.fmt_datahora(e["saida_prevista"])[:16], tempo, e["conta"] or "",
                           e["adultos"] + e["criancas"]))
        _preencher(self.tab_hospedados, linhas, [e["id"] for e in hospedados], fundos)

    def _tique(self):
        if self.isVisible() and self.abas.currentIndex() == 0:
            self._atualizar_hoje(self.ctx.hotel.painel_hoje())

    # ------------------------------------------------------------ Mapa
    def _montar_mapa(self):
        _, layout = self._aba("Mapa de reservas")
        barra = QHBoxLayout()
        barra.addWidget(_botao("◀ Semana anterior", lambda: self.mover_mapa(-7)))
        barra.addWidget(_botao("Hoje", lambda: self.mover_mapa(0)))
        barra.addWidget(_botao("Próxima semana ▶", lambda: self.mover_mapa(7)))
        barra.addStretch(1)
        barra.addWidget(texto("Azul: reserva · Verde: hospedado · Cinza: já saiu. Dois cliques num dia livre reserva; "
                              "num bloco, abre a estadia.", "suave"), 3)
        layout.addLayout(barra)
        self.inicio_mapa = fmt.agora_dt().date() - timedelta(days=1)
        self.dias_mapa = 14
        self.grade_mapa = QTableWidget(0, self.dias_mapa)
        self.grade_mapa.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade_mapa.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade_mapa.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.grade_mapa.horizontalHeader().setMinimumSectionSize(56)
        self.grade_mapa.cellDoubleClicked.connect(self._clique_mapa)
        layout.addWidget(self.grade_mapa, 1)

    def mover_mapa(self, dias: int):
        self.inicio_mapa = (fmt.agora_dt().date() - timedelta(days=1)) if dias == 0 else \
            self.inicio_mapa + timedelta(days=dias)
        self._atualizar_mapa()

    def _atualizar_mapa(self):
        mapa = self.ctx.hotel.mapa(self.inicio_mapa, self.dias_mapa)
        g = self.grade_mapa
        g.clearSpans()
        g.clear()
        g.setRowCount(len(mapa["linhas"]))
        hoje = fmt.hoje()
        titulos = []
        for d in mapa["datas"]:
            dia = datetime.strptime(d, "%Y-%m-%d").date()
            titulos.append(("● " if d == hoje else "") + f"{DIAS_SEMANA[dia.weekday()]}\n{dia.day:02d}/{dia.month:02d}")
        g.setHorizontalHeaderLabels(titulos)
        g.setVerticalHeaderLabels([f"{l['uh']['numero']} · {l['uh']['tipo']}" for l in mapa["linhas"]])
        for i, linha in enumerate(mapa["linhas"]):
            for j in range(self.dias_mapa):
                item = QTableWidgetItem("")
                item.setData(Qt.ItemDataRole.UserRole, ("livre", linha["uh"]["id"], mapa["datas"][j]))
                g.setItem(i, j, item)
            for b in linha["blocos"]:
                if any(g.item(i, j).data(Qt.ItemDataRole.UserRole)[0] == "estadia" for j in range(b["col_ini"], b["col_fim"])):
                    continue                                  # dois blocos no mesmo dia (período): o primeiro aparece
                item = QTableWidgetItem(("◂ " if b["continua_antes"] else "") + b["titular"]
                                        + (" ▸" if b["continua_depois"] else ""))
                item.setData(Qt.ItemDataRole.UserRole, ("estadia", b["estadia_id"], None))
                item.setBackground(QBrush(cor(self, b["situacao"])))
                item.setToolTip(f"{b['titular']} · {SITUACOES[b['situacao']]}")
                g.setItem(i, b["col_ini"], item)
                if b["col_fim"] - b["col_ini"] > 1:
                    g.setSpan(i, b["col_ini"], 1, b["col_fim"] - b["col_ini"])

    def _clique_mapa(self, linha: int, coluna: int):
        item = self.grade_mapa.item(linha, coluna)
        if item is None:
            return
        tipo, ident, data = item.data(Qt.ItemDataRole.UserRole)
        if tipo == "livre":
            self.nova_reserva(ident, data)
        else:
            self.mostrar_estadia(ident)

    # ------------------------------------------------------------ Reservas
    def _montar_reservas(self):
        _, layout = self._aba("Reservas")
        filtros = QHBoxLayout()
        self.filtro_situacao = QComboBox()
        self.filtro_situacao.addItem("Em aberto (reservadas e hospedadas)", ("reservada", "hospedada"))
        for chave, rotulo in SITUACOES.items():
            self.filtro_situacao.addItem(rotulo, (chave,))
        self.filtro_situacao.addItem("Todas", None)
        self.filtro_texto = QLineEdit()
        self.filtro_texto.setPlaceholderText("Nome, telefone ou quarto")
        self.filtro_de = _campo_data(fmt.agora_dt().date() - timedelta(days=30))
        self.filtro_ate = _campo_data(fmt.agora_dt().date() + timedelta(days=180))
        for w in (self.filtro_situacao, self.filtro_texto):
            filtros.addWidget(w, 1)
        filtros.addWidget(QLabel("Entrada de"))
        filtros.addWidget(self.filtro_de)
        filtros.addWidget(QLabel("até"))
        filtros.addWidget(self.filtro_ate)
        filtros.addWidget(_botao("Filtrar", self._atualizar_reservas))
        layout.addLayout(filtros)
        self.tab_reservas = _tabela(["Quarto", "Hóspede", "Quando", "Estadia", "Situação", "Pessoas", "Telefone", "Conta"],
                                    elastica=1)
        self.tab_reservas.doubleClicked.connect(lambda _: self.mostrar_estadia(_selecionado(self.tab_reservas)))
        layout.addWidget(self.tab_reservas, 1)
        linha = tema.LinhaFluida()
        linha.addWidget(_botao("Ver estadia", lambda: self.mostrar_estadia(_selecionado(self.tab_reservas))))
        linha.addWidget(_botao("Mudar datas", self.mudar_datas))
        linha.addWidget(_botao("Trocar de quarto", lambda: self.trocar_quarto(self.tab_reservas)))
        linha.addWidget(_botao("Cancelar reserva", lambda: self.cancelar_reserva(self.tab_reservas)))
        layout.addLayout(linha)

    def _atualizar_reservas(self):
        lista = self.ctx.hotel.estadias(self.filtro_situacao.currentData(), self.filtro_texto.text(),
                                        _iso(self.filtro_de.date()), _iso(self.filtro_ate.date()))
        _preencher(self.tab_reservas, [
            (e["uh"], e["titular_nome"], _quando(e), _noites(e), e["situacao_rotulo"], e["adultos"] + e["criancas"],
             e["telefone"] or "", e["conta"] or "") for e in lista], [e["id"] for e in lista],
            [cor(self, e["situacao"]) if e["situacao"] in ("reservada", "hospedada") else None for e in lista])

    # ------------------------------------------------------------ Hóspedes
    def _montar_hospedes(self):
        _, layout = self._aba("Hóspedes")
        linha = QHBoxLayout()
        self.busca_hospede = QLineEdit()
        self.busca_hospede.setPlaceholderText("Procurar por nome, CPF, documento ou telefone")
        self.busca_hospede.textChanged.connect(lambda _: self._atualizar_hospedes())
        linha.addWidget(self.busca_hospede, 1)
        linha.addWidget(_botao("Novo hóspede", self.novo_hospede, "primario"))
        linha.addWidget(_botao("Editar ficha", self.editar_hospede))
        layout.addLayout(linha)
        self.tab_hospedes = _tabela(["Nome", "CPF", "Documento", "Nascimento", "Telefone", "Cidade", "Ficha"], elastica=0)
        self.tab_hospedes.doubleClicked.connect(lambda _: self.editar_hospede())
        layout.addWidget(self.tab_hospedes, 1)
        layout.addWidget(texto("Os dados dos hóspedes ficam só neste computador (não sobem para a nuvem).", "suave"))

    def _atualizar_hospedes(self):
        lista = self.ctx.hotel.buscar_hospedes(self.busca_hospede.text(), limite=300)
        _preencher(self.tab_hospedes, [
            (h["nome"], fmt_cpf(h["cpf"]), f"{h['documento_tipo']} {h['documento'] or ''}".strip(),
             fmt.fmt_data(h["nascimento"]), h["telefone"] or "", "/".join(x for x in (h["cidade"], h["uf"]) if x),
             "completa" if not self.ctx.hotel._faltas_ficha(h) else "falta " + ", ".join(self.ctx.hotel._faltas_ficha(h)))
            for h in lista], [h["id"] for h in lista])

    def novo_hospede(self):
        dialogo = DialogoHospede(self.ctx, parent=self)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            self.atualizar()

    def editar_hospede(self):
        hid = _selecionado(self.tab_hospedes)
        if hid is None:
            self.avisar("Escolha o hóspede na lista.")
            return
        if DialogoHospede(self.ctx, hid, parent=self).exec() == QDialog.DialogCode.Accepted:
            self.atualizar()

    # ------------------------------------------------------------ Governança
    def _montar_governanca(self):
        _, layout = self._aba("Governança")
        layout.addWidget(texto("A arrumação de cada quarto. Depois do check-out o quarto fica sujo; quem arruma marca como "
                               "limpo. Em manutenção o quarto sai da venda.", "suave"))
        self.tab_governanca = _tabela(["Quarto", "Tipo", "Andar", "Arrumação", "Ocupação", "Observação"], elastica=5)
        layout.addWidget(self.tab_governanca, 1)
        linha = tema.LinhaFluida()
        for chave, rotulo in LIMPEZA.items():
            linha.addWidget(_botao(f"Marcar {rotulo.lower()}", lambda c=chave: self.marcar_limpeza(c)))
        layout.addLayout(linha)

    def _atualizar_governanca(self, painel: dict):
        uhs = painel["uhs"]
        _preencher(self.tab_governanca, [
            (u["numero"], u["tipo"], u["andar"] or "", u["limpeza_rotulo"],
             "Ocupado" if u["ocupada"] else ("Chega hoje" if u["chegada_hoje"] else "Livre"),
             u["motivo_manutencao"] or u["observacao"] or "") for u in uhs], [u["id"] for u in uhs],
            [cor(self, u["limpeza"]) for u in uhs])

    def marcar_limpeza(self, situacao: str):
        uh_id = _selecionado(self.tab_governanca)
        if uh_id is None:
            self.avisar("Escolha o quarto na lista.")
            return
        motivo = None
        if situacao == "manutencao":
            motivo, ok = QInputDialog.getText(self, "Manutenção", "O que o quarto tem?")
            if not ok:
                return
        if self._executar(self.ctx.hotel.marcar_limpeza, uh_id, situacao, motivo) is None and self.mensagem.text():
            return
        self.avisar(f"Quarto marcado como {LIMPEZA[situacao].lower()}.")

    # ------------------------------------------------------------ Relatórios
    def _montar_relatorios(self):
        _, layout = self._aba("Relatórios")
        linha = QHBoxLayout()
        hoje = fmt.agora_dt().date()
        self.rel_de = _campo_data(hoje.replace(day=1))
        self.rel_ate = _campo_data(hoje)
        linha.addWidget(QLabel("De"))
        linha.addWidget(self.rel_de)
        linha.addWidget(QLabel("até"))
        linha.addWidget(self.rel_ate)
        linha.addWidget(_botao("Calcular", self._atualizar_relatorios, "primario"))
        linha.addWidget(_botao("Exportar fichas (FNRH)…", self.exportar_fichas))
        linha.addStretch(1)
        layout.addLayout(linha)
        self.rel_resumo = texto("", "subtitulo")
        layout.addWidget(self.rel_resumo)
        layout.addWidget(texto("Diária média = receita das diárias ÷ noites vendidas. RevPAR = receita das diárias ÷ noites "
                               "disponíveis. A receita conta no dia em que a diária entrou na conta.", "suave"))
        corpo = QHBoxLayout()
        esquerda = QVBoxLayout()
        esquerda.addWidget(texto("Ocupação por noite", "legenda"))
        self.tab_ocupacao = _tabela(["Noite", "Quartos ocupados", "Ocupação"])
        esquerda.addWidget(self.tab_ocupacao, 1)
        corpo.addLayout(esquerda, 1)
        direita = QVBoxLayout()
        cafe = QHBoxLayout()
        cafe.addWidget(texto("Café da manhã de", "legenda"))
        self.cafe_dia = _campo_data(hoje)
        self.cafe_dia.dateChanged.connect(lambda _: self._atualizar_cafe())
        cafe.addWidget(self.cafe_dia)
        cafe.addStretch(1)
        direita.addLayout(cafe)
        self.cafe_resumo = texto("", "suave")
        direita.addWidget(self.cafe_resumo)
        self.tab_cafe = _tabela(["Quarto", "Hóspede", "Pessoas", "Café"], elastica=1)
        direita.addWidget(self.tab_cafe, 1)
        corpo.addLayout(direita, 1)
        layout.addLayout(corpo, 1)

    def _atualizar_relatorios(self):
        try:
            r = self.ctx.hotel.ocupacao(_iso(self.rel_de.date()), _iso(self.rel_ate.date()))
        except (ErroNegocio, ErroValidacao) as erro:
            self.avisar(str(erro))
            return
        self.rel_resumo.setText(
            f"Ocupação {fmt.fmt_qtd(r['ocupacao_pct'], 1)}% ({r['noites_vendidas']} de {r['noites_disponiveis']} noites) · "
            f"diárias {fmt.fmt_brl(r['receita_diarias_cent'])} · diária média {fmt.fmt_brl(r['diaria_media_cent'])} · "
            f"RevPAR {fmt.fmt_brl(r['revpar_cent'])} · períodos {r['periodos']} "
            f"({fmt.fmt_brl(r['receita_periodos_cent'])})")
        _preencher(self.tab_ocupacao, [(fmt.fmt_data(d["data"]), d["ocupados"], f"{fmt.fmt_qtd(d['pct'], 1)}%")
                                       for d in r["por_dia"]])
        self._atualizar_cafe()

    def _atualizar_cafe(self):
        c = self.ctx.hotel.cafe_do_dia(_iso(self.cafe_dia.date()))
        self.cafe_resumo.setText(f"{c['pessoas']} pessoa(s): {c['inclusos']} com café incluso, {c['avulsos']} avulso(s).")
        _preencher(self.tab_cafe, [(q["uh"], q["titular"], q["pessoas"], "incluso" if q["incluso"] else "avulso")
                                   for q in c["quartos"]])

    def exportar_fichas(self, caminho: str | None = None):
        de, ate = _iso(self.rel_de.date()), _iso(self.rel_ate.date())
        if caminho is None:
            caminho, _ = QFileDialog.getSaveFileName(self, "Exportar fichas dos hóspedes", f"fichas_hospedes_{de}_{ate}.csv",
                                                     "Planilha CSV (*.csv)")
            if not caminho:
                return None
        destino = self._executar(self.ctx.hotel.exportar_fichas, de, ate, caminho)
        if destino:
            self.avisar(f"Fichas exportadas em {destino}. Confira e envie na FNRH Digital (site do Ministério do Turismo).")
        return destino

    # ------------------------------------------------------------ Quartos e tarifas
    def _montar_cadastro(self):
        pagina, layout = self._aba("Quartos e tarifas")
        if not self.pode_cadastrar:
            layout.addWidget(texto("Só o gerente (nível de acesso de Configurações) muda quartos e tarifas.", "suave"))
            layout.addStretch(1)
            return
        corpo = QHBoxLayout()
        tipos = QGroupBox("Tipos de quarto e diária")
        lt = QVBoxLayout(tipos)
        self.tab_tipos = _tabela(["Tipo", "Pessoas", "Diária", "Café", "Quartos"], elastica=0)
        self.tab_tipos.itemSelectionChanged.connect(self._tipo_escolhido)
        lt.addWidget(self.tab_tipos, 1)
        ft = QFormLayout()
        self.tipo_nome = QLineEdit()
        self.tipo_capacidade = QSpinBox()
        self.tipo_capacidade.setRange(1, 20)
        self.tipo_capacidade.setValue(2)
        self.tipo_preco = QLineEdit()
        self.tipo_preco.setPlaceholderText("150,00")
        self.tipo_cafe = QCheckBox("Café incluso")
        self.tipo_cafe.setChecked(True)
        ft.addRow("Nome", self.tipo_nome)
        ft.addRow("Pessoas", self.tipo_capacidade)
        ft.addRow("Diária (R$)", self.tipo_preco)
        ft.addRow("", self.tipo_cafe)
        lt.addLayout(ft)
        bt = tema.LinhaFluida()
        bt.addWidget(_botao("Salvar tipo", self.salvar_tipo, "primario"))
        bt.addWidget(_botao("Novo", self._limpar_tipo))
        lt.addLayout(bt)
        corpo.addWidget(tipos, 1)
        quartos = QGroupBox("Quartos")
        lq = QVBoxLayout(quartos)
        self.tab_uhs = _tabela(["Quarto", "Tipo", "Andar"], elastica=1)
        self.tab_uhs.itemSelectionChanged.connect(self._uh_escolhida)
        lq.addWidget(self.tab_uhs, 1)
        fq = QFormLayout()
        self.uh_numero = QLineEdit()
        self.uh_tipo = QComboBox()
        self.uh_andar = QLineEdit()
        fq.addRow("Número", self.uh_numero)
        fq.addRow("Tipo", self.uh_tipo)
        fq.addRow("Andar", self.uh_andar)
        lq.addLayout(fq)
        bq = tema.LinhaFluida()
        bq.addWidget(_botao("Salvar quarto", self.salvar_uh, "primario"))
        bq.addWidget(_botao("Novo", self._limpar_uh))
        bq.addWidget(_botao("Desativar", self.desativar_uh))
        lq.addLayout(bq)
        corpo.addWidget(quartos, 1)
        periodos = QGroupBox("Períodos (por horas) e serviços")
        lp = QVBoxLayout(periodos)
        self.tab_periodos = _tabela(["Período", "Duração", "Preço"], elastica=0)
        self.tab_periodos.itemSelectionChanged.connect(self._periodo_escolhido)
        lp.addWidget(self.tab_periodos, 1)
        fp = QFormLayout()
        self.per_nome = QLineEdit()
        self.per_nome.setPlaceholderText("2 horas, Pernoite…")
        self.per_minutos = QSpinBox()
        self.per_minutos.setRange(30, 1440)
        self.per_minutos.setSingleStep(30)
        self.per_minutos.setValue(120)
        self.per_minutos.setSuffix(" min")
        self.per_preco = QLineEdit()
        fp.addRow("Nome", self.per_nome)
        fp.addRow("Duração", self.per_minutos)
        fp.addRow("Preço (R$)", self.per_preco)
        lp.addLayout(fp)
        bp = tema.LinhaFluida()
        bp.addWidget(_botao("Salvar período", self.salvar_periodo, "primario"))
        bp.addWidget(_botao("Novo", self._limpar_periodo))
        lp.addLayout(bp)
        fe = QFormLayout()
        self.preco_cafe = QLineEdit()
        self.preco_hora = QLineEdit()
        fe.addRow("Café avulso (R$/pessoa)", self.preco_cafe)
        fe.addRow("Hora adicional (R$)", self.preco_hora)
        lp.addLayout(fe)
        lp.addWidget(_botao("Salvar preços dos serviços", self.salvar_extras))
        corpo.addWidget(periodos, 1)
        layout.addLayout(corpo, 1)
        self._tipo_id = self._uh_id = self._periodo_id = None

    def _atualizar_cadastro(self):
        if not self.pode_cadastrar:
            return
        h = self.ctx.hotel
        tipos = h.tipos()
        _preencher(self.tab_tipos, [(t["nome"], t["capacidade"], fmt.fmt_brl(t["preco_diaria_cent"]),
                                     "incluso" if t["cafe_incluso"] else "à parte", t["uhs"]) for t in tipos],
                   [t["id"] for t in tipos])
        atual = self.uh_tipo.currentData()
        self.uh_tipo.clear()
        for t in tipos:
            self.uh_tipo.addItem(t["nome"], t["id"])
        self.uh_tipo.setCurrentIndex(max(0, self.uh_tipo.findData(atual)))
        uhs = h.uhs()
        _preencher(self.tab_uhs, [(u["numero"], u["tipo"], u["andar"] or "") for u in uhs], [u["id"] for u in uhs])
        periodos = h.periodos()
        _preencher(self.tab_periodos, [(p["nome"], p["duracao"], fmt.fmt_brl(p["preco_cent"])) for p in periodos],
                   [p["id"] for p in periodos])
        extras = h.precos_extras()
        self.preco_cafe.setText(fmt.fmt_num(extras["cafe"]) if extras["cafe"] else "")
        self.preco_hora.setText(fmt.fmt_num(extras["hora_extra"]) if extras["hora_extra"] else "")

    @staticmethod
    def _centavos(campo: QLineEdit) -> int:
        try:
            return fmt.para_centavos(campo.text() or "0")
        except ValueError:
            raise ErroValidacao("Preço inválido (use 150,00).") from None

    def _tipo_escolhido(self):
        tid = _selecionado(self.tab_tipos)
        t = next((t for t in self.ctx.hotel.tipos() if t["id"] == tid), None)
        if t:
            self._tipo_id = tid
            self.tipo_nome.setText(t["nome"])
            self.tipo_capacidade.setValue(t["capacidade"])
            self.tipo_preco.setText(fmt.fmt_num(t["preco_diaria_cent"]))
            self.tipo_cafe.setChecked(bool(t["cafe_incluso"]))

    def _limpar_tipo(self):
        self._tipo_id = None
        self.tab_tipos.clearSelection()
        self.tipo_nome.clear()
        self.tipo_preco.clear()

    def salvar_tipo(self):
        try:
            preco = self._centavos(self.tipo_preco)
        except ErroValidacao as erro:
            self.avisar(str(erro))
            return
        if self._executar(self.ctx.hotel.salvar_tipo, self.tipo_nome.text(), self.tipo_capacidade.value(), preco,
                          self.tipo_cafe.isChecked(), None, self._tipo_id):
            self._limpar_tipo()
            self.avisar("Tipo de quarto salvo. A diária é um produto do caixa (grupo HOSPEDAGEM).")

    def _uh_escolhida(self):
        uid = _selecionado(self.tab_uhs)
        if uid:
            u = self.ctx.hotel.uh(uid)
            self._uh_id = uid
            self.uh_numero.setText(u["numero"])
            self.uh_tipo.setCurrentIndex(max(0, self.uh_tipo.findData(u["tipo_id"])))
            self.uh_andar.setText(u["andar"] or "")

    def _limpar_uh(self):
        self._uh_id = None
        self.tab_uhs.clearSelection()
        self.uh_numero.clear()
        self.uh_andar.clear()

    def salvar_uh(self):
        if self.uh_tipo.currentData() is None:
            self.avisar("Cadastre um tipo de quarto antes.")
            return
        if self._executar(self.ctx.hotel.salvar_uh, self.uh_numero.text(), self.uh_tipo.currentData(),
                          self.uh_andar.text(), None, self._uh_id):
            self._limpar_uh()
            self.avisar("Quarto salvo.")

    def desativar_uh(self):
        if self._uh_id is None:
            self.avisar("Escolha o quarto na lista.")
            return
        self._executar(self.ctx.hotel.desativar_uh, self._uh_id)
        self._limpar_uh()

    def _periodo_escolhido(self):
        pid = _selecionado(self.tab_periodos)
        p = next((p for p in self.ctx.hotel.periodos() if p["id"] == pid), None)
        if p:
            self._periodo_id = pid
            self.per_nome.setText(p["nome"])
            self.per_minutos.setValue(p["minutos"])
            self.per_preco.setText(fmt.fmt_num(p["preco_cent"]))

    def _limpar_periodo(self):
        self._periodo_id = None
        self.tab_periodos.clearSelection()
        self.per_nome.clear()
        self.per_preco.clear()

    def salvar_periodo(self):
        try:
            preco = self._centavos(self.per_preco)
        except ErroValidacao as erro:
            self.avisar(str(erro))
            return
        if self._executar(self.ctx.hotel.salvar_periodo, self.per_nome.text(), self.per_minutos.value(), preco,
                          self._periodo_id):
            self._limpar_periodo()
            self.avisar("Período salvo.")

    def salvar_extras(self):
        try:
            for chave, campo in (("cafe", self.preco_cafe), ("hora_extra", self.preco_hora)):
                if campo.text().strip():
                    self.ctx.hotel.definir_preco_extra(chave, self._centavos(campo))
        except (ErroNegocio, ErroValidacao) as erro:
            self.avisar(str(erro))
            return
        self.atualizar()
        self.avisar("Preços dos serviços salvos.")

    # ------------------------------------------------------------ ações
    def atualizar(self, *_):
        try:
            self.exigir_acesso()
        except (ErroNegocio, ErroPermissao) as erro:
            self.avisar(str(erro))
            return
        painel = self.ctx.hotel.painel_hoje()
        r = painel["resumo"]
        self.resumo.setText(f"{r['ocupados']} de {r['quartos']} quartos ocupados · {r['prontos']} prontos · "
                            f"{r['sujos']} a arrumar · {r['manutencao']} em manutenção · {r['hospedes']} hóspede(s) · "
                            f"{r['chegadas']} chegada(s) e {r['saidas']} saída(s) hoje")
        indice = self.abas.currentIndex()
        self._atualizar_hoje(painel)
        if indice == 1:
            self._atualizar_mapa()
        elif indice == 2:
            self._atualizar_reservas()
        elif indice == 3:
            self._atualizar_hospedes()
        elif indice == 4:
            self._atualizar_governanca(painel)
        elif indice == 5:
            self._atualizar_relatorios()
        elif indice == 6:
            self._atualizar_cadastro()

    def nova_reserva(self, uh_id: int | None = None, entrada: str | None = None):
        if not self.ctx.hotel.uhs():
            self.avisar("Cadastre os tipos de quarto e os quartos em Quartos e tarifas.")
            return None
        dialogo = DialogoReserva(self.ctx, uh_id, entrada, parent=self)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            e = self.ctx.hotel.estadia(dialogo.estadia_id)
            self.atualizar()
            self.avisar(f"Reserva feita: quarto {e['uh']}, {e['titular_nome']}, {_quando(e)}.")
        return dialogo

    def checkin_sem_reserva(self):
        dialogo = DialogoReserva(self.ctx, agora=True, parent=self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return None
        estadia_id = dialogo.estadia_id
        if not self._checkin(estadia_id):
            self.ctx.hotel.cancelar(estadia_id, "check-in sem reserva desistido no balcão")
            self.atualizar()
        return estadia_id

    def _checkin(self, estadia_id: int) -> bool:
        dialogo = DialogoCheckin(self.ctx, estadia_id, parent=self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False
        e = self.ctx.hotel.estadia(estadia_id)
        self.atualizar()
        self.avisar(f"Check-in feito: quarto {e['uh']}, conta {e['conta']} no caixa.")
        return True

    def fazer_checkin(self):
        estadia_id = _selecionado(self.tab_chegadas)
        if estadia_id is None:
            self.avisar("Escolha a chegada na lista.")
            return
        self._checkin(estadia_id)

    def fazer_checkout(self):
        estadia_id = _selecionado(self.tab_hospedados)
        if estadia_id is None:
            self.avisar("Escolha o hóspede na lista dos hospedados.")
            return
        try:
            dialogo = DialogoCheckout(self.ctx, estadia_id, parent=self)
        except (ErroNegocio, ErroValidacao) as erro:
            self.avisar(str(erro))
            return
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        r = dialogo.resultado
        self.atualizar()
        falta = r["total_cent"] - r["pago_cent"]
        self.avisar(f"Check-out feito. Conta {r['conta']}: {fmt.fmt_brl(r['total_cent'])}"
                    + (f", falta receber {fmt.fmt_brl(falta)} no caixa." if falta > 0 else ", já paga."))
        if falta > 0 and QMessageBox.question(self, "Receber a conta", f"Abrir a conta {r['conta']} no caixa para "
                                              "receber agora?") == QMessageBox.StandardButton.Yes:
            self._abrir_no_caixa(r["conta"])

    def _abrir_no_caixa(self, conta: int):
        abrir = getattr(self.app, "abrir_caixa", None)
        if abrir is None:
            self.avisar(f"Abra o caixa e chame a comanda {conta}.")
            return
        janela = abrir()
        if janela is not None and hasattr(janela, "ent_pos"):
            janela.ent_pos.setText(str(conta))
            janela.chamar_posicao()

    def abrir_conta_no_caixa(self):
        estadia_id = _selecionado(self.tab_hospedados)
        if estadia_id is None:
            self.avisar("Escolha o hóspede na lista dos hospedados.")
            return
        e = self.ctx.hotel.estadia(estadia_id)
        if not e["conta_aberta"]:
            self.avisar(f"A conta {e['conta']} já foi fechada no caixa.")
            return
        self._abrir_no_caixa(e["conta"])

    def lancar_cafe(self):
        estadia_id = _selecionado(self.tab_hospedados)
        if estadia_id is None:
            self.avisar("Escolha o hóspede na lista dos hospedados.")
            return
        e = self.ctx.hotel.estadia(estadia_id)
        pessoas, ok = QInputDialog.getInt(self, "Café avulso", f"Quarto {e['uh']}: quantas pessoas tomaram o café?",
                                          e["adultos"] + e["criancas"], 1, 20)
        if ok and self._executar(self.ctx.hotel.lancar_cafe, estadia_id, pessoas):
            self.avisar(f"Café de {pessoas} pessoa(s) lançado na conta {e['conta']}.")

    def lancar_diarias_vencidas(self):
        total = self._executar(self.ctx.hotel.lancar_diarias_vencidas)
        if total is not None:
            self.avisar(f"{total} diária(s) lançada(s) nas contas." if total else "Nenhuma diária vencida para lançar.")

    def _pedir_data(self, titulo: str, rotulo: str, atual: str) -> str | None:
        dialogo = QDialog(self)
        dialogo.setWindowTitle(titulo)
        layout = QVBoxLayout(dialogo)
        layout.addWidget(QLabel(rotulo))
        campo = _campo_data(atual)
        layout.addWidget(campo)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(dialogo.accept)
        botoes.rejected.connect(dialogo.reject)
        layout.addWidget(botoes)
        return _iso(campo.date()) if dialogo.exec() == QDialog.DialogCode.Accepted else None

    def prorrogar(self):
        estadia_id = _selecionado(self.tab_hospedados)
        if estadia_id is None:
            self.avisar("Escolha o hóspede na lista dos hospedados.")
            return
        e = self.ctx.hotel.estadia(estadia_id)
        nova = self._pedir_data("Prorrogar ou antecipar", f"Quarto {e['uh']}: nova data de saída", e["saida_prevista"])
        if nova and self._executar(self.ctx.hotel.alterar_datas, estadia_id, None, nova) is not None or (
                nova and not self.mensagem.text()):
            self.avisar(f"Saída do quarto {e['uh']} mudada para {fmt.fmt_data(nova)}.")

    def mudar_datas(self):
        estadia_id = _selecionado(self.tab_reservas)
        if estadia_id is None:
            self.avisar("Escolha a reserva na lista.")
            return
        e = self.ctx.hotel.estadia(estadia_id)
        if e["situacao"] == "hospedada":
            nova = self._pedir_data("Mudar a saída", "Nova data de saída", e["saida_prevista"])
            if nova:
                self._executar(self.ctx.hotel.alterar_datas, estadia_id, None, nova)
            return
        entrada = self._pedir_data("Mudar datas", "Nova data de entrada", e["entrada_prevista"])
        if not entrada:
            return
        saida = self._pedir_data("Mudar datas", "Nova data de saída", e["saida_prevista"])
        if saida:
            self._executar(self.ctx.hotel.alterar_datas, estadia_id, entrada, saida)

    def trocar_quarto(self, tabela: QTableWidget):
        estadia_id = _selecionado(tabela)
        if estadia_id is None:
            self.avisar("Escolha a estadia na lista.")
            return
        e = self.ctx.hotel.estadia(estadia_id)
        inicio, fim = self.ctx.hotel._intervalo(e)
        livres = [u for u in self.ctx.hotel.disponiveis(inicio, fim, e["adultos"] + e["criancas"]) if u["id"] != e["uh_id"]]
        if not livres:
            self.avisar("Nenhum outro quarto livre para essa estadia.")
            return
        rotulos = [f"{u['numero']} — {u['tipo']} ({u['limpeza_rotulo'].lower()})" for u in livres]
        escolha, ok = QInputDialog.getItem(self, "Trocar de quarto", f"{e['titular_nome']}: ir para", rotulos, 0, False)
        if ok:
            nova = livres[rotulos.index(escolha)]
            self._executar(self.ctx.hotel.trocar_quarto, estadia_id, nova["id"], True)

    def cancelar_reserva(self, tabela: QTableWidget):
        estadia_id = _selecionado(tabela)
        if estadia_id is None:
            self.avisar("Escolha a reserva na lista.")
            return
        motivo, ok = QInputDialog.getText(self, "Cancelar reserva", "Motivo do cancelamento:")
        if ok:
            self._executar(self.ctx.hotel.cancelar, estadia_id, motivo)

    def marcar_nao_compareceu(self):
        estadia_id = _selecionado(self.tab_chegadas)
        if estadia_id is None:
            self.avisar("Escolha a chegada na lista.")
            return
        self._executar(self.ctx.hotel.nao_compareceu, estadia_id)

    def mostrar_estadia(self, estadia_id):
        if estadia_id is None:
            return
        e = self.ctx.hotel.estadia(estadia_id)
        linhas = [f"Quarto {e['uh']} ({e['tipo']}) · {e['situacao_rotulo']}", f"{e['titular_nome']} · {_quando(e)} · "
                  f"{_noites(e)}", f"{e['adultos']} adulto(s), {e['criancas']} criança(s) · origem {e['origem_rotulo']}"]
        if e["telefone"]:
            linhas.append(f"Telefone: {e['telefone']}")
        if e["conta"]:
            linhas.append(f"Conta {e['conta']} no caixa" + (" (aberta)" if e["conta_aberta"] else " (fechada)"))
        for a in e["acompanhantes"]:
            linhas.append(f"Acompanhante: {a['nome']}" + (f" (responsável: {a['responsavel']})" if a["responsavel"] else ""))
        if e["observacao"]:
            linhas.append(f"Observação: {e['observacao']}")
        if e["motivo_cancelamento"]:
            linhas.append(f"Cancelada: {e['motivo_cancelamento']}")
        QMessageBox.information(self, f"Estadia no quarto {e['uh']}", "\n".join(linhas))
