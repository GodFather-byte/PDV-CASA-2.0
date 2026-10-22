"""Catálogo Qt opt-in dos relatórios genéricos de ``relatorios_ui.SPECS``.

Uso: ``JanelaRelatorios(ctx, chave="caixa_mov").exec()``. Sem integração ao menu.
Filtros adicionais do Tk ficam sempre visíveis. Consulta e CSV usam os mesmos
controladores e conversores, sem recalcular valores na interface.

Fora deste catálogo: vendas_periodo e estoque_atual (telas Qt próprias).
Pendente neste catálogo: a rota especial auditoria_eventos (início/fim ISO,
ação, paginação e retratos). Sua consulta já existe separadamente em
ui_qt.auditoria.JanelaAuditoria; não há exportação dessa rota nesta janela.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLineEdit, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.core.relatorio import para_csv, para_texto
from src.ui_qt.tema import texto
from src.ui_qt.visualizador import JanelaVisualizador


FILTROS = {
    "de": ("Data inicial", "data"), "ate": ("Data final", "data"),
    "hora_ini": ("Hora inicial", "hora"), "hora_fim": ("Hora final", "hora"),
    "cupom_ini": ("Cupom inicial", "int"), "cupom_fim": ("Cupom final", "int"),
    "turno_atual": ("Somente o turno atual (aberto)", "sn"), "turno": ("Turno", "int"),
    "operador_id": ("Operador", "lookup:operadores"),
    "garcom_id": ("Garçom", "lookup:operadores"),
    "vendedor_id": ("Vendedor", "lookup:operadores"),
    "entregador_id": ("Entregador", "lookup:operadores"),
    "cliente_id": ("Cliente", "lookup:clientes"),
    "grupo_id": ("Categoria / setor", "lookup:grupos"),
    "modalidade": ("Modalidade", "escolha:balcao|mesa|comanda|caderneta|entrega"),
    "tipo_caixa": ("Movimento", "escolha:entrada|saida"),
    "tipo_estoque": ("Tipo de movimento", "escolha:compra|entrada|saida|descarte|quebra|oxidacao|devolucao|contagem|inicial|pedido|desc_acabados"),
    "fornecedor_id": ("Fornecedor", "lookup:fornecedores"),
    "plano_id": ("Plano de contas", "lookup:planos_contas"),
    "subplano_id": ("Sub plano", "lookup:subplanos"),
    "por": ("Considerar a data de", "escolha:dt_quitacao|dt_entrada|dt_vencimento"),
    "apenas_resultado": ("Somente contas que afetam o resultado", "sn"),
    "apenas_debitos": ("Somente débitos", "sn"),
    "incluir_previsao": ("Incluir previsões", "sn"),
    "garota": ("Garota (número)", "int"),
    "situacao_comissao": ("Situação da comissão", "escolha:pendente|paga|cancelada"),
    "detalhar": ("Listar cada lançamento", "sn"),
}
PERIODO = ("de", "ate")
PERIODO_TURNO = PERIODO + ("turno", "operador_id")
VENDAS = PERIODO + ("hora_ini", "hora_fim", "cupom_ini", "cupom_fim",
                    "turno_atual", "turno", "operador_id", "modalidade")
VENDAS_CATEGORIA = VENDAS + ("grupo_id",)
VENDAS_MAIS = ("garcom_id", "vendedor_id", "entregador_id", "cliente_id")


@dataclass(frozen=True)
class Spec:
    titulo: str
    modulo: str
    metodo: str
    filtros: tuple[str, ...]
    padrao: str = "hoje"
    mais: tuple[str, ...] = ()
    tipo: str = ""

    def executar(self, ctx, filtros):
        metodo = getattr(ctx.relatorios, self.metodo)
        if self.metodo == "clientes_inativos":
            return metodo(filtros.get("de") or fmt.somar_dias(fmt.hoje(), -30),
                          filtros.get("ate"))
        if not self.filtros:
            return metodo()
        if self.tipo:
            filtros = {**filtros, "tipo": filtros.get(self.tipo)}
        return metodo(filtros)


# Módulos espelham RELATORIOS de ui.app, sem importar sua dependência Tk.
SPECS = {
    "vendas_grupo": Spec("Venda por grupo", "rel_vendas_grupo", "vendas_por_grupo", VENDAS_CATEGORIA, mais=VENDAS_MAIS),
    "mais_vendidos": Spec("Produtos mais vendidos", "rel_vendas_grupo", "mais_vendidos", VENDAS_CATEGORIA, mais=VENDAS_MAIS),
    "informativo": Spec("Informativo de vendas por dia", "rel_informativos", "informativo_dias", PERIODO + ("operador_id",), "mes"),
    "horas": Spec("Vendas por hora", "rel_informativos", "vendas_por_hora", PERIODO + ("hora_ini", "hora_fim"), "mes"),
    "cancelados": Spec("Cancelamentos", "rel_informativos", "cancelados", PERIODO + ("operador_id",), "mes"),
    "caixa_mov": Spec("Entradas e saídas financeiras do caixa", "rel_caixa", "caixa_movimentos", PERIODO_TURNO + ("tipo_caixa",), tipo="tipo_caixa"),
    "fechamentos": Spec("Fechamentos do caixa", "rel_caixa", "fechamentos", PERIODO_TURNO, "mes"),
    "comandas": Spec("Comandas", "rel_comandas", "comandas", VENDAS, mais=VENDAS_MAIS),
    "auditoria_operadores": Spec("Auditoria por operador", "rel_auditoria", "auditoria_operadores", PERIODO, "mes"),
    "garcons": Spec("Garçons", "rel_garcons", "garcons", VENDAS, mais=VENDAS_MAIS),
    "comissao_garotas": Spec("Comissão das garotas", "rel_comissao_garotas", "comissoes_garotas", PERIODO + ("turno", "garota", "situacao_comissao", "detalhar"), "mes"),
    "cmv": Spec("C.M.V. - Custo da mercadoria vendida", "rel_cmv", "cmv", VENDAS_CATEGORIA, mais=VENDAS_MAIS),
    "comissao_produto": Spec("Comissão por produto", "rel_comissoes", "comissoes_produto", PERIODO, "mes"),
    "comissao_venda": Spec("Comissão por venda", "rel_comissoes", "comissoes_venda", PERIODO, "mes"),
    "comissao_cliente": Spec("Vendas por cliente", "rel_comissoes", "comissoes_cliente", PERIODO + ("cliente_id",), "mes"),
    "clientes_inativos": Spec("Clientes inativos (sem consumo no período)", "rel_clientes", "clientes_inativos", PERIODO, "vazio"),
    "clientes_resumo": Spec("Entrega e caderneta por cliente", "rel_clientes", "clientes_resumo", PERIODO, "mes"),
    "resultado_financeiro": Spec("Resultado financeiro", "rel_financeiro", "resultado_financeiro", PERIODO + ("por", "plano_id", "subplano_id", "apenas_resultado", "apenas_debitos", "incluir_previsao"), "mes"),
    "extrato_contas": Spec("Extrato de contas", "rel_financeiro", "extrato_contas", PERIODO, "mes"),
    "mov_estoque": Spec("Movimento de estoque", "rel_estoque", "movimento_estoque", PERIODO + ("tipo_estoque", "fornecedor_id"), "mes", tipo="tipo_estoque"),
    "posicao_estoque": Spec("Posição do estoque por período", "rel_estoque", "posicao_estoque_periodo", PERIODO, "mes"),
    "custo_medio": Spec("Preço médio de compra", "rel_informativos", "custo_medio", PERIODO + ("fornecedor_id",), "mes"),
    "form_contagem": Spec("Formulário de contagem", "rel_estoque", "formulario_contagem", (), "vazio"),
    "form_pedidos": Spec("Formulário de pedidos", "rel_estoque", "formulario_pedidos", (), "vazio"),
}


class PainelFiltros(QWidget):
    def __init__(self, ctx, spec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.campos = {}
        formulario = QFormLayout(self)
        for chave in spec.filtros + spec.mais:
            rotulo, tipo = FILTROS[chave]
            if tipo == "sn":
                campo = QCheckBox()
            elif tipo.startswith(("lookup:", "escolha:")):
                campo = QComboBox()
                campo.addItem("", None)
                if tipo.startswith("lookup:"):
                    for identificador, nome in ctx.cadastros.opcoes(tipo.split(":")[1]):
                        campo.addItem(nome, identificador)
                else:
                    for valor in tipo.split(":")[1].split("|"):
                        campo.addItem(valor, valor)
            else:
                campo = QLineEdit()
                if tipo == "data":
                    campo.setPlaceholderText("DD/MM/AAAA ou AAAA-MM-DD; vazio = sem limite")
                elif tipo == "hora":
                    campo.setPlaceholderText("HH:MM")
            campo.setObjectName(chave)
            self.campos[chave] = campo
            formulario.addRow(rotulo, campo)
        self.limpar()

    def limpar(self):
        for campo in self.campos.values():
            if isinstance(campo, QCheckBox):
                campo.setChecked(False)
            elif isinstance(campo, QComboBox):
                campo.setCurrentIndex(0)
            else:
                campo.clear()
        hoje = fmt.hoje()
        if self.spec.padrao != "vazio":
            for chave, valor in (("de", hoje[:8] + "01" if self.spec.padrao == "mes" else hoje),
                                 ("ate", hoje)):
                if chave in self.campos:
                    self.campos[chave].setText(fmt.fmt_data(valor))
        if "por" in self.campos:
            self.campos["por"].setCurrentIndex(self.campos["por"].findData("dt_quitacao"))

    def valores(self):
        saida = {}
        for chave, campo in self.campos.items():
            tipo = FILTROS[chave][1]
            if isinstance(campo, QCheckBox):
                if campo.isChecked():
                    saida[chave] = True
            elif isinstance(campo, QComboBox):
                if campo.currentData() is not None:
                    saida[chave] = campo.currentData()
            elif campo.text().strip():
                bruto = campo.text().strip()
                converter = {"data": fmt.para_data_iso, "hora": fmt.para_hora, "int": int}
                saida[chave] = converter.get(tipo, str)(bruto)
        if saida.get("de") and saida.get("ate") and saida["de"] > saida["ate"]:
            raise ValueError("A data inicial deve ser anterior ou igual à data final.")
        return saida


class JanelaRelatorios(QDialog):
    """Somente leitura; resultados são descartados ao trocar relatório ou filtros."""

    def __init__(self, ctx, parent=None, chave="caixa_mov"):
        super().__init__(parent)
        self.ctx = ctx
        self.chave = chave
        self._exigir_acesso()
        self.rel = None
        self._consulta = None
        self.setWindowTitle("Relatórios • somente leitura • Qt opt-in")
        self.resize(1100, 800)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Relatórios", "titulo"))
        self.selecao = QComboBox()
        for codigo, spec in SPECS.items():
            self.selecao.addItem(spec.titulo, codigo)
        self.selecao.setCurrentIndex(self.selecao.findData(chave))
        layout.addWidget(self.selecao)
        self.area_filtros = QScrollArea()
        self.area_filtros.setWidgetResizable(True)
        layout.addWidget(self.area_filtros, 2)
        barra = QHBoxLayout()
        self.aplicar = QPushButton("Consultar")
        self.aplicar.clicked.connect(self.atualizar)
        self.limpar_botao = QPushButton("Limpar filtros")
        self.limpar_botao.clicked.connect(self.limpar)
        self.csv_botao = QPushButton("Exportar CSV")
        self.csv_botao.clicked.connect(lambda: self.exportar_csv())
        self.visualizar_botao = QPushButton("Pré-visualizar texto")
        self.visualizar_botao.clicked.connect(self.visualizar)
        for botao in (self.aplicar, self.limpar_botao, self.visualizar_botao, self.csv_botao):
            barra.addWidget(botao)
        layout.addLayout(barra)
        self.criterios = texto("", "suave")
        self.criterios.setWordWrap(True)
        layout.addWidget(self.criterios)
        self.grade, self.totais = self._grade(), self._grade()
        layout.addWidget(self.grade, 3)
        layout.addWidget(self.totais, 1)
        self.mensagem = texto("", "aviso")
        self.mensagem.setWordWrap(True)
        layout.addWidget(self.mensagem)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        layout.addWidget(fechar)
        self.selecao.currentIndexChanged.connect(self._selecionar)
        self._selecionar()

    @property
    def spec(self):
        return SPECS[self.chave]

    def _exigir_acesso(self):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre no sistema para consultar relatórios.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        operador = self.ctx.acesso.operador(self.ctx.operador_id)
        self.ctx.acesso.exigir(operador, self.spec.modulo)

    @staticmethod
    def _grade():
        grade = QTableWidget()
        grade.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        grade.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        grade.setAlternatingRowColors(True)
        grade.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        grade.horizontalHeader().setStretchLastSection(True)
        return grade

    def _descartar(self):
        self.rel = None
        self._consulta = None
        for grade in (self.grade, self.totais):
            grade.clear()
            grade.setRowCount(0)
            grade.setColumnCount(0)
        self.criterios.clear()
        self.csv_botao.setEnabled(False)
        self.visualizar_botao.setEnabled(False)

    def _alterado(self, *_):
        self._descartar()
        self.mensagem.setText("Filtros alterados. Consulte novamente.")

    def _falhar(self, erro):
        self._descartar()
        self.mensagem.setText(str(erro))
        return False

    def _selecionar(self, *_):
        self._descartar()
        self.chave = self.selecao.currentData()
        antigo = self.area_filtros.takeWidget()
        if antigo is not None:
            antigo.deleteLater()
        self.painel = None
        try:
            self._exigir_acesso()
            self.painel = PainelFiltros(self.ctx, self.spec)
        except (ErroNegocio, ValueError, KeyError, sqlite3.Error) as erro:
            self._falhar(erro)
            return
        self.area_filtros.setWidget(self.painel)
        for campo in self.painel.campos.values():
            if isinstance(campo, QCheckBox):
                campo.toggled.connect(self._alterado)
            elif isinstance(campo, QComboBox):
                campo.currentIndexChanged.connect(self._alterado)
            else:
                campo.textChanged.connect(self._alterado)
                campo.returnPressed.connect(self.atualizar)
        self.atualizar()

    def limpar(self):
        if self.painel is None:
            self._selecionar()
        else:
            self.painel.limpar()
            self.atualizar()

    @staticmethod
    def _preencher(grade, titulos, linhas, colunas=(), estilos=()):
        grade.setColumnCount(len(titulos))
        grade.setHorizontalHeaderLabels(titulos)
        grade.setRowCount(len(linhas))
        for numero, valores in enumerate(linhas):
            estilo = estilos[numero] if numero < len(estilos) else ""
            for indice, valor in enumerate(valores):
                item = QTableWidgetItem(str(valor))
                item.setData(Qt.ItemDataRole.UserRole, valor)
                if indice < len(colunas):
                    alinhamento = {"d": Qt.AlignmentFlag.AlignRight,
                                   "c": Qt.AlignmentFlag.AlignHCenter}.get(
                                       colunas[indice].alinha, Qt.AlignmentFlag.AlignLeft)
                    item.setTextAlignment(alinhamento | Qt.AlignmentFlag.AlignVCenter)
                if estilo in ("total", "subtotal", "secao"):
                    fonte = item.font()
                    fonte.setBold(True)
                    item.setFont(fonte)
                grade.setItem(numero, indice, item)

    def atualizar(self):
        self._descartar()
        try:
            self._exigir_acesso()
            if self.painel is None:
                self._selecionar()
                return self.rel is not None
            filtros = self.painel.valores()
            rel = self.spec.executar(self.ctx, filtros)
        except (ErroNegocio, ValueError, KeyError, sqlite3.Error) as erro:
            return self._falhar(erro)
        self.rel = rel
        self._consulta = (self.chave, self.ctx.operador_id, filtros)
        self.criterios.setText("\n".join([rel.titulo, *rel.cabecalho, *rel.criterios]))
        self._preencher(self.grade, [c.titulo for c in rel.colunas], rel.linhas,
                        rel.colunas, rel.estilos)
        self._preencher(self.totais, ["Indicador", "Valor"], rel.rodape)
        self.csv_botao.setEnabled(True)
        self.visualizar_botao.setEnabled(True)
        self.mensagem.setText("Nada encontrado para os critérios." if rel.vazio() else "")
        return True

    def _exigir_resultado(self):
        self._exigir_acesso()
        if (self.rel is None or self.painel is None or
                self._consulta != (self.chave, self.ctx.operador_id, self.painel.valores())):
            raise ErroNegocio("Consulte novamente antes de exportar.")

    def exportar_csv(self, caminho=None):
        """Exporta apenas a consulta exibida; revalida acesso após o diálogo nativo."""
        try:
            self._exigir_resultado()
            if not caminho:
                caminho, _ = QFileDialog.getSaveFileName(
                    self, "Exportar relatório", self.chave + ".csv", "CSV (*.csv)")
            if not caminho:
                return False
            self._exigir_resultado()
            with Path(caminho).open("w", encoding="utf-8-sig", newline="") as arquivo:
                arquivo.write(para_csv(self.rel))
        except (ErroNegocio, ValueError, KeyError, OSError, sqlite3.Error) as erro:
            return self._falhar(erro)
        self.mensagem.setText("CSV exportado.")
        return True

    def visualizar(self):
        """Abre cópia textual da consulta exibida, sem imprimir automaticamente."""
        try:
            self._exigir_resultado()
            janela = JanelaVisualizador(
                self.ctx, self.rel.titulo, para_texto(self.rel, 100), parent=self,
                modulo=self.spec.modulo, nome=self.chave, tipo="relatorio")
        except (ErroNegocio, ValueError, KeyError, sqlite3.Error) as erro:
            return self._falhar(erro)
        janela.exec()
        return True
