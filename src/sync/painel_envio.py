"""Painel do dono no celular: o que o PDV envia para a nuvem (opcional, Configurações > Nuvem > `painel_dono`).

A cada rodada da sincronização (`python -m src.app --sync`) o PDV manda, com o token da loja:
  * as vendas fechadas ou canceladas que ainda não subiram (`vendas.sincronizado = 0`), com itens e pagamentos, em lotes;
    a nuvem confirma os uuids recebidos e só então eles são marcados como enviados (cancelar uma venda já enviada zera a
    marca, e ela sobe de novo com o status novo);
  * um retrato do momento: turno aberto, estoque controlado (zerados e abaixo do mínimo), caderneta a receber, entregas
    pendentes, comandas abertas (com a marca de comissão lançada), comissões das garotas dos últimos 30 dias,
    fechamentos e sangrias dos últimos 31 dias e o faturamento dos últimos 12 meses. O retrato substitui o anterior
    DESTE caixa na nuvem; é dele que o celular tira "atualizado às HH:MM". O faturamento mensal vai no retrato porque
    a nuvem não guarda as vendas por mais de cerca de 120 dias.

Cada caixa tem o seu banco, então se identifica (`id_do_caixa`): numa loja com dois caixas a nuvem guarda um retrato de
cada um, em vez de o último a falar apagar o do outro.

Nada é apagado ou alterado no banco local além da marca de enviado. Sem rede, as vendas esperam a próxima rodada. O painel
mostra só o que já subiu: não é um espelho ao vivo do caixa.

Também daqui sai a troca da senha do painel pelo próprio PDV (`trocar_senha`): o dono não depende do fornecedor.
"""
from __future__ import annotations

import logging
import json
import socket
from uuid import uuid4

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.core.posicao import nome as nome_posicao
from src.sync import devolucoes_envio

log = logging.getLogger("pdv.painel")

LOTE = 200                    # vendas por envio: cabe numa chamada curta mesmo em rede ruim
LIMITE_ABAIXO_MINIMO = 50     # produtos listados no retrato (o resto vira só contagem)
LIMITE_COMANDAS = 80          # comandas abertas no retrato; o resto não cabe numa chamada curta
LIMITE_COMISSOES = 300        # lançamentos de comissão dos últimos 30 dias
LIMITE_FECHAMENTOS = 40
LIMITE_SANGRIAS = 200
DIAS_COMISSAO = 30
DIAS_MOVIMENTO = 31           # fechamentos e sangrias: um mês, com folga para a virada do dia
MESES_FATURAMENTO = 12
CHAVE_ULTIMO_ENVIO = "painel_ultimo_envio"
CHAVE_ULTIMO_ERRO = "painel_ultimo_erro"
CHAVE_CAIXA_ID = "painel_caixa_id"
CHAVE_CAIXA_COMPUTADOR = "painel_caixa_computador"
SENHA_MINIMA = 8                # as mesmas regras da nuvem (backend/painel.py: validar_senha)
SENHA_MAXIMA = 128


def ligado(banco) -> bool:
    """O envio só acontece com o painel ligado e a nuvem configurada (endereço e token)."""
    return (banco.cfg_bool("painel_dono", False) and bool(banco.cfg("api_url").strip())
            and bool(banco.cfg("api_token").strip()))


def _base_nuvem(api_url: str) -> str:
    """O endereço configurado é o de envio antigo (.../v1/sincronizar); os do painel ficam ao lado (.../v1/painel/...)."""
    base = (api_url or "").strip().rstrip("/")
    if base.endswith("/v1/sincronizar"):
        base = base[: -len("/v1/sincronizar")]
    return base


def url_envio(api_url: str) -> str:
    return f"{_base_nuvem(api_url)}/v1/painel/envio"


def url_senha(api_url: str) -> str:
    return f"{_base_nuvem(api_url)}/v1/painel/senha"


def id_do_caixa(banco) -> str:
    """Identidade deste caixa na nuvem, para dois caixas da mesma loja não se sobrescreverem. Nasce na primeira vez e fica no
    banco. Se o banco foi copiado para outro computador (nome diferente), o computador novo ganha o id dele: sem isso a
    cópia e o original dividiriam o mesmo retrato."""
    computador = socket.gethostname()
    atual = banco.cfg(CHAVE_CAIXA_ID).strip()
    if not atual or banco.cfg(CHAVE_CAIXA_COMPUTADOR).strip() != computador:
        atual = uuid4().hex[:16]
        with banco.transacao():
            banco.cfg_set(CHAVE_CAIXA_ID, atual)
            banco.cfg_set(CHAVE_CAIXA_COMPUTADOR, computador)
    return atual


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


def coletar_vendas(banco, limite: int | None = None, *, uuids: list[str] | None = None) -> list[dict]:
    """As vendas que faltam subir, da mais antiga para a mais nova, já no formato que a nuvem guarda."""
    # Venda, itens e pagamentos precisam pertencer ao mesmo instante. A rede fica fora desta transação curta.
    with banco.transacao():
        return _coletar_vendas(banco, limite, uuids)


def _coletar_vendas(banco, limite: int | None, uuids: list[str] | None) -> list[dict]:
    limite = LOTE if limite is None else limite
    if uuids is not None and not uuids:
        return []
    filtro = "" if uuids is None else f" AND v.uuid IN ({','.join('?' for _ in uuids)})"
    virada = _virada(banco)
    caixa_id = id_do_caixa(banco)
    vendas = banco.todos(
        """SELECT v.*, o.nome AS operador, g.nome AS garcom, x.nome AS cancelada_por_nome, c.nome AS cliente,
                  t.numero AS turno_numero
           FROM vendas v LEFT JOIN operadores o ON o.id = v.operador_id
           LEFT JOIN operadores g ON g.id = v.garcom_id LEFT JOIN operadores x ON x.id = v.cancelada_por
           LEFT JOIN clientes c ON c.id = v.cliente_id LEFT JOIN turnos t ON t.id = v.turno_id
           WHERE v.status IN ('fechada','cancelada') AND v.sincronizado = 0""" + filtro + " ORDER BY v.id LIMIT ?",
        (*(() if uuids is None else uuids), limite))
    saida = []
    for v in vendas:
        v = dict(v)
        itens = [dict(i) for i in banco.todos(
            """SELECT p.nome, p.codigo, u.abreviatura AS unidade, i.quantidade, i.preco_unit_cent, i.preco_base_cent,
                      i.total_cent, i.temperatura, i.cancelado, i.observacao, i.comissao_cent,
                      gr.nome AS grupo, COALESCE(st.nome, '') AS setor, p.custo_cent AS custo_unit_cent
               FROM itens_venda i JOIN produtos_historico p ON p.id = i.produto_id
               JOIN unidades u ON u.id = p.unidade_id JOIN subgrupos s ON s.id = p.subgrupo_id
               JOIN grupos gr ON gr.id = s.grupo_id LEFT JOIN setores_impressao st ON st.id = s.setor_impressao_id
               WHERE i.venda_id = ? ORDER BY i.id""", (v["id"],))]
        pagamentos = [dict(p) for p in banco.todos(
            """SELECT t.tipo, p.valor_cent, p.troco_cent FROM pagamentos_venda p
               JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id WHERE p.venda_id = ? ORDER BY p.id""", (v["id"],))]
        momento = v["fechada_em"] or v["ultimo_lancamento_em"] or v["aberta_em"]
        saida.append({
            "uuid": v["uuid"], "cupom": v["cupom"], "status": v["status"], "modalidade": v["modalidade"],
            "posicao_rotulo": _rotulo_posicao(v, v["cliente"]), "operador": v["operador"] or "",
            "garcom": v["garcom"] or "", "cancelada_por": v["cancelada_por_nome"] or "",
            "turno_numero": v["turno_numero"], "terminal": v["terminal"], "terminal_id": caixa_id,
            "aberta_em": v["aberta_em"], "fechada_em": momento, "dia": fmt.dia_operacional(momento, virada),
            "subtotal_cent": v["subtotal_cent"], "desconto_cent": v["desconto_cent"], "servico_cent": v["servico_cent"],
            "taxa_cent": v["taxa_cent"], "acrescimo_cent": v["acrescimo_cent"], "total_cent": v["total_cent"],
            "pago_cent": v["pago_cent"], "troco_cent": v["troco_cent"], "pessoas": v["pessoas"],
            "motivo_cancelamento": v["motivo_cancelamento"] or "", "itens": itens, "pagamentos": pagamentos,
        })
    return saida


def _dia_inicio(hoje: str, dias: int) -> str:
    """O primeiro dia operacional de uma janela que termina em `hoje` (inclusive)."""
    from datetime import date, timedelta
    return (date.fromisoformat(hoje) - timedelta(days=dias - 1)).isoformat()


def _meses_fechados(banco, virada: int, hoje: str) -> list[dict]:
    """Faturamento das vendas fechadas, mês a mês, nos últimos 12 meses operacionais.

    A nuvem apaga a venda depois da retenção (cerca de 120 dias). Sem este resumo o gráfico anual
    do celular ficaria pela metade. Cada mês entra mesmo zerado, para o gráfico ter as doze barras."""
    from datetime import date
    fim = date.fromisoformat(hoje)
    ano, mes = fim.year, fim.month
    for _ in range(MESES_FATURAMENTO - 1):
        mes -= 1
        if mes == 0:
            mes, ano = 12, ano - 1
    inicio = date(ano, mes, 1).isoformat()
    linhas = banco.todos(
        """SELECT strftime('%Y-%m', datetime(fechada_em, ?)) AS mes,
                  COUNT(*) AS quantidade, COALESCE(SUM(total_cent), 0) AS faturamento_cent
           FROM vendas WHERE status = 'fechada' AND fechada_em >= ? GROUP BY mes""",
        (f"-{int(virada)} hours", f"{inicio} 00:00:00"))
    por_mes = {r["mes"]: r for r in linhas}
    saida = []
    for _ in range(MESES_FATURAMENTO):
        chave = f"{ano:04d}-{mes:02d}"
        r = por_mes.get(chave)
        saida.append({
            "mes": chave,
            "faturamento_cent": int(r["faturamento_cent"]) if r else 0,
            "quantidade": int(r["quantidade"]) if r else 0,
        })
        mes += 1
        if mes == 13:
            mes, ano = 1, ano + 1
    return saida


def _modulos(banco) -> dict:
    """O que a casa usa. O painel esconde garota e portaria quando o flag vem desligado."""
    def pct(chave: str) -> float:
        try:
            return float(str(banco.cfg(chave, "0")).replace(",", "."))
        except ValueError:
            return 0.0
    return {
        "usar_mesas": banco.cfg_bool("usar_mesas", True),
        "usar_garotas": banco.cfg_bool("usar_garotas", True),
        "usar_portaria": banco.cfg_bool("usar_portaria", True),
        "usar_cozinha_bar": banco.cfg_bool("usar_cozinha_bar", False),
        "servico_pct": pct("servico_pct"),
        "comissao_garcom_pct": pct("comissao_garcom_pct"),
    }


def _comandas_abertas(banco) -> list[dict]:
    """Mesas e comandas abertas. O valor é o da portaria. `garota` só na comanda com comissão pendente.
    Cada uma leva garçom, pessoas e os itens (nome e valor, sem custo)."""
    from src.porteiro.consulta import retrato as retrato_portaria
    extras = {}
    for r in banco.todos(
            """SELECT v.comanda, v.posicao, v.pessoas, COALESCE(g.nome, '') AS garcom
               FROM vendas v LEFT JOIN operadores g ON g.id = v.garcom_id
               WHERE v.modalidade = 'mesa' AND v.status IN ('aberta', 'conta_enviada')"""):
        extras[(int(r["comanda"] or 0), int(r["posicao"]))] = dict(r)
    saida = []
    for p in retrato_portaria(banco).get("posicoes") or []:
        comanda = bool(p.get("comanda"))
        numero = int(p["numero"])
        extra = extras.get((1 if comanda else 0, numero), {})
        itens = []
        for i in (p.get("itens") or [])[:8]:
            if not isinstance(i, dict):
                continue
            itens.append({"nome": str(i.get("nome") or "")[:60], "quantidade": i.get("quantidade"),
                          "total_cent": int(i.get("total_cent") or 0)})
        saida.append({
            "numero": numero, "comanda": comanda,
            "rotulo": p.get("rotulo") or str(numero),
            "devido_cent": int(p.get("devido_cent") or 0),
            "total_cent": int(p.get("total_cent") or 0),
            "pago_cent": int(p.get("pago_cent") or 0),
            "aberta_em": (p.get("aberta_em") or "")[:19],
            "aberta_txt": p.get("aberta_txt") or "",
            "garota": bool(p.get("garota")),
            "situacao": p.get("situacao") or "",
            "garcom": extra.get("garcom") or "",
            "pessoas": int(extra.get("pessoas") or 0),
            "itens": itens,
        })
    saida.sort(key=lambda c: (0 if c["situacao"] == "devendo" else 1, 0 if not c["comanda"] else 1, c["numero"]))
    return saida[:LIMITE_COMANDAS]


def _comissoes(banco, virada: int, hoje: str) -> dict:
    """Lançamentos pendentes e pagos da janela (o celular filtra hoje, 7 e 30 dias) e o total ainda a pagar."""
    inicio, _ = fmt.faixa_dia_operacional(_dia_inicio(hoje, DIAS_COMISSAO), virada)
    linhas = []
    for r in banco.todos(
            """SELECT c.garota, COALESCE(g.nome, '') AS nome, c.valor_cent, c.status, c.criado_em
               FROM comissoes_garotas c LEFT JOIN garotas g ON g.numero = c.garota
               WHERE c.status IN ('pendente', 'paga') AND c.criado_em >= ?
               ORDER BY c.criado_em DESC, c.id DESC LIMIT ?""", (inicio, LIMITE_COMISSOES)):
        linhas.append({
            "garota": int(r["garota"]), "nome": r["nome"] or "", "valor_cent": int(r["valor_cent"]),
            "status": r["status"], "criado_em": (r["criado_em"] or "")[:19],
            "dia": fmt.dia_operacional(r["criado_em"], virada),
        })
    pendente = banco.valor(
        "SELECT COALESCE(SUM(valor_cent), 0) FROM comissoes_garotas WHERE status = 'pendente'", (), 0)
    return {"linhas": linhas, "pendente_total_cent": int(pendente)}


def _fechamentos_e_sangrias(banco, virada: int, hoje: str) -> tuple[list[dict], list[dict]]:
    """Fechamentos de turno e sangrias (só saída) da janela. Suprimento entra no fechamento, não na lista de sangrias."""
    inicio, _ = fmt.faixa_dia_operacional(_dia_inicio(hoje, DIAS_MOVIMENTO), virada)
    fechamentos = []
    for t in banco.todos(
            """SELECT t.id, t.numero, t.aberto_em, t.fechado_em, t.valor_inicial_cent, t.valor_final_cent,
                      t.esperado_cent, t.resultado_cent, o.nome AS operador,
                      (SELECT COALESCE(SUM(valor_cent), 0) FROM movimentos_caixa m
                       WHERE m.turno_id = t.id AND m.tipo = 'saida') AS sangrias_cent,
                      (SELECT COALESCE(SUM(valor_cent), 0) FROM movimentos_caixa m
                       WHERE m.turno_id = t.id AND m.tipo = 'entrada') AS suprimentos_cent
               FROM turnos t LEFT JOIN operadores o ON o.id = t.operador_id
               WHERE t.status = 'fechado' AND t.fechado_em >= ?
               ORDER BY t.fechado_em DESC LIMIT ?""", (inicio, LIMITE_FECHAMENTOS)):
        from src.whatsapp.caixa import _formas_da_auditoria
        fechamentos.append({
            "turno_numero": int(t["numero"]), "operador": t["operador"] or "",
            "aberto_em": (t["aberto_em"] or "")[:19], "fechado_em": (t["fechado_em"] or "")[:19],
            "dia": fmt.dia_operacional(t["fechado_em"], virada),
            "valor_inicial_cent": int(t["valor_inicial_cent"] or 0),
            "valor_final_cent": int(t["valor_final_cent"] or 0),
            "esperado_cent": int(t["esperado_cent"] or 0),
            "resultado_cent": int(t["resultado_cent"] or 0),
            "sangrias_cent": int(t["sangrias_cent"] or 0),
            "suprimentos_cent": int(t["suprimentos_cent"] or 0),
            "formas": _formas_da_auditoria(banco, t["id"]),
        })
    sangrias = []
    for m in banco.todos(
            """SELECT m.valor_cent, m.descricao, m.criado_em, o.nome AS operador, t.numero AS turno_numero
               FROM movimentos_caixa m JOIN turnos t ON t.id = m.turno_id
               LEFT JOIN operadores o ON o.id = m.operador_id
               WHERE m.tipo = 'saida' AND m.criado_em >= ?
               ORDER BY m.criado_em DESC LIMIT ?""", (inicio, LIMITE_SANGRIAS)):
        sangrias.append({
            "valor_cent": int(m["valor_cent"]), "descricao": m["descricao"] or "",
            "criado_em": (m["criado_em"] or "")[:19], "dia": fmt.dia_operacional(m["criado_em"], virada),
            "operador": m["operador"] or "", "turno_numero": int(m["turno_numero"]),
        })
    return fechamentos, sangrias


def _whatsapp(banco) -> dict:
    from src.whatsapp.resumo import numeros
    return {
        "numeros": numeros(banco.cfg("whatsapp_dono")),
        "cancelamento_cent": banco.cfg_int("whatsapp_alerta_cancelamento_cent", 5000),
        "desconto_cent": banco.cfg_int("whatsapp_alerta_desconto_cent", 5000),
        "sangria_cent": banco.cfg_int("whatsapp_alerta_sangria_cent", 20000),
        "mesa_horas": banco.cfg_int("whatsapp_mesa_horas", 4),
        "expediente_de": (banco.cfg("sync_expediente_de") or "").strip(),
        "expediente_ate": (banco.cfg("sync_expediente_ate") or "").strip(),
    }


def _perdas(banco) -> list[dict]:
    from src.whatsapp.caixa import perdas_recentes
    return perdas_recentes(banco)


def retrato(banco) -> dict:
    """O momento da loja: caixa, estoque, caderneta, entregas, comandas, comissões e o movimento do caixa.
    Tudo em centavos e quantidades como estão no banco."""
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
    config = ConfigController(banco)
    maquina = config.maquina()
    virada = _virada(banco)
    hoje = fmt.dia_operacional(None, virada)
    fechamentos, sangrias = _fechamentos_e_sangrias(banco, virada, hoje)
    return {
        "loja_nome": config.nome_loja(), "virada_dia_hora": virada,
        "terminal_id": id_do_caixa(banco), "terminal": turnos.terminal,
        "terminal_rotulo": (maquina.get("descricao") or "").strip() or f"Caixa {turnos.terminal}",
        "terminal_computador": (maquina.get("nome_computador") or "").strip() or socket.gethostname(),
        "dia_operacional": hoje, "momento": fmt.agora(),
        "atualizacao_seg": 60,
        "devolucoes_suportadas": True, "devolucoes_pendentes_envio": devolucoes_envio.pendentes(banco),
        "caixa": caixa, "estoque": estoque,
        "caderneta": {"a_receber_cent": int(devedores["total"]), "clientes_devendo": int(devedores["n"])},
        "entregas_pendentes": banco.valor(
            "SELECT COUNT(*) FROM vendas WHERE modalidade = 'entrega' AND status IN ('aberta','conta_enviada')", (), 0),
        "vendas_pendentes_envio": pendentes(banco),
        "modulos": _modulos(banco),
        "comandas": _comandas_abertas(banco),
        "comissoes": _comissoes(banco, virada, hoje),
        "fechamentos": fechamentos, "sangrias": sangrias,
        "perdas": _perdas(banco),
        "whatsapp": _whatsapp(banco),
        "faturamento_meses": _meses_fechados(banco, virada, hoje),
    }


def marcar_enviadas(banco, vendas: list[dict]) -> int:
    """Confirma somente retratos ainda iguais aos enviados; uma alteração durante o HTTP continua pendente."""
    if not vendas:
        return 0
    enviadas = {v["uuid"]: v for v in vendas}
    marcadas = 0
    with banco.transacao():
        atuais = coletar_vendas(banco, limite=len(enviadas), uuids=list(enviadas))
        for atual in atuais:
            if atual == enviadas[atual["uuid"]]:
                marcadas += banco.executar("UPDATE vendas SET sincronizado = 1 WHERE uuid = ? AND sincronizado = 0",
                                           (atual["uuid"],)).rowcount
    return marcadas


_FOTO_PADRAO = object()


def _postar(banco, corpo: dict, http=None) -> dict:
    if http is None:
        import requests as http
    r = None
    try:
        r = http.post(url_envio(banco.cfg("api_url")), json=corpo,
                      headers={"Authorization": f"Bearer {banco.cfg('api_token').strip()}"}, timeout=(5, 30))
        if r.status_code != 200:
            raise RuntimeError(f"Painel do dono: a nuvem respondeu HTTP {r.status_code}.")
        dados = r.json()
        if not isinstance(dados, dict):
            raise ValueError("Resposta do painel inválida.")
        return dados
    except Exception:
        # Mensagem persistida sem URL, token ou conteúdo da exceção de rede.
        codigo = getattr(r, "status_code", None)
        http_erro = f" HTTP {codigo}" if type(codigo) is int else ""
        banco.cfg_set(CHAVE_ULTIMO_ERRO, f"{fmt.agora()}{http_erro} envio não confirmado; confira a conexão e o log.")
        raise


def confirmar_sucesso(banco) -> None:
    banco.cfg_set(CHAVE_ULTIMO_ENVIO, fmt.agora())
    banco.cfg_set(CHAVE_ULTIMO_ERRO, "")


def enviar(banco, http=None, *, foto=_FOTO_PADRAO) -> dict | None:
    """Uma rodada de envio. Devolve {"vendas": n, "lotes": n} ou None quando o painel está desligado.
    Lança exceção se a nuvem não respondeu 200 (a sincronização registra e tenta de novo)."""
    if not ligado(banco):
        return None
    foto = retrato(banco) if foto is _FOTO_PADRAO else foto
    enviadas = lotes = 0
    while True:
        vendas = coletar_vendas(banco)
        retornos = devolucoes_envio.coletar(banco, LOTE)
        corpo = {"vendas": vendas, "devolucoes": retornos, "enviado_em": fmt.agora()}
        if foto is not None:
            corpo["retrato"] = foto
        resposta = _postar(banco, corpo, http)
        confirmados = {u for u in (resposta.get("uuids") or []) if isinstance(u, str)}
        marcadas = marcar_enviadas(banco, [v for v in vendas if v["uuid"] in confirmados])
        enviadas += marcadas
        devolvidas = devolucoes_envio.confirmar(banco, retornos, resposta.get("devolucoes_uuids") or [])
        lotes += 1
        if retornos and not devolvidas:
            banco.cfg_set(CHAVE_ULTIMO_ERRO, f"{fmt.agora()} devoluções não confirmadas; atualize a nuvem.")
            raise RuntimeError("A nuvem não confirmou as devoluções; permanecem na fila local.")
        confirmar_sucesso(banco)
        foto = None                    # os lotes seguintes levam apenas as vendas e devoluções pendentes
        if (len(vendas) < LOTE and len(retornos) < LOTE) or not (marcadas or devolvidas) \
                or not (pendentes(banco) or devolucoes_envio.pendentes(banco)):
            break
    if enviadas:
        log.info("Painel do dono: %d venda(s) enviada(s) em %d lote(s).", enviadas, lotes)
    return {"vendas": enviadas, "lotes": lotes}


# ------------------------------------------------------------------ senha do painel
def validar_senha(senha: str) -> str:
    """As regras da nuvem (backend/painel.py), conferidas antes para o operador ver o erro sem esperar a rede."""
    senha = (senha or "").strip()
    if len(senha) < SENHA_MINIMA:
        raise ErroNegocio(f"A senha do painel precisa ter pelo menos {SENHA_MINIMA} caracteres.")
    if len(senha) > SENHA_MAXIMA:
        raise ErroNegocio("A senha do painel é longa demais.")
    return senha


def _detalhe(resposta) -> str:
    try:
        detalhe = resposta.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    return detalhe.strip() if isinstance(detalhe, str) else ""


def trocar_senha_na_nuvem(url_api: str, token: str, senha: str | None = None, http=None, timeout=(5, 30)) -> str | None:
    """Troca a senha do painel do dono, com o token DA LOJA (o administrador da nuvem não é preciso). Sem `senha` a nuvem gera
    uma e ela volta aqui (aparece só agora); com `senha` devolve None. As sessões abertas no celular caem: o dono entra de
    novo. Não toca no banco local, então pode rodar fora da thread da tela. Levanta ErroNegocio com a mensagem pronta para o
    operador (a senha só muda quando a nuvem responde 200)."""
    senha = validar_senha(senha) if (senha or "").strip() else None
    if not (url_api or "").strip() or not (token or "").strip():
        raise ErroNegocio("Preencha o endereço da nuvem e o token da API em Configurações > Nuvem antes de trocar a senha do painel.")
    if http is None:
        import requests as http
    try:
        r = http.post(url_senha(url_api), json={"senha": senha} if senha else {},
                      headers={"Authorization": f"Bearer {token.strip()}"}, timeout=timeout)
    except OSError as e:
        raise ErroNegocio("Sem conexão com a nuvem: a senha NÃO foi trocada. Confira a internet e o endereço em "
                          "Configurações > Nuvem.") from e
    if r.status_code != 200:
        detalhe = _detalhe(r)
        if r.status_code == 401:
            raise ErroNegocio("A nuvem não reconheceu o token da API: a senha NÃO foi trocada. Confira o token em "
                              "Configurações > Nuvem.")
        if r.status_code in (403, 422) and detalhe:
            raise ErroNegocio(f"{detalhe} A senha NÃO foi trocada.")
        raise ErroNegocio(f"A nuvem respondeu HTTP {r.status_code}: a senha NÃO foi trocada.")
    try:
        dados = r.json()
    except ValueError:
        dados = {}
    gerada = dados.get("senha") if isinstance(dados, dict) else None
    if senha:
        return None
    if not gerada:
        raise ErroNegocio("A nuvem trocou a senha mas não devolveu a nova. Defina uma senha própria para o painel.")
    return str(gerada)


def registrar_troca_de_senha(banco, gerada: bool, operador_id: int | None = None) -> None:
    """Deixa no log do PDV que a senha do painel foi trocada e por quem (nunca a senha)."""
    banco.log("painel_senha_trocada", "senha gerada pela nuvem" if gerada else "senha escolhida pelo operador", operador_id)


def trocar_senha(banco, senha: str | None = None, http=None, operador_id: int | None = None) -> str | None:
    """`trocar_senha_na_nuvem` com o endereço e o token desta loja (Configurações > Nuvem) e o registro no log do PDV."""
    gerada = trocar_senha_na_nuvem(banco.cfg("api_url"), banco.cfg("api_token"), senha, http)
    registrar_troca_de_senha(banco, bool(gerada), operador_id)
    return gerada
