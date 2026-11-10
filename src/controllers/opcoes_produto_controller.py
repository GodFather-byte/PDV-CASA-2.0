"""Cadastro de opções comerciais por produto e retrato das escolhas no lançamento."""
import json
from src.core import opcoes_produto
from src.core.erros import ErroNegocio


class OpcoesProdutoController:
    def __init__(self, banco):
        self.banco = banco

    def grupos(self, produto_id):
        bruto = self.banco.valor("SELECT grupos_json FROM produto_opcoes WHERE produto_id = ?", (produto_id,), "[]")
        try:
            return opcoes_produto.catalogo(json.loads(bruto))
        except (ValueError, KeyError, TypeError) as exc:
            raise ErroNegocio("Cadastro de adicionais inválido; confira o produto.") from exc

    def salvar(self, produto_id, grupos):
        if not self.banco.um("SELECT id FROM produtos WHERE id = ?", (produto_id,)):
            raise ErroNegocio("Produto não encontrado.")
        try:
            limpos = opcoes_produto.catalogo(grupos)
        except (ValueError, KeyError, TypeError) as exc:
            raise ErroNegocio(str(exc)) from None
        with self.banco.transacao():
            self.banco.executar(
                "INSERT INTO produto_opcoes(produto_id, grupos_json) VALUES (?, ?) "
                "ON CONFLICT(produto_id) DO UPDATE SET grupos_json = excluded.grupos_json",
                (produto_id, json.dumps(limpos, ensure_ascii=False)))

    def selecionar(self, produto_id, ids=None):
        try:
            return opcoes_produto.selecionar(self.grupos(produto_id), ids)
        except (ValueError, KeyError, TypeError) as exc:
            raise ErroNegocio(str(exc)) from None

    def conferir_pedido(self, produto_id, item):
        ids = item.get("opcoes_ids") or []
        atuais = self.selecionar(produto_id, ids)
        esperadas = item.get("opcoes")
        if esperadas is not None:
            if not isinstance(esperadas, list) or any(not isinstance(o, dict) for o in esperadas):
                raise ErroNegocio("Escolhas do pedido inválidas.")
            resumo = lambda opcoes: sorted(((o.get("id"), o.get("grupo"), o.get("nome")) for o in opcoes),
                                          key=lambda o: str(o[0]))
            if resumo(atuais) != resumo(esperadas):
                raise ErroNegocio("As opções do produto mudaram desde o pedido. Confira com o cliente antes de aceitar.")
        return ids
