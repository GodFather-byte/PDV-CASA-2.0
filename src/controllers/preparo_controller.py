"""Status de preparo por item, para o módulo de operação Cozinha/Bar (usar_cozinha_bar).

Só olha itens de subgrupo marcado com `impressora_remota = 1` (o mesmo flag que já decide
o que vai para o ticket da cozinha/bar em ImpressaoController.pedido_remoto) — é o painel
que acompanha esses itens até a entrega, sem duplicar aquele critério.
"""
from __future__ import annotations

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.core.posicao import nome as nome_posicao

STATUS_PREPARO = ("pendente", "em_preparo", "entregue")
_PROXIMO = {"pendente": "em_preparo", "em_preparo": "entregue"}


def _rotulo_posicao(venda: dict) -> str:
    if venda["modalidade"] == "balcao":
        return "Balcão"
    base = nome_posicao(bool(venda["comanda"]), venda["posicao"])
    apelido = (venda.get("apelido") or "").strip()
    return f"{base} ({apelido})" if apelido else base


class PreparoController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id

    def fila(self, setor_id: int | None = None, status: tuple = ("pendente", "em_preparo")) -> list[dict]:
        """Itens não cancelados de subgrupo remoto, mais antigos primeiro. `setor_id` filtra pelo setor do
        subgrupo (subgrupos.setor_impressao_id); sem setor cadastrado no subgrupo, não aparece nesse filtro."""
        sql = """SELECT i.id, i.quantidade, i.observacao, i.status_preparo, i.criado_em,
                        pr.nome AS produto, s.nome AS subgrupo, v.modalidade, v.comanda, v.posicao, v.apelido
                 FROM itens_venda i
                 JOIN produtos_historico pr ON pr.id = i.produto_id
                 JOIN subgrupos s ON s.id = pr.subgrupo_id
                 JOIN vendas v ON v.id = i.venda_id
                 WHERE i.cancelado = 0 AND s.impressora_remota = 1
                   AND i.status_preparo IN ({})""".format(",".join("?" * len(status)))
        params: list = list(status)
        if setor_id is not None:
            sql += " AND s.setor_impressao_id = ?"
            params.append(setor_id)
        linhas = [dict(r) for r in self.banco.todos(sql + " ORDER BY i.criado_em, i.id", params)]
        for r in linhas:
            r["posicao_rotulo"] = _rotulo_posicao(r)
            r["minutos"] = fmt.minutos_entre(r["criado_em"])
        return linhas

    def marcar(self, item_id: int, status: str) -> None:
        if status not in STATUS_PREPARO:
            raise ErroNegocio(f"Situação de preparo inválida: {status}")
        n = self.banco.executar(
            "UPDATE itens_venda SET status_preparo = ?, preparo_atualizado_em = ?, preparo_operador_id = ? "
            "WHERE id = ? AND cancelado = 0",
            (status, fmt.agora(), self.operador_id, item_id)).rowcount
        if not n:
            raise ErroNegocio("Item não encontrado ou cancelado.")

    def avancar(self, item_id: int) -> str:
        """pendente -> em_preparo -> entregue; devolve a nova situação."""
        atual = self.banco.valor("SELECT status_preparo FROM itens_venda WHERE id = ? AND cancelado = 0", (item_id,))
        if atual is None:
            raise ErroNegocio("Item não encontrado ou cancelado.")
        novo = _PROXIMO.get(atual, "entregue")
        self.marcar(item_id, novo)
        return novo
