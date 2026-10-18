"""Fachada de relatórios (menu Relatórios) e painel da tela principal."""
from __future__ import annotations

from src.controllers.contas_controller import ContasController
from src.controllers.relatorio_comissoes import RelatoriosComissoes
from src.controllers.relatorio_gestao import RelatoriosGestao
from src.controllers.relatorio_vendas import RelatoriosVendas
from src.core import formatacao as fmt


class RelatorioController(RelatoriosVendas, RelatoriosGestao, RelatoriosComissoes):
    def __init__(self, banco):
        self.banco = banco

    def painel(self) -> dict:
        """Os números da tela principal: estoque, contas e vendas do dia."""
        b = self.banco
        r = b.um(
            """SELECT COUNT(*) AS total,
                      COALESCE(SUM(qt_atual <= 0), 0) AS sem,
                      COALESCE(SUM(qt_atual > 0 AND qt_atual <= estoque_minimo), 0) AS ponto,
                      COALESCE(SUM(qt_atual > 0 AND qt_atual > estoque_minimo), 0) AS normal
               FROM produtos WHERE controla_estoque = 1 AND ativo = 1""")
        # "Vendas do dia" é a noite inteira: com a virada às 6h, a venda das 2h ainda conta na noite que começou ontem.
        virada = b.cfg_int("virada_dia_hora", 6)
        v = b.um(
            """SELECT COUNT(*) AS n, COALESCE(SUM(total_cent), 0) AS total FROM vendas
               WHERE status = 'fechada' AND fechada_em >= ? AND fechada_em < ? AND subtotal_cent > 0""",
            fmt.faixa_dia_operacional(fmt.dia_operacional(virada=virada), virada))
        contas = ContasController(b).painel()
        return {
            "atualizado_em": fmt.agora(),
            "estoque_total": r["total"], "estoque_sem": r["sem"], "estoque_ponto": r["ponto"], "estoque_normal": r["normal"],
            "contas_anteriores": contas["anteriores"], "contas_hoje": contas["hoje"],
            "vendas_dia": v["n"], "vendas_total": v["total"], "venda_media": fmt.dividir_cent(v["total"], v["n"]),
            "ultimo_backup": b.cfg("ultimo_backup") or None,
        }
