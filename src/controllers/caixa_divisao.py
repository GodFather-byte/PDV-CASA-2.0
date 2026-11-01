"""Divisão por itens usada exclusivamente pelo CaixaController; preserva os vínculos e as transações do caixa."""
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio


class DivisaoContaMixin:
    def _tem_vinculos(self) -> bool:
        """A tabela `pagamentos_itens` (vínculo pagamento x item da divisão por item) vem de uma migração do esquema."""
        return bool(self.banco.valor(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pagamentos_itens'"))

    def _pagos_por_item(self, venda_id: int) -> dict[int, dict]:
        """{item_id: {'quantidade', 'valor_cent'}} já pagos na divisão por item desta venda."""
        if not self._tem_vinculos():
            return {}
        return {r["item_id"]: {"quantidade": fmt.arred_qtd(r["qtd"]), "valor_cent": r["valor"]}
                for r in self.banco.todos(
                    """SELECT x.item_id, SUM(x.quantidade) AS qtd, SUM(x.valor_cent) AS valor FROM pagamentos_itens x
                       JOIN pagamentos_venda p ON p.id = x.pagamento_id WHERE p.venda_id = ? GROUP BY x.item_id""",
                    (venda_id,))}

    def _total_resto(self, item: dict, resto: float, paga: float) -> int:
        """Total da parte que fica na linha numa cisão (cancelamento parcial ou transferência). Se só sobra a parte já
        paga por item, a linha fica exatamente com o valor pago (sem diferença de arredondamento de centavo)."""
        if paga > 0 and resto == paga:
            return self.banco.valor(
                "SELECT COALESCE(SUM(valor_cent), 0) FROM pagamentos_itens WHERE item_id = ?", (item["id"],), 0)
        return fmt.mult_cent(item["preco_unit_cent"], resto)

    def _conferir_vinculos(self, venda_id: int) -> None:
        """Trava da divisão por item, chamada dentro da transação de toda mudança na conta (lançamento, reprecificação,
        cancelamento, desconto, serviço, rodízio, transferência). Recusa (e a transação desfaz) qualquer mudança que deixe
        um vínculo pagamento x item inconsistente: item cancelado ou fora da conta do pagamento, quantidade paga acima da
        lançada, preço diferente do que foi pago, item pago que deixou de ter valor próprio (rodízio) ou conta abaixo do
        que já foi pago por item. Para mudar, o operador remove o pagamento primeiro (o que libera os itens)."""
        if not self._tem_vinculos():
            return
        linhas = self.banco.todos(
            """SELECT x.item_id, SUM(x.quantidade) AS qtd, SUM(x.valor_cent) AS valor, COUNT(*) AS n,
                      MIN(p.venda_id) AS venda_min, MAX(p.venda_id) AS venda_max
               FROM pagamentos_itens x JOIN pagamentos_venda p ON p.id = x.pagamento_id
               WHERE p.venda_id = ? OR x.item_id IN (SELECT id FROM itens_venda WHERE venda_id = ?)
               GROUP BY x.item_id""", (venda_id, venda_id))
        if not linhas:
            return
        v = self.obter(venda_id)
        ativos = {i["id"]: i for i in self.itens(venda_id)}
        pago_por_item = 0
        for r in linhas:
            i = ativos.get(r["item_id"])
            qtd = fmt.arred_qtd(r["qtd"])
            problema = None
            if i is None or r["venda_min"] != venda_id or r["venda_max"] != venda_id:
                problema = "foi cancelado ou saiu da conta em que foi pago"
            else:
                cobrado = 0 if (v.get("rodizio") and i["rodizio_incluso"]) else i["total_cent"]
                if cobrado <= 0:
                    problema = "deixaria de ter valor próprio na conta (incluso no rodízio)"
                elif qtd > i["quantidade"] or r["valor"] > cobrado:
                    problema = "ficaria com menos quantidade ou valor do que o já pago"
                elif qtd == i["quantidade"] and r["valor"] != cobrado:
                    problema = f"mudaria de valor ({fmt.fmt_brl(r['valor'])} pago, {fmt.fmt_brl(cobrado)} na conta)"
                elif abs(r["valor"] - fmt.mult_cent(i["preco_unit_cent"], qtd)) > r["n"]:
                    problema = "mudaria de preço depois de pago"
            if problema:
                nome = i["nome"] if i else "Um item"
                raise ErroNegocio(f"'{nome}' já foi pago na divisão por item e {problema}. "
                                  "Remova o pagamento desse item antes de fazer esta mudança.")
            pago_por_item += r["valor"]
        total = self.calcular(v)["total"]
        if total < pago_por_item:
            raise ErroNegocio(f"A conta ficaria em {fmt.fmt_brl(total)}, abaixo dos {fmt.fmt_brl(pago_por_item)} já pagos "
                              "na divisão por item. Remova o pagamento antes de fazer esta mudança.")

    def _qtd_paga(self, item_id: int) -> float:
        if not self._tem_vinculos():
            return 0
        return fmt.arred_qtd(self.banco.valor(
            "SELECT COALESCE(SUM(quantidade), 0) FROM pagamentos_itens WHERE item_id = ?", (item_id,), 0) or 0)

    def itens_para_divisao(self, venda_id: int) -> list[dict]:
        """Itens ativos com o que já foi pago por item e o que ainda está livre (quantidade e valor) para a divisão.
        Itens sem valor próprio (incluso no rodízio) aparecem com valor zero e não podem ser pagos por item."""
        v = self.obter(venda_id)
        pagos = self._pagos_por_item(venda_id)
        saida = []
        for i in self.itens(venda_id):
            pago = pagos.get(i["id"], {"quantidade": 0, "valor_cent": 0})
            cobrado = 0 if (v.get("rodizio") and i["rodizio_incluso"]) else i["total_cent"]
            livre = max(fmt.arred_qtd(i["quantidade"] - pago["quantidade"]), 0)
            saida.append({"item_id": i["id"], "produto_id": i["produto_id"], "nome": i["nome"], "codigo": i["codigo"],
                          "quantidade": i["quantidade"], "preco_unit_cent": i["preco_unit_cent"],
                          "total_cent": cobrado, "qtd_paga": pago["quantidade"], "valor_pago_cent": pago["valor_cent"],
                          "qtd_livre": livre,
                          "valor_livre_cent": max(cobrado - pago["valor_cent"], 0) if livre > 0 else 0})
        return saida

    def previa_pagamento_itens(self, venda_id: int, selecao) -> dict:
        """Quanto custam os itens escolhidos (lista de (item_id, quantidade)). Devolve {'itens': [...], 'valor_cent'}.
        O valor de cada item é proporcional à quantidade, em centavos; quem leva o que resta do item leva o restante exato,
        então pagar um item em várias vezes soma exatamente o total dele. Serviço, desconto, taxa e acréscimo não entram:
        ficam no restante da conta, que é dividido por valor."""
        v = self._aberta(venda_id)
        if v["modalidade"] == "caderneta":
            raise ErroNegocio("Venda em caderneta não recebe pagamento: o valor fica na conta do cliente.")
        if v["prepago"]:
            raise ErroNegocio("Comanda pré-paga já tem crédito carregado: a divisão por item não se aplica.")
        selecao = list(selecao or [])
        if not selecao:
            raise ErroNegocio("Escolha ao menos um item para pagar.")
        ids = [int(i) for i, _ in selecao]
        if len(set(ids)) != len(ids):
            raise ErroNegocio("O mesmo item foi escolhido mais de uma vez. Informe a quantidade total dele uma vez só.")
        disponiveis = {d["item_id"]: d for d in self.itens_para_divisao(venda_id)}
        linhas, total = [], 0
        for item_id, qtd in selecao:
            d = disponiveis.get(int(item_id))
            if d is None:
                raise ErroNegocio("Item não encontrado nesta conta ou já cancelado.")
            try:
                qtd = fmt.validar_qtd(qtd)
            except ValueError as exc:
                raise ErroNegocio(str(exc).capitalize() + ".") from None
            if qtd <= 0:
                raise ErroNegocio(f"Informe uma quantidade maior que zero para '{d['nome']}'.")
            if d["total_cent"] <= 0:
                raise ErroNegocio(f"'{d['nome']}' não tem valor próprio na conta (incluso no rodízio). Divida por valor.")
            if d["qtd_livre"] <= 0:
                raise ErroNegocio(f"'{d['nome']}' já foi pago na divisão por item.")
            if qtd > d["qtd_livre"]:
                raise ErroNegocio(f"'{d['nome']}': só {fmt.fmt_qtd(d['qtd_livre'], 3)} ainda não foi pago.")
            if qtd == d["qtd_livre"]:
                valor = d["valor_livre_cent"]
            else:
                valor = min(fmt.arredondar(fmt._dec(d["total_cent"]) * fmt._dec(qtd) / fmt._dec(d["quantidade"])),
                            d["valor_livre_cent"])
            linhas.append({"item_id": d["item_id"], "nome": d["nome"], "quantidade": qtd, "valor_cent": valor})
            total += valor
        if total <= 0:
            raise ErroNegocio("Os itens escolhidos não têm valor a pagar.")
        falta = self.liquidar(venda_id)["falta"]
        if total > falta:
            raise ErroNegocio(f"Os itens escolhidos somam {fmt.fmt_brl(total)}, mas faltam só {fmt.fmt_brl(falta)} na conta "
                              "(parte já foi paga por valor, sem item atribuído). Divida o restante por valor.")
        return {"itens": linhas, "valor_cent": total}

    def pagar_itens(self, venda_id: int, tipo_pagamento_id: int, selecao, valor_esperado_cent: int | None = None) -> int:
        """Divisão da conta por item: recebe, na forma escolhida, exatamente o valor dos itens (mais o acréscimo da forma,
        se houver) e vincula o pagamento a cada item e quantidade. O vínculo impede pagar o mesmo item duas vezes e
        protege o item do cancelamento; remover o pagamento libera os itens. `valor_esperado_cent` é o valor que a tela
        mostrou ao operador: se a conta mudou nesse meio tempo, nada é gravado. Devolve o id do pagamento."""
        if not self._tem_vinculos():
            raise ErroNegocio("A divisão por item precisa da atualização do banco de dados (tabela pagamentos_itens).")
        previa = self.previa_pagamento_itens(venda_id, selecao)
        valor = previa["valor_cent"] + self.acrescimo_da_forma(venda_id, tipo_pagamento_id)
        if valor_esperado_cent is not None and valor_esperado_cent != valor:
            raise ErroNegocio(f"O valor dos itens mudou para {fmt.fmt_brl(valor)}. Confira e tente de novo.")
        agora = fmt.agora()
        with self.banco.transacao():
            pid = self.adicionar_pagamento(venda_id, tipo_pagamento_id, valor)
            for ln in previa["itens"]:
                self.banco.inserir("pagamentos_itens", {"pagamento_id": pid, "item_id": ln["item_id"],
                                                        "quantidade": ln["quantidade"], "valor_cent": ln["valor_cent"],
                                                        "criado_em": agora})
            self.banco.registrar_auditoria(
                "pagamentos_venda", pid, "pagamento_por_item",
                depois={"venda_id": venda_id, "tipo_pagamento_id": tipo_pagamento_id, "valor_cent": valor,
                        "itens": [{k: ln[k] for k in ("item_id", "quantidade", "valor_cent")} for ln in previa["itens"]]},
                operador_id=self.operador_id)
        return pid

    def itens_do_pagamento(self, pagamento_id: int) -> list[dict]:
        """Itens (e quantidades) pagos por um pagamento da divisão por item; vazio se foi pago por valor."""
        if not self._tem_vinculos():
            return []
        return [dict(r) for r in self.banco.todos(
            """SELECT x.item_id, x.quantidade, x.valor_cent, p.nome FROM pagamentos_itens x
               JOIN itens_venda i ON i.id = x.item_id JOIN produtos_historico p ON p.id = i.produto_id
               WHERE x.pagamento_id = ? ORDER BY x.id""", (pagamento_id,))]

