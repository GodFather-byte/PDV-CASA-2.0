"""Lançamentos de estoque (manual ADM 5.2 e versão web): compra, entrada, saída,
descarte, contagem/diferença, inicial, pedido (vira compra ao confirmar a entrega) e
descarte de produtos acabados. Também dá baixa/estorno de vendas.

Toda alteração de quantidade passa por `_mover`, que grava um registro em
movimentos_estoque. É esse histórico que permite estornar com exatidão.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import re

from src.core.erros import ErroEstoqueInsuficiente, ErroPermissao
from src.controllers import notificacoes
from src.controllers.produto_controller import ProdutoController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.database.conexao import normalizar

TIPOS = {
    "inicial": "Inicial", "pedido": "Pedido", "compra": "Compra", "entrada": "Entrada",
    "saida": "Saída", "descarte": "Descarte", "contagem": "Contagem (diferença)",
    "desc_acabados": "Descarte de produtos acabados", "quebra": "Quebra",
    "oxidacao": "Oxidação", "devolucao": "Devolução",
}
TIPOS_AJUSTE_GERENTE = {"inicial", "entrada", "saida", "descarte", "contagem", "desc_acabados",
                        "quebra", "oxidacao", "devolucao"}


class EstoqueController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.produtos = ProdutoController(banco)
        self.operador_id = operador_id

    def _exigir_gerente(self) -> None:
        operador_id = self.operador_id if self.operador_id is not None else self.banco._operador_auditoria
        if type(operador_id) is not int:
            raise ErroPermissao("Somente gerente (nível 4) pode ajustar estoque ou custo.")
        operador = self.banco.um("SELECT nivel FROM operadores WHERE id = ? AND ativo = 1", (operador_id,))
        if operador is None or operador["nivel"] < 4:
            raise ErroPermissao("Somente gerente (nível 4) pode ajustar estoque ou custo.")

    @contextmanager
    def _auditar_com_operador(self):
        anterior = self.banco._operador_auditoria
        atual = self.operador_id if self.operador_id is not None else anterior
        if atual != anterior:
            self.banco.definir_operador_auditoria(atual)
        try:
            yield
        finally:
            if atual != anterior:
                self.banco.definir_operador_auditoria(anterior)

    # ---------------------------------------------------------- primitivas
    def _mover(self, produto_id: int, delta: float, tipo: str, ref_tipo: str | None = None,
               ref_id: int | None = None, observacao: str | None = None) -> float:
        agora = fmt.agora()
        tabela = "produtos" if self.produtos.por_id(produto_id) is not None else "produtos_historico"
        if not self.banco.valor(f"SELECT 1 FROM {tabela} WHERE id = ?", (produto_id,)):
            raise ErroNegocio("Produto do movimento de estoque não encontrado.")
        with self._auditar_com_operador(), self.banco.transacao():
            if tabela == "produtos":
                cur = self.banco.executar(
                    "UPDATE produtos SET qt_atual = ROUND(qt_atual + ?, 4), ult_atualizacao = ? "
                    "WHERE id = ? AND (? >= 0 OR ROUND(qt_atual + ?, 4) >= 0)",
                    (delta, agora, produto_id, delta, delta))
            else:
                cur = self.banco.executar(
                    "UPDATE produtos_historico SET qt_atual = ROUND(qt_atual + ?, 4) "
                    "WHERE id = ? AND (? >= 0 OR ROUND(qt_atual + ?, 4) >= 0)",
                    (delta, produto_id, delta, delta))
            if cur.rowcount == 0:
                p = self.produtos.por_id(produto_id)
                nome = p["nome"] if p else self.banco.valor(
                    "SELECT nome FROM produtos_historico WHERE id = ?", (produto_id,), "produto")
                disponivel = self.banco.valor(f"SELECT qt_atual FROM {tabela} WHERE id = ?", (produto_id,), 0)
                raise ErroNegocio(
                    f"Estoque insuficiente de '{nome}': há {fmt.fmt_qtd(disponivel, fmt.CASAS_QTD)}, "
                    f"mas a retirada é de {fmt.fmt_qtd(-delta, fmt.CASAS_QTD)}.")
            apos = self.banco.valor(f"SELECT qt_atual FROM {tabela} WHERE id = ?", (produto_id,))
            self.banco.inserir("movimentos_estoque", {
                "produto_id": produto_id, "tipo": tipo, "quantidade": fmt.arred_qtd(delta),
                "qt_apos": apos, "ref_tipo": ref_tipo, "ref_id": ref_id, "criado_em": agora,
                "operador_id": self.operador_id if self.operador_id is not None else self.banco._operador_auditoria,
                "observacao": observacao})
        return apos

    def _estornar_referencia(self, ref_tipo: str, ref_id: int, tipo_original: str | None, tipo_estorno: str) -> None:
        sql = "SELECT produto_id, quantidade FROM movimentos_estoque WHERE ref_tipo = ? AND ref_id = ?"
        params = [ref_tipo, ref_id]
        if tipo_original:
            sql += " AND tipo = ?"
            params.append(tipo_original)
        for m in self.banco.todos(sql, params):
            self._mover(m["produto_id"], -m["quantidade"], tipo_estorno, ref_tipo, ref_id)

    # ----------------------------------------------------------- vendas
    def baixar_venda(self, venda_id: int) -> None:
        """Dá baixa nos produtos (e insumos da composição) dos itens não cancelados.

        Idempotente: se a venda já tem movimentos de baixa, repetir a chamada não faz nada."""
        with self._auditar_com_operador(), self.banco.transacao():
            if self.banco.um("SELECT 1 FROM movimentos_estoque WHERE ref_tipo = 'venda' AND ref_id = ? "
                             "AND tipo = 'venda' LIMIT 1", (venda_id,)):
                return
            consumos = self._consumos_venda(venda_id)
            faltas = self._faltas_estoque(consumos)
            if faltas:
                raise ErroEstoqueInsuficiente(faltas)
            antes: dict[int, float] = {}
            for produto_id, quantidade in consumos.items():
                antes[produto_id] = self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto_id,), 0)
                self._mover(produto_id, -quantidade, "venda", "venda", venda_id)
        self._avisar_cruzamentos(antes)

    def _consumos_venda(self, venda_id: int) -> dict[int, float]:
        consumos: dict[int, float] = {}
        for item in self.banco.todos(
                "SELECT id, produto_id, quantidade FROM itens_venda WHERE venda_id = ? AND cancelado = 0", (venda_id,)):
            partes = self.banco.todos("SELECT produto_id, fracao FROM itens_venda_partes WHERE item_id = ?", (item["id"],))
            alvos = self._dividir_em_partes(item["quantidade"], partes) or [(item["produto_id"], item["quantidade"])]
            for produto_id, quantidade in alvos:
                for consumo_id, qtd in self.produtos.consumos(produto_id, quantidade):
                    consumos[consumo_id] = fmt.arred_qtd(consumos.get(consumo_id, 0) + qtd)
        return consumos

    def _faltas_estoque(self, consumos: dict[int, float]) -> list[dict]:
        faltas = []
        for produto_id, necessario in consumos.items():
            produto = self.produtos.por_id(produto_id)
            if produto and produto["controla_estoque"] and produto["qt_atual"] < necessario:
                faltas.append({"produto_id": produto_id, "nome": produto["nome"],
                               "disponivel": produto["qt_atual"], "necessario": necessario})
        return faltas

    def _avisar_cruzamentos(self, antes: dict[int, float]) -> None:
        """Avisa o dono (Telegram) dos produtos que, por causa desta baixa, ACABARAM ou entraram no ponto de pedido.
        Só quando o produto cruza o limite (não a cada venda de um produto que já estava zerado)."""
        alertas = []
        for pid, qt_antes in antes.items():
            p = self.produtos.por_id(pid)
            depois = self.produtos.situacao_estoque(p)
            antes_sit = self.produtos.situacao_estoque({**p, "qt_atual": qt_antes})
            if depois != "normal" and depois != antes_sit:
                alertas.append((p["nome"], depois, p["qt_atual"], p["estoque_minimo"]))
        if alertas:
            notificacoes.avisar(self.banco, "estoque", "estoque_alerta", alertas)

    @staticmethod
    def _dividir_em_partes(quantidade: float, partes) -> list[tuple[int, float]]:
        """Reparte a quantidade vendida entre as partes (meio a meio, três sabores...). Cada baixa é arredondada na precisão
        do estoque; a ÚLTIMA parte leva o que falta, para a soma ser exatamente a quantidade vendida (1/3 três vezes
        arredondado dava 0,9999 e uma sobra a cada venda)."""
        alvos, usado = [], 0.0
        for i, p in enumerate(partes):
            q = round(quantidade - usado, fmt.CASAS_QTD) if i == len(partes) - 1 else round(quantidade * p["fracao"], fmt.CASAS_QTD)
            usado += q
            alvos.append((p["produto_id"], q))
        return alvos

    def estornar_venda(self, venda_id: int) -> None:
        """Desfaz a baixa da venda. Idempotente: um segundo estorno não faz nada."""
        if self.banco.um("SELECT 1 FROM movimentos_estoque WHERE ref_tipo = 'venda' AND ref_id = ? "
                         "AND tipo = 'estorno_venda' LIMIT 1", (venda_id,)):
            return
        self._estornar_referencia("venda", venda_id, "venda", "estorno_venda")

    # ------------------------------------------------------- lançamentos
    def criar_lancamento(self, tipo: str, data: str | None = None, descricao: str | None = None,
                         documento: str | None = None, nota_fiscal: str | None = None,
                         fornecedor_id: int | None = None, valor_cent: int = 0) -> int:
        if tipo not in TIPOS:
            raise ErroNegocio(f"Tipo de movimento inválido: {tipo}")
        if tipo in TIPOS_AJUSTE_GERENTE:
            self._exigir_gerente()
        if tipo in ("compra", "pedido") and not fornecedor_id:
            raise ErroNegocio("Informe o fornecedor (cadastre em Manutenção de Cadastros > Fornecedores).")
        tipo_perda = tipo if tipo in ("quebra", "oxidacao", "devolucao") else None
        tipo_registro = "descarte" if tipo_perda else tipo
        return self.banco.inserir("lancamentos_estoque", {
            "tipo": tipo_registro, "tipo_perda": tipo_perda, "data": fmt.para_data_iso(data) or fmt.hoje(),
            "descricao": descricao or TIPOS[tipo], "documento": documento, "nota_fiscal": nota_fiscal,
            "fornecedor_id": fornecedor_id, "valor_cent": valor_cent,
            "operador_id": self.operador_id, "criado_em": fmt.agora()})

    def lancamento(self, lanc_id: int) -> dict:
        r = self.banco.um(
            """SELECT l.*, f.nome AS fornecedor FROM lancamentos_estoque l
               LEFT JOIN fornecedores f ON f.id = l.fornecedor_id WHERE l.id = ?""", (lanc_id,))
        if r is None:
            raise ErroNegocio("Lançamento de estoque não encontrado.")
        return dict(r)

    def lancamentos(self, tipo: str | None = None, de: str | None = None, ate: str | None = None) -> list[dict]:
        onde, params = [], []
        if tipo:
            onde.append("l.tipo = ?"); params.append(tipo)
        if de:
            onde.append("l.data >= ?"); params.append(de)
        if ate:
            onde.append("l.data <= ?"); params.append(ate)
        sql = ("SELECT l.*, f.nome AS fornecedor, (SELECT COALESCE(SUM(valor_cent),0) FROM itens_estoque "
               "WHERE lancamento_id = l.id) AS total_itens FROM lancamentos_estoque l "
               "LEFT JOIN fornecedores f ON f.id = l.fornecedor_id")
        if onde:
            sql += " WHERE " + " AND ".join(onde)
        return [dict(r) for r in self.banco.todos(sql + " ORDER BY l.data DESC, l.id DESC", params)]

    def itens(self, lanc_id: int) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            """SELECT i.*, p.codigo, p.nome, u.abreviatura AS unidade FROM itens_estoque i
               JOIN produtos_historico p ON p.id = i.produto_id JOIN unidades u ON u.id = p.unidade_id
               WHERE i.lancamento_id = ? ORDER BY i.id""", (lanc_id,))]

    def total_itens(self, lanc_id: int) -> int:
        return self.banco.valor("SELECT SUM(valor_cent) FROM itens_estoque WHERE lancamento_id = ?", (lanc_id,), 0)

    # ----------------------------------------------------------- itens
    @staticmethod
    def _validar_quantidade(quantidade: float) -> float:
        try:
            return fmt.validar_qtd(quantidade)
        except ValueError as exc:
            raise ErroNegocio(str(exc).capitalize() + ".") from None

    def adicionar_item(self, lanc_id: int, produto_id: int, quantidade: float, valor_cent: int = 0,
                       desconto_cent: int = 0, estoque_minimo: float | None = None, ligar_controle: bool = False,
                       observacao: str | None = None) -> int:
        """Lança um item e já atualiza o estoque (como o sistema original).

        `valor_cent` é o total do item na nota (não o unitário). Com `ligar_controle`, uma compra/entrada/contagem de produto
        que ainda não controla estoque liga o controle (o saldo parte de 0); sem ele, o produto é recusado.

        Fardo/caixa fechada (`ProdutoController.embalagem`) não tem estoque próprio: o item é gravado nas unidades (10 fardos
        de 12 viram 120 latas, pelo mesmo valor da nota). Contagem e inventário inicial de fardo são recusados."""
        lanc = self.lancamento(lanc_id)
        tipo = lanc["tipo_perda"] or lanc["tipo"]
        if tipo in TIPOS_AJUSTE_GERENTE:
            self._exigir_gerente()
        p = self.produtos.por_id(produto_id)
        if p is None:
            raise ErroNegocio("Produto não encontrado.")
        quantidade = self._validar_quantidade(quantidade)
        emb = self.produtos.embalagem(produto_id) if tipo != "desc_acabados" else None
        if emb:
            if tipo in ("inicial", "contagem"):
                raise ErroNegocio(f"'{p['nome']}' é um fardo/caixa de {emb['quantidade']} '{emb['unitario']}' e não tem estoque "
                                  f"próprio: conte as unidades no produto '{emb['unitario']}'.")
            produto_id, p = emb["unitario_id"], self.produtos.por_id(emb["unitario_id"])
            quantidade = fmt.arred_qtd(quantidade * emb["quantidade"])
        if quantidade < 0 or (quantidade == 0 and tipo not in ("inicial", "contagem")):
            raise ErroNegocio("Informe uma quantidade maior que zero.")
        if tipo == "desc_acabados" and not self.produtos.composicao(produto_id):
            raise ErroNegocio(f"'{p['nome']}' não tem composição (ficha técnica) cadastrada.")
        liga_controle = False
        if tipo not in ("inicial", "desc_acabados") and not p["controla_estoque"]:
            if not ligar_controle or tipo not in ("compra", "entrada", "contagem"):
                raise ErroNegocio(f"'{p['nome']}' não controla estoque. Marque 'Controla estoque' no cadastro do produto.")
            liga_controle = True
        if tipo in ("inicial", "contagem") and self.banco.um(
                "SELECT 1 FROM itens_estoque WHERE lancamento_id = ? AND produto_id = ?", (lanc_id, produto_id)):
            raise ErroNegocio(f"'{p['nome']}' já foi lançado neste movimento. Exclua o item para lançá-lo de novo.")

        with self._auditar_com_operador(), self.banco.transacao():
            if liga_controle:
                self.banco.executar("UPDATE produtos SET controla_estoque = 1 WHERE id = ?", (produto_id,))
                self.banco.log("estoque_controle_ligado", p["nome"], self.operador_id)
            item_id = self.banco.inserir("itens_estoque", {
                "lancamento_id": lanc_id, "produto_id": produto_id, "quantidade": quantidade,
                "preco_unit_cent": fmt.dividir_cent(max(valor_cent - desconto_cent, 0), quantidade),
                "desconto_cent": desconto_cent, "valor_cent": valor_cent,
                "qt_anterior": p["qt_atual"], "diferenca": 0, "aplicado": 0})
            if lanc["tipo"] != "pedido":
                self._aplicar_item(item_id, tipo, p, quantidade, valor_cent, desconto_cent,
                                   observacao)
            if estoque_minimo is not None:
                self.banco.executar("UPDATE produtos SET estoque_minimo = ? WHERE id = ?",
                                    (fmt.arred_qtd(estoque_minimo), produto_id))
            self._atualizar_total(lanc_id)
        return item_id

    def _aplicar_item(self, item_id: int, tipo: str, p: dict, qtd: float, valor_cent: int, desconto_cent: int,
                      observacao: str | None = None) -> None:
        pid = p["id"]
        antes = p["qt_atual"]
        if tipo == "inicial":
            self.banco.executar("UPDATE produtos SET controla_estoque = 1, qt_inicial = ? WHERE id = ?", (qtd, pid))
            self._mover(pid, qtd - antes, "inicial", "item_estoque", item_id)
        elif tipo == "compra":
            self._mover(pid, qtd, "compra", "item_estoque", item_id)
            unit = fmt.dividir_cent(max(valor_cent - desconto_cent, 0), qtd)
            self.banco.executar("UPDATE produtos SET ult_preco_cent = ? WHERE id = ?", (unit, pid))
        elif tipo == "entrada":
            self._mover(pid, qtd, "entrada", "item_estoque", item_id)
        elif tipo in ("saida", "descarte", "quebra", "oxidacao", "devolucao"):
            self._mover(pid, -qtd, tipo, "item_estoque", item_id,
                        observacao if tipo in ("quebra", "oxidacao", "devolucao") else None)
        elif tipo == "contagem":
            self._mover(pid, qtd - antes, "contagem", "item_estoque", item_id)
        elif tipo == "desc_acabados":
            for consumo_id, q in self.produtos.consumos(pid, qtd):
                self._mover(consumo_id, -q, "desc_acabados", "item_estoque", item_id)
        depois = self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (pid,))
        self.banco.executar("UPDATE itens_estoque SET aplicado = 1, diferenca = ? WHERE id = ?",
                            (fmt.arred_qtd(depois - antes), item_id))

    def remover_item(self, item_id: int) -> None:
        """Exclui o item e desfaz o efeito dele no estoque."""
        item = self.banco.um("SELECT * FROM itens_estoque WHERE id = ?", (item_id,))
        if item is None:
            raise ErroNegocio("Item não encontrado.")
        lanc = self.lancamento(item["lancamento_id"])
        if item["aplicado"] or lanc["tipo"] in TIPOS_AJUSTE_GERENTE or lanc["tipo_perda"]:
            self._exigir_gerente()
        with self._auditar_com_operador(), self.banco.transacao():
            if item["aplicado"]:
                self._estornar_referencia("item_estoque", item_id, None, "estorno")
            self.banco.executar("DELETE FROM itens_estoque WHERE id = ?", (item_id,))
            if lanc["tipo"] == "compra":
                self._recalcular_ult_preco(item["produto_id"])
            self._atualizar_total(item["lancamento_id"])

    def excluir_lancamento(self, lanc_id: int) -> None:
        with self._auditar_com_operador(), self.banco.transacao():
            for it in self.banco.todos("SELECT id FROM itens_estoque WHERE lancamento_id = ?", (lanc_id,)):
                self.remover_item(it["id"])
            self.banco.executar("DELETE FROM contas WHERE lancamento_estoque_id = ? AND dt_quitacao IS NULL", (lanc_id,))
            self.banco.executar("DELETE FROM lancamentos_estoque WHERE id = ?", (lanc_id,))

    def _atualizar_total(self, lanc_id: int) -> None:
        total = self.total_itens(lanc_id)
        self.banco.executar("UPDATE lancamentos_estoque SET valor_cent = CASE WHEN tipo = 'compra' "
                            "THEN valor_cent ELSE ? END WHERE id = ?", (total, lanc_id))

    def _recalcular_ult_preco(self, produto_id: int) -> None:
        r = self.banco.um(
            """SELECT i.valor_cent, i.desconto_cent, i.quantidade FROM itens_estoque i
               JOIN lancamentos_estoque l ON l.id = i.lancamento_id
               WHERE i.produto_id = ? AND l.tipo = 'compra' AND i.quantidade > 0
               ORDER BY l.data DESC, i.id DESC LIMIT 1""", (produto_id,))
        unit = fmt.dividir_cent(max(r["valor_cent"] - r["desconto_cent"], 0), r["quantidade"]) if r else 0
        self.banco.executar("UPDATE produtos SET ult_preco_cent = ? WHERE id = ?", (unit, produto_id))

    def definir_minimo(self, produto_id: int, minimo: float) -> None:
        self._exigir_gerente()
        with self._auditar_com_operador():
            self.banco.executar("UPDATE produtos SET estoque_minimo = ? WHERE id = ?", (fmt.arred_qtd(minimo), produto_id))

    def alterar_custo(self, produto_id: int, custo_cent: int) -> None:
        self._exigir_gerente()
        if type(custo_cent) is not int or custo_cent < 0:
            raise ErroNegocio("O custo deve ser informado em centavos inteiros e não negativos.")
        if self.produtos.por_id(produto_id) is None:
            raise ErroNegocio("Produto não encontrado.")
        with self._auditar_com_operador():
            self.banco.executar("UPDATE produtos SET ult_preco_cent = ? WHERE id = ?", (custo_cent, produto_id))

    # ------------------------------------------------------------ pedido
    def confirmar_pedido(self, lanc_id: int, valores: dict | None = None) -> None:
        """Confirma a entrega de um pedido: ele vira COMPRA e passa a mexer no estoque.
        `valores` = {item_id: total_do_item_em_centavos} (o valor só é conhecido na entrega)."""
        lanc = self.lancamento(lanc_id)
        if lanc["tipo"] != "pedido":
            raise ErroNegocio("Somente pedidos podem ter a entrega confirmada.")
        itens = self.itens(lanc_id)
        if not itens:
            raise ErroNegocio("O pedido não tem itens.")
        with self._auditar_com_operador(), self.banco.transacao():
            for it in itens:
                total = (valores or {}).get(it["id"], it["valor_cent"])
                self.banco.executar(
                    "UPDATE itens_estoque SET valor_cent = ?, preco_unit_cent = ? WHERE id = ?",
                    (total, fmt.dividir_cent(max(total - it["desconto_cent"], 0), it["quantidade"]), it["id"]))
            self.banco.executar("UPDATE lancamentos_estoque SET tipo = 'compra' WHERE id = ?", (lanc_id,))
            for it in self.itens(lanc_id):
                p = self.produtos.por_id(it["produto_id"])
                self.banco.executar("UPDATE itens_estoque SET qt_anterior = ? WHERE id = ?", (p["qt_atual"], it["id"]))
                self._aplicar_item(it["id"], "compra", p, it["quantidade"], it["valor_cent"], it["desconto_cent"])
            self.banco.executar("UPDATE lancamentos_estoque SET valor_cent = ? WHERE id = ?",
                                (self.total_itens(lanc_id), lanc_id))

    # ----------------------------------------------------- listas de apoio
    def itens_para_contagem(self) -> list[dict]:
        """Base do formulário de contagem física."""
        return [dict(r) for r in self.banco.todos(
            """SELECT p.id, p.codigo, p.nome, p.qt_atual, u.abreviatura AS unidade FROM produtos p
               JOIN unidades u ON u.id = p.unidade_id
               WHERE p.controla_estoque = 1 AND p.ativo = 1 ORDER BY p.nome""")]

    # ------------------------------------------------- visão geral (painel)
    ROTULO_MOVIMENTO = {
        "inicial": "Estoque inicial", "compra": "Compra", "entrada": "Entrada", "saida": "Saída", "descarte": "Descarte",
        "contagem": "Contagem", "desc_acabados": "Descarte de acabado", "venda": "Venda", "estorno_venda": "Venda cancelada",
        "estorno": "Lançamento desfeito", "quebra": "Quebra", "oxidacao": "Oxidação", "devolucao": "Devolução",
    }

    @staticmethod
    def _texto_adega(texto: str | None) -> str:
        return " ".join(re.sub(r"[^A-Z0-9]+", " ", normalizar(texto or "")).split())

    @classmethod
    def _classificacao_adega(cls, p: dict) -> str | None:
        """Recorte indicativo, não fiscal; sinais explícitos precedem famílias do cadastro."""
        if (p["preco_gelada_cent"] > 0 or p["atacado_qtd"] > 0 or p["atacado_gelada_qtd"] > 0
                or p["casco_produto_id"] is not None or p["casco_vinculado"]):
            return "Configuração de gelada/atacado/casco"
        familias = {
            "ADEGA", "BEBIDA", "BEBIDAS", "CONVENIENCIA", "CERVEJA", "CERVEJAS",
            "DESTILADO", "DESTILADOS", "VINHO", "VINHOS", "ESPUMANTE", "ESPUMANTES",
            "REFRIGERANTE", "REFRIGERANTES", "AGUA", "AGUAS", "SUCO", "SUCOS",
            "ENERGETICO", "ENERGETICOS", "GELO", "CARVAO", "WHISKY", "WHISKEY",
            "VODKA", "GIN", "CACHACA", "LICOR", "RUM", "TEQUILA",
        }
        for campo in ("grupo", "categoria"):
            termos = cls._texto_adega(p[campo]).split()
            if familias.intersection(termos):
                return "Família do grupo/subgrupo"
        # Somente prefixos descritivos inequívocos, sem marcas nem trechos de palavras.
        nome = cls._texto_adega(p["nome"])
        prefixos = ("CERVEJA", "VINHO", "ESPUMANTE", "REFRIGERANTE", "ENERGETICO",
                    "WHISKY", "WHISKEY", "VODKA", "CACHACA", "TEQUILA", "GIN",
                    "SUCO", "AGUA MINERAL", "AGUA COM GAS", "AGUA SEM GAS",
                    "GELO EM CUBOS", "CARVAO VEGETAL")
        if any(nome == termo or nome.startswith(termo + " ") for termo in prefixos):
            return "Nome indicativo"
        return None

    def _consumo_30_dias(self) -> dict[int, float]:
        """Saídas líquidas no intervalo local [agora - 30 dias, agora], já em unidades."""
        agora = fmt.agora()
        inicio = (datetime.fromisoformat(agora) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        return {r["produto_id"]: max(round(-r["saldo"], fmt.CASAS_QTD), 0)
                for r in self.banco.todos(
                    """SELECT produto_id, SUM(quantidade) AS saldo FROM movimentos_estoque
                       WHERE tipo IN ('venda', 'estorno_venda') AND ref_tipo = 'venda'
                         AND criado_em >= ? AND criado_em <= ? GROUP BY produto_id""", (inicio, agora))}

    def painel(self, situacao: str | None = None, texto: str = "", grupo: str | None = None,
               adega: bool = False) -> list[dict]:
        """Produtos que controlam estoque, já com a situação (sem/ponto/normal), o valor parado e o quanto repor.

        `situacao` filtra por 'sem', 'ponto', 'normal' ou 'livre' (produtos que ainda não controlam estoque); `texto` procura no
        nome sem acentos, código ou código de barras (e inclui os que não controlam);
        `grupo` filtra pelo grupo do produto.
        `adega` recorta famílias/configurações/nomes indicativos e inclui consumo líquido e cobertura em 30 dias."""
        return self._painel(situacao, texto, grupo, adega=adega, calcular_cobertura=adega)

    def _painel(self, situacao: str | None = None, texto: str = "", grupo: str | None = None,
                 adega: bool = False, *, calcular_cobertura: bool = False) -> list[dict]:
        """Base comum de saldo/recorte; resumo e compras não precisam consultar o histórico."""
        busca = normalizar((texto or "").strip())
        # Quem procura por nome também acha o produto que ainda NÃO controla estoque (senão o RedBull cadastrado sem a marca
        # "Controla estoque" ficava invisível, sem como começar a controlar). 'livre' lista só esses.
        controle = "p.controla_estoque = 1" if not busca and situacao != "livre" else \
                   "p.controla_estoque = 0" if situacao == "livre" else "1 = 1"
        consumos = self._consumo_30_dias() if calcular_cobertura else {}
        linhas = []
        for r in self.banco.todos(
                f"""SELECT p.id, p.codigo, p.cbarra, p.nome, p.qt_atual, p.estoque_minimo, p.ult_preco_cent, p.ult_atualizacao,
                          p.controla_estoque, p.preco_gelada_cent, p.atacado_qtd, p.atacado_gelada_qtd,
                          p.casco_produto_id,
                          p.id IN (SELECT casco_produto_id FROM produtos
                                   WHERE casco_produto_id IS NOT NULL) AS casco_vinculado,
                          u.abreviatura AS unidade, g.nome AS grupo, s.nome AS categoria
                   FROM produtos p JOIN unidades u ON u.id = p.unidade_id
                   JOIN subgrupos s ON s.id = p.subgrupo_id JOIN grupos g ON g.id = s.grupo_id
                   WHERE {controle} AND p.ativo = 1 ORDER BY p.controla_estoque DESC, p.nome"""):
            p = dict(r)
            if adega:
                p["classificacao_adega"] = self._classificacao_adega(p)
                if not p["classificacao_adega"]:
                    continue
            p["situacao"] = self.produtos.situacao_estoque(p) if p["controla_estoque"] else "livre"
            if situacao and p["situacao"] != situacao:
                continue
            if grupo and p["grupo"] != grupo:
                continue
            if busca and not any(busca in normalizar(campo or "") for campo in
                                 (p["nome"], p["codigo"], p["cbarra"])):
                continue
            p["valor_cent"] = round(max(p["qt_atual"], 0) * p["ult_preco_cent"]) if p["controla_estoque"] else 0
            p["repor"] = self.sugestao_reposicao(p)
            p["prioridade"] = {"sem": "Alta", "ponto": "Média", "normal": "Baixa", "livre": "Definir controle"}[p["situacao"]]
            if calcular_cobertura:
                p["consumo_30_dias"] = consumos.get(p["id"], 0)
                p["media_diaria"] = p["consumo_30_dias"] / 30
                p["cobertura_dias"] = (max(p["qt_atual"], 0) / p["media_diaria"]
                                       if p["controla_estoque"] and p["media_diaria"] > 0 else None)
                p["cobertura_rotulo"] = (
                    "Sem controle" if not p["controla_estoque"] else
                    "Sem consumo líquido em 30 dias" if p["cobertura_dias"] is None else
                    f"{p['cobertura_dias']:.1f} dias".replace(".", ","))
            linhas.append(p)
        if adega:
            linhas.sort(key=lambda p: (("sem", "ponto", "normal", "livre").index(p["situacao"]), p["nome"]))
        return linhas

    @staticmethod
    def sugestao_reposicao(p: dict) -> float:
        """Quanto comprar para o produto voltar a uma folga confortável (o dobro do mínimo). Sem mínimo cadastrado, não sugere."""
        if p["situacao"] in ("normal", "livre") or p["estoque_minimo"] <= 0:
            return 0.0
        return fmt.arred_qtd(max(p["estoque_minimo"] * 2 - max(p["qt_atual"], 0), 0))

    def resumo(self, adega: bool = False) -> dict:
        """Contagem por situação e valor total parado em estoque (quantidade × último preço de compra)."""
        todos = self._painel(adega=adega)
        r = {"total": len(todos), "sem": 0, "ponto": 0, "normal": 0, "valor_cent": sum(p["valor_cent"] for p in todos)}
        for p in todos:
            r[p["situacao"]] += 1
        r["livre"] = len(self._painel("livre", adega=True)) if adega else self.banco.valor(
            "SELECT COUNT(*) FROM produtos WHERE controla_estoque = 0 AND ativo = 1", (), 0)
        return r

    def grupos(self) -> list[str]:
        return [r["nome"] for r in self.banco.todos("SELECT nome FROM grupos ORDER BY nome")]

    def historico(self, produto_id: int, limite: int = 30) -> list[dict]:
        """Últimos movimentos do produto (mais recente primeiro), com o nome do tipo em português."""
        saida = []
        for r in self.banco.todos(
                "SELECT * FROM movimentos_estoque WHERE produto_id = ? ORDER BY id DESC LIMIT ?", (produto_id, limite)):
            m = dict(r)
            m["rotulo"] = self.ROTULO_MOVIMENTO.get(m["tipo"], m["tipo"])
            saida.append(m)
        return saida

    def registrar_rapido(self, produto_id: int, tipo: str, quantidade: float, descricao: str | None = None) -> int:
        """Um movimento de um item só (entrada, saída, descarte ou contagem), sem montar lançamento na mão.

        Cria o lançamento do dia com o item e devolve o id. Em 'contagem' a quantidade é o que existe de verdade na prateleira."""
        if tipo not in ("entrada", "saida", "descarte", "contagem", "quebra", "oxidacao", "devolucao"):
            raise ErroNegocio("Tipo inválido para movimento rápido de estoque.")
        p = self.produtos.por_id(produto_id)
        if p is None:
            raise ErroNegocio("Produto não encontrado.")
        quantidade = self._validar_quantidade(quantidade)
        emb = self.produtos.embalagem(produto_id)
        if emb and tipo != "contagem":               # fardo/caixa: o movimento é das unidades (a contagem o adicionar_item recusa)
            produto_id, quantidade = emb["unitario_id"], fmt.arred_qtd(quantidade * emb["quantidade"])
            p = self.produtos.por_id(produto_id)
        if tipo in ("saida", "descarte", "quebra", "oxidacao", "devolucao") \
                and fmt.arred_qtd(quantidade) > max(p["qt_atual"], 0) and p["controla_estoque"]:
            raise ErroNegocio(f"Só há {fmt.fmt_qtd(p['qt_atual'])} de '{p['nome']}' em estoque; não dá para tirar {fmt.fmt_qtd(quantidade)}.")
        with self.banco.transacao():
            lanc = self.criar_lancamento(tipo, descricao=descricao or f"{TIPOS[tipo]} rápida - {p['nome']}")
            self.adicionar_item(lanc, produto_id, quantidade,
                                ligar_controle=not p["controla_estoque"] and tipo in ("entrada", "contagem"),
                                observacao=descricao)
        return lanc

    def pedido_sugerido(self, fornecedor_id: int, produtos: list[tuple[int, float]] | None = None, *,
                        adega: bool = False, situacao: str | None = None, texto: str = "",
                        grupo: str | None = None) -> int:
        """Cria um PEDIDO com o que está faltando (sem estoque ou no ponto de pedido), na quantidade sugerida.

        `produtos` = [(produto_id, quantidade)] para escolher à mão; sem ele, usa a sugestão do recorte.
        Adega combina os mesmos filtros do painel; itens explícitos também devem pertencer ao recorte a repor.
        Sem filtros, mantém o pedido geral de todos os que precisam repor."""
        sugestoes = self.lista_de_compras(adega=adega, situacao=situacao, texto=texto, grupo=grupo)
        if produtos is not None and adega:
            permitidos = {p["id"] for p in sugestoes}
            if any(pid not in permitidos for pid, _ in produtos):
                raise ErroNegocio("O pedido Adega só permite produtos a repor do recorte selecionado.")
        itens = produtos if produtos is not None else [(p["id"], p["repor"]) for p in sugestoes]
        itens = [(pid, q) for pid, q in itens if q > 0]
        if not itens:
            raise ErroNegocio("Nenhum produto precisa de reposição agora (ou falta definir o estoque mínimo).")
        with self.banco.transacao():
            lanc = self.criar_lancamento("pedido", descricao="Pedido sugerido pelo painel" + (" Adega" if adega else ""),
                                        fornecedor_id=fornecedor_id)
            for pid, q in itens:
                self.adicionar_item(lanc, pid, q)
        return lanc

    def lista_de_compras(self, *, adega: bool = False, situacao: str | None = None,
                         texto: str = "", grupo: str | None = None) -> list[dict]:
        """Produtos a repor; os filtros opcionais reutilizam exatamente o recorte do painel."""
        falta = [p for p in self._painel(situacao, texto, grupo, adega=adega) if p["repor"] > 0]
        return sorted(falta, key=lambda p: (p["situacao"] != "sem", p["nome"]))
