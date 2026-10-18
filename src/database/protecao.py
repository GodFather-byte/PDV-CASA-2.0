"""Proteção do banco local: checagem de integridade, backups válidos e restauração.

Roda ANTES de o banco ser aberto pelo programa (ver src/ui/inicializacao.py). Nada aqui depende de Tkinter.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
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
