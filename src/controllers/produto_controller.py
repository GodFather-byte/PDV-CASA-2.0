"""Regras de produtos usadas no caixa e nos relatórios: busca por código/código de
barras/atalho/nome, preço vigente (promoções por período, dia da semana e horário),
situação de estoque e composição (ficha técnica)."""
from __future__ import annotations

from datetime import datetime

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados


def _entre_horas(hora: str, ini: str, fim: str) -> bool:
    if ini <= fim:
        return ini <= hora <= fim
    return hora >= ini or hora <= fim   # vira a meia-noite (ex.: 22:00 às 04:00)


def _entre_dias(dia: int, ini: int, fim: int) -> bool:
    if ini <= fim:
        return ini <= dia <= fim
    return dia >= ini or dia <= fim     # ex.: sexta a segunda


class ProdutoController:
    def __init__(self, banco: BancoDados | None = None):
        self.banco = banco or BancoDados()

    # --------------------------------------------------------------- busca
    def por_id(self, produto_id: int) -> dict | None:
        r = self.banco.um("SELECT * FROM produtos WHERE id = ?", (produto_id,))
        return dict(r) if r else None

    def buscar_codigo(self, texto: str, apenas_venda: bool = True) -> dict | None:
        """Resolve o que o operador digitou/bipou: código (com ou sem zeros), código de
        barras ou atalho. Retorna None se não achar (a tela então pesquisa por nome)."""
        t = (texto or "").strip()
        if not t:
            return None
        filtro = " AND ativo = 1 AND venda = 1" if apenas_venda else ""
        if t.isdigit():
            for coluna, valor in (("codigo", t.zfill(13)), ("cbarra", t)):
                r = self.banco.um(f"SELECT * FROM produtos WHERE {coluna} = ?{filtro}", (valor,))
                if r:
                    return dict(r)
        r = self.banco.um(f"SELECT * FROM produtos WHERE atalho = ? COLLATE NOCASE{filtro}", (t,))
        return dict(r) if r else None

    def pesquisar(self, texto: str, limite: int = 60, apenas_venda: bool = True) -> list[dict]:
        t = (texto or "").strip().replace("%", "").replace("_", "")
        filtro = "AND ativo = 1 AND venda = 1" if apenas_venda else ""
        linhas = self.banco.todos(
            f"""SELECT * FROM produtos WHERE norm(nome) LIKE norm(?) {filtro}
                ORDER BY (norm(nome) LIKE norm(?)) DESC, nome LIMIT ?""", (f"%{t}%", f"{t}%", limite))
        return [dict(r) for r in linhas]

    def listar_venda(self) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            "SELECT * FROM produtos WHERE ativo = 1 AND venda = 1 ORDER BY nome")]

    # --------------------------------------------------------------- preços
    def preco_vigente(self, produto: dict, quando: datetime | None = None) -> int:
        """Preço de venda em centavos considerando promoções ativas.

        Se mais de uma promoção estiver ativa vale a de menor preço."""
        q = quando or fmt.agora_dt()
        dia_iso, hora = q.strftime("%Y-%m-%d"), q.strftime("%H:%M")
        promos = []
        if (produto.get("promo_preco_cent") or 0) > 0 and produto.get("promo_de") and produto.get("promo_ate"):
            if produto["promo_de"] <= dia_iso <= produto["promo_ate"]:
                promos.append(produto["promo_preco_cent"])
        if (produto.get("sem_preco_cent") or 0) > 0 and produto.get("sem_inicial") and produto.get("sem_final"):
            if _entre_dias(fmt.dia_semana(dia_iso), produto["sem_inicial"], produto["sem_final"]):
                promos.append(produto["sem_preco_cent"])
        if (produto.get("hora_preco_cent") or 0) > 0 and produto.get("hora_ini") and produto.get("hora_fim"):
            if _entre_horas(hora, produto["hora_ini"], produto["hora_fim"]):
                promos.append(produto["hora_preco_cent"])
        return min(promos) if promos else produto["preco_cent"]

    def preco_partes(self, base: dict, partes: list[dict], quando: datetime | None = None) -> int:
        """Preço de um item dividido/combo. Composto: preço único do produto-base.
        Senão: o maior preço entre as partes (opção 'Maior') ou a média proporcional."""
        if base.get("composto"):
            return self.preco_vigente(base, quando)
        precos = [self.preco_vigente(p, quando) for p in partes]
        if base.get("maior"):
            return max(precos)
        return fmt.arredondar(sum(fmt._dec(p) for p in precos) / len(precos))

    # -------------------------------------------------------------- estoque
    @staticmethod
    def situacao_estoque(produto: dict) -> str:
        """'sem' (zerado/negativo, vermelho), 'ponto' (entre zero e o mínimo, amarelo)
        ou 'normal' (acima do mínimo, verde)."""
        qt, minimo = produto["qt_atual"], produto["estoque_minimo"]
        if qt <= 0:
            return "sem"
        if qt <= minimo:
            return "ponto"
        return "normal"

    # ----------------------------------------------------------- composição
    def composicao(self, produto_id: int) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            """SELECT c.id, c.insumo_id, c.quantidade, p.codigo, p.nome, p.ult_preco_cent, u.abreviatura AS unidade
               FROM composicoes c JOIN produtos p ON p.id = c.insumo_id
               JOIN unidades u ON u.id = p.unidade_id
               WHERE c.produto_id = ? ORDER BY p.nome""", (produto_id,))]

    def incluir_composicao(self, produto_id: int, insumo_id: int, quantidade: float) -> int:
        if quantidade <= 0:
            raise ErroNegocio("A quantidade da composição deve ser maior que zero.")
        if produto_id == insumo_id:
            raise ErroNegocio("Um produto não pode compor a si mesmo.")
        insumo = self.por_id(insumo_id)
        if insumo is None:
            raise ErroNegocio("Produto de composição não encontrado.")
        if not insumo["controla_estoque"] and not self.composicao(insumo_id):
            raise ErroNegocio(f"'{insumo['nome']}' não está habilitado no estoque. "
                              "Marque 'Controla estoque' no cadastro do produto antes de usá-lo na composição.")
        if self._alcanca(insumo_id, produto_id):
            raise ErroNegocio("Composição circular: o insumo já depende deste produto.")
        if self.banco.um("SELECT 1 FROM composicoes WHERE produto_id = ? AND insumo_id = ?", (produto_id, insumo_id)):
            raise ErroNegocio("Este insumo já faz parte da composição. Exclua-o e inclua com a nova quantidade.")
        return self.banco.inserir("composicoes", {
            "produto_id": produto_id, "insumo_id": insumo_id, "quantidade": fmt.arred_qtd(quantidade)})

    def excluir_composicao(self, composicao_id: int) -> None:
        self.banco.executar("DELETE FROM composicoes WHERE id = ?", (composicao_id,))

    def _alcanca(self, origem: int, alvo: int, visitados: set | None = None) -> bool:
        visitados = visitados if visitados is not None else set()
        if origem == alvo:
            return True
        if origem in visitados:
            return False
        visitados.add(origem)
        return any(self._alcanca(r[0], alvo, visitados) for r in self.banco.todos(
            "SELECT insumo_id FROM composicoes WHERE produto_id = ?", (origem,)))

    def consumos(self, produto_id: int, quantidade: float, _pilha: tuple = ()) -> list[tuple[int, float]]:
        """O que sai do estoque ao vender `quantidade` do produto: ele mesmo (se controla
        estoque) mais, recursivamente, cada insumo da composição."""
        if produto_id in _pilha:
            raise ErroNegocio("Composição circular detectada no estoque.")
        p = self.por_id(produto_id)
        saida = []
        if p["controla_estoque"]:
            saida.append((produto_id, fmt.arred_qtd(quantidade)))
        for c in self.banco.todos("SELECT insumo_id, quantidade FROM composicoes WHERE produto_id = ?", (produto_id,)):
            saida += self.consumos(c["insumo_id"], quantidade * c["quantidade"], _pilha + (produto_id,))
        return saida

    def custo(self, produto_id: int) -> int:
        """Custo em centavos: soma dos insumos (último preço de compra x quantidade);
        sem composição, o último preço de compra do próprio produto."""
        comps = self.banco.todos("SELECT insumo_id, quantidade FROM composicoes WHERE produto_id = ?", (produto_id,))
        if not comps:
            atual = self.por_id(produto_id)
            return atual["ult_preco_cent"] if atual else self.banco.valor(
                "SELECT custo_cent FROM produtos_historico WHERE id = ?", (produto_id,), 0)
        return sum(fmt.mult_cent(self.custo(c["insumo_id"]), c["quantidade"]) for c in comps)
