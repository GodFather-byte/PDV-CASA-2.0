"""Pedido online (Will Adega): o pedido que o cliente fez no cardápio vira uma entrega no caixa, já preenchida.

O preço é o do caixa na hora de aceitar (o do cardápio é só estimativa). O cliente é achado pelo telefone ou cadastrado; o
bairro vem pelo nome. Produto que saiu de venda fica de fora e é avisado. Aceitar o mesmo pedido duas vezes (a nuvem não
respondeu e o caixa tentou de novo) devolve a entrega que já existe.
"""
from __future__ import annotations

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

PAGAMENTOS = {"dinheiro": "Dinheiro", "pix": "Pix na entrega", "cartao": "Cartão na entrega"}


def marca(numero) -> str:
    """O que fica no recado da entrega e identifica o pedido online (também evita importar duas vezes)."""
    return f"Pedido online #{int(numero)}"


def resumo(pedido: dict) -> str:
    """Uma linha para a lista do caixa: '#12 · João · Centro · 3 itens · R$ 87,50'."""
    onde = "Retira na loja" if pedido.get("retirada") else (pedido.get("bairro") or "Sem bairro")
    itens = sum(int(i.get("qtd") or 0) for i in pedido.get("itens") or [])
    return (f"#{pedido.get('numero')} · {pedido.get('nome', '')} · {onde} · {itens} ite{'ns' if itens != 1 else 'm'} · "
            f"{fmt.fmt_brl(int(pedido.get('total_cent') or 0))}")


def detalhe(pedido: dict) -> str:
    linhas = [resumo(pedido), ""]
    for i in pedido.get("itens") or []:
        linhas.append(f"{i.get('qtd')}x {i.get('nome')}")
    linhas.append("")
    if not pedido.get("retirada"):
        linhas.append(f"Entrega: {pedido.get('endereco', '')} · {pedido.get('bairro') or 'bairro não informado'}")
    pagamento = PAGAMENTOS.get(pedido.get("pagamento"), pedido.get("pagamento") or "")
    if pedido.get("troco_para_cent"):
        pagamento += f" (troco para {fmt.fmt_brl(int(pedido['troco_para_cent']))})"
    linhas.append(f"Pagamento: {pagamento}")
    linhas.append(f"Telefone: {pedido.get('telefone', '')}")
    if pedido.get("observacao"):
        linhas.append(f"Obs.: {pedido['observacao']}")
    return "\n".join(linhas)


class PedidoOnlineController:
    def __init__(self, banco, caixa, entregas, produtos, operador_id: int | None = None):
        self.banco = banco
        self.caixa = caixa
        self.entregas = entregas
        self.produtos = produtos
        self.operador_id = operador_id

    def ja_importado(self, numero) -> int | None:
        r = self.banco.um("SELECT id FROM vendas WHERE modalidade = 'entrega' AND mensagem LIKE ? AND status <> 'cancelada' "
                          "ORDER BY id DESC LIMIT 1", (marca(numero) + "%",))
        return r["id"] if r else None

    def _cliente(self, pedido: dict) -> int:
        """O cliente pelo telefone (só os números); sem cadastro, cria um com o endereço do pedido."""
        telefone = "".join(c for c in str(pedido.get("telefone") or "") if c.isdigit())
        if not telefone:
            raise ErroNegocio("Pedido sem telefone.")
        bairro = None
        if pedido.get("bairro"):
            b = self.banco.um("SELECT id FROM bairros WHERE nome = ? COLLATE NOCASE", (pedido["bairro"],))
            bairro = b["id"] if b else None
        for r in self.banco.todos("SELECT id, telefone, ativo FROM clientes WHERE telefone IS NOT NULL AND telefone <> ''"):
            if r["ativo"] and "".join(c for c in r["telefone"] if c.isdigit()).endswith(telefone[-8:]):
                if not pedido.get("retirada") and pedido.get("endereco"):
                    self.banco.atualizar("clientes", r["id"], {"endereco": pedido["endereco"][:60],
                                                              **({"bairro_id": bairro} if bairro else {})})
                return r["id"]
        from src.controllers.cadastro_controller import CadastroController
        cadastro = CadastroController(self.banco)
        return cadastro.salvar("clientes", {
            "numero_consulta": cadastro.proximo_numero_cliente(), "nome": (pedido.get("nome") or "Cliente online")[:60], "telefone": telefone[:20],
            "endereco": (pedido.get("endereco") or "")[:60], "bairro_id": bairro, "ativo": 1})

    def importar(self, pedido: dict) -> dict:
        """Cria a entrega do pedido. Devolve venda_id, os itens que ficaram de fora e se já existia."""
        if not self.banco.cfg_bool("pedido_online", False):
            raise ErroNegocio("O pedido online está desligado (Configurações > Módulos).")
        existente = self.ja_importado(pedido.get("numero"))
        if existente:
            return {"venda_id": existente, "faltando": [], "ja_existia": True}
        faltando, linhas = [], []
        for item in pedido.get("itens") or []:
            p = self.produtos.buscar_codigo(str(item.get("codigo") or ""))
            qtd = int(item.get("qtd") or 0)
            if p is None or not p["ativo"] or qtd <= 0:
                faltando.append(f"{qtd}x {item.get('nome')}")
            else:
                linhas.append((p["id"], qtd))
        if not linhas:
            raise ErroNegocio("Nenhum produto do pedido está à venda agora. Recuse o pedido e avise o cliente.")
        pagamento = PAGAMENTOS.get(pedido.get("pagamento"), "")
        recado = " · ".join(x for x in (
            marca(pedido.get("numero")), "RETIRA NA LOJA" if pedido.get("retirada") else "", pagamento,
            pedido.get("observacao") or "") if x)
        with self.banco.transacao():
            venda_id = self.entregas.abrir(self._cliente(pedido))
            if pedido.get("retirada"):
                self.banco.atualizar("vendas", venda_id, {"taxa_cent": 0})
            for produto_id, qtd in linhas:
                self.caixa.adicionar_item(venda_id, produto_id, qtd)
            troco = int(pedido.get("troco_para_cent") or 0) if pedido.get("pagamento") == "dinheiro" else 0
            self.banco.atualizar("vendas", venda_id, {"mensagem": recado[:200],
                                                     **({"troco_para_cent": troco} if troco else {})})
        self.banco.log("pedido_online_aceito", f"{marca(pedido.get('numero'))}: venda {venda_id}", self.operador_id)
        return {"venda_id": venda_id, "faltando": faltando, "ja_existia": False}
