"""Coleta Qt da conferência por forma, sem gravar nem fechar turno."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio


class DialogoFechamento(QDialog):
    def __init__(self, ctx, turno_id: int, valor_final_cent: int, parent=None):
        self.ctx, self.turno_id, self.valor_final_cent = ctx, turno_id, valor_final_cent
        self.operador_id = ctx.operador_id
        self.formas = ctx.turnos.formas_conferencia(turno_id, self.operador_id)
        self.resultado = None
        self.previa = None
        super().__init__(parent)
        self.setWindowTitle("Conferência por forma")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Informe todas as formas, inclusive zero. Não copie o esperado."))
        layout.addWidget(QLabel(f"Gaveta declarada: {fmt.fmt_brl(valor_final_cent)}"))
        grade = QGridLayout()
        layout.addLayout(grade)
        for coluna, titulo in enumerate(("Forma", "Informado (R$)", "Esperado", "Diferença")):
            grade.addWidget(QLabel(titulo), 0, coluna)
        self.campos, self.esperados, self.diferencas = {}, {}, {}
        for linha, forma in enumerate(self.formas, 1):
            chave = forma["tipo_id"]
            grade.addWidget(QLabel(forma["tipo"]), linha, 0)
            self.campos[chave] = QLineEdit()
            self.esperados[chave] = QLabel("Não revelado")
            self.diferencas[chave] = QLabel("—")
            grade.addWidget(self.campos[chave], linha, 1)
            grade.addWidget(self.esperados[chave], linha, 2)
            grade.addWidget(self.diferencas[chave], linha, 3)
        self.gaveta = QLabel("Dinheiro inclui fundo, suprimentos e sangrias; recebido já líquido de troco.")
        self.gaveta.setWordWrap(True)
        layout.addWidget(self.gaveta)
        layout.addWidget(QLabel("Justificativa (obrigatória se houver diferença)"))
        self.motivo = QLineEdit()
        layout.addWidget(self.motivo)
        self.mensagem = QLabel("")
        self.mensagem.setWordWrap(True)
        layout.addWidget(self.mensagem)
        conferir = QPushButton("Conferir")
        conferir.clicked.connect(self.conferir)
        layout.addWidget(conferir)
        self.btn_aceitar = QPushButton("Usar declaração")
        self.btn_aceitar.setEnabled(False)
        self.btn_aceitar.clicked.connect(self.aceitar)
        layout.addWidget(self.btn_aceitar)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        layout.addWidget(cancelar)

    def _comparar(self):
        if self.ctx.operador_id != self.operador_id:
            raise ErroNegocio("O operador mudou. Cancele e inicie novamente a conferência.")
        valores = {}
        for forma in self.formas:
            texto = self.campos[forma["tipo_id"]].text().strip()
            if not texto or not any(c.isdigit() for c in texto):
                raise ErroNegocio(f"Informe o valor de {forma['tipo']}, inclusive zero.")
            valores[forma["tipo_id"]] = fmt.para_centavos(texto)
        previa = self.ctx.turnos.conferencia_fechamento(
            self.turno_id, self.operador_id, self.valor_final_cent, informados_por_forma=valores)
        return valores, previa

    def _mostrar(self, previa):
        self.previa = previa
        for linha in previa["linhas"]:
            self.esperados[linha["tipo_id"]].setText(fmt.fmt_brl(linha["esperado_cent"]))
            self.diferencas[linha["tipo_id"]].setText(fmt.fmt_brl(linha["diferenca_cent"]))
        g = previa["gaveta"]
        self.gaveta.setText(f"Gaveta: esperado {fmt.fmt_brl(g['esperado_cent'])} / "
                            f"informado {fmt.fmt_brl(g['informado_cent'])} / diferença {fmt.fmt_brl(g['diferenca_cent'])}")
        self.mensagem.setText("Há diferença: justifique para continuar." if previa["tem_diferenca"]
                             else "Valores conferidos. Confirme para usar esta declaração.")
        self.btn_aceitar.setEnabled(True)

    def conferir(self):
        try:
            _, previa = self._comparar()
            self._mostrar(previa)
            return True
        except (ErroNegocio, ValueError, OverflowError) as erro:
            self.previa = None
            self.btn_aceitar.setEnabled(False)
            self.mensagem.setText(str(erro))
            return False

    def aceitar(self):
        try:
            valores, previa = self._comparar()
            if self.previa != previa:
                self._mostrar(previa)
                self.mensagem.setText("A conferência mudou. Revise os valores e confirme novamente.")
                return False
            motivo = self.motivo.text().strip()
            if previa["tem_diferenca"] and not motivo:
                raise ErroNegocio("Informe a justificativa obrigatória da diferença.")
            self.resultado = {"informados_por_forma": valores, "justificativa": motivo}
            self.accept()
            return True
        except (ErroNegocio, ValueError, OverflowError) as erro:
            self.mensagem.setText(str(erro))
            return False


def coletar(ctx, turno_id: int, valor_final_cent: int, parent=None) -> dict | None:
    dialogo = DialogoFechamento(ctx, turno_id, valor_final_cent, parent)
    return dialogo.resultado if dialogo.exec() == QDialog.DialogCode.Accepted else None
