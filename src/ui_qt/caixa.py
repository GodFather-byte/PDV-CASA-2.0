"""Caixa em PySide6 (piloto opt-in). Usa o MESMO fluxo de venda do caixa clássico: tudo passa pelo `CaixaController` e pelo
`TurnoController` do contexto; esta tela só lê o que o operador digita, confirma e mostra o resultado.

O que já funciona aqui: abertura do turno (fundo de caixa), venda de balcão, chamar mesa ou comanda (e retomar as abertas),
lançar produto por código, código de barras, atalho ou nome com quantidade, cancelar item, receber pagamentos (troco e
contra-vale), fechar a venda (cupom), cancelar a venda e trocar o turno. Cancelamentos pedem a senha do supervisor quando
a configuração exige, como no caixa clássico.

Comissão das garotas (código 50): lançada na própria linha de entrada (`comissao_na_linha`, padrão) ou pela janela, paga
(acerto com shows, vale e Pix) e cancelada como no caixa clássico; as telas ficam em `src/ui_qt/comissao.py`. A saída sem
consumo (código 1002) libera a comanda vazia e imprime o ticket.

Adega: balcão sem painel de mesas quando desligadas, quantidade antes do código (6*código), cadastro rápido do leitor,
escolha natural/gelada e cascos. Atacado e agrupamento ficam exclusivamente no controlador.
Cascos são itens separados: ao cancelar uma bebida, confira também o casco (e vice-versa).
As operações complementares usam os mesmos controladores e periféricos do Tk, sem abrir janelas Tk.
"""
from __future__ import annotations

import re
import math
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from src.core import formatacao as fmt
from src.controllers.produto_controller import ProdutoController
from src.core.erros import ErroNegocio
from src.core.identidade_visual import preview_logotipo
from src.core.posicao import exemplos, parece_posicao, rotulo_do_campo
from src.core.posicao import nome as nome_posicao
from src.hardware.impressora_termica import ErroImpressao
from src.hardware.dispositivos import DispositivoIndisponivel
from src.ui.caixa_pagamento import LIMITE_TROCO_CENT, ler_valor_pagamento
from src.ui_qt import comissao

PAGINA_SEM_OPERADOR, PAGINA_ABERTURA, PAGINA_VENDA, PAGINA_FECHAMENTO = range(4)
TENTATIVAS_SUPERVISOR = 3
VERDE, AMBAR, VERMELHO = "#1f7a3d", "#a15c00", "#b32020"
COR_COMISSAO, COR_COMISSAO_PAGA = "#fff1d6", "#e8f3ea"      # fundo das linhas de comissão marcada na comanda da garota
QTD_ANTES_DO_CODIGO = re.compile(r"(\d+(?:[.,]\d+)?)\s*\*\s*(\S.*)")

ESTILO = """
QWidget#fundo { background: #f4f5f7; }
QFrame#cartao { background: #ffffff; border: 1px solid #d5d9e0; border-radius: 6px; }
QLabel#titulo { font-size: 16pt; font-weight: bold; color: #1d2733; }
QLabel#total { font-size: 28pt; font-weight: bold; color: #1d2733; }
QLabel#troco { font-size: 16pt; font-weight: bold; color: #1f5fb3; }
QLabel#mudo { color: #5b6573; }
QLabel#alerta { color: #a15c00; font-weight: bold; }
QLabel#status { padding: 4px; }
QPushButton { padding: 6px 12px; }
QPushButton#primario { background: #1f7a3d; color: white; font-weight: bold; border-radius: 4px; padding: 8px 14px; }
QPushButton#perigo { background: #b32020; color: white; border-radius: 4px; padding: 6px 12px; }
QPushButton:disabled { background: #c9ced6; color: #6b7480; }
"""


def _fmt_qtd(q) -> str:
    """Quantidade com até 4 casas, sem zeros sobrando: 1 -> '1', 0.5 -> '0,5', 1.2345 -> '1,2345'."""
    texto = fmt.fmt_qtd(q, fmt.CASAS_QTD)
    return texto.rstrip("0").rstrip(",") if "," in texto else texto


def ler_dinheiro(texto: str, permitir_zero: bool = False) -> int:
    """Valor digitado -> centavos, com as mesmas proteções do pagamento do caixa clássico (sem letras, sinal, 1e5...).
    Com `permitir_zero`, vazio ou zero valem 0 (fundo de caixa ou gaveta vazia)."""
    s = (texto or "").strip()
    if permitir_zero and (not s or re.fullmatch(r"(?:R\$\s*)?0+(?:[.,]0{1,2})?", s)):
        return 0
    return ler_valor_pagamento(s)


def _vivo(widget) -> bool:
    try:
        from shiboken6 import isValid
    except ImportError:          # pragma: no cover - shiboken6 vem junto com o PySide6
        return True
    return isValid(widget)


class Dialogos:
    """Janelas de pergunta do caixa (todas em português). Os testes trocam por uma versão roteirizada."""

    def __init__(self, pai: QWidget):
        self.pai = pai

    def _mensagem(self, icone, titulo: str, texto: str) -> None:
        caixa = QMessageBox(icone, titulo, texto, QMessageBox.NoButton, self.pai)
        caixa.addButton("OK", QMessageBox.AcceptRole)
        caixa.exec()

    def aviso(self, titulo: str, texto: str) -> None:
        self._mensagem(QMessageBox.Warning, titulo, texto)

    def erro(self, titulo: str, texto: str) -> None:
        self._mensagem(QMessageBox.Critical, titulo, texto)

    def confirmar(self, titulo: str, texto: str, padrao_sim: bool = True) -> bool:
        caixa = QMessageBox(QMessageBox.Question, titulo, texto, QMessageBox.NoButton, self.pai)
        sim = caixa.addButton("Sim", QMessageBox.YesRole)
        nao = caixa.addButton("Não", QMessageBox.NoRole)
        caixa.setDefaultButton(sim if padrao_sim else nao)
        caixa.setEscapeButton(nao)
        caixa.exec()
        return caixa.clickedButton() is sim

    def _entrada(self, titulo: str, rotulo: str) -> QInputDialog:
        dlg = QInputDialog(self.pai)
        dlg.setWindowTitle(titulo)
        dlg.setLabelText(rotulo)
        dlg.setOkButtonText("OK")
        dlg.setCancelButtonText("Cancelar")
        return dlg

    def pedir_texto(self, titulo: str, rotulo: str, senha: bool = False, padrao: str = "") -> str | None:
        dlg = self._entrada(titulo, rotulo)
        dlg.setTextValue(padrao)
        dlg.setTextEchoMode(QLineEdit.Password if senha else QLineEdit.Normal)
        return dlg.textValue() if dlg.exec() == QDialog.Accepted else None

    def escolher(self, titulo: str, rotulo: str, opcoes: list[tuple]):
        """`opcoes` = [(valor, texto)]. Devolve o valor escolhido ou None."""
        if not opcoes:
            return None
        dlg = self._entrada(titulo, rotulo)
        dlg.setComboBoxItems([t for _, t in opcoes])
        dlg.setComboBoxEditable(False)
        if dlg.exec() != QDialog.Accepted:
            return None
        return next((v for v, t in opcoes if t == dlg.textValue()), None)


class Documento(QDialog):
    """Mostra um cupom ou fechamento na tela (modo de impressão 'tela' ou impressora fora). Não bloqueia o caixa."""

    def __init__(self, pai: QWidget, titulo: str, texto: str):
        super().__init__(pai)
        self.setWindowTitle(titulo)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        caixa = QVBoxLayout(self)
        self.texto = QPlainTextEdit(texto)
        self.texto.setReadOnly(True)
        self.texto.setFont(QFont("Consolas", 10))
        caixa.addWidget(self.texto)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.close)
        caixa.addWidget(fechar, alignment=Qt.AlignRight)
        self.resize(460, 560)


def _cartao() -> tuple[QFrame, QVBoxLayout]:
    quadro = QFrame()
    quadro.setObjectName("cartao")
    caixa = QVBoxLayout(quadro)
    caixa.setContentsMargins(12, 10, 12, 10)
    return quadro, caixa


def _rotulo(texto: str = "", nome: str | None = None) -> QLabel:
    lbl = QLabel(texto)
    if nome:
        lbl.setObjectName(nome)
    lbl.setWordWrap(True)
    return lbl

class JanelaCaixa(QMainWindow):
    """Caixa Qt. Contrato: `JanelaCaixa(ctx, parent=None).show()` não bloqueia; quem abre guarda a referência.
    Fechar a janela (inclusive na saída da sessão) nunca encerra o turno nem a venda de balcão: ela fica aberta para
    continuar depois. Durante uma gravação o fechamento é recusado (a janela continua visível)."""

    def __init__(self, ctx, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.com_mesas = ctx.banco.cfg_bool("usar_mesas", True)
        self._subgrupo_rapido = None
        self.venda_id: int | None = None
        self.dialogos = Dialogos(self)
        self.documentos: list[QDialog] = []
        self._ocupado = False
        self._fechando_venda = False
        self.modo_comissao = False                 # a linha de entrada está lançando comissão (garota nº + valor), não produto
        self._cancelamento_autorizado = None
        self.comissao_marcada: list[dict] = []     # as comissões da comanda da garota que está na tela
        self.janela_comissoes = None
        self.setWindowTitle(f"Caixa - {self._nome_loja()}")
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setStyleSheet(ESTILO)
        self.resize(1240, 760)
        self._montar()
        self.recarregar_tudo()

    def _nome_loja(self) -> str:
        try:
            return self.ctx.config.nome_loja()
        except Exception:  # noqa: BLE001 - o título não pode impedir o caixa de abrir
            return "WillPDV"

    # ================================================================ layout
    def _montar(self) -> None:
        fundo = QWidget()
        fundo.setObjectName("fundo")
        geral = QVBoxLayout(fundo)
        self.lbl_cabecalho = _rotulo("", "titulo")
        cabecalho = QHBoxLayout()
        self.logo_loja = QLabel()
        dados_logo = preview_logotipo(self.ctx.config.loja().get("logotipo"), (64, 48))
        if dados_logo:
            imagem = QPixmap()
            imagem.loadFromData(dados_logo, "PNG")
            self.logo_loja.setPixmap(imagem)
            cabecalho.addWidget(self.logo_loja)
        cabecalho.addWidget(self.lbl_cabecalho, 1)
        geral.addLayout(cabecalho)
        self.paginas = QStackedWidget()
        self.paginas.addWidget(self._pagina_sem_operador())
        self.paginas.addWidget(self._pagina_abertura())
        self.paginas.addWidget(self._pagina_venda())
        self.paginas.addWidget(self._pagina_fechamento())
        geral.addWidget(self.paginas, 1)
        self.lbl_status = _rotulo("", "status")
        geral.addWidget(self.lbl_status)
        self.setCentralWidget(fundo)
        atalho = QShortcut(QKeySequence("F12"), self)
        atalho.activated.connect(self.fechar_venda)
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.activated.connect(self.cancelar_modo_comissao)
        for tecla, acao in (("F4", self.foco_posicao), ("F5", self.caderneta), ("F6", self.entrega),
                            ("F8", self.pre_conta), ("F9", self.repique),
                            ("F10", self.transferir_mesa), ("F2", self.balanca), ("F11", self.gaveta)):
            atalho = QShortcut(QKeySequence(tecla), self)
            atalho.activated.connect(acao)

    def _pagina_sem_operador(self) -> QWidget:
        pagina, caixa = _cartao()
        caixa.addWidget(_rotulo("Nenhum operador na sessão. Entre no sistema para usar o caixa.", "titulo"))
        caixa.addStretch(1)
        return pagina

    def _pagina_abertura(self) -> QWidget:
        pagina = QWidget()
        externo = QVBoxLayout(pagina)
        quadro, caixa = _cartao()
        quadro.setMaximumWidth(520)
        caixa.addWidget(_rotulo("Abertura do turno", "titulo"))
        caixa.addWidget(_rotulo("Não há turno aberto. Informe o número do turno e o dinheiro encontrado na gaveta "
                                "(fundo de caixa) para começar a vender.", "mudo"))
        form = QFormLayout()
        self.spin_turno = QSpinBox()
        self.spin_turno.setRange(1, 9)
        form.addRow("Turno:", self.spin_turno)
        self.ent_fundo = QLineEdit("0,00")
        form.addRow("Valor inicial (R$):", self.ent_fundo)
        caixa.addLayout(form)
        self.btn_abrir_turno = QPushButton("Abrir turno")
        self.btn_abrir_turno.setObjectName("primario")
        self.btn_abrir_turno.clicked.connect(self.abrir_turno)
        self.ent_fundo.returnPressed.connect(self.abrir_turno)
        caixa.addWidget(self.btn_abrir_turno)
        externo.addWidget(quadro, alignment=Qt.AlignHCenter | Qt.AlignTop)
        externo.addStretch(1)
        return pagina

    def _pagina_venda(self) -> QWidget:
        pagina = QWidget()
        grade = QHBoxLayout(pagina)

        esq, c_esq = _cartao()
        self.painel_mesas = esq
        esq.setFixedWidth(230)
        c_esq.addWidget(_rotulo("Mesas e comandas", "titulo"))
        self.lbl_dica_pos = _rotulo("", "mudo")
        c_esq.addWidget(self.lbl_dica_pos)
        linha = QHBoxLayout()
        self.ent_pos = QLineEdit()
        self.ent_pos.setPlaceholderText("Número")
        self.ent_pos.returnPressed.connect(self.chamar_posicao)
        linha.addWidget(self.ent_pos)
        self.btn_chamar = QPushButton("Chamar")
        self.btn_chamar.clicked.connect(self.chamar_posicao)
        linha.addWidget(self.btn_chamar)
        c_esq.addLayout(linha)
        self.btn_balcao = QPushButton("Venda de balcão")
        self.btn_balcao.clicked.connect(self.ir_para_balcao)
        c_esq.addWidget(self.btn_balcao)
        c_esq.addWidget(_rotulo("Abertas (duplo clique para chamar):", "mudo"))
        self.lista_mesas = QListWidget()
        self.lista_mesas.itemActivated.connect(self._mesa_escolhida)
        c_esq.addWidget(self.lista_mesas, 1)
        grade.addWidget(esq)
        if not self.com_mesas:
            esq.hide()
            self.ent_pos.hide()
            self.btn_chamar.hide()
            self.btn_balcao.hide()
            self.lista_mesas.hide()

        centro, c_cen = _cartao()
        self.lbl_venda = _rotulo("Balcão", "titulo")
        c_cen.addWidget(self.lbl_venda)
        self.lbl_aviso_venda = _rotulo("", "alerta")
        self.lbl_aviso_venda.hide()
        c_cen.addWidget(self.lbl_aviso_venda)
        entrada = QGridLayout()
        self.lbl_cod_titulo = QLabel("Código ou nome do produto:")
        entrada.addWidget(self.lbl_cod_titulo, 0, 0)
        self.lbl_qtd_titulo = QLabel("Quantidade:")
        entrada.addWidget(self.lbl_qtd_titulo, 0, 1)
        self.ent_codigo = QLineEdit()
        self.ent_codigo.setPlaceholderText("Código, código de barras, nome ou 6*código")
        self.ent_codigo.returnPressed.connect(self._enter_codigo)
        self.ent_codigo.textEdited.connect(self._esconder_produtos)
        self.ent_codigo.textEdited.connect(self._comissao_nome)
        entrada.addWidget(self.ent_codigo, 1, 0)
        self.ent_qtd = QLineEdit("1")
        self.ent_qtd.setMaximumWidth(110)
        self.ent_qtd.returnPressed.connect(self.lancar_item)
        entrada.addWidget(self.ent_qtd, 1, 1)
        self.btn_lancar = QPushButton("Lançar")
        self.btn_lancar.setObjectName("primario")
        self.btn_lancar.clicked.connect(self.lancar_item)
        entrada.addWidget(self.btn_lancar, 1, 2)
        self.lbl_comissao_nome = _rotulo("", "alerta")    # no modo comissão: quem é a garota do número digitado
        self.lbl_comissao_nome.hide()
        entrada.addWidget(self.lbl_comissao_nome, 2, 0, 1, 3)
        entrada.setColumnStretch(0, 1)
        c_cen.addLayout(entrada)
        self.lista_produtos = QListWidget()
        self.lista_produtos.setMaximumHeight(150)
        self.lista_produtos.itemActivated.connect(lambda _item: self.lancar_item())
        self.lista_produtos.hide()
        c_cen.addWidget(self.lista_produtos)
        self.tabela = QTableWidget(0, 6)
        self.tabela.setHorizontalHeaderLabels(["Código", "Produto", "Un.", "Preço (R$)", "Qtd.", "Total (R$)"])
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.itemActivated.connect(self._ativar_linha)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        c_cen.addWidget(self.tabela, 1)
        botoes = QHBoxLayout()
        self.btn_cancelar_item = QPushButton("Cancelar item")
        self.btn_cancelar_item.clicked.connect(self.cancelar_item)
        botoes.addWidget(self.btn_cancelar_item)
        self.btn_cancelar_venda = QPushButton("Cancelar venda")
        self.btn_cancelar_venda.setObjectName("perigo")
        self.btn_cancelar_venda.clicked.connect(self.cancelar_venda)
        botoes.addWidget(self.btn_cancelar_venda)
        botoes.addStretch(1)
        self.btn_pagar_garota = QPushButton("Pagar a garota")
        self.btn_pagar_garota.clicked.connect(lambda: self.pagar_comissao())
        self.btn_pagar_garota.hide()
        botoes.addWidget(self.btn_pagar_garota)
        self.btn_comissoes = QPushButton("Comissões")
        self.btn_comissoes.clicked.connect(self.abrir_comissoes)
        botoes.addWidget(self.btn_comissoes)
        c_cen.addLayout(botoes)
        self.btn_operacoes = QPushButton("Operações do caixa")
        menu = QMenu(self.btn_operacoes)
        self.acoes = {}
        for chave, titulo, acao in (
                ("desconto", "Desconto", self.desconto), ("servico", "Serviço manual / automático", self.servico),
                ("observacao", "Observação do item", self.observacao_item),
                ("transferir_mesa", "Transferir mesa / comanda (F10)", self.transferir_mesa),
                ("transferir_varias", "Transferir várias mesas / comandas", self.transferir_varias),
                ("transferir_item", "Transferir item", self.transferir_item),
                ("pre_conta", "Pré-conta / emitir entrega (F8)", self.pre_conta),
                ("caderneta", "Caderneta (F5)", self.caderneta), ("entrega", "Entrega (F6)", self.entrega),
                ("troco_entrega", "Liberar troco da entrega", self.liberar_troco),
                ("sangria", "Sangria / suprimento", self.sangria), ("repique", "Repique", self.repique),
                ("gaveta", "Abrir gaveta", self.gaveta), ("balanca", "Capturar peso", self.balanca),
                ("reimpressao", "Reimprimir cupom", self.reimprimir),
                ("consultar_comanda", "Consultar comanda", self.consultar_comanda),
                ("modo_cancelar", "Cancelar linhas (Enter; Esc retorna)", self.iniciar_cancelamento)):
            self.acoes[chave] = menu.addAction(titulo)
            self.acoes[chave].triggered.connect(acao)
        self.btn_operacoes.setMenu(menu)
        if not self.com_mesas:
            for chave in ("servico", "transferir_mesa", "transferir_varias", "transferir_item",
                          "repique", "consultar_comanda"):
                self.acoes[chave].setVisible(False)
            self.acoes["pre_conta"].setText("Emitir pedido de entrega (F8)")
        c_cen.addWidget(self.btn_operacoes)
        grade.addWidget(centro, 1)

        dir_, c_dir = _cartao()
        dir_.setFixedWidth(320)
        self.lbl_total_rotulo = _rotulo("Total (R$)", "mudo")
        c_dir.addWidget(self.lbl_total_rotulo)
        self.lbl_total = _rotulo("0,00", "total")
        c_dir.addWidget(self.lbl_total)
        self.lbl_detalhe = _rotulo("", "mudo")
        c_dir.addWidget(self.lbl_detalhe)
        self.lbl_falta_rotulo = _rotulo("Troco (R$)", "mudo")
        c_dir.addWidget(self.lbl_falta_rotulo)
        self.lbl_troco = _rotulo("0,00", "troco")
        c_dir.addWidget(self.lbl_troco)
        form = QFormLayout()
        self.cmb_forma = QComboBox()
        self.cmb_forma.currentIndexChanged.connect(lambda _i: self._sugerir_valor())
        form.addRow("Forma:", self.cmb_forma)
        self.ent_valor = QLineEdit()
        self.ent_valor.returnPressed.connect(self.receber)
        form.addRow("Valor (R$):", self.ent_valor)
        c_dir.addLayout(form)
        self.btn_receber = QPushButton("Receber")
        self.btn_receber.clicked.connect(self.receber)
        c_dir.addWidget(self.btn_receber)
        self.lista_pagamentos = QListWidget()
        self.lista_pagamentos.setMaximumHeight(130)
        c_dir.addWidget(self.lista_pagamentos)
        self.btn_remover_pag = QPushButton("Remover pagamento")
        self.btn_remover_pag.clicked.connect(self.remover_pagamento)
        c_dir.addWidget(self.btn_remover_pag)
        self.lbl_msg_pag = _rotulo("", "mudo")
        c_dir.addWidget(self.lbl_msg_pag)
        c_dir.addStretch(1)
        self.btn_fechar_venda = QPushButton("Fechar venda (F12)")
        self.btn_fechar_venda.setObjectName("primario")
        self.btn_fechar_venda.clicked.connect(self.fechar_venda)
        c_dir.addWidget(self.btn_fechar_venda)
        self.btn_trocar_turno = QPushButton("Trocar turno")
        self.btn_trocar_turno.clicked.connect(self.ir_para_fechamento)
        c_dir.addWidget(self.btn_trocar_turno)
        grade.addWidget(dir_)
        return pagina
    def _pagina_fechamento(self) -> QWidget:
        pagina = QWidget()
        externo = QVBoxLayout(pagina)
        quadro, caixa = _cartao()
        quadro.setMaximumWidth(620)
        caixa.addWidget(_rotulo("Troca de turno", "titulo"))
        caixa.addWidget(_rotulo("Confira primeiro o que foi lançado em cartão e Pix com o fechamento da maquininha. "
                                "Depois conte a gaveta e digite o valor encontrado (o esperado não é mostrado).", "mudo"))
        self.txt_maquininha = QPlainTextEdit()
        self.txt_maquininha.setReadOnly(True)
        self.txt_maquininha.setMaximumHeight(140)
        caixa.addWidget(self.txt_maquininha)
        self.lbl_avisos_turno = _rotulo("", "alerta")
        caixa.addWidget(self.lbl_avisos_turno)
        form = QFormLayout()
        self.ent_gaveta = QLineEdit()
        self.ent_gaveta.setPlaceholderText("0,00")
        form.addRow("Valor na gaveta (+ cheques/tickets) R$:", self.ent_gaveta)
        caixa.addLayout(form)
        botoes = QHBoxLayout()
        self.btn_voltar_venda = QPushButton("Voltar ao caixa")
        self.btn_voltar_venda.clicked.connect(self.voltar_para_venda)
        botoes.addWidget(self.btn_voltar_venda)
        botoes.addStretch(1)
        self.btn_confirmar_turno = QPushButton("Encerrar turno")
        self.btn_confirmar_turno.setObjectName("perigo")
        self.btn_confirmar_turno.clicked.connect(self.fechar_turno)
        botoes.addWidget(self.btn_confirmar_turno)
        caixa.addLayout(botoes)
        externo.addWidget(quadro, alignment=Qt.AlignHCenter | Qt.AlignTop)
        externo.addStretch(1)
        return pagina

    # ========================================================= utilidades
    def avisar(self, texto: str, cor: str = VERDE) -> None:
        self.lbl_status.setText(texto)
        self.lbl_status.setStyleSheet(f"color: {cor}; font-weight: bold;" if texto else "")

    def _executar(self, funcao, *args, **kwargs):
        """Como `tema.tratar` do caixa clássico: erro de negócio vira mensagem; erro inesperado é registrado e avisado,
        sem derrubar a tela. Devolve (ok, resultado). Enquanto grava, a janela recusa ser fechada."""
        anterior, self._ocupado = self._ocupado, True
        try:
            return True, funcao(*args, **kwargs)
        except ErroNegocio as e:
            self.dialogos.erro("Caixa", str(e))
        except Exception as e:  # noqa: BLE001 - nunca deixar o caixa morrer
            from src.core import registro
            registro.registrar_excecao(*sys.exc_info(), origem=getattr(funcao, "__name__", "caixa_qt"))
            self.dialogos.erro("Erro", f"Erro inesperado: {e}\nO movimento já gravado foi preservado.")
        finally:
            self._ocupado = anterior
        return False, None

    def _autorizar(self, modulo: str, chave_config: str, motivo: str) -> bool:
        """A mesma regra do caixa clássico: se a configuração exige e o operador não tem nível, pede a senha de um
        supervisor (3 tentativas; senhas erradas demais bloqueiam pelo AcessoController)."""
        if not self.ctx.acesso.precisa_senha(self.ctx.operador, modulo, chave_config):
            return True
        return self._pedir_supervisor(modulo, motivo)

    def _pedir_supervisor(self, modulo: str, motivo: str) -> bool:
        """Autorização obrigatória, inclusive quando as senhas opcionais do caixa estão desligadas."""
        for _ in range(TENTATIVAS_SUPERVISOR):
            senha = self.dialogos.pedir_texto("Autorização", f"{motivo}\nDigite uma senha válida:", senha=True)
            if senha is None:
                return False
            try:
                sup = self.ctx.acesso.validar_supervisor(senha, modulo)
            except ErroNegocio as e:
                self.dialogos.erro("Autorização", str(e))
                return False
            if sup is not None:
                return True
            self.dialogos.erro("Autorização", "Senha inválida ou sem permissão para esta operação.")
        return False

    def _pedir_motivo(self, titulo: str, rotulo: str, padrao: str) -> str | None:
        """Motivo do cancelamento: só é perguntado quando a configuração exige (e então não pode ficar vazio)."""
        if not self.ctx.banco.cfg_bool("exigir_motivo_cancelamento", False):
            return padrao
        while True:
            texto = self.dialogos.pedir_texto(titulo, rotulo)
            if texto is None:
                return None
            if texto.strip():
                return texto.strip()
            self.dialogos.aviso(titulo, "Informe o motivo.")

    def venda(self) -> dict | None:
        if self.venda_id is None:
            return None
        v = self.ctx.banco.um("SELECT * FROM vendas WHERE id = ?", (self.venda_id,))
        if v is None or v["status"] not in ("aberta", "conta_enviada"):
            self.venda_id = None
            return None
        return dict(v)

    def _turno(self) -> dict | None:
        return self.ctx.turnos.atual()

    def _pronto(self) -> bool:
        """Só vende com operador na sessão, turno aberto e a tela de venda à mostra."""
        if self.ctx.operador is None:
            self.recarregar_tudo()
            return False
        if self._turno() is None:
            self.dialogos.aviso("Caixa", "Não há turno aberto. Abra o turno antes de vender.")
            self.recarregar_tudo()
            return False
        return self.paginas.currentIndex() == PAGINA_VENDA

    # ========================================================= recarregar
    def recarregar_tudo(self) -> None:
        if self.ctx.operador is None:
            self.lbl_cabecalho.setText("Caixa")
            self.paginas.setCurrentIndex(PAGINA_SEM_OPERADOR)
            return
        turno = self._turno()
        if turno is None:
            self.venda_id = None
            self.lbl_cabecalho.setText(f"Caixa  ·  {self.ctx.operador.nome.upper()}  ·  sem turno aberto")
            max_turnos = max(self.ctx.banco.cfg_int("num_turnos", 3), 1)
            self.spin_turno.setRange(1, max(max_turnos, 9))
            self.spin_turno.setValue(self.ctx.turnos.numero_sugerido())
            self.ent_fundo.setText("0,00")
            self.paginas.setCurrentIndex(PAGINA_ABERTURA)
            self.ent_fundo.setFocus()
            return
        self.lbl_cabecalho.setText(f"Caixa  ·  TURNO {turno['numero']}  ·  {self.ctx.operador.nome.upper()}")
        if self.venda() is None:
            balcao = self.ctx.caixa.balcao_aberto()       # retoma o balcão interrompido (queda de energia, saída do caixa)
            self.venda_id = balcao["id"] if balcao else None
        if self.paginas.currentIndex() != PAGINA_FECHAMENTO:
            self.paginas.setCurrentIndex(PAGINA_VENDA)
        padrao = self.ctx.caixa.padrao_posicao()
        comum, outra = exemplos(padrao)
        self.lbl_dica_pos.setText(f"{rotulo_do_campo(padrao)}. Ex.: {comum} ou {outra}; 0 volta ao balcão.")
        self._carregar_formas()
        self.recarregar()

    def _carregar_formas(self) -> None:
        atual = self.cmb_forma.currentData()
        self.cmb_forma.blockSignals(True)
        self.cmb_forma.clear()
        for f in self.ctx.caixa.formas_pagamento():
            self.cmb_forma.addItem(f["tipo"], int(f["id"]))
        i = self.cmb_forma.findData(atual) if atual is not None else -1
        self.cmb_forma.setCurrentIndex(i if i >= 0 else 0)
        self.cmb_forma.blockSignals(False)
    def recarregar(self) -> None:
        """Atualiza a venda da tela (itens, total, pagamentos) e a lista de mesas e comandas abertas."""
        v = self.venda()
        if not self._em_cancelamento():
            self._cancelamento_autorizado = None
        caixa = self.ctx.caixa
        self.tabela.setRowCount(0)
        itens = caixa.itens(v["id"]) if v else []
        for it in itens:
            linha = self.tabela.rowCount()
            self.tabela.insertRow(linha)
            nome = it["nome"] + (f"  [{' / '.join(it['partes_nomes'])}]" if it["partes_nomes"] else "")
            detalhe_preco = ""
            if self.ctx.banco.cfg("perfil_operacao") == "adega":
                explicacao = ProdutoController.explicacao_preco_adega(it, v["modalidade"])
                if explicacao["rotulo"]:
                    nome += f"  [{explicacao['rotulo']}]"
                detalhe_preco = explicacao["detalhe"]
                if detalhe_preco:
                    nome += f" — {detalhe_preco}"
            if it["observacao"]:
                nome += f" — {it['observacao']}"
            valores = [it["codigo"], nome, it["unidade"], fmt.fmt_num(it["preco_unit_cent"]), _fmt_qtd(it["quantidade"]),
                       fmt.fmt_num(it["total_cent"])]
            for col, texto in enumerate(valores):
                celula = QTableWidgetItem(str(texto))
                if detalhe_preco:
                    celula.setToolTip(detalhe_preco)
                celula.setData(Qt.UserRole, int(it["id"]))
                if col >= 3:
                    celula.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabela.setItem(linha, col, celula)
        self.comissao_marcada = self._comissoes_da_comanda(v)
        codigo = self.ctx.comissoes.codigo() or "COM"
        for c in self.comissao_marcada:            # a comissão não é item da venda: a linha leva "c<id>" para não confundir
            linha = self.tabela.rowCount()
            self.tabela.insertRow(linha)
            paga = c["status"] == "paga"
            valores = [codigo, "COMISSÃO (paga)" if paga else "COMISSÃO (a pagar)", "", fmt.fmt_num(c["valor_cent"]), "1",
                       fmt.fmt_num(c["valor_cent"])]
            for col, texto in enumerate(valores):
                celula = QTableWidgetItem(str(texto))
                celula.setData(Qt.UserRole, f"c{c['id']}")
                celula.setBackground(QColor(COR_COMISSAO_PAGA if paga else COR_COMISSAO))
                if col >= 3:
                    celula.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabela.setItem(linha, col, celula)
        if itens or self.comissao_marcada:
            self.tabela.scrollToBottom()
        total = v["total_cent"] if v else 0
        pags = caixa.pagamentos(v["id"]) if v else []
        recebido = sum(p["valor_cent"] for p in pags)
        if v is None or v["modalidade"] == "balcao":
            self.lbl_venda.setText("Balcão" + ("" if v else "  ·  nova venda"))
        elif v["modalidade"] in ("caderneta", "entrega"):
            cliente = self.ctx.caderneta.obter(v["cliente_id"])
            self.lbl_venda.setText(f"{'Caderneta' if v['modalidade'] == 'caderneta' else 'Entrega ' + str(v['posicao'])}"
                                   f" · {cliente['nome'] if cliente else 'Cliente indisponível'} · {v['status']}")
        else:
            situacao = "Conta enviada" if v["status"] == "conta_enviada" else "Aberta"
            self.lbl_venda.setText(f"{caixa.rotular_posicao(v['comanda'], v['posicao'])}  ·  "
                                   f"{nome_posicao(v['comanda'], v['posicao'])}  ·  {situacao}")
        self.lbl_total.setText(fmt.fmt_num(total))
        self.lbl_total_rotulo.setText("Total (R$)")
        self.lbl_detalhe.setText(self._detalhe_total(v))
        self.lista_pagamentos.clear()
        for p in pags:
            item = QListWidgetItem(f"{p['tipo']}: {fmt.fmt_brl(p['valor_cent'])}")
            item.setData(Qt.UserRole, int(p["id"]))
            self.lista_pagamentos.addItem(item)
        if recebido:
            falta = max(total - recebido, 0)
            self.lbl_falta_rotulo.setText("Falta receber (R$)" if falta else "Troco (R$)")
            self.lbl_troco.setText(fmt.fmt_num(falta if falta else recebido - total))
            self.lbl_msg_pag.setText(f"Recebido: {fmt.fmt_brl(recebido)}")
        else:
            self.lbl_falta_rotulo.setText("Troco (R$)")
            self.lbl_troco.setText("0,00")
            self.lbl_msg_pag.setText("")
        if v and v["modalidade"] == "caderneta":
            cliente = self.ctx.caderneta.obter(v["cliente_id"])
            self.lbl_msg_pag.setText(f"Saldo do cliente: {fmt.fmt_brl(cliente['saldo_cent'])}\n"
                                     + ("Venda a prazo: feche para lançar o débito." if itens else
                                        f"Recebido para crédito: {fmt.fmt_brl(recebido)}"))
            if not itens:
                info = caixa.info_credito(v["id"])
                self.lbl_total_rotulo.setText("Recebido para crédito (R$)")
                self.lbl_total.setText(fmt.fmt_num(recebido))
                self.lbl_falta_rotulo.setText("Excedente a decidir (R$)")
                self.lbl_troco.setText(fmt.fmt_num(info["excedente"]))
        self._aviso_comissao(v)
        tem_itens = bool(itens)
        pode_pagar_garota = bool(v) and self._comissao_na_linha() and (
            self._a_pagar_na_comanda() or (not tem_itens and self._acerto_so_de_shows(v)))
        self.btn_pagar_garota.setVisible(pode_pagar_garota)
        self.btn_cancelar_item.setEnabled(tem_itens or self._a_pagar_na_comanda())
        self.btn_cancelar_venda.setEnabled(v is not None)
        caderneta = bool(v and v["modalidade"] == "caderneta")
        self.btn_receber.setEnabled(not caderneta if tem_itens else caderneta)
        self.btn_remover_pag.setEnabled(bool(pags))
        self.btn_fechar_venda.setEnabled(tem_itens or caderneta)
        self._sugerir_valor()
        self.carregar_mesas()

    def _detalhe_total(self, v: dict | None) -> str:
        if not v:
            return ""
        partes = []
        if v["desconto_cent"]:
            partes.append(f"Desconto: - {fmt.fmt_brl(v['desconto_cent'])}")
        if v["servico_cent"]:
            partes.append(f"Serviço: {fmt.fmt_brl(v['servico_cent'])}")
        if v["taxa_cent"]:
            partes.append(f"{'Compl. consumação' if v['comanda'] else 'Taxa de entrega'}: {fmt.fmt_brl(v['taxa_cent'])}")
        if v["acrescimo_cent"]:
            partes.append(f"Taxa do crédito: {fmt.fmt_brl(v['acrescimo_cent'])}")
        return "\n".join(partes)

    def _comissoes_da_comanda(self, v: dict | None) -> list[dict]:
        """As comissões marcadas na comanda da garota (pendentes de qualquer turno e as pagas neste), como no caixa clássico."""
        if not (v and v["modalidade"] == "mesa" and v["comanda"]):
            return []
        turno = self._turno()
        try:
            return self.ctx.comissoes.marcadas(v["posicao"], turno["id"] if turno else None)
        except (ErroNegocio, ValueError):
            return []

    def _aviso_comissao(self, v: dict | None) -> None:
        """Comanda de garota com comissão marcada: quanto há a pagar, o que já foi pago neste turno e como pagar."""
        texto = ""
        if v and self.comissao_marcada:
            a_pagar = sum(c["valor_cent"] for c in self.comissao_marcada if c["status"] == "pendente")
            paga = sum(c["valor_cent"] for c in self.comissao_marcada if c["status"] == "paga")
            nome = self.ctx.comissoes.nome(v["posicao"])
            texto = f"COMISSÃO MARCADA NA COMANDA {v['posicao']}{' ' + nome if nome else ''}     A pagar: {fmt.fmt_brl(a_pagar)}"
            if paga:
                texto += f"     Paga neste turno: {fmt.fmt_brl(paga)}"
            if a_pagar:
                texto += "     F12 paga a garota" if self._comissao_na_linha() else "     Pague pelo botão Comissões"
        self.lbl_aviso_venda.setText(texto)
        self.lbl_aviso_venda.setVisible(bool(texto))

    def carregar_mesas(self) -> None:
        self.lista_mesas.clear()
        if not self.com_mesas:
            return
        for m in self.ctx.caixa.mesas():
            situacao = " (conta)" if m["status"] == "conta_enviada" else " (parada)" if m["inativa"] else ""
            item = QListWidgetItem(f"{m['rotulo']}  ·  {fmt.fmt_brl(m['total_cent'])}  ·  {m['n_itens']} item(ns){situacao}")
            item.setData(Qt.UserRole, m["rotulo"])
            self.lista_mesas.addItem(item)
            if m["id"] == self.venda_id:
                item.setSelected(True)

    def _sugerir_valor(self) -> None:
        """No campo do valor já vem o que falta (com a taxa da forma escolhida, se ela cobrar)."""
        v = self.venda()
        if v is None:
            self.ent_valor.clear()
            return
        pago = sum(p["valor_cent"] for p in self.ctx.caixa.pagamentos(v["id"]))
        if v["modalidade"] == "caderneta" and not self.ctx.caixa.itens(v["id"]):
            falta = max(self.ctx.caixa.info_credito(v["id"])["divida"] - pago, 0)
            self.ent_valor.setText(fmt.fmt_num(falta) if falta else "")
            return
        falta = max(v["total_cent"] - pago, 0)
        forma = self.cmb_forma.currentData()
        if falta and forma is not None:
            falta += self.ctx.caixa.acrescimo_da_forma(v["id"], int(forma))
        self.ent_valor.setText(fmt.fmt_num(falta) if falta else "")

    # ========================================================= turno
    def abrir_turno(self) -> None:
        if self.ctx.operador is None or self._turno() is not None:
            self.recarregar_tudo()
            return
        try:
            valor = ler_dinheiro(self.ent_fundo.text(), permitir_zero=True)
        except ValueError as e:
            self.dialogos.aviso("Abertura do turno", str(e))
            return
        numero = self.spin_turno.value()
        if not self.dialogos.confirmar("Abertura do turno", f"Abrir o turno {numero} com valor inicial de "
                                                            f"{fmt.fmt_brl(valor)}?"):
            return
        ok, _ = self._executar(self.ctx.turnos.abrir, self.ctx.operador_id, numero, valor)
        if ok:
            self.avisar(f"Turno {numero} aberto com {fmt.fmt_brl(valor)}.")
            self.recarregar_tudo()
            self.ent_codigo.setFocus()
    # ========================================================= itens
    def _pode_operar(self) -> bool:
        return not self._ocupado and not self._fechando_venda and self._pronto()

    def _pedir_convertido(self, titulo, rotulo, converter, padrao=""):
        while True:
            texto = self.dialogos.pedir_texto(titulo, rotulo, padrao=padrao)
            if texto is None:
                return None
            try:
                return converter(texto)
            except ValueError as e:
                self.dialogos.aviso(titulo, str(e))

    def _partes(self, produto: dict) -> list[int] | None:
        def numero(texto):
            if not texto.strip().isdigit() or not 1 <= int(texto) <= produto["partes"]:
                raise ValueError(f"Informe de 1 a {produto['partes']} partes.")
            return int(texto)
        n = self._pedir_convertido(produto["nome"], "Dividir em quantas partes? (1 = sem divisão)", numero, "2")
        if n is None:
            return None
        if n == 1:
            return []
        candidatos = [p for p in self.ctx.cadastros.listar("produtos", apenas_ativos=True)
                      if (p["compoe"] and p["id"] != produto["id"] if produto["composto"] else p["montagem"])]
        if not candidatos:
            self.dialogos.aviso("Montagem", "Não há produtos cadastrados para montar esta divisão.")
            return None
        partes = []
        for i in range(n):
            pid = self.dialogos.escolher(produto["nome"], f"Parte {i + 1} de {n}:",
                                         [(p["id"], p["nome"]) for p in candidatos])
            if pid is None:
                return None
            partes.append(pid)
        return partes

    def observacao_item(self) -> None:
        if not self._pode_operar():
            return
        sel = self._item_selecionado()
        if sel is None:
            return
        item_id, _ = sel
        if not self.ctx.banco.valor("SELECT usa_observacao FROM produtos WHERE id = "
                                    "(SELECT produto_id FROM itens_venda WHERE id = ?)", (item_id,)):
            self.dialogos.aviso("Observação", "Este produto não permite observações (habilite no cadastro).")
            return
        obs = self.ctx.cadastros.listar("observacoes")
        texto = (self.dialogos.escolher("Observação", "Escolha a observação:",
                                        [(r["texto"], f"{r['codigo']} - {r['texto']}") for r in obs]) if obs else
                 self.dialogos.pedir_texto("Observação", "Não há observações cadastradas. Digite a observação do item:"))
        if texto:
            ok, _ = self._executar(self.ctx.caixa.definir_observacao, item_id, texto)
            if ok:
                self._enviar_remoto([item_id])
                self.recarregar()

    def desconto(self) -> None:
        if not self._pode_operar():
            return
        v = self.venda()
        if not v or not self.ctx.caixa.itens(v["id"]) or not self.ctx.banco.cfg_bool("usar_desconto", False):
            self.dialogos.aviso("Desconto", "O desconto está desligado ou a venda não tem itens.")
            return
        if not self._autorizar("caixa_desconto", "exigir_senha_desconto", "Desconto exige autorização:"):
            return
        modo = self.dialogos.escolher("Desconto", "Informar em:", [("valor", "Valor (R$)"), ("pct", "Percentual (%)")])
        if modo is None:
            return
        if modo == "pct":
            def percentual(texto):
                s = texto.strip().replace(",", ".")
                if not re.fullmatch(r"\d+(?:\.\d+)?", s) or not 0 <= float(s) <= 100:
                    raise ValueError("Informe um percentual de 0 a 100.")
                return float(s)
            valor = self._pedir_convertido("Desconto", "Percentual (0 a 100):", percentual)
        else:
            valor = self._pedir_convertido("Desconto", "Valor (R$; 0 retira):",
                                           lambda t: ler_dinheiro(t, permitir_zero=True))
        if valor is not None:
            self._executar(self.ctx.caixa.definir_desconto, v["id"], **{modo if modo == "pct" else "valor_cent": valor})
            self.recarregar()

    def servico(self) -> None:
        if not self._pode_operar():
            return
        v = self.venda()
        if not v or v["modalidade"] != "mesa":
            self.dialogos.aviso("Serviço", "O serviço manual é definido em mesas e comandas.")
            return
        texto = self.dialogos.pedir_texto("Serviço", "Valor do serviço (R$; 0 dispensa; vazio volta ao automático):")
        if texto is None:
            return
        try:
            cent = ler_dinheiro(texto, permitir_zero=True) if texto.strip() else None
        except ValueError as e:
            self.dialogos.aviso("Serviço", str(e))
            return
        self._executar(self.ctx.caixa.definir_servico, v["id"], cent)
        self.recarregar()

    # ========================================================= operações de mesas e comandas
    def transferir_mesa(self) -> None:
        if not self.com_mesas or not self._pode_operar():
            return
        v = self.venda()
        if not v or v["modalidade"] != "mesa":
            self.dialogos.aviso("Transferência", "Chame a mesa ou comanda que será transferida.")
            return
        destino = self._pedir_posicao("Transferência", "Mesa ou comanda de destino:")
        if destino is not None:
            ok, vid = self._executar(self.ctx.caixa.transferir_mesa, (bool(v["comanda"]), v["posicao"]), destino)
            if ok:
                self._limpar_entrada()
                self._cancelamento_autorizado = None
                self.venda_id = vid
                self.recarregar()

    def transferir_varias(self) -> None:
        if not self._pode_operar():
            return
        destino = self._pedir_posicao("Transferir várias", "Mesa ou comanda de destino:")
        if destino is None:
            return
        def origens(texto):
            return [self.ctx.caixa.ler_posicao(x.strip()) for x in texto.split(",") if x.strip()]
        fontes = self._pedir_convertido("Transferir várias", "Origens separadas por vírgula:", origens)
        if fontes is not None:
            ok, _ = self._executar(self.ctx.caixa.transferir_varias, fontes, destino)
            if ok:
                self._cancelamento_autorizado = None
                self.recarregar()

    def transferir_item(self) -> None:
        if not self._pode_operar():
            return
        sel, v = self._item_selecionado(), self.venda()
        if not sel or not v or v["modalidade"] != "mesa":
            return
        item_id = sel[0]
        item = next((it for it in self.ctx.caixa.itens(v["id"]) if it["id"] == item_id), None)
        if item is None:
            return
        destino = self._pedir_posicao("Transferir item", "Mesa ou comanda de destino:")
        if destino is None:
            return
        qtd = self._pedir_convertido("Transferir item", "Quantidade a transferir:", fmt.para_qtd, _fmt_qtd(item["quantidade"]))
        if qtd is not None:
            self._executar(self.ctx.caixa.transferir_item, item_id, destino, qtd)
            self.recarregar()

    def _documento_operacao(self, titulo, preparar, nome, tipo, **kwargs) -> None:
        """A gravação já ocorreu: falhas na preparação/impressão não autorizam repetir a operação."""
        ok, texto = self._executar(preparar)
        if ok:
            self._executar(self._emitir, titulo, texto, nome, tipo=tipo, **kwargs)

    def pre_conta(self) -> None:
        if not self._pode_operar():
            return
        v = self.venda()
        if v and v["modalidade"] == "entrega":
            return self.emitir_pedido_entrega()
        if not v or v["modalidade"] != "mesa":
            self.dialogos.aviso("Pré-conta", "A pré-conta é enviada às mesas e comandas. Chame uma delas."
                                if self.com_mesas else "No balcão não há pré-conta. Receba e feche a venda (F12).")
            return
        ok, _ = self._executar(self.ctx.caixa.enviar_conta, v["id"])
        if ok:
            self.venda_id = None
            self._limpar_entrada()
            self.recarregar()
            self._documento_operacao("Pré-conta", lambda: self.ctx.impressao.pre_conta(v["id"]),
                                      f"pre_conta_{'comanda' if v['comanda'] else 'mesa'}_{v['posicao']}", "pre_conta")

    def consultar_comanda(self) -> None:
        if not self._pode_operar():
            return
        pos = self._pedir_posicao("Consulta de comanda", "Comanda ou mesa a consultar:")
        if pos is None:
            return
        ok, s = self._executar(self.ctx.caixa.situacao_posicao, *pos)
        if not ok:
            return
        nome, quando = nome_posicao(*pos), fmt.fmt_datahora(s.get("quando"))[:16]
        situacao = s["situacao"]
        if situacao == "paga":
            texto = f"{nome}: PAGA\nCupom {s['cupom']} - {fmt.fmt_brl(s['total_cent'])}\nem {quando}"
        elif situacao == "aberta":
            texto = (f"{nome}: ABERTA - A PAGAR {fmt.fmt_brl(s['total_cent'])}\n{s['itens']} item(ns), desde {quando}"
                     + ("\nA conta já foi enviada ao cliente." if s["conta_enviada"] else ""))
        elif situacao == "vazia":
            texto = f"{nome}: aberta, sem nenhum consumo."
        elif situacao == "cancelada":
            texto = f"{nome}: a última venda foi CANCELADA ({fmt.fmt_brl(s['total_cent'])}) em {quando}."
        else:
            texto = f"{nome}: nenhum registro."
        a_pagar = self.ctx.comissoes.pendente(pos[1]) if pos[0] else 0
        if a_pagar:
            texto += f"\n\nComissão da garota {pos[1]} a pagar: {fmt.fmt_brl(a_pagar)}."
        self._mostrar("Consulta de comanda", texto)

    # ========================================================= caderneta e entrega
    def _exigir_venda_vazia(self) -> bool:
        v = self.venda()
        if v and (self.ctx.caixa.itens(v["id"]) or self.ctx.caixa.pagamentos(v["id"])):
            self.dialogos.aviso("Modalidade", "Conclua, pague ou cancele a venda atual antes de trocar de modalidade.")
            return False
        ok, _ = self._executar(self._descartar_se_vazia)
        if ok:
            self.venda_id = None
            self._cancelamento_autorizado = None
            self._limpar_entrada()
        return ok

    def _escolher_cliente(self) -> int | None:
        texto = self.dialogos.pedir_texto("Cliente", "Número, nome ou telefone (vazio lista os ativos):")
        if texto is None:
            return None
        clientes = self.ctx.caderneta.buscar(texto, limite=200)
        cid = self.dialogos.escolher("Cliente", "Escolha o cliente:", [(c["id"],
              f"{c['numero_consulta']} - {c['nome']} · {c['telefone'] or ''} · {c['bairro'] or ''} · "
              f"Saldo {fmt.fmt_brl(c['saldo_cent'])} · Limite {fmt.fmt_brl(c['limite_cent'])}") for c in clientes]
              + [("novo", "Incluir cliente")])
        if cid == "novo":
            from src.ui_qt.cadastros import FormularioCadastro
            ok, cid = self._executar(self._incluir_cliente, FormularioCadastro)
            return cid if ok else None
        if cid is None:
            return None
        c = self.ctx.caderneta.obter(cid)
        if c and self.dialogos.confirmar("Cliente", f"Confirma {c['numero_consulta']} - {c['nome']}?\n"
                                         f"Saldo {fmt.fmt_brl(c['saldo_cent'])}"):
            return cid
        return None

    def _incluir_cliente(self, formulario) -> int | None:
        dlg = formulario(self.ctx, "clientes", parent=self)
        try:
            return dlg.id_ if dlg.exec() == QDialog.Accepted else None
        finally:
            dlg.deleteLater()

    def caderneta(self) -> None:
        if not self._pode_operar() or not self.ctx.banco.cfg_bool("usar_caderneta", False):
            return
        escolha = self.dialogos.escolher("Caderneta", "Operação:", [
            ("venda", "Venda a prazo / receber dívida"), ("consulta", "Consultar / extrato do cliente"),
            ("devedores", "Consultar devedores")])
        if escolha is None:
            return
        if escolha == "venda" and not self._exigir_venda_vazia():
            return
        if escolha == "devedores":
            cid = self.dialogos.escolher("Caderneta", "Devedores:", [
                (c["id"], f"{c['numero_consulta']} - {c['nome']} · {fmt.fmt_brl(c['saldo_cent'])}")
                for c in self.ctx.caderneta.devedores()])
        else:
            cid = self._escolher_cliente()
        if cid is None:
            return
        if escolha == "venda":
            ok, vid = self._executar(self.ctx.caixa.abrir_caderneta, cid)
            if ok:
                self.venda_id = vid
                self.recarregar()
        else:
            self.consultar_cliente(cid)

    def consultar_cliente(self, cliente_id: int) -> None:
        escolha = self.dialogos.escolher("Caderneta", "Consultar:", [
            ("extrato", "Extrato (tela / impressão)"), ("compras", "Últimas compras"), ("lancamentos", "Débitos / créditos e detalhes")])
        cad = self.ctx.caderneta
        if escolha == "extrato":
            self._documento_operacao("Extrato da caderneta", lambda: cad.texto_extrato(cliente_id, self.ctx.impressao.largura()),
                                      "caderneta", "relatorio")
        elif escolha == "compras":
            texto = "\n".join(f"Cupom {p['cupom']} · {fmt.fmt_data(p['data'])} · {p['nome']} · "
                              f"{_fmt_qtd(p['quantidade'])} · {fmt.fmt_brl(p['total_cent'])}" for p in cad.ultimas_compras(cliente_id))
            self._mostrar("Últimas compras", texto or "Nenhuma compra.")
        elif escolha == "lancamentos":
            linhas = cad.lancamentos(cliente_id)
            lid = self.dialogos.escolher("Caderneta", "Débitos e créditos:", [(l["id"],
                f"{l['criado_em']} · Cupom {l['cupom'] or ''} · {l['tipo']} · {fmt.fmt_brl(l['valor_cent'])} · {l['descricao'] or ''}")
                for l in linhas])
            lanc = next((l for l in linhas if l["id"] == lid), None)
            if lanc and lanc["venda_id"]:
                vid = lanc["venda_id"]
                texto = [f"{p['nome']} · {_fmt_qtd(p['quantidade'])} · {fmt.fmt_brl(p['total_cent'])}" for p in cad.produtos_da_venda(vid)]
                texto += [f"Pagamento em {p['tipo']} · {fmt.fmt_brl(p['valor_cent'])}" for p in cad.pagamentos_da_venda(vid)]
                self._mostrar("Detalhes do lançamento", "\n".join(texto) or "Sem produtos / pagamentos.")

    def entrega(self) -> None:
        if not self._pode_operar() or not self.ctx.banco.cfg_bool("usar_delivery", False):
            return
        escolha = self.dialogos.escolher("Delivery", "Operação:", [
            ("novo", "Novo pedido"), ("lista", "Entregas pendentes (receber / entregador / cancelar)")])
        if escolha is None:
            return
        if escolha == "novo":
            if not self._exigir_venda_vazia():
                return
            cid = self._escolher_cliente()
            if cid is None:
                return
            ok, vid = self._executar(self.ctx.entregas.abrir, cid)
            if ok:
                self.venda_id = vid
        elif escolha == "lista":
            pedidos = self.ctx.entregas.pendentes()
            vid = self.dialogos.escolher("Entregas pendentes", "Escolha o pedido:", [(p["id"],
                f"{p['posicao']} · {p['hora_pedido']} · {p['cliente']} · {p['endereco'] or ''} · {p['bairro'] or ''} · "
                f"{p['t_pedido']} min (rota: {p['t_entrega']} min) · {p['entregador'] or 'Sem entregador'} · {fmt.fmt_brl(p['total_cent'])}")
                for p in pedidos])
            if vid is None:
                return
            acao = self.dialogos.escolher("Pedido", "Operação:", [
                ("receber", "Receber / retomar pedido"), ("entregador", "Atribuir entregador"), ("cancelar", "Cancelar pedido")])
            if acao == "receber":
                if not self._exigir_venda_vazia():
                    return
                self.venda_id = vid
                self._limpar_entrada()
            elif acao == "entregador":
                eid = self._escolher_entregador()
                if eid is not None:
                    self._executar(self.ctx.entregas.atribuir_entregador, vid, eid)
            elif acao == "cancelar" and self._autorizar(
                    "caixa_cancelamento", "exigir_senha_cancelamento", "Cancelar pedido exige autorização:"):
                if self.dialogos.confirmar("Cancelar pedido", "Cancelar este pedido de entrega?", padrao_sim=False):
                    motivo = self._pedir_motivo("Cancelar pedido", "Motivo:", "pedido de entrega cancelado")
                    if motivo is not None:
                        self._executar(self.ctx.caixa.cancelar_venda, vid, motivo)
        self.recarregar()

    def _escolher_entregador(self, opcional=False):
        opcoes = [(r["id"], r["nome"]) for r in self.ctx.cadastros.listar("operadores", apenas_ativos=True) if r["entregador"]]
        if not opcoes and not opcional:
            self.dialogos.aviso("Entregador", "Nenhum entregador cadastrado. Marque 'É entregador' no cadastro de operadores.")
            return None
        return self.dialogos.escolher("Entregador", "Quem leva o pedido?", ([("manter", "Manter entregador / sem entregador")] if opcional else []) + opcoes)

    def liberar_troco(self) -> None:
        if not self._pode_operar():
            return
        v = self.venda()
        if not v or v["modalidade"] != "entrega":
            return
        cent = self._pedir_convertido("Entrega", f"Total {fmt.fmt_brl(v['total_cent'])}. Cliente vai pagar com (R$):",
                                      lambda t: ler_dinheiro(t, permitir_zero=True), fmt.fmt_num(v["troco_para_cent"]))
        if cent is None:
            return
        eid = self._escolher_entregador(opcional=True)
        if eid is None:
            return
        mensagem = self.dialogos.pedir_texto("Entrega", "Mensagem para o pedido:", padrao=v["mensagem"] or "")
        if mensagem is None:
            return
        ok, troco = self._executar(self.ctx.entregas.definir_dados, v["id"], cent, None if eid == "manter" else eid, mensagem)
        if ok:
            self.avisar(f"Dados gravados. Troco a levar: {fmt.fmt_brl(troco)}.")
            self.recarregar()

    def emitir_pedido_entrega(self) -> None:
        if not self._pode_operar():
            return
        v = self.venda()
        if not v or v["modalidade"] != "entrega":
            return
        ok, _ = self._executar(self.ctx.entregas.emitir_pedido, v["id"])
        if ok:
            self.venda_id = None
            self._limpar_entrada()
            self.recarregar()
            self._documento_operacao("Pedido de entrega", lambda: self.ctx.impressao.pedido_entrega(v["id"]),
                                      f"entrega_{v['posicao']}", "entrega")

    # ========================================================= dinheiro e periféricos
    def sangria(self) -> None:
        if not self._pode_operar() or not self._autorizar("caixa_sangria", "exigir_senha_sangria", "Sangria exige autorização:"):
            return
        tipo = self.dialogos.escolher("Movimento financeiro", "Tipo:", [("saida", "Saída (sangria)"), ("entrada", "Entrada (suprimento)")])
        if tipo is None:
            return
        cent = self._pedir_convertido("Movimento financeiro", "Valor (R$):", ler_dinheiro)
        if cent is None:
            return
        desc = self.dialogos.pedir_texto("Movimento financeiro", "Descrição / motivo:")
        if desc is None:
            return
        ok, _ = self._executar(self.ctx.turnos.movimentar, self._turno()["id"], self.ctx.operador_id, tipo, cent, desc)
        if ok:
            self.avisar("Movimento financeiro registrado.")
            self._documento_operacao("Comprovante", lambda: self.ctx.impressao.comprovante_movimento(
                tipo, cent, desc, self.ctx.operador.nome), "sangria", "comprovante", abrir_gaveta=True)

    def repique(self) -> None:
        if not self.com_mesas or not self._pode_operar():
            return
        v = self.venda()
        pos = (bool(v["comanda"]), v["posicao"]) if v and v["modalidade"] == "mesa" else self._pedir_posicao(
            "Repique", "Comanda ou mesa que deixou o repique:")
        if pos is None:
            return
        cent = self._pedir_convertido("Repique", "Valor deixado pelo cliente (R$):", ler_dinheiro)
        if cent is not None:
            ok, _ = self._executar(self.ctx.turnos.repique, self._turno()["id"], self.ctx.operador_id, pos[1], cent, pos[0])
            if ok:
                self.avisar(f"Repique de {fmt.fmt_brl(cent)} registrado.")

    def gaveta(self) -> None:
        if not self._pode_operar() or not self._autorizar("caixa_gaveta", "exigir_senha_gaveta", "Abrir a gaveta exige autorização:"):
            return
        def abrir():
            self.ctx.banco.log("gaveta", "abertura manual", self.ctx.operador_id)
            try:
                self.ctx.gaveta().abrir()
            except DispositivoIndisponivel as e:
                self.dialogos.aviso("Gaveta", f"{e}\nA abertura foi registrada; o hardware não confirmou a abertura.")
                return False
            return True
        ok, abriu = self._executar(abrir)
        if ok and abriu:
            self.avisar("Comando de abertura enviado à gaveta.")

    def balanca(self) -> None:
        if not self._pode_operar() or self.modo_comissao:
            return
        p = self._produto_digitado(self.ent_codigo.text().strip())
        if not p:
            return
        try:
            peso = self.ctx.balanca().ler_peso()
        except DispositivoIndisponivel as e:
            peso = self._pedir_convertido("Balança", f"{e}\nPeso manual (kg):", fmt.para_qtd, self.ent_qtd.text())
            if peso is None:
                return
        self.ent_qtd.setText(_fmt_qtd(fmt.arred_qtd(peso)))
        self.ent_qtd.setFocus()
        self.ent_qtd.selectAll()

    def reimprimir(self) -> None:
        if not self._pode_operar():
            return
        modo = self.dialogos.escolher("Reimprimir", "Cupom (2ª via, não fiscal):",
                                      [("ultimo", "Último cupom"), ("numero", "Por número")])
        if modo is None:
            return
        if modo == "ultimo":
            vid = self.ctx.banco.valor("SELECT id FROM vendas WHERE cupom IS NOT NULL AND status IN "
                                       "('fechada','cancelada') ORDER BY cupom DESC LIMIT 1")
        else:
            def numero(texto):
                if not texto.strip().isdigit() or int(texto) < 1:
                    raise ValueError("Informe um número de cupom maior que zero.")
                return int(texto)
            n = self._pedir_convertido("Reimprimir", "Número do cupom:", numero)
            if n is None:
                return
            vid = self.ctx.banco.valor("SELECT id FROM vendas WHERE cupom = ? AND status IN ('fechada','cancelada')", (n,))
        if vid is None:
            self.dialogos.aviso("Reimprimir", "Cupom não encontrado entre as vendas fechadas/canceladas.")
            return
        n = self.ctx.caixa.obter(vid)["cupom"]
        self._documento_operacao(f"2ª via cupom {n}", lambda: self.ctx.impressao.cupom(vid, segunda_via=True),
                                  f"2via_cupom_{n}", "cupom", venda_id=vid)

    def iniciar_cancelamento(self) -> None:
        if not self._pode_operar() or not self.venda():
            return
        self._cancelamento_autorizado = None
        if self._autorizar("caixa_cancelamento", "exigir_senha_cancelamento", "Cancelar linhas exige autorização:"):
            self._cancelamento_autorizado = (self.venda_id, self.ctx.operador_id, self._turno()["id"])
            self.tabela.setFocus()
            if self.tabela.rowCount():
                self.tabela.selectRow(self.tabela.rowCount() - 1)
            self.avisar("Selecione a linha e tecle Enter para cancelar. Esc retorna.", AMBAR)

    def _em_cancelamento(self) -> bool:
        turno = self._turno()
        return bool(turno and self._cancelamento_autorizado == (self.venda_id, self.ctx.operador_id, turno["id"]))

    def _ativar_linha(self, _item) -> None:
        if self._em_cancelamento():
            self.cancelar_item()

    def _esconder_produtos(self, _texto: str = "") -> None:
        self.lista_produtos.clear()
        self.lista_produtos.hide()

    def _mostrar_produtos(self, produtos: list[dict]) -> None:
        self.lista_produtos.clear()
        for p in produtos:
            item = QListWidgetItem(f"{p['codigo']}  ·  {p['nome']}  ·  {fmt.fmt_brl(self.ctx.produtos.preco_vigente(p))}")
            item.setData(Qt.UserRole, int(p["id"]))
            self.lista_produtos.addItem(item)
        self.lista_produtos.show()
        self.lista_produtos.setCurrentRow(0)
        self.lista_produtos.setFocus()

    def _produto_digitado(self, texto: str, somente_produto: bool = False) -> dict | None | bool:
        """O produto do campo do código: escolhido na lista, pelo código/barras/atalho ou pelo nome. Devolve False quando o
        texto foi tratado de outro jeito (posição, lista para escolher ou operação bloqueada)."""
        escolhido = self.lista_produtos.currentItem() if self.lista_produtos.isVisible() else None
        if escolhido is not None:
            return self.ctx.produtos.por_id(int(escolhido.data(Qt.UserRole)))
        if not texto:
            self.avisar("Digite o código ou parte do nome do produto.", AMBAR)
            return False
        if not somente_produto and self.ctx.comissoes.eh_codigo(texto):
            self.ent_codigo.clear()
            self.lancar_comissao()
            return False
        if not somente_produto and self.ctx.caixa.eh_codigo_saida(texto):
            self.ent_codigo.clear()
            self.liberar_saida()
            return False
        p = self.ctx.produtos.buscar_codigo(texto)
        if p is None and not somente_produto and self.com_mesas and parece_posicao(texto):
            self.ent_codigo.clear()
            self.ent_pos.setText(texto)
            self.chamar_posicao()
            return False
        if p is None and not texto.isdigit():
            achados = self.ctx.produtos.pesquisar(texto)
            if len(achados) == 1:
                p = achados[0]
            elif achados:
                self._mostrar_produtos(achados)
                self.avisar(f"{len(achados)} produtos com '{texto}'. Escolha na lista e tecle Enter.", AMBAR)
                return False
        if p is None and texto.isdigit() and len(texto) >= 8:
            p = self._cadastro_rapido(texto)
            if p is None:
                self.ent_codigo.setFocus()
                return False
        if p is None:
            self.avisar(f"Produto '{texto}' não encontrado.", VERMELHO)
            self.ent_codigo.selectAll()
            return False
        return p

    def _cadastro_rapido(self, cbarra: str) -> dict | None:
        """Produto desconhecido no leitor: permissão de cadastro ou autorização de supervisor."""
        if not self.dialogos.confirmar("Produto novo", f"O código {cbarra} não está cadastrado.\n"
                                                       "Cadastrar o produto agora?"):
            return None
        if not self.ctx.acesso.pode(self.ctx.operador, "cad_produtos") and not self._pedir_supervisor(
                "cad_produtos", "Cadastrar produto exige autorização:"):
            return None
        nome = self.dialogos.pedir_texto("Produto novo", "Nome do produto:")
        if nome is None:
            return None
        preco = self._pedir_convertido("Produto novo", "Preço de venda (R$):",
                                      lambda t: ler_dinheiro(t, permitir_zero=True))
        if preco is None:
            return None
        gelada = self._pedir_convertido("Produto novo", "Preço gelada (R$, opcional; vazio = só natural):",
                                       lambda t: ler_dinheiro(t, permitir_zero=True) if t.strip() else 0)
        if gelada is None:
            return None
        opcoes = [(r["id"], f"{r['nome']} - {r['grupo']}") for r in self.ctx.banco.todos(
            "SELECT s.id, s.nome, g.nome AS grupo FROM subgrupos s "
            "JOIN grupos g ON g.id = s.grupo_id ORDER BY g.nome, s.nome")]
        opcoes.sort(key=lambda o: o[0] != self._subgrupo_rapido)
        subgrupo = self.dialogos.escolher("Produto novo", "Categoria:", opcoes) if opcoes else None
        if opcoes and subgrupo is None:
            return None
        def estoque(texto):
            return fmt.para_qtd(texto) if texto.strip() else ""
        qtd = self._pedir_convertido("Produto novo", "Quantidade em estoque (opcional; vazio não controla):", estoque)
        if qtd is None:
            return None
        ok, p = self._executar(self.ctx.produtos.cadastrar_rapido, cbarra, nome.strip(), preco, subgrupo,
                              None if qtd == "" else qtd, self.ctx.operador_id, preco_gelada_cent=gelada)
        if not ok:
            return None
        self._subgrupo_rapido = p["subgrupo_id"]
        return p

    def _enter_codigo(self) -> None:
        """Enter no campo do código: no modo comissão vai para o valor; senão lança o produto."""
        if self.modo_comissao:
            self._comissao_ir_ao_valor()
        else:
            self.lancar_item()

    def lancar_item(self) -> None:
        if not self._pronto() or self._ocupado:
            return
        if self.modo_comissao:                        # Enter na quantidade (o valor) ou botão Lançar: grava a comissão
            self._comissao_confirmar()
            return
        texto = self.ent_codigo.text().strip()
        quantidade_codigo = QTD_ANTES_DO_CODIGO.fullmatch(texto)
        if quantidade_codigo:
            self.ent_qtd.setText(quantidade_codigo.group(1))
            texto = quantidade_codigo.group(2).strip()
        p = self._produto_digitado(texto, somente_produto=quantidade_codigo is not None)
        if p is False:
            return
        if p is None or not p["ativo"]:
            self.avisar("Produto não encontrado.", VERMELHO)
            return
        try:
            qtd = fmt.para_qtd(self.ent_qtd.text() or "1")
        except ValueError:
            self.avisar("Quantidade inválida.", VERMELHO)
            self.ent_qtd.setFocus()
            self.ent_qtd.selectAll()
            return
        if not math.isfinite(qtd) or qtd <= 0:
            self.dialogos.erro("Erro", "Informe uma quantidade maior que zero e finita.")
            self.ent_qtd.setFocus()
            self.ent_qtd.selectAll()
            return
        partes = None
        if p["partes"] > 1 and (p["composto"] or self.ctx.banco.valor(
                "SELECT COUNT(*) FROM produtos WHERE montagem = 1 AND ativo = 1")):
            partes = self._partes(p)
            if partes is None:
                return
        opcoes = {}
        if p.get("preco_gelada_cent", 0) > 0:
            temperatura = self.dialogos.escolher(
                "Temperatura da bebida", f"{p['nome']}: como o cliente vai levar? "
                "(preço unitário de tabela; atacado automático no balcão)",
                [("natural", f"Natural · {fmt.fmt_brl(self.ctx.produtos.preco_vigente(p))}"),
                 ("gelada", f"Gelada · {fmt.fmt_brl(p['preco_gelada_cent'])}")])
            if temperatura is None:
                return
            opcoes["temperatura"] = temperatura
        if p.get("casco_produto_id"):
            casco = self.ctx.produtos.por_id(p["casco_produto_id"])
            if casco is None:
                self.dialogos.aviso("Cascos / vasilhames", "Casco não encontrado. Confira o cadastro do produto.")
                return
            maximo = max(0, math.floor(qtd))
            def cascos(texto):
                s = texto.strip()
                if not s.isascii() or not s.isdecimal() or not 0 <= int(s) <= maximo:
                    raise ValueError(f"Informe um número inteiro de 0 a {maximo}.")
                return int(s)
            quantidade_cascos = self._pedir_convertido(
                "Cascos / vasilhames", f"{p['nome']} · {casco['nome']} · {fmt.fmt_brl(casco['preco_cent'])} por casco.\n"
                f"Quantos cascos cobrar? Inteiro de 0 a {maximo} (0 = todas as garrafas são trocas).\n"
                "O casco é um item separado: cancelar a bebida NÃO cancela o casco e vice-versa. "
                "Confira os dois itens ao cancelar:", cascos, "0")
            if quantidade_cascos is None:
                return
            opcoes["quantidade_cascos"] = quantidade_cascos
        ok, _ = self._executar(self._lancar, p["id"], qtd, partes, **opcoes)
        if not ok:
            self.recarregar()
            self.ent_qtd.setFocus()
            self.ent_qtd.selectAll()
            return
        self.avisar(f"{_fmt_qtd(fmt.arred_qtd(qtd))} x {p['nome']} lançado.")
        self.ent_codigo.clear()
        self.ent_qtd.setText("1")
        self._esconder_produtos()
        self.recarregar()
        self.ent_codigo.setFocus()

    def _lancar(self, produto_id: int, qtd: float, partes: list[int] | None = None, **opcoes) -> int:
        """Abre o balcão se preciso e lança o item na MESMA transação: se o item for recusado, nenhuma venda vazia fica."""
        caixa = self.ctx.caixa
        anterior = self.venda_id
        try:
            with self.ctx.banco.transacao():
                if self.venda_id is None:
                    self.venda_id = caixa.abrir_balcao()
                item_id = caixa.adicionar_item(self.venda_id, produto_id, qtd, partes=partes or None, **opcoes)
        except BaseException:
            self.venda_id = anterior
            raise
        self._enviar_remoto([item_id])
        return item_id

    def _enviar_remoto(self, item_ids: list[int]) -> None:
        """Manda os itens para a cozinha/bar. Falha da impressora remota não bloqueia a venda."""
        try:
            for sub, texto in self.ctx.impressao.pedido_remoto(self.venda_id, item_ids).items():
                self.ctx.impressao.enviar_remoto(texto, f"pedido_{sub}")
        except ErroImpressao as e:
            self.avisar(f"Impressora da cozinha/bar indisponível: {e}", VERMELHO)

    def _item_selecionado(self) -> tuple[int, str] | None:
        linha = self.tabela.currentRow()
        if linha < 0 or self.tabela.item(linha, 0) is None:
            return None
        chave = self.tabela.item(linha, 0).data(Qt.UserRole)
        if isinstance(chave, str):                    # linha de comissão marcada, não item da venda
            return None
        return int(chave), self.tabela.item(linha, 1).text()

    def _comissao_selecionada(self) -> int | None:
        """O id da comissão marcada escolhida na lista, ou None se a linha é item (ou nada está escolhido)."""
        linha = self.tabela.currentRow()
        item = self.tabela.item(linha, 0) if linha >= 0 else None
        chave = item.data(Qt.UserRole) if item is not None else None
        return int(chave[1:]) if isinstance(chave, str) and chave.startswith("c") else None

    def cancelar_item(self) -> None:
        if not self._pronto() or self._ocupado:
            return
        lid = self._comissao_selecionada()
        if lid is not None:                           # linha de comissão: cancela o lançamento, não um item
            if self._comissao_na_linha():
                self._cancelar_comissao(lid)
            else:
                self.dialogos.aviso("Cancela item", "Para pagar ou cancelar a comissão, use o botão Comissões.")
            return
        sel = self._item_selecionado()
        if sel is None:
            self.dialogos.aviso("Cancela item", "Selecione na lista o item a cancelar.")
            return
        item_id, nome = sel
        if not self._em_cancelamento() and not self._autorizar(
                "caixa_cancelamento", "exigir_senha_cancelamento", "Cancelar item exige autorização:"):
            return
        if not self.dialogos.confirmar("Cancela item", f"Cancelar o item '{nome}'?", padrao_sim=False):
            return
        motivo = self._pedir_motivo("Cancela item", f"Motivo do cancelamento de '{nome}':", "")
        if motivo is None:
            return
        ok, _ = self._executar(self.ctx.caixa.cancelar_item, item_id, motivo)
        self.recarregar()
        if ok:
            self.avisar("Item cancelado.", AMBAR)

    def cancelar_venda(self) -> None:
        if not self._pronto() or self._ocupado:
            return
        v = self.venda()
        if v is None:
            self.dialogos.aviso("Cancela venda", "Não há venda em andamento.")
            return
        if not self._autorizar("caixa_cancelamento", "exigir_senha_cancelamento", "Cancelar a venda exige autorização:"):
            return
        if not self.dialogos.confirmar("Cancela venda", "Cancelar a venda inteira?\nTodos os itens lançados serão eliminados.",
                                       padrao_sim=False):
            return
        motivo = self._pedir_motivo("Cancela venda", "Motivo do cancelamento da venda:", "cancelada no caixa")
        if motivo is None:
            return
        ok, _ = self._executar(self.ctx.caixa.cancelar_venda, v["id"], motivo)
        if ok:
            self.venda_id = None
            self.avisar("Venda cancelada.", AMBAR)
        self.recarregar()
    # ========================================================= mesas e comandas
    def _descartar_se_vazia(self) -> None:
        """Ao sair de uma mesa ou comanda recém-aberta e sem nada, ela é eliminada para não deixar mesa fantasma."""
        v = self.venda()
        if v and v["modalidade"] == "mesa" and not self.ctx.caixa.itens(v["id"], cancelados=True) \
                and not self.ctx.caixa.pagamentos(v["id"]):
            self.ctx.caixa.cancelar_venda(v["id"], "mesa vazia descartada")
            self.venda_id = None

    def _mesa_escolhida(self, item: QListWidgetItem) -> None:
        self.ent_pos.setText(str(item.data(Qt.UserRole)))
        self.chamar_posicao()

    def ir_para_balcao(self) -> None:
        self.ent_pos.setText("0")
        self.chamar_posicao()

    def foco_posicao(self) -> None:
        self._limpar_entrada()
        (self.ent_pos if self.com_mesas else self.ent_codigo).setFocus()

    def chamar_posicao(self) -> None:
        if not self.com_mesas:
            self._limpar_entrada()
            self.ent_pos.clear()
            self.ent_codigo.setFocus()
            return
        if not self._pronto() or self._ocupado:
            return
        if self.modo_comissao:                        # trocou de posição no meio da comissão: ela é descartada
            self._limpar_entrada()
        texto = self.ent_pos.text().strip() or "0"
        try:
            comanda, n = self.ctx.caixa.ler_posicao(texto)
        except ValueError as e:
            self.dialogos.aviso("Mesa ou comanda", str(e))
            return
        atual = self.venda()
        self.ent_pos.clear()
        if atual and atual["modalidade"] == "mesa" and atual["posicao"] == n and bool(atual["comanda"]) == comanda:
            self.ent_codigo.setFocus()
            return
        if atual and n == 0 and atual["modalidade"] == "balcao":
            self.ent_codigo.setFocus()
            return
        if atual and atual["modalidade"] != "mesa" and (
                self.ctx.caixa.itens(atual["id"]) or self.ctx.caixa.pagamentos(atual["id"])):
            self.dialogos.aviso("Mesa ou comanda", "Conclua, pague ou cancele a venda em andamento antes de chamar uma "
                                                   "mesa ou comanda.")
            return
        self._cancelamento_autorizado = None
        ok, _ = self._executar(self._descartar_se_vazia)
        if not ok:
            return
        if n == 0:
            balcao = self.ctx.caixa.balcao_aberto()
            self.venda_id = balcao["id"] if balcao else None
            self.recarregar()
            self.ent_codigo.setFocus()
            return
        pessoas = 0
        existente = self.ctx.banco.valor(
            "SELECT id FROM vendas WHERE modalidade='mesa' AND comanda=? AND posicao=? AND status IN ('aberta','conta_enviada')",
            (int(comanda), n))
        if not existente and not comanda and self.ctx.banco.cfg_bool("pergunta_pessoas"):
            pessoas = self._pedir_pessoas(f"Mesa {n}")
            if pessoas is None:
                self.recarregar()
                return
        ok, res = self._executar(self.ctx.caixa.abrir_mesa, n, pessoas, comanda)
        if ok:
            self.venda_id = res[0]
            self.avisar(f"{nome_posicao(comanda, n)} {'aberta' if res[1] else 'chamada'}.")
        self.recarregar()
        self.ent_codigo.setFocus()

    def _pedir_pessoas(self, titulo: str) -> int | None:
        while True:
            texto = self.dialogos.pedir_texto(titulo, "Número de pessoas na mesa (1 a 999):", padrao="1")
            if texto is None:
                return None
            if texto.strip().isdigit() and 1 <= int(texto) <= 999:
                return int(texto)
            self.dialogos.aviso(titulo, "Digite um número de 1 a 999.")

    # ========================================================= pagamento
    def _receber(self, venda_id: int, forma_id: int, cent: int) -> tuple[int, dict]:
        """Grava o pagamento e confere a conta; se a forma não pode ficar com a sobra (troco), desfaz tudo."""
        caixa = self.ctx.caixa
        pago_antes = sum(p["valor_cent"] for p in caixa.pagamentos(venda_id))
        with self.ctx.banco.transacao():
            pid = caixa.adicionar_pagamento(venda_id, forma_id, cent)
            total = caixa.obter(venda_id)["total_cent"]       # já com a taxa do crédito, se esta forma a cobra
            try:
                return pid, caixa.liquidar(venda_id, total)
            except ErroNegocio:
                nome = self.cmb_forma.currentText() or "Esta forma"
                raise ErroNegocio(f"{nome} não dá troco: o valor não pode passar do que falta "
                                  f"({fmt.fmt_brl(max(total - pago_antes, 0))}).") from None

    def receber(self) -> None:
        if not self._pronto() or self._ocupado or self._fechando_venda:
            return
        v = self.venda()
        if v is None or (not self.ctx.caixa.itens(v["id"]) and v["modalidade"] != "caderneta"):
            self.dialogos.aviso("Pagamento", "Lance ao menos um item antes de receber.")
            return
        if v["modalidade"] == "caderneta" and self.ctx.caixa.itens(v["id"]):
            self.dialogos.aviso("Caderneta", "Venda em caderneta não recebe pagamento. Use Fechar venda para lançar o débito.")
            return
        forma = self.cmb_forma.currentData()
        if forma is None:
            self.dialogos.aviso("Pagamento", "Escolha a forma de pagamento.")
            return
        try:
            cent = ler_valor_pagamento(self.ent_valor.text())
        except ValueError as e:
            self.dialogos.aviso("Pagamento", str(e))
            self.ent_valor.setFocus()
            self.ent_valor.selectAll()
            return
        credito = v["modalidade"] == "caderneta"
        if credito:
            ok, _ = self._executar(self.ctx.caixa.adicionar_pagamento, v["id"], int(forma), cent)
            self.recarregar()
            return
        ok, r = self._executar(self._receber, v["id"], int(forma), cent)
        if not ok:
            self.recarregar()
            return
        pid, liq = r
        if liq.get("troco", 0) > LIMITE_TROCO_CENT and not self.dialogos.confirmar(
                "Troco alto", f"O troco será de {fmt.fmt_brl(liq['troco'])} (recebido: {fmt.fmt_brl(cent)}).\n"
                              "O valor recebido está certo?", padrao_sim=False):
            self._executar(self.ctx.caixa.remover_pagamento, pid)
            self.recarregar()
            return
        self.recarregar()
        if liq.get("falta", 0) == 0:
            self.avisar(f"Pagamento completo. Troco {fmt.fmt_brl(liq.get('troco', 0))}. Feche a venda (F12).")
            self.btn_fechar_venda.setFocus()

    def remover_pagamento(self) -> None:
        if not self._pronto() or self._ocupado or self._fechando_venda:
            return
        item = self.lista_pagamentos.currentItem()
        if item is None and self.lista_pagamentos.count():
            item = self.lista_pagamentos.item(self.lista_pagamentos.count() - 1)   # sem seleção: o último lançado
        if item is None:
            self.avisar("Não há pagamento lançado para remover.", AMBAR)
            return
        ok, _ = self._executar(self.ctx.caixa.remover_pagamento, int(item.data(Qt.UserRole)))
        self.recarregar()
        if ok:
            self.avisar("Pagamento removido.", AMBAR)
    # ========================================================= fechamento da venda
    def fechar_venda(self) -> None:
        if self._fechando_venda or self._ocupado or not self._pronto():   # duas teclas F12 seguidas não gravam duas vezes
            return
        self._fechando_venda = True
        try:
            self._fechar_venda()
        finally:
            self._fechando_venda = False

    def _fechar_venda(self) -> None:
        v = self.venda()
        itens = self.ctx.caixa.itens(v["id"]) if v else []
        if v is None or (not itens and v["modalidade"] != "caderneta"):
            so_comissao = v is not None and self._a_pagar_na_comanda()
            if so_comissao and self._comissao_na_linha():
                self.pagar_comissao(v["posicao"])     # comanda da garota só com comissão: F12 paga a ela
                return
            if v is not None and not so_comissao and self._acerto_so_de_shows(v):
                self.pagar_comissao(v["posicao"])     # garota cadastrada sem comissão marcada: F12 acerta só os shows dela
                return
            self.dialogos.aviso("Fechar venda", "Esta comanda só tem comissão marcada.\nPara pagar à garota, use o botão "
                                "Comissões." if so_comissao else "Lance ao menos um item antes de fechar a venda.")
            return
        if self._a_pagar_na_comanda() and self._comissao_na_linha():
            a_pagar = sum(c["valor_cent"] for c in self.comissao_marcada if c["status"] == "pendente")
            escolha = self.dialogos.escolher("Fechar...", "Esta comanda tem consumo e comissão a pagar. Escolha:", [
                ("itens", f"Pagar a comanda (R$ {fmt.fmt_num(v['total_cent'])})"),
                ("comissao", f"Pagar a comissão da garota (R$ {fmt.fmt_num(a_pagar)})")])
            if escolha is None:
                return
            if escolha == "comissao":
                self.pagar_comissao(v["posicao"])
                return
        garcom = pessoas = None
        if v["modalidade"] == "mesa":
            if self.ctx.banco.cfg_bool("controle_garcom") and not v["garcom_id"]:
                garcom = self._escolher_garcom()
                if garcom is None:
                    return
            if self.ctx.banco.cfg_bool("pergunta_pessoas") and not v["pessoas"] and not v["comanda"]:
                pessoas = self._pedir_pessoas("Mesa")
                if pessoas is None:
                    return
        credito = None
        if v["modalidade"] == "caderneta":
            if itens:
                c = self.ctx.caderneta.obter(v["cliente_id"])
                if not self.dialogos.confirmar("Caderneta", f"Lançar {fmt.fmt_brl(v['total_cent'])} na caderneta de {c['nome']}?"):
                    return
            else:
                info = self.ctx.caixa.info_credito(v["id"])
                if info["excedente"] > 0:
                    credito = self.dialogos.confirmar("Caderneta", f"O valor excede a dívida em {fmt.fmt_brl(info['excedente'])}.\n"
                                                       "Acrescentar o excedente ao crédito? (Não = devolver como troco)")
        ok, venda = self._executar(self.ctx.caixa.fechar, v["id"], garcom, pessoas, credito)
        if not ok:
            self.recarregar()
            return
        self.venda_id = None
        self._pos_fechamento(venda)

    def _escolher_garcom(self) -> int | None:
        ativos = self.ctx.cadastros.listar("operadores", apenas_ativos=True)
        garcons = [(r["id"], r["nome"]) for r in ativos if r["garcom"]] or [(r["id"], r["nome"]) for r in ativos]
        return self.dialogos.escolher("Garçom", "Garçom que atendeu:", garcons)

    def _pos_fechamento(self, venda: dict) -> None:
        """A venda já está gravada: falha de impressão só é avisada (o cupom é mostrado na tela, nunca se perde)."""
        try:
            saida = self.ctx.impressao.saida_da_venda(venda["id"])
        except Exception as e:  # noqa: BLE001 - a venda já está gravada
            saida = None
            self._registrar_falha(e)
        try:
            if self.ctx.banco.cfg_bool("imprimir_cupom", True):
                op = self.ctx.impressao.opcoes_cupom(venda["id"])
                self._emitir(f"Cupom {venda['cupom']}", self.ctx.impressao.cupom(venda["id"]), f"cupom_{venda['cupom']}",
                             tipo="cupom", abrir_gaveta=op["abrir_gaveta"], copias=op["copias"], venda_id=venda["id"])
            if saida:
                self._emitir("Ticket de saída", saida, f"saida_cupom_{venda['cupom']}", tipo="saida")
        except Exception as e:  # noqa: BLE001 - venda gravada: erro de impressão não derruba o caixa
            self._registrar_falha(e)
            self.dialogos.erro("Impressão", f"A venda foi gravada (cupom {venda['cupom']}), mas não foi possível preparar "
                                            f"a impressão:\n{e}\nReimprima o cupom em Operações do caixa.")
        self.ent_codigo.clear()
        self.ent_qtd.setText("1")
        self._esconder_produtos()
        self.recarregar()
        self.lbl_falta_rotulo.setText("Troco (R$)")
        self.lbl_troco.setText(fmt.fmt_num(venda["troco_cent"]))
        texto = f"Venda {venda['cupom']} fechada. Troco {fmt.fmt_brl(venda['troco_cent'])}."
        if venda.get("vale_cent"):
            texto += f" Contra-vale {fmt.fmt_brl(venda['vale_cent'])}."
        alerta = self._alerta_gaveta()
        self.avisar(f"{texto}   {alerta}" if alerta else texto, AMBAR if alerta else VERDE)
        self.ent_codigo.setFocus()

    @staticmethod
    def _registrar_falha(e: Exception) -> None:
        from src.core import registro
        registro.registrar_excecao(type(e), e, e.__traceback__, origem="caixa_qt_impressao")

    def _emitir(self, titulo: str, texto: str, nome: str, tipo: str | None = None, abrir_gaveta: bool = False,
                copias: int = 1, venda_id: int | None = None) -> bool:
        """Como `enviar_ou_mostrar` do caixa clássico: modo 'tela' mostra; senão imprime e, se falhar, mostra com aviso."""
        if self.ctx.impressao.deve_mostrar_na_tela():
            self._mostrar(titulo, texto)
            return False
        try:
            self.ctx.impressao.enviar(texto, nome, tipo=tipo, abrir_gaveta=abrir_gaveta, copias=copias, venda_id=venda_id)
            return True
        except ErroImpressao as e:
            self.dialogos.erro("Impressão", f"Não foi possível imprimir: {e}\nMostrando o documento na tela.")
            self._mostrar(titulo, texto)
            return False

    def _mostrar(self, titulo: str, texto: str) -> None:
        self.documentos = [d for d in self.documentos if _vivo(d) and d.isVisible()]
        doc = Documento(self, titulo, texto)
        self.documentos.append(doc)
        doc.show()

    def _alerta_gaveta(self) -> str:
        turno = self._turno()
        if turno is None:
            return ""
        horario = self.ctx.turnos.sangria_do_horario(turno["id"])
        if horario:
            return f"ATENÇÃO: está na hora da sangria das {horario} (Operações do caixa)."
        limite = self.ctx.banco.cfg_int("limite_gaveta", 0) * 100
        if limite <= 0 or self.ctx.turnos.dinheiro_esperado(turno["id"]) <= limite:
            return ""
        return f"ATENÇÃO: a gaveta passou de {fmt.fmt_brl(limite)}. Faça uma sangria (Operações do caixa)."
    # ========================================================= comissão das garotas (código 50)
    def _comissao_na_linha(self) -> bool:
        """Comissão lançada, paga e cancelada na própria tela do caixa (padrão) ou pelas janelas (config desligada)."""
        return self.ctx.banco.cfg_bool("comissao_na_linha", True)

    def _a_pagar_na_comanda(self) -> bool:
        return any(c["status"] == "pendente" for c in self.comissao_marcada)

    def _acerto_so_de_shows(self, v: dict | None) -> bool:
        """Comanda vazia de uma garota cadastrada e ativa: dá para acertar com ela só os shows (sem comissão marcada)."""
        if not v or v["modalidade"] != "mesa" or not v["comanda"] or not self._comissao_na_linha() \
                or not self.ctx.comissoes.pede_shows():
            return False
        g = self.ctx.comissoes.garota(v["posicao"])
        return g is not None and bool(g["ativo"])

    def _dialogo_comissao(self, sugerida: str = "") -> tuple[int, int] | None:
        """Ponto de troca dos testes: a janela do código 50. Devolve (número da garota, centavos) ou None."""
        dlg = comissao.DialogoComissao(self, self.ctx, sugerida)
        return dlg.resultado if dlg.exec() == QDialog.Accepted else None

    def _dialogo_acerto(self, numero: int, nome: str, comissao_cent: int, quantidade: int,
                        do_caixa_padrao: bool = False) -> dict | None:
        """Ponto de troca dos testes: a janela do acerto. Devolve {"do_caixa", "shows", "valor_show_cent", "pix_cent",
        "vale_cent"} ou None."""
        dlg = comissao.DialogoAcerto(self, self.ctx, numero, nome, comissao_cent, quantidade, do_caixa_padrao)
        return dlg.resultado if dlg.exec() == QDialog.Accepted else None

    def lancar_comissao(self) -> None:
        """Código 50. Com `comissao_na_linha`: na própria linha de entrada, 'Garota nº' (já vem o da comanda) e o valor.
        Desligada: pela janela."""
        if self._ocupado:
            return
        if not self._comissao_na_linha():
            self._lancar_comissao_na_janela()
            return
        if not self._autorizar("caixa_comissao", "exigir_senha_comissao", "Lançar comissão exige autorização:"):
            self.ent_codigo.setFocus()
            return
        if self._turno() is None:
            self.dialogos.aviso("Comissão", "Abra o turno do caixa antes de lançar comissão.")
            return
        self._limpar_entrada()
        v = self.venda()
        garota = str(v["posicao"]) if v and v["modalidade"] == "mesa" and v["comanda"] else ""
        self.modo_comissao = True
        self.lbl_cod_titulo.setText("Garota nº:")
        self.lbl_qtd_titulo.setText(f"{self.ctx.comissoes.rotulo_valor()}:")
        self.btn_lancar.setText("Lançar comissão")
        self.ent_codigo.setText(garota)
        self.ent_qtd.clear()
        self.lbl_comissao_nome.show()
        self._comissao_nome()
        if garota:
            oque = "os pontos" if self.ctx.comissoes.em_pontos() else "o valor"
            self.avisar(f"Comissão da garota {garota}: digite {oque} e tecle Enter (Esc cancela).", AMBAR)
            self.ent_qtd.setFocus()
        else:
            self.avisar("Comissão: digite o número da garota e tecle Enter (Esc cancela).", AMBAR)
            self.ent_codigo.setFocus()

    def _lancar_comissao_na_janela(self) -> None:
        """Com 'comissao_na_linha' desligado: na comanda 180 a garota é a 180 (a janela já vem com o número)."""
        v = self.venda()
        sugerida = str(v["posicao"]) if v and v["modalidade"] == "mesa" and v["comanda"] else ""
        r = comissao.lancar(self, sugerida)
        if r is not None:
            self.avisar(r[1])
        self.recarregar()                             # a comissão nova já aparece na comanda da garota
        self.ent_codigo.setFocus()

    def _comissao_nome(self, _texto: str = "") -> None:
        """No modo comissão, mostra quem é a garota do número digitado."""
        if not self.modo_comissao:
            return
        texto = self.ent_codigo.text().strip()
        try:
            n = self.ctx.comissoes.validar_numero(texto) if texto else None
        except ErroNegocio:
            n = None
        g = self.ctx.comissoes.garota(n) if n is not None else None
        if n is None:
            desc = "COMISSÃO - digite a garota"
        elif g is not None:
            desc = f"COMISSÃO - {g['nome']}" + ("" if g["ativo"] else " (inativa)")
        elif self.ctx.comissoes.cadastro_vazio():
            desc = f"COMISSÃO - garota {n}"
        else:
            desc = "COMISSÃO - não cadastrada"
        self.lbl_comissao_nome.setText(desc)

    def _comissao_ir_ao_valor(self) -> None:
        try:
            self.ctx.comissoes.validar_numero(self.ent_codigo.text())
        except ErroNegocio as e:
            self.avisar(str(e), VERMELHO)
            return
        self.ent_qtd.setFocus()
        self.ent_qtd.selectAll()

    def _comissao_confirmar(self) -> None:
        """Enter no valor: confere (garota, valor, perguntas de exceção), grava, imprime a via da garota e deixa o caixa livre."""
        try:
            numero = self.ctx.comissoes.validar_numero(self.ent_codigo.text())
        except ErroNegocio as e:
            self.avisar(str(e), VERMELHO)
            self.ent_codigo.setFocus()
            return
        try:
            cent = self.ctx.comissoes.para_centavos(self.ent_qtd.text())
        except (ValueError, ErroNegocio) as e:
            self.avisar(str(e) if isinstance(e, ErroNegocio) else "Valor inválido.", VERMELHO)
            self.ent_qtd.setFocus()
            return
        if cent <= 0:
            self.avisar("Informe " + ("os pontos" if self.ctx.comissoes.em_pontos() else "o valor") + " da comissão.",
                        VERMELHO)
            self.ent_qtd.setFocus()
            return
        campo = comissao.conferir_lancamento(self.dialogos, self.ctx, numero, cent)
        if campo is not None:
            (self.ent_codigo if campo == "numero" else self.ent_qtd).setFocus()
            return
        turno = self._turno()
        if turno is None:
            self.dialogos.aviso("Comissão", "Abra o turno do caixa antes de lançar comissão.")
            return
        r = comissao.registrar_comissao(self, turno["id"], numero, cent)
        if r is None:
            self.ent_qtd.setFocus()                   # o erro já foi mostrado: o operador corrige e tenta de novo
            return
        self._limpar_entrada()
        self.recarregar()                             # a comissão nova já aparece na comanda da garota
        self.avisar(r[1])
        self.ent_codigo.setFocus()

    def _limpar_entrada(self) -> None:
        """Desfaz o modo comissão (se ligado) e devolve a linha de entrada ao produto."""
        if self.modo_comissao:
            self.modo_comissao = False
            self.lbl_cod_titulo.setText("Código ou nome do produto:")
            self.lbl_qtd_titulo.setText("Quantidade:")
            self.btn_lancar.setText("Lançar")
            self.lbl_comissao_nome.clear()
            self.lbl_comissao_nome.hide()
        self.ent_codigo.clear()
        self.ent_qtd.setText("1")
        self._esconder_produtos()

    def cancelar_modo_comissao(self) -> None:
        """Esc: desiste da comissão que estava sendo digitada (nada foi gravado)."""
        if self._cancelamento_autorizado is not None:
            self._cancelamento_autorizado = None
            self.avisar("")
            self.ent_codigo.setFocus()
        if not self.modo_comissao and self.com_mesas:
            return
        era_comissao = self.modo_comissao
        self._limpar_entrada()
        self.avisar("Comissão descartada." if era_comissao else "", AMBAR)
        self.ent_codigo.setFocus()

    def pagar_comissao(self, numero: int | None = None) -> None:
        """Acerta a garota `numero` (sem número, a da comanda na tela): comissão marcada, shows, vale e Pix, com recibo e,
        se o dinheiro sair da gaveta, a sangria e o comprovante."""
        if self._ocupado:
            return
        if numero is None:
            v = self.venda()
            if not (v and v["modalidade"] == "mesa" and v["comanda"]):
                self.dialogos.aviso("Comissão", "Chame a comanda da garota para pagar (ou use o botão Comissões).")
                return
            numero = v["posicao"]
        pag = comissao.pagar_garota(self, int(numero))
        if pag is not None:
            self.recarregar()
            self.avisar(comissao.texto_pagamento(pag))
        self.ent_codigo.setFocus()

    def _cancelar_comissao(self, lancamento_id: int) -> None:
        """Cancelar item numa linha de comissão da comanda da garota."""
        lanc = next((c for c in self.comissao_marcada if c["id"] == lancamento_id), None)
        if lanc is None:
            return
        if lanc["status"] != "pendente":
            self.dialogos.aviso("Comissão", "Esta comissão já foi paga: não pode mais ser cancelada.")
            return
        quem = f"a comissão de {fmt.fmt_brl(lanc['valor_cent'])} da garota {lanc['garota']}"
        if self._em_cancelamento():
            if not self.dialogos.confirmar("Cancelar comissão", f"Cancelar {quem}?\nEle deixa de contar como comissão a pagar.",
                                           padrao_sim=False):
                return
            ok, _ = self._executar(self.ctx.comissoes.cancelar, lanc["id"], self.ctx.operador_id, "cancelado no caixa")
        else:
            ok = comissao.cancelar_lancamento(self, lanc["id"], quem)
        if ok:
            self.recarregar()
            self.avisar("Comissão cancelada.", AMBAR)

    def abrir_comissoes(self):
        """Botão Comissões: o que há a pagar a cada garota, pagamento com recibo e cancelamento de lançamento."""
        j = self.janela_comissoes
        if j is not None and _vivo(j) and j.isVisible():
            j.atualizar()
        else:
            j = self.janela_comissoes = comissao.JanelaComissoes(self)
            j.show()
        j.raise_()
        return j

    # ========================================================= saída sem consumo (1002)
    def _pedir_posicao(self, titulo: str, rotulo: str) -> tuple[bool, int] | None:
        """Pergunta uma comanda ou mesa na notação da loja; devolve (comanda, número) ou None se cancelado."""
        if not self.com_mesas:
            return None
        while True:
            texto = self.dialogos.pedir_texto(titulo, rotulo)
            if texto is None:
                return None
            try:
                return self.ctx.caixa.ler_posicao(texto)
            except ValueError as e:
                self.dialogos.aviso(titulo, str(e))

    def liberar_saida(self) -> None:
        """Código 1002 na comanda do cliente que não consumiu nada: libera a posição e imprime o ticket de saída (comanda,
        data, hora). Sem comanda na tela, pergunta qual."""
        if self._ocupado or not self._pronto():
            return
        v = self.venda()
        if v and v["modalidade"] == "mesa":
            pos = (bool(v["comanda"]), v["posicao"])
        else:
            comum, outra = exemplos(self.ctx.caixa.padrao_posicao())
            pos = self._pedir_posicao("Saída sem consumo", f"Comanda (ex.: {comum}) ou mesa (ex.: {outra}) que vai sair:")
            if pos is None:
                self.ent_codigo.setFocus()
                return
        ok, info = self._executar(self.ctx.caixa.liberar_saida, *pos)
        if not ok:
            self.ent_codigo.setFocus()
            return
        self.venda()                                  # a posição liberada deixa de estar aberta: solta a venda da tela
        try:
            self._emitir("Ticket de saída", self.ctx.impressao.comprovante_saida(info, self.ctx.operador.nome),
                         f"saida_{info['rotulo']}", tipo="saida")
        except Exception as e:  # noqa: BLE001 - a saída já está gravada
            self._registrar_falha(e)
            self.dialogos.erro("Impressão", f"A saída foi liberada, mas o ticket não pôde ser preparado:\n{e}")
        self.recarregar()
        self.avisar(f"Saída liberada: {info['nome']} sem consumo.")
        self.ent_codigo.setFocus()

    # ========================================================= troca de turno
    def ir_para_fechamento(self) -> None:
        if not self._pronto() or self._ocupado:
            return
        v = self.venda()
        if v and v["modalidade"] != "mesa" and (
                self.ctx.caixa.itens(v["id"]) or self.ctx.caixa.pagamentos(v["id"])):
            self.dialogos.aviso("Troca de turno", "Há uma venda em andamento. Conclua ou cancele antes de trocar o turno.")
            return
        ok, _ = self._executar(self._descartar_se_vazia)
        if not ok:
            return
        self.venda_id = None
        turno = self._turno()
        maq = self.ctx.turnos.maquininha(turno["id"])
        linhas = [f"{r['tipo']}: {r['qtd']} lançamento(s), {fmt.fmt_brl(r['valor'])}" for r in maq["linhas"]]
        self.txt_maquininha.setPlainText("\n".join(linhas) or "Nenhum lançamento em cartão ou Pix neste turno.")
        self.lbl_avisos_turno.setText(self._avisos_turno().strip())
        self.ent_gaveta.clear()
        self.paginas.setCurrentIndex(PAGINA_FECHAMENTO)
        self.ent_gaveta.setFocus()

    def _avisos_turno(self) -> str:
        aviso = ""
        abertas = self.ctx.turnos.posicoes_abertas()
        if abertas:
            nomes = ", ".join(p["nome"] for p in abertas[:6]) + (", ..." if len(abertas) > 6 else "")
            aviso = (f"\n\nATENÇÃO: {len(abertas)} mesa(s)/comanda(s) aberta(s), "
                     f"{fmt.fmt_brl(sum(p['total_cent'] for p in abertas))}:\n{nomes}.\nElas continuam abertas no próximo turno.")
        a_pagar = self.ctx.comissoes.pendentes_por_garota()
        if a_pagar:
            aviso += (f"\n\nComissão das garotas a pagar: {fmt.fmt_brl(sum(p['total_cent'] for p in a_pagar))} "
                      f"({len(a_pagar)} garota(s)).\nSe vai pagar com dinheiro da gaveta, responda Não, pague "
                      "(botão Comissões) e conte o caixa de novo.")
        return aviso

    def voltar_para_venda(self) -> None:
        self.paginas.setCurrentIndex(PAGINA_VENDA)
        self.recarregar_tudo()
        self.ent_codigo.setFocus()

    def fechar_turno(self) -> None:
        if self._ocupado or self.paginas.currentIndex() != PAGINA_FECHAMENTO:
            return
        turno = self._turno()
        if turno is None:
            self.recarregar_tudo()
            return
        try:
            valor = ler_dinheiro(self.ent_gaveta.text(), permitir_zero=True)
        except ValueError as e:
            self.dialogos.aviso("Troca de turno", str(e))
            return
        if not self.dialogos.confirmar("Troca de turno", f"Confirma {fmt.fmt_brl(valor)} como valor final?\n"
                                       "Depois de confirmar o turno é encerrado e não pode ser acertado."
                                       + self._avisos_turno(), padrao_sim=False):
            return
        ok, res = self._executar(self.ctx.turnos.fechar, turno["id"], self.ctx.operador_id, valor)
        if not ok:
            return
        if self.ctx.utilitarios.backup_automatico("troca de turno") is None:
            self.dialogos.aviso("Backup", "O turno foi fechado, mas o BACKUP automático falhou.\n"
                                          "Faça um backup manual em Utilitários > Backup de dados e confira a pasta/disco.")
        self._documento_fechamento(res)
        self.paginas.setCurrentIndex(PAGINA_VENDA)
        self.recarregar_tudo()
        self.avisar(f"Turno {turno['numero']} encerrado.", AMBAR)

    def _documento_fechamento(self, res: dict) -> None:
        """O fechamento sai na impressora (se configurado) ou é mostrado na tela; erro aqui não desfaz o turno fechado."""
        try:
            texto = self.ctx.impressao.fechamento(res)
            nome = f"fechamento_turno_{res['turno']['numero']}"
            if self.ctx.banco.cfg_bool("imprimir_fechamento_ao_trocar", True) and not self.ctx.impressao.deve_mostrar_na_tela():
                vias = max(1, min(self.ctx.banco.cfg_int("vias_fechamento", 1), 3))
                try:
                    self.ctx.impressao.enviar(texto, nome, tipo="fechamento", copias=vias)
                    return
                except ErroImpressao as e:
                    self.dialogos.erro("Impressão", f"O fechamento não foi impresso: {e}\nMostrando na tela.")
            self._mostrar("Fechamento do turno", texto)
        except Exception as e:  # noqa: BLE001 - o turno já está fechado
            self._registrar_falha(e)
            self.dialogos.erro("Fechamento", f"O turno foi fechado, mas o relatório não pôde ser preparado:\n{e}")

    # ========================================================= sair
    def closeEvent(self, evento) -> None:
        """Sair nunca fecha o turno. Venda de balcão com itens fica aberta para continuar depois (pergunta antes);
        mesa ou comanda vazia é descartada. Durante uma gravação o fechamento é recusado."""
        if self._ocupado or self._fechando_venda:
            evento.ignore()
            return
        try:
            v = self.venda() if self.ctx.operador is not None else None
            if v and v["modalidade"] == "balcao" and self.ctx.caixa.itens(v["id"]):
                if not self.dialogos.confirmar("Sair do caixa", "Há uma venda em andamento no balcão.\n"
                                               "Sair mantém a venda aberta para continuar depois. Sair mesmo?"):
                    evento.ignore()
                    return
            else:
                self._descartar_se_vazia()
        except ErroNegocio:
            pass
        for doc in self.documentos:
            if _vivo(doc):
                doc.close()
        self.documentos = []
        if self.janela_comissoes is not None and _vivo(self.janela_comissoes):
            self.janela_comissoes.close()
        self.janela_comissoes = None
        self._cancelamento_autorizado = None
        evento.accept()