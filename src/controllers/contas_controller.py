"""Lançamento de contas a pagar/receber (manual ADM 5.1 e versão web 'Contas')."""
from __future__ import annotations

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

SQL_BASE = """SELECT c.*, sp.nome AS subplano, pl.id AS plano_id, pl.nome AS plano, pl.debito, pl.resultado,
                     t.tipo AS tipo_financeiro, f.nome AS fornecedor
              FROM contas c JOIN subplanos sp ON sp.id = c.subplano_id
              JOIN planos_contas pl ON pl.id = sp.plano_id
              JOIN tipos_pagamento t ON t.id = c.tipo_pagamento_id
              LEFT JOIN fornecedores f ON f.id = c.fornecedor_id"""


def _data(texto: str | None) -> str | None:
    """Data digitada inválida vira aviso ao operador, não 'erro inesperado'."""
    try:
        return fmt.para_data_iso(texto)
    except ValueError as e:
        raise ErroNegocio(f"Data inválida: {texto} (use dd/mm/aaaa).") from e


class ContasController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id

    def incluir(self, subplano_id: int, descricao: str, tipo_pagamento_id: int, valor_cent: int,
                dt_vencimento: str | None = None, dt_entrada: str | None = None, dt_quitacao: str | None = None,
                documento: str | None = None, mercadoria: bool = False, nota: str | None = None,
                previsao: bool = False, fornecedor_id: int | None = None, meses: int = 1,
                lancamento_estoque_id: int | None = None, parcelas_cent: list[int] | None = None) -> list[int]:
        """Cria a conta. `meses` > 1 repete o lançamento mensalmente (conta mensal: o mesmo valor todo mês);
        com `parcelas_cent` (um valor por mês) cada mês recebe o seu valor, para dividir um total."""
        if not (descricao or "").strip():
            raise ErroNegocio("Informe a descrição da conta.")
        if valor_cent <= 0:
            raise ErroNegocio("Informe um valor maior que zero.")
        if not 1 <= meses <= 120:
            raise ErroNegocio("O número de meses deve ficar entre 1 e 120.")
        if parcelas_cent is not None and (len(parcelas_cent) != meses or min(parcelas_cent) <= 0):
            raise ErroNegocio(f"Valor pequeno demais para dividir em {meses} parcelas.")
        entrada = _data(dt_entrada) or fmt.hoje()
        venc = _data(dt_vencimento) or entrada
        quit_ = _data(dt_quitacao)
        if quit_ and quit_ < entrada:
            raise ErroNegocio("A quitação não pode ser anterior à data de entrada.")
        ids = []
        with self.banco.transacao():
            for i in range(meses):
                ids.append(self.banco.inserir("contas", {
                    "subplano_id": subplano_id, "descricao": descricao.strip(),
                    "tipo_pagamento_id": tipo_pagamento_id, "valor_cent": parcelas_cent[i] if parcelas_cent else valor_cent,
                    "documento": documento, "mercadoria": int(bool(mercadoria)), "nota": nota,
                    "previsao": int(bool(previsao)), "dt_entrada": entrada,
                    "dt_vencimento": fmt.somar_meses(venc, i),
                    "dt_quitacao": quit_ if i == 0 else None, "fornecedor_id": fornecedor_id,
                    "lancamento_estoque_id": lancamento_estoque_id,
                    "parcela": f"{i + 1}/{meses}" if meses > 1 else None,
                    "operador_id": self.operador_id, "criado_em": fmt.agora()}))
        return ids

    def obter(self, conta_id: int) -> dict:
        r = self.banco.um(SQL_BASE + " WHERE c.id = ?", (conta_id,))
        if r is None:
            raise ErroNegocio("Conta não encontrada.")
        return dict(r)

    def atualizar(self, conta_id: int, **campos) -> None:
        permitidos = {"subplano_id", "descricao", "tipo_pagamento_id", "valor_cent", "documento", "mercadoria",
                      "nota", "previsao", "dt_entrada", "dt_vencimento", "dt_quitacao", "fornecedor_id"}
        dados = {k: v for k, v in campos.items() if k in permitidos}
        if "valor_cent" in dados and dados["valor_cent"] <= 0:
            raise ErroNegocio("Informe um valor maior que zero.")
        for k in ("dt_entrada", "dt_vencimento", "dt_quitacao"):
            if k in dados:
                dados[k] = _data(dados[k])
        self.obter(conta_id)
        self.banco.atualizar("contas", conta_id, dados)

    def quitar(self, conta_id: int, data: str | None = None) -> None:
        c = self.obter(conta_id)
        quando = _data(data) or fmt.hoje()
        if quando < c["dt_entrada"]:
            raise ErroNegocio("A quitação não pode ser anterior à data de entrada.")
        self.banco.executar("UPDATE contas SET dt_quitacao = ?, previsao = 0 WHERE id = ?", (quando, conta_id))

    def desfazer_quitacao(self, conta_id: int) -> None:
        self.banco.executar("UPDATE contas SET dt_quitacao = NULL WHERE id = ?", (conta_id,))

    def excluir(self, conta_id: int) -> None:
        self.obter(conta_id)
        self.banco.executar("DELETE FROM contas WHERE id = ?", (conta_id,))

    def listar(self, de: str | None = None, ate: str | None = None, por: str = "dt_vencimento",
               plano_id: int | None = None, subplano_id: int | None = None, tipo_pagamento_id: int | None = None,
               quitada: bool | None = None, previsao: bool | None = None, texto: str | None = None) -> list[dict]:
        if por not in ("dt_vencimento", "dt_entrada", "dt_quitacao"):
            raise ErroNegocio("Critério de data inválido.")
        onde, params = [], []
        if de:
            onde.append(f"c.{por} >= ?"); params.append(de)
        if ate:
            onde.append(f"c.{por} <= ?"); params.append(ate)
        for coluna, valor in (("pl.id", plano_id), ("sp.id", subplano_id), ("c.tipo_pagamento_id", tipo_pagamento_id)):
            if valor:
                onde.append(f"{coluna} = ?"); params.append(valor)
        if quitada is not None:
            onde.append("c.dt_quitacao IS NOT NULL" if quitada else "c.dt_quitacao IS NULL")
        if previsao is not None:
            onde.append("c.previsao = ?"); params.append(int(previsao))
        if texto:
            onde.append("(norm(c.descricao) LIKE norm(?) OR norm(c.documento) LIKE norm(?) OR norm(c.nota) LIKE norm(?))")
            params += [f"%{texto}%"] * 3
        sql = SQL_BASE + (" WHERE " + " AND ".join(onde) if onde else "")
        return [dict(r) for r in self.banco.todos(sql + f" ORDER BY c.{por}, c.id", params)]

    def transferir(self, origem_id: int, destino_id: int, valor_cent: int, data: str | None = None,
                   descricao: str = "Transferência entre contas") -> tuple[int, int]:
        """Move valor de uma conta (tipo financeiro) para outra: um débito e um crédito quitados."""
        if origem_id == destino_id:
            raise ErroNegocio("Origem e destino da transferência são iguais.")
        sub_deb = self.banco.valor("SELECT sp.id FROM subplanos sp JOIN planos_contas p ON p.id = sp.plano_id "
                                   "WHERE p.codigo = '4.05' LIMIT 1")
        sub_cre = self.banco.valor("SELECT sp.id FROM subplanos sp JOIN planos_contas p ON p.id = sp.plano_id "
                                   "WHERE p.codigo = '4.04' LIMIT 1")
        if not sub_deb or not sub_cre:
            raise ErroNegocio("Planos de transferência (4.04 e 4.05) não encontrados no plano de contas.")
        d = fmt.para_data_iso(data) or fmt.hoje()
        with self.banco.transacao():
            a = self.incluir(sub_deb, descricao, origem_id, valor_cent, d, d, d)[0]
            b = self.incluir(sub_cre, descricao, destino_id, valor_cent, d, d, d)[0]
        return a, b

    def criar_da_compra(self, lancamento_id: int, vencimento: str, tipo_pagamento_id: int,
                        subplano_id: int | None = None, meses: int = 1, dividir: bool = True) -> list[int]:
        """Botão 'Contas a Pagar' da compra: gera a conta de mercadorias do fornecedor. Com `meses` > 1 o
        total da compra é DIVIDIDO em parcelas mensais (os centavos que sobram ficam na 1ª); `dividir=False`
        repete o valor inteiro todo mês, que só serve para contas recorrentes, não para uma compra."""
        lanc = self.banco.um("SELECT * FROM lancamentos_estoque WHERE id = ?", (lancamento_id,))
        if lanc is None or lanc["tipo"] not in ("compra", "pedido"):
            raise ErroNegocio("Lançamento de compra não encontrado.")
        if self.banco.um("SELECT 1 FROM contas WHERE lancamento_estoque_id = ?", (lancamento_id,)):
            raise ErroNegocio("Esta compra já foi lançada em contas a pagar.")
        valor = lanc["valor_cent"] or self.banco.valor(
            "SELECT SUM(valor_cent) FROM itens_estoque WHERE lancamento_id = ?", (lancamento_id,), 0)
        if subplano_id is None:
            subplano_id = self.banco.valor("SELECT sp.id FROM subplanos sp JOIN planos_contas p ON p.id = sp.plano_id "
                                           "WHERE p.codigo = '2.01' LIMIT 1")
        forn = self.banco.valor("SELECT nome FROM fornecedores WHERE id = ?", (lanc["fornecedor_id"],), "")
        parcelas = None
        if dividir and meses > 1:
            base, sobra = divmod(valor, meses)
            parcelas = [base + sobra] + [base] * (meses - 1)
        return self.incluir(subplano_id, f"Compra {forn}".strip(), tipo_pagamento_id, valor, vencimento,
                            lanc["data"], None, lanc["documento"], True, lanc["nota_fiscal"], False,
                            lanc["fornecedor_id"], meses, lancamento_id, parcelas)

    def painel(self) -> dict:
        hoje = fmt.hoje()
        return {
            "anteriores": self.banco.valor(
                "SELECT COUNT(*) FROM contas WHERE dt_quitacao IS NULL AND dt_vencimento < ?", (hoje,), 0),
            "hoje": self.banco.valor(
                "SELECT COUNT(*) FROM contas WHERE dt_quitacao IS NULL AND dt_vencimento = ?", (hoje,), 0),
        }
