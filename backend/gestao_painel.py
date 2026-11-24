"""Relatórios e cadastros em lote pelo painel do dono e pelo assistente da loja.

A sessão do painel ou o token `wpdv_` (o mesmo da importação) lê vendas que o caixa já subiu
e o espelho da retaguarda. Custo e lucro aparecem porque quem entra no painel, ou gera o token,
é o dono. Não há login de operador nesta API.

Escrita (preço, reajuste, estoque) sem `dry_run: false` só devolve a prévia. Quando grava,
enfileira `cadastro.salvar` ou `estoque.movimento`: o caixa antigo que já tem retaguarda aplica
na sincronização. Não há tipo novo de comando.

Dinheiro em centavos inteiros. Quantidade com até 4 casas. Data em `AAAA-MM-DD`.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.database import get_db
from src.core import custo_lucro, formatacao as fmt
from src.core.erros import ErroNegocio
from src.core.formatacao import texto_planilha

PREFIXO = "/v1/painel/gestao"
TIPOS = ("resumo", "vendas", "produtos", "categorias", "abc", "formas", "operadores", "estoque", "caixa", "rede")
TIPOS_ESTOQUE = ("entrada", "saida", "contagem", "quebra", "descarte")
CAMPOS_LOTE = ("preco_cent", "custo_medio_cent", "estoque_minimo", "subgrupo_id", "ativo")
LIMITE_ENVIO = 200
LIMITE_LINHAS = 500
COBERTURA_DIAS = 7
PERCENTUAL_MIN = Decimal("-90")
PERCENTUAL_MAX = Decimal("300")


def _painel():
    from backend import painel
    return painel


def _agora() -> str:
    return _painel()._agora()


def _norm(texto) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip().casefold()


def _inteiro(valor, nome: str) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErroNegocio(f"{nome}: informe um número inteiro.")
    return valor


def _centavos(valor, nome: str) -> int:
    valor = _inteiro(valor, nome)
    if valor < 0 or valor > 100_000_000:
        raise ErroNegocio(f"{nome}: valor fora do limite.")
    return valor


def _quantidade(valor, nome: str = "Quantidade") -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        raise ErroNegocio(f"{nome} inválida.")
    texto = str(valor).strip().replace(",", ".")
    try:
        numero = Decimal(texto)
    except InvalidOperation:
        raise ErroNegocio(f"{nome} inválida.") from None
    if numero < 0 or numero > Decimal("1000000"):
        raise ErroNegocio(f"{nome} fora do limite.")
    try:
        return float(fmt.para_qtd(format(numero.quantize(Decimal("0.0001")), "f")))
    except ValueError:
        raise ErroNegocio(f"{nome} inválida.") from None


def _percentual(valor) -> Decimal:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        raise ErroNegocio("Percentual inválido. Use um número, por exemplo 10 ou -5.")
    texto = str(valor).strip().replace(",", ".")
    try:
        numero = Decimal(texto)
    except InvalidOperation:
        raise ErroNegocio("Percentual inválido. Use um número, por exemplo 10 ou -5.") from None
    if numero == 0 or numero < PERCENTUAL_MIN or numero > PERCENTUAL_MAX:
        raise ErroNegocio("O percentual fica entre -90 e 300, e não pode ser zero.")
    return numero


def preco_reajustado(preco_cent: int, percentual: Decimal) -> int:
    """Novo preço em centavos. 10 em R$ 8,00 (800) vira 880. Meio centavo sobe."""
    novo = fmt.arredondar(fmt._dec(preco_cent) * (Decimal(100) + percentual) / Decimal(100))
    if novo < 0:
        raise ErroNegocio("O reajuste deixaria um preço negativo.")
    return int(novo)


def _data(texto: str | None, nome: str) -> date:
    bruto = str(texto or "")[:10]
    try:
        dia = date.fromisoformat(bruto)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Informe {nome} como AAAA-MM-DD.") from None
    if bruto != dia.isoformat():
        raise HTTPException(status_code=422, detail=f"Informe {nome} como AAAA-MM-DD.")
    return dia


def _periodo(de: str | None, ate: str | None) -> tuple[date, date]:
    hoje = _painel()._hoje()
    inicio = _data(de, "a data inicial") if de else hoje
    fim = _data(ate, "a data final") if ate else hoje
    if fim < inicio:
        raise HTTPException(status_code=422, detail="A data final é anterior à inicial.")
    if (fim - inicio).days > 400:
        raise HTTPException(status_code=422, detail="O intervalo pode ter no máximo 400 dias.")
    return inicio, fim


def _erro_http(erro: ErroNegocio) -> HTTPException:
    return HTTPException(status_code=422, detail=str(erro))


# ---------------------------------------------------------------- espelho e vendas
def _tabela(dados: dict | None) -> list[dict]:
    if not isinstance(dados, dict):
        return []
    campos = dados.get("campos") or []
    saida = []
    for linha in dados.get("linhas") or []:
        if isinstance(linha, list) and len(linha) == len(campos):
            saida.append(dict(zip(campos, linha)))
    return saida


def _catalogo(db: Session, chave: str) -> dict:
    from backend.retaguarda import secao
    produtos, quando = secao(db, chave, "cadastro:produtos")
    subgrupos, _ = secao(db, chave, "cadastro:subgrupos")
    grupos, _ = secao(db, chave, "cadastro:grupos")
    return {
        "quando": quando,
        "produtos": _tabela(produtos),
        "subgrupos": _tabela(subgrupos),
        "grupos": _tabela(grupos),
        "tem_cadastro": produtos is not None,
    }


def _nomes_categoria(catalogo: dict) -> dict[int, tuple[str, str]]:
    """subgrupo_id -> (nome do subgrupo, nome do grupo)."""
    grupos = {g.get("id"): str(g.get("nome") or "") for g in catalogo["grupos"]}
    saida = {}
    for sub in catalogo["subgrupos"]:
        if isinstance(sub.get("id"), int):
            saida[sub["id"]] = (str(sub.get("nome") or ""), grupos.get(sub.get("grupo_id"), ""))
    return saida


def _vendas(db: Session, chave: str, inicio: date, fim: date) -> list[dict]:
    painel = _painel()
    linhas = (db.query(painel.PainelVenda).filter(
        painel.PainelVenda.chave_loja == chave,
        painel.PainelVenda.dia >= inicio.isoformat(),
        painel.PainelVenda.dia <= fim.isoformat()).all())
    saida = []
    for linha in linhas:
        try:
            venda = json.loads(linha.dados)
        except (TypeError, ValueError):
            venda = {}
        if not isinstance(venda, dict):
            venda = {}
        venda["status"] = linha.status
        venda["total_cent"] = linha.total_cent
        venda["desconto_cent"] = linha.desconto_cent
        venda["operador"] = linha.operador or venda.get("operador") or ""
        venda["fechada_em"] = linha.fechada_em or ""
        venda["dia"] = linha.dia
        venda["itens"] = [i for i in (venda.get("itens") or []) if isinstance(i, dict)]
        venda["pagamentos"] = [p for p in (venda.get("pagamentos") or []) if isinstance(p, dict)]
        saida.append(venda)
    return saida


def _itens_validos(venda: dict):
    for item in venda.get("itens") or []:
        if painel_cancelado(item):
            continue
        yield item


def painel_cancelado(item: dict) -> bool:
    return bool(_painel()._int(item.get("cancelado")))


def _custo_item(item: dict) -> tuple[int, bool]:
    return _painel()._custo_do_item(item)


# ---------------------------------------------------------------- relatórios
def _agregar(vendas: list[dict]) -> dict:
    """Totais do período a partir das vendas já guardadas na nuvem. Cancelada não entra no faturamento."""
    painel = _painel()
    fechadas = [v for v in vendas if v.get("status") == "fechada"]
    canceladas = [v for v in vendas if v.get("status") == "cancelada"]
    faturamento = sum(painel._int(v.get("total_cent")) for v in fechadas)
    por_dia: dict[str, dict] = {}
    por_hora: dict[str, dict] = {}
    produtos: dict[str, dict] = {}
    categorias: dict[str, dict] = {}
    formas: dict[str, dict] = {}
    operadores: dict[str, dict] = {}
    tem_custo = False
    for venda in fechadas:
        dia = str(venda.get("dia") or "")[:10]
        bloco_dia = por_dia.setdefault(dia, {"dia": dia, "faturamento_cent": 0, "vendas": 0})
        bloco_dia["faturamento_cent"] += painel._int(venda.get("total_cent"))
        bloco_dia["vendas"] += 1
        hora = str(venda.get("fechada_em") or "")[11:13] or "--"
        bloco_hora = por_hora.setdefault(hora, {"hora": hora, "faturamento_cent": 0, "vendas": 0})
        bloco_hora["faturamento_cent"] += painel._int(venda.get("total_cent"))
        bloco_hora["vendas"] += 1
        nome_op = str(venda.get("operador") or "Sem operador")[:60]
        op = operadores.setdefault(nome_op, {"operador": nome_op, "vendas": 0, "faturamento_cent": 0, "desconto_cent": 0})
        op["vendas"] += 1
        op["faturamento_cent"] += painel._int(venda.get("total_cent"))
        op["desconto_cent"] += painel._int(venda.get("desconto_cent"))
        for pag in venda.get("pagamentos") or []:
            tipo = str(pag.get("tipo") or "Sem forma")[:40]
            valor = painel._int(pag.get("valor_cent")) - painel._int(pag.get("troco_cent"))
            forma = formas.setdefault(tipo, {"tipo": tipo, "valor_cent": 0, "vezes": 0})
            forma["valor_cent"] += valor
            forma["vezes"] += 1
        for item in _itens_validos(venda):
            nome = str(item.get("nome") or "Sem nome")[:60]
            grupo = str(item.get("grupo") or "Sem categoria")[:40]
            qtd = float(item.get("quantidade") or 0)
            valor = painel._int(item.get("total_cent"))
            custo, tem = _custo_item(item)
            tem_custo = tem_custo or tem
            chave = (str(item.get("codigo") or ""), nome)
            prod = produtos.setdefault(chave, {
                "codigo": str(item.get("codigo") or ""), "nome": nome, "grupo": grupo,
                "quantidade": 0.0, "valor_cent": 0, "custo_cent": 0, "tem_custo": False,
            })
            prod["quantidade"] += qtd
            prod["valor_cent"] += valor
            prod["custo_cent"] += custo
            prod["tem_custo"] = prod["tem_custo"] or tem
            cat = categorias.setdefault(grupo, {"categoria": grupo, "quantidade": 0.0, "valor_cent": 0, "custo_cent": 0})
            cat["quantidade"] += qtd
            cat["valor_cent"] += valor
            cat["custo_cent"] += custo
    return {
        "fechadas": len(fechadas), "canceladas": len(canceladas), "faturamento_cent": faturamento,
        "ticket_medio_cent": round(faturamento / len(fechadas)) if fechadas else 0,
        "desconto_cent": sum(painel._int(v.get("desconto_cent")) for v in fechadas),
        "tem_custo": tem_custo,
        "por_dia": [por_dia[k] for k in sorted(por_dia)],
        "por_hora": [por_hora[k] for k in sorted(por_hora)],
        "produtos": sorted(produtos.values(), key=lambda p: (-p["valor_cent"], p["nome"])),
        "categorias": sorted(categorias.values(), key=lambda c: (-c["valor_cent"], c["categoria"])),
        "formas": sorted(formas.values(), key=lambda f: (-f["valor_cent"], f["tipo"])),
        "operadores": sorted(operadores.values(), key=lambda o: (-o["faturamento_cent"], o["operador"])),
    }


def _com_lucro(bloco: dict, tem_custo: bool) -> dict:
    venda = int(bloco.get("valor_cent") or bloco.get("faturamento_cent") or 0)
    if not tem_custo:
        bloco["lucro_cent"] = None
        bloco["margem"] = None
        return bloco
    custo = int(bloco.get("custo_cent") or 0)
    bloco["lucro_cent"] = custo_lucro.lucro_cent(venda, custo)
    bloco["margem"] = custo_lucro.margem_texto(venda, custo)
    return bloco


def classificar_abc(linhas: list[dict], chave_valor: str = "valor_cent") -> list[dict]:
    """A até 80% do total, B até 95%, C o restante. Empate de valor não muda a ordem recebida."""
    total = sum(int(l.get(chave_valor) or 0) for l in linhas) or 1
    acumulado = 0
    saida = []
    for linha in linhas:
        valor = int(linha.get(chave_valor) or 0)
        if valor <= 0:
            item = dict(linha)
            item["participacao_bp"] = 0
            item["acumulado_bp"] = acumulado * 10000 // total
            item["classe"] = "C"
            saida.append(item)
            continue
        # A classe olha o acumulado antes do item: quem ainda cabe nos 80% é A,
        # mesmo que sozinho passe disso. Um produto só fica em A.
        antes = acumulado * 10000 // total
        acumulado += valor
        classe = "A" if antes < 8000 else "B" if antes < 9500 else "C"
        item = dict(linha)
        item["participacao_bp"] = valor * 10000 // total
        item["acumulado_bp"] = acumulado * 10000 // total
        item["classe"] = classe
        saida.append(item)
    return saida


def _ticket(operador: dict) -> dict:
    vendas = int(operador["vendas"])
    operador["ticket_medio_cent"] = round(operador["faturamento_cent"] / vendas) if vendas else 0
    return operador


def _qtd(valor) -> float:
    try:
        return round(float(valor or 0), 4)
    except (TypeError, ValueError):
        return 0.0


def _ativo(produto: dict) -> bool:
    return bool(produto.get("ativo")) and produto.get("ativo") != "N"


def _controla(produto: dict) -> bool:
    return bool(produto.get("controla_estoque")) and produto.get("controla_estoque") != "N"


def sugerir_compra(catalogo: dict, vendas: list[dict], inicio: date, fim: date) -> dict:
    """Estoque baixo, parado e compra para cobrir 7 dias no ritmo do período."""
    if not catalogo["tem_cadastro"]:
        return {"disponivel": False,
                "nota": "A loja ainda não enviou o cadastro. No caixa, ligue a retaguarda em Configurações > Nuvem.",
                "baixo": [], "parados": [], "sugestao": []}
    nomes = _nomes_categoria(catalogo)
    vendido: dict[str, float] = {}
    for venda in vendas:
        if venda.get("status") != "fechada":
            continue
        for item in _itens_validos(venda):
            codigo = str(item.get("codigo") or "").strip()
            nome = _norm(item.get("nome"))
            chave = "c:" + codigo if codigo else "n:" + nome
            vendido[chave] = vendido.get(chave, 0.0) + float(item.get("quantidade") or 0)
    dias = max((fim - inicio).days + 1, 1)
    baixo, parados, sugestao = [], [], []
    for produto in catalogo["produtos"]:
        if not _ativo(produto) or not _controla(produto):
            continue
        codigo = str(produto.get("codigo") or "").strip()
        nome = str(produto.get("nome") or "")
        chave = "c:" + codigo if codigo else "n:" + _norm(nome)
        qtd_venda = vendido.get(chave, 0.0)
        saldo = _qtd(produto.get("qt_atual"))
        minimo = _qtd(produto.get("estoque_minimo"))
        sub, grupo = nomes.get(produto.get("subgrupo_id"), ("", ""))
        base = {"id": produto.get("id"), "codigo": codigo, "nome": nome, "grupo": grupo, "subgrupo": sub,
                "qt_atual": saldo, "estoque_minimo": minimo, "vendido": round(qtd_venda, 4),
                "preco_cent": int(produto.get("preco_cent") or 0)}
        if saldo <= minimo:
            baixo.append(base)
        if qtd_venda <= 0 and saldo > 0 and dias >= COBERTURA_DIAS:
            parado = dict(base)
            parado["valor_parado_cent"] = fmt.mult_cent(int(produto.get("preco_cent") or 0), saldo)
            parados.append(parado)
        media = qtd_venda / dias
        if media > 0:
            falta = media * COBERTURA_DIAS - saldo
            if falta > 0.0001 or saldo <= minimo:
                comprar = int(fmt._dec(max(falta, 0)).quantize(Decimal(1), rounding=ROUND_CEILING))
                if saldo <= minimo and comprar < 1 and minimo > saldo:
                    comprar = int(fmt._dec(minimo - saldo).quantize(Decimal(1), rounding=ROUND_CEILING)) or 1
                if comprar > 0:
                    item = dict(base)
                    item["comprar"] = comprar
                    item["cobertura_dias"] = COBERTURA_DIAS
                    sugestao.append(item)
    baixo.sort(key=lambda i: (i["qt_atual"], i["nome"]))
    parados.sort(key=lambda i: (-i["valor_parado_cent"], i["nome"]))
    sugestao.sort(key=lambda i: (-i["comprar"], i["nome"]))
    nota = "Compra para cobrir 7 dias no ritmo deste período."
    if dias < COBERTURA_DIAS:
        nota = "Período curto: a sugestão usa o ritmo desses dias. Parados pedem pelo menos 7 dias."
        parados = []
    return {"disponivel": True, "nota": nota, "dias": dias, "atualizado_em": catalogo["quando"],
            "baixo": baixo[:LIMITE_LINHAS], "parados": parados[:LIMITE_LINHAS], "sugestao": sugestao[:LIMITE_LINHAS]}


def _colunas(pares: list[tuple[str, str]]) -> list[dict]:
    return [{"chave": c, "rotulo": r} for c, r in pares]


def montar_relatorio(tipo: str, vendas: list[dict], catalogo: dict, inicio: date, fim: date,
                     retratos: list[dict] | None = None) -> dict:
    agregado = _agregar(vendas)
    tem = agregado["tem_custo"]
    base = {"tipo": tipo, "de": inicio.isoformat(), "ate": fim.isoformat(), "custo_visivel": True,
            "tem_custo": tem, "loja_cadastro": catalogo["tem_cadastro"]}
    if tipo == "resumo":
        produtos = []
        for bruto in agregado["produtos"][:5]:
            item = _com_lucro(dict(bruto), bool(bruto.get("tem_custo")))
            item["quantidade"] = round(item["quantidade"], 4)
            produtos.append(item)
        base.update({
            "faturamento_cent": agregado["faturamento_cent"], "vendas": agregado["fechadas"],
            "canceladas": agregado["canceladas"], "ticket_medio_cent": agregado["ticket_medio_cent"],
            "desconto_cent": agregado["desconto_cent"], "top_produtos": produtos,
            "por_hora": agregado["por_hora"],
            "colunas": _colunas([("nome", "Produto"), ("quantidade", "Quantidade"), ("valor_cent", "Faturamento")]),
            "linhas": produtos,
        })
        return base
    if tipo == "vendas":
        base.update({"por_dia": agregado["por_dia"], "por_hora": agregado["por_hora"],
                     "faturamento_cent": agregado["faturamento_cent"], "vendas": agregado["fechadas"],
                     "ticket_medio_cent": agregado["ticket_medio_cent"],
                     "colunas": _colunas([("dia", "Dia"), ("vendas", "Vendas"), ("faturamento_cent", "Faturamento")]),
                     "linhas": agregado["por_dia"]})
        return base
    if tipo == "produtos":
        linhas = []
        for bruto in agregado["produtos"][:LIMITE_LINHAS]:
            item = _com_lucro(dict(bruto), bool(bruto.get("tem_custo")))
            item["quantidade"] = round(item["quantidade"], 4)
            linhas.append(item)
        base.update({"linhas": linhas, "colunas": _colunas([
            ("codigo", "Código"), ("nome", "Produto"), ("grupo", "Categoria"), ("quantidade", "Quantidade"),
            ("valor_cent", "Faturamento"), ("custo_cent", "Custo"), ("lucro_cent", "Lucro"), ("margem", "Margem")])})
        return base
    if tipo == "categorias":
        linhas = []
        for bruto in agregado["categorias"]:
            item = _com_lucro(dict(bruto), tem)
            item["quantidade"] = round(item["quantidade"], 4)
            linhas.append(item)
        base.update({"linhas": linhas, "colunas": _colunas([
            ("categoria", "Categoria"), ("quantidade", "Quantidade"), ("valor_cent", "Faturamento"),
            ("lucro_cent", "Lucro"), ("margem", "Margem")])})
        return base
    if tipo == "abc":
        preparados = []
        for bruto in agregado["produtos"]:
            if int(bruto["valor_cent"]) <= 0:
                continue
            item = _com_lucro(dict(bruto), bool(bruto.get("tem_custo")))
            item["quantidade"] = round(item["quantidade"], 4)
            preparados.append(item)
        linhas = classificar_abc(preparados, "valor_cent")[:LIMITE_LINHAS]
        contagem = {"A": 0, "B": 0, "C": 0}
        for linha in linhas:
            contagem[linha["classe"]] = contagem.get(linha["classe"], 0) + 1
        base.update({
            "criterio": "faturamento",
            "nota": "Classe pelo faturamento: A até 80%, B até 95%, C o restante. "
                    + ("O lucro está na coluna ao lado." if tem else "O caixa ainda não enviou custo nestas vendas."),
            "classes": contagem, "linhas": linhas,
            "colunas": _colunas([
                ("classe", "Classe"), ("nome", "Produto"), ("grupo", "Categoria"), ("quantidade", "Quantidade"),
                ("valor_cent", "Faturamento"), ("lucro_cent", "Lucro"), ("margem", "Margem")]),
        })
        return base
    if tipo == "formas":
        base.update({"linhas": agregado["formas"], "colunas": _colunas([
            ("tipo", "Forma"), ("vezes", "Vezes"), ("valor_cent", "Valor")])})
        return base
    if tipo == "operadores":
        linhas = [_ticket(dict(o)) for o in agregado["operadores"]]
        base.update({"linhas": linhas, "colunas": _colunas([
            ("operador", "Operador"), ("vendas", "Vendas"), ("faturamento_cent", "Faturamento"),
            ("ticket_medio_cent", "Ticket médio"), ("desconto_cent", "Descontos")])})
        return base
    if tipo == "estoque":
        estoque = sugerir_compra(catalogo, vendas, inicio, fim)
        base.update(estoque)
        base["linhas"] = estoque["sugestao"]
        base["colunas"] = _colunas([
            ("codigo", "Código"), ("nome", "Produto"), ("grupo", "Categoria"), ("qt_atual", "Estoque"),
            ("estoque_minimo", "Mínimo"), ("vendido", "Vendido no período"), ("comprar", "Comprar")])
        return base
    if tipo == "caixa":
        return {**base, **_caixa(retratos or [], inicio, fim)}
    raise ErroNegocio("Relatório desconhecido.")


def _caixa(retratos: list[dict], inicio: date, fim: date) -> dict:
    de, ate = inicio.isoformat(), fim.isoformat()
    fechamentos, sangrias = [], []
    for dados in retratos:
        if not isinstance(dados, dict):
            continue
        caixa = str(dados.get("terminal_rotulo") or dados.get("terminal") or "")
        for item in dados.get("fechamentos") or []:
            if isinstance(item, dict) and de <= str(item.get("dia") or "")[:10] <= ate:
                linha = {k: item.get(k) for k in (
                    "dia", "turno_numero", "operador", "fechado_em", "valor_inicial_cent", "valor_final_cent",
                    "esperado_cent", "resultado_cent", "sangrias_cent", "suprimentos_cent")}
                linha["caixa"] = caixa
                fechamentos.append(linha)
        for item in dados.get("sangrias") or []:
            if isinstance(item, dict) and de <= str(item.get("dia") or "")[:10] <= ate:
                sangrias.append({
                    "dia": str(item.get("dia") or "")[:10], "criado_em": item.get("criado_em") or "",
                    "operador": item.get("operador") or "", "turno_numero": item.get("turno_numero"),
                    "valor_cent": int(item.get("valor_cent") or 0), "descricao": str(item.get("descricao") or "")[:80],
                    "caixa": caixa,
                })
    fechamentos.sort(key=lambda i: (i.get("dia") or "", i.get("fechado_em") or ""))
    sangrias.sort(key=lambda i: i.get("criado_em") or "")
    return {
        "nota": "Fechamentos e sangrias vêm do último retrato de cada caixa (cerca de 31 dias). "
                "Um caixa antigo pode não enviar esta lista.",
        "fechamentos": fechamentos[:LIMITE_LINHAS], "sangrias": sangrias[:LIMITE_LINHAS],
        "linhas": fechamentos[:LIMITE_LINHAS],
        "colunas": _colunas([
            ("dia", "Dia"), ("caixa", "Caixa"), ("turno_numero", "Turno"), ("operador", "Operador"),
            ("resultado_cent", "Sobra ou falta"), ("sangrias_cent", "Sangrias"), ("suprimentos_cent", "Suprimentos")]),
    }


def montar_rede(por_loja: list[dict], totais: dict) -> dict:
    linhas = []
    for loja in por_loja:
        vendas = int(loja.get("vendas") or 0)
        fat = int(loja.get("faturamento_cent") or 0)
        linhas.append({
            "loja": loja.get("nome") or loja.get("chave"), "chave": loja.get("chave"),
            "vendas": vendas, "faturamento_cent": fat,
            "ticket_medio_cent": loja.get("ticket_medio_cent", round(fat / vendas) if vendas else 0),
            "lucro_cent": loja.get("lucro_cent"), "margem": loja.get("margem"),
        })
    return {"tipo": "rede", "custo_visivel": True, "linhas": linhas, "totais": {
        "faturamento_cent": totais.get("faturamento_cent"), "lucro_cent": totais.get("lucro_cent"),
        "vendas": sum(l["vendas"] for l in linhas),
    }, "colunas": _colunas([
        ("loja", "Loja"), ("vendas", "Vendas"), ("faturamento_cent", "Faturamento"),
        ("ticket_medio_cent", "Ticket médio"), ("lucro_cent", "Lucro"), ("margem", "Margem")])}


def _celula(coluna: str, valor) -> str:
    if valor is None:
        return ""
    if coluna.endswith("_cent") and isinstance(valor, int):
        return fmt.fmt_num(valor)
    if isinstance(valor, float):
        return fmt.fmt_qtd(valor, 4).rstrip("0").rstrip(",") or "0"
    return str(valor)


def exportar(relatorio: dict, formato: str) -> Response:
    colunas = relatorio.get("colunas") or []
    linhas = relatorio.get("linhas") or []
    cabeca = [c["rotulo"] for c in colunas]
    grade = [cabeca] + [[_celula(c["chave"], linha.get(c["chave"])) for c in colunas] for linha in linhas]
    nome = f"relatorio-{relatorio.get('tipo') or 'painel'}"
    if formato == "csv":
        buf = io.StringIO()
        grade = [[texto_planilha(celula) for celula in linha] for linha in grade]
        csv.writer(buf, delimiter=";", lineterminator="\n").writerows(grade)
        return Response(("\ufeff" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="{nome}.csv"'})
    if formato == "xlsx":
        from src.controllers.importacao_produtos import escrever_xlsx
        return Response(escrever_xlsx(grade), headers={
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "Content-Disposition": f'attachment; filename="{nome}.xlsx"'})
    raise HTTPException(status_code=422, detail="Formato inválido: use json, csv ou xlsx.")


# ---------------------------------------------------------------- cadastros (prévia e fila)
def _produto_publico(produto: dict, nomes: dict[int, tuple[str, str]]) -> dict:
    sub, grupo = nomes.get(produto.get("subgrupo_id"), ("", ""))
    return {
        "id": produto.get("id"), "codigo": str(produto.get("codigo") or ""), "nome": str(produto.get("nome") or ""),
        "preco_cent": int(produto.get("preco_cent") or 0), "custo_medio_cent": int(produto.get("custo_medio_cent") or 0),
        "qt_atual": _qtd(produto.get("qt_atual")), "estoque_minimo": _qtd(produto.get("estoque_minimo")),
        "grupo": grupo, "subgrupo": sub, "subgrupo_id": produto.get("subgrupo_id"),
        "codigo_barras": re.sub(r"\D", "", str(produto.get("cbarra") or "")),
        "ativo": _ativo(produto), "controla_estoque": _controla(produto),
    }


def filtrar_produtos(catalogo: dict, busca: str) -> list[dict]:
    nomes = _nomes_categoria(catalogo)
    termo = _norm(busca)
    barras = re.sub(r"\D", "", busca or "")
    saida = []
    for produto in catalogo["produtos"]:
        pub = _produto_publico(produto, nomes)
        if not termo:
            saida.append(pub)
            continue
        alvo = _norm(pub["nome"]) + " " + _norm(pub["codigo"]) + " " + _norm(pub["grupo"])
        if termo in alvo or (barras and barras == pub["codigo_barras"]):
            saida.append(pub)
    return saida


def _achar(produtos: list[dict], item: dict) -> dict:
    if not isinstance(item, dict):
        raise ErroNegocio("Cada alteração precisa ser um objeto.")
    if item.get("id") is not None:
        ident = _inteiro(item["id"], "Produto")
        achados = [p for p in produtos if p.get("id") == ident]
    else:
        barras = re.sub(r"\D", "", str(item.get("codigo_barras") or ""))
        if barras:
            achados = [p for p in produtos if re.sub(r"\D", "", str(p.get("cbarra") or "")) == barras]
        else:
            nome = _norm(item.get("nome"))
            if not nome:
                raise ErroNegocio("Informe o id, o código de barras ou o nome do produto.")
            achados = [p for p in produtos if _norm(p.get("nome")) == nome]
    if not achados:
        raise ErroNegocio("Produto não encontrado no cadastro que o caixa enviou.")
    if len(achados) > 1:
        raise ErroNegocio("Há mais de um produto com esse nome ou código. Use o id.")
    return achados[0]


def _valores_lote(item: dict, subgrupos: set[int]) -> dict:
    desconhecidos = [k for k in item if k not in CAMPOS_LOTE and k not in ("id", "nome", "codigo_barras")]
    if desconhecidos:
        raise ErroNegocio(f"Campo não editável por aqui: {desconhecidos[0]}.")
    valores = {}
    if "preco_cent" in item:
        valores["preco_cent"] = _centavos(item["preco_cent"], "Preço")
    if "custo_medio_cent" in item:
        valores["custo_medio_cent"] = _centavos(item["custo_medio_cent"], "Custo")
    if "estoque_minimo" in item:
        valores["estoque_minimo"] = _quantidade(item["estoque_minimo"], "Estoque mínimo")
    if "subgrupo_id" in item:
        ident = _inteiro(item["subgrupo_id"], "Categoria")
        if ident not in subgrupos:
            raise ErroNegocio("Categoria (subgrupo) não existe nesta loja.")
        valores["subgrupo_id"] = ident
    if "ativo" in item:
        bruto = item["ativo"]
        if bruto in (1, True, "1", "S", "s"):
            valores["ativo"] = 1
        elif bruto in (0, False, "0", "N", "n"):
            valores["ativo"] = 0
        else:
            raise ErroNegocio("Ativo: use 1 ou 0.")
    if not valores:
        raise ErroNegocio("Nada para alterar. Informe preço, custo, estoque mínimo, categoria ou ativo.")
    return valores


def previa_precos(catalogo: dict, itens: list) -> list[dict]:
    if not catalogo["tem_cadastro"]:
        raise ErroNegocio("A loja ainda não enviou o cadastro. Ligue a retaguarda no caixa.")
    if not isinstance(itens, list) or not itens:
        raise ErroNegocio("Informe ao menos um produto.")
    if len(itens) > 1000:
        raise ErroNegocio("No máximo 1000 produtos por pedido.")
    subgrupos = {s.get("id") for s in catalogo["subgrupos"] if isinstance(s.get("id"), int)}
    saida = []
    for n, item in enumerate(itens, start=1):
        try:
            produto = _achar(catalogo["produtos"], item)
            valores = _valores_lote(item, subgrupos)
        except ErroNegocio as erro:
            raise ErroNegocio(f"Item {n}: {erro}") from None
        antes = {k: produto.get(k) for k in valores}
        if any(not _mesmo(antes.get(k), valores[k]) for k in valores):
            saida.append({"id": produto.get("id"), "nome": str(produto.get("nome") or ""), "valores": valores, "antes": antes})
    if not saida:
        raise ErroNegocio("Nada mudou em relação ao cadastro que o caixa enviou.")
    return saida


def _produtos_da_categoria(catalogo: dict, categoria: str) -> list[dict]:
    alvo = _norm(categoria)
    if not alvo:
        raise ErroNegocio("Informe a categoria (nome do grupo ou do subgrupo).")
    nomes = _nomes_categoria(catalogo)
    grupos = {_norm(g.get("nome")): g.get("id") for g in catalogo["grupos"] if _norm(g.get("nome"))}
    sub_por_nome: dict[str, list[int]] = {}
    for sub in catalogo["subgrupos"]:
        if isinstance(sub.get("id"), int):
            sub_por_nome.setdefault(_norm(sub.get("nome")), []).append(sub["id"])
    ids: set[int] = set()
    if alvo in grupos:
        grupo_id = grupos[alvo]
        ids = {s.get("id") for s in catalogo["subgrupos"] if s.get("grupo_id") == grupo_id and isinstance(s.get("id"), int)}
    elif alvo in sub_por_nome and len(sub_por_nome[alvo]) == 1:
        ids = set(sub_por_nome[alvo])
    else:
        for sub_id, (sub, grupo) in nomes.items():
            if _norm(f"{sub} - {grupo}") == alvo or _norm(f"{sub}-{grupo}") == alvo:
                ids.add(sub_id)
    if not ids:
        if alvo in sub_por_nome and len(sub_por_nome[alvo]) > 1:
            raise ErroNegocio("Há mais de um subgrupo com esse nome. Use \"Subgrupo - Grupo\".")
        raise ErroNegocio("Categoria não encontrada no cadastro da loja.")
    return [p for p in catalogo["produtos"] if p.get("subgrupo_id") in ids and _ativo(p)]


def previa_reajuste(catalogo: dict, categoria: str, percentual: Decimal) -> list[dict]:
    if not catalogo["tem_cadastro"]:
        raise ErroNegocio("A loja ainda não enviou o cadastro. Ligue a retaguarda no caixa.")
    saida = []
    for produto in _produtos_da_categoria(catalogo, categoria):
        antes = int(produto.get("preco_cent") or 0)
        if antes <= 0:
            continue
        novo = preco_reajustado(antes, percentual)
        if novo == antes:
            continue
        saida.append({"id": produto.get("id"), "nome": str(produto.get("nome") or ""),
                      "antes": {"preco_cent": antes}, "valores": {"preco_cent": novo}})
    if not saida:
        raise ErroNegocio("Nenhum produto ativo com preço nessa categoria.")
    return saida


def previa_estoque(catalogo: dict, corpo: dict) -> dict:
    if not catalogo["tem_cadastro"]:
        raise ErroNegocio("A loja ainda não enviou o cadastro. Ligue a retaguarda no caixa.")
    tipo = str(corpo.get("tipo") or "")
    if tipo not in TIPOS_ESTOQUE:
        raise ErroNegocio("Tipo de movimento inválido. Use entrada, saida, contagem, quebra ou descarte.")
    quantidade = _quantidade(corpo.get("quantidade"), "Quantidade")
    if quantidade == 0 and tipo != "contagem":
        raise ErroNegocio("Informe a quantidade do movimento.")
    motivo = re.sub(r"\s+", " ", str(corpo.get("motivo") or "")).strip()
    if len(motivo) < 3 or len(motivo) > 80:
        raise ErroNegocio("Informe o motivo, com 3 a 80 caracteres.")
    produto = _achar(catalogo["produtos"], corpo)
    if not _controla(produto):
        raise ErroNegocio("Este produto não controla estoque.")
    return {"produto_id": produto.get("id"), "nome": str(produto.get("nome") or ""), "tipo": tipo,
            "quantidade": quantidade, "motivo": motivo, "qt_atual": _qtd(produto.get("qt_atual"))}


def _mesmo(antes, depois) -> bool:
    if isinstance(antes, (int, float)) or isinstance(depois, (int, float)):
        try:
            return abs(float(antes or 0) - float(depois or 0)) < 0.0001
        except (TypeError, ValueError):
            return False
    return antes == depois


def _fatiar(alteracoes: list[dict], inicio: int) -> tuple[list[dict], int]:
    if inicio < 0 or inicio > len(alteracoes):
        raise ErroNegocio("Início do lote inválido.")
    lote = alteracoes[inicio:inicio + LIMITE_ENVIO]
    return lote, inicio + len(lote)


def _enfileirar(db: Session, chave: str, autor: str, comandos: list[tuple[str, dict, str]]) -> list[int]:
    from backend.retaguarda import LIMITE_PENDENTES, criar, pendentes
    livres = LIMITE_PENDENTES - pendentes(db, chave)
    if len(comandos) > livres:
        raise HTTPException(
            status_code=409,
            detail=f"A fila só tem espaço para mais {max(livres, 0)} alteração(ões). "
                   "Espere o caixa aplicar o que já está aguardando.")
    ids = []
    for tipo, dados, resumo in comandos:
        comando = criar(db, chave, {"tipo": tipo, "dados": dados, "resumo": resumo}, autor)
        ids.append(comando.id)
    return ids


def _resumo_preco(nome: str, antes: dict, valores: dict) -> str:
    partes = [nome]
    if "preco_cent" in valores:
        partes.append(f"{fmt.fmt_brl(antes.get('preco_cent'))} → {fmt.fmt_brl(valores['preco_cent'])}")
    if "subgrupo_id" in valores:
        partes.append("categoria")
    if "estoque_minimo" in valores:
        partes.append("estoque mínimo")
    if "ativo" in valores:
        partes.append("inativar" if valores["ativo"] == 0 else "reativar")
    if "custo_medio_cent" in valores:
        partes.append("custo")
    return "Preço: " + ", ".join(partes)


def _resposta_lote(alteracoes: list[dict], inicio: int, aplicar: bool, db, chave, autor) -> dict:
    if not aplicar:
        inicio = 0
    lote, proximo = _fatiar(alteracoes, inicio)
    if aplicar and not lote:
        raise ErroNegocio("Não há mais produtos neste lote.")
    visiveis = alteracoes if not aplicar else lote
    corpo = {"dry_run": not aplicar, "total": len(alteracoes), "mostrando": len(visiveis), "inicio": inicio,
             "proximo": proximo if aplicar else 0, "faltam": max(len(alteracoes) - proximo, 0) if aplicar else 0,
             "alteracoes": [{**a, "resumo": _resumo_preco(a["nome"], a["antes"], a["valores"])} for a in visiveis]}
    if not aplicar:
        corpo["aviso"] = "Nada foi gravado. Envie de novo com dry_run false para o caixa aplicar."
        if len(corpo["alteracoes"]) > 80:
            corpo["alteracoes"] = corpo["alteracoes"][:80]
            corpo["mostrando"] = len(corpo["alteracoes"])
        return corpo
    comandos = []
    for item in lote:
        comandos.append(("cadastro.salvar", {"entidade": "produtos", "id": item["id"], "valores": item["valores"]},
                         _resumo_preco(item["nome"], item["antes"], item["valores"])[:200]))
    corpo["comandos"] = _enfileirar(db, chave, autor, comandos)
    corpo["enviados"] = len(corpo["comandos"])
    corpo["aviso"] = "Enviado ao caixa. Ele aplica na próxima sincronização."
    if corpo["faltam"]:
        corpo["aviso"] += f" Faltam {corpo['faltam']}. Envie de novo com inicio {proximo}."
    return corpo


# ---------------------------------------------------------------- rotas
def instalar(router: APIRouter, Loja) -> None:
    from backend.importacao_painel import AcessoImportacao, PainelTokenApi

    def acesso(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> AcessoImportacao:
        painel = _painel()
        token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
        if not token:
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        if token.startswith("wpdv_"):
            linha = db.query(PainelTokenApi).filter_by(token_hash=painel._hash(token), revogado_em=None).first()
            if linha is None:
                raise HTTPException(status_code=401, detail="Token inválido ou revogado.")
            linha.ultimo_uso = _agora()
            db.commit()
            return AcessoImportacao("token", linha.chave_loja, None, f"token:{linha.nome}"[:60])
        sessao = db.query(painel.PainelSessao).filter_by(token_hash=painel._hash(token)).first()
        if sessao is None or sessao.expira_em <= _agora():
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        sessao.ultimo_uso = _agora()
        db.commit()
        if sessao.grupo_id:
            return AcessoImportacao("sessao", None, sessao.grupo_id, "dono")
        from backend.memoria_nuvem import memoria
        memoria.lembrar_sessao(token, sessao.chave_loja)
        return AcessoImportacao("sessao", sessao.chave_loja, None, "dono")

    def loja_de(db: Session, quem: AcessoImportacao, pedida: str | None) -> str:
        pedida = str(pedida or "").strip()
        if quem.tipo == "token":
            if pedida and pedida != quem.chave_loja:
                raise HTTPException(status_code=403, detail="Este token é de outra loja.")
            return quem.chave_loja or ""
        if quem.grupo_id:
            if not pedida:
                raise HTTPException(status_code=422, detail="Escolha a loja de destino.")
            loja = db.query(Loja).filter(Loja.chave_loja == pedida, Loja.grupo_id == quem.grupo_id,
                                         Loja.ativa.is_(True)).first()
            if loja is None:
                raise HTTPException(status_code=404, detail="Esta loja não está na sua rede.")
            return pedida
        if not quem.chave_loja:
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        if pedida and pedida != quem.chave_loja:
            raise HTTPException(status_code=403, detail="A sessão é de outra loja.")
        loja = db.query(Loja).filter(Loja.chave_loja == quem.chave_loja, Loja.ativa.is_(True)).first()
        if loja is None:
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        return quem.chave_loja

    def _grupo(db: Session, quem: AcessoImportacao):
        from backend.grupos import Grupo
        if not quem.grupo_id:
            raise HTTPException(status_code=422, detail="O comparativo entre lojas abre com a senha da rede (?grupo=).")
        grupo = db.get(Grupo, quem.grupo_id)
        if grupo is None:
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        return grupo

    def _retratos(db: Session, chave: str) -> list[dict]:
        return [dados for _, dados in _painel()._ler_caixas(db, chave)]

    @router.get(PREFIXO + "/resumo")
    def resumo(de: str = Query("", max_length=10), ate: str = Query("", max_length=10),
               loja: str = Query("", max_length=64), quem: AcessoImportacao = Depends(acesso),
               db: Session = Depends(get_db)):
        chave = loja_de(db, quem, loja)
        inicio, fim = _periodo(de or None, ate or None)
        rel = montar_relatorio("resumo", _vendas(db, chave, inicio, fim), _catalogo(db, chave), inicio, fim)
        rel["loja"] = chave
        return rel

    @router.get(PREFIXO + "/relatorio")
    def relatorio(tipo: str = Query("resumo", max_length=20), de: str = Query("", max_length=10),
                  ate: str = Query("", max_length=10), formato: str = Query("json", max_length=8),
                  loja: str = Query("", max_length=64), quem: AcessoImportacao = Depends(acesso),
                  db: Session = Depends(get_db)):
        if tipo not in TIPOS:
            raise HTTPException(status_code=422, detail="Relatório inválido. Veja docs/api-assistente.md.")
        inicio, fim = _periodo(de or None, ate or None)
        if tipo == "rede":
            from backend.grupos import consolidado
            grupo = _grupo(db, quem)
            bruto = consolidado(db, grupo, inicio, fim)
            rel = montar_rede(bruto.get("por_loja") or [], bruto)
            rel.update({"de": inicio.isoformat(), "ate": fim.isoformat(), "tem_custo": bruto.get("cmv_sincronizado")})
        else:
            chave = loja_de(db, quem, loja)
            rel = montar_relatorio(tipo, _vendas(db, chave, inicio, fim), _catalogo(db, chave), inicio, fim,
                                   _retratos(db, chave))
            rel["loja"] = chave
        if formato == "json":
            return rel
        return exportar(rel, formato)

    @router.get(PREFIXO + "/painel")
    def painel_gestao(de: str = Query(..., max_length=10), ate: str = Query(..., max_length=10),
                      loja: str = Query("", max_length=64), quem: AcessoImportacao = Depends(acesso),
                      db: Session = Depends(get_db)):
        """O que a aba Relatórios desenha numa chamada só."""
        chave = loja_de(db, quem, loja)
        inicio, fim = _periodo(de, ate)
        vendas = _vendas(db, chave, inicio, fim)
        catalogo = _catalogo(db, chave)
        blocos = {tipo: montar_relatorio(tipo, vendas, catalogo, inicio, fim, _retratos(db, chave))
                  for tipo in ("abc", "categorias", "operadores", "vendas", "estoque")}
        from backend.retaguarda import historico
        aud = historico(db, chave)["comandos"][:8]
        return {"loja": chave, "de": inicio.isoformat(), "ate": fim.isoformat(), "custo_visivel": True,
                "abc": blocos["abc"], "categorias": blocos["categorias"], "operadores": blocos["operadores"],
                "vendas": blocos["vendas"], "estoque": blocos["estoque"], "auditoria": aud}

    @router.get(PREFIXO + "/produtos")
    def produtos(q: str = Query("", max_length=80), loja: str = Query("", max_length=64),
                 quem: AcessoImportacao = Depends(acesso), db: Session = Depends(get_db)):
        chave = loja_de(db, quem, loja)
        catalogo = _catalogo(db, chave)
        if not catalogo["tem_cadastro"]:
            raise HTTPException(status_code=409, detail="A loja ainda não enviou o cadastro. Ligue a retaguarda no caixa.")
        lista = filtrar_produtos(catalogo, q)
        return {"loja": chave, "total": len(lista), "custo_visivel": True, "atualizado_em": catalogo["quando"],
                "produtos": lista[:50]}

    @router.get(PREFIXO + "/auditoria")
    def auditoria(limite: int = Query(30, ge=1, le=150), loja: str = Query("", max_length=64),
                  quem: AcessoImportacao = Depends(acesso), db: Session = Depends(get_db)):
        from backend.retaguarda import historico
        chave = loja_de(db, quem, loja)
        comandos = historico(db, chave)["comandos"][:limite]
        return {"loja": chave, "comandos": comandos,
                "nota": "Quem pediu, quando, e se o caixa já aplicou. A senha de operador não aparece."}

    def _aplicar_flag(corpo: dict) -> bool:
        return corpo.get("dry_run") is False

    @router.post(PREFIXO + "/precos")
    def precos(corpo: dict = Body(...), quem: AcessoImportacao = Depends(acesso), db: Session = Depends(get_db)):
        chave = loja_de(db, quem, corpo.get("loja"))
        try:
            alteracoes = previa_precos(_catalogo(db, chave), corpo.get("itens"))
            inicio = _inteiro(corpo.get("inicio") or 0, "Início") if corpo.get("inicio") not in (None, "") else 0
            resposta = _resposta_lote(alteracoes, inicio, _aplicar_flag(corpo), db, chave, quem.autor)
        except ErroNegocio as erro:
            raise _erro_http(erro) from None
        resposta["loja"] = chave
        return resposta

    @router.post(PREFIXO + "/reajuste")
    def reajuste(corpo: dict = Body(...), quem: AcessoImportacao = Depends(acesso), db: Session = Depends(get_db)):
        chave = loja_de(db, quem, corpo.get("loja"))
        try:
            percentual = _percentual(corpo.get("percentual"))
            alteracoes = previa_reajuste(_catalogo(db, chave), str(corpo.get("categoria") or ""), percentual)
            inicio = _inteiro(corpo.get("inicio") or 0, "Início") if corpo.get("inicio") not in (None, "") else 0
            resposta = _resposta_lote(alteracoes, inicio, _aplicar_flag(corpo), db, chave, quem.autor)
        except ErroNegocio as erro:
            raise _erro_http(erro) from None
        resposta["loja"] = chave
        resposta["categoria"] = str(corpo.get("categoria") or "")
        resposta["percentual"] = str(corpo.get("percentual"))
        return resposta

    @router.post(PREFIXO + "/estoque")
    def estoque(corpo: dict = Body(...), quem: AcessoImportacao = Depends(acesso), db: Session = Depends(get_db)):
        chave = loja_de(db, quem, corpo.get("loja"))
        try:
            previa = previa_estoque(_catalogo(db, chave), corpo)
        except ErroNegocio as erro:
            raise _erro_http(erro) from None
        aplicar = _aplicar_flag(corpo)
        resposta = {"loja": chave, "dry_run": not aplicar, **previa}
        if not aplicar:
            resposta["aviso"] = "Nada foi gravado. Envie de novo com dry_run false para o caixa aplicar."
            return resposta
        rotulo = {"entrada": "entrada", "saida": "saída", "contagem": "contagem", "quebra": "quebra", "descarte": "descarte"}
        resumo = f"Estoque: {rotulo[previa['tipo']]} de {previa['quantidade']} em {previa['nome']} ({previa['motivo']})"
        resposta["comandos"] = _enfileirar(db, chave, quem.autor, [(
            "estoque.movimento",
            {"produto_id": previa["produto_id"], "tipo": previa["tipo"], "quantidade": previa["quantidade"],
             "descricao": previa["motivo"]},
            resumo[:200])])
        resposta["aviso"] = "Enviado ao caixa. Ele aplica na próxima sincronização. Repetir este pedido lança de novo."
        return resposta
