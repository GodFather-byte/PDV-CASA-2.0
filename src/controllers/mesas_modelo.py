"""Modelo dos cartões de mesas, comandas, garotas e balcão do caixa (sem tela: a mesma lista alimenta o painel Qt)."""
from __future__ import annotations

from src.core import formatacao as fmt

ROTULOS_ESTADO = {"consumindo": "Aberta", "parada": "Sem movimento", "conta": "Aguard. acerto",
                  "balcao": "Venda de balcão", "garota": "Acerto pendente", "parcial": "Pago em parte",
                  "acerto": "Concluir acerto"}
ROTULOS_PILULA = {"consumindo": "Aberta", "parada": "Parada", "conta": "Acerto", "balcao": "Balcão",
                  "garota": "Comissão", "parcial": "Parcial", "acerto": "Concluir"}
ROTULOS_TIPO = {"balcao": "BALCÃO", "comanda": "COMANDA", "mesa": "MESA", "garota": "GAROTA"}
ABAS = (("Todas", "Todas"), ("Abertas", "Abertas"), ("Pago em parte", "Parciais"),
        ("Aguardando acerto", "Acerto"), ("Comissões", "Comissões"))      # (valor do filtro, rótulo curto da tela estreita)
GRUPOS_ABA = {"Abertas": {"consumindo", "parada"}, "Pago em parte": {"parcial"},
              "Aguardando acerto": {"conta", "acerto", "garota"}, "Comissões": {"garota"}}


def montar_tiles(mesas: list[dict], balcao: dict | None = None, garotas=()) -> list[dict]:
    """Modelo dos cartões: o balcão primeiro, depois as mesas e comandas (na ordem recebida) e, por fim, as garotas
    com comissão a pagar.

    `mesas` é o que `CaixaController.mesas()` devolve; `balcao`, a venda de balcão em andamento (ou None); `garotas`, uma
    lista de {'rotulo': a comanda da garota na notação da loja, 'total_cent': o que há a pagar a ela} (e, se houver, 'nome' e
    'marcacoes'). A garota que também tem consumo aberto na comanda não ganha um cartão à parte: o cartão da comanda leva o
    selo `garota` (o total a pagar). Se a comanda dela está aberta mas vazia (o operador só foi ver ou marcar a comissão), o
    cartão é o da garota, como seria fora dela. As chaves de identificação (`nome`, `pessoas`, `itens`, `marcacoes`) só
    existem quando há o que mostrar."""
    tiles = [{"chave": "0", "rotulo": "Balcão", "tipo": "balcao", "estado": "balcao",
              "total": fmt.fmt_num(balcao["total_cent"]) if balcao and balcao["total_cent"] else "", "minutos": 0}]
    a_pagar = {g["rotulo"]: g for g in garotas}
    for m in mesas:
        recebido = m.get("recebido_cent", 0)
        if m.get("prepago"):                 # pré-pago: o cliente ainda consome; o cartão mostra o saldo, não o "falta"
            estado = "conta" if m["status"] == "conta_enviada" else "parada" if m["inativa"] else "consumindo"
        elif recebido > 0 and recebido < m["total_cent"]:
            estado = "parcial"
        elif recebido > 0 and recebido >= m["total_cent"]:
            estado = "acerto"
        elif m["status"] == "conta_enviada":
            estado = "conta"
        elif m["inativa"]:
            estado = "parada"
        else:
            estado = "consumindo"
        tile = {"chave": m["rotulo"], "rotulo": m["rotulo"], "tipo": "comanda" if m["comanda"] else "mesa",
                "estado": estado, "total": fmt.fmt_num(m["total_cent"]), "minutos": m["minutos_parada"]}
        if m.get("prepago"):
            tile["saldo"] = fmt.fmt_num(recebido - m["total_cent"] + m.get("taxa_cent", 0))
        elif recebido > 0:
            tile["falta"] = fmt.fmt_num(max(0, m["total_cent"] - recebido))
        g = a_pagar.pop(m["rotulo"], None) if m["comanda"] else None
        if g is not None and m.get("n_itens", 1) == 0:
            tile.update(tipo="garota", estado="garota", total=fmt.fmt_num(g["total_cent"]), minutos=0)
            _identificar_garota(tile, g)
        else:
            if g is not None:
                tile["garota"] = fmt.fmt_num(g["total_cent"])
            for chave, valor in (("nome", (m.get("apelido") or m.get("cliente_nome") or "").strip()),
                                 ("pessoas", m.get("pessoas") or 0), ("itens", m.get("n_itens") or 0)):
                if valor:
                    tile[chave] = valor
        tiles.append(tile)
    for g in a_pagar.values():
        tile = {"chave": g["rotulo"], "rotulo": g["rotulo"], "tipo": "garota", "estado": "garota",
                "total": fmt.fmt_num(g["total_cent"]), "minutos": 0}
        _identificar_garota(tile, g)
        tiles.append(tile)
    return tiles


def _identificar_garota(tile: dict, g: dict) -> None:
    if g.get("nome"):
        tile["nome"] = g["nome"]
    if g.get("marcacoes"):
        tile["marcacoes"] = g["marcacoes"]


def idade(minutos: int) -> str:
    """'42 min' ou '1h52': há quanto tempo a posição está aberta sem lançamento."""
    if minutos < 1:
        return "agora"
    return f"{minutos} min" if minutos < 60 else f"{minutos // 60}h{minutos % 60:02d}"
