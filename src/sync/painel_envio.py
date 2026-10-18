"""Painel do dono no celular: o que o PDV envia para a nuvem (opcional, Configurações > Nuvem > `painel_dono`).

A cada rodada da sincronização (`python -m src.app --sync`) o PDV manda, com o token da loja:
  * as vendas fechadas ou canceladas que ainda não subiram (`vendas.sincronizado = 0`), com itens e pagamentos, em lotes;
    a nuvem confirma os uuids recebidos e só então eles são marcados como enviados (cancelar uma venda já enviada zera a
    marca, e ela sobe de novo com o status novo);
  * um retrato do momento: turno aberto, estoque controlado (zerados e abaixo do mínimo), caderneta a receber e entregas
    pendentes. O retrato substitui o anterior na nuvem; é dele que o celular tira "atualizado às HH:MM".

Nada é apagado ou alterado no banco local além da marca de enviado. Sem rede, as vendas esperam a próxima rodada. O painel
mostra só o que já subiu: não é um espelho ao vivo do caixa.
"""
from __future__ import annotations

import logging

from src.core import formatacao as fmt
from src.core.posicao import nome as nome_posicao

log = logging.getLogger("pdv.painel")

LOTE = 200                    # vendas por envio: cabe numa chamada curta mesmo em rede ruim
LIMITE_ABAIXO_MINIMO = 50     # produtos listados no retrato (o resto vira só contagem)
CHAVE_ULTIMO_ENVIO = "painel_ultimo_envio"
CHAVE_ULTIMO_ERRO = "painel_ultimo_erro"


def ligado(banco) -> bool:
    """O envio só acontece com o painel ligado e a nuvem configurada (endereço e token)."""
    return (banco.cfg_bool("painel_dono", False) and bool(banco.cfg("api_url").strip())
            and bool(banco.cfg("api_token").strip()))


def url_envio(api_url: str) -> str:
    """O endereço configurado é o de envio antigo (.../v1/sincronizar); o do painel fica ao lado (.../v1/painel/envio)."""
    base = (api_url or "").strip().rstrip("/")
    if base.endswith("/v1/sincronizar"):
        base = base[: -len("/v1/sincronizar")]
    return f"{base}/v1/painel/envio"


def _virada(banco) -> int:
    return min(max(banco.cfg_int("virada_dia_hora", 6), 0), 23)


def _rotulo_posicao(v: dict, cliente: str | None) -> str:
    if v["modalidade"] == "mesa":
        return nome_posicao(v["comanda"], v["posicao"]) + (f" ({v['apelido']})" if v.get("apelido") else "")
    if v["modalidade"] == "entrega":
        return "Entrega" + (f" - {cliente}" if cliente else "")
    if v["modalidade"] == "caderneta":
        return "Caderneta" + (f" - {cliente}" if cliente else "")
    return "Balcão"


def pendentes(banco) -> int:
    return banco.valor("SELECT COUNT(*) FROM vendas WHERE status IN ('fechada','cancelada') AND sincronizado = 0", (), 0)


def coletar_vendas(banco, limite: int | None = None) -> list[dict]:
    """As vendas que faltam subir, da mais antiga para a mais nova, já no formato que a nuvem guarda."""
    limite = LOTE if limite is None else limite
    virada = _virada(banco)
    vendas = banco.todos(
        """SELECT v.*, o.nome AS operador, c.nome AS cliente, t.numero AS turno_numero
           FROM vendas v LEFT JOIN operadores o ON o.id = v.operador_id LEFT JOIN clientes c ON c.id = v.cliente_id
           LEFT JOIN turnos t ON t.id = v.turno_id
           WHERE v.status IN ('fechada','cancelada') AND v.sincronizado = 0 ORDER BY v.id LIMIT ?""", (limite,))
    saida = []
    for v in vendas:
        v = dict(v)
        itens = [dict(i) for i in banco.todos(
            """SELECT p.nome, p.codigo, u.abreviatura AS unidade, i.quantidade, i.preco_unit_cent, i.preco_base_cent,
                      i.total_cent, i.temperatura, i.cancelado, i.observacao
               FROM itens_venda i JOIN produtos_historico p ON p.id = i.produto_id JOIN unidades u ON u.id = p.unidade_id
               WHERE i.venda_id = ? ORDER BY i.id""", (v["id"],))]
        pagamentos = [dict(p) for p in banco.todos(
            """SELECT t.tipo, p.valor_cent, p.troco_cent FROM pagamentos_venda p
               JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id WHERE p.venda_id = ? ORDER BY p.id""", (v["id"],))]
        momento = v["fechada_em"] or v["ultimo_lancamento_em"] or v["aberta_em"]
        saida.append({
            "uuid": v["uuid"], "cupom": v["cupom"], "status": v["status"], "modalidade": v["modalidade"],
            "posicao_rotulo": _rotulo_posicao(v, v["cliente"]), "operador": v["operador"] or "",
            "turno_numero": v["turno_numero"], "terminal": v["terminal"],
            "aberta_em": v["aberta_em"], "fechada_em": momento, "dia": fmt.dia_operacional(momento, virada),
            "subtotal_cent": v["subtotal_cent"], "desconto_cent": v["desconto_cent"], "servico_cent": v["servico_cent"],
            "taxa_cent": v["taxa_cent"], "acrescimo_cent": v["acrescimo_cent"], "total_cent": v["total_cent"],
            "pago_cent": v["pago_cent"], "troco_cent": v["troco_cent"], "pessoas": v["pessoas"],
            "motivo_cancelamento": v["motivo_cancelamento"] or "", "itens": itens, "pagamentos": pagamentos,
        })
    return saida


def retrato(banco) -> dict:
    """O momento da loja: caixa, estoque, caderneta e entregas. Tudo em centavos e quantidades como estão no banco."""
    from src.controllers.turno_controller import TurnoController
    turnos = TurnoController(banco)
    turno = turnos.atual()
    caixa = None
    if turno is not None:
        r = turnos.resumo(turno["id"])
        caixa = {
            "turno_numero": turno["numero"], "operador": banco.valor(
                "SELECT nome FROM operadores WHERE id = ?", (turno["operador_id"],)) or "",
            "aberto_em": turno["aberto_em"], "valor_inicial_cent": turno["valor_inicial_cent"],
            "recebido_cent": r["total_recebido"], "esperado_gaveta_cent": r["esperado"],
            "sangrias_cent": r["saidas"], "suprimentos_cent": r["entradas"], "tc": r["tc"], "tm_cent": r["tm"],
            "cancelamentos": len(r.get("cupons_cancelados") or []),
            "recebimentos": [{"tipo": x["tipo"], "valor_cent": x["valor"]} for x in r["recebimentos"]],
        }
    abaixo = [dict(p) for p in banco.todos(
        """SELECT p.codigo, p.nome, p.qt_atual, p.estoque_minimo, u.abreviatura AS unidade
           FROM produtos p JOIN unidades u ON u.id = p.unidade_id
           WHERE p.ativo = 1 AND p.controla_estoque = 1 AND p.qt_atual <= p.estoque_minimo
           ORDER BY (p.qt_atual <= 0) DESC, p.nome LIMIT ?""", (LIMITE_ABAIXO_MINIMO,))]
    for p in abaixo:
        p["codigo"] = p["codigo"].lstrip("0") or "0"
    estoque = {
        "controlados": banco.valor("SELECT COUNT(*) FROM produtos WHERE ativo = 1 AND controla_estoque = 1", (), 0),
        "zerados": banco.valor(
            "SELECT COUNT(*) FROM produtos WHERE ativo = 1 AND controla_estoque = 1 AND qt_atual <= 0", (), 0),
        "abaixo_minimo_total": banco.valor(
            "SELECT COUNT(*) FROM produtos WHERE ativo = 1 AND controla_estoque = 1 AND qt_atual <= estoque_minimo", (), 0),
        "abaixo_minimo": abaixo,
    }
    devedores = banco.um("SELECT COUNT(*) AS n, COALESCE(SUM(-saldo_cent), 0) AS total FROM clientes WHERE saldo_cent < 0")
    from src.controllers.config_controller import ConfigController
    return {
        "loja_nome": ConfigController(banco).nome_loja(), "virada_dia_hora": _virada(banco),
        "dia_operacional": fmt.dia_operacional(None, _virada(banco)), "momento": fmt.agora(),
        "caixa": caixa, "estoque": estoque,
        "caderneta": {"a_receber_cent": int(devedores["total"]), "clientes_devendo": int(devedores["n"])},
        "entregas_pendentes": banco.valor(
            "SELECT COUNT(*) FROM vendas WHERE modalidade = 'entrega' AND status IN ('aberta','conta_enviada')", (), 0),
        "vendas_pendentes_envio": pendentes(banco),
    }


def marcar_enviadas(banco, uuids: list[str]) -> int:
    if not uuids:
        return 0
    marcas = ",".join("?" * len(uuids))
    with banco.transacao():
        banco.executar(f"UPDATE vendas SET sincronizado = 1 WHERE uuid IN ({marcas}) AND status IN ('fechada','cancelada')",
                       tuple(uuids))
    return len(uuids)


def enviar(banco, http=None) -> dict | None:
    """Uma rodada de envio. Devolve {"vendas": n, "lotes": n} ou None quando o painel está desligado.
    Lança exceção se a nuvem não respondeu 200 (a sincronização registra e tenta de novo)."""
    if not ligado(banco):
        return None
    if http is None:
        import requests as http
    url = url_envio(banco.cfg("api_url"))
    cabecalhos = {"Authorization": f"Bearer {banco.cfg('api_token').strip()}"}
    enviadas = lotes = 0
    while True:
        vendas = coletar_vendas(banco)
        corpo = {"vendas": vendas, "retrato": retrato(banco), "enviado_em": fmt.agora()}
        try:
            r = http.post(url, json=corpo, headers=cabecalhos, timeout=(5, 30))
        except OSError as e:
            banco.cfg_set(CHAVE_ULTIMO_ERRO, f"{fmt.agora()} sem conexão: {e}"[:200])
            raise
        if r.status_code != 200:
            banco.cfg_set(CHAVE_ULTIMO_ERRO, f"{fmt.agora()} HTTP {r.status_code}"[:200])
            raise RuntimeError(f"Painel do dono: a nuvem respondeu HTTP {r.status_code}.")
        resposta = r.json()
        confirmados = [u for u in (resposta.get("uuids") or []) if isinstance(u, str)]
        enviadas += marcar_enviadas(banco, confirmados)
        lotes += 1
        banco.cfg_set(CHAVE_ULTIMO_ENVIO, fmt.agora())
        banco.cfg_set(CHAVE_ULTIMO_ERRO, "")
        if len(vendas) < LOTE or not confirmados:
            break
    if enviadas:
        log.info("Painel do dono: %d venda(s) enviada(s) em %d lote(s).", enviadas, lotes)
    return {"vendas": enviadas, "lotes": lotes}
