"""Custo congelado ao fechar a venda e rateio exato dos ajustes analíticos de devolução."""
from src.core import formatacao as fmt


def registrar(banco, venda_id: int, produtos, estoque) -> None:
    """Participa da transação do CaixaController. Cadastros futuros não alteram o custo deste cupom."""
    for item in banco.todos("SELECT id, produto_id, quantidade FROM itens_venda WHERE venda_id = ? AND cancelado = 0",
                            (venda_id,)):
        partes = banco.todos("SELECT produto_id, fracao FROM itens_venda_partes WHERE item_id = ?", (item["id"],))
        alvos = estoque._dividir_em_partes(item["quantidade"], partes) or [(item["produto_id"], item["quantidade"])]
        custo = sum(fmt.mult_cent(produtos.custo(pid), qtd) for pid, qtd in alvos)
        recuperavel = any(produtos.consumos(pid, qtd) for pid, qtd in alvos)
        banco.executar("INSERT OR IGNORE INTO itens_venda_custos(item_id, custo_cent, recuperavel, registrado_em) VALUES (?,?,?,?)",
                       (item["id"], custo, int(recuperavel), fmt.agora()))


def parcela(total_cent: int, anterior: float, quantidade: float, vendida: float) -> int:
    """Diferença acumulada: devoluções fracionadas somam exatamente o total original, sem perder centavos."""
    def acumulado(qtd):
        return fmt.arredondar(fmt._dec(total_cent) * fmt._dec(qtd) / fmt._dec(vendida))
    return acumulado(fmt.arred_qtd(anterior + quantidade)) - acumulado(anterior)
