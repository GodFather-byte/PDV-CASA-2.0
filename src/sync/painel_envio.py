"""Painel do dono no celular: o que o PDV envia para a nuvem (opcional, Configurações > Nuvem > `painel_dono`).

A cada rodada da sincronização (`python -m src.app --sync`) o PDV manda, com o token da loja:
  * as vendas fechadas ou canceladas que ainda não subiram (`vendas.sincronizado = 0`), com itens e pagamentos, em lotes;
    a nuvem confirma os uuids recebidos e só então eles são marcados como enviados (cancelar uma venda já enviada zera a
    marca, e ela sobe de novo com o status novo);
  * um retrato do momento: turno aberto, estoque controlado (zerados e abaixo do mínimo), caderneta a receber e entregas
    pendentes. O retrato substitui o anterior DESTE caixa na nuvem; é dele que o celular tira "atualizado às HH:MM".

Cada caixa tem o seu banco, então se identifica (`id_do_caixa`): numa loja com dois caixas a nuvem guarda um retrato de
cada um, em vez de o último a falar apagar o do outro.

Nada é apagado ou alterado no banco local além da marca de enviado. Sem rede, as vendas esperam a próxima rodada. O painel
mostra só o que já subiu: não é um espelho ao vivo do caixa.

Também daqui sai a troca da senha do painel pelo próprio PDV (`trocar_senha`): o dono não depende do fornecedor.
"""
from __future__ import annotations

import logging
import socket
from uuid import uuid4

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.core.posicao import nome as nome_posicao

log = logging.getLogger("pdv.painel")

LOTE = 200                    # vendas por envio: cabe numa chamada curta mesmo em rede ruim
LIMITE_ABAIXO_MINIMO = 50     # produtos listados no retrato (o resto vira só contagem)
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


def coletar_vendas(banco, limite: int | None = None) -> list[dict]:
    """As vendas que faltam subir, da mais antiga para a mais nova, já no formato que a nuvem guarda."""
    limite = LOTE if limite is None else limite
    virada = _virada(banco)
    caixa_id = id_do_caixa(banco)
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
            "turno_numero": v["turno_numero"], "terminal": v["terminal"], "terminal_id": caixa_id,
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
    config = ConfigController(banco)
    maquina = config.maquina()
    return {
        "loja_nome": config.nome_loja(), "virada_dia_hora": _virada(banco),
        "terminal_id": id_do_caixa(banco), "terminal": turnos.terminal,
        "terminal_rotulo": (maquina.get("descricao") or "").strip() or f"Caixa {turnos.terminal}",
        "terminal_computador": (maquina.get("nome_computador") or "").strip() or socket.gethostname(),
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
