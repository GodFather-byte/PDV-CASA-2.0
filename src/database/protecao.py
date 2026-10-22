"""Proteção do banco local: checagem de integridade, backups válidos e restauração.

Roda ANTES de o banco ser aberto pelo programa (ver src/ui/inicializacao.py). Nada aqui depende de Tkinter.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

log = logging.getLogger("pdv.protecao")
PADRAO_BACKUP = "loja_offline-*.db"
PENDENTE = "restaurar.pendente"


def verificar_arquivo(caminho: str | Path) -> str | None:
    """None se o banco está íntegro (ou ainda não existe); senão, o motivo. Abre só para leitura."""
    caminho = Path(caminho)
    if not caminho.exists():
        return None
    if caminho.stat().st_size == 0:
        return "O arquivo do banco está vazio."
    try:
        con = sqlite3.connect(f"file:{caminho.as_posix()}?mode=ro", uri=True, timeout=15)
        try:
            linhas = [r[0] for r in con.execute("PRAGMA quick_check")]
        finally:
            con.close()
    except sqlite3.Error as e:
        return str(e)
    return None if linhas == ["ok"] else "; ".join(linhas[:3])


def _arquivo_pastas(caminho_db: str | Path) -> Path:
    return Path(str(caminho_db) + ".pastas.json")


def registrar_pasta(caminho_db: str | Path, pasta: str | Path) -> None:
    """Guarda ao lado do banco as pastas onde há backups: se o banco estragar, as configurações dentro dele somem."""
    arquivo = _arquivo_pastas(caminho_db)
    pastas = pastas_conhecidas(caminho_db)
    nova = str(Path(pasta).resolve())
    if nova in pastas:
        return
    try:
        arquivo.write_text(json.dumps(pastas + [nova]), encoding="utf-8")
    except OSError:
        pass


def pastas_conhecidas(caminho_db: str | Path) -> list[str]:
    try:
        dados = json.loads(_arquivo_pastas(caminho_db).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in dados if isinstance(p, str)]


def listar_backups(pastas) -> list[Path]:
    """Todos os backups das pastas, do mais novo ao mais antigo (o nome carrega a data e a hora)."""
    achados: dict[str, Path] = {}
    for pasta in pastas:
        try:
            for p in Path(pasta).glob(PADRAO_BACKUP):
                achados.setdefault(p.name, p)
        except OSError:
            continue
    return sorted(achados.values(), key=lambda p: p.name, reverse=True)


def backup_valido(caminho: str | Path) -> bool:
    """Íntegro e com o esquema do PDV (não é um arquivo qualquer)."""
    if verificar_arquivo(caminho) is not None:
        return False
    try:
        con = sqlite3.connect(f"file:{Path(caminho).as_posix()}?mode=ro", uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('vendas','produtos','turnos')").fetchone()[0] == 3
        finally:
            con.close()
    except sqlite3.Error:
        return False


TABELAS_ESSENCIAIS = ("vendas", "produtos", "turnos")
TABELAS_CONFERIDAS = ("config", "operadores", "produtos", "clientes", "turnos", "vendas", "itens_venda",
                      "pagamentos_venda", "movimentos_caixa", "movimentos_estoque", "caderneta", "log_eventos")
_CAMINHO_WINDOWS = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\s'\"<>|]*")
_CAMINHO_ENTRE_ASPAS = re.compile(r"(['\"])[^'\"\r\n]*[\\/][^'\"\r\n]*\1")
_CAMINHO_POSIX = re.compile(r"(?<![\w.])/(?:[^\s'\"<>|/]+/)+[^\s'\"<>|]*")


def sanitizar_erro(erro, *segredos: str, limite: int = 240) -> str:
    """Texto curto para gravar/mostrar: sem caminhos completos, quebras de linha nem segredos informados."""
    texto = " ".join(str(erro).split())
    for segredo in segredos:
        if segredo:
            texto = texto.replace(segredo, "***")
    texto = _CAMINHO_ENTRE_ASPAS.sub("<caminho>", texto)
    texto = _CAMINHO_POSIX.sub("<caminho>", _CAMINHO_WINDOWS.sub("<caminho>", texto))
    return (texto or erro.__class__.__name__)[:limite]


def _resumo_banco(con: sqlite3.Connection) -> dict:
    tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    contagens = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in TABELAS_CONFERIDAS if t in tabelas}
    vendas = {"fechadas": 0, "total_fechadas_cent": 0, "ultima_venda_em": None}
    if "vendas" in tabelas:
        colunas = {r[1] for r in con.execute('PRAGMA table_info("vendas")')}
        if {"status", "total_cent", "fechada_em"} <= colunas:
            linha = con.execute("SELECT COUNT(*), COALESCE(SUM(total_cent), 0), MAX(fechada_em) FROM vendas "
                                "WHERE status = 'fechada'").fetchone()
            vendas = {"fechadas": linha[0], "total_fechadas_cent": int(linha[1]), "ultima_venda_em": linha[2]}
    return {"tabelas": tabelas, "contagens": contagens, "vendas": vendas,
            "versao": con.execute("PRAGMA user_version").fetchone()[0]}


def testar_restauracao_isolada(backup: str | Path, versao_maxima: int | None = None,
                               proibidos=(), pasta_temporaria: str | Path | None = None) -> dict:
    """Ensaio de restauração: copia o backup para uma pasta temporária, refaz nela o mesmo preparo de `restaurar`
    (API de backup do SQLite + journal DELETE) e confere integridade completa, esquema, chaves estrangeiras e
    contagens/vendas entre origem e cópia restaurada. Vínculos quebrados aprovam com 'avisos' (lista não vazia). Nunca abre, troca ou marca o banco de produção; o backup
    original só é lido. Não levanta erro: devolve {'ok', 'verificacoes': [(item, ok, detalhe)], 'erro', ...}."""
    backup = Path(backup)
    verificacoes: list[tuple[str, bool, str]] = []
    resultado = {"ok": False, "arquivo": backup.name, "verificacoes": verificacoes, "erro": "", "versao": None,
                 "contagens": {}, "vendas": {}, "tamanho": None, "avisos": []}

    def falhar(item: str, detalhe: str) -> dict:
        detalhe = sanitizar_erro(detalhe)
        verificacoes.append((item, False, detalhe))
        resultado["erro"] = sanitizar_erro(f"{item}: {detalhe}")
        return resultado

    try:
        alvo = backup.resolve()
        for proibido in proibidos:
            base = Path(proibido).resolve()
            if alvo in (base, Path(str(base) + "-wal"), Path(str(base) + "-shm")):
                return falhar("Arquivo escolhido", "é o banco em uso, não um backup.")
        if not backup.is_file():
            return falhar("Arquivo do backup", "não encontrado ou não é um arquivo.")
        resultado["tamanho"] = backup.stat().st_size
        if not resultado["tamanho"]:
            return falhar("Arquivo do backup", "está vazio.")
        verificacoes.append(("Arquivo do backup", True, f"{resultado['tamanho']} bytes"))
        with tempfile.TemporaryDirectory(prefix="willpdv_teste_restauracao_", dir=pasta_temporaria) as pasta:
            origem = Path(pasta) / "origem.db"
            restaurado = Path(pasta) / "restaurado.db"
            shutil.copyfile(backup, origem)
            wal = Path(str(backup) + "-wal")
            if wal.is_file():
                shutil.copyfile(wal, Path(str(origem) + "-wal"))
            verificacoes.append(("Cópia isolada", True, "backup copiado para pasta temporária; original só lido"))
            problema = verificar_arquivo(origem)
            if problema is not None:
                return falhar("Integridade do backup", problema)
            verificacoes.append(("Integridade do backup", True, "quick_check ok"))
            con = sqlite3.connect(origem)
            try:
                antes = _resumo_banco(con)
                destino = sqlite3.connect(restaurado)
                try:
                    con.backup(destino)
                    destino.execute("PRAGMA journal_mode = DELETE")
                finally:
                    destino.close()
            finally:
                con.close()
            verificacoes.append(("Restauração de teste", True, "cópia restaurada na pasta temporária"))
            con = sqlite3.connect(f"file:{restaurado.as_posix()}?mode=ro", uri=True)
            try:
                integridade = [r[0] for r in con.execute("PRAGMA integrity_check")]
                if integridade != ["ok"]:
                    return falhar("Integridade da cópia restaurada", "; ".join(integridade[:3]))
                verificacoes.append(("Integridade da cópia restaurada", True, "integrity_check ok"))
                depois = _resumo_banco(con)
                faltando = [t for t in TABELAS_ESSENCIAIS if t not in depois["tabelas"]]
                if faltando:
                    return falhar("Esquema do PDV", "faltam as tabelas " + ", ".join(faltando))
                resultado["versao"] = depois["versao"]
                if versao_maxima is not None and depois["versao"] > versao_maxima:
                    return falhar("Versão do esquema",
                                  f"backup na versão {depois['versao']}, este PDV aceita até {versao_maxima}.")
                verificacoes.append(("Esquema do PDV", True, f"versão {depois['versao']}"))
                # integrity_check não confere chaves estrangeiras. Órfãos não impedem a restauração (o SQLite não
                # os revalida ao abrir e a restauração real copia o banco igual), mas indicam dado inconsistente
                # (backup antigo/legado ou gravação sem foreign_keys): aprova COM AVISO explícito, nunca em silêncio.
                orfaos = con.execute("PRAGMA foreign_key_check").fetchmany(1001)
                if orfaos:
                    por_tabela: dict[str, int] = {}
                    for linha in orfaos[:1000]:
                        por_tabela[f"{linha[0]} sem {linha[2]}"] = por_tabela.get(f"{linha[0]} sem {linha[2]}", 0) + 1
                    total = "mais de 1000" if len(orfaos) > 1000 else str(len(orfaos))
                    aviso = (f"{total} registro(s) sem vínculo (" + "; ".join(
                        f"{k}: {n}" for k, n in sorted(por_tabela.items())[:5]) + ")")
                    resultado["avisos"].append(f"Vínculos entre tabelas: {aviso}")
                    verificacoes.append(("Vínculos entre tabelas", False, f"AVISO: {aviso}"))
                else:
                    verificacoes.append(("Vínculos entre tabelas", True, "foreign_key_check ok"))
            finally:
                con.close()
            if antes["contagens"] != depois["contagens"] or antes["vendas"] != depois["vendas"]:
                return falhar("Conferência de dados", "a cópia restaurada difere do backup.")
            resultado["contagens"], resultado["vendas"] = depois["contagens"], depois["vendas"]
            verificacoes.append(("Conferência de dados", True, ", ".join(
                f"{t}: {n}" for t, n in depois["contagens"].items())))
    except (OSError, sqlite3.Error, ValueError) as e:
        return falhar("Erro na verificação", sanitizar_erro(e))
    resultado["ok"] = True
    return resultado


def ultimo_backup_valido(pastas) -> Path | None:
    return next((p for p in listar_backups(pastas) if backup_valido(p)), None)


def restaurar(caminho_db: str | Path, backup: str | Path) -> Path | None:
    """Põe o backup no lugar do banco. O banco atual NÃO é apagado: vai para `<banco>.antes-<data>` (com -wal/-shm
    ao lado). Devolve onde ele ficou (None se não havia banco)."""
    caminho_db, backup = Path(caminho_db), Path(backup)
    if not backup_valido(backup):
        raise ValueError("O backup escolhido está danificado ou não é um banco do PDV.")
    identificador = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex}"
    preparado = caminho_db.with_name(f"{caminho_db.name}.restaurando-{identificador}")
    guardado = caminho_db.with_name(f"{caminho_db.name}.antes-{identificador}")
    movidos = []
    havia_banco = caminho_db.exists()
    try:
        # O backup SQLite inclui também transações que ainda estejam no WAL da origem.
        origem = sqlite3.connect(f"file:{backup.as_posix()}?mode=ro", uri=True)
        try:
            destino = sqlite3.connect(preparado)
            try:
                origem.backup(destino)
                destino.execute("PRAGMA journal_mode = DELETE")
            finally:
                destino.close()
        finally:
            origem.close()
        if not backup_valido(preparado):
            raise ValueError("A cópia preparada para restauração não é válida.")
        with preparado.open("r+b") as arquivo:
            os.fsync(arquivo.fileno())
        if havia_banco:
            shutil.copyfile(caminho_db, guardado)
            with guardado.open("r+b") as arquivo:
                os.fsync(arquivo.fileno())
        for sufixo in ("-wal", "-shm"):
            lateral = Path(str(caminho_db) + sufixo)
            if lateral.exists():
                salvo = Path(str(guardado) + sufixo)
                os.replace(lateral, salvo)
                movidos.append((lateral, salvo))
        try:
            os.replace(preparado, caminho_db)
        except BaseException:
            for lateral, salvo in reversed(movidos):
                os.replace(salvo, lateral)
            raise
        return guardado if havia_banco else None
    except BaseException:
        # Também reverte quando a movimentação do segundo arquivo lateral falha.
        for lateral, salvo in reversed(movidos):
            if salvo.exists() and not lateral.exists():
                os.replace(salvo, lateral)
        raise
    finally:
        for sufixo in ("", "-wal", "-shm"):
            Path(str(preparado) + sufixo).unlink(missing_ok=True)


def pedir_restauracao(caminho_db: str | Path, backup: str | Path) -> None:
    """Deixa a restauração marcada para o próximo início do programa (o banco aberto não pode ser trocado por baixo)."""
    if not backup_valido(backup):
        raise ValueError("O backup escolhido está danificado ou não é um banco do PDV.")
    Path(str(caminho_db) + "." + PENDENTE).write_text(str(Path(backup).resolve()), encoding="utf-8")


def aplicar_restauracao_pendente(caminho_db: str | Path) -> Path | None:
    """Se houver pedido de restauração, executa e apaga o pedido. Devolve o backup usado."""
    marca = Path(str(caminho_db) + "." + PENDENTE)
    if not marca.exists():
        return None
    backup = Path(marca.read_text(encoding="utf-8").strip())
    restaurar(caminho_db, backup)
    marca.unlink()
    return backup


def _raiz() -> Path:
    from src.database.conexao import RAIZ
    return RAIZ


def _pastas_de_backup(caminho_db: str) -> list[str]:
    return [str(_raiz() / "Backup"), *pastas_conhecidas(caminho_db)]


def preparar_banco(caminho_db: str, perguntar) -> str:
    """Devolve 'ok', 'restaurado' (voltou um backup) ou 'cancelado' (o operador desistiu de abrir).
    `perguntar(titulo, texto) -> bool` é a pergunta sim/não ao operador (nos testes, uma função)."""
    try:
        usado = aplicar_restauracao_pendente(caminho_db)
    except (OSError, ValueError, sqlite3.Error) as e:
        log.error("Restauração marcada falhou: %s", e)
        return "cancelado"
    problema = verificar_arquivo(caminho_db)
    if problema is None:
        return "restaurado" if usado else "ok"
    log.error("Banco com problema de integridade: %s", problema)
    backup = ultimo_backup_valido(_pastas_de_backup(caminho_db))
    if backup is None:
        if Path(caminho_db).stat().st_size == 0:
            log.error("Banco vazio sem backup válido; abertura cancelada.")
            return "cancelado"
        return "ok" if perguntar(
            "Banco danificado",
            "O banco de dados está danificado e NÃO há backup válido nas pastas conhecidas.\n\n"
            "Abrir mesmo assim? (Pode dar erro. Chame o suporte antes de vender.)") else "cancelado"
    if perguntar("Banco danificado",
                 f"O banco de dados está danificado ({problema[:120]}).\n\nRestaurar o último backup válido?\n{backup.name}\n\n"
                 "O banco danificado é guardado ao lado, sem apagar nada."):
        try:
            restaurar(caminho_db, backup)
        except (OSError, ValueError, sqlite3.Error) as e:
            log.error("Restauração falhou: %s", e)
            return "cancelado"
        log.warning("Banco restaurado do backup %s.", backup)
        return "restaurado"
    return "cancelado"
