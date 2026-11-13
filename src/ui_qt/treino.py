"""Caixa de treino com tutorial: a pessoa faz uma venda inteira no teclado, guiada passo a passo.

O caixa é o de verdade (`JanelaCaixa`), mas ligado a um banco só na memória (`controllers/treino.py`): nada entra no
caixa da loja, no estoque, na impressora, na SEFAZ ou no Mercado Pago. Fechar a janela joga o treino fora.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel

from src.controllers import treino
from src.controllers.contexto import Contexto
from src.controllers.tutoriais import ROTEIROS, Tutoriais, passos_venda

FAIXA = "background: #f5c518; color: #101820; font-weight: bold; font-size: 15px; padding: 4px 10px;"


def _avaliador(janela, banco, fechadas_antes: int):
    """Condições do tutorial da venda, olhando o caixa de treino."""
    def foco_em(widget) -> bool:
        return QApplication.focusWidget() is widget

    def itens() -> list:
        v = janela.venda()
        return janela.ctx.caixa.itens(v["id"]) if v else []

    def fechadas() -> int:
        return int(banco.valor("SELECT COUNT(*) FROM vendas WHERE status = 'fechada'") or 0)

    def avaliar(condicao: str, _janela):
        if condicao == "comanda":
            v = janela.venda()
            return bool(v and v["modalidade"] == "mesa") and not foco_em(janela.ent_pos)
        if condicao == "codigo":
            return foco_em(janela.ent_qtd) or bool(itens())
        if condicao == "item":
            return bool(itens())
        if condicao == "forma":
            return foco_em(janela.cmb_forma) or foco_em(janela.ent_valor) or fechadas() > fechadas_antes
        if condicao == "valor":
            return foco_em(janela.ent_valor) or fechadas() > fechadas_antes
        if condicao == "pago":
            v = janela.venda()
            if v is None:
                return fechadas() > fechadas_antes
            pago = sum(p["valor_cent"] for p in janela.ctx.caixa.pagamentos(v["id"]))
            return bool(itens()) and pago >= v["total_cent"]
        if condicao == "fechada":
            return fechadas() > fechadas_antes
        return None
    return avaliar


def abrir_caixa_treino(principal):
    """Abre o caixa de treino (sem tutorial). Devolve a janela."""
    from src.ui_qt.caixa import JanelaCaixa
    anterior = principal.janelas.get("treino")
    if anterior is not None:
        anterior.close()
    banco, operador = treino.criar_banco(principal.ctx.banco)
    janela = JanelaCaixa(Contexto(banco, operador), principal)
    janela.setWindowTitle("Caixa de TREINO - nada aqui vale de verdade")
    faixa = QLabel("TREINO: pode errar à vontade. Nada entra no caixa, no estoque nem na impressora.")
    faixa.setStyleSheet(FAIXA)
    janela.statusBar().insertPermanentWidget(0, faixa)
    janela.treino_banco = banco
    janela.destroyed.connect(lambda *_: banco.fechar())
    principal._unica("treino", lambda: janela)
    janela.ent_pos.setFocus() if janela.com_mesas else janela.ent_codigo.setFocus()
    return janela


def iniciar_venda(principal):
    """Tutorial "Fazer uma venda": abre o caixa de treino e guia a venda no teclado."""
    from src.ui_qt.tutorial import MotorTutorial
    anterior = getattr(principal, "tutorial", None)
    if anterior and anterior.ativo:
        anterior.encerrar()
    janela = abrir_caixa_treino(principal)
    roteiro = ROTEIROS["venda"]
    loja, operador_id = principal.ctx.banco, principal.ctx.operador_id
    fechadas = int(janela.treino_banco.valor("SELECT COUNT(*) FROM vendas WHERE status = 'fechada'") or 0)

    def avisar(mensagem):
        import shiboken6
        if shiboken6.isValid(janela) and janela.isVisible():
            janela.avisar(mensagem)
        principal.mensagem.setText(mensagem)

    motor = MotorTutorial({"caixa": janela}, passos_venda(janela.com_mesas), aviso=avisar, fim=roteiro.fim,
                          ao_encerrar=getattr(principal, "marcar_tutoriais", None),
                          avaliar=_avaliador(janela, janela.treino_banco, fechadas),
                          ao_concluir=lambda: Tutoriais(loja, operador_id).concluir("venda"))
    principal.tutorial = motor
    return motor
