"""Vários caixas na mesma loja: a tela do caixa principal (Caixas da loja) e a ligação de um caixa adicional.

O que acontece por baixo está em src/database/rede.py. No principal, a loja liga o atendimento, copia o código de
ligação e acompanha quem está ligado. No computador adicional, o código é colado na tela de entrada.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QInputDialog, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.core import edicao
from src.core.erros import ErroNegocio, ErroPermissao
from src.database import rede
from src.ui_qt.tema import texto


class JanelaCaixasDaLoja(QDialog):
    """No caixa principal: liga o atendimento aos outros caixas, mostra o código de ligação e quem está ligado."""

    def __init__(self, ctx, servico=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.servico = servico
        self.exigir_acesso()
        self.setWindowTitle("Caixas da loja")
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Caixas da loja", "titulo"))
        self.explicacao = texto("", "suave")
        self.explicacao.setWordWrap(True)
        layout.addWidget(self.explicacao)
        self.atender = QCheckBox("Atender outros caixas da loja neste computador (caixa principal)")
        self.atender.clicked.connect(self._alternar)
        layout.addWidget(self.atender)
        self.estado = texto("", "aviso")
        self.estado.setWordWrap(True)
        layout.addWidget(self.estado)
        layout.addWidget(texto("Código de ligação (cole no outro computador, na tela de entrada)"))
        self.codigo = QPlainTextEdit()
        self.codigo.setReadOnly(True)
        self.codigo.setMaximumHeight(96)
        layout.addWidget(self.codigo)
        barra_codigo = QHBoxLayout()
        self.btn_copiar = QPushButton("Copiar código")
        self.btn_copiar.clicked.connect(self._copiar)
        self.btn_trocar = QPushButton("Gerar código novo")
        self.btn_trocar.setToolTip("Use se o código vazou. Os outros caixas precisam receber o código de novo.")
        self.btn_trocar.clicked.connect(self._trocar_codigo)
        barra_codigo.addWidget(self.btn_copiar)
        barra_codigo.addWidget(self.btn_trocar)
        barra_codigo.addStretch()
        layout.addLayout(barra_codigo)
        layout.addWidget(texto("Caixas adicionais"))
        self.tabela = QTableWidget(0, 4)
        self.tabela.setHorizontalHeaderLabels(["Caixa", "Computador", "Situação", "Ligado desde"])
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabela.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.tabela, 1)
        barra = QHBoxLayout()
        self.btn_liberar = QPushButton("Liberar o número selecionado")
        self.btn_liberar.setToolTip("Para trocar o computador de um caixa: solta o número para a máquina nova usar.")
        self.btn_liberar.clicked.connect(self._liberar)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.close)
        barra.addWidget(self.btn_liberar)
        barra.addStretch()
        barra.addWidget(fechar)
        layout.addLayout(barra)
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.atualizar)
        self._timer.start()
        self.atualizar()

    def exigir_acesso(self):
        operador_id = self.ctx.operador_id
        if operador_id is None:
            raise ErroPermissao("Entre novamente para configurar os caixas da loja.")
        self.ctx.acesso.exigir(self.ctx.acesso.operador(operador_id), "cfg_maquinas")

    # ---------------------------------------------------------------- tela
    def atualizar(self):
        banco = self.ctx.banco
        if banco.remoto:
            self.explicacao.setText(
                f"Este computador é o caixa {banco.cfg_int('terminal', 1)}, ligado ao caixa principal. O banco da loja "
                "fica lá: o código de ligação e a lista de caixas são vistos no caixa principal. Para este "
                "computador voltar a ter o banco próprio, use o botão da tela de entrada.")
            for campo in (self.atender, self.codigo, self.btn_copiar, self.btn_trocar, self.tabela, self.btn_liberar):
                campo.setEnabled(False)
            self.estado.setText("")
            return
        self.explicacao.setText(
            "Com dois ou mais computadores vendendo, este guarda o banco da loja e os outros usam o mesmo estoque, "
            "fiado e preços pela rede. Cada caixa tem o seu turno, a sua gaveta e a sua impressora. Se este "
            "computador desligar ou a rede cair, os outros param de vender até a ligação voltar.")
        ligado = banco.cfg_bool("rede_caixas", False)
        self.atender.setChecked(ligado)
        ativo = bool(self.servico and self.servico.ativo)
        if not ligado:
            self.estado.setText("Desligado: só este caixa usa o banco.")
        elif ativo:
            self.estado.setText(
                f"Atendendo na porta {rede.porta_da_loja(banco)}. Se o Windows perguntar, permita o acesso do "
                f"{edicao.atual().nome} na rede privada.")
        else:
            erro = getattr(self.servico, "ultimo_erro", None) if self.servico else None
            self.estado.setText(erro or "Ligado na configuração, mas o atendimento não está no ar. Feche e abra o programa.")
        self.codigo.setPlainText(rede.codigo_da_loja(banco) if ligado else "")
        for campo in (self.codigo, self.btn_copiar, self.btn_trocar):
            campo.setEnabled(ligado)
        self._preencher_tabela()

    def _preencher_tabela(self):
        banco = self.ctx.banco
        ligados = {c["terminal"]: c for c in (self.servico.conectados() if self.servico else [])}
        registrados = rede.terminais_registrados(banco)
        selecionado = self._terminal_selecionado()
        numeros = sorted(set(ligados) | set(registrados))
        self.tabela.setRowCount(len(numeros))
        for linha, numero in enumerate(numeros):
            agora = ligados.get(numero)
            nome = (agora or {}).get("nome") or registrados.get(numero, {}).get("nome") or ""
            desde = datetime.fromtimestamp(agora["desde"]).strftime("%d/%m %H:%M") if agora else ""
            for coluna, valor in enumerate((f"Caixa {numero}", nome, "Ligado agora" if agora else "Desligado", desde)):
                item = QTableWidgetItem(valor)
                item.setData(0x0100, numero)                     # Qt.UserRole
                self.tabela.setItem(linha, coluna, item)
            if numero == selecionado:
                self.tabela.selectRow(linha)
        self.tabela.resizeColumnsToContents()

    def _terminal_selecionado(self):
        item = self.tabela.item(self.tabela.currentRow(), 0) if self.tabela.currentRow() >= 0 else None
        return item.data(0x0100) if item is not None else None

    # --------------------------------------------------------------- ações
    def _alternar(self, marcado):
        try:
            self.exigir_acesso()
            banco = self.ctx.banco
            banco.cfg_set("rede_caixas", "S" if marcado else "N")
            banco.log("rede_caixas_ligada" if marcado else "rede_caixas_desligada", "", self.ctx.operador_id)
            if self.servico is not None:
                self.servico.ultimo_erro = None
                try:
                    self.servico.reiniciar()
                except ErroNegocio as erro:
                    self.servico.ultimo_erro = str(erro)
        except ErroNegocio as erro:
            self.estado.setText(str(erro))
        self.atualizar()

    def _copiar(self):
        QApplication.clipboard().setText(self.codigo.toPlainText())
        self.estado.setText("Código copiado. Quem tiver este código entra no banco da loja: não publique.")

    def _trocar_codigo(self):
        if QMessageBox.question(
                self, "Gerar código novo",
                "Os caixas adicionais param de entrar até receberem o código novo. Gerar mesmo assim?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.exigir_acesso()
            rede.trocar_chave(self.ctx.banco)
            if self.servico is not None:
                self.servico.reiniciar()
        except ErroNegocio as erro:
            self.estado.setText(str(erro))
        self.atualizar()

    def _liberar(self):
        numero = self._terminal_selecionado()
        if numero is None:
            self.estado.setText("Selecione um caixa na lista.")
            return
        if any(c["terminal"] == numero for c in (self.servico.conectados() if self.servico else [])):
            self.estado.setText(f"O caixa {numero} está ligado agora. Feche o programa nele antes de liberar o número.")
            return
        try:
            self.exigir_acesso()
            rede.liberar_terminal(self.ctx.banco, numero)
        except ErroNegocio as erro:
            self.estado.setText(str(erro))
        self.atualizar()

    def closeEvent(self, evento):
        self._timer.stop()
        super().closeEvent(evento)


# ------------------------------------------------------------- caixa adicional
def testar_ligacao(codigo: str, terminal: int) -> str:
    """Confere o código falando com o caixa principal antes de gravar: versão, edição e número do caixa. Devolve a
    identidade deste computador (a que reservou o número lá). Levanta ErroNegocio/ErroLigacao com o motivo."""
    from uuid import uuid4
    dados = rede.ler_codigo(codigo)
    anterior = rede.ligacao_salva()
    instalacao = anterior["instalacao"] if anterior else uuid4().hex
    conexao = rede.ConexaoRemota(dados["hosts"], dados["porta"], dados["chave"], terminal, instalacao)
    try:
        conexao.ligar()
    finally:
        conexao.close()
    return instalacao


def ligar_este_computador(parent, banco) -> bool:
    """Tela de entrada: transforma este computador em caixa adicional, ou desfaz. True quando mudou e o programa deve
    fechar para reabrir com o banco certo."""
    nome = edicao.atual().nome
    if banco.remoto:
        if QMessageBox.question(
                parent, "Desligar do caixa principal",
                f"Este computador deixa de ser o caixa {banco.cfg_int('terminal', 1)} e volta a usar o banco próprio. "
                "As vendas já feitas continuam no caixa principal. Desligar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        rede.remover_ligacao()
        QMessageBox.information(parent, nome, f"Pronto. Abra o {nome} de novo.")
        return True
    codigo, aceito = QInputDialog.getMultiLineText(
        parent, "Ligar a outro caixa da loja",
        "Para este computador vender no mesmo estoque do caixa principal, cole o código de ligação que aparece lá em "
        "Caixas da loja (começa com WILLCAIXA1-).\n\nO que estiver gravado neste computador não vai para o caixa "
        "principal: fica guardado aqui, sem uso.")
    if not aceito or not codigo.strip():
        return False
    terminal, aceito = QInputDialog.getInt(
        parent, "Número deste caixa", "Número deste caixa (o 1 é o caixa principal):", 2, 2, 99)
    if not aceito:
        return False
    try:
        rede.salvar_ligacao(codigo, terminal, testar_ligacao(codigo, terminal))
    except (ErroNegocio, rede.ErroLigacao) as erro:
        QMessageBox.warning(parent, "Ligar a outro caixa da loja", str(erro))
        return False
    QMessageBox.information(parent, nome, f"Ligado ao caixa principal como caixa {terminal}. Abra o {nome} de novo.")
    return True


def perguntar_sem_ligacao(parent, erro) -> str:
    """Na abertura, sem conversa com o principal: 'tentar', 'desligar' (voltar ao banco próprio) ou 'fechar'."""
    caixa = QMessageBox(parent)
    caixa.setIcon(QMessageBox.Icon.Warning)
    caixa.setWindowTitle(f"{edicao.atual().nome} • caixa adicional")
    caixa.setText(str(erro))
    caixa.setInformativeText("Este computador vende pelo banco do caixa principal. Sem a ligação ele não abre.")
    tentar = caixa.addButton("Tentar de novo", QMessageBox.ButtonRole.AcceptRole)
    desligar = caixa.addButton("Usar o banco deste computador", QMessageBox.ButtonRole.DestructiveRole)
    caixa.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
    caixa.exec()
    if caixa.clickedButton() is tentar:
        return "tentar"
    if caixa.clickedButton() is desligar:
        if QMessageBox.question(
                parent, "Usar o banco deste computador",
                "Este computador deixa de ser caixa adicional. O que for vendido aqui não aparece no caixa principal. "
                "Continuar?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            return "desligar"
        return "tentar"
    return "fechar"
