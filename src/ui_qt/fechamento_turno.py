"""Troca de turno do caixa no modelo clássico: conferir a maquininha, declarar a gaveta, confirmar e ver o resumo do turno.

`DialogoMaquininha` mostra o que foi lançado no turno em cartão (débito e crédito separados) e Pix, antes de contar a gaveta,
sem revelar o dinheiro esperado. `PainelFechamento` é o resumo depois de fechar: dados do turno, recebimentos financeiros e a
faixa do resultado (sobra/zero em verde, falta em vermelho) com Imprimir, Gerar arquivo texto e Conferência do turno.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from src.controllers import conferencia_turno
from src.core import formatacao as fmt

# Linhas do fechamento de módulos opcionais: zeradas e com o módulo desligado (boate), não aparecem.
_LINHAS_OPCIONAIS = {"entregas_pendentes": "usar_delivery", "venda_caderneta": "usar_caderneta",
                     "pagtos_caderneta": "usar_caderneta"}


def _negrito(texto: str, direita: bool = False) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setStyleSheet("font-weight: bold;")
    if direita:
        rotulo.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return rotulo


class DialogoMaquininha(QDialog):
    """Antes de contar a gaveta: o que foi lançado no turno em cartão e Pix, para comparar com o fechamento do lote."""

    def __init__(self, maq: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Conferir maquininha")
        raiz = QVBoxLayout(self)
        raiz.addWidget(_negrito("Lançado neste turno no sistema"))
        dica = QLabel("Compare cada linha com o total que a maquininha (fechamento do lote) mostra.")
        dica.setWordWrap(True)
        raiz.addWidget(dica)
        grade = QGridLayout()
        for i, cab in enumerate(("Forma", "Qtd.", "Valor (R$)")):
            grade.addWidget(_negrito(cab, direita=i > 0), 0, i)
        for i, r in enumerate(maq["linhas"], start=1):
            grade.addWidget(_negrito(str(r["tipo"])), i, 0)
            grade.addWidget(QLabel(str(r["qtd"])), i, 1, Qt.AlignRight)
            valor = _negrito(fmt.fmt_num(r["valor"]), direita=True)
            valor.setStyleSheet("font-weight: bold; font-size: 15pt;")
            grade.addWidget(valor, i, 2)
        fim = len(maq["linhas"]) + 1
        linha = QFrame()
        linha.setFrameShape(QFrame.HLine)
        grade.addWidget(linha, fim, 0, 1, 3)
        grade.addWidget(_negrito("Total"), fim + 1, 0)
        grade.addWidget(QLabel(str(maq["qtd"])), fim + 1, 1, Qt.AlignRight)
        total = _negrito(fmt.fmt_num(maq["total"]), direita=True)
        total.setStyleSheet("font-weight: bold; font-size: 15pt;")
        grade.addWidget(total, fim + 1, 2)
        grade.setColumnStretch(0, 1)
        raiz.addLayout(grade)
        aviso = QLabel("Se algum valor não bate, cancele e confira os pagamentos antes de fechar o turno.")
        aviso.setWordWrap(True)
        raiz.addWidget(aviso)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        botoes.addWidget(cancelar)
        self.btn_continuar = QPushButton("Continuar")
        self.btn_continuar.setObjectName("primario")
        self.btn_continuar.setDefault(True)
        self.btn_continuar.clicked.connect(self.accept)
        botoes.addWidget(self.btn_continuar)
        raiz.addLayout(botoes)
        self.setMinimumWidth(440)


def dados_do_turno(ctx, res: dict) -> list[tuple[str, str]]:
    """As linhas do quadro 'Turno' do resumo; as zeradas de módulos desligados (delivery, garotas, portaria) somem."""
    t = res["turno"]
    M = fmt.fmt_num
    abertas = res.get("posicoes_abertas") or []
    com = res.get("comissoes") or {}
    shows = res.get("shows") or {}
    dados = [("Turno", t["numero"]), ("Abertura", fmt.fmt_datahora(t["aberto_em"])),
             ("Valor inicial (+)", M(res["valor_inicial"])), ("Cupom inicial", res["cupom_inicial"]),
             ("Fechamento", fmt.fmt_datahora(fmt.agora())), ("Valor final (-)", M(res["valor_final"])),
             ("Cupom final", res["cupom_final"]), ("Posições", res["posicoes"]), ("Entregas", res["entregas"]),
             ("Perc. entrega", f"{res['perc_entrega']:.2f}".replace(".", ",")), ("TC (cupons)", res["tc"]),
             ("TM", M(res["tm"])), ("Nº de pessoas", res["pessoas"]), ("Valor por pessoa", M(res["valor_por_pessoa"])),
             ("Posições em aberto", f"{len(abertas)} ({M(sum(p['total_cent'] for p in abertas))})" if abertas else "nenhuma"),
             ("Cupons cancelados", len(res.get("cupons_cancelados") or ())),
             ("Itens cancelados", len(res.get("itens_cancelados") or ())),
             ("Transferências", len(res.get("transferencias") or ())),
             ("Comissões das garotas", M(com["total_cent"]) if com.get("quantidade") else "nenhuma"),
             ("Shows pagos às garotas", M(shows["total_cent"]) if shows.get("quantidade") else "nenhum"),
             ("Saídas sem consumo (1002)", len(res.get("saidas_liberadas") or ())),
             ("Produtos vendidos", f"{len(res.get('produtos_vendidos') or ())} (lista na conferência)")]
    if not res["entregas"] and not ctx.banco.cfg_bool("usar_delivery", False):
        dados = [d for d in dados if d[0] not in ("Entregas", "Perc. entrega")]
    if not com.get("quantidade") and not shows.get("quantidade") and not ctx.comissoes.ligada():
        dados = [d for d in dados if d[0] not in ("Comissões das garotas", "Shows pagos às garotas")]
    if not res.get("saidas_liberadas") and not ctx.banco.cfg_bool("usar_portaria", True):
        dados = [d for d in dados if d[0] != "Saídas sem consumo (1002)"]
    return [(r, str(v)) for r, v in dados]


def dados_financeiros(ctx, res: dict) -> list[tuple[str, str, bool]]:
    """As linhas do quadro 'Recebimentos financeiros': (rótulo, valor, em destaque). Uma linha vazia ('', '', False) é o traço."""
    M = fmt.fmt_num
    linhas: list[tuple[str, str, bool]] = [(r["tipo"], M(r["valor"]), False)
                                           for r in res["recebimentos"] or [{"tipo": "(nenhum)", "valor": 0}]]
    for rotulo, chave in (("Adiant. de contas abertas", "adiantamentos_abertos"),
                          ("Pago em turno anterior", "recebido_turno_anterior")):
        if res.get(chave):                  # explica por que o recebido difere do vendido; só aparece quando acontece
            linhas.append((f"  {rotulo}", M(res[chave]), False))
    linhas.append(("", "", False))
    for rotulo, chave in (("Troco", "troco"), ("C. Vale emitido (+)", "vale_emitido"), ("Venda (+)", "venda"),
                          ("Desconto (-)", "desconto"), ("Serviço (+)", "servico"), ("Taxa (+)", "taxa"),
                          ("Taxa do crédito (+)", "acrescimo"), ("Repique", "repique"),
                          ("Entregas pend.", "entregas_pendentes"), ("Venda caderneta", "venda_caderneta"),
                          ("Pagtos caderneta (+)", "pagtos_caderneta"), ("Entradas financ. (+)", "entradas"),
                          ("Saídas financ. (-)", "saidas"), ("Fora da gaveta (cartão/Pix)", "fora_da_gaveta"),
                          ("Valor esperado", "esperado")):
        if not res[chave] and (chave == "acrescimo" or (
                chave in _LINHAS_OPCIONAIS and not ctx.banco.cfg_bool(_LINHAS_OPCIONAIS[chave], False))):
            continue
        valor = str(res[chave]) if chave == "entregas_pendentes" else M(res[chave])
        linhas.append((rotulo, valor, chave == "esperado"))
    return linhas


def rotulo_do_resultado(resultado: int) -> str:
    return "SOBRA" if resultado > 0 else ("FALTA" if resultado < 0 else "CAIXA CONFERIDO")


class PainelFechamento(QDialog):
    """Resumo do turno (sobra/zero em verde, falta em vermelho) com Imprimir, Gerar arquivo texto e Conferência do turno.

    `emitir(titulo, texto, nome, tipo)` imprime ou mostra (como o caixa faz com qualquer documento) e `mostrar(titulo, texto)`
    abre o texto na tela; `avisar(titulo, texto)` informa o arquivo gerado."""

    def __init__(self, ctx, res: dict, vias_impressas: int = 0, emitir: Callable | None = None,
                 mostrar: Callable | None = None, avisar: Callable | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx, self.res = ctx, res
        self._emitir, self._mostrar, self._avisar = emitir, mostrar, avisar
        self.setWindowTitle("Fechamento do turno")
        raiz = QVBoxLayout(self)
        quadros = QHBoxLayout()
        esq = QGroupBox("Turno")
        g_esq = QGridLayout(esq)
        for i, (rotulo, valor) in enumerate(dados_do_turno(ctx, res)):
            g_esq.addWidget(QLabel(rotulo), i, 0)
            g_esq.addWidget(_negrito(valor, direita=True), i, 1)
        quadros.addWidget(esq)
        dir_ = QGroupBox("Recebimentos financeiros")
        g_dir = QGridLayout(dir_)
        for i, (rotulo, valor, destaque) in enumerate(dados_financeiros(ctx, res)):
            if not rotulo:
                tracado = QFrame()
                tracado.setFrameShape(QFrame.HLine)
                g_dir.addWidget(tracado, i, 0, 1, 2)
                continue
            g_dir.addWidget(_negrito(rotulo) if destaque else QLabel(rotulo), i, 0)
            g_dir.addWidget(_negrito(valor, direita=True), i, 1)
        quadros.addWidget(dir_)
        raiz.addLayout(quadros)
        resultado = res["resultado"]
        cor = "#17805a" if resultado >= 0 else "#b83a45"
        self.faixa = QLabel(f"Resultado: {fmt.fmt_brl(resultado)}  -  {rotulo_do_resultado(resultado)}")
        self.faixa.setAlignment(Qt.AlignCenter)
        self.faixa.setStyleSheet(f"background: {cor}; color: #ffffff; font-size: 20pt; font-weight: bold; "
                                 "padding: 10px; border-radius: 8px;")
        raiz.addWidget(self.faixa)
        barra = QHBoxLayout()
        self.btn_imprimir = QPushButton("Imprimir Fechamento")
        self.btn_imprimir.clicked.connect(self.imprimir)
        barra.addWidget(self.btn_imprimir)
        self.btn_texto = QPushButton("Gera Arquivo Texto")
        self.btn_texto.clicked.connect(self.gerar_texto)
        barra.addWidget(self.btn_texto)
        self.btn_conferencia = QPushButton("Conferência do turno")
        self.btn_conferencia.clicked.connect(self.conferencia)
        barra.addWidget(self.btn_conferencia)
        barra.addStretch(1)
        self.btn_concluir = QPushButton("Concluir (Enter)")
        self.btn_concluir.setObjectName("primario")
        self.btn_concluir.setDefault(True)
        self.btn_concluir.clicked.connect(self.accept)
        barra.addWidget(self.btn_concluir)
        raiz.addLayout(barra)
        self.lbl_impresso = QLabel("")
        if vias_impressas:
            self.lbl_impresso.setText(
                f"Fechamento enviado à impressora ({vias_impressas} via{'s' if vias_impressas > 1 else ''}): "
                "o caixa responsável e o gerente assinam.")
            self.lbl_impresso.setStyleSheet("color: #52a98a; font-weight: bold;")
        raiz.addWidget(self.lbl_impresso)
        self.btn_concluir.setFocus()

    def _texto(self) -> str:
        return self.ctx.impressao.fechamento(self.res)

    def _nome(self) -> str:
        return f"fechamento_turno_{self.res['turno']['numero']}"

    def imprimir(self) -> None:
        if self._emitir:
            self._emitir("Fechamento de turno", self._texto(), self._nome(), tipo="fechamento")

    def conferencia(self) -> None:
        """Posições abertas, cancelamentos e transferências do turno, na tela (sem imprimir)."""
        if self._mostrar:
            self._mostrar("Conferência do turno",
                          conferencia_turno.texto_conferencia(self.res, self.ctx.impressao.largura()))

    def gerar_texto(self) -> None:
        """Grava o fechamento em arquivo sem imprimir a fita."""
        caminho = self.ctx.impressao.enviar(self._texto(), self._nome())
        if self._avisar:
            self._avisar("Gera Arquivo Texto", f"Arquivo gerado:\n{caminho}")
