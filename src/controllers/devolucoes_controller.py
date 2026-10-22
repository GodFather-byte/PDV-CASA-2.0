"""Devolução (parcial ou total) de venda FECHADA, ligada ao cupom original (docs/DEVOLUCOES.md).

Regras:
  * A venda original, seus pagamentos e o bruto histórico NUNCA são alterados: a devolução é um registro novo e
    imutável (tabelas `devolucoes`, `devolucoes_itens`), datado e contado no turno em que o reembolso foi feito.
  * O valor devolvido rateia o desconto e o serviço reais da venda por item (centavos inteiros, maior resto, ordem
    do item); taxa de entrega/consumação e acréscimo da forma ("extras") só voltam na devolução que completa a venda.
    A soma das devoluções nunca passa do total líquido efetivamente pago.
  * Reembolso explícito: dinheiro da gaveta (gera saída em `movimentos_caixa`), externo (Pix/cartão: o estorno é feito
    fora do PDV e só a referência informada fica registrada; o PDV NÃO chama banco/adquirente) ou crédito na caderneta
    (venda a prazo). Retorno ao estoque é opcional por item e nunca devolve mais do que a venda baixou.
  * `uuid` é a chave de idempotência: repetir o mesmo pedido (duplo clique, nova tentativa) devolve o registro existente.
  * Troca = devolução marcada como troca + NOVA venda de balcão pelo próprio CaixaController (`abrir_troca`).
O fluxo de gravação entra sempre por CaixaController (devolver/abrir_troca); este módulo também oferece as consultas
para fechamento de turno e relatórios (`resumo_turno`, `listar`).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao

MODULO = "caixa_cancelamento"
ESCALA = 10 ** fmt.CASAS_QTD          # quantidades em unidades inteiras de 0,0001
MODOS = {"dinheiro_gaveta": "Dinheiro da gaveta", "externo": "Estorno externo (Pix/cartão)",
         "caderneta": "Crédito na caderneta"}
TIPO_ESTOQUE = "devolucao_venda"      # tipo e ref_tipo dos movimentos de estoque (não é perda nem venda)
MAX_MOTIVO = 300
MAX_REFERENCIA = 120


def _unidades(q, campo: str = "quantidade") -> int:
    try:
        d = Decimal(str(q).strip().replace(",", ".")) if isinstance(q, str) else Decimal(repr(float(q)))
    except (InvalidOperation, TypeError, ValueError):
        raise ErroNegocio(f"{campo.capitalize()} inválida.") from None
    if not d.is_finite():
        raise ErroNegocio(f"{campo.capitalize()} inválida.")
    escalado = d * ESCALA
    if escalado != escalado.to_integral_value():
        raise ErroNegocio(f"A {campo} aceita no máximo {fmt.CASAS_QTD} casas decimais.")
    return int(escalado)


def _qtd(unidades: int) -> float:
    return round(unidades / ESCALA, fmt.CASAS_QTD)


def ratear(total: int, pesos: list[tuple[object, int]]) -> dict:
    """Divide `total` centavos pelos pesos (maior resto; empate pela ordem da lista). Soma exata e determinística."""
    if not pesos:
        return {}
    soma = sum(max(p, 0) for _, p in pesos)
    if soma <= 0:
        pesos = [(k, 1) for k, _ in pesos]
        soma = len(pesos)
    base = {k: total * max(p, 0) // soma for k, p in pesos}
    sobra = total - sum(base.values())
    ordem = sorted(range(len(pesos)), key=lambda i: (-(total * max(pesos[i][1], 0) % soma), i))
    for i in ordem[:sobra]:
        base[pesos[i][0]] += 1
    return base


class DevolucoesController:
    def __init__(self, banco, operador_id: int | None = None, caixa=None):
        self.banco = banco
        self.operador_id = operador_id
        if caixa is None:
            from src.controllers.caixa_controller import CaixaController
            caixa = CaixaController(banco, operador_id)
        self.caixa = caixa

    # ========================================================== consultas
    def venda_por_cupom(self, cupom) -> dict:
        try:
            numero = int(str(cupom).strip())
        except (TypeError, ValueError):
            raise ErroNegocio("Informe o número do cupom.") from None
        r = self.banco.um("SELECT id FROM vendas WHERE cupom = ?", (numero,))
        if r is None:
            raise ErroNegocio(f"Cupom {numero} não encontrado.")
        return self.caixa.obter(r["id"])

    def _base(self, v: dict) -> dict:
        """Valor líquido de cada item devolvível com desconto e serviço reais da venda já rateados."""
        if v["status"] != "fechada":
            raise ErroNegocio("Só venda FECHADA aceita devolução." if v["status"] != "cancelada"
                              else "Este cupom está cancelado: não há o que devolver.")
        itens = self.caixa.itens(v["id"])
        cobrados = [i for i in itens if not (v["rodizio"] and i["rodizio_incluso"])]
        if not cobrados:
            raise ErroNegocio("Esta venda não tem itens cobrados por unidade para devolver "
                              "(crédito de caderneta, recarga ou só rodízio).")
        rodizio = v["rodizio_total_cent"] if v["rodizio"] else 0
        soma = sum(i["total_cent"] for i in cobrados) + rodizio
        extras_total = v["taxa_cent"] + v["acrescimo_cent"]
        if (soma != v["subtotal_cent"] or v["total_cent"] != v["subtotal_cent"] - v["desconto_cent"]
                + v["servico_cent"] + extras_total or v["desconto_cent"] > v["subtotal_cent"]):
            raise ErroNegocio("Os totais gravados desta venda não batem com os itens (venda antiga ou cadastro alterado). "
                              "Faça a devolução manualmente com o gerente.")
        pesos = [(i["id"], i["total_cent"]) for i in cobrados] + ([("rodizio", rodizio)] if rodizio else [])
        descontos = ratear(v["desconto_cent"], pesos)
        pesos_serv = [(i["id"], i["total_cent"]) for i in cobrados if i["cobra_servico"]]
        pesos_serv += [("rodizio", rodizio)] if rodizio else []
        servicos = ratear(v["servico_cent"], pesos_serv if sum(p for _, p in pesos_serv) > 0 else pesos)
        linhas = {}
        for i in cobrados:
            q = _unidades(fmt.arred_qtd(i["quantidade"]))
            if q <= 0:
                continue
            linhas[i["id"]] = {**i, "q_unid": q, "bruto": i["total_cent"], "desc": descontos.get(i["id"], 0),
                               "serv": servicos.get(i["id"], 0)}
        rod_liq = rodizio - descontos.get("rodizio", 0) + servicos.get("rodizio", 0)
        liquido_itens = sum(l["bruto"] - l["desc"] + l["serv"] for l in linhas.values())
        return {"venda": v, "itens": linhas, "rodizio_liquido": rod_liq,
                "extras": v["total_cent"] - liquido_itens - rod_liq}

    def _ja_devolvido(self, venda_id: int) -> tuple[dict, dict]:
        por_item = {r["item_id"]: {"unid": _unidades(fmt.arred_qtd(r["q"])), "bruto": r["b"], "desc": r["d"],
                                   "serv": r["s"], "valor": r["v"]}
                    for r in self.banco.todos(
                        """SELECT di.item_id, SUM(di.quantidade) AS q, SUM(di.bruto_cent) AS b, SUM(di.desconto_cent) AS d,
                                  SUM(di.servico_cent) AS s, SUM(di.valor_cent) AS v
                           FROM devolucoes_itens di JOIN devolucoes d ON d.id = di.devolucao_id
                           WHERE d.venda_id = ? GROUP BY di.item_id""", (venda_id,))}
        r = self.banco.um("SELECT COUNT(*) AS n, COALESCE(SUM(valor_cent), 0) AS valor, COALESCE(SUM(extras_cent), 0) AS "
                          "extras, COALESCE(MAX(completa), 0) AS completa FROM devolucoes WHERE venda_id = ?", (venda_id,))
        return por_item, dict(r)

    def _pago_liquido(self, v: dict) -> tuple[int, dict]:
        """Teto do reembolso: total da venda limitado ao que entrou de fato; e o líquido por forma (sem troco)."""
        por_forma: dict[int, int] = {}
        for p in self.caixa.pagamentos(v["id"]):
            por_forma[p["tipo_pagamento_id"]] = por_forma.get(p["tipo_pagamento_id"], 0) + p["valor_cent"] - p["troco_cent"]
        if v["modalidade"] == "caderneta":
            return v["total_cent"], por_forma
        return max(min(v["total_cent"], sum(por_forma.values()) - v["vale_cent"]), 0), por_forma
    def situacao(self, venda_id: int) -> dict:
        """Tudo que a tela precisa: itens com saldo devolvível, valores já devolvidos e modos de reembolso aceitos."""
        v = self.caixa.obter(venda_id)
        base = self._base(v)
        feito, tot = self._ja_devolvido(venda_id)
        baixa = self._baixa_restante(venda_id)
        itens = []
        for item_id, l in base["itens"].items():
            f = feito.get(item_id, {"unid": 0, "valor": 0})
            partes = self.banco.valor("SELECT COUNT(*) FROM itens_venda_partes WHERE item_id = ?", (item_id,), 0)
            itens.append({
                "item_id": item_id, "produto_id": l["produto_id"], "codigo": l["codigo"], "nome": l["nome"],
                "unidade": l["unidade"], "observacao": l["observacao"], "quantidade": _qtd(l["q_unid"]),
                "devolvida": _qtd(f["unid"]), "saldo": _qtd(l["q_unid"] - f["unid"]), "total_cent": l["bruto"],
                "desconto_cent": l["desc"], "servico_cent": l["serv"], "liquido_cent": l["bruto"] - l["desc"] + l["serv"],
                "devolvido_cent": f["valor"],
                "sugere_estoque": not partes and baixa.get(l["produto_id"], 0) > 0})
        teto, por_forma = self._pago_liquido(v)
        formas = []
        for tid, valor in por_forma.items():
            t = self.banco.um("SELECT tipo, na_gaveta FROM tipos_pagamento WHERE id = ?", (tid,))
            ext = self.banco.valor("SELECT COALESCE(SUM(valor_cent), 0) FROM devolucoes WHERE venda_id = ? AND "
                                   "reembolso_modo = 'externo' AND tipo_pagamento_id = ?", (venda_id, tid), 0)
            formas.append({"tipo_pagamento_id": tid, "tipo": t["tipo"], "na_gaveta": bool(t["na_gaveta"]),
                           "pago_cent": valor, "estornado_externo_cent": ext})
        return {"venda": v, "itens": itens, "total_cent": v["total_cent"], "teto_cent": teto,
                "devolvido_cent": tot["valor"], "saldo_cent": max(teto - tot["valor"], 0),
                "extras_cent": base["extras"], "extras_devolvidos_cent": tot["extras"],
                "rodizio_nao_devolvivel_cent": base["rodizio_liquido"], "completa": bool(tot["completa"]),
                "formas": formas, "modos": self.modos_permitidos(v),
                "devolucoes": self.da_venda(venda_id)}

    def modos_permitidos(self, v: dict) -> list[str]:
        if v["modalidade"] == "caderneta":
            return ["caderneta"]
        return ["dinheiro_gaveta", "externo"]

    def formas_dinheiro(self) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            "SELECT id, tipo FROM tipos_pagamento WHERE ativo = 1 AND na_gaveta = 1 ORDER BY caixa DESC, ordem, tipo")]

    # ============================================================ cálculo
    def _normalizar_selecao(self, selecao) -> list[dict]:
        if isinstance(selecao, dict):
            selecao = [{"item_id": k, "quantidade": q} for k, q in selecao.items()]
        saida, vistos = [], set()
        for s in selecao or []:
            item_id = int(s["item_id"])
            if item_id in vistos:
                raise ErroNegocio("O mesmo item aparece duas vezes na devolução.")
            vistos.add(item_id)
            unid = _unidades(s["quantidade"])
            if unid < 0:
                raise ErroNegocio("A quantidade devolvida não pode ser negativa.")
            if unid == 0:
                continue
            saida.append({"item_id": item_id, "unid": unid, "retorna_estoque": bool(s.get("retorna_estoque", False))})
        if not saida:
            raise ErroNegocio("Informe a quantidade de pelo menos um item a devolver.")
        return saida

    def _calcular(self, v: dict, selecao, reembolsar_extras: bool = True) -> dict:
        base = self._base(v)
        feito, tot = self._ja_devolvido(v["id"])
        linhas = []
        restantes = {k: l["q_unid"] - feito.get(k, {}).get("unid", 0) for k, l in base["itens"].items()}
        for s in self._normalizar_selecao(selecao):
            l = base["itens"].get(s["item_id"])
            if l is None:
                raise ErroNegocio("Item não pertence a esta venda ou não pode ser devolvido (cancelado ou incluso no rodízio).")
            f = feito.get(s["item_id"], {"unid": 0, "bruto": 0, "desc": 0, "serv": 0})
            if s["unid"] > restantes[s["item_id"]]:
                raise ErroNegocio(f"'{l['nome']}': restam {fmt.fmt_qtd(_qtd(restantes[s['item_id']]), fmt.CASAS_QTD)} "
                                  f"para devolver.")
            restantes[s["item_id"]] -= s["unid"]
            cum, q = f["unid"] + s["unid"], l["q_unid"]
            # Acumulado pelo piso: devoluções parciais nunca passam do proporcional e a última fecha o valor exato.
            a = (l["bruto"] - l["desc"]) * cum // q - (f["bruto"] - f["desc"])
            d = l["desc"] * cum // q - f["desc"]
            sv = l["serv"] * cum // q - f["serv"]
            a, d, sv = max(a, 0), max(d, 0), max(sv, 0)
            linhas.append({"item_id": s["item_id"], "produto_id": l["produto_id"], "nome": l["nome"],
                           "quantidade": _qtd(s["unid"]), "unid": s["unid"], "bruto_cent": a + d, "desconto_cent": d,
                           "servico_cent": sv, "valor_cent": a + sv, "retorna_estoque": s["retorna_estoque"]})
        completa = all(r == 0 for r in restantes.values())
        extras = max(base["extras"] - tot["extras"], 0) if completa and reembolsar_extras else 0
        r = {"itens": linhas, "itens_bruto_cent": sum(x["bruto_cent"] for x in linhas),
             "desconto_rateado_cent": sum(x["desconto_cent"] for x in linhas),
             "servico_rateado_cent": sum(x["servico_cent"] for x in linhas), "extras_cent": extras, "completa": completa}
        r["valor_cent"] = r["itens_bruto_cent"] - r["desconto_rateado_cent"] + r["servico_rateado_cent"] + extras
        teto, _ = self._pago_liquido(v)
        if tot["valor"] + r["valor_cent"] > teto:
            raise ErroNegocio(f"A devolução ({fmt.fmt_brl(r['valor_cent'])}) passaria do total pago na venda "
                              f"({fmt.fmt_brl(teto)}; já devolvido {fmt.fmt_brl(tot['valor'])}).")
        return r

    def previa(self, venda_id: int, selecao, reembolsar_extras: bool = True) -> dict:
        return self._calcular(self.caixa.obter(venda_id), selecao, reembolsar_extras)

    # ============================================================ estoque
    def _baixa_restante(self, venda_id: int) -> dict[int, float]:
        r = {row["produto_id"]: -row["q"] for row in self.banco.todos(
            "SELECT produto_id, SUM(quantidade) AS q FROM movimentos_estoque WHERE ref_tipo = 'venda' AND ref_id = ? "
            "AND tipo IN ('venda', 'estorno_venda') GROUP BY produto_id", (venda_id,))}
        for row in self.banco.todos(
                f"""SELECT m.produto_id, SUM(m.quantidade) AS q FROM movimentos_estoque m
                    JOIN devolucoes d ON d.id = m.ref_id WHERE m.ref_tipo = '{TIPO_ESTOQUE}' AND m.tipo = '{TIPO_ESTOQUE}'
                    AND d.venda_id = ? GROUP BY m.produto_id""", (venda_id,)):
            r[row["produto_id"]] = r.get(row["produto_id"], 0) - row["q"]
        return {k: fmt.arred_qtd(q) for k, q in r.items() if fmt.arred_qtd(q) > 0}

    def _consumos(self, item_id: int, produto_id: int, quantidade: float) -> list[tuple[int, float]]:
        from src.controllers.estoque_controller import EstoqueController
        partes = self.banco.todos("SELECT produto_id, fracao FROM itens_venda_partes WHERE item_id = ? ORDER BY id",
                                  (item_id,))
        saida = []
        for pid, q in EstoqueController._dividir_em_partes(quantidade, partes) or [(produto_id, quantidade)]:
            if self.caixa.produtos.por_id(pid) is None:
                saida.append((pid, q))           # produto excluído: o teto da baixa decide se volta
            else:
                saida += self.caixa.produtos.consumos(pid, q)
        return saida

    def _devolver_estoque(self, venda_id: int, devolucao_id: int, linhas: list[dict], cupom) -> None:
        restante = self._baixa_restante(venda_id)
        total: dict[int, float] = {}
        for l in linhas:
            if not l["retorna_estoque"]:
                continue
            for pid, q in self._consumos(l["item_id"], l["produto_id"], l["quantidade"]):
                volta = fmt.arred_qtd(min(q, restante.get(pid, 0)))
                if volta > 0:
                    restante[pid] = fmt.arred_qtd(restante[pid] - volta)
                    total[pid] = fmt.arred_qtd(total.get(pid, 0) + volta)
        for pid, q in total.items():
            self.caixa.estoque._mover(pid, q, TIPO_ESTOQUE, TIPO_ESTOQUE, devolucao_id, f"Devolução do cupom {cupom}")
    # ============================================================ gravação
    @staticmethod
    def _uuid(valor) -> str:
        try:
            u = UUID(str(valor))
        except (TypeError, ValueError, AttributeError):
            raise ErroNegocio("Identificador da devolução inválido.") from None
        if str(u) != str(valor).lower():
            raise ErroNegocio("Identificador da devolução inválido.")
        return str(u)

    def _exigir_autorizador(self, autorizado_por) -> dict:
        minimo = max(int(self.banco.valor("SELECT nivel FROM acessos WHERE modulo = ?", (MODULO,), 1) or 1), 1)
        op = self.banco.um("SELECT id, nome, nivel, ativo FROM operadores WHERE id = ?", (autorizado_por,)) \
            if autorizado_por is not None else None
        if op is None or not op["ativo"] or op["nivel"] < minimo:
            raise ErroPermissao("A devolução precisa da autorização de um operador com acesso a cancelamento no caixa.")
        return dict(op)

    def registrar(self, venda_id: int, selecao, motivo: str, autorizado_por: int, reembolso_modo: str, uuid: str,
                  tipo_pagamento_id: int | None = None, referencia_externa: str | None = None, troca: bool = False,
                  reembolsar_extras: bool = True) -> dict:
        """Grava a devolução numa única transação: registro imutável + saída da gaveta/crédito + estoque opcional.
        Repetir o mesmo `uuid` (duplo clique, nova tentativa após erro de impressão) devolve o registro já gravado."""
        uid = self._uuid(uuid)
        if self.operador_id is None:
            raise ErroPermissao("Entre com um operador para registrar a devolução.")
        motivo = " ".join((motivo or "").split())
        if not motivo:
            raise ErroNegocio("Informe o motivo da devolução.")
        if len(motivo) > MAX_MOTIVO:
            raise ErroNegocio(f"O motivo aceita no máximo {MAX_MOTIVO} caracteres.")
        referencia = " ".join((referencia_externa or "").split()) or None
        if referencia and len(referencia) > MAX_REFERENCIA:
            raise ErroNegocio(f"A referência do estorno aceita no máximo {MAX_REFERENCIA} caracteres.")
        if reembolso_modo not in MODOS:
            raise ErroNegocio("Escolha como o valor será devolvido ao cliente.")
        with self.banco.transacao():
            existente = self.banco.um("SELECT id, venda_id FROM devolucoes WHERE uuid = ?", (uid,))
            if existente is not None:
                if existente["venda_id"] != venda_id:
                    raise ErroNegocio("Este identificador de devolução já foi usado em outro cupom.")
                return {**self.obter(existente["id"]), "repetida": True}
            op = self.banco.um("SELECT ativo FROM operadores WHERE id = ?", (self.operador_id,))
            if op is None or not op["ativo"]:
                raise ErroPermissao("Operador inativo ou inexistente.")
            self._exigir_autorizador(autorizado_por)
            turno = self.caixa.turnos.exigir_aberto()
            v = self.caixa.obter(venda_id)
            if v["prepago"]:
                raise ErroNegocio("Venda de cartão pré-pago: a devolução por item ainda não é suportada aqui "
                                  "(o saldo do cartão é acertado pela recarga). Procure o gerente.")
            if reembolso_modo not in self.modos_permitidos(v):
                raise ErroNegocio("Venda em caderneta só devolve como crédito na caderneta do cliente."
                                  if v["modalidade"] == "caderneta"
                                  else "Crédito na caderneta só vale para venda feita na caderneta.")
            calc = self._calcular(v, selecao, reembolsar_extras)
            valor = calc["valor_cent"]
            agora = fmt.agora()
            dados = {"uuid": uid, "venda_id": venda_id, "venda_uuid": v["uuid"], "cupom_original": v["cupom"],
                     "turno_id": turno["id"], "criado_em": agora, "operador_id": self.operador_id,
                     "autorizado_por": autorizado_por, "motivo": motivo, "completa": int(calc["completa"]),
                     "troca": int(bool(troca)), "itens_bruto_cent": calc["itens_bruto_cent"],
                     "desconto_rateado_cent": calc["desconto_rateado_cent"],
                     "servico_rateado_cent": calc["servico_rateado_cent"], "extras_cent": calc["extras_cent"],
                     "valor_cent": valor, "reembolso_modo": reembolso_modo}
            if reembolso_modo == "dinheiro_gaveta":
                if tipo_pagamento_id is None:
                    formas = self.formas_dinheiro()
                    if not formas:
                        raise ErroNegocio("Não há forma de pagamento em dinheiro (na gaveta) cadastrada.")
                    tipo_pagamento_id = formas[0]["id"]
                tp = self.banco.um("SELECT na_gaveta FROM tipos_pagamento WHERE id = ?", (tipo_pagamento_id,))
                if tp is None or not tp["na_gaveta"]:
                    raise ErroNegocio("Reembolso pela gaveta precisa de uma forma de pagamento em dinheiro.")
                dados["tipo_pagamento_id"] = tipo_pagamento_id
                dados["referencia_externa"] = referencia
                if valor > 0:
                    dados["movimento_caixa_id"] = self.caixa.turnos.movimentar(
                        turno["id"], self.operador_id, "saida", valor, f"Devolução do cupom {v['cupom']}")
            elif reembolso_modo == "externo":
                if not referencia:
                    raise ErroNegocio("Informe a referência do estorno externo (NSU, código do Pix ou comprovante).")
                _, por_forma = self._pago_liquido(v)
                tp = self.banco.um("SELECT tipo, na_gaveta FROM tipos_pagamento WHERE id = ?", (tipo_pagamento_id,)) \
                    if tipo_pagamento_id is not None else None
                if tp is None or tp["na_gaveta"] or tipo_pagamento_id not in por_forma:
                    raise ErroNegocio("Escolha a forma (Pix/cartão) usada no pagamento desta venda para o estorno externo.")
                ja = self.banco.valor("SELECT COALESCE(SUM(valor_cent), 0) FROM devolucoes WHERE venda_id = ? AND "
                                      "reembolso_modo = 'externo' AND tipo_pagamento_id = ?",
                                      (venda_id, tipo_pagamento_id), 0)
                if ja + valor > por_forma[tipo_pagamento_id]:
                    raise ErroNegocio(f"O estorno em {tp['tipo']} passaria do que foi pago nessa forma "
                                      f"({fmt.fmt_brl(por_forma[tipo_pagamento_id])}; já estornado {fmt.fmt_brl(ja)}).")
                dados["tipo_pagamento_id"] = tipo_pagamento_id
                dados["referencia_externa"] = referencia
            else:
                cli = self.banco.um("SELECT id, ativo FROM clientes WHERE id = ?", (v["cliente_id"],)) \
                    if v["cliente_id"] is not None else None
                if cli is None:
                    raise ErroNegocio("Cliente da caderneta não encontrado.")
                dados["cliente_id"] = cli["id"]
                dados["referencia_externa"] = referencia
                if valor > 0:
                    self.banco.executar("UPDATE clientes SET saldo_cent = saldo_cent + ? WHERE id = ?", (valor, cli["id"]))
                    dados["caderneta_id"] = self.banco.inserir("caderneta", {
                        "cliente_id": cli["id"], "venda_id": None, "tipo": "credito", "valor_cent": valor,
                        "descricao": f"Devolução do cupom {v['cupom']}", "criado_em": agora})
            dev_id = self.banco.inserir("devolucoes", dados)
            for l in calc["itens"]:
                self.banco.inserir("devolucoes_itens", {
                    "devolucao_id": dev_id, "item_id": l["item_id"], "produto_id": l["produto_id"],
                    "quantidade": l["quantidade"], "bruto_cent": l["bruto_cent"], "desconto_cent": l["desconto_cent"],
                    "servico_cent": l["servico_cent"], "valor_cent": l["valor_cent"],
                    "retorna_estoque": int(l["retorna_estoque"])})
            self._devolver_estoque(venda_id, dev_id, calc["itens"], v["cupom"])
            self.banco.log("devolucao_venda", f"devolução {dev_id} cupom {v['cupom']} {fmt.fmt_brl(valor)} "
                                              f"{reembolso_modo}", self.operador_id)
        return {**self.obter(dev_id), "repetida": False}

    def abrir_troca(self, devolucao_id: int) -> int:
        """Troca: abre (ou retoma) a venda de balcão onde o cliente leva o produto novo, pelo fluxo normal do caixa.
        Idempotente: a mesma devolução sempre aponta para a mesma venda nova."""
        with self.banco.transacao():
            d = self.banco.um("SELECT id, troca FROM devolucoes WHERE id = ?", (devolucao_id,))
            if d is None:
                raise ErroNegocio("Devolução não encontrada.")
            if not d["troca"]:
                raise ErroNegocio("Esta devolução não foi registrada como troca.")
            ligada = self.banco.valor("SELECT venda_id FROM devolucoes_trocas WHERE devolucao_id = ?", (devolucao_id,))
            if ligada is not None:
                return ligada
            venda_id = self.caixa.abrir_balcao()
            if self.banco.valor("SELECT 1 FROM devolucoes_trocas WHERE venda_id = ?", (venda_id,)) is not None:
                raise ErroNegocio("A venda de balcão aberta já pertence a outra troca. Feche-a antes.")
            if self.caixa.itens(venda_id, cancelados=True) or self.caixa.pagamentos(venda_id):
                raise ErroNegocio("Já há uma venda de balcão em andamento. Feche ou cancele antes de abrir a troca.")
            self.banco.inserir("devolucoes_trocas", {"devolucao_id": devolucao_id, "venda_id": venda_id,
                                                      "operador_id": self.operador_id, "criado_em": fmt.agora()})
            return venda_id
    # ============================================================ leitura
    _SELECT = """SELECT d.*, o.nome AS operador, a.nome AS autorizador, t.tipo AS forma, t.na_gaveta,
                        v.fechada_em AS venda_fechada_em, v.turno_id AS venda_turno_id, v.total_cent AS venda_total_cent,
                        x.venda_id AS troca_venda_id
                 FROM devolucoes d JOIN vendas v ON v.id = d.venda_id
                 LEFT JOIN operadores o ON o.id = d.operador_id LEFT JOIN operadores a ON a.id = d.autorizado_por
                 LEFT JOIN tipos_pagamento t ON t.id = d.tipo_pagamento_id
                 LEFT JOIN devolucoes_trocas x ON x.devolucao_id = d.id"""

    def obter(self, devolucao_id: int) -> dict:
        r = self.banco.um(self._SELECT + " WHERE d.id = ?", (devolucao_id,))
        if r is None:
            raise ErroNegocio("Devolução não encontrada.")
        d = dict(r)
        d["itens"] = [dict(x) for x in self.banco.todos(
            """SELECT di.*, p.codigo, p.nome FROM devolucoes_itens di JOIN produtos_historico p ON p.id = di.produto_id
               WHERE di.devolucao_id = ? ORDER BY di.id""", (devolucao_id,))]
        return d

    def da_venda(self, venda_id: int) -> list[dict]:
        return [dict(r) for r in self.banco.todos(self._SELECT + " WHERE d.venda_id = ? ORDER BY d.id", (venda_id,))]

    def listar(self, turno_id: int | None = None, de: str | None = None, ate: str | None = None) -> list[dict]:
        """Devoluções pela data do REEMBOLSO (criado_em / turno em que saiu), não pela data da venda original.
        `de`/`ate` em ISO local; `ate` só com a data inclui o dia inteiro."""
        sql, params = self._SELECT + " WHERE 1 = 1", []
        if turno_id is not None:
            sql += " AND d.turno_id = ?"
            params.append(turno_id)
        if de:
            sql += " AND d.criado_em >= ?"
            params.append(de)
        if ate:
            sql += " AND d.criado_em <= ?"
            params.append(ate + " 23:59:59" if len(ate) == 10 else ate)
        return [dict(r) for r in self.banco.todos(sql + " ORDER BY d.criado_em, d.id", params)]

    def resumo_turno(self, turno_id: int) -> dict:
        """Contrato para fechamento/conferência de turno e relatórios (ver docs/DEVOLUCOES.md).
        Só `dinheiro_gaveta_cent` sai da gaveta (e já está em movimentos_caixa como 'saida'; não somar de novo).
        `externos` são estornos declarados pelo operador: a referência NÃO prova o estorno bancário."""
        lista = self.listar(turno_id=turno_id)
        r = {"turno_id": turno_id, "quantidade": len(lista), "valor_cent": 0, "itens_bruto_cent": 0,
             "desconto_rateado_cent": 0, "servico_rateado_cent": 0, "extras_cent": 0, "dinheiro_gaveta_cent": 0,
             "por_modo": {m: {"quantidade": 0, "valor_cent": 0} for m in MODOS}, "por_forma": [],
             "movimentos_caixa_ids": [], "externos": [], "trocas": 0}
        formas: dict[tuple, dict] = {}
        for d in lista:
            for k in ("valor_cent", "itens_bruto_cent", "desconto_rateado_cent", "servico_rateado_cent", "extras_cent"):
                r[k] += d[k]
            r["por_modo"][d["reembolso_modo"]]["quantidade"] += 1
            r["por_modo"][d["reembolso_modo"]]["valor_cent"] += d["valor_cent"]
            r["trocas"] += d["troca"]
            if d["reembolso_modo"] == "dinheiro_gaveta":
                r["dinheiro_gaveta_cent"] += d["valor_cent"]
            if d["movimento_caixa_id"] is not None:
                r["movimentos_caixa_ids"].append(d["movimento_caixa_id"])
            if d["reembolso_modo"] == "externo":
                r["externos"].append({"devolucao_id": d["id"], "cupom_original": d["cupom_original"], "tipo": d["forma"],
                                      "valor_cent": d["valor_cent"], "referencia_externa": d["referencia_externa"]})
            chave = (d["reembolso_modo"], d["tipo_pagamento_id"])
            f = formas.setdefault(chave, {"modo": d["reembolso_modo"], "tipo_pagamento_id": d["tipo_pagamento_id"],
                                          "tipo": d["forma"] or MODOS[d["reembolso_modo"]],
                                          "na_gaveta": bool(d["na_gaveta"]), "quantidade": 0, "valor_cent": 0})
            f["quantidade"] += 1
            f["valor_cent"] += d["valor_cent"]
        r["por_forma"] = list(formas.values())
        return r

    def comprovante(self, devolucao_id: int, largura: int = 40) -> str:
        d = self.obter(devolucao_id)
        linha = "-" * largura

        def par(esq: str, dir_: str) -> str:
            return esq[: max(largura - len(dir_) - 1, 1)].ljust(largura - len(dir_)) + dir_

        txt = ["DEVOLUÇÃO DE VENDA".center(largura), linha,
               f"Cupom original: {d['cupom_original']}", f"Data: {fmt.fmt_datahora(d['criado_em'])}",
               f"Operador: {d['operador'] or '-'}", f"Autorizado por: {d['autorizador'] or '-'}", linha]
        for i in d["itens"]:
            txt.append(i["nome"][:largura])
            txt.append(par(f"  {fmt.fmt_qtd(i['quantidade'], fmt.CASAS_QTD)} x", fmt.fmt_brl(i["valor_cent"])))
        txt.append(linha)
        txt.append(par("Itens (bruto)", fmt.fmt_brl(d["itens_bruto_cent"])))
        if d["desconto_rateado_cent"]:
            txt.append(par("Desconto rateado", "-" + fmt.fmt_brl(d["desconto_rateado_cent"])))
        if d["servico_rateado_cent"]:
            txt.append(par("Serviço rateado", fmt.fmt_brl(d["servico_rateado_cent"])))
        if d["extras_cent"]:
            txt.append(par("Taxa/acréscimo", fmt.fmt_brl(d["extras_cent"])))
        txt.append(par("TOTAL DEVOLVIDO", fmt.fmt_brl(d["valor_cent"])))
        txt.append(f"Reembolso: {MODOS[d['reembolso_modo']]}" + (f" ({d['forma']})" if d["forma"] else ""))
        if d["referencia_externa"]:
            txt.append(f"Referência: {d['referencia_externa']}"[:largura])
        if d["reembolso_modo"] == "externo":
            txt.append("Estorno feito fora do PDV.")
        txt.append(f"Motivo: {d['motivo']}"[: largura * 3])
        if d["troca"]:
            txt.append("TROCA: o produto novo sai em outra venda.")
        txt += [linha, f"Controle: {d['uuid']}"[:largura], "", "Assinatura do cliente:", "", "_" * largura, ""]
        return "\n".join(txt)
    # ============================================================ acesso (telas)
    def exigir_acesso(self) -> None:
        """Abrir a tela: operador ativo (consulta o cadastro atual, nunca o nível em cache). Gravar exige ainda um
        autorizador com o acesso `caixa_cancelamento` (o próprio operador, se tiver, ou a senha de um supervisor)."""
        if type(self.operador_id) is not int:
            raise ErroPermissao("Entre com um operador para registrar devoluções.")
        if self.banco.um("SELECT id FROM operadores WHERE id = ? AND ativo = 1", (self.operador_id,)) is None:
            raise ErroPermissao("Operador inexistente ou inativo. Encerre a sessão.")

    def operador_autoriza(self) -> bool:
        """True se o próprio operador logado tem nível para autorizar a devolução (dispensa senha de supervisor)."""
        try:
            self._exigir_autorizador(self.operador_id)
            return True
        except ErroPermissao:
            return False