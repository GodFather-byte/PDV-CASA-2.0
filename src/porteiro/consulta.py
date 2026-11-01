"""Consulta da portaria: a comanda (ou mesa) ainda deve, ou pode sair.

Somente leitura. Não recalcula gravando, não fecha, não lança pagamento e não escreve no banco.
O valor em aberto é o mesmo que o caixa usaria para receber: produtos, serviço, consumação, acréscimo
e o que já foi pago (por valor ou por item).
"""
from __future__ import annotations

from datetime import datetime

from src.controllers.caixa_controller import CaixaController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.core.posicao import interpretar, nome as nome_posicao

_FORMATO_HORA = "%Y-%m-%d %H:%M:%S"


def _qtd(quantidade) -> str:
    texto = fmt.fmt_qtd(quantidade, 4)
    if "," in texto:
        texto = texto.rstrip("0").rstrip(",")
    return texto


def _linha(nome: str, quantidade, total_cent: int) -> dict:
    return {
        "nome": nome,
        "quantidade": None if quantidade is None else quantidade,
        "quantidade_txt": "" if quantidade is None else _qtd(quantidade),
        "total_cent": int(total_cent),
        "total_txt": fmt.fmt_brl(total_cent),
    }


def _quando(iso: str | None) -> str:
    if not iso or len(iso) < 16:
        return ""
    return f"{iso[8:10]}/{iso[5:7]} {iso[11:16]}"


def _cabecalho(nome: str, apelido: str) -> str:
    return f"{nome} · {apelido}" if apelido else nome


def _base(caixa: CaixaController, comanda: bool, numero: int, apelido: str = "") -> dict:
    nome = nome_posicao(comanda, numero)
    return {
        "comanda": bool(comanda),
        "numero": numero,
        "rotulo": caixa.rotular_posicao(comanda, numero),
        "nome": nome,
        "apelido": apelido,
        "cabecalho": _cabecalho(nome, apelido),
        "devido_cent": 0,
        "total_cent": 0,
        "pago_cent": 0,
        "valor_txt": "",
        "itens": [],
        "cupom": None,
    }


def _liberada(dados: dict, motivo: str, detalhe: str, **extra) -> dict:
    dados.update(situacao="liberada", titulo="LIBERADA", motivo=motivo, detalhe=detalhe, **extra)
    return dados


def _itens_em_aberto(caixa: CaixaController, venda: dict) -> list[dict]:
    """Itens que ainda têm valor. O que já foi pago na divisão por item sai da lista."""
    linhas = []
    for item in caixa.itens_para_divisao(venda["id"]):
        if item["valor_livre_cent"] <= 0:
            continue
        linhas.append(_linha(item["nome"], item["qtd_livre"], item["valor_livre_cent"]))
    return linhas


def _complementos(venda: dict, calculo: dict) -> list[dict]:
    linhas = []
    if calculo["rodizio_total"]:
        linhas.append(_linha("Rodízio", venda.get("pessoas") or None, calculo["rodizio_total"]))
    if calculo["servico"]:
        linhas.append(_linha("Serviço", None, calculo["servico"]))
    if calculo["taxa"]:
        nome = "Consumação mínima" if venda.get("comanda") else "Taxa"
        linhas.append(_linha(nome, None, calculo["taxa"]))
    if calculo["acrescimo"]:
        linhas.append(_linha("Acréscimo", None, calculo["acrescimo"]))
    if calculo["desconto"]:
        linhas.append(_linha("Desconto", None, -calculo["desconto"]))
    return linhas


def _idade_segundos(momento: str | None, agora: str) -> int | None:
    try:
        fim = datetime.strptime((agora or "")[:19], _FORMATO_HORA)
        inicio = datetime.strptime((momento or "")[:19], _FORMATO_HORA)
    except ValueError:
        return None
    return max(int((fim - inicio).total_seconds()), 0)


def frescura(momento: str | None = None, agora: str | None = None, no_caixa: bool = False) -> dict:
    """De onde veio a resposta e há quanto tempo o caixa a viu. O celular só mostra o texto."""
    agora = agora or fmt.agora()
    if no_caixa:
        return {"fonte": "caixa", "momento": agora, "atualizado": "agora, no caixa",
                "origem_txt": "No caixa · agora, no caixa", "atrasado": False}
    seg = _idade_segundos(momento, agora)
    if seg is None:
        atualizado, atrasado = "sem horário do caixa", True
    elif seg < 5:
        atualizado, atrasado = "atualizado agora", False
    elif seg < 60:
        atualizado, atrasado = f"atualizado há {seg}s", False
    elif seg < 3600:
        atualizado, atrasado = f"atualizado há {seg // 60} min", seg >= 20 * 60
    else:
        atualizado, atrasado = f"atualizado há {seg // 3600} h", True
    texto = f"Na nuvem · {atualizado}"
    if atrasado:
        texto += ". O caixa pode estar sem internet."
    return {"fonte": "nuvem", "momento": momento or "", "atualizado": atualizado,
            "origem_txt": texto, "atrasado": atrasado}


def consultar(banco, texto) -> dict:
    """A situação de uma comanda ou mesa para a portaria. Levanta ErroNegocio se o número não faz sentido."""
    dados = _consultar(banco, texto)
    dados.update(frescura(no_caixa=True))
    return dados


def numeros_com_comissao(banco) -> set[int]:
    """Números de comanda da garota: a comissão foi lançada e ainda está registrada (pendente).

    O número da garota é o da comanda dela. Paga ou cancelada não marca a comanda — é o mesmo
    critério do cartão rosa do caixa (comissão a pagar)."""
    return {int(linha["garota"]) for linha in banco.todos(
        "SELECT DISTINCT garota FROM comissoes_garotas WHERE status = 'pendente'")}


def retrato(banco) -> dict:
    """Comandas e mesas abertas, no formato da consulta, para a nuvem substituir o retrato anterior.
    Só leitura: não grava total nem fecha conta. `garota` marca a comanda com comissão pendente."""
    caixa = CaixaController(banco)
    garotas = numeros_com_comissao(banco)
    posicoes = []
    for linha in caixa.banco.todos(
            """SELECT * FROM vendas WHERE modalidade = 'mesa' AND status IN ('aberta', 'conta_enviada')
               ORDER BY comanda, posicao"""):
        v = dict(linha)
        posicoes.append(_aberta(caixa, v, bool(v["comanda"]), int(v["posicao"]), garotas))
    return {"posicao_padrao": caixa.padrao_posicao(), "posicoes": posicoes}


def listar_abertas(banco) -> dict:
    """Comandas abertas para o painel do porteiro, sem as das garotas e sem mesas.
    Só leitura. O celular atualiza esta lista; a consulta de um número continua à parte."""
    caixa = CaixaController(banco)
    garotas = numeros_com_comissao(banco)
    comandas = []
    for linha in caixa.banco.todos(
            """SELECT * FROM vendas WHERE modalidade = 'mesa' AND comanda = 1
               AND status IN ('aberta', 'conta_enviada') ORDER BY posicao"""):
        v = dict(linha)
        numero = int(v["posicao"])
        if numero in garotas:
            continue
        comandas.append(_resumo_lista(_aberta(caixa, v, True, numero, garotas)))
    comandas.sort(key=lambda item: (0 if item["situacao"] == "devendo" else 1, item["numero"]))
    dados = {"comandas": comandas}
    dados.update(frescura(no_caixa=True))
    return dados


def _resumo_lista(dados: dict) -> dict:
    return {
        "numero": dados["numero"],
        "rotulo": dados["rotulo"],
        "cabecalho": dados["cabecalho"],
        "situacao": dados["situacao"],
        "titulo": dados["titulo"],
        "devido_cent": dados["devido_cent"],
        "total_cent": dados["total_cent"],
        "pago_cent": dados["pago_cent"],
        "valor_txt": dados["valor_txt"] or fmt.fmt_brl(0),
        "total_txt": fmt.fmt_brl(dados["total_cent"]),
        "aberta_em": dados.get("aberta_em") or "",
        "aberta_txt": dados.get("aberta_txt") or "",
    }


def _consultar(banco, texto) -> dict:
    caixa = CaixaController(banco)
    try:
        comanda, numero = interpretar(texto, caixa.padrao_posicao())
    except ValueError as exc:
        raise ErroNegocio(str(exc)) from None
    if numero <= 0:
        raise ErroNegocio("Informe o número da comanda.")
    caixa.validar_mesa(numero, comanda)

    aberta = banco.um(
        """SELECT * FROM vendas WHERE modalidade = 'mesa' AND comanda = ? AND posicao = ?
           AND status IN ('aberta', 'conta_enviada') ORDER BY id DESC LIMIT 1""",
        (int(comanda), numero))
    if aberta is not None:
        return _aberta(caixa, dict(aberta), comanda, numero)

    ultima = banco.um(
        """SELECT * FROM vendas WHERE modalidade = 'mesa' AND comanda = ? AND posicao = ?
           ORDER BY id DESC LIMIT 1""",
        (int(comanda), numero))
    dados = _base(caixa, comanda, numero, (ultima["apelido"] or "").strip() if ultima is not None else "")
    nome = dados["nome"]
    if ultima is None:
        return _liberada(dados, "sem_registro", f"{nome} sem conta registrada. Nada a cobrar.")
    dados["total_cent"] = ultima["total_cent"] or 0
    if ultima["status"] == "fechada":
        dados["cupom"] = ultima["cupom"]
        partes = ["Conta paga"]
        extras = []
        if ultima["cupom"]:
            extras.append(f"cupom {ultima['cupom']}")
        hora = _quando(ultima["fechada_em"])
        if hora:
            extras.append(hora)
        if extras:
            partes.append("(" + ", ".join(extras) + ")")
        return _liberada(dados, "paga", " ".join(partes) + ".")
    return _liberada(dados, "cancelada", f"{nome}: a última conta foi cancelada. Nada em aberto.")


def _aberta(caixa: CaixaController, venda: dict, comanda: bool, numero: int,
           garotas: set[int] | None = None) -> dict:
    apelido = (venda.get("apelido") or "").strip()
    dados = _base(caixa, comanda, numero, apelido)
    if garotas is None and comanda:
        garotas = numeros_com_comissao(caixa.banco)
    dados["garota"] = bool(comanda and garotas and numero in garotas)
    dados["aberta_em"] = (venda.get("aberta_em") or "")[:19]
    dados["aberta_txt"] = _quando(venda.get("aberta_em"))
    # calcular só lê. Não chamar recalcular: ele grava o total na venda.
    calculo = caixa.calcular(venda)
    pago = sum(p["valor_cent"] for p in caixa.pagamentos(venda["id"]))
    devido = max(calculo["total"] - pago, 0)
    dados.update(total_cent=calculo["total"], pago_cent=pago, devido_cent=devido)
    if devido <= 0:
        if pago <= 0:
            return _liberada(dados, "vazia", "Nada lançado para cobrar. Pode liberar.")
        return _liberada(dados, "quitada", "O valor já foi recebido no caixa. Pode liberar.")
    partes = []
    if venda["status"] == "conta_enviada":
        partes.append("A conta já foi pedida.")
    partes.append(f"Ainda falta {fmt.fmt_brl(devido)}.")
    if pago > 0:
        partes.append(f"Já recebido {fmt.fmt_brl(pago)} de {fmt.fmt_brl(calculo['total'])}.")
    dados.update(
        situacao="devendo",
        titulo="DEVENDO",
        motivo="aberta",
        detalhe=" ".join(partes),
        valor_txt=fmt.fmt_brl(devido),
        itens=_itens_em_aberto(caixa, venda) + _complementos(venda, calculo),
    )
    return dados
