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


def _digitos(valor) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def _mesmo_telefone(a: str, b: str) -> bool:
    """O número inteiro, com ou sem o 55 do Brasil. Os 8 últimos dígitos sozinhos não bastam."""
    if not a or not b:
        return False
    if a == b:
        return True
    if a.startswith("55") and a[2:] == b and len(b) >= 10:
        return True
    if b.startswith("55") and b[2:] == a and len(a) >= 10:
        return True
    return False


def _qtd(item: dict) -> float:
    try:
        return fmt.validar_qtd(item.get("qtd"))
    except (TypeError, ValueError):
        return 0.0


def _texto_qtd(qtd: float) -> str:
    if abs(qtd - round(qtd)) < 1e-9:
        return str(int(round(qtd)))
    return fmt.fmt_qtd(qtd)


def resumo(pedido: dict) -> str:
    """Uma linha para a lista do caixa: '#12 · João · Centro · 3 itens · R$ 87,50'."""
    onde = "Retira na loja" if pedido.get("retirada") else (pedido.get("bairro") or "Sem bairro")
    itens = sum(_qtd(i) for i in pedido.get("itens") or [])
    texto_itens = _texto_qtd(itens)
    return (f"#{pedido.get('numero')} · {pedido.get('nome', '')} · {onde} · {texto_itens} "
            f"ite{'ns' if itens != 1 else 'm'} · {fmt.fmt_brl(int(pedido.get('total_cent') or 0))}")


def detalhe(pedido: dict) -> str:
    linhas = [resumo(pedido), ""]
    for i in pedido.get("itens") or []:
        temp = " gelada" if i.get("temperatura") == "gelada" else ""
        linhas.append(f"{_texto_qtd(_qtd(i))}x {i.get('nome')}{temp}")
    linhas.append("")
    if pedido.get("aviso"):
        linhas.append(pedido["aviso"])
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
        """O número inteiro: '#1' não pode casar com '#10' nem com '#11'."""
        texto = marca(numero)
        r = self.banco.um(
            "SELECT id FROM vendas WHERE modalidade = 'entrega' AND status <> 'cancelada' "
            "AND (mensagem = ? OR mensagem LIKE ?) ORDER BY id DESC LIMIT 1",
            (texto, texto + " ·%"))
        return r["id"] if r else None

    def _cliente(self, pedido: dict) -> int:
        """O cliente pelo telefone inteiro (com ou sem o 55); sem cadastro, cria um com o endereço do pedido."""
        telefone = _digitos(pedido.get("telefone"))
        if not telefone:
            raise ErroNegocio("Pedido sem telefone.")
        bairro = None
        if pedido.get("bairro"):
            b = self.banco.um("SELECT id FROM bairros WHERE nome = ? COLLATE NOCASE", (pedido["bairro"],))
            bairro = b["id"] if b else None
        for r in self.banco.todos("SELECT id, telefone, ativo FROM clientes WHERE telefone IS NOT NULL AND telefone <> ''"):
            if r["ativo"] and _mesmo_telefone(_digitos(r["telefone"]), telefone):
                if not pedido.get("retirada") and pedido.get("endereco"):
                    self.banco.atualizar("clientes", r["id"], {"endereco": str(pedido["endereco"])[:160],
                                                              **({"bairro_id": bairro} if bairro else {})})
                return r["id"]
        from src.controllers.cadastro_controller import CadastroController
        cadastro = CadastroController(self.banco)
        return cadastro.salvar("clientes", {
            "numero_consulta": cadastro.proximo_numero_cliente(), "nome": (pedido.get("nome") or "Cliente online")[:60],
            "telefone": telefone[:20], "endereco": (pedido.get("endereco") or "")[:160], "bairro_id": bairro, "ativo": 1})

    def importar(self, pedido: dict) -> dict:
        """Cria a entrega do pedido. Devolve venda_id e se já existia. Item fora de venda não entra: o pedido não é aceito."""
        if not self.banco.cfg_bool("pedido_online", False):
            raise ErroNegocio("O pedido online está desligado (Configurações > Módulos).")
        existente = self.ja_importado(pedido.get("numero"))
        if existente:
            return {"venda_id": existente, "faltando": [], "ja_existia": True}
        faltando, linhas = [], []
        for item in pedido.get("itens") or []:
            p = self.produtos.buscar_codigo(str(item.get("codigo") or ""))
            qtd = _qtd(item)
            temp = item.get("temperatura") if item.get("temperatura") in ("natural", "gelada") else "natural"
            cascos = item.get("cascos") or 0
            if isinstance(cascos, bool) or not isinstance(cascos, int) or cascos < 0:
                cascos = 0
            if p is None or not p["ativo"] or qtd <= 0:
                faltando.append(f"{_texto_qtd(qtd)}x {item.get('nome')}")
            elif temp == "gelada" and not p["preco_gelada_cent"]:
                faltando.append(f"{_texto_qtd(qtd)}x {item.get('nome')} (sem preço gelado)")
            elif cascos and not p["casco_produto_id"]:
                faltando.append(f"{item.get('nome')} não trabalha com casco")
            else:
                linhas.append((p["id"], qtd, temp, cascos))
        if faltando or not linhas:
            lista = ", ".join(faltando) or "nenhum produto"
            raise ErroNegocio(f"Não aceito: {lista}. Recuse o pedido e avise o cliente.")
        pagamento = PAGAMENTOS.get(pedido.get("pagamento"), "")
        recado = " · ".join(x for x in (
            marca(pedido.get("numero")), "RETIRA NA LOJA" if pedido.get("retirada") else "", pagamento,
            pedido.get("aviso") or "", pedido.get("observacao") or "") if x)
        forma = pedido.get("pagamento") if pedido.get("pagamento") in PAGAMENTOS else ""
        with self.banco.transacao():
            venda_id = self.entregas.abrir(self._cliente(pedido))
            if pedido.get("retirada"):
                self.banco.atualizar("vendas", venda_id, {"taxa_cent": 0})
            for produto_id, qtd, temp, cascos in linhas:
                self.caixa.adicionar_item(venda_id, produto_id, qtd, temperatura=temp, quantidade_cascos=cascos)
            troco = int(pedido.get("troco_para_cent") or 0) if pedido.get("pagamento") == "dinheiro" else 0
            aviso = {"pedido_online_aviso": "aceito", "pedido_online_aviso_ok": 0} if pedido.get("id") else {}
            self.banco.atualizar("vendas", venda_id, {
                "mensagem": recado[:200], "forma_online": forma or None,
                **({"troco_para_cent": troco} if troco else {}),
                **({"pedido_online_id": int(pedido["id"])} if pedido.get("id") else {}),
                **aviso})
            self.caixa.estoque.reservar_venda(venda_id)
        self.banco.log("pedido_online_aceito", f"{marca(pedido.get('numero'))}: venda {venda_id}", self.operador_id)
        return {"venda_id": venda_id, "faltando": [], "ja_existia": False}
