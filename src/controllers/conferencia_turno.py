"""Conferência do turno: o que o fechamento mostra além dos totais.

  * posições (mesas e comandas) que ainda estão abertas, com o total de cada uma;
  * cupons e itens cancelados durante o turno, e quem cancelou;
  * transferências entre mesas e comandas: de onde para onde foi o consumo, quanto e quem fez.

Serve para o dono auditar o turno: comanda esquecida aberta, item cancelado, consumo passado para a conta de outro cliente.
As transferências ficam no `log_eventos` (evento 'transferencia', detalhe em JSON): não há tabela própria.
"""
from __future__ import annotations

import json
import re
import textwrap

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.core.posicao import nome as nome_posicao
from src.core.posicao import rotulo as rotulo_posicao

LIMITE_FITA = 40      # linhas por seção na fita; o resto vira "e mais N"
LIMITE_PRODUTOS = 300  # o fechamento lista todos os produtos vendidos (o cardápio de uma casa cabe com folga)
M, Q = fmt.fmt_num, fmt.fmt_qtd


def comparar_fechamento(resumo: dict, formas: list[dict], valor_final_cent: int,
                       informados_por_forma: dict[int, int] | None = None) -> dict:
    """Compara valores em centavos, sem atribuir contagens ausentes a formas legadas."""
    if type(valor_final_cent) is not int or valor_final_cent < 0:
        raise ErroNegocio("O valor final deve ser inteiro em centavos e não pode ser negativo.")
    recebidos = {r["tipo_id"]: r["valor"] for r in resumo["recebimentos"]}
    if informados_por_forma is not None:
        if (not isinstance(informados_por_forma, dict)
                or any(type(k) is not int or type(v) is not int or v < 0
                       for k, v in informados_por_forma.items())):
            raise ErroNegocio("Informe por forma valores inteiros em centavos, não negativos.")
        if set(informados_por_forma) != {f["tipo_id"] for f in formas}:
            raise ErroNegocio("Informe o valor de todas as formas da conferência, sem formas desconhecidas.")
        if sum(informados_por_forma[f["tipo_id"]] for f in formas if f["na_gaveta"]) != valor_final_cent:
            raise ErroNegocio("A soma das formas físicas deve ser igual ao valor informado na gaveta.")
    dinheiro = next((f["tipo_id"] for f in formas if f.get("dinheiro")), None)
    ajustes = resumo["valor_inicial"] + resumo["entradas"] - resumo["saidas"]
    if ajustes and dinheiro is None:
        raise ErroNegocio("Não foi possível identificar a forma Dinheiro para o fundo e movimentos da gaveta.")
    linhas = []
    for forma in formas:
        esperado = recebidos.get(forma["tipo_id"], 0) + (ajustes if forma["tipo_id"] == dinheiro else 0)
        informado = informados_por_forma[forma["tipo_id"]] if informados_por_forma is not None else None
        linhas.append({**forma, "esperado_cent": esperado, "informado_cent": informado,
                       "diferenca_cent": informado - esperado if informado is not None else None})
    diferenca = valor_final_cent - resumo["esperado"]
    return {"linhas": linhas,
            "estornos_informados": resumo.get("devolucoes", {}).get("externos", []),
            "gaveta": {"esperado_cent": resumo["esperado"], "informado_cent": valor_final_cent,
                       "diferenca_cent": diferenca},
            "por_forma_informada": informados_por_forma is not None,
            "tem_diferenca": bool(diferenca or any(l["diferenca_cent"] for l in linhas)),
            "composicao": {"fundo_cent": resumo["valor_inicial"], "suprimentos_cent": resumo["entradas"],
                          "sangrias_cent": resumo["saidas"], "troco_cent": resumo["troco"],
                          "acrescimo_cent": resumo["acrescimo"],
                          "recebido_turno_anterior_cent": resumo["recebido_turno_anterior"]}}


def registrar_transferencia(banco, operador_id: int | None, tipo: str, origem: str, destino: str, valor_cent: int,
                            **extra) -> None:
    """Grava no log uma transferência: tipo 'mesa' (posição inteira) ou 'item' (parte dos produtos).
    `origem` e `destino` são os rótulos das posições ('5' para mesa, 'C2' para comanda)."""
    detalhe = {"tipo": tipo, "origem": origem, "destino": destino, "valor_cent": valor_cent, **extra}
    banco.log("transferencia", json.dumps(detalhe, ensure_ascii=False), operador_id)


def _local(modalidade: str, comanda, posicao) -> str:
    if modalidade == "mesa":
        return nome_posicao(comanda, posicao)
    return {"balcao": "Balcão", "caderneta": "Caderneta"}.get(modalidade, f"Entrega {posicao}")


def posicoes_abertas(banco) -> list[dict]:
    """Mesas e comandas com consumo que ainda estão abertas (as vazias, recém-abertas, não contam)."""
    return [{"rotulo": rotulo_posicao(r["comanda"], r["posicao"]), "nome": nome_posicao(r["comanda"], r["posicao"]),
             "status": r["status"], "total_cent": r["total_cent"], "itens": r["itens"]}
            for r in banco.todos(
                """SELECT v.comanda, v.posicao, v.status, v.total_cent,
                          (SELECT COUNT(*) FROM itens_venda i WHERE i.venda_id = v.id AND i.cancelado = 0) AS itens
                   FROM vendas v WHERE v.modalidade = 'mesa' AND v.status IN ('aberta','conta_enviada')
                   ORDER BY v.comanda, v.posicao""") if r["itens"]]


def _cupons_cancelados(banco, turno_id: int) -> list[dict]:
    return [{"cupom": r["cupom"], "local": _local(r["modalidade"], r["comanda"], r["posicao"]),
             "total_cent": r["total_cent"], "motivo": r["motivo_cancelamento"], "por": r["por"]}
            for r in banco.todos(
                """SELECT v.cupom, v.modalidade, v.comanda, v.posicao, v.total_cent, v.motivo_cancelamento, o.nome AS por
                   FROM vendas v LEFT JOIN operadores o ON o.id = v.cancelada_por
                   WHERE v.turno_id = ? AND v.status = 'cancelada' ORDER BY v.cupom""", (turno_id,))]


def _produtos_vendidos(banco, turno_id: int) -> list[dict]:
    """O que saiu no turno: cada produto das vendas fechadas nele (itens não cancelados), do maior total ao menor."""
    return [dict(r) for r in banco.todos(
        """SELECT p.nome AS produto, SUM(i.quantidade) AS quantidade, SUM(i.total_cent) AS total_cent
           FROM itens_venda i JOIN vendas v ON v.id = i.venda_id JOIN produtos_historico p ON p.id = i.produto_id
           WHERE v.turno_id = ? AND v.status = 'fechada' AND i.cancelado = 0
           GROUP BY p.id ORDER BY total_cent DESC, p.nome""", (turno_id,))]


_TIPO_VENDA = {("balcao", 0): "Balcão", ("mesa", 1): "Comandas", ("mesa", 0): "Mesas", ("caderneta", 0): "Caderneta",
               ("entrega", 0): "Entrega"}


def _vendas_por_tipo(banco, turno_id: int) -> list[dict]:
    """Vendas fechadas no turno por tipo (balcão, comandas, mesas...): quantos cupons e quanto. Recebimento de caderneta
    (sem itens) não é venda e fica de fora."""
    return [{"tipo": _TIPO_VENDA.get((r["modalidade"], r["comanda"]), r["modalidade"]), "cupons": r["cupons"],
             "total_cent": r["total_cent"]}
            for r in banco.todos(
                """SELECT modalidade, CASE WHEN modalidade = 'mesa' THEN comanda ELSE 0 END AS comanda,
                          COUNT(*) AS cupons, SUM(total_cent) AS total_cent FROM vendas
                   WHERE turno_id = ? AND status = 'fechada' AND subtotal_cent > 0
                   GROUP BY 1, 2 ORDER BY total_cent DESC""", (turno_id,))]


def _saidas_liberadas(banco, turno_id: int) -> list[dict]:
    """Saídas sem consumo do turno (código 1002): hora, comanda e quem liberou."""
    return [{"quando": r["quando"], "local": nome_posicao(bool(r["comanda"]), r["posicao"]), "por": r["por"]}
            for r in banco.todos(
                """SELECT l.quando, json_extract(l.detalhe, '$.comanda') AS comanda, json_extract(l.detalhe, '$.posicao') AS posicao,
                          o.nome AS por FROM log_eventos l LEFT JOIN operadores o ON o.id = l.operador_id
                   WHERE l.evento = 'saida_liberada' AND json_extract(l.detalhe, '$.turno_id') = ? ORDER BY l.id""", (turno_id,))]


def _eventos(banco, evento: str, inicio: str, fim: str):
    return banco.todos(
        """SELECT l.quando, l.detalhe, o.nome AS por FROM log_eventos l LEFT JOIN operadores o ON o.id = l.operador_id
           WHERE l.evento = ? AND l.quando >= ? AND l.quando <= ? ORDER BY l.id""", (evento, inicio, fim))


def _itens_cancelados(banco, inicio: str, fim: str) -> list[dict]:
    """Parte do log (quem e quando) e só então vai ao item (por chave): não varre a tabela de itens inteira."""
    saida = []
    for e in _eventos(banco, "item_cancelado", inicio, fim):
        achou = re.search(r"item (\d+)", e["detalhe"] or "")
        r = banco.um(
            """SELECT i.quantidade, i.total_cent, p.codigo, p.nome, v.modalidade, v.comanda, v.posicao, v.cupom
               FROM itens_venda i JOIN vendas v ON v.id = i.venda_id JOIN produtos_historico p ON p.id = i.produto_id
               WHERE i.id = ?""", (int(achou.group(1)),)) if achou else None
        if r is None:                 # a venda já foi apagada (limpeza do movimento)
            continue
        saida.append({"quando": e["quando"], "local": _local(r["modalidade"], r["comanda"], r["posicao"]),
                      "cupom": r["cupom"], "codigo": r["codigo"], "produto": r["nome"], "quantidade": r["quantidade"],
                      "total_cent": r["total_cent"], "por": e["por"],
                      "motivo": (re.search(r"motivo: (.*)", e["detalhe"] or "") or [None, None])[1]})
    return saida


def _transferencias(banco, inicio: str, fim: str) -> list[dict]:
    saida = []
    for e in _eventos(banco, "transferencia", inicio, fim):
        try:
            d = json.loads(e["detalhe"])
        except (TypeError, ValueError):
            continue
        saida.append({"quando": e["quando"], "por": e["por"],
                      **{k: d.get(k) for k in ("tipo", "origem", "destino", "valor_cent", "produto", "quantidade")}})
    return saida


def conferencia(banco, turno: dict) -> dict:
    """Tudo que a conferência traz, para o turno `turno` (aberto: até agora; fechado: até o fechamento)."""
    from src.controllers.comissao_controller import ComissaoController      # import tardio: ele importa o TurnoController
    inicio, fim = turno["aberto_em"], turno.get("fechado_em") or fmt.agora()
    comissoes = ComissaoController(banco)
    return {"posicoes_abertas": posicoes_abertas(banco),
            "cupons_cancelados": _cupons_cancelados(banco, turno["id"]),
            "itens_cancelados": _itens_cancelados(banco, inicio, fim),
            "transferencias": _transferencias(banco, inicio, fim),
            "produtos_vendidos": _produtos_vendidos(banco, turno["id"]),
            "vendas_por_tipo": _vendas_por_tipo(banco, turno["id"]),
            "saidas_liberadas": _saidas_liberadas(banco, turno["id"]),
            "comissoes": {**comissoes.resumo_turno(turno["id"]), "a_pagar_cent": comissoes.total_a_pagar()},
            "shows": comissoes.shows_do_turno(turno["id"]),
            "pix_garotas_cent": comissoes.pix_do_turno(turno["id"])}


# ----------------------------------------------------------------- texto da fita
def _lr(esq: str, dir_: str, w: int) -> str:
    esq = esq[: max(w - len(dir_) - 1, 1)]
    return esq.ljust(w - len(dir_)) + dir_


def _hora(quando: str | None) -> str:
    return (quando or "")[11:16]


def _qtd(q) -> str:
    """1 em vez de 1,000 quando a quantidade é inteira."""
    q = q or 0
    return Q(q, 0) if q == int(q) else Q(q)


def _curto(rotulo: str | None) -> str:
    """'C2' continua 'C2'; o '5' das mesas vira 'M5' para não ser confundido com número de comanda."""
    rotulo = rotulo or "?"
    return rotulo if rotulo[:1] in "Cc" else f"M{rotulo}"


def faixa(titulo: str, w: int) -> str:
    """Título de seção da fita, centralizado entre traços: '-------- VENDAS POR TIPO --------'."""
    return f" {titulo} ".center(w, "-")[:w]


def _secao(titulo: str, itens: list, formata, w: int, limite: int = LIMITE_FITA) -> list[str]:
    linhas = ["", faixa(f"{titulo} ({len(itens)})", w)]
    for it in itens[:limite]:
        linhas += formata(it)
    if len(itens) > limite:
        linhas.append(f"  ... e mais {len(itens) - limite}")
    return linhas


def linhas_fita(res: dict, w: int = 40) -> list[str]:
    """As seções da conferência para a fita de `w` colunas. Só aparecem as que têm algo; a linha das posições abertas
    aparece sempre (um 'nenhuma' mostra que foi conferido)."""
    saida: list[str] = []
    fechamento = res.get("conferencia_fechamento")
    if fechamento:
        saida += ["", faixa("ESPERADO / INFORMADO POR FORMA", w)]
        for linha in fechamento["linhas"]:
            saida += [linha["tipo"][:w],
                      _lr("  Esperado", M(linha["esperado_cent"]), w)]
            if linha["informado_cent"] is None:
                saida.append("  Não informado por forma"[:w])
            else:
                saida += [_lr("  Informado", M(linha["informado_cent"]), w),
                          _lr("  Diferença", M(linha["diferenca_cent"]), w)]
        saida += ["  Dinheiro inclui fundo e movimentos."[:w],
                  "  Recebimentos já líquidos de troco."[:w],
                  "  Cartão/Pix não compõem a gaveta."[:w]]
        motivo = fechamento.get("justificativa")
        if motivo:
            saida += ["Justificativa da diferença:"[:w], *textwrap.wrap(motivo, width=w)]
    devolucoes = res.get("devolucoes")
    if devolucoes and devolucoes["quantidade"]:
        saida += ["", faixa("DEVOLUÇÕES DO TURNO", w),
                  _lr("  Total devolvido", M(devolucoes["valor_cent"]), w),
                  "  Dinheiro já incluído nas sangrias."[:w],
                  _lr("  Estornos externos informados",
                      M(devolucoes["por_modo"].get("externo", {}).get("valor_cent", 0)), w),
                  "  Externo não comprova estorno bancário."[:w]]
        for forma in devolucoes["por_forma"]:
            if forma["modo"] == "externo":
                saida.append(_lr(f"  {forma['tipo']}", M(forma["valor_cent"]), w))
    if res.get("vendas_por_tipo"):
        saida += _secao("VENDAS POR TIPO", res["vendas_por_tipo"],
                        lambda t: [_lr(f"  {t['tipo']} ({t['cupons']} cupons)", M(t["total_cent"]), w)], w)
    if res.get("produtos_vendidos"):
        produtos = res["produtos_vendidos"]
        saida += _secao("PRODUTOS VENDIDOS", produtos,
                        lambda p: [_lr(f"  {_qtd(p['quantidade'])}x {p['produto']}", M(p["total_cent"]), w)], w,
                        limite=LIMITE_PRODUTOS)
        saida.append(_lr("  Total dos produtos", M(sum(p["total_cent"] for p in produtos)), w))
    abertas = res.get("posicoes_abertas") or []
    if abertas:
        def posicao(p):
            nome = p["nome"] + (" - conta enviada" if p["status"] == "conta_enviada" else "")
            return [_lr(f"  {nome}", M(p["total_cent"]), w)]
        saida += _secao("POSIÇÕES EM ABERTO", abertas, posicao, w)
        saida.append(_lr("  Total em aberto", M(sum(p["total_cent"] for p in abertas)), w))
    else:
        saida += ["", faixa("POSIÇÕES EM ABERTO", w), _lr("  Nenhuma mesa ou comanda aberta", "OK", w)]

    def cupom(c):
        linhas = [_lr(f"  {c['cupom']} {c['local']}", M(c["total_cent"]), w)]
        motivo = f"{c['por'] or '?'}: {c['motivo']}" if c["motivo"] else f"por {c['por'] or '?'}"
        return linhas + [f"     {motivo}"[:w]]

    def item(i):
        return [_lr(f"  {_hora(i['quando'])} {_curto_local(i['local'])} {_qtd(i['quantidade'])}x {i['produto']}",
                    M(i["total_cent"]), w),
                (f"        {i['por'] or '?'}: {i['motivo']}" if i.get("motivo") else f"        por {i['por'] or '?'}")[:w]]

    def transferencia(t):
        o = "inteira" if t["tipo"] == "mesa" else f"{_qtd(t['quantidade'])}x {t['produto'] or '?'}"
        return [_lr(f"  {_hora(t['quando'])} {_curto(t['origem'])}>{_curto(t['destino'])} {o}", M(t["valor_cent"] or 0), w),
                f"        por {t['por'] or '?'}"[:w]]

    if res.get("cupons_cancelados"):
        saida += _secao("CUPONS CANCELADOS", res["cupons_cancelados"], cupom, w)
    if res.get("itens_cancelados"):
        saida += _secao("ITENS CANCELADOS", res["itens_cancelados"], item, w)
    if res.get("transferencias"):
        saida += _secao("TRANSFERÊNCIAS", res["transferencias"], transferencia, w)

    def comissao(g):
        quem = f"{g['garota']} {g['nome']}".strip()
        return [_lr(f"  {quem} ({g['lancamentos']}x)", M(g["total_cent"]), w)]

    if res.get("saidas_liberadas"):
        saida += _secao("SAÍDAS SEM CONSUMO (1002)", res["saidas_liberadas"],
                        lambda s: [_lr(f"  {_hora(s['quando'])} {_curto_local(s['local'])}", f"por {s['por'] or '?'}", w)], w)

    c = res.get("comissoes") or {}
    if c.get("por_garota") or c.get("a_pagar_cent"):
        saida += _secao("COMISSÕES DAS GAROTAS", c.get("por_garota") or [], comissao, w)
        if c.get("por_garota"):
            saida.append(_lr("  Total lançado no turno", M(c["total_cent"]), w))
        if c.get("a_pagar_cent"):
            saida.append(_lr("  A pagar às garotas (todas)", M(c["a_pagar_cent"]), w))

    def show(g):
        quem = f"{g['garota']} {g['nome']}".strip()
        return [_lr(f"  {quem} ({g['shows']}x)", M(g["total_cent"]), w)]

    if res.get("pix_garotas_cent"):
        saida += ["", _lr("Pago às garotas por Pix", M(res["pix_garotas_cent"]), w), "  (não saiu da gaveta)"]
    shows = res.get("shows") or {}
    if shows.get("quantidade"):
        saida += _secao("SHOWS PAGOS ÀS GAROTAS", shows["por_garota"], show, w)
        saida.append(_lr("  Total de shows", M(shows["total_cent"]), w))
    return saida


def _curto_local(local: str) -> str:
    """'Comanda 2' -> 'C2', 'Mesa 5' -> 'M5'; Balcão, Caderneta e Entrega continuam por extenso."""
    partes = local.split()
    if len(partes) == 2 and partes[0] in ("Comanda", "Mesa"):
        return f"{partes[0][0]}{partes[1]}"
    return local


def texto_conferencia(res: dict, w: int = 40) -> str:
    """As mesmas seções como texto avulso (para ver na tela sem imprimir)."""
    return "CONFERÊNCIA DO TURNO".center(w) + "\n" + "\n".join(linhas_fita(res, w)[1:])
