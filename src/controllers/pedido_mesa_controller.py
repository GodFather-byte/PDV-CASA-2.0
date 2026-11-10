"""Importação idempotente de pedidos online de mesa, sempre pelo CaixaController."""
from src.core import edicao, formatacao as fmt
from src.core.erros import ErroNegocio


def importar(ctrl, pedido):
    b = ctrl.banco
    mesa, pedido_id = pedido.get("mesa"), pedido.get("id")
    if edicao.atual().chave != "willrestaurante" or not b.cfg_bool("usar_mesas"):
        raise ErroNegocio("Pedido online de mesa não está disponível nesta edição.")
    if type(mesa) is not int or not 1 <= mesa <= b.cfg_int("num_mesas", 0):
        raise ErroNegocio("Mesa fora da configuração da loja.")
    if type(pedido_id) is not int or pedido_id <= 0:
        raise ErroNegocio("Pedido de mesa sem identificação da nuvem.")
    with b.transacao():
        existente = b.um("SELECT venda_id FROM pedidos_mesa_importados WHERE pedido_id = ?", (pedido_id,))
        if existente:
            return {"venda_id": existente["venda_id"], "faltando": [], "ja_existia": True}
        itens = pedido.get("itens")
        if not isinstance(itens, list) or not itens:
            raise ErroNegocio("Pedido de mesa sem itens.")
        venda_id, _ = ctrl.caixa.abrir_mesa(mesa, comanda=False)
        item_ids = []
        for i in itens:
            p = ctrl.produtos.buscar_codigo(str(i.get("codigo") or ""))
            if p is None:
                raise ErroNegocio("Produto do pedido não encontrado. Recuse e confira com o cliente.")
            try:
                qtd = fmt.validar_qtd(i.get("qtd"))
            except (ValueError, TypeError):
                raise ErroNegocio("Quantidade inválida no pedido.") from None
            item_ids.append(ctrl.caixa.adicionar_item(venda_id, p["id"], qtd,
                                     observacao=(pedido.get("observacao") or "")[:200],
                                     temperatura=i.get("temperatura") or "natural",
                                     opcoes_ids=i.get("opcoes_ids") or []))
        b.executar("INSERT INTO pedidos_mesa_importados(pedido_id, venda_id, criado_em) VALUES (?,?,?)",
                   (pedido_id, venda_id, fmt.agora()))
        b.log("pedido_mesa_aceito", f"Pedido {pedido_id}: mesa {mesa}, venda {venda_id}", ctrl.operador_id)
        return {"venda_id": venda_id, "faltando": [], "ja_existia": False, "item_ids": item_ids}
