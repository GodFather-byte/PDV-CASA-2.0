"""Painel de alertas operacionais (Qt), só leitura do banco local e atualização manual.

`JanelaAlertas(ctx, parent=None)` levanta ErroPermissao se o operador não puder ver nenhuma seção. Ao reabrir a instância
existente, o menu chama `exigir_acesso()`, que reconsulta o operador e recorta as seções permitidas.
"""
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers.alertas_controller import CATEGORIAS, ROTULO_NIVEL, AlertasController
from src.core.erros import ErroPermissao
from src.ui_qt.tema import texto

ROTULO_SECAO = {"estoque": "estoque (Relatórios de estoque)", "operacao": "operação (Relatórios informativos)"}
COR_NIVEL = {"critico": "#b42318", "aviso": "#a15c00", "info": "#5b6470"}


class JanelaAlertas(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.alertas = AlertasController(ctx.banco)
        self.secoes = self.alertas.exigir_secoes(ctx.operador_id)
        self.setWindowTitle("Alertas da casa")
        self.resize(1100, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Alertas da casa", "titulo"))
        self.resumo = texto("")
        layout.addWidget(self.resumo)
        self.secoes_texto = texto("", "suave")
        layout.addWidget(self.secoes_texto)
        self.grade = QTableWidget(0, 4)
        self.grade.setHorizontalHeaderLabels(("Nível", "Área", "Alerta", "Detalhe"))
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.setAlternatingRowColors(True)
        self.grade.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.grade)
        barra = QHBoxLayout()
        self.btn_atualizar = QPushButton("Atualizar (F5)")
        self.btn_atualizar.clicked.connect(self.atualizar)
        self.btn_fechar = QPushButton("Fechar (Esc)")
        self.btn_fechar.clicked.connect(self.close)
        barra.addWidget(self.btn_atualizar)
        barra.addStretch(1)
        barra.addWidget(self.btn_fechar)
        layout.addLayout(barra)
        QShortcut(QKeySequence("F5"), self, activated=self.atualizar)
        self._preencher()

    def exigir_acesso(self) -> set:
        """Reconsulta o operador no banco: recorta as seções permitidas e atualiza; sem nenhuma, limpa e levanta."""
        secoes = self.alertas.secoes_permitidas(self.ctx.operador_id)
        self.secoes = secoes
        if not secoes:
            self.grade.setRowCount(0)
            self.resumo.setText("Acesso aos alertas não permitido para o operador atual.")
            self.secoes_texto.setText("")
            raise ErroPermissao("Seu nível de acesso não permite ver os alertas (relatórios de estoque ou informativos).")
        self._preencher()
        return secoes

    def atualizar(self) -> None:
        try:
            self.exigir_acesso()
        except ErroPermissao:
            pass

    def _preencher(self) -> None:
        lista = self.alertas.alertas(self.secoes)
        self.grade.setRowCount(len(lista))
        for linha, a in enumerate(lista):
            for coluna, valor in enumerate((ROTULO_NIVEL[a["nivel"]], CATEGORIAS[a["categoria"]], a["titulo"], a["detalhe"])):
                item = QTableWidgetItem(valor)
                item.setForeground(QColor(COR_NIVEL[a["nivel"]]))
                self.grade.setItem(linha, coluna, item)
        self.grade.resizeColumnsToContents()
        c = self.alertas.contagem(lista)
        self.resumo.setText("Nenhum alerta agora." if not lista else
                            f"{c['critico']} crítico(s), {c['aviso']} de atenção, {c['info']} informativo(s)")
        vistas = ", ".join(ROTULO_SECAO[s] for s in sorted(self.secoes))
        ocultas = [ROTULO_SECAO[s] for s in sorted(set(ROTULO_SECAO) - self.secoes)]
        self.secoes_texto.setText(f"Mostrando: {vistas}." + (f" Sem permissão para: {', '.join(ocultas)}." if ocultas else "")
                                  + " Consulta só leitura do banco deste caixa; atualização manual (F5).")
