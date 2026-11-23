"""Coleta Qt da conferência por forma, sem gravar nem fechar turno."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.ui_qt.tema import texto


class DialogoFechamento(QDialog):
    def __init__(self, ctx, turno_id: int, valor_final_cent: int, parent=None):
        self.ctx, self.turno_id, self.valor_final_cent = ctx, turno_id, valor_final_cent
        self.operador_id = ctx.operador_id
        self.formas = ctx.turnos.formas_conferencia(turno_id, self.operador_id)
        self.resultado = None
        self.previa = None
        super().__init__(parent)
        self.setWindowTitle("Conferência por forma")
        self.resize(640, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        layout.addWidget(texto("Conferência por forma", "titulo"))
        layout.addWidget(texto("Informe o valor apurado em cada forma de pagamento, inclusive zero.", "suave"))
        quadro = QFrame()
        quadro.setObjectName("cartao")
        grade = QGridLayout(quadro)
        grade.setContentsMargins(12, 10, 12, 10)
        layout.addWidget(quadro)
        layout.addWidget(texto(f"Gaveta declarada: {fmt.fmt_brl(valor_final_cent)}", "secao"))
        for coluna, titulo in enumerate(("Forma", "Informado (R$)", "Esperado", "Diferença")):
            grade.addWidget(texto(titulo, "suave", quebra=False), 0, coluna)
        self.campos, self.esperados, self.diferencas = {}, {}, {}
        for linha, forma in enumerate(self.formas, 1):
            chave = forma["tipo_id"]
            grade.addWidget(QLabel(forma["tipo"]), linha, 0)
            self.campos[chave] = QLineEdit()
            self.campos[chave].setAlignment(Qt.AlignRight)
            self.campos[chave].setAccessibleName(f"Valor informado em {forma['tipo']}")
            self.esperados[chave] = QLabel("Não revelado")
            self.diferencas[chave] = QLabel("—")
            grade.addWidget(self.campos[chave], linha, 1)
            grade.addWidget(self.esperados[chave], linha, 2)
            grade.addWidget(self.diferencas[chave], linha, 3)
        self.gaveta = texto("A gaveta inclui fundo de caixa, suprimentos, sangrias e recebimentos em dinheiro "
                            "já descontados os trocos.", "suave")
        layout.addWidget(self.gaveta)
        layout.addWidget(QLabel("Justificativa (obrigatória se houver diferença)"))
        self.motivo = QLineEdit()
        self.motivo.setAccessibleName("Justificativa da diferença")
        layout.addWidget(self.motivo)
        self.mensagem = texto("", "aviso")
        layout.addWidget(self.mensagem)
        layout.addStretch(1)
        acoes = QHBoxLayout()
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        acoes.addWidget(cancelar)
        acoes.addStretch(1)
        conferir = QPushButton("Conferir")
        conferir.clicked.connect(self.conferir)
        acoes.addWidget(conferir)
        self.btn_aceitar = QPushButton("Usar declaração")
        self.btn_aceitar.setObjectName("primario")
        self.btn_aceitar.setEnabled(False)
        self.btn_aceitar.clicked.connect(self.aceitar)
        acoes.addWidget(self.btn_aceitar)
        layout.addLayout(acoes)

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
