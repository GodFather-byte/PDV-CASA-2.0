"""Assistente Qt independente para seleção, diagnóstico e teste de impressora."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QMessageBox, QPushButton,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.controllers import impressao_assistente as assistente
from src.core.erros import ErroPermissao
from src.hardware import impressoras_so
from src.ui_qt.tema import texto


class JanelaAssistenteImpressora(QDialog):
    """Janela de diagnóstico de impressoras sem instalar drivers ou alterar filas."""

    def __init__(self, ctx, parent=None, ao_configurar=None):
        super().__init__(parent)
        self.ctx = ctx
        self.ao_configurar = ao_configurar
        self.impressoras = []
        self.setWindowTitle("Assistente de impressora")
        self.resize(950, 700)

        layout = QVBoxLayout(self)
        layout.addWidget(texto("Assistente de impressora", "titulo"))
        layout.addWidget(texto(
            "Escolha uma impressora instalada, confira os achados e configure o caixa. "
            "O teste só informa que o envio foi solicitado; confirme se o papel realmente saiu.",
            "suave"))
        layout.addWidget(texto(
            "Por segurança, instalar driver genérico e limpar ou destravar filas do Windows "
            "não estão disponíveis nesta janela. Use o driver do fabricante nas configurações do Windows.",
            "aviso"))

        self.grade = QTableWidget(0, 4)
        self.grade.setHorizontalHeaderLabels(("Impressora", "Porta e driver", "Situação", "Na fila"))
        self.grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grade.horizontalHeader().setStretchLastSection(True)
        self.grade.doubleClicked.connect(self.configurar_e_testar)
        layout.addWidget(self.grade, 2)

        layout.addWidget(texto("O que foi encontrado", "subtitulo"))
        self.achados = QPlainTextEdit()
        self.achados.setReadOnly(True)
        self.achados.setMaximumHeight(175)
        layout.addWidget(self.achados, 1)

        barra = QHBoxLayout()
        self.btn_configurar = QPushButton("Configurar e enviar teste")
        self.btn_configurar.setObjectName("primario")
        self.btn_atualizar = QPushButton("Atualizar (F5)")
        self.btn_copiar = QPushButton("Copiar diagnóstico")
        self.btn_windows = QPushButton("Configurações do Windows")
        self.btn_instalar = QPushButton("Instalar driver (indisponível)")
        self.btn_fila = QPushButton("Limpar/destravar fila (indisponível)")
        self.btn_instalar.setEnabled(False)
        self.btn_fila.setEnabled(False)
        self.btn_fechar = QPushButton("Fechar")
        for botao in (self.btn_configurar, self.btn_atualizar, self.btn_copiar,
                      self.btn_windows, self.btn_instalar, self.btn_fila, self.btn_fechar):
            barra.addWidget(botao)
        layout.addLayout(barra)

        self.btn_configurar.clicked.connect(self.configurar_e_testar)
        self.btn_atualizar.clicked.connect(self.atualizar)
        self.btn_copiar.clicked.connect(self.copiar_diagnostico)
        self.btn_windows.clicked.connect(self.abrir_configuracoes_windows)
        self.btn_fechar.clicked.connect(self.close)
        self.shortcut_f5 = self.addAction("Atualizar impressoras")
        self.shortcut_f5.setShortcut("F5")
        self.shortcut_f5.triggered.connect(self.atualizar)
        self.atualizar()

    def atualizar(self):
        selecionada = self._nome_selecionado()
        try:
            self.impressoras = impressoras_so.listar_impressoras()
            self.grade.setRowCount(len(self.impressoras))
            for linha, imp in enumerate(self.impressoras):
                detalhes = " · ".join(x for x in (imp.porta, imp.driver) if x)
                situacao = imp.situacao + (" · PAUSADA" if imp.pausada else "")
                valores = (imp.nome + ("  (padrão do Windows)" if imp.padrao else ""),
                           detalhes, situacao, str(imp.trabalhos))
                for coluna, valor in enumerate(valores):
                    item = QTableWidgetItem(valor)
                    item.setData(Qt.ItemDataRole.UserRole, linha)
                    self.grade.setItem(linha, coluna, item)

            sugerida = next((i for i in self.impressoras
                             if selecionada and i.nome.strip().lower() == selecionada.lower()), None)
            sugerida = sugerida or assistente.sugerir(self.impressoras)
            if sugerida is None and self.impressoras:
                sugerida = self.impressoras[0]
            if sugerida is not None:
                indice = self.impressoras.index(sugerida)
                self.grade.selectRow(indice)
            self._mostrar_achados()
        except Exception as erro:
            self.impressoras = []
            self.grade.setRowCount(0)
            self.achados.setPlainText(f"Não foi possível atualizar a lista de impressoras: {erro}")

    def _nome_selecionado(self):
        linhas = self.grade.selectionModel().selectedRows()
        if not linhas:
            return None
        indice = linhas[0].row()
        return self.impressoras[indice].nome if indice < len(self.impressoras) else None

    def _selecionada(self):
        linhas = self.grade.selectionModel().selectedRows()
        if not linhas:
            QMessageBox.warning(self, "Impressora", "Escolha uma impressora da lista.")
            return None
        indice = linhas[0].row()
        if indice >= len(self.impressoras):
            return None
        return self.impressoras[indice]

    def _mostrar_achados(self):
        try:
            achados = assistente.diagnosticar(self.ctx.banco, self.impressoras)
        except Exception as erro:
            self.achados.setPlainText(f"Não foi possível montar o diagnóstico: {erro}")
            return
        simbolos = {"erro": "ERRO", "aviso": "ATENÇÃO", "ok": "OK"}
        linhas = []
        for achado in achados:
            linha = f"{simbolos.get(achado.nivel, 'INFO')}: {achado.texto}"
            if achado.solucao:
                linha += f"\n  Como resolver: {achado.solucao}"
            linhas.append(linha)
        self.achados.setPlainText("\n\n".join(linhas))

    def _exigir_permissao_maquinas(self):
        operador_id = self.ctx.operador_id
        if operador_id is None:
            raise ErroPermissao("Entre novamente para configurar a impressora.")
        cadastro = self.ctx.cadastros.obter("operadores", operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        operador = self.ctx.acesso.operador(operador_id)
        self.ctx.operador = operador
        self.ctx.acesso.exigir(operador, "cfg_maquinas")

    def _autorizar_acao(self):
        try:
            self._exigir_permissao_maquinas()
        except ErroPermissao as erro:
            QMessageBox.warning(self, "Acesso não permitido", str(erro))
            return False
        return True

    def configurar_e_testar(self):
        imp = self._selecionada()
        if imp is None:
            return
        if imp.virtual:
            resposta = QMessageBox.question(
                self, "Impressora virtual",
                f"'{imp.nome}' é virtual (PDF/fax) e não imprime em papel.\n"
                "Deseja configurá-la e enviar o teste mesmo assim?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return
        if not self._autorizar_acao():
            return
        try:
            assistente.configurar(self.ctx.banco, imp.nome)
        except Exception as erro:
            QMessageBox.warning(self, "Configuração da impressora", f"Não foi possível configurar: {erro}")
            return
        if self.ao_configurar:
            self.ao_configurar()

        # Revalida após gravar e imediatamente antes do envio, pois a permissão pode ter mudado.
        if not self._autorizar_acao():
            self.atualizar()
            return
        try:
            impressora = self.ctx.impressao.impressora_de("spooler", imp.nome)
            self.ctx.impressao.imprimir_teste(impressora)
        except Exception as erro:
            QMessageBox.warning(
                self, "Teste de impressão",
                f"Não foi possível concluir a chamada de impressão para '{imp.nome}': {erro}\n"
                "O papel não foi confirmado. Confira o diagnóstico e a fila no Windows.",
            )
            self.atualizar()
            return

        resposta = QMessageBox.question(
            self, "Confirme o papel",
            f"A chamada de impressão para '{imp.nome}' terminou sem erro. "
            "Isso não confirma que o papel saiu.\n\nO papel saiu corretamente?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta == QMessageBox.StandardButton.Yes:
            QMessageBox.information(self, "Teste de impressão",
                                    "Você confirmou que a página saiu. O caixa está configurado para esta impressora.")
        else:
            QMessageBox.information(
                self, "Teste de impressão",
                "O papel não foi confirmado. Confira se a impressora está ligada, com papel e online. "
                "Atualize ou copie o diagnóstico para o suporte.",
            )
        self.atualizar()

    def copiar_diagnostico(self):
        try:
            from src.versao import VERSAO
            relatorio = assistente.relatorio(self.ctx.banco, self.impressoras, versao=VERSAO)
        except Exception as erro:
            QMessageBox.warning(self, "Diagnóstico", f"Não foi possível gerar o diagnóstico: {erro}")
            return
        self.setFocus()
        self.window().activateWindow()
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(relatorio)
        QMessageBox.information(self, "Diagnóstico copiado", "Diagnóstico copiado. Cole-o numa mensagem para o suporte.")

    def abrir_configuracoes_windows(self):
        if sys.platform == "win32":
            try:
                os.startfile("ms-settings:printers")
                return
            except (AttributeError, OSError):
                pass
        QMessageBox.information(
            self, "Impressoras do Windows",
            "Abra manualmente: Iniciar > Configurações > Impressoras e scanners.",
        )
