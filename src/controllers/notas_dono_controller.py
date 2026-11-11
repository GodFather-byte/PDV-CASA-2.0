"""Notas de compra enviadas pelo dono (painel) que chegaram a este caixa e esperam conferência.

A nota só entra no estoque quando o operador confere os itens na tela de importação de NF-e e confirma. Aqui ficam
a fila local, a prévia e o desfecho (lançada ou recusada), que a sincronização devolve para o painel.
"""
from __future__ import annotations

from src.controllers.importacao_produtos import ImportacaoNFe, PreviaNFe
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

CAMPOS = "id, chave, numero, emitente, arquivo, enviada_em, recebida_em, situacao, situacao_em, detalhe"


class NotasDonoController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id

    # ------------------------------------------------------------- consulta
    def pendentes(self) -> list[dict]:
        """As notas esperando conferência, a mais antiga primeiro. Nota já lançada por outro caminho sai da fila."""
        self.conciliar()
        return [dict(r) for r in self.banco.todos(
            f"SELECT {CAMPOS} FROM notas_dono WHERE situacao = 'pendente' ORDER BY id")]

    def quantidade(self) -> int:
        return self.banco.valor("SELECT COUNT(*) FROM notas_dono WHERE situacao = 'pendente'", (), 0) or 0

    def recentes(self, limite: int = 30) -> list[dict]:
        return [dict(r) for r in self.banco.todos(
            f"SELECT {CAMPOS} FROM notas_dono WHERE situacao <> 'pendente' ORDER BY situacao_em DESC LIMIT ?",
            (int(limite),))]

    def _nota(self, nota_id: int):
        nota = self.banco.um(f"SELECT {CAMPOS}, xml FROM notas_dono WHERE id = ?", (int(nota_id),))
        if nota is None:
            raise ErroNegocio("Nota não encontrada. Atualize a lista.")
        return nota

    def previa(self, nota_id: int) -> PreviaNFe:
        """A mesma prévia do XML escolhido no computador: itens, vínculos com o cadastro e custos."""
        nota = self._nota(nota_id)
        if nota["situacao"] != "pendente" or not nota["xml"]:
            raise ErroNegocio("Esta nota já foi conferida.")
        return ImportacaoNFe(self.banco, self.operador_id).analisar_bytes(bytes(nota["xml"]), nota["arquivo"])

    # ------------------------------------------------------------- desfecho
    def conciliar(self) -> int:
        """Marca como lançada a nota cuja chave já está nas importações (conferida aqui ou importada pelo arquivo)."""
        linhas = self.banco.todos(
            "SELECT n.id FROM notas_dono n JOIN importacoes_nfe i ON i.chave = n.chave WHERE n.situacao = 'pendente'")
        for linha in linhas:
            self._encerrar(linha["id"], "lancada", "Entrada registrada no estoque.")
        return len(linhas)

    def marcar_lancada(self, nota_id: int) -> None:
        nota = self._nota(nota_id)
        if nota["situacao"] == "pendente":
            self._encerrar(nota_id, "lancada", "Entrada registrada no estoque.")

    def recusar(self, nota_id: int, motivo: str) -> None:
        motivo = (motivo or "").strip()
        if len(motivo) < 3:
            raise ErroNegocio("Informe o motivo da recusa: ele aparece para o dono no painel.")
        nota = self._nota(nota_id)
        if nota["situacao"] != "pendente":
            raise ErroNegocio("Esta nota já foi conferida.")
        self._encerrar(nota_id, "recusada", motivo[:200])
        self.banco.log("nota_dono_recusada", f"NF-e {nota['numero']} • {nota['emitente']}: {motivo[:120]}", self.operador_id)

    def _encerrar(self, nota_id: int, situacao: str, detalhe: str) -> None:
        # O XML sai do banco: a entrada (ou a recusa) já está registrada e a cópia não é mais necessária.
        self.banco.executar(
            "UPDATE notas_dono SET situacao = ?, situacao_em = ?, detalhe = ?, xml = NULL, aviso_ok = 0 WHERE id = ?",
            (situacao, fmt.agora(), detalhe, int(nota_id)))
