"""Devoluções imutáveis para a nuvem, identificadas por UUID e pela data do reembolso."""
from src.core import formatacao as fmt
from src.controllers.custos_venda import parcela


def pendentes(banco) -> int:
    return banco.valor("SELECT COUNT(*) FROM devolucoes d WHERE NOT EXISTS "
                       "(SELECT 1 FROM painel_devolucoes_enviadas e WHERE e.uuid = d.uuid)", (), 0)


def coletar(banco, limite: int = 200) -> list[dict]:
    saida = []
    with banco.transacao():
        for d in banco.todos("SELECT d.* FROM devolucoes d WHERE NOT EXISTS "
                             "(SELECT 1 FROM painel_devolucoes_enviadas e WHERE e.uuid = d.uuid) "
                             "ORDER BY d.id LIMIT ?", (limite,)):
            itens = []
            completo = True
            for i in banco.todos(
                    """SELECT di.*, i.quantidade AS vendida, i.comissao_cent, c.custo_cent, c.recuperavel,
                       (SELECT COALESCE(SUM(a.quantidade),0) FROM devolucoes_itens a
                        WHERE a.item_id = di.item_id AND a.id < di.id) AS anterior
                       FROM devolucoes_itens di JOIN itens_venda i ON i.id = di.item_id
                       LEFT JOIN itens_venda_custos c ON c.item_id = di.item_id WHERE di.devolucao_id = ? ORDER BY di.id""", (d["id"],)):
                custo = parcela(i["custo_cent"], i["anterior"], i["quantidade"], i["vendida"]) \
                    if i["custo_cent"] is not None else None
                completo = completo and custo is not None
                itens.append({"item_id": i["item_id"], "quantidade": i["quantidade"],
                              "retorna_estoque": bool(i["retorna_estoque"]),
                              "custo_recuperado_cent": (custo if i["recuperavel"] != 0 else 0) if i["retorna_estoque"] else 0,
                              "comissao_ajuste_cent": parcela(i["comissao_cent"], i["anterior"], i["quantidade"], i["vendida"])})
            saida.append({"uuid": d["uuid"], "venda_uuid": d["venda_uuid"], "cupom_original": d["cupom_original"],
                          "criado_em": d["criado_em"], "dia": fmt.dia_operacional(d["criado_em"], banco.cfg_int("virada_dia_hora", 6)),
                          "valor_cent": d["valor_cent"], "modo": d["reembolso_modo"], "troca": bool(d["troca"]),
                          "custo_completo": completo, "itens": itens})
    return saida


def confirmar(banco, enviados: list[dict], confirmados: list[str]) -> int:
    permitidos = {d["uuid"] for d in enviados}
    n = 0
    with banco.transacao():
        for uid in set(u for u in confirmados if isinstance(u, str)) & permitidos:
            n += banco.executar("INSERT OR IGNORE INTO painel_devolucoes_enviadas(uuid, enviado_em) VALUES (?,?)",
                                (uid, fmt.agora())).rowcount
    return n
