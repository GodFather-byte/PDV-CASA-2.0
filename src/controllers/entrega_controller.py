"""Delivery (manual do Caixa, tecla F6): pedido para cliente cadastrado, taxa pelo
bairro, troco para quanto, entregador e acompanhamento dos pedidos em rota."""
from __future__ import annotations

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio


class EntregaController:
    def __init__(self, banco, caixa):
        self.banco = banco
        self.caixa = caixa

    def abrir(self, cliente_id: int) -> int:
        """Novo pedido de entrega. A taxa vem do bairro do cliente (ou da taxa padrão)."""
        cli = self.banco.um(
            """SELECT c.*, b.taxa_cent AS taxa_bairro FROM clientes c
               LEFT JOIN bairros b ON b.id = c.bairro_id WHERE c.id = ?""", (cliente_id,))
        if cli is None or not cli["ativo"]:
            raise ErroNegocio("Cliente inativo ou inexistente.")
        taxa = cli["taxa_bairro"]
        if taxa is None:
            taxa = fmt.para_centavos(self.banco.cfg("taxa_entrega_padrao", "0") or 0)
        pedido = self.banco.valor("SELECT COALESCE(MAX(posicao), 1000) + 1 FROM vendas WHERE modalidade = 'entrega'")
        with self.banco.transacao():
            return self.caixa._nova("entrega", pedido, cliente_id=cliente_id, taxa_cent=taxa)

    def definir_dados(self, venda_id: int, troco_para_cent: int | None = None,
                      entregador_id: int | None = None, mensagem: str | None = None) -> int:
        """Janela 'liberar troco': quanto o cliente vai pagar, entregador e recado.
        Devolve o troco que o motoboy deve levar."""
        v = self.caixa._aberta(venda_id)
        if v["modalidade"] != "entrega":
            raise ErroNegocio("Esta venda não é uma entrega.")
        dados = {}
        if troco_para_cent is not None:
            if troco_para_cent < 0:
                raise ErroNegocio("Valor inválido para o troco.")
            dados["troco_para_cent"] = troco_para_cent
        if entregador_id is not None:
            dados["entregador_id"] = entregador_id
        if mensagem is not None:
            dados["mensagem"] = mensagem.strip() or None
        self.banco.atualizar("vendas", venda_id, dados)
        return self.troco_a_levar(venda_id)

    def troco_a_levar(self, venda_id: int) -> int:
        v = self.caixa.obter(venda_id)
        return max(v["troco_para_cent"] - v["total_cent"], 0) if v["troco_para_cent"] else 0

    def emitir_pedido(self, venda_id: int) -> dict:
        """F8: fecha o lançamento e deixa o pedido aguardando entregador/pagamento."""
        v = self.caixa._aberta(venda_id)
        if v["modalidade"] != "entrega":
            raise ErroNegocio("Esta venda não é uma entrega.")
        if not self.caixa.itens(venda_id):
            raise ErroNegocio("O pedido não tem itens.")
        if v["troco_para_cent"] and v["troco_para_cent"] < self.caixa.recalcular(venda_id)["total"]:
            raise ErroNegocio("O valor que o cliente vai pagar é menor que o total do pedido.")
        self.banco.executar("UPDATE vendas SET status = 'conta_enviada' WHERE id = ?", (venda_id,))
        return self.caixa.obter(venda_id)

    def atribuir_entregador(self, venda_id: int, entregador_id: int) -> None:
        """Tecla E na lista de entregas: registra quem leva e a hora da saída."""
        v = self.caixa._aberta(venda_id)
        if v["modalidade"] != "entrega":
            raise ErroNegocio("Esta venda não é uma entrega.")
        ent = self.banco.um("SELECT entregador, ativo FROM operadores WHERE id = ?", (entregador_id,))
        if ent is None or not ent["ativo"]:
            raise ErroNegocio("Entregador inválido.")
        self.banco.executar("UPDATE vendas SET entregador_id = ?, saida_entrega_em = ? WHERE id = ?",
                            (entregador_id, fmt.agora(), venda_id))

    def pendentes(self) -> list[dict]:
        """Pedidos emitidos e ainda não pagos (a lista 'Entregas' da tela do caixa)."""
        linhas = [dict(r) for r in self.banco.todos(
            """SELECT v.*, c.nome AS cliente, c.endereco, b.nome AS bairro, o.nome AS entregador
               FROM vendas v JOIN clientes c ON c.id = v.cliente_id
               LEFT JOIN bairros b ON b.id = c.bairro_id LEFT JOIN operadores o ON o.id = v.entregador_id
               WHERE v.modalidade = 'entrega' AND v.status IN ('aberta','conta_enviada') ORDER BY v.id""")]
        for e in linhas:
            e["hora_pedido"] = fmt.fmt_hora(e["aberta_em"])[:5]
            e["t_pedido"] = fmt.minutos_entre(e["aberta_em"])
            e["t_entrega"] = fmt.minutos_entre(e["saida_entrega_em"]) if e["saida_entrega_em"] else 0
        return linhas
