"""Junta o resumo do dia no banco do caixa, para o fechamento abrir o WhatsApp."""
from __future__ import annotations

import json

from src.core import formatacao as fmt
from src.whatsapp.resumo import abrir, numeros, texto_resumo


def _virada(banco) -> int:
    return min(max(banco.cfg_int("virada_dia_hora", 6), 0), 23)


def _vendas(banco, dia: str) -> list:
    virada = _virada(banco)
    inicio, fim = fmt.faixa_dia_operacional(dia, virada)
    return banco.todos(
        """SELECT v.id, v.status, v.total_cent, v.desconto_cent, v.servico_cent, v.fechada_em, v.garcom_id,
                  g.nome AS garcom
           FROM vendas v LEFT JOIN operadores g ON g.id = v.garcom_id
           WHERE v.status IN ('fechada', 'cancelada')
             AND COALESCE(v.fechada_em, v.ultimo_lancamento_em, v.aberta_em) >= ?
             AND COALESCE(v.fechada_em, v.ultimo_lancamento_em, v.aberta_em) < ?""",
        (inicio, fim))


def montar(banco, dia: str | None = None) -> dict:
    from src.controllers.config_controller import ConfigController
    virada = _virada(banco)
    dia = dia or fmt.dia_operacional(None, virada)
    anterior = fmt.somar_dias(dia, -7) if hasattr(fmt, "somar_dias") else _dia_menos(dia, 7)
    vendas = _vendas(banco, dia)
    semana = _vendas(banco, anterior)
    fechadas = [v for v in vendas if v["status"] == "fechada"]
    canceladas = [v for v in vendas if v["status"] == "cancelada"]
    bruto = sum(int(v["total_cent"] or 0) for v in fechadas)
    qtd = len(fechadas)
    formas: dict[str, int] = {}
    produtos: dict[str, dict] = {}
    garcons: dict[str, dict] = {}
    for v in fechadas:
        nome_g = (v["garcom"] or "").strip() or "Sem garçom"
        bloco = garcons.setdefault(nome_g, {"nome": nome_g, "faturamento_cent": 0, "quantidade": 0})
        bloco["faturamento_cent"] += int(v["total_cent"] or 0)
        bloco["quantidade"] += 1
        for p in banco.todos(
                """SELECT t.tipo, p.valor_cent, p.troco_cent FROM pagamentos_venda p
                   JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id WHERE p.venda_id = ?""", (v["id"],)):
            formas[p["tipo"]] = formas.get(p["tipo"], 0) + int(p["valor_cent"] or 0) - int(p["troco_cent"] or 0)
        for item in banco.todos(
                """SELECT h.nome, i.quantidade, i.total_cent FROM itens_venda i
                   JOIN produtos_historico h ON h.id = i.produto_id
                   WHERE i.venda_id = ? AND i.cancelado = 0""", (v["id"],)):
            prod = produtos.setdefault(item["nome"], {"nome": item["nome"], "quantidade": 0.0, "valor_cent": 0})
            prod["quantidade"] += float(item["quantidade"] or 0)
            prod["valor_cent"] += int(item["total_cent"] or 0)
    bruto_semana = sum(int(v["total_cent"] or 0) for v in semana if v["status"] == "fechada")
    inicio, _ = fmt.faixa_dia_operacional(dia, virada)
    sangrias = banco.valor(
        "SELECT COALESCE(SUM(valor_cent), 0) FROM movimentos_caixa WHERE tipo = 'saida' AND criado_em >= ?",
        (inicio,), 0)
    conferencias = _conferencias(banco, dia)
    config = ConfigController(banco)
    pct = banco.cfg("servico_pct") or "0"
    return {
        "loja": config.nome_loja() or "Loja",
        "periodo": f"Dia {dia[8:10]}/{dia[5:7]}/{dia[0:4]}",
        "vendas": {
            "faturamento_cent": bruto,
            "liquido_cent": bruto,
            "quantidade": qtd,
            "ticket_medio_cent": round(bruto / qtd) if qtd else 0,
            "desconto_cent": sum(int(v["desconto_cent"] or 0) for v in fechadas),
            "canceladas": len(canceladas),
            "canceladas_cent": sum(int(v["total_cent"] or 0) for v in canceladas),
        },
        "comparacao": {"rotulo": anterior, "faturamento_cent": bruto_semana},
        "servico_cent": sum(int(v["servico_cent"] or 0) for v in fechadas),
        "servico_pct": f"{pct}%",
        "garcons": sorted(garcons.values(), key=lambda g: -g["faturamento_cent"]),
        "produtos": sorted(produtos.values(), key=lambda p: -p["valor_cent"]),
        "formas": [{"tipo": t, "valor_cent": v} for t, v in sorted(formas.items(), key=lambda kv: -kv[1])],
        "sangrias_cent": int(sangrias or 0),
        "conferencias": conferencias,
        "perdas": perdas_recentes(banco),
    }


def _dia_menos(dia: str, dias: int) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(dia) - timedelta(days=dias)).isoformat()


def _conferencias(banco, dia: str) -> list[dict]:
    virada = _virada(banco)
    inicio, fim = fmt.faixa_dia_operacional(dia, virada)
    linhas = []
    for t in banco.todos(
            """SELECT t.id, t.numero, t.valor_final_cent, t.esperado_cent, t.resultado_cent, f.nome AS fechado_por
               FROM turnos t LEFT JOIN operadores f ON f.id = t.fechado_por
               WHERE t.status = 'fechado' AND t.fechado_em >= ? AND t.fechado_em < ?""",
            (inicio, fim)):
        formas = _formas_da_auditoria(banco, t["id"])
        linhas.append({
            "turno_numero": int(t["numero"]),
            "fechado_por": t["fechado_por"] or "",
            "esperado_cent": int(t["esperado_cent"] or 0),
            "informado_cent": int(t["valor_final_cent"] or 0),
            "diferenca_cent": int(t["resultado_cent"] or 0),
            "formas": formas,
        })
    return linhas


def _formas_da_auditoria(banco, turno_id: int) -> list[dict]:
    linha = banco.um(
        """SELECT depois FROM auditoria_eventos
           WHERE entidade = 'turnos' AND entidade_id = ? AND acao = 'fechamento_conferido'
           ORDER BY id DESC LIMIT 1""", (str(turno_id),))
    if not linha or not linha["depois"]:
        return []
    try:
        dados = json.loads(linha["depois"])
    except json.JSONDecodeError:
        return []
    resumo = dados.get("resumo") if isinstance(dados, dict) else None
    conf = (resumo or {}).get("conferencia_fechamento") if isinstance(resumo, dict) else None
    if not isinstance(conf, dict):
        return []
    saida = []
    for forma in conf.get("linhas") or []:
        if not isinstance(forma, dict):
            continue
        saida.append({
            "tipo": forma.get("tipo") or "",
            "esperado_cent": int(forma.get("esperado_cent") or 0),
            "informado_cent": forma.get("informado_cent"),
            "diferenca_cent": forma.get("diferenca_cent"),
        })
    return saida


def perdas_recentes(banco, limite: int = 15) -> list[dict]:
    """Falta na última contagem: unidade a menos vezes o último preço. Sobra não entra como perda."""
    itens = banco.todos(
        """SELECT p.nome, i.diferenca, p.ult_preco_cent, l.data
           FROM itens_estoque i
           JOIN lancamentos_estoque l ON l.id = i.lancamento_id
           JOIN produtos p ON p.id = i.produto_id
           WHERE l.tipo = 'contagem' AND i.diferenca < 0
           ORDER BY l.id DESC, i.id DESC LIMIT ?""", (limite,))
    return [{
        "nome": r["nome"],
        "unidades": abs(float(r["diferenca"] or 0)),
        "valor_cent": int(round(abs(float(r["diferenca"] or 0)) * int(r["ult_preco_cent"] or 0))),
        "data": r["data"],
    } for r in itens]


def enviar_no_fechamento(banco, abrir_url=None) -> str | None:
    """Monta o texto do dia e abre o WhatsApp de cada número. Sem número, não abre."""
    destino = numeros(banco.cfg("whatsapp_dono"))
    if not destino:
        return None
    texto = texto_resumo(montar(banco))
    abrir(destino, texto, abrir_url=abrir_url)
    return texto
