"""Telas da senha de segurança do dono e de apagar vendas de teste (regra em vendas_teste_controller)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from src.controllers.vendas_teste_controller import TurnoFechado, VendasTesteController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.ui_qt.tema import texto


def _senha() -> QLineEdit:
    campo = QLineEdit()
    campo.setEchoMode(QLineEdit.EchoMode.Password)
    return campo


class JanelaSenhaSeguranca(QDialog):
    """Cria ou troca a senha de segurança do dono (para trocar, pede a atual)."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctl = VendasTesteController(ctx.banco, ctx.operador_id)
        existe = self.ctl.senha_configurada()
        self.setWindowTitle("Senha de segurança do dono")
        layout = QVBoxLayout(self)
        layout.addWidget(texto(
            "Senha só do dono, diferente da senha de entrada. Ela autoriza apagar vendas de teste aqui no caixa e "
            "no painel do celular. Guarde bem: sem ela ninguém apaga venda.", "suave"))
        form = QFormLayout()
        self.atual = _senha()
        if existe:
            form.addRow("Senha atual:", self.atual)
        self.nova, self.confirma = _senha(), _senha()
        form.addRow("Senha nova:", self.nova)
        form.addRow("Repita a senha nova:", self.confirma)
        layout.addLayout(form)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        botoes = QHBoxLayout()
        salvar = QPushButton("Trocar senha" if existe else "Criar senha")
        salvar.clicked.connect(self.salvar)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        botoes.addWidget(salvar)
        botoes.addWidget(cancelar)
        layout.addLayout(botoes)

    def salvar(self) -> bool:
        try:
            self.ctl.definir_senha(self.nova.text(), self.confirma.text(), self.atual.text())
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return False
        self.accept()
        return True


class JanelaApagarVendasTeste(QDialog):
    """Escolhe o período, marca as vendas, confere o total e confirma com a senha de segurança."""

    def __init__(self, ctx, parent=None, perguntar=None):
        super().__init__(parent)
        self.ctl = VendasTesteController(ctx.banco, ctx.operador_id)
        self._perguntar = perguntar or self._perguntar_qt
        self.vendas: list[dict] = []
        self.setWindowTitle("Apagar vendas de teste")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(texto(
            "Apaga de vez as vendas marcadas, aqui e no painel do dono. O estoque volta e fica o registro na "
            "auditoria. Venda com NFC-e, devolução, fiado ou Pix recebido não pode ser apagada.", "suave"))
        linha = QHBoxLayout()
        hoje = fmt.fmt_data(fmt.hoje())
        self.inicio, self.fim = QLineEdit(hoje), QLineEdit(hoje)
        buscar = QPushButton("Buscar")
        buscar.clicked.connect(self.buscar)
        for w in (texto("De:"), self.inicio, texto("até:"), self.fim, buscar):
            linha.addWidget(w)
        layout.addLayout(linha)
        self.tabela = QTableWidget(0, 5)
        self.tabela.setHorizontalHeaderLabels(["Apagar", "Cupom", "Data", "Situação", "Total"])
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.itemChanged.connect(lambda _: self._atualizar_total())
        layout.addWidget(self.tabela)
        self.total = texto("Nenhuma venda marcada.")
        layout.addWidget(self.total)
        form = QFormLayout()
        self.senha = _senha()
        form.addRow("Senha de segurança:", self.senha)
        layout.addLayout(form)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        botoes = QHBoxLayout()
        self.botao_apagar = QPushButton("Apagar marcadas")
        self.botao_apagar.clicked.connect(self.apagar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        botoes.addWidget(self.botao_apagar)
        botoes.addWidget(fechar)
        layout.addLayout(botoes)
        self.buscar()
        if not self.ctl.senha_configurada():
            self.mensagem.setText("Crie antes a senha de segurança do dono (Utilitários > Senha de segurança).")
            self.botao_apagar.setEnabled(False)

    def buscar(self) -> None:
        self.mensagem.clear()
        inicio, fim = fmt.para_data_iso(self.inicio.text()), fmt.para_data_iso(self.fim.text())
        if not inicio or not fim:
            self.mensagem.setText("Informe as datas (dd/mm/aaaa).")
            return
        self.vendas = self.ctl.candidatas(inicio, fim)
        self.tabela.blockSignals(True)
        self.tabela.setRowCount(len(self.vendas))
        for i, v in enumerate(self.vendas):
            marca = QTableWidgetItem("")
            if v["bloqueio"]:
                marca.setFlags(Qt.ItemFlag.NoItemFlags)
                marca.setToolTip(v["bloqueio"])
            else:
                marca.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                marca.setCheckState(Qt.CheckState.Unchecked)
            situacao = v["bloqueio"] or ("cancelada" if v["status"] == "cancelada" else "fechada") + \
                (" (turno fechado)" if v["turno_fechado"] else "")
            for col, valor in enumerate([marca, str(v["cupom"] or ""), fmt.fmt_datahora(v["fechada_em"]), situacao,
                                         fmt.fmt_brl(v["total_cent"])]):
                self.tabela.setItem(i, col, valor if isinstance(valor, QTableWidgetItem) else QTableWidgetItem(valor))
        self.tabela.blockSignals(False)
        self._atualizar_total()

    def marcadas(self) -> list[dict]:
        return [v for i, v in enumerate(self.vendas)
                if self.tabela.item(i, 0) is not None and self.tabela.item(i, 0).checkState() == Qt.CheckState.Checked]

    def marcar_todas(self) -> None:
        for i, v in enumerate(self.vendas):
            if not v["bloqueio"]:
                self.tabela.item(i, 0).setCheckState(Qt.CheckState.Checked)

    def _atualizar_total(self) -> None:
        escolhidas = self.marcadas()
        total = sum(v["total_cent"] for v in escolhidas if v["status"] == "fechada")
        self.total.setText(f"{len(escolhidas)} venda(s) marcada(s), total {fmt.fmt_brl(total)}"
                           if escolhidas else "Nenhuma venda marcada.")

    def _perguntar_qt(self, mensagem: str) -> bool:
        return QMessageBox.question(self, "Apagar vendas de teste", mensagem) == QMessageBox.StandardButton.Yes

    def apagar(self) -> dict | None:
        self.mensagem.clear()
        escolhidas = self.marcadas()
        if not escolhidas:
            self.mensagem.setText("Marque as vendas de teste que vão ser apagadas.")
            return None
        total = sum(v["total_cent"] for v in escolhidas if v["status"] == "fechada")
        if not self._perguntar(f"Apagar {len(escolhidas)} venda(s), total {fmt.fmt_brl(total)}?\n"
                               "Não dá para desfazer (só restaurando um backup)."):
            return None
        ids = [v["id"] for v in escolhidas]
        try:
            try:
                resultado = self.ctl.apagar(ids, self.senha.text())
            except TurnoFechado as aviso:
                if not self._perguntar(str(aviso)):
                    return None
                resultado = self.ctl.apagar(ids, self.senha.text(), confirmar_turno_fechado=True)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))
            return None
        finally:
            self.senha.clear()
        self.buscar()
        self.mensagem.setText(f"{resultado['apagadas']} venda(s) apagada(s). A nuvem apaga na próxima sincronização.")
        return resultado
