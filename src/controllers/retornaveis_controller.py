"""Posse de produtos por cliente, independente de venda, estoque ou dinheiro."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
import math

from src.controllers.acesso_controller import AcessoController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao


AVISO = (
    "Controle de posse por cliente, para qualquer produto (não só cascos). "
    "Empréstimos e devoluções não são vendas, não movimentam estoque nem financeiro "
    "e não geram caução ou cobrança. Trocas/cascos históricos não geram saldo."
)
TIPOS = {"emprestimo": "Empréstimo / saída", "devolucao": "Devolução / retorno"}


class RetornaveisController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id

    def exigir_acesso(self) -> None:
        """Consulta o cadastro e a permissão atuais, nunca o nível em cache."""
        if type(self.operador_id) is not int:
            raise ErroPermissao("Entre com um operador para acessar os retornáveis.")
        operador = self.banco.um(
            "SELECT id FROM operadores WHERE id = ? AND ativo = 1", (self.operador_id,))
        if operador is None:
            raise ErroPermissao("Operador inexistente ou inativo. Encerre a sessão.")
        acesso = AcessoController(self.banco)
        acesso.exigir(acesso.operador(self.operador_id), "lanc_estoque")

    @staticmethod
    def _quantidade(valor) -> Decimal:
        try:
            if isinstance(valor, bool):
                raise ValueError
            quantidade = Decimal(str(valor).strip().replace(",", "."))
            if not quantidade.is_finite() or quantidade <= 0:
                raise ValueError
            numero = float(quantidade)
            if not math.isfinite(numero) or Decimal(str(numero)) != quantidade:
                raise ValueError
            with localcontext() as contexto:
                contexto.prec = 400
                if quantidade != quantidade.quantize(Decimal("0.0001")):
                    raise ValueError
            return quantidade
        except (InvalidOperation, ValueError, OverflowError):
            raise ErroNegocio(
                "Informe uma quantidade positiva e finita, com até 4 casas decimais.") from None

    def _saldo(self, cliente_id: int, produto_id: int) -> float:
        return self.banco.valor(
            "SELECT saldo_apos FROM retornaveis_movimentos "
            "WHERE cliente_id = ? AND produto_id = ? ORDER BY id DESC LIMIT 1",
            (cliente_id, produto_id), 0.0)

    def saldo(self, cliente_id: int, produto_id: int) -> float:
        self.exigir_acesso()
        return self._saldo(cliente_id, produto_id)

    def saldos(self, cliente_id: int) -> list[dict]:
        self.exigir_acesso()
        return [dict(linha) for linha in self.banco.todos(
            "SELECT m.produto_id, p.codigo, p.nome AS produto, m.saldo_apos AS saldo "
            "FROM retornaveis_movimentos m JOIN produtos_historico p ON p.id = m.produto_id "
            "WHERE m.cliente_id = ? AND m.id = ("
            "SELECT MAX(ultimo.id) FROM retornaveis_movimentos ultimo "
            "WHERE ultimo.cliente_id = m.cliente_id AND ultimo.produto_id = m.produto_id) "
            "ORDER BY p.nome", (cliente_id,))]

    def historico(self, cliente_id: int, produto_id: int | None = None) -> list[dict]:
        self.exigir_acesso()
        filtro = " AND m.produto_id = ?" if produto_id is not None else ""
        parametros = (cliente_id, produto_id) if produto_id is not None else (cliente_id,)
        return [dict(linha) for linha in self.banco.todos(
            "SELECT m.*, p.nome AS produto, p.codigo, o.nome AS operador "
            "FROM retornaveis_movimentos m JOIN produtos_historico p ON p.id = m.produto_id "
            "JOIN operadores o ON o.id = m.operador_id "
            f"WHERE m.cliente_id = ?{filtro} ORDER BY m.id DESC", parametros)]

    def registrar(self, cliente_id: int, produto_id: int, tipo: str,
                  quantidade, motivo: str) -> int:
        """Registra um movimento imutável e retorna seu id; saldo e auditoria são atômicos."""
        with self.banco.transacao():
            self.exigir_acesso()
            if not isinstance(tipo, str) or tipo not in TIPOS:
                raise ErroNegocio("Escolha empréstimo ou devolução.")
            qtd = self._quantidade(quantidade)
            if not isinstance(motivo, str) or not motivo.strip():
                raise ErroNegocio("Informe o motivo do empréstimo ou da devolução.")
            if type(cliente_id) is not int or not self.banco.valor(
                    "SELECT 1 FROM clientes WHERE id = ? AND ativo = 1", (cliente_id,)):
                raise ErroNegocio("Selecione um cliente existente e ativo.")
            if type(produto_id) is not int or not self.banco.valor(
                    "SELECT 1 FROM produtos WHERE id = ? AND ativo = 1", (produto_id,)):
                raise ErroNegocio("Selecione um produto existente e ativo.")
            with localcontext() as contexto:
                contexto.prec = 400
                anterior = Decimal(str(self._saldo(cliente_id, produto_id)))
                novo = anterior + qtd if tipo == "emprestimo" else anterior - qtd
            if novo < 0:
                raise ErroNegocio(
                    "Devolução maior que o saldo em posse deste cliente para o produto.")
            saldo = float(novo)
            if not math.isfinite(saldo) or Decimal(str(saldo)) != novo:
                raise ErroNegocio("Saldo excede a precisão suportada. Confira a quantidade.")
            return self.banco.inserir("retornaveis_movimentos", {
                "cliente_id": cliente_id, "produto_id": produto_id, "tipo": tipo,
                "quantidade": float(qtd), "saldo_apos": saldo, "motivo": motivo.strip(),
                "operador_id": self.operador_id, "criado_em": fmt.agora(),
            })
