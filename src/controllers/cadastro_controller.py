"""CRUD genérico dirigido pelo registro de entidades (ver entidades.py)."""
from __future__ import annotations

import re
import sqlite3

from src.controllers.entidades import ENTIDADES, LOOKUPS, Campo, Entidade
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroValidacao

_SIM = {"S", "SIM", "1", "TRUE", "T", "Y"}


def _bool(valor) -> int:
    if isinstance(valor, str):
        return 1 if valor.strip().upper() in _SIM else 0
    return 1 if valor else 0


class CadastroController:
    def __init__(self, banco):
        self.banco = banco

    # ----------------------------------------------------------- metadados
    @staticmethod
    def entidade(chave: str) -> Entidade:
        return ENTIDADES[chave]

    def opcoes(self, lookup: str) -> list:
        """[(id, rótulo)] para preencher combos."""
        return [(r[0], r[1]) for r in self.banco.todos(LOOKUPS[lookup])]

    def rotulos(self, lookup: str) -> dict:
        return dict(self.opcoes(lookup))

    # ------------------------------------------------------------- consulta
    def listar(self, chave: str, texto: str | None = None, ordem: str | None = None,
               apenas_ativos: bool = False, filtros: dict | None = None) -> list[dict]:
        ent = ENTIDADES[chave]
        onde, params = [], []
        if texto and ent.busca:
            padrao = "%" + re.sub(r"([%_\\])", r"\\\1", texto.strip()) + "%"
            onde.append("(" + " OR ".join(f"norm({c}) LIKE norm(?) ESCAPE '\\'" for c in ent.busca) + ")")
            params += [padrao] * len(ent.busca)
        if apenas_ativos and ent.tem_ativo:
            onde.append("ativo = 1")
        for coluna, valor in (filtros or {}).items():
            ent.campo(coluna)  # valida o nome da coluna
            onde.append(f"{coluna} = ?")
            params.append(valor)
        sql = f"SELECT * FROM {ent.tabela}"
        if onde:
            sql += " WHERE " + " AND ".join(onde)
        sql += f" ORDER BY {ordem or ent.ordem}"
        linhas = [dict(r) for r in self.banco.todos(sql, params)]
        self._rotular(ent, linhas)
        return linhas

    def obter(self, chave: str, id_: int) -> dict | None:
        ent = ENTIDADES[chave]
        r = self.banco.um(f"SELECT * FROM {ent.tabela} WHERE id = ?", (id_,))
        if r is None:
            return None
        linha = dict(r)
        self._rotular(ent, [linha])
        return linha

    def _rotular(self, ent: Entidade, linhas: list[dict]) -> None:
        for c in ent.campos:
            if c.tipo == "lookup":
                mapa = self.rotulos(c.lookup)
                for ln in linhas:
                    ln["_lk_" + c.nome] = mapa.get(ln.get(c.nome), "")

    # ---------------------------------------------------------- apresentação
    def exibir(self, ent: Entidade | str, linha: dict | None) -> dict:
        """Converte uma linha do banco em textos prontos para formulário/grade."""
        if isinstance(ent, str):
            ent = ENTIDADES[ent]
        saida = {}
        for c in ent.campos:
            v = (linha or {}).get(c.nome)
            saida[c.nome] = self._exibir_campo(c, v, linha)
        return saida

    @staticmethod
    def _exibir_campo(c: Campo, v, linha) -> str:
        if c.tipo == "senha":
            return ""
        if c.tipo == "lookup":
            return (linha or {}).get("_lk_" + c.nome, "") or ""
        if v is None:
            return ""
        if c.tipo == "dinheiro":
            return fmt.fmt_num(v)
        if c.tipo == "decimal":
            texto = f"{float(v):.4f}".rstrip("0").rstrip(".")
            return texto.replace(".", ",")
        if c.tipo == "sn":
            return "S" if v else "N"
        if c.tipo == "data":
            return fmt.fmt_data(v)
        if c.tipo == "escolha":
            for valor, rotulo in c.opcoes or []:
                if str(valor) == str(v):
                    return rotulo
            return str(v)
        return str(v)

    def valores_iniciais(self, chave: str) -> dict:
        """Valores sugeridos para um novo registro (padrões e próximo código)."""
        ent = ENTIDADES[chave]
        brutos = {}
        for c in ent.campos:
            if c.somente_leitura or c.tipo in ("lookup", "senha"):
                continue
            if c.padrao is not None:
                brutos[c.nome] = self._exibir_campo(c, c.padrao, None)
        b = self.banco
        if chave == "produtos":
            brutos["codigo"] = self.proximo_codigo_produto()
        elif chave == "observacoes":
            brutos["codigo"] = str(b.valor("SELECT MAX(codigo) FROM observacoes", padrao=0) + 1)
        elif chave == "clientes":
            brutos["numero_consulta"] = self.proximo_numero_cliente()
        elif chave == "tipos_pagamento":
            brutos["ordem"] = str(b.valor("SELECT MAX(ordem) FROM tipos_pagamento", padrao=0) + 10)
        elif chave == "planos_contas":
            brutos["ordem"] = str(b.valor("SELECT MAX(ordem) FROM planos_contas", padrao=0) + 1)
        return brutos

    def proximo_codigo_produto(self) -> str:
        maior = 0
        for (cod,) in self.banco.todos("SELECT codigo FROM produtos"):
            if cod.isdigit():
                maior = max(maior, int(cod))
        return str(maior + 1).zfill(13)

    def proximo_numero_cliente(self) -> str:
        """Maior número de consulta numérico + 1 (contar os clientes repetiria um número depois de uma exclusão)."""
        maior = 0
        for (num,) in self.banco.todos("SELECT numero_consulta FROM clientes"):
            if num.isdigit():
                maior = max(maior, int(num))
        return str(maior + 1).zfill(6)

    # ------------------------------------------------------------ gravação
    def converter(self, ent: Entidade, valores: dict, inserindo: bool) -> dict:
        dados, erros = {}, {}
        for c in ent.campos:
            if c.somente_leitura:
                continue
            if c.nome not in valores and not inserindo:
                continue  # edição parcial: só altera o que foi enviado
            try:
                dados[c.nome] = self._converter_campo(c, valores.get(c.nome), inserindo)
            except ValueError as e:
                erros[c.nome] = str(e)
        if erros:
            raise ErroValidacao(" ".join(erros.values()), erros)
        return dados

    @staticmethod
    def _converter_campo(c: Campo, bruto, inserindo: bool):
        if isinstance(bruto, str):
            bruto = bruto.strip()
        vazio = bruto is None or bruto == ""
        if c.tipo == "senha":
            if vazio and c.obrigatorio and inserindo:
                raise ValueError(f"Informe: {c.rotulo}.")
            return bruto or ""
        if vazio:
            if c.padrao is not None and c.tipo in ("int", "dinheiro", "decimal", "sn", "escolha"):
                return c.padrao
            if c.obrigatorio:
                raise ValueError(f"Informe: {c.rotulo}.")
            if c.tipo in ("int", "dinheiro", "decimal", "sn"):
                return 0
            return None
        t = c.tipo
        if t == "texto":
            if c.tamanho and len(bruto) > c.tamanho:
                raise ValueError(f"{c.rotulo}: máximo de {c.tamanho} caracteres.")
            return bruto
        if t == "cod13":
            if not bruto.isdigit() or len(bruto) > 13:
                raise ValueError(f"{c.rotulo}: somente números, até 13 dígitos.")
            return bruto.zfill(13)
        if t == "int":
            try:
                n = int(float(str(bruto).replace(",", ".")))
            except ValueError:
                raise ValueError(f"{c.rotulo}: número inteiro inválido.") from None
            if (c.minimo is not None and n < c.minimo) or (c.maximo is not None and n > c.maximo):
                faixa = f"entre {c.minimo:g} e {c.maximo:g}" if None not in (c.minimo, c.maximo) else "fora da faixa permitida"
                raise ValueError(f"{c.rotulo}: valor {faixa}.")
            return n
        if t == "dinheiro":
            try:
                return fmt.para_centavos(bruto)
            except ValueError:
                raise ValueError(f"{c.rotulo}: valor inválido.") from None
        if t == "decimal":
            try:
                return fmt.para_qtd(bruto)
            except ValueError:
                raise ValueError(f"{c.rotulo}: número inválido.") from None
        if t == "sn":
            return _bool(bruto)
        if t == "data":
            try:
                return fmt.para_data_iso(str(bruto))
            except ValueError as e:
                raise ValueError(f"{c.rotulo}: {e}") from None
        if t == "hora":
            try:
                return fmt.para_hora(str(bruto))
            except ValueError as e:
                raise ValueError(f"{c.rotulo}: {e}") from None
        if t == "escolha":
            for valor, rotulo in c.opcoes or []:
                if str(valor) == str(bruto) or rotulo == bruto:
                    return valor
            raise ValueError(f"{c.rotulo}: opção inválida.")
        if t == "lookup":
            try:
                return int(bruto)
            except ValueError:
                raise ValueError(f"{c.rotulo}: seleção inválida.") from None
        return bruto

    def salvar(self, chave: str, valores: dict, id_: int | None = None) -> int:
        ent = ENTIDADES[chave]
        dados = self.converter(ent, valores, inserindo=id_ is None)
        try:
            with self.banco.transacao():
                if ent.antes_salvar:
                    dados = ent.antes_salvar(self.banco, dados, id_)
                if id_ is None:
                    id_ = self.banco.inserir(ent.tabela, dados)
                else:
                    if self.banco.um(f"SELECT 1 FROM {ent.tabela} WHERE id = ?", (id_,)) is None:
                        raise ErroNegocio("Registro não encontrado (foi excluído por outro usuário?).")
                    self.banco.atualizar(ent.tabela, id_, dados)
        except sqlite3.IntegrityError as e:
            raise self._traduzir(ent, e) from e
        return id_

    def excluir(self, chave: str, id_: int) -> str | None:
        """Exclui o cadastro; os registros históricos de produtos são preservados separadamente."""
        ent = ENTIDADES[chave]
        if ent.excluir_fn:
            try:
                return ent.excluir_fn(self.banco, id_)
            except sqlite3.IntegrityError as e:
                raise ErroNegocio(ent.msg_em_uso) from e
        if ent.antes_excluir:
            ent.antes_excluir(self.banco, id_)
        try:
            with self.banco.transacao():
                self.banco.executar(f"DELETE FROM {ent.tabela} WHERE id = ?", (id_,))
        except sqlite3.IntegrityError as e:
            if "FOREIGN KEY" in str(e):
                raise ErroNegocio(ent.msg_em_uso) from e
            raise self._traduzir(ent, e) from e

    @staticmethod
    def _traduzir(ent: Entidade, exc: sqlite3.IntegrityError) -> ErroNegocio:
        msg = str(exc)
        nomes = {c.nome: c.rotulo for c in ent.campos}
        if "UNIQUE" in msg:
            cols = [n for n in re.findall(r"\b%s\.(\w+)" % re.escape(ent.tabela), msg) if n in nomes]
            alvo = ", ".join(nomes[n] for n in cols) or "um campo único"
            return ErroNegocio(f"Já existe um registro com o mesmo valor em: {alvo}.")
        if "FOREIGN KEY" in msg:
            return ErroNegocio("Um dos valores selecionados não existe mais. Atualize a lista e tente de novo.")
        if "NOT NULL" in msg:
            col = msg.rsplit(".", 1)[-1]
            return ErroNegocio(f"Campo obrigatório não informado: {nomes.get(col, col)}.")
        return ErroNegocio(f"Dados inválidos: {msg}")
