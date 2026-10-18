"""Contas a pagar/receber Qt independentes, usando os controladores da sessão.

A data de quitação é consultiva no formulário: Quitar/Desfazer quitação são
as únicas ações que a alteram, para aplicar a validação de ContasController.quitar.
"""
from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout,
    QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto


class JanelaContas(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._exigir_acesso()
        self.id_atual = None
        self.linhas = []
        self.setWindowTitle("Contas a pagar / receber")
        self.resize(1180, 760)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Contas a pagar / receber", "titulo"))
        barra = QHBoxLayout()
        for chave, rotulo, acao in (
            ("novo", "Incluir", self.novo), ("gravar", "Gravar (Ctrl+S)", self.gravar),
            ("cancelar", "Cancelar edição", self.cancelar), ("excluir", "Excluir", self.excluir),
            ("quitar", "Quitar", self.quitar),
            ("desquitar", "Desfazer quitação", self.desquitar),
        ):
            botao = QPushButton(rotulo)
            botao.clicked.connect(acao)
            setattr(self, f"btn_{chave}", botao)
            barra.addWidget(botao)
        layout.addLayout(barra)
        self.subplano, self.tipo, self.fornecedor = QComboBox(), QComboBox(), QComboBox()
        self.descricao, self.valor = QLineEdit(), QLineEdit()
        self.documento, self.nota = QLineEdit(), QLineEdit()
        self.entrada, self.vencimento, self.quitacao = QLineEdit(), QLineEdit(), QLineEdit()
        self.quitacao.setReadOnly(True)
        self.mercadoria = QCheckBox("Refere-se a mercadorias")
        self.previsao = QCheckBox("Previsão (fora do resultado até confirmar)")
        self.meses = QSpinBox()
        self.meses.setRange(1, 120)
        formulario = QGridLayout()
        campos = (
            ("Sub plano de contas *", self.subplano), ("Descrição *", self.descricao),
            ("Tipo financeiro *", self.tipo), ("Valor *", self.valor),
            ("Documento de pagamento", self.documento), ("Nota fiscal / comprovante", self.nota),
            ("Fornecedor", self.fornecedor), ("Entrada (dd/mm/aaaa)", self.entrada),
            ("Vencimento (dd/mm/aaaa)", self.vencimento),
            ("Quitação (botão Quitar)", self.quitacao),
            ("Conta mensal: repetir por meses", self.meses),
        )
        for indice, (rotulo, campo) in enumerate(campos):
            grupo = QFormLayout()
            grupo.addRow(rotulo, campo)
            formulario.addLayout(grupo, indice // 4, indice % 4)
        formulario.addWidget(self.mercadoria, 3, 0)
        formulario.addWidget(self.previsao, 3, 1, 1, 3)
        layout.addLayout(formulario)
        layout.addWidget(texto(
            "Conta mensal repete o valor inteiro a cada mês; não divide o total. "
            "A edição e exclusão afetam apenas a conta selecionada.", "suave"))
        filtros = QHBoxLayout()
        inicio = fmt.hoje()[:8] + "01"
        self.f_de = QLineEdit(fmt.fmt_data(inicio))
        self.f_ate = QLineEdit(fmt.fmt_data(fmt.somar_meses(inicio, 1)))
        self.f_por, self.f_situacao, self.f_previsao = QComboBox(), QComboBox(), QComboBox()
        for rotulo, valor in (("Vencimento", "dt_vencimento"), ("Entrada", "dt_entrada"),
                              ("Quitação", "dt_quitacao")):
            self.f_por.addItem(rotulo, valor)
        for rotulo, valor in (("Todas", None), ("Em aberto", False), ("Quitadas", True)):
            self.f_situacao.addItem(rotulo, valor)
        for rotulo, valor in (("Todas", None), ("Previsões", True), ("Confirmadas", False)):
            self.f_previsao.addItem(rotulo, valor)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Descrição, documento ou nota")
        for rotulo, campo in (("De", self.f_de), ("Até (inclusive)", self.f_ate),
                               ("Data por", self.f_por), ("Situação", self.f_situacao),
                               ("Previsão", self.f_previsao), ("Busca", self.busca)):
            grupo = QFormLayout()
            grupo.addRow(rotulo, campo)
            filtros.addLayout(grupo)
        self.btn_listar = QPushButton("Consultar (F5)")
        self.btn_listar.clicked.connect(self.listar)
        self.busca.returnPressed.connect(self.listar)
        filtros.addWidget(self.btn_listar)
        layout.addLayout(filtros)
        cabecalhos = [
            "Vencimento", "Entrada", "Quitação", "Descrição", "Plano / Sub plano",
            "Tipo financeiro", "Valor", "Documento", "Previsão", "Parcela", "Situação",
        ]
        self.grade = QTableWidget(0, len(cabecalhos))
        self.grade.setHorizontalHeaderLabels(cabecalhos)
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.setAlternatingRowColors(True)
        self.grade.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.grade.horizontalHeader().setStretchLastSection(True)
        self.grade.itemSelectionChanged.connect(self.selecionar)
        layout.addWidget(self.grade, 1)
        self.resumo, self.mensagem = texto("", "suave"), texto("", "aviso")
        layout.addWidget(self.resumo)
        layout.addWidget(self.mensagem)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        layout.addWidget(fechar)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.gravar)
        QShortcut(QKeySequence("F5"), self, activated=self.listar)
        QShortcut(QKeySequence("Delete"), self.grade, activated=self.excluir)
        self._opcoes()
        self._novo()
        self.listar()

    def _exigir_acesso(self):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre com um operador para acessar as contas.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.acesso.exigir(self.ctx.acesso.operador(self.ctx.operador_id), "lanc_contas")

    def _erro(self, erro):
        if isinstance(erro, ErroPermissao):
            self.linhas = []
            bloqueado = self.grade.blockSignals(True)
            try:
                self.grade.setRowCount(0)
            finally:
                self.grade.blockSignals(bloqueado)
            self.resumo.clear()
            self._novo()
            for combo in (self.subplano, self.tipo, self.fornecedor):
                combo.clear()
        self.mensagem.setText(str(erro))
        return False

    def _opcoes(self):
        for combo, chave in ((self.subplano, "subplanos"), (self.tipo, "tipos_pagamento"),
                              (self.fornecedor, "fornecedores")):
            combo.clear()
            if chave == "fornecedores":
                combo.addItem("", None)
            for identificador, rotulo in self.ctx.cadastros.opcoes(chave):
                combo.addItem(rotulo, identificador)

    def _novo(self):
        self.id_atual = None
        bloqueado = self.grade.blockSignals(True)
        try:
            self.grade.clearSelection()
        finally:
            self.grade.blockSignals(bloqueado)
        for campo in (self.descricao, self.valor, self.documento, self.nota, self.quitacao):
            campo.clear()
        self.subplano.setCurrentIndex(-1)
        self.tipo.setCurrentIndex(0)
        self.fornecedor.setCurrentIndex(0)
        self.entrada.setText(fmt.fmt_data(fmt.hoje()))
        self.vencimento.setText(fmt.fmt_data(fmt.hoje()))
        self.mercadoria.setChecked(False)
        self.previsao.setChecked(False)
        self.meses.setValue(1)
        self.meses.setEnabled(True)
        for botao in (self.btn_excluir, self.btn_quitar, self.btn_desquitar):
            botao.setEnabled(False)

    def novo(self):
        try:
            self._exigir_acesso()
            self._opcoes()
            self._novo()
            self.mensagem.clear()
            self.subplano.setFocus()
            return True
        except ErroNegocio as erro:
            return self._erro(erro)

    def listar(self, selecionar=None):
        try:
            self._exigir_acesso()
            de, ate = fmt.para_data_iso(self.f_de.text()), fmt.para_data_iso(self.f_ate.text())
            if de and ate and de > ate:
                raise ErroNegocio("A data inicial não pode ser posterior à final.")
            linhas = self.ctx.contas.listar(
                de, ate, self.f_por.currentData(), quitada=self.f_situacao.currentData(),
                previsao=self.f_previsao.currentData(), texto=self.busca.text().strip() or None)
        except (ErroNegocio, ValueError) as erro:
            return self._erro(erro)
        self._novo()
        self.linhas = linhas
        self.grade.blockSignals(True)
        try:
            self.grade.setRowCount(len(linhas))
            for linha, conta in enumerate(linhas):
                situacao = "Quitada" if conta["dt_quitacao"] else (
                    "Vencida" if conta["dt_vencimento"] < fmt.hoje() else "Em aberto")
                valores = (
                    fmt.fmt_data(conta["dt_vencimento"]), fmt.fmt_data(conta["dt_entrada"]),
                    fmt.fmt_data(conta["dt_quitacao"]), conta["descricao"],
                    f"{conta['plano']} / {conta['subplano']}", conta["tipo_financeiro"],
                    fmt.fmt_num(conta["valor_cent"]), conta["documento"] or "",
                    "Sim" if conta["previsao"] else "", conta["parcela"] or "", situacao,
                )
                for coluna, valor in enumerate(valores):
                    self.grade.setItem(linha, coluna, QTableWidgetItem(str(valor)))
        finally:
            self.grade.blockSignals(False)
        total = sum(-c["valor_cent"] if c["debito"] else c["valor_cent"] for c in linhas)
        self.resumo.setText(
            f"{len(linhas)} conta(s) • Saldo do período (créditos - débitos): {fmt.fmt_brl(total)}")
        self.mensagem.setText("" if linhas else "Nenhuma conta encontrada.")
        if selecionar is not None:
            for linha, conta in enumerate(linhas):
                if conta["id"] == selecionar:
                    self.grade.selectRow(linha)
                    break
        return True

    @staticmethod
    def _escolher(combo, identificador, rotulo):
        indice = combo.findData(identificador)
        if indice < 0 and identificador is not None:
            combo.addItem(rotulo, identificador)
            indice = combo.count() - 1
        combo.setCurrentIndex(indice)

    def _carregar(self, conta):
        self.id_atual = conta["id"]
        self._escolher(self.subplano, conta["subplano_id"],
                       f"{conta['subplano']} - {conta['plano']}")
        self._escolher(self.tipo, conta["tipo_pagamento_id"], conta["tipo_financeiro"])
        self._escolher(self.fornecedor, conta["fornecedor_id"], conta["fornecedor"] or "")
        for campo, chave in ((self.descricao, "descricao"), (self.documento, "documento"),
                             (self.nota, "nota")):
            campo.setText(conta[chave] or "")
        self.valor.setText(fmt.fmt_num(conta["valor_cent"]))
        for campo, chave in ((self.entrada, "dt_entrada"), (self.vencimento, "dt_vencimento"),
                             (self.quitacao, "dt_quitacao")):
            campo.setText(fmt.fmt_data(conta[chave]))
        self.mercadoria.setChecked(bool(conta["mercadoria"]))
        self.previsao.setChecked(bool(conta["previsao"]))
        self.meses.setValue(1)
        self.meses.setEnabled(False)
        self.btn_excluir.setEnabled(True)
        self.btn_quitar.setEnabled(True)
        self.btn_desquitar.setEnabled(bool(conta["dt_quitacao"]))

    def selecionar(self):
        try:
            self._exigir_acesso()
            linha = self.grade.currentRow()
            if not self.grade.selectedItems() or not 0 <= linha < len(self.linhas):
                self._novo()
                return False
            self._carregar(self.ctx.contas.obter(self.linhas[linha]["id"]))
            self.mensagem.clear()
            return True
        except ErroNegocio as erro:
            self._novo()
            return self._erro(erro)

    def cancelar(self):
        try:
            self._exigir_acesso()
            if self.id_atual is None:
                self._novo()
            else:
                self._carregar(self.ctx.contas.obter(self.id_atual))
            self.mensagem.clear()
            return True
        except ErroNegocio as erro:
            self._novo()
            return self._erro(erro)

    def gravar(self):
        try:
            self._exigir_acesso()
            sub, tipo = self.subplano.currentData(), self.tipo.currentData()
            if not sub or not tipo:
                raise ErroNegocio("Escolha o sub plano e o tipo financeiro.")
            if not self.descricao.text().strip():
                raise ErroNegocio("Informe a descrição da conta.")
            entrada = self.entrada.text().strip() or fmt.hoje()
            dados = dict(
                descricao=self.descricao.text(), tipo_pagamento_id=tipo,
                valor_cent=fmt.para_centavos(self.valor.text()),
                dt_entrada=entrada, dt_vencimento=self.vencimento.text().strip() or entrada,
                documento=self.documento.text() or None, nota=self.nota.text() or None,
                mercadoria=self.mercadoria.isChecked(), previsao=self.previsao.isChecked(),
                fornecedor_id=self.fornecedor.currentData(),
            )
            alvo = self.id_atual
            if alvo is None:
                self.ctx.contas.incluir(sub, meses=self.meses.value(), **dados)
            else:
                self.ctx.contas.atualizar(alvo, subplano_id=sub, **dados)
        except (ErroNegocio, ValueError) as erro:
            return self._erro(erro)
        self.listar(alvo)
        return True

    def _confirmar(self, titulo, pergunta):
        return QMessageBox.question(
            self, titulo, pergunta, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _operar(self, acao):
        try:
            self._exigir_acesso()
            alvo = self.id_atual
            if alvo is None:
                return False
            conta = self.ctx.contas.obter(alvo)
            data = None
            if acao == "quitar":
                data, aceitou = QInputDialog.getText(
                    self, "Quitar conta", "Data da quitação (dd/mm/aaaa):",
                    text=fmt.fmt_data(fmt.hoje()))
                if not aceitou:
                    return False
                titulo, pergunta = "Quitar conta", f"Quitar a conta «{conta['descricao']}»?"
            elif acao == "desfazer_quitacao":
                titulo, pergunta = "Desfazer quitação", f"Reabrir a conta «{conta['descricao']}»?"
            else:
                titulo, pergunta = "Excluir conta", f"Excluir definitivamente a conta «{conta['descricao']}»?"
            if not self._confirmar(titulo, pergunta):
                return False
            # Diálogos podem deixar a janela aberta enquanto a sessão/permissão muda.
            self._exigir_acesso()
            controller = self.ctx.contas
            controller.obter(alvo)
            if acao == "quitar":
                controller.quitar(alvo, data)
            else:
                getattr(controller, acao)(alvo)
        except ErroNegocio as erro:
            return self._erro(erro)
        self.listar(None if acao == "excluir" else alvo)
        return True

    def quitar(self):
        return self._operar("quitar")

    def desquitar(self):
        return self._operar("desfazer_quitacao")

    def excluir(self):
        return self._operar("excluir")
