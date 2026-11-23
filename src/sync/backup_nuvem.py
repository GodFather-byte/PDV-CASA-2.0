"""Backup do caixa na nuvem: manda o backup local mais novo (o mesmo arquivo de Utilitários > Backup) compactado, e
recupera a loja inteira num computador novo.

Envio: no máximo a cada INTERVALO_HORAS, sempre que há um backup local mais novo que o último enviado (o caixa faz
backup na troca de turno, na saída e no início). Caixa adicional (banco remoto) não envia: o banco é do principal.
Recuperação: baixa da nuvem, confere o SHA-256 e o banco, mantém o endereço, o token e a licença desta instalação e
marca a restauração para o próximo início (o mesmo caminho do backup local, com cópia de segurança do banco atual).
"""
from __future__ import annotations

import gzip
import hashlib
import logging
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

log = logging.getLogger("pdv.backup_nuvem")

INTERVALO_HORAS = 3
CHAVE_ULTIMO = "backup_nuvem_ultimo"          # quando a nuvem confirmou
CHAVE_ARQUIVO = "backup_nuvem_arquivo"        # nome do último arquivo enviado
CHAVE_ERRO = "backup_nuvem_erro"
# O que é desta instalação e não pode voltar antigo junto com o banco recuperado.
CHAVES_DA_INSTALACAO = ("api_url", "api_token", "chave_loja", "painel_dono", "licenca_token", "licenca_ultimo_uso")


def configurado(banco) -> bool:
    return (not getattr(banco, "remoto", False) and banco.caminho != ":memory:"
            and bool((banco.cfg("api_url") or "").strip()) and bool((banco.cfg("api_token") or "").strip()))


def _mais_novo(banco) -> Path | None:
    from src.controllers.utilitario_controller import UtilitarioController
    backups = [p for p in UtilitarioController(banco).listar_backups() if "recuperado" not in p.name
               and "nuvem" not in p.name]
    return max(backups, key=lambda p: p.stat().st_mtime) if backups else None


def ha_pendente(banco) -> bool:
    if not configurado(banco):
        return False
    novo = _mais_novo(banco)
    if novo is None or novo.name == banco.cfg(CHAVE_ARQUIVO):
        return False
    ultimo = banco.cfg(CHAVE_ULTIMO)
    if not ultimo:
        return True
    try:
        horas = (datetime.fromisoformat(fmt.agora()) - datetime.fromisoformat(ultimo)).total_seconds() / 3600
    except ValueError:
        return True
    return horas >= INTERVALO_HORAS


def _base(banco) -> tuple[str, dict]:
    from src.sync.painel_envio import _base_nuvem
    return _base_nuvem(banco.cfg("api_url")), {"Authorization": f"Bearer {banco.cfg('api_token').strip()}"}


def _esquema(caminho: Path) -> int:
    conexao = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        return int(conexao.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conexao.close()


def enviar(banco, http=None) -> bool:
    """Manda o backup local mais novo. Devolve True se a nuvem confirmou. Erro de rede vira aviso, não exceção."""
    if not ha_pendente(banco):
        return False
    arquivo = _mais_novo(banco)
    if http is None:
        import requests as http
    base, cabecalho = _base(banco)
    try:
        with tempfile.TemporaryDirectory(prefix="willpdv_backup_nuvem_") as pasta:
            gz = Path(pasta) / "backup.db.gz"
            with open(arquivo, "rb") as origem, gzip.open(gz, "wb", compresslevel=6) as destino:
                shutil.copyfileobj(origem, destino, 1024 * 1024)
            dados = gz.read_bytes()
        feito_em = datetime.fromtimestamp(arquivo.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        r = http.post(f"{base}/v1/backup", data=dados, timeout=(5, 180), headers={
            **cabecalho, "Content-Type": "application/gzip", "X-Backup-Feito-Em": feito_em,
            "X-Backup-Esquema": str(_esquema(arquivo)), "X-Backup-Sha256": hashlib.sha256(dados).hexdigest()})
    except OSError as e:
        banco.cfg_set(CHAVE_ERRO, f"{fmt.agora()} sem conexão com a nuvem")
        log.warning("Backup na nuvem: %s", e)
        return False
    if r.status_code == 404:
        return False                                     # nuvem antiga: tenta de novo em outra rodada
    if r.status_code != 200:
        banco.cfg_set(CHAVE_ERRO, f"{fmt.agora()} a nuvem respondeu HTTP {r.status_code}")
        return False
    banco.cfg_set(CHAVE_ULTIMO, fmt.agora())
    banco.cfg_set(CHAVE_ARQUIVO, arquivo.name)
    banco.cfg_set(CHAVE_ERRO, "")
    log.info("Backup na nuvem: %s (%d bytes)", arquivo.name, len(dados))
    return True


def situacao(banco) -> tuple[str, str]:
    """(nível, texto) para Utilitários."""
    if getattr(banco, "remoto", False):
        return "ok", "Caixa adicional: o backup na nuvem é feito pelo caixa principal."
    if not configurado(banco):
        return "sem", "Backup na nuvem desligado: este caixa não está ligado à nuvem."
    ultimo, erro = banco.cfg(CHAVE_ULTIMO), banco.cfg(CHAVE_ERRO)
    if not ultimo:
        return "aviso", "Backup na nuvem: ainda não enviado. " + (f"Último problema: {erro}." if erro else "")
    texto = f"Backup na nuvem: último enviado em {fmt.fmt_datahora(ultimo)}."
    return ("aviso", texto + f" Último problema: {erro}.") if erro else ("ok", texto)


def listar(banco, http=None) -> list[dict]:
    if not configurado(banco):
        raise ErroNegocio("Ligue este caixa à nuvem (código de instalação) para ver os backups da loja.")
    if http is None:
        import requests as http
    base, cabecalho = _base(banco)
    try:
        r = http.get(f"{base}/v1/backup/lista", headers=cabecalho, timeout=(5, 30))
    except OSError as e:
        raise ErroNegocio("Sem conexão com a nuvem.") from e
    if r.status_code != 200:
        raise ErroNegocio(f"A nuvem não listou os backups (HTTP {r.status_code}).")
    return [b for b in (r.json().get("backups") or []) if isinstance(b, dict)]


def _manter_instalacao(banco, recuperado: Path) -> None:
    """Grava no banco recuperado o endereço, o token e a licença desta instalação (o código de instalação novo)."""
    valores = {c: banco.cfg(c) for c in CHAVES_DA_INSTALACAO if (banco.cfg(c) or "").strip()}
    conexao = sqlite3.connect(recuperado)
    try:
        with conexao:
            for chave, valor in valores.items():
                conexao.execute("INSERT INTO config(chave, valor) VALUES (?, ?) "
                                "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor", (chave, valor))
    finally:
        conexao.close()


def restaurar(banco, backup_id: int, operador_id: int | None = None, http=None) -> str:
    """Baixa o backup da nuvem e marca a restauração para o próximo início. Devolve a data do backup."""
    from src.controllers.utilitario_controller import UtilitarioController
    from src.database import protecao
    from src.database import esquema
    if not configurado(banco):
        raise ErroNegocio("Ligue este caixa à nuvem (código de instalação) antes de recuperar o backup.")
    if http is None:
        import requests as http
    base, cabecalho = _base(banco)
    try:
        r = http.get(f"{base}/v1/backup/{int(backup_id)}", headers=cabecalho, timeout=(5, 300))
    except OSError as e:
        raise ErroNegocio("Sem conexão com a nuvem para baixar o backup.") from e
    if r.status_code != 200:
        raise ErroNegocio(f"A nuvem não entregou o backup (HTTP {r.status_code}).")
    dados = r.content
    if hashlib.sha256(dados).hexdigest() != (r.headers.get("X-Backup-Sha256") or "").lower():
        raise ErroNegocio("O backup chegou incompleto. Tente de novo.")
    util = UtilitarioController(banco, operador_id)
    try:
        with tempfile.TemporaryDirectory(prefix="willpdv_recuperar_nuvem_") as pasta:
            recuperado = Path(pasta) / "recuperado.db"
            with gzip.open(__import__("io").BytesIO(dados)) as origem, open(recuperado, "wb") as destino:
                shutil.copyfileobj(origem, destino, 1024 * 1024)
            if not protecao.backup_valido(recuperado):
                raise ErroNegocio("O backup da nuvem não é um banco válido do caixa.")
            if _esquema(recuperado) > esquema.VERSAO_ESQUEMA:
                raise ErroNegocio("Este backup é de uma versão mais nova do programa. Atualize e tente de novo.")
            _manter_instalacao(banco, recuperado)
            destino = util.pasta_backup()
            destino.mkdir(parents=True, exist_ok=True)
            local = destino / f"loja_offline-recuperado-nuvem-{uuid4().hex}.db"
            shutil.copyfile(recuperado, local)
    except (OSError, EOFError, sqlite3.Error) as e:
        raise ErroNegocio(f"Não foi possível preparar o backup da nuvem: {e}") from e
    try:
        util.pedir_restauracao(str(local))
    except BaseException:
        local.unlink(missing_ok=True)
        raise
    banco.log("backup_nuvem_restaurar", r.headers.get("X-Backup-Feito-Em", ""), operador_id)
    return r.headers.get("X-Backup-Feito-Em", "")
