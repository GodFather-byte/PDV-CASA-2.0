"""Vendas do caixa (manual do Caixa): balcão, mesas, itens, desconto, serviço,
pagamentos, troco/vale, fechamento e cancelamento.

Regras principais:
  * Toda venda pertence a um turno aberto e recebe o nº do cupom ao fechar/cancelar.
  * O estoque só é baixado quando a venda é FECHADA (e estornado se o cupom for cancelado).
  * Desconto incide só sobre os produtos; o serviço (só em mesa) não sofre desconto.
  * Troco sai das formas que permitem troco; excedente em forma que 'emite vale' vira contra-vale.
"""
from __future__ import annotations

import json
import math
from uuid import uuid4

from src.controllers import notificacoes
from src.controllers.estoque_controller import EstoqueController
from src.controllers.produto_controller import ProdutoController
from src.controllers.turno_controller import TurnoController, proximo_cupom
from src.controllers.conferencia_turno import registrar_transferencia
from src.core import formatacao as fmt
from src.core.posicao import interpretar as interpretar_posicao
from src.core.posicao import nome as nome_posicao
from src.core.posicao import padrao_valido
from src.core.posicao import rotulo as rotulo_posicao
from src.core.erros import ErroNegocio

ABERTAS = ("aberta", "conta_enviada")
NUM_COMANDAS_PADRAO = 10000
LIMITE_PARTES_DIVISAO = 30   # dividir a conta entre mais que isso é quase certo erro de digitação
# Teto de quantidade por item (config qtd_maxima_item; 0 = sem limite): barra o código de barras bipado
# no campo Quantidade, que viraria uma venda de bilhões.
QTD_MAXIMA_ITEM = 99_999


class CaixaController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id
        self.turnos = TurnoController(banco)
        self.estoque = EstoqueController(banco, operador_id)
        self.produtos = ProdutoController(banco)

    # ============================================================ consulta
    def obter(self, venda_id: int) -> dict:
        r = self.banco.um("SELECT * FROM vendas WHERE id = ?", (venda_id,))
        if r is None:
            raise ErroNegocio("Venda não encontrada.")
        return dict(r)

    def itens(self, venda_id: int, cancelados: bool = False) -> list[dict]:
        sql = """SELECT i.*, p.codigo, p.nome, u.abreviatura AS unidade, s.rodizio_incluso
                 FROM itens_venda i JOIN produtos_historico p ON p.id = i.produto_id
                 JOIN unidades u ON u.id = p.unidade_id JOIN subgrupos s ON s.id = p.subgrupo_id
                 WHERE i.venda_id = ?"""
        if not cancelados:
            sql += " AND i.cancelado = 0"
        linhas = [dict(r) for r in self.banco.todos(sql + " ORDER BY i.id", (venda_id,))]
        for ln in linhas:
            ln["partes_nomes"] = [r[0] for r in self.banco.todos(
                "SELECT p.nome FROM itens_venda_partes x JOIN produtos_historico p ON p.id = x.produto_id "
                "WHERE x.item_id = ? ORDER BY x.id", (ln["id"],))]
        return linhas

    def pagamentos(self, venda_id: int) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            """SELECT p.*, t.tipo, t.permite_troco, t.emite_vale, t.na_gaveta, t.acrescimo_cent FROM pagamentos_venda p
               JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id WHERE p.venda_id = ? ORDER BY p.id""",
            (venda_id,))]

    def formas_pagamento(self) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            "SELECT * FROM tipos_pagamento WHERE ativo = 1 AND caixa = 1 ORDER BY ordem, tipo")]

    def _aberta(self, venda_id: int) -> dict:
        v = self.obter(venda_id)
        if v["status"] not in ABERTAS:
            raise ErroNegocio("Esta venda já foi encerrada.")
        return v

    # ============================================================ abertura
    def _nova(self, modalidade: str, posicao: int = 0, **extra) -> int:
        turno = self.turnos.exigir_aberto()
        agora = fmt.agora()
        dados = {"uuid": str(uuid4()), "turno_id": None, "terminal": turno["terminal"],
                 "operador_id": self.operador_id, "modalidade": modalidade, "posicao": posicao,
                 "aberta_em": agora, "ultimo_lancamento_em": agora}
        dados.update(extra)
        return self.banco.inserir("vendas", dados)

    def balcao_aberto(self) -> dict | None:
        """A venda de balcão em andamento, se houver (a que o caixa retoma após uma queda de energia)."""
        r = self.banco.um(
            "SELECT * FROM vendas WHERE modalidade = 'balcao' AND status = 'aberta' ORDER BY id DESC LIMIT 1")
        return dict(r) if r else None

    def abrir_balcao(self) -> int:
        """Retoma a venda de balcão em andamento (ex.: após queda de energia) ou abre outra."""
        self.turnos.exigir_aberto()
        r = self.balcao_aberto()
        return r["id"] if r else self._nova("balcao")

    def abrir_caderneta(self, cliente_id: int) -> int:
        """Venda a prazo ou recebimento de dívida do cliente (a mesma tela serve aos dois:
        com itens é débito, sem itens é crédito). Reaproveita a que estiver aberta."""
        self.turnos.exigir_aberto()
        c = self.banco.um("SELECT ativo FROM clientes WHERE id = ?", (cliente_id,))
        if c is None or not c["ativo"]:
            raise ErroNegocio("Cliente inativo ou inexistente.")
        r = self.banco.valor(
            "SELECT id FROM vendas WHERE modalidade = 'caderneta' AND cliente_id = ? AND status = 'aberta'",
            (cliente_id,))
        return r or self._nova("caderneta", cliente_id=cliente_id)

    # ------------------------------------------------------- notação das posições
    def padrao_posicao(self) -> str:
        """'comanda': o número sem letra é a comanda e a mesa é M5. 'mesa': o número sem letra é a mesa e a comanda é C2."""
        return padrao_valido(self.banco.cfg("posicao_padrao", "comanda"))

    def ler_posicao(self, texto) -> tuple[bool, int]:
        """O que o operador digitou ('123', 'M5', 'C2') como (comanda, número), na notação da loja. 0 é o balcão."""
        return interpretar_posicao(texto, self.padrao_posicao())

    def rotular_posicao(self, comanda, posicao) -> str:
        """Como a posição aparece nas telas e listas: na mesma notação em que se digita."""
        return rotulo_posicao(comanda, posicao, self.padrao_posicao())

    def validar_mesa(self, posicao: int, comanda: bool = False) -> None:
        if comanda:
            maximo = self.banco.cfg_int("num_comandas", NUM_COMANDAS_PADRAO)
            if maximo < 1:
                raise ErroNegocio("As comandas estão desligadas (Configurações > Número de comandas).")
            if not 1 <= posicao <= maximo:
                raise ErroNegocio(f"Comanda inválida. Use de 1 a {maximo}.")
            return
        maximo = self.banco.cfg_int("num_mesas", 50)
        if not 1 <= posicao <= maximo:
            raise ErroNegocio(f"Mesa inválida. Use de 1 a {maximo}.")

    def abrir_mesa(self, posicao: int, pessoas: int = 0, comanda: bool = False) -> tuple[int, bool]:
        """Chama a mesa (ou comanda) se já estiver aberta; senão abre. Retorna (venda_id, criada)."""
        self.validar_mesa(posicao, comanda)
        r = self.banco.valor(
            "SELECT id FROM vendas WHERE modalidade = 'mesa' AND comanda = ? AND posicao = ? "
            "AND status IN ('aberta','conta_enviada')", (int(comanda), posicao))
        if r:
            return r, False
        return self._nova("mesa", posicao, pessoas=max(pessoas, 0), comanda=int(comanda)), True

    def mesas(self) -> list[dict]:
        """Mesas e comandas abertas (mesas primeiro). `rotulo` é o que a tela mostra, na notação da loja: '123' e 'M5'
        (ou '5' e 'C2', se o número sem letra for a mesa)."""
        limite = self.banco.cfg_int("tempo_inatividade_min", 30)
        padrao = self.padrao_posicao()
        linhas = [dict(r) for r in self.banco.todos(
            """SELECT v.*, (SELECT COUNT(*) FROM itens_venda i WHERE i.venda_id = v.id AND i.cancelado = 0) AS n_itens
               FROM vendas v WHERE modalidade = 'mesa' AND status IN ('aberta','conta_enviada')
               ORDER BY comanda, posicao""")]
        for m in linhas:
            m["rotulo"] = rotulo_posicao(m["comanda"], m["posicao"], padrao)
            m["minutos_parada"] = fmt.minutos_entre(m["ultimo_lancamento_em"] or m["aberta_em"])
            m["inativa"] = bool(limite > 0 and m["status"] == "aberta" and m["minutos_parada"] >= limite)
        return linhas

    def situacao_posicao(self, comanda: bool, numero: int) -> dict:
        """A consulta da saída da casa: o que se sabe de uma mesa ou comanda agora. A venda mais recente daquele número manda
        (a comanda de papel é reutilizada a noite toda): 'aberta' (consumo a pagar), 'paga' (com o cupom e a hora), 'cancelada',
        'vazia' (aberta, sem consumo) ou 'sem_registro'."""
        v = self.banco.um("SELECT * FROM vendas WHERE modalidade = 'mesa' AND comanda = ? AND posicao = ? ORDER BY id DESC LIMIT 1",
                          (int(comanda), numero))
        if v is None:
            return {"situacao": "sem_registro"}
        if v["status"] in ("aberta", "conta_enviada"):
            itens = self.banco.valor("SELECT COUNT(*) FROM itens_venda WHERE venda_id = ? AND cancelado = 0", (v["id"],), 0)
            if not itens:
                return {"situacao": "vazia"}
            return {"situacao": "aberta", "total_cent": v["total_cent"], "itens": itens, "quando": v["aberta_em"],
                    "conta_enviada": v["status"] == "conta_enviada"}
        if v["status"] == "fechada":
            return {"situacao": "paga", "total_cent": v["total_cent"], "cupom": v["cupom"], "quando": v["fechada_em"]}
        return {"situacao": "cancelada", "total_cent": v["total_cent"], "quando": v["fechada_em"] or v["aberta_em"]}

    # ------------------------------------------------- saída sem consumo (1002)
    def codigo_saida(self) -> str:
        """O código que, digitado na comanda, libera a saída de quem não consumiu (configuração `codigo_saida`, 1002)."""
        return (self.banco.cfg("codigo_saida", "1002") or "").strip()

    def eh_codigo_saida(self, texto) -> bool:
        cod, t = self.codigo_saida(), ("" if texto is None else str(texto)).strip()
        if not cod or not t:
            return False
        if cod.isdigit() and t.isdigit():
            return int(cod) == int(t)
        return cod.lower() == t.lower()

    def liberar_saida(self, comanda: bool, numero: int) -> dict:
        """Libera a saída do cliente cuja comanda (ou mesa) não consumiu nada: fecha a posição vazia e registra a saída no
        turno (aparece no fechamento). Com consumo ou pagamento lançado, recusa: a conta precisa ser fechada."""
        self.validar_mesa(numero, comanda)
        turno = self.turnos.exigir_aberto()
        nome = nome_posicao(comanda, numero)
        v = self.banco.um("SELECT * FROM vendas WHERE modalidade = 'mesa' AND comanda = ? AND posicao = ? "
                          "AND status IN ('aberta','conta_enviada')", (int(comanda), numero))
        with self.banco.transacao():
            if v is not None:
                if self.itens(v["id"]):
                    a_pagar = self.recalcular(v["id"])["total"]                # com o serviço: o que o cliente deve
                    raise ErroNegocio(f"A {nome.lower()} tem consumo de {fmt.fmt_brl(a_pagar)}: feche a conta antes de "
                                      "liberar a saída.")
                if self.pagamentos(v["id"]):
                    raise ErroNegocio(f"A {nome.lower()} tem pagamento lançado: feche ou cancele a conta antes de liberar a saída.")
                self.cancelar_venda(v["id"], "saída liberada sem consumo")
            quando = fmt.agora()
            rotulo = self.rotular_posicao(comanda, numero)
            # Nº do ticket de saída: sequência própria, guardada na configuração (a limpeza do movimento não a reinicia).
            ticket = self.banco.cfg_int("ultimo_ticket_saida", 0) + 1
            self.banco.cfg_set("ultimo_ticket_saida", str(ticket))
            self.banco.log("saida_liberada", json.dumps({"turno_id": turno["id"], "comanda": int(comanda), "posicao": numero,
                                                         "rotulo": rotulo, "ticket": ticket}), self.operador_id)
        return {"nome": nome, "rotulo": rotulo, "quando": quando, "turno": turno["numero"], "comanda": bool(comanda),
                "numero": numero, "ticket": ticket}

    def saidas_liberadas(self, turno_id: int) -> list[dict]:
        """As saídas sem consumo liberadas no turno, com a hora e quem liberou."""
        return [dict(r) for r in self.banco.todos(
            """SELECT l.quando, json_extract(l.detalhe, '$.rotulo') AS rotulo, o.nome AS operador FROM log_eventos l
               LEFT JOIN operadores o ON o.id = l.operador_id
               WHERE l.evento = 'saida_liberada' AND json_extract(l.detalhe, '$.turno_id') = ? ORDER BY l.id""", (turno_id,))]

    APELIDO_MAXIMO = 24

    def definir_apelido(self, venda_id: int, texto: str | None) -> str:
        """Dá um nome à mesa ou comanda aberta ("Carlos", "Aniversário"), para achá-la no painel sem decorar o número. Texto vazio
        tira o nome. Só mesas e comandas têm nome: o balcão, a caderneta e a entrega já se identificam sozinhos."""
        v = self._aberta(venda_id)
        if v["modalidade"] != "mesa":
            raise ErroNegocio("Só mesas e comandas podem ter nome.")
        apelido = " ".join((texto or "").split())
        if len(apelido) > self.APELIDO_MAXIMO:
            raise ErroNegocio(f"O nome vai até {self.APELIDO_MAXIMO} letras.")
        self.banco.executar("UPDATE vendas SET apelido = ? WHERE id = ?", (apelido or None, venda_id))
        self.banco.log("apelido", f"venda {venda_id}: {apelido or '(sem nome)'}", self.operador_id)
        return apelido

    def definir_pessoas(self, venda_id: int, pessoas: int) -> None:
        self._aberta(venda_id)
        self.banco.executar("UPDATE vendas SET pessoas = ? WHERE id = ?", (max(int(pessoas), 0), venda_id))

    # ============================================================== itens
    def adicionar_item(self, venda_id: int, produto_id: int, quantidade: float, observacao: str | None = None,
                       partes: list[int] | None = None) -> int:
        v = self._aberta(venda_id)
        p = self.produtos.por_id(produto_id)
        if p is None or not p["ativo"]:
            raise ErroNegocio("Produto não encontrado.")
        if not p["venda"]:
            raise ErroNegocio(f"'{p['nome']}' não está liberado para venda.")
        quantidade = fmt.arred_qtd(quantidade)
        if not math.isfinite(quantidade) or quantidade <= 0:
            raise ErroNegocio("Informe uma quantidade maior que zero.")
        maximo = self.banco.cfg_int("qtd_maxima_item", QTD_MAXIMA_ITEM)
        if 0 < maximo < quantidade:
            raise ErroNegocio(f"Quantidade acima do limite de {maximo} por item. "
                              "Confira se um código de barras não foi digitado no campo Quantidade.")
        if not p["aceita_decimal"] and quantidade != int(quantidade):
            raise ErroNegocio(f"'{p['nome']}' não aceita quantidade fracionada.")
        if v["modalidade"] == "caderneta" and v["cliente_id"] is None:
            raise ErroNegocio("Selecione o cliente da caderneta antes de lançar itens.")
        self._conferir_limite_comanda(v)

        if partes:
            qtd_partes = len(partes)
            if qtd_partes > p["partes"]:
                raise ErroNegocio(f"'{p['nome']}' pode ser dividido em no máximo {p['partes']} partes.")
            componentes = []
            for pid in partes:
                c = self.produtos.por_id(pid)
                if c is None or not c["ativo"]:
                    raise ErroNegocio("Produto de montagem não encontrado.")
                if not (c["compoe"] if p["composto"] else c["montagem"]):
                    raise ErroNegocio(f"'{c['nome']}' não pode compor '{p['nome']}'.")
                componentes.append(c)
            preco = self.produtos.preco_partes(p, componentes)
        else:
            componentes = []
            preco = self.produtos.preco_vigente(p)

        total = fmt.mult_cent(preco, quantidade)
        agora = fmt.agora()
        with self.banco.transacao():
            item_id = self.banco.inserir("itens_venda", {
                "venda_id": venda_id, "produto_id": produto_id, "quantidade": quantidade,
                "preco_unit_cent": preco, "total_cent": total, "cobra_servico": p["cobrar_servico"],
                "observacao": observacao, "comissao_cent": fmt.pct_de(total, p["comissao_pct"]),
                "partes": max(len(componentes), 1), "operador_id": self.operador_id, "criado_em": agora})
            for c in componentes:
                self.banco.inserir("itens_venda_partes", {
                    "item_id": item_id, "produto_id": c["id"], "fracao": 1 / len(componentes)})
            self.banco.executar(
                "UPDATE vendas SET ultimo_lancamento_em = ?, status = 'aberta' WHERE id = ?", (agora, venda_id))
            self.recalcular(venda_id)
        return item_id

    LIMITE_COMANDA_PADRAO = 200

    def _conferir_limite_comanda(self, v: dict) -> None:
        """Limite de consumo da comanda do cliente (Configurações > Mesas e serviço, padrão R$ 200,00; 0 = sem limite): quando o
        consumo chega ao limite, não deixa lançar mais nada até a comanda ser acertada. Vale só para comanda (não para mesa, balcão
        ou caderneta) e na mesma faixa de números da consumação mínima, para deixar de fora as comandas das garotas."""
        if v["modalidade"] != "mesa" or not v.get("comanda"):
            return
        limite = self.banco.cfg_int("limite_comanda", self.LIMITE_COMANDA_PADRAO) * 100
        if limite <= 0:
            return
        de, ate = self.banco.cfg_int("consumacao_minima_de", 0), self.banco.cfg_int("consumacao_minima_ate", 0)
        if v["posicao"] < de or (ate and v["posicao"] > ate):
            return
        consumo = self.banco.valor("SELECT COALESCE(SUM(total_cent), 0) FROM itens_venda WHERE venda_id = ? AND cancelado = 0",
                                   (v["id"],))
        if consumo >= limite:
            raise ErroNegocio(f"A comanda chegou ao limite de {fmt.fmt_brl(limite)}. "
                              "Não dá para lançar mais: é preciso acertar a comanda.")

    def cancelar_item(self, item_id: int, motivo: str = "") -> None:
        motivo = (motivo or "").strip()
        if not motivo and self.banco.cfg_bool("exigir_motivo_cancelamento", False):
            raise ErroNegocio("Informe o motivo do cancelamento.")
        item = self.banco.um("SELECT * FROM itens_venda WHERE id = ?", (item_id,))
        if item is None or item["cancelado"]:
            raise ErroNegocio("Item não encontrado ou já cancelado.")
        self._aberta(item["venda_id"])
        with self.banco.transacao():
            self.banco.executar("UPDATE itens_venda SET cancelado = 1, cancelado_em = ? WHERE id = ?",
                                (fmt.agora(), item_id))
            self.recalcular(item["venda_id"])
            self.banco.log("item_cancelado", f"venda {item['venda_id']} item {item_id}" + (f" motivo: {motivo}"[:200] if motivo else ""),
                           self.operador_id)
        notificacoes.avisar(self.banco, "item", "item_cancelado", item_id, motivo, self.operador_id)

    def definir_observacao(self, item_id: int, texto: str | None) -> None:
        item = self.banco.um("SELECT venda_id FROM itens_venda WHERE id = ?", (item_id,))
        if item is None:
            raise ErroNegocio("Item não encontrado.")
        self._aberta(item["venda_id"])                 # cupom já emitido não muda
        self.banco.executar("UPDATE itens_venda SET observacao = ? WHERE id = ?", ((texto or "").strip() or None, item_id))

    # ============================================================== totais
    def calcular(self, v: dict, itens: list[dict] | None = None) -> dict:
        itens = itens if itens is not None else self.itens(v["id"])
        rodizio_total = 0
        itens_cobrados = itens
        if v.get("rodizio"):
            # Rodízio: produtos do subgrupo "incluso" não entram na conta por item (preço fixo cobre eles);
            # bebida e extras (subgrupo não marcado) continuam cobrados normalmente, por item.
            itens_cobrados = [i for i in itens if not i["rodizio_incluso"]]
            valor_pessoa = fmt.para_centavos(self.banco.cfg("valor_rodizio_pessoa", "0") or 0)
            rodizio_total = valor_pessoa * (v["pessoas"] or 0)
        subtotal = sum(i["total_cent"] for i in itens_cobrados) + rodizio_total
        if v["desconto_pct"] > 0:
            desconto = fmt.pct_de(subtotal, v["desconto_pct"])
        else:
            desconto = v["desconto_cent"]
        desconto = min(max(desconto, 0), subtotal)
        servico = 0
        chave_servico = "cobra_servico_comanda" if v.get("comanda") else "cobra_servico_mesa"
        if v["modalidade"] == "mesa" and self.banco.cfg_bool(chave_servico, True):
            if v["servico_manual"]:
                servico = v["servico_cent"]
            else:
                base = sum(i["total_cent"] for i in itens_cobrados if i["cobra_servico"]) + rodizio_total
                servico = fmt.pct_de(base, float(self.banco.cfg("servico_pct", "10") or 0))
        taxa = v["taxa_cent"]
        if v["modalidade"] == "mesa" and v.get("comanda") and not v.get("rodizio"):
            taxa = self.complemento_consumacao(v["posicao"], subtotal - desconto)      # comanda não tem taxa de entrega
        acrescimo = self.acrescimo_pagamento(v)
        return {"subtotal": subtotal, "desconto": desconto, "servico": servico, "taxa": taxa, "acrescimo": acrescimo,
                "rodizio_total": rodizio_total,
                "total": subtotal - desconto + servico + taxa + acrescimo}

    def acrescimo_pagamento(self, v: dict) -> int:
        """Acréscimo das formas de pagamento lançadas na venda (taxa do crédito, R$ 5,00): cobrado UMA vez por venda, o maior
        entre as formas usadas, e some se o pagamento for removido. A caderneta não paga na hora, então não tem acréscimo."""
        if v["modalidade"] == "caderneta":
            return 0
        return self.banco.valor(
            """SELECT COALESCE(MAX(t.acrescimo_cent), 0) FROM pagamentos_venda p
               JOIN tipos_pagamento t ON t.id = p.tipo_pagamento_id WHERE p.venda_id = ?""", (v["id"],), 0)

    def acrescimo_da_forma(self, venda_id: int, tipo_pagamento_id: int) -> int:
        """Quanto a venda passa a custar a mais se receber esta forma agora (0 se a forma não tem acréscimo ou se a venda já
        cobra um igual ou maior). A tela soma isso ao valor sugerido, para o cartão já passar com a taxa."""
        v = self.obter(venda_id)
        if v["modalidade"] == "caderneta":
            return 0
        forma = self.banco.valor("SELECT acrescimo_cent FROM tipos_pagamento WHERE id = ?", (tipo_pagamento_id,), 0) or 0
        return max(forma - self.acrescimo_pagamento(v), 0)

    def complemento_consumacao(self, numero_comanda: int, consumo_cent: int) -> int:
        """Consumação mínima: quanto falta para a comanda chegar ao mínimo (Configurações > Mesas e serviço). É cobrado como
        um acréscimo no total (guardado em `taxa_cent`, que comanda não usa para entrega). Só vale para comanda COM consumo,
        dentro da faixa de números configurada: comanda vazia (a da garota, por exemplo) nunca é cobrada."""
        minimo = self.banco.cfg_int("consumacao_minima", 0) * 100
        if minimo <= 0 or consumo_cent <= 0 or consumo_cent >= minimo:
            return 0
        de, ate = self.banco.cfg_int("consumacao_minima_de", 0), self.banco.cfg_int("consumacao_minima_ate", 0)
        if numero_comanda < de or (ate and numero_comanda > ate):
            return 0
        return minimo - consumo_cent

    def recalcular(self, venda_id: int) -> dict:
        v = self.obter(venda_id)
        c = self.calcular(v)
        self.banco.executar(
            "UPDATE vendas SET subtotal_cent = ?, desconto_cent = ?, servico_cent = ?, taxa_cent = ?, acrescimo_cent = ?, "
            "rodizio_total_cent = ?, total_cent = ? WHERE id = ?",
            (c["subtotal"], c["desconto"], c["servico"], c["taxa"], c["acrescimo"], c["rodizio_total"], c["total"],
             venda_id))
        return c

    def definir_desconto(self, venda_id: int, pct: float | None = None, valor_cent: int | None = None) -> dict:
        v = self._aberta(venda_id)
        if not self.banco.cfg_bool("usar_desconto", False) and (pct or valor_cent):
            raise ErroNegocio("O desconto está desligado (Configurações > Caixa > Permitir desconto).")
        if pct is not None and valor_cent is not None:
            raise ErroNegocio("Informe o desconto em percentual OU em valor, não os dois.")
        if pct is not None:
            if not 0 <= pct <= 100:
                raise ErroNegocio("O percentual de desconto deve estar entre 0 e 100.")
            v.update(desconto_pct=pct, desconto_cent=0)
        else:
            valor_cent = valor_cent or 0
            if valor_cent < 0:
                raise ErroNegocio("O desconto não pode ser negativo.")
            if valor_cent > v["subtotal_cent"]:
                raise ErroNegocio("O desconto não pode ser maior que o total dos produtos.")
            v.update(desconto_pct=0, desconto_cent=valor_cent)
        calculo = self.calcular(v)
        with self.banco.transacao():
            self.banco.atualizar("vendas", venda_id, {
                "desconto_pct": v["desconto_pct"], "desconto_cent": calculo["desconto"],
                "subtotal_cent": calculo["subtotal"], "servico_cent": calculo["servico"],
                "taxa_cent": calculo["taxa"], "acrescimo_cent": calculo["acrescimo"],
                "total_cent": calculo["total"]})
            self.banco.log("desconto", f"venda {venda_id}: pct={pct} valor={valor_cent}", self.operador_id)
        return calculo

    def definir_servico(self, venda_id: int, valor_cent: int | None) -> dict:
        """None volta ao cálculo automático. O cliente pode pagar menos (ou zero): serviço não é obrigatório."""
        self._aberta(venda_id)
        if valor_cent is None:
            self.banco.executar("UPDATE vendas SET servico_manual = 0, servico_cent = 0 WHERE id = ?", (venda_id,))
        else:
            if valor_cent < 0:
                raise ErroNegocio("O serviço não pode ser negativo.")
            self.banco.executar("UPDATE vendas SET servico_manual = 1, servico_cent = ? WHERE id = ?", (valor_cent, venda_id))
        return self.recalcular(venda_id)

    def ativar_rodizio(self, venda_id: int, pessoas: int) -> dict:
        """Liga o rodízio nesta mesa/comanda: os produtos de subgrupo "incluso" passam a entrar na conta
        pelo preço fixo por pessoa (valor_rodizio_pessoa), não pelo preço do item. Opt-in por mesa: a casa
        pode ter mesa à la carte e mesa em rodízio ao mesmo tempo."""
        if not self.banco.cfg_bool("usar_rodizio", False):
            raise ErroNegocio("O rodízio está desligado (Configurações > Módulos).")
        v = self._aberta(venda_id)
        if v["modalidade"] != "mesa":
            raise ErroNegocio("Rodízio só vale para mesa ou comanda.")
        if pessoas < 1:
            raise ErroNegocio("Informe quantas pessoas estão no rodízio.")
        self.banco.executar("UPDATE vendas SET rodizio = 1, pessoas = ? WHERE id = ?", (pessoas, venda_id))
        return self.recalcular(venda_id)

    def desativar_rodizio(self, venda_id: int) -> dict:
        self._aberta(venda_id)
        self.banco.executar("UPDATE vendas SET rodizio = 0 WHERE id = ?", (venda_id,))
        return self.recalcular(venda_id)

    # ========================================================== pagamentos
    def adicionar_pagamento(self, venda_id: int, tipo_pagamento_id: int, valor_cent: int) -> int:
        v = self._aberta(venda_id)
        forma = self.banco.um("SELECT * FROM tipos_pagamento WHERE id = ? AND ativo = 1", (tipo_pagamento_id,))
        if forma is None or not forma["caixa"]:
            raise ErroNegocio("Esta forma de pagamento não está habilitada para o caixa.")
        if valor_cent <= 0:
            raise ErroNegocio("Informe um valor maior que zero.")
        if v["modalidade"] == "caderneta" and self.itens(venda_id):
            raise ErroNegocio("Venda em caderneta não recebe pagamento: o valor fica na conta do cliente.")
        turno = self.turnos.exigir_aberto()
        with self.banco.transacao():
            pid = self.banco.inserir("pagamentos_venda", {
                "venda_id": venda_id, "tipo_pagamento_id": tipo_pagamento_id,
                "valor_cent": valor_cent, "criado_em": fmt.agora(), "turno_id": turno["id"]})
            if forma["acrescimo_cent"]:
                self.recalcular(venda_id)              # o crédito acrescenta a taxa ao total da venda
        return pid

    def remover_pagamento(self, pagamento_id: int) -> None:
        p = self.banco.um("SELECT venda_id, turno_id FROM pagamentos_venda WHERE id = ?", (pagamento_id,))
        if p is None:
            raise ErroNegocio("Pagamento não encontrado.")
        self._aberta(p["venda_id"])
        if self._de_outro_turno(p["turno_id"], self.turnos.atual()):
            raise ErroNegocio("Este pagamento foi recebido em um turno que já foi fechado e conferido; ele não pode "
                              "ser removido. Se for preciso devolver o valor, cancele a conta.")
        with self.banco.transacao():
            self.banco.executar("DELETE FROM pagamentos_venda WHERE id = ?", (pagamento_id,))
            self.recalcular(p["venda_id"])             # sem o crédito, a taxa sai do total

    @staticmethod
    def _de_outro_turno(turno_id: int | None, atual: dict | None) -> bool:
        """Pagamento recebido em um turno que não é o aberto agora (pagamento antigo sem turno conta como do atual)."""
        return turno_id is not None and (atual is None or turno_id != atual["id"])

    def liquidar(self, venda_id: int, total: int | None = None) -> dict:
        """Confronta pagamentos x total. Devolve pago, falta, troco, vale e o rateio do troco
        por pagamento. Levanta erro se o excesso não puder virar troco nem vale."""
        pags = self.pagamentos(venda_id)
        if total is None:
            total = self.obter(venda_id)["total_cent"]
        pago = sum(p["valor_cent"] for p in pags)
        out = {"total": total, "pago": pago, "falta": max(total - pago, 0), "troco": 0, "vale": 0, "rateio": {}}
        excesso = pago - total
        if excesso <= 0:
            return out
        cap_troco = sum(p["valor_cent"] for p in pags if p["permite_troco"])
        troco = min(excesso, cap_troco)
        vale = min(excesso - troco, sum(p["valor_cent"] for p in pags if p["emite_vale"]))
        if excesso - troco - vale > 0:
            raise ErroNegocio("O valor pago excede o total e a forma de pagamento não permite troco.")
        # O troco é dado agora, da gaveta do turno aberto: sai primeiro dos pagamentos recebidos neste turno, para não
        # mexer na conferência de um turno já fechado. Só se eles não bastarem (alguém pagou a mais num turno anterior
        # e deixou a conta aberta) o resto recai sobre os pagamentos antigos.
        atual = self.turnos.atual()
        restante = troco
        for p in sorted(pags, key=lambda p: (self._de_outro_turno(p["turno_id"], atual), p["id"])):
            if p["permite_troco"] and restante > 0:
                parte = min(restante, p["valor_cent"])
                out["rateio"][p["id"]] = parte
                restante -= parte
        out.update(troco=troco, vale=vale)
        return out

    def dividir_restante(self, venda_id: int, partes: int) -> list[int]:
        """Divide o que falta pagar (liquidar()['falta']) em `partes` iguais, em centavos, sem
        perder nem sobrar: as primeiras parcelas recebem o centavo que não divide exato."""
        if not 2 <= partes <= LIMITE_PARTES_DIVISAO:
            raise ErroNegocio(f"Divida entre 2 e {LIMITE_PARTES_DIVISAO} partes.")
        falta = self.liquidar(venda_id)["falta"]
        if falta <= 0:
            raise ErroNegocio("Não há valor em aberto para dividir.")
        base, resto = divmod(falta, partes)
        return [base + (1 if i < resto else 0) for i in range(partes)]

    def info_credito(self, venda_id: int) -> dict:
        """Recebimento de dívida na caderneta: dívida atual, valor pago e excedente."""
        v = self.obter(venda_id)
        saldo = self.banco.valor("SELECT saldo_cent FROM clientes WHERE id = ?", (v["cliente_id"],), 0)
        pago = sum(p["valor_cent"] for p in self.pagamentos(venda_id))
        divida = max(-saldo, 0)
        return {"divida": divida, "pago": pago, "excedente": max(pago - divida, 0) if divida else 0}

    # =========================================================== fechamento
    def proximo_cupom(self) -> int:
        return proximo_cupom(self.banco)

    def fechar(self, venda_id: int, garcom_id: int | None = None, pessoas: int | None = None,
               excesso_como_credito: bool | None = None) -> dict:
        v = self._aberta(venda_id)
        turno = self.turnos.exigir_aberto()
        itens = self.itens(venda_id)
        eh_credito = v["modalidade"] == "caderneta" and not itens
        eh_debito = v["modalidade"] == "caderneta" and bool(itens)
        if not itens and not eh_credito:
            raise ErroNegocio("A venda não tem itens.")
        if v["modalidade"] == "caderneta" and not v["cliente_id"]:
            raise ErroNegocio("Selecione o cliente da caderneta.")
        if v["modalidade"] == "mesa" and self.banco.cfg_bool("controle_garcom") and not (garcom_id or v["garcom_id"]):
            raise ErroNegocio("Informe o garçom que atendeu a mesa.")

        with self.banco.transacao():
            self.banco.executar("UPDATE pagamentos_venda SET turno_id = ? WHERE venda_id = ? AND turno_id IS NULL",
                                (turno["id"], venda_id))
            calc = self.recalcular(venda_id)
            total = calc["total"]
            troco = vale = 0
            rateio: dict = {}
            if eh_credito:
                info = self.info_credito(venda_id)
                if info["pago"] <= 0:
                    raise ErroNegocio("Informe a forma de pagamento e o valor recebido.")
                creditar = info["pago"]
                if info["excedente"] > 0 and excesso_como_credito is not True:
                    if excesso_como_credito is None:
                        raise ErroNegocio("O valor excede a dívida do cliente: defina se o troco vira crédito.")
                    creditar = info["divida"]
                    liq = self.liquidar(venda_id, creditar)
                    troco, vale, rateio = liq["troco"], liq["vale"], liq["rateio"]
                total = creditar
            elif eh_debito:
                if self.pagamentos(venda_id):
                    raise ErroNegocio("Venda em caderneta não recebe pagamento. Remova os pagamentos lançados.")
                self._debitar_caderneta(v["cliente_id"], total)
            else:
                liq = self.liquidar(venda_id, total)
                if liq["falta"] > 0:
                    raise ErroNegocio(f"Faltam {fmt.fmt_brl(liq['falta'])} para completar o pagamento.")
                troco, vale, rateio = liq["troco"], liq["vale"], liq["rateio"]

            for pag_id, parte in rateio.items():
                self.banco.executar("UPDATE pagamentos_venda SET troco_cent = ? WHERE id = ?", (parte, pag_id))
            pago = sum(p["valor_cent"] for p in self.pagamentos(venda_id))
            agora = fmt.agora()
            self.banco.atualizar("vendas", venda_id, {
                "turno_id": turno["id"], "cupom": self.proximo_cupom(), "status": "fechada", "fechada_em": agora,
                "total_cent": total, "pago_cent": pago, "troco_cent": troco, "vale_cent": vale,
                "garcom_id": garcom_id or v["garcom_id"],
                "pessoas": 0 if eh_credito else (pessoas if pessoas is not None else (v["pessoas"] or 1)),
                "sincronizado": 0})
            if eh_credito:
                self._creditar_caderneta(v["cliente_id"], venda_id, total)
            elif itens:
                self.estoque.baixar_venda(venda_id)
            if eh_debito:
                self.banco.inserir("caderneta", {
                    "cliente_id": v["cliente_id"], "venda_id": venda_id, "tipo": "debito", "valor_cent": total,
                    "descricao": "Venda em caderneta", "criado_em": agora})
        notificacoes.avisar(self.banco, "venda", "venda_fechada", venda_id)      # fora da transação: só avisa o que ficou gravado
        return self.obter(venda_id)

    def _debitar_caderneta(self, cliente_id: int, total: int) -> None:
        c = self.banco.um("SELECT nome, saldo_cent, limite_cent, ativo FROM clientes WHERE id = ?", (cliente_id,))
        if c is None or not c["ativo"]:
            raise ErroNegocio("Cliente da caderneta inativo ou inexistente.")
        if total <= 0:
            raise ErroNegocio("O total da venda em caderneta deve ser maior que zero.")
        novo = c["saldo_cent"] - total
        if c["limite_cent"] > 0 and novo < -c["limite_cent"]:
            raise ErroNegocio(f"Limite de crédito excedido para {c['nome']}: limite {fmt.fmt_brl(c['limite_cent'])}, "
                              f"dívida após a venda {fmt.fmt_brl(-novo)}.")
        self.banco.executar("UPDATE clientes SET saldo_cent = ? WHERE id = ?", (novo, cliente_id))

    def _creditar_caderneta(self, cliente_id: int, venda_id: int, valor: int) -> None:
        if valor <= 0:
            return
        self.banco.executar("UPDATE clientes SET saldo_cent = saldo_cent + ? WHERE id = ?", (valor, cliente_id))
        self.banco.inserir("caderneta", {
            "cliente_id": cliente_id, "venda_id": venda_id, "tipo": "credito", "valor_cent": valor,
            "descricao": "Pagamento / crédito", "criado_em": fmt.agora()})

    # ============================================================ cancelar
    def cancelar_venda(self, venda_id: int, motivo: str = "") -> None:
        motivo = (motivo or "").strip()
        if not motivo and self.banco.cfg_bool("exigir_motivo_cancelamento", False):
            raise ErroNegocio("Informe o motivo do cancelamento.")
        """Venda aberta: some se estiver vazia; senão vira cupom cancelado. Cupom fechado:
        só no turno ainda aberto; estorna estoque e caderneta."""
        v = self.obter(venda_id)
        agora = fmt.agora()
        with self.banco.transacao():
            if v["status"] in ABERTAS:
                if not self.itens(venda_id, cancelados=True) and not self.pagamentos(venda_id):
                    self.banco.executar("DELETE FROM vendas WHERE id = ?", (venda_id,))
                    return
                turno = self.turnos.exigir_aberto()
                self.banco.atualizar("vendas", venda_id, {
                    "status": "cancelada", "cupom": self.proximo_cupom(), "fechada_em": agora,
                    "turno_id": turno["id"],
                    "cancelada_por": self.operador_id, "motivo_cancelamento": motivo, "sincronizado": 0})
                self._devolver_adiantamentos(venda_id, turno)
                # O recebido neste turno é devolvido da própria gaveta: sai da venda, como sempre. O de turno anterior
                # fica registrado (aquele turno o recebeu e já foi conferido com ele).
                self.banco.executar("DELETE FROM pagamentos_venda WHERE venda_id = ? AND (turno_id IS NULL OR turno_id = ?)",
                                    (venda_id, turno["id"]))
            elif v["status"] == "fechada":
                turno = self.turnos.atual()
                if turno is None or v["turno_id"] != turno["id"]:
                    raise ErroNegocio("Só é possível cancelar cupons do turno atual. Este turno já foi fechado.")
                self._devolver_adiantamentos(venda_id, turno)
                self.estoque.estornar_venda(venda_id)
                self._estornar_caderneta(v)
                self.banco.atualizar("vendas", venda_id, {
                    "status": "cancelada", "cancelada_por": self.operador_id, "motivo_cancelamento": motivo,
                    "sincronizado": 0})
            else:
                raise ErroNegocio("Este cupom já está cancelado.")
            self.banco.log("venda_cancelada", f"venda {venda_id} cupom {v['cupom']} {motivo}".strip(), self.operador_id)
        notificacoes.avisar(self.banco, "cancelamento", "venda_cancelada", venda_id)

    def _devolver_adiantamentos(self, venda_id: int, turno: dict) -> int:
        """Cancelamento de conta que recebeu dinheiro em um turno já fechado: aquele turno continua com o valor (ele
        entrou lá e foi conferido), e a devolução ao cliente sai da gaveta do turno atual como uma saída registrada.
        Pix e cartão não passam pela gaveta: o estorno deles é feito na maquininha ou no banco. Devolve o valor."""
        valor = sum(p["valor_cent"] - p["troco_cent"] for p in self.pagamentos(venda_id)
                    if p["na_gaveta"] and self._de_outro_turno(p["turno_id"], turno))
        if valor > 0:
            self.turnos.movimentar(turno["id"], self.operador_id, "saida", valor,
                                   f"Devolução de adiantamento da venda {venda_id} (recebido em turno anterior)")
        return valor

    def _estornar_caderneta(self, v: dict) -> None:
        for lan in self.banco.todos("SELECT * FROM caderneta WHERE venda_id = ?", (v["id"],)):
            sinal = 1 if lan["tipo"] == "debito" else -1
            self.banco.executar("UPDATE clientes SET saldo_cent = saldo_cent + ? WHERE id = ?",
                                (sinal * lan["valor_cent"], lan["cliente_id"]))
        self.banco.executar("DELETE FROM caderneta WHERE venda_id = ?", (v["id"],))

    # ====================================================== mesas / contas
    def enviar_conta(self, venda_id: int) -> dict:
        """Marca a mesa como 'conta enviada' (bandeja) e devolve os totais para a pré-conta."""
        v = self._aberta(venda_id)
        if v["modalidade"] != "mesa":
            raise ErroNegocio("Somente mesas enviam conta.")
        if not self.itens(venda_id):
            raise ErroNegocio("A mesa não tem itens.")
        self.banco.executar("UPDATE vendas SET status = 'conta_enviada' WHERE id = ?", (venda_id,))
        return self.recalcular(venda_id)

    def _mover_itens(self, origem_id: int, destino_id: int) -> None:
        """Junta a venda de origem na de destino e apaga a origem. Tudo o que pertence à origem vai junto: sem isso, o
        adiantamento já pago na mesa sumiria (os pagamentos são apagados em cascata com a venda) e um repique ligado a
        ela travaria a transferência. Cada pagamento mantém o turno em que entrou."""
        self.banco.executar("UPDATE itens_venda SET venda_id = ? WHERE venda_id = ?", (destino_id, origem_id))
        self.banco.executar("UPDATE pagamentos_venda SET venda_id = ? WHERE venda_id = ?", (destino_id, origem_id))
        self.banco.executar("UPDATE repiques SET venda_id = ? WHERE venda_id = ?", (destino_id, origem_id))
        # O desconto dado na origem vale também na conta juntada: soma ao do destino, em valor (o percentual de cada uma
        # vira o valor que ele dava, que é o que o cliente já viu na pré-conta).
        desconto = self.banco.valor("SELECT desconto_cent FROM vendas WHERE id = ?", (origem_id,), 0)
        if desconto > 0:
            self.banco.executar("UPDATE vendas SET desconto_cent = desconto_cent + ?, desconto_pct = 0 WHERE id = ?",
                                (desconto, destino_id))
        pessoas = self.banco.valor("SELECT pessoas FROM vendas WHERE id = ?", (origem_id,), 0)
        self.banco.executar("UPDATE vendas SET pessoas = pessoas + ?, ultimo_lancamento_em = ?, status = 'aberta' "
                            "WHERE id = ?", (pessoas, fmt.agora(), destino_id))
        self.banco.executar("DELETE FROM vendas WHERE id = ?", (origem_id,))

    def _par(self, posicao_ou_par) -> tuple[bool, int]:
        """Aceita 5 (número inteiro: mesa), (True, 2) (comanda) ou o texto digitado, na notação da loja ('123', 'M5', 'C2').
        Devolve (comanda, número)."""
        if isinstance(posicao_ou_par, tuple):
            return bool(posicao_ou_par[0]), int(posicao_ou_par[1])
        if isinstance(posicao_ou_par, str):
            return self.ler_posicao(posicao_ou_par)
        return False, int(posicao_ou_par)

    def _mesa_aberta(self, numero: int, comanda: bool = False) -> dict:
        r = self.banco.um(
            "SELECT * FROM vendas WHERE modalidade = 'mesa' AND comanda = ? AND posicao = ? "
            "AND status IN ('aberta','conta_enviada')", (int(comanda), numero))
        if r is None:
            raise ErroNegocio(f"A {nome_posicao(comanda, numero).lower()} não está aberta.")
        return dict(r)

    def transferir_mesa(self, origem, destino) -> int:
        """Mesa ou comanda inteira para outra posição (mesa->mesa, mesa->comanda, comanda->comanda...).
        Se o destino já estiver aberto, os itens se somam. Aceita 5, 'C2' ou (True, 2)."""
        c_origem, n_origem = self._par(origem)
        c_destino, n_destino = self._par(destino)
        self.validar_mesa(n_destino, c_destino)
        if (c_origem, n_origem) == (c_destino, n_destino):
            raise ErroNegocio(f"Origem e destino são a mesma {'comanda' if c_destino else 'mesa'}.")
        with self.banco.transacao():
            o = self._mesa_aberta(n_origem, c_origem)
            d = self.banco.um("SELECT id FROM vendas WHERE modalidade = 'mesa' AND comanda = ? AND posicao = ? "
                              "AND status IN ('aberta','conta_enviada')", (int(c_destino), n_destino))
            if d is None:
                self.banco.executar("UPDATE vendas SET posicao = ?, comanda = ?, status = 'aberta' WHERE id = ?",
                                    (n_destino, int(c_destino), o["id"]))
                destino_id = o["id"]
            else:
                destino_id = d["id"]
                self._mover_itens(o["id"], destino_id)
            self.recalcular(destino_id)
            registrar_transferencia(self.banco, self.operador_id, "mesa", rotulo_posicao(c_origem, n_origem),
                                    rotulo_posicao(c_destino, n_destino), o["subtotal_cent"])
        return destino_id

    def transferir_varias(self, origens: list, destino) -> int:
        """Várias mesas/comandas para uma só (tecla T no caixa). Origens: 5, 'C2' ou (True, 2)."""
        c_destino, n_destino = self._par(destino)
        self.validar_mesa(n_destino, c_destino)
        pares = [p for p in dict.fromkeys(self._par(o) for o in origens) if p != (c_destino, n_destino)]
        if not pares:
            raise ErroNegocio("Informe ao menos uma mesa ou comanda de origem.")
        with self.banco.transacao():
            for c, n in pares:
                self._mesa_aberta(n, c)
            destino_id, _ = self.abrir_mesa(n_destino, comanda=c_destino)
            for c, n in pares:
                o = self._mesa_aberta(n, c)
                self._mover_itens(o["id"], destino_id)
                registrar_transferencia(self.banco, self.operador_id, "mesa", rotulo_posicao(c, n),
                                        rotulo_posicao(c_destino, n_destino), o["subtotal_cent"])
            self.recalcular(destino_id)
        return destino_id

    def transferir_item(self, item_id: int, destino, quantidade: float) -> None:
        """Parte dos produtos de uma mesa ou comanda para outra (destino: 5, 'C2' ou (True, 2))."""
        c_destino, n_destino = self._par(destino)
        quantidade = fmt.arred_qtd(quantidade)
        item = self.banco.um("SELECT * FROM itens_venda WHERE id = ? AND cancelado = 0", (item_id,))
        if item is None:
            raise ErroNegocio("Item não encontrado.")
        origem = self._aberta(item["venda_id"])
        if origem["modalidade"] != "mesa":
            raise ErroNegocio("Só é possível transferir itens entre mesas e comandas.")
        if (bool(origem["comanda"]), origem["posicao"]) == (c_destino, n_destino):
            raise ErroNegocio(f"Origem e destino são a mesma {'comanda' if c_destino else 'mesa'}.")
        if not 0 < quantidade <= item["quantidade"]:
            raise ErroNegocio(f"Quantidade inválida (máximo {fmt.fmt_qtd(item['quantidade'], 3)}).")
        with self.banco.transacao():
            destino_id, _ = self.abrir_mesa(n_destino, comanda=c_destino)
            if quantidade == item["quantidade"]:
                self.banco.executar("UPDATE itens_venda SET venda_id = ? WHERE id = ?", (destino_id, item_id))
                valor_movido = item["total_cent"]
            else:
                resto = fmt.arred_qtd(item["quantidade"] - quantidade)
                total_resto = fmt.mult_cent(item["preco_unit_cent"], resto)
                valor_movido = item["total_cent"] - total_resto
                comissao_resto = fmt.arredondar(
                    fmt._dec(item["comissao_cent"]) * fmt._dec(resto) / fmt._dec(item["quantidade"]))
                # As duas partes somam exatamente o total e a comissão originais (sem duplicar nem perder centavo).
                self.banco.executar("UPDATE itens_venda SET quantidade = ?, total_cent = ?, comissao_cent = ? WHERE id = ?",
                                    (resto, total_resto, comissao_resto, item_id))
                novo = dict(item)
                novo.pop("id")
                novo.update(venda_id=destino_id, quantidade=quantidade, total_cent=item["total_cent"] - total_resto,
                            comissao_cent=item["comissao_cent"] - comissao_resto)
                novo_id = self.banco.inserir("itens_venda", novo)
                for pt in self.banco.todos("SELECT produto_id, fracao FROM itens_venda_partes WHERE item_id = ?", (item_id,)):
                    self.banco.inserir("itens_venda_partes", {"item_id": novo_id, "produto_id": pt["produto_id"], "fracao": pt["fracao"]})
            self.banco.executar("UPDATE vendas SET ultimo_lancamento_em = ?, status = 'aberta' WHERE id = ?",
                                (fmt.agora(), destino_id))
            self.recalcular(origem["id"])
            self.recalcular(destino_id)
            registrar_transferencia(
                self.banco, self.operador_id, "item", rotulo_posicao(origem["comanda"], origem["posicao"]),
                rotulo_posicao(c_destino, n_destino), valor_movido, quantidade=quantidade,
                produto=self.banco.valor("SELECT nome FROM produtos WHERE id = ?", (item["produto_id"],)))