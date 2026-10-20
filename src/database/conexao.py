"""Conexão SQLite do PDV: cria o esquema, migra bancos legados e oferece
transações aninhadas e atalhos de consulta."""
from __future__ import annotations

import os
import json
import sqlite3
import sys
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from src.core import formatacao as fmt
from src.database import esquema, sementes


def normalizar(texto) -> str | None:
    """Maiúsculas e sem acentos ('Café' -> 'CAFE'): a busca por nome acha 'cafe', 'CAFÉ' e 'café'.
    O LIKE do SQLite só ignora a caixa das letras ASCII, então ele sozinho falha com acento."""
    if texto is None:
        return None
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).upper()


def _raiz_dados() -> Path:
    """Pasta do banco, de Backup/ e de impressao/. No código-fonte é a raiz do projeto. No executável
    do PyInstaller o código fica em `_internal`, que a atualização substitui, então os dados vão para
    %LOCALAPPDATA%\\WILL-PDV e sobrevivem às versões."""
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WILL-PDV"
    return Path(__file__).resolve().parents[2]


RAIZ = _raiz_dados()


def caminho_padrao() -> str:
    """Banco na raiz do projeto (fora da pasta de código), ou o caminho em PDV_DB."""
    return os.environ.get("PDV_DB") or str(RAIZ / "loja_offline.db")


class BancoDados:
    def __init__(self, caminho: str | None = None, semear: bool = True):
        self.caminho = str(caminho or caminho_padrao())
        self._profundidade = 0
        self._operador_auditoria = None
        self._auditoria_ativa = False
        if self.caminho != ":memory:":
            Path(self.caminho).parent.mkdir(parents=True, exist_ok=True)
        self.conexao = self._abrir()
        try:
            if self._banco_legado():
                self._guardar_legado()
                self.conexao.close()
                for sufixo in ("", "-wal", "-shm"):
                    try:
                        os.remove(self.caminho + sufixo)
                    except FileNotFoundError:
                        pass
                self.conexao = self._abrir()
            self._guardar_antes_migracao()
            self._criar_esquema()
            if semear:
                sementes.aplicar(self)
            self._auditoria_ativa = True
        except Exception:
            self.conexao.close()
            raise

    # ------------------------------------------------------------- abertura
    def _abrir(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.caminho, isolation_level=None, timeout=15)
        try:
            versao = con.execute("PRAGMA user_version").fetchone()[0]
            if versao > esquema.VERSAO_ESQUEMA:
                raise ValueError(
                    f"Banco na versão {versao}, superior à suportada ({esquema.VERSAO_ESQUEMA}). "
                    "Atualize o PDV antes de abrir este banco.")
            con.row_factory = sqlite3.Row
            con.create_function("norm", 1, normalizar, deterministic=True)
            con.create_function("auditoria_agora", 0, fmt.agora)
            con.create_function("auditoria_operador", 0, lambda: self._operador_auditoria)
            con.create_function("auditoria_ativa", 0, lambda: int(self._auditoria_ativa))
            con.create_function("auditoria_json", -1, lambda *pares: json.dumps(
                dict(zip(pares[::2], pares[1::2])), ensure_ascii=False, allow_nan=False))
            con.execute("PRAGMA foreign_keys = ON")
            if self.caminho != ":memory:":
                con.execute("PRAGMA journal_mode = WAL")
        except BaseException:
            con.close()
            raise
        return con

    def _banco_legado(self) -> bool:
        """Protótipo antigo (produtos sem coluna 'codigo'), sem versão de esquema."""
        if self.conexao.execute("PRAGMA user_version").fetchone()[0] != 0:
            return False
        tem = self.conexao.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='produtos'").fetchone()
        if not tem:
            return False
        colunas = [r[1] for r in self.conexao.execute("PRAGMA table_info(produtos)")]
        return "codigo" not in colunas

    def _guardar_legado(self) -> None:
        if self.caminho == ":memory:":
            return
        destino = f"{self.caminho}.legado-{fmt.agora().replace(':', '').replace(' ', '-')}.bak"
        Path(destino).parent.mkdir(parents=True, exist_ok=True)
        copia = sqlite3.connect(destino)
        try:
            self.conexao.backup(copia)
        finally:
            copia.close()

    def _guardar_antes_migracao(self) -> None:
        """Preserva um retrato consistente antes de qualquer DDL de atualização."""
        versao = self.conexao.execute("PRAGMA user_version").fetchone()[0]
        if self.caminho == ":memory:" or versao >= esquema.VERSAO_ESQUEMA:
            return
        if self.conexao.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone() is None:
            return
        instante = fmt.agora().replace(":", "").replace(" ", "-")
        destino = Path(f"{self.caminho}.antes-migracao-v{versao}-{instante}-{uuid4().hex}.bak")
        try:
            with destino.open("xb"):
                pass
            copia = sqlite3.connect(destino)
            try:
                self.conexao.backup(copia)
                copia.execute("PRAGMA journal_mode = DELETE")
                if [r[0] for r in copia.execute("PRAGMA quick_check")] != ["ok"]:
                    raise sqlite3.DatabaseError("A cópia anterior à migração falhou na verificação de integridade.")
            finally:
                copia.close()
            with destino.open("r+b") as arquivo:
                os.fsync(arquivo.fileno())
        except BaseException:
            for sufixo in ("", "-wal", "-shm"):
                Path(str(destino) + sufixo).unlink(missing_ok=True)
            raise

    def _criar_esquema(self) -> None:
        versao = self.conexao.execute("PRAGMA user_version").fetchone()[0]
        novo = self.conexao.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='config'").fetchone() is None
        for comando in esquema.TABELAS:
            self.conexao.execute(comando)
        if not novo and versao < esquema.VERSAO_ESQUEMA:
            self._migrar(versao)
        for comando in esquema.INDICES_POS_MIGRACAO + esquema.AUDITORIA:
            self.conexao.execute(comando)
        self.conexao.execute(f"PRAGMA user_version = {esquema.VERSAO_ESQUEMA}")

    def _migrar(self, de: int) -> None:
        """Aplica as migrações pendentes, da versão `de`+1 até a atual, cada uma em transação."""
        for versao in range(de + 1, esquema.VERSAO_ESQUEMA + 1):
            comandos = esquema.MIGRACOES.get(versao)
            self.conexao.execute("BEGIN")
            try:
                for passo in comandos or ():
                    if isinstance(passo, tuple):
                        # ("coluna", tabela, nome, definição): só adiciona se faltar (a tabela pode ter acabado
                        # de ser criada já na forma atual, em um banco antigo que não a tinha).
                        _, tabela, coluna, definicao = passo
                        if coluna not in [r[1] for r in self.conexao.execute(f"PRAGMA table_info({tabela})")]:
                            self.conexao.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")
                    else:
                        self.conexao.execute(passo)
                self.conexao.execute(f"PRAGMA user_version = {versao}")
            except Exception:
                self.conexao.execute("ROLLBACK")
                raise
            self.conexao.execute("COMMIT")

    # ------------------------------------------------------------ transações
    @contextmanager
    def transacao(self):
        """BEGIN na primeira camada; SAVEPOINT nas aninhadas. Reverte tudo se houver exceção."""
        nome = f"sp{self._profundidade}"
        if self._profundidade == 0:
            self.conexao.execute("BEGIN IMMEDIATE")
        else:
            self.conexao.execute(f"SAVEPOINT {nome}")
        self._profundidade += 1
        try:
            yield self
        except BaseException:
            self._profundidade -= 1
            if self._profundidade == 0:
                self.conexao.execute("ROLLBACK")
            else:
                self.conexao.execute(f"ROLLBACK TO {nome}")
                self.conexao.execute(f"RELEASE {nome}")
            raise
        else:
            self._profundidade -= 1
            if self._profundidade == 0:
                self.conexao.execute("COMMIT")
            else:
                self.conexao.execute(f"RELEASE {nome}")

    # ------------------------------------------------------------- consultas
    def executar(self, sql: str, params=()) -> sqlite3.Cursor:
        return self.conexao.execute(sql, params)

    def um(self, sql: str, params=()):
        return self.conexao.execute(sql, params).fetchone()

    def todos(self, sql: str, params=()) -> list[sqlite3.Row]:
        return self.conexao.execute(sql, params).fetchall()

    def valor(self, sql: str, params=(), padrao=None):
        linha = self.conexao.execute(sql, params).fetchone()
        return linha[0] if linha is not None and linha[0] is not None else padrao

    def inserir(self, tabela: str, dados: dict) -> int:
        colunas = ", ".join(dados)
        marcas = ", ".join("?" for _ in dados)
        cur = self.conexao.execute(f"INSERT INTO {tabela} ({colunas}) VALUES ({marcas})", tuple(dados.values()))
        return cur.lastrowid

    def atualizar(self, tabela: str, id_: int, dados: dict) -> None:
        if not dados:
            return
        sets = ", ".join(f"{c} = ?" for c in dados)
        self.conexao.execute(f"UPDATE {tabela} SET {sets} WHERE id = ?", (*dados.values(), id_))

    # ------------------------------------------------------- config e auditoria
    def definir_operador_auditoria(self, operador_id: int | None) -> None:
        """Identidade da sessão; autorizações de supervisor não a substituem."""
        if operador_id is not None:
            if not isinstance(operador_id, int) or isinstance(operador_id, bool):
                raise ValueError("Operador da auditoria deve ser um identificador inteiro.")
            if not self.valor("SELECT 1 FROM operadores WHERE id = ? AND ativo = 1", (operador_id,)):
                raise ValueError("Operador da auditoria não encontrado ou inativo.")
        self._operador_auditoria = operador_id

    def cfg(self, chave: str, padrao: str = "") -> str:
        v = self.valor("SELECT valor FROM config WHERE chave = ?", (chave,))
        return padrao if v is None else v

    def cfg_bool(self, chave: str, padrao: bool = False) -> bool:
        return self.cfg(chave, "S" if padrao else "N").strip().upper() in ("S", "1", "SIM", "TRUE")

    def cfg_int(self, chave: str, padrao: int = 0) -> int:
        try:
            return int(float(self.cfg(chave, str(padrao)) or padrao))
        except ValueError:
            return padrao

    def cfg_set(self, chave: str, valor) -> None:
        self.executar("INSERT OR REPLACE INTO config(chave, valor) VALUES (?, ?)", (chave, str(valor)))

    def log(self, evento: str, detalhe: str = "", operador_id: int | None = None) -> None:
        self.executar("INSERT INTO log_eventos(quando, operador_id, evento, detalhe) VALUES (?,?,?,?)",
                      (fmt.agora(), operador_id, evento, detalhe))

    def registrar_auditoria(self, entidade: str, entidade_id: str, acao: str,
                            antes: dict | None = None, depois: dict | None = None,
                            operador_id: int | None = None) -> None:
        """Grava evento estruturado explícito, inclusive quando a operação de negócio foi recusada."""
        ator = self._operador_auditoria if operador_id is None else operador_id
        self.executar(
            "INSERT INTO auditoria_eventos(quando, operador_id, origem, entidade, entidade_id, acao, antes, depois) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fmt.agora(), ator, "operador" if ator is not None else "sistema", entidade, str(entidade_id), acao,
             json.dumps(antes, ensure_ascii=False, allow_nan=False) if antes is not None else None,
             json.dumps(depois, ensure_ascii=False, allow_nan=False) if depois is not None else None))

    # --------------------------------------------------------------- backup
    def copiar_para(self, destino: str) -> None:
        """Cópia consistente do banco inteiro (API de backup do SQLite)."""
        Path(destino).parent.mkdir(parents=True, exist_ok=True)
        copia = sqlite3.connect(destino)
        try:
            self.conexao.backup(copia)
        finally:
            copia.close()

    def fechar(self) -> None:
        try:
            self.conexao.close()
        except sqlite3.Error:
            pass


if __name__ == "__main__":
    banco = BancoDados()
    print(f"Banco criado/conectado com sucesso em {banco.caminho}")
    banco.fechar()
