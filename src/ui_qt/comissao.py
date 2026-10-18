"""Comissão das garotas no caixa Qt: lançar (código 50), pagar/acertar (comissão, shows, vale e Pix) e cancelar lançamento.

Espelha `src/ui/comissao_ui.py` do caixa clássico: as regras são do `ComissaoController`, os papéis do `ImpressaoController` e as
senhas do `AcessoController`. Esta camada só pergunta, confere o que foi digitado e mostra o resultado.

As funções soltas recebem o caixa (`JanelaCaixa`) como anfitrião e usam dele: `ctx`, `dialogos`, `_autorizar`, `_executar`,
`_emitir`, `_registrar_falha` e os dois pontos de troca dos testes, `_dialogo_comissao` e `_dialogo_acerto`."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QDialog, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from src.controllers.comissao_controller import LIMITE_CONFIRMAR_CENT
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.ui.comissao_ui import entregar_via

VERMELHO, MUDO = "#b32020", "#5b6573"


# ===================================================================== regras de tela (as mesmas do caixa clássico)
def conferir_lancamento(dialogos, ctx, numero: int, cent: int) -> str | None:
    """As perguntas antes de lançar: garota não cadastrada, inativa e valor alto. Devolve None se tudo foi confirmado, ou o
    campo a corrigir ('numero' ou 'valor') quando o operador respondeu Não."""
    g = ctx.comissoes.garota(numero)
    if g is None and not ctx.comissoes.cadastro_vazio():
        if not dialogos.confirmar("Garota não cadastrada", f"A garota {numero} não está cadastrada.\n"
                                                           "Lançar a comissão assim mesmo?", padrao_sim=False):
            return "numero"
    elif g is not None and not g["ativo"]:
        if not dialogos.confirmar("Garota inativa", f"A garota {numero} - {g['nome']} está inativa.\n"
                                                    "Lançar a comissão assim mesmo?", padrao_sim=False):
            return "numero"
    if cent > LIMITE_CONFIRMAR_CENT and not dialogos.confirmar(
            "Confirma o valor", f"Valor alto: {fmt.fmt_brl(cent)} para a garota {numero}.\nConfirma?", padrao_sim=False):
        return "valor"
    return None


def descrever_garota(ctx, texto: str) -> tuple[str, bool]:
    """(texto, é_alerta) para mostrar ao lado do número digitado: nome, '(inativa)', 'não cadastrada' ou vazio."""
    texto = (texto or "").strip()
    try:
        n = ctx.comissoes.validar_numero(texto) if texto else None
    except ErroNegocio:
        n = None
    g = ctx.comissoes.garota(n) if n is not None else None
    if g is not None:
        return g["nome"] + ("" if g["ativo"] else " (inativa)"), not g["ativo"]
    if n is not None and not ctx.comissoes.cadastro_vazio():
        return "não cadastrada", True
    return "", False


def registrar_comissao(caixa, turno_id: int, numero: int, cent: int) -> tuple[int, str] | None:
    """Grava a comissão e imprime a via da garota. Devolve (id do lançamento, frase para o status) ou None se não gravou."""
    ctx = caixa.ctx
    ok, lancamento_id = caixa._executar(ctx.comissoes.lancar, numero, cent, turno_id, ctx.operador_id)
    if not ok:
        return None
    nome = ctx.comissoes.nome(numero)
    texto = (f"Comissão de {fmt.fmt_brl(cent)} lançada para a garota {numero}{' ' + nome if nome else ''}. "
             f"A pagar a ela: {fmt.fmt_brl(ctx.comissoes.pendente(numero))}.") + entregar_via(ctx, lancamento_id)
    return lancamento_id, texto


def lancar(caixa, sugerida: str = "") -> tuple[int, str] | None:
    """O código 50 pela janela (com `comissao_na_linha` desligada, e o botão Lançar da janela Comissões): autoriza, abre a
    janela, faz as perguntas de exceção e grava. Respondeu Não a uma pergunta: a janela volta para corrigir.
    Devolve (número da garota, frase para o status) ou None."""
    ctx = caixa.ctx
    if not caixa._autorizar("caixa_comissao", "exigir_senha_comissao", "Lançar comissão exige autorização:"):
        return None
    if ctx.turnos.atual() is None:
        caixa.dialogos.aviso("Comissão", "Abra o turno do caixa antes de lançar comissão.")
        return None
    while True:
        escolha = caixa._dialogo_comissao(sugerida)
        if escolha is None:
            return None
        numero, cent = escolha
        campo = conferir_lancamento(caixa.dialogos, ctx, numero, cent)
        if campo is None:
            break
        sugerida = str(numero) if campo == "valor" else ""
    turno = ctx.turnos.atual()
    if turno is None:
        caixa.dialogos.aviso("Comissão", "Abra o turno do caixa antes de lançar comissão.")
        return None
    r = registrar_comissao(caixa, turno["id"], numero, cent)
    return (numero, r[1]) if r is not None else None


def pagar_garota(caixa, numero: int) -> dict | None:
    """Acerta a conta da garota: autoriza, pergunta (shows, vale, Pix, se sai da gaveta), grava e entrega o recibo (e o
    comprovante da saída, quando o dinheiro saiu da gaveta). Devolve o pagamento, ou None se não houve."""
    ctx = caixa.ctx
    if not caixa._autorizar("caixa_pagar_comissao", "exigir_senha_sangria", "Pagar comissão exige autorização:"):
        return None
    itens = ctx.comissoes.lancamentos(numero)
    if not itens and not ctx.comissoes.pede_shows():
        caixa.dialogos.aviso("Comissão", f"A garota {numero} não tem comissão pendente.")
        return None
    escolha = caixa._dialogo_acerto(numero, ctx.comissoes.nome(numero), sum(i["valor_cent"] for i in itens), len(itens),
                                    ctx.banco.cfg_bool("comissao_paga_do_caixa", False))
    if escolha is None:
        return None
    turno = ctx.turnos.atual()
    ok, pag = caixa._executar(ctx.comissoes.pagar, numero, turno["id"] if turno else None, ctx.operador_id,
                              escolha["do_caixa"], escolha["shows"], escolha["valor_show_cent"], escolha["pix_cent"],
                              escolha["vale_cent"])
    if not ok:
        return None
    try:
        caixa._emitir("Recibo de acerto" if pag["shows"] else "Recibo de comissão",
                      ctx.impressao.recibo_comissao(pag, ctx.operador.nome), f"recibo_comissao_{numero}",
                      tipo="comprovante", abrir_gaveta=pag["tirou_do_caixa"])
        if pag["tirou_do_caixa"]:
            # O dinheiro saiu da gaveta: sai também o comprovante da saída financeira (o mesmo da sangria), só com o que saiu
            # do caixa (o Pix não passa por ela). A gaveta já foi aberta pelo recibo.
            caixa._emitir("Comprovante de saída",
                          ctx.impressao.comprovante_movimento("saida", pag["dinheiro_cent"], pag["movimento_descricao"],
                                                              ctx.operador.nome),
                          f"saida_comissao_{numero}", tipo="comprovante")
    except Exception as e:  # noqa: BLE001 - o pagamento já está gravado: falha do papel nunca pode parecer falha do acerto
        caixa._registrar_falha(e)
        caixa.dialogos.erro("Impressão", f"O pagamento foi gravado, mas o recibo não pôde ser preparado:\n{e}")
    return pag


def cancelar_lancamento(caixa, lancamento_id: int, rotulo: str) -> bool:
    """Cancela um lançamento de comissão pendente (senha de cancelamento, se exigida, e confirmação)."""
    ctx = caixa.ctx
    if not caixa._autorizar("caixa_cancelamento", "exigir_senha_cancelamento", "Cancelar comissão exige autorização:"):
        return False
    if not caixa.dialogos.confirmar("Cancelar comissão", f"Cancelar {rotulo}?\nEle deixa de contar como comissão a pagar.",
                                    padrao_sim=False):
        return False
    ok, _ = caixa._executar(ctx.comissoes.cancelar, int(lancamento_id), ctx.operador_id, "cancelado no caixa")
    return ok


def texto_pagamento(pag: dict) -> str:
    """A frase do status depois do acerto, como no caixa clássico."""
    if not pag["shows"]:
        return f"Comissão de {fmt.fmt_brl(pag['total_cent'])} paga à garota {pag['garota']}."
    return (f"Acerto de {fmt.fmt_brl(pag['total_cent'])} pago à garota {pag['garota']} "
            f"(comissão {fmt.fmt_brl(pag['comissao_cent'])} + {pag['shows']} shows {fmt.fmt_brl(pag['shows_cent'])}).")


# ===================================================================== janelas
def _campo(largura: int, tamanho: int = 16, direita: bool = False) -> QLineEdit:
    campo = QLineEdit()
    campo.setFont(QFont("Segoe UI", tamanho, QFont.Bold))
    campo.setMaximumWidth(largura)
    campo.setAlignment(Qt.AlignRight if direita else Qt.AlignCenter)
    return campo


def _mudo(texto: str = "") -> QLabel:
    lbl = QLabel(texto)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {MUDO};")
    return lbl


def _botoes(dlg: QDialog, caixa: QVBoxLayout, texto_ok: str, ao_ok) -> QPushButton:
    linha = QHBoxLayout()
    linha.addStretch(1)
    ok = QPushButton(texto_ok)
    ok.setObjectName("primario")
    ok.setAutoDefault(False)
    ok.clicked.connect(ao_ok)
    cancelar = QPushButton("Cancelar")
    cancelar.setAutoDefault(False)
    cancelar.clicked.connect(dlg.reject)
    linha.addWidget(ok)
    linha.addWidget(cancelar)
    caixa.addLayout(linha)
    return ok


class DialogoComissao(QDialog):
    """A janela do código 50: número da garota (já preenchido com o da comanda) e valor. `resultado` = (número, centavos).
    As perguntas de exceção (não cadastrada, inativa, valor alto) ficam com quem abre, em `lancar`."""

    def __init__(self, pai: QWidget, ctx, sugerida: str = ""):
        super().__init__(pai)
        self.ctx = ctx
        self.resultado: tuple[int, int] | None = None
        self.setWindowTitle("Comissão da garota")
        caixa = QVBoxLayout(self)
        caixa.addWidget(QLabel("Número da garota"))
        linha = QHBoxLayout()
        self.ent_numero = _campo(120, 18)
        self.ent_numero.setText(str(sugerida or ""))
        linha.addWidget(self.ent_numero)
        self.lbl_nome = QLabel("")
        self.lbl_nome.setFont(QFont("Segoe UI", 13, QFont.Bold))
        linha.addWidget(self.lbl_nome, 1)
        caixa.addLayout(linha)
        caixa.addWidget(QLabel(f"Comissão: {ctx.comissoes.rotulo_valor()}"))
        self.ent_valor = _campo(180, 18, direita=True)
        caixa.addWidget(self.ent_valor)
        self.lbl_msg = QLabel("")
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setStyleSheet(f"color: {VERMELHO};")
        caixa.addWidget(self.lbl_msg)
        _botoes(self, caixa, "Lançar", self.gravar)
        self.ent_numero.textEdited.connect(self.mostrar_nome)
        self.ent_numero.returnPressed.connect(lambda: self.ent_valor.setFocus())
        self.ent_valor.returnPressed.connect(self.gravar)
        self.mostrar_nome()
        (self.ent_valor if sugerida else self.ent_numero).setFocus()

    def mostrar_nome(self, _texto: str = "") -> None:
        texto, alerta = descrever_garota(self.ctx, self.ent_numero.text())
        self.lbl_nome.setText(texto)
        self.lbl_nome.setStyleSheet("color: #a15c00;" if alerta else f"color: {MUDO};")

    def gravar(self) -> None:
        try:
            n = self.ctx.comissoes.validar_numero(self.ent_numero.text())
        except ErroNegocio as e:
            self.lbl_msg.setText(str(e))
            self.ent_numero.setFocus()
            return
        try:
            cent = self.ctx.comissoes.para_centavos(self.ent_valor.text())
        except (ValueError, ErroNegocio) as e:
            self.lbl_msg.setText(str(e) if isinstance(e, ErroNegocio) else "Valor inválido.")
            self.ent_valor.setFocus()
            return
        if cent <= 0:
            self.lbl_msg.setText("Informe o valor da comissão.")
            self.ent_valor.setFocus()
            return
        self.resultado = (n, cent)
        self.accept()


class DialogoAcerto(QDialog):
    """O acerto da garota: a comissão marcada e, se a casa pergunta (`comissao_pede_shows`), os shows que o OPERADOR lança aqui
    (nada é contado sozinho), o vale que ela já pegou, a parte paga por Pix e se o dinheiro sai da gaveta.
    `resultado` = {"do_caixa", "shows", "valor_show_cent", "pix_cent", "vale_cent"}, como o `dialogo_pagar` do caixa clássico.
    O vale é descontado do total e não sai do caixa de novo; o Pix é sobre o que sobra depois do vale e nunca passa pela gaveta."""

    def __init__(self, pai: QWidget, ctx, numero: int, nome: str, comissao_cent: int, quantidade: int,
                 do_caixa_padrao: bool = False):
        super().__init__(pai)
        self.ctx = ctx
        self.comissao_cent = comissao_cent
        self.quantidade = quantidade
        self.pede_shows = ctx.comissoes.pede_shows()
        self.resultado: dict | None = None
        self.setWindowTitle("Pagar comissão")
        caixa = QVBoxLayout(self)
        titulo = QLabel(f"Garota {numero} {nome}".strip())
        titulo.setFont(QFont("Segoe UI", 12, QFont.Bold))
        caixa.addWidget(titulo)
        caixa.addWidget(_mudo(f"{quantidade} lançamento(s) de comissão a pagar" if quantidade else "Sem comissão marcada"))
        lbl_com = QLabel(f"Comissão: {fmt.fmt_brl(comissao_cent)}")
        lbl_com.setFont(QFont("Georgia", 14, QFont.Bold))
        caixa.addWidget(lbl_com)

        self.ent_qtd: QLineEdit | None = None
        self.grupo_show = QButtonGroup(self)
        if self.pede_shows:
            quadro = QGroupBox("Shows (lançados por você)")
            q = QVBoxLayout(quadro)
            linha = QHBoxLayout()
            linha.addWidget(QLabel("Quantidade de shows:"))
            self.ent_qtd = _campo(90, 16)
            self.ent_qtd.textEdited.connect(self.calcular)
            linha.addWidget(self.ent_qtd)
            linha.addStretch(1)
            q.addLayout(linha)
            valores = QHBoxLayout()
            valores.addWidget(QLabel("Valor de cada show:"))
            for cent in ctx.comissoes.valores_show():
                botao = QRadioButton(fmt.fmt_brl(cent))
                self.grupo_show.addButton(botao, cent)
                valores.addWidget(botao)
            valores.addStretch(1)
            q.addLayout(valores)
            self.grupo_show.idClicked.connect(lambda _id: self.calcular())
            caixa.addWidget(quadro)

        linha_vale = QHBoxLayout()
        linha_vale.addWidget(QLabel("A garota pegou vale? Valor do vale (R$):"))
        self.ent_vale = _campo(130, 14, direita=True)
        self.ent_vale.textEdited.connect(self.calcular)
        linha_vale.addWidget(self.ent_vale)
        linha_vale.addStretch(1)
        caixa.addLayout(linha_vale)
        caixa.addWidget(_mudo("O vale é descontado do total (pago em dinheiro ou em Pix) e não sai do caixa de novo: aquele "
                              "dinheiro já saiu quando ela o pegou. Deixe vazio se não tem vale."))
        self.lbl_vale = _mudo()
        caixa.addWidget(self.lbl_vale)
        caixa.addWidget(QLabel("TOTAL A PAGAR"))
        self.lbl_total = QLabel("")
        self.lbl_total.setFont(QFont("Georgia", 24, QFont.Bold))
        caixa.addWidget(self.lbl_total)

        quadro_pix = QGroupBox("Pagamento")
        qp = QVBoxLayout(quadro_pix)
        linha_pix = QHBoxLayout()
        linha_pix.addWidget(QLabel("Parte paga por Pix (R$):"))
        self.ent_pix = _campo(130, 14, direita=True)
        self.ent_pix.textEdited.connect(self.calcular)
        linha_pix.addWidget(self.ent_pix)
        self.btn_tudo_pix = QPushButton("Tudo no Pix")
        self.btn_tudo_pix.setAutoDefault(False)
        self.btn_tudo_pix.clicked.connect(self.tudo_no_pix)
        linha_pix.addWidget(self.btn_tudo_pix)
        linha_pix.addStretch(1)
        qp.addLayout(linha_pix)
        self.lbl_divisao = _mudo()
        qp.addWidget(self.lbl_divisao)
        caixa.addWidget(quadro_pix)

        # Nem sempre sobra dinheiro no caixa: por padrão o pagamento só fica registrado (comissao_paga_do_caixa = N).
        self.chk_do_caixa = QCheckBox("O dinheiro sai da gaveta do caixa (registra uma sangria e abre a gaveta)")
        self.chk_do_caixa.setChecked(bool(do_caixa_padrao))
        caixa.addWidget(self.chk_do_caixa)
        caixa.addWidget(_mudo("Desmarcado: o acerto fica registrado como pago, sem mexer no dinheiro do caixa. "
                              "O Pix nunca sai da gaveta."))
        self.lbl_msg = QLabel("")
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setStyleSheet(f"color: {VERMELHO};")
        caixa.addWidget(self.lbl_msg)
        _botoes(self, caixa, "Pagar", self.confirmar)
        for campo in (self.ent_qtd, self.ent_vale, self.ent_pix):
            if campo is not None:
                campo.returnPressed.connect(self.confirmar)
        self.calcular()
        (self.ent_qtd or self.ent_vale).setFocus()

    # ------------------------------------------------------------------ leitura dos campos
    def _shows_txt(self) -> str:
        return self.ent_qtd.text() if self.ent_qtd is not None else "0"

    def _valor_show(self) -> int:
        return max(self.grupo_show.checkedId(), 0)          # -1 = nenhum escolhido

    @staticmethod
    def _cent(campo: QLineEdit, limite: int) -> int | None:
        """Centavos do campo (vazio = 0), ou None se o que foi digitado não é um valor entre 0 e `limite`."""
        try:
            cent = fmt.para_centavos(campo.text()) if campo.text().strip() else 0
        except ValueError:
            return None
        return cent if 0 <= cent <= limite else None

    def _shows(self) -> tuple[int, int]:
        """(quantidade, valor) válidos, ou (0, 0) enquanto o que está na tela ainda não forma um show."""
        try:
            return self.ctx.comissoes.validar_shows(self._shows_txt(), self._valor_show())
        except ErroNegocio:
            return 0, 0

    def calcular(self, *_args) -> None:
        """Atualiza o total e a divisão dinheiro/Pix. Sem shows, o total é só a comissão."""
        n, v = self._shows()
        total = self.comissao_cent + n * v
        vale = self._cent(self.ent_vale, total)
        a_pagar = total - (vale or 0)
        self.lbl_total.setText(fmt.fmt_brl(a_pagar))
        self.lbl_vale.setText("O vale é inválido ou maior que o total do acerto." if vale is None else
                              f"Total {fmt.fmt_brl(total)}  -  vale {fmt.fmt_brl(vale)}  =  {fmt.fmt_brl(a_pagar)}" if vale else "")
        pix = self._cent(self.ent_pix, a_pagar)
        self.lbl_divisao.setText("Pix maior que o total ou inválido." if pix is None else
                                 f"Dinheiro {fmt.fmt_brl(a_pagar - pix)}  +  Pix {fmt.fmt_brl(pix)}")

    def tudo_no_pix(self) -> None:
        n, v = self._shows()                                 # shows ainda incompletos: o Pix cobre ao menos a comissão
        total = self.comissao_cent + n * v
        self.ent_pix.setText(fmt.fmt_num(total - (self._cent(self.ent_vale, total) or 0)))
        self.calcular()
        self.ent_pix.setFocus()

    def confirmar(self) -> None:
        try:
            n, v = self.ctx.comissoes.validar_shows(self._shows_txt() if self.pede_shows else 0, self._valor_show())
        except ErroNegocio as e:
            self.lbl_msg.setText(str(e))
            return
        if not self.quantidade and not n:
            self.lbl_msg.setText("Esta garota não tem comissão marcada: informe os shows para acertar.")
            if self.ent_qtd is not None:
                self.ent_qtd.setFocus()
            return
        total = self.comissao_cent + n * v
        vale = self._cent(self.ent_vale, total)
        if vale is None:
            self.lbl_msg.setText("O vale é inválido ou maior que o total do acerto.")
            self.ent_vale.setFocus()
            return
        pix = self._cent(self.ent_pix, total - vale)
        if pix is None:
            self.lbl_msg.setText("O valor do Pix é inválido ou maior que o total a pagar.")
            self.ent_pix.setFocus()
            return
        self.resultado = {"do_caixa": self.chk_do_caixa.isChecked(), "shows": n, "valor_show_cent": v, "pix_cent": pix,
                          "vale_cent": vale}
        self.accept()


def _tabela(colunas: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(colunas))
    t.setHorizontalHeaderLabels(colunas)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    return t


def _preencher(tabela: QTableWidget, linhas: list[list], chaves: list, direita: tuple[int, ...]) -> None:
    tabela.setRowCount(0)
    for valores, chave in zip(linhas, chaves):
        linha = tabela.rowCount()
        tabela.insertRow(linha)
        for col, texto in enumerate(valores):
            celula = QTableWidgetItem(str(texto))
            celula.setData(Qt.UserRole, chave)
            if col in direita:
                celula.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tabela.setItem(linha, col, celula)


def _chave(tabela: QTableWidget):
    linha = tabela.currentRow()
    item = tabela.item(linha, 0) if linha >= 0 else None
    return item.data(Qt.UserRole) if item is not None else None


def _selecionar(tabela: QTableWidget, chave) -> bool:
    for linha in range(tabela.rowCount()):
        if tabela.item(linha, 0).data(Qt.UserRole) == chave:
            tabela.setCurrentCell(linha, 0)
            return True
    return False


class JanelaComissoes(QDialog):
    """Comissões a pagar: uma linha por garota e, ao lado, os lançamentos dela. Lança, paga (com recibo) e cancela lançamento.
    Não é modal: o caixa continua à mão; cada mudança recarrega a comanda que está no caixa."""

    def __init__(self, caixa):
        super().__init__(caixa)
        self.caixa = caixa
        self.ctx = caixa.ctx
        self.setWindowTitle("Comissões das garotas")
        self.resize(1000, 540)
        geral = QVBoxLayout(self)
        self.lbl_total = QLabel("")
        self.lbl_total.setFont(QFont("Segoe UI", 12, QFont.Bold))
        geral.addWidget(self.lbl_total)
        meio = QHBoxLayout()
        esq = QGroupBox("Garotas com comissão a pagar")
        self.tabela_garotas = _tabela(["Nº", "Nome", "Lanç.", "A pagar"])
        QVBoxLayout(esq).addWidget(self.tabela_garotas)
        meio.addWidget(esq, 1)
        dir_ = QGroupBox("Lançamentos da garota escolhida")
        self.tabela_lancamentos = _tabela(["Nº", "Quando", "Valor", "Operador", "Observação"])
        QVBoxLayout(dir_).addWidget(self.tabela_lancamentos)
        meio.addWidget(dir_, 1)
        geral.addLayout(meio, 1)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        geral.addWidget(self.lbl_status)
        barra = QHBoxLayout()
        self.btn_lancar = QPushButton("Lançar comissão")
        self.btn_lancar.clicked.connect(self.lancar)
        self.btn_pagar = QPushButton("Pagar a garota escolhida")
        self.btn_pagar.setObjectName("primario")
        self.btn_pagar.clicked.connect(self.pagar)
        self.btn_cancelar = QPushButton("Cancelar lançamento")
        self.btn_cancelar.setObjectName("perigo")
        self.btn_cancelar.clicked.connect(self.cancelar)
        self.btn_atualizar = QPushButton("Atualizar")
        self.btn_atualizar.clicked.connect(self.atualizar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.close)
        for b in (self.btn_lancar, self.btn_pagar, self.btn_cancelar, self.btn_atualizar):
            b.setAutoDefault(False)
            barra.addWidget(b)
        barra.addStretch(1)
        barra.addWidget(fechar)
        geral.addLayout(barra)
        self.tabela_garotas.currentCellChanged.connect(lambda *_: self._mostrar_lancamentos())
        self.atualizar()

    def _mudou(self) -> None:
        self.atualizar()
        self.caixa.recarregar()

    # ------------------------------------------------------------------ lista
    def atualizar(self) -> None:
        atual = self.garota_escolhida()
        pend = self.ctx.comissoes.pendentes_por_garota()
        self.tabela_garotas.blockSignals(True)
        _preencher(self.tabela_garotas, [[p["garota"], p["nome"], p["lancamentos"], fmt.fmt_num(p["total_cent"])]
                                         for p in pend], [int(p["garota"]) for p in pend], direita=(0, 2, 3))
        if pend and not (atual is not None and _selecionar(self.tabela_garotas, atual)):
            self.tabela_garotas.setCurrentCell(0, 0)
        self.tabela_garotas.blockSignals(False)
        total = sum(p["total_cent"] for p in pend)
        self.lbl_total.setText(f"Total a pagar às garotas: {fmt.fmt_brl(total)}" if pend else "Nenhuma comissão a pagar.")
        self._mostrar_lancamentos()

    def garota_escolhida(self) -> int | None:
        return _chave(self.tabela_garotas)

    def selecionar_garota(self, numero: int) -> bool:
        ok = _selecionar(self.tabela_garotas, int(numero))
        self._mostrar_lancamentos()
        return ok

    def selecionar_lancamento(self, lancamento_id: int) -> bool:
        return _selecionar(self.tabela_lancamentos, int(lancamento_id))

    def _mostrar_lancamentos(self) -> None:
        n = self.garota_escolhida()
        itens = self.ctx.comissoes.lancamentos(n) if n is not None else []
        _preencher(self.tabela_lancamentos, [[i["id"], fmt.fmt_datahora(i["criado_em"])[:16], fmt.fmt_num(i["valor_cent"]),
                                              i["operador"] or "", i["observacao"] or ""] for i in itens],
                   [int(i["id"]) for i in itens], direita=(0, 2))

    # ------------------------------------------------------------------ ações
    def lancar(self) -> None:
        r = lancar(self.caixa, str(self.garota_escolhida() or ""))
        if r is not None:
            self.lbl_status.setText(r[1])
        self._mudou()

    def pagar(self) -> None:
        n = self.garota_escolhida()
        if n is None:
            self.caixa.dialogos.aviso("Comissões", "Escolha uma garota da lista.")
            return
        pag = pagar_garota(self.caixa, n)
        if pag is not None:
            self.lbl_status.setText(texto_pagamento(pag))
        self._mudou()                              # nada a pagar (ou já pago em outro lugar): a lista se corrige

    def cancelar(self) -> None:
        lid = _chave(self.tabela_lancamentos)
        if lid is None:
            self.caixa.dialogos.aviso("Comissões", "Escolha, na lista da direita, o lançamento que será cancelado.")
            return
        linha = self.tabela_lancamentos.currentRow()
        valor = self.tabela_lancamentos.item(linha, 2).text()
        if cancelar_lancamento(self.caixa, lid, f"o lançamento {lid} de R$ {valor}"):
            self.lbl_status.setText(f"Lançamento {lid} cancelado.")
            self._mudou()
