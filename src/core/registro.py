"""Registro de erros em arquivo (logs/pdv.log) e pacote de suporte para o fornecedor.

Um erro inesperado nunca pode sumir sem rastro nem derrubar o caixa: ele é gravado com o traceback completo e o
operador vê uma mensagem clara. O pacote de suporte leva só os logs e dados da máquina, NUNCA o banco de vendas.
"""
from __future__ import annotations

import logging
import logging.handlers
import platform
import sys
import threading
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

from src.versao import VERSAO

log = logging.getLogger("pdv")
_configurado = False


def pasta_logs() -> Path:
    from src.database.conexao import RAIZ
    return RAIZ / "logs"


def configurar_logs(pasta: Path | None = None) -> Path:
    """Liga o arquivo de log e captura as exceções que ninguém tratou (programa e threads). Idempotente."""
    global _configurado
    pasta = pasta or pasta_logs()
    arquivo = pasta / "pdv.log"
    if _configurado:
        return arquivo
    pasta.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(arquivo, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(handler)
    if log.level == logging.NOTSET or log.level > logging.INFO:
        log.setLevel(logging.INFO)
    sys.excepthook = _excecao_nao_tratada
    threading.excepthook = lambda a: registrar_excecao(a.exc_type, a.exc_value, a.exc_traceback, f"thread {a.thread and a.thread.name}")
    _configurado = True
    log.info("PDV %s iniciado (Python %s, %s).", VERSAO, platform.python_version(), platform.platform())
    return arquivo


def registrar_excecao(tipo, valor, tb, origem: str = "") -> None:
    texto = "".join(traceback.format_exception(tipo, valor, tb))
    log.error("Erro inesperado%s:\n%s", f" ({origem})" if origem else "", texto)


def _excecao_nao_tratada(tipo, valor, tb) -> None:
    if issubclass(tipo, KeyboardInterrupt):
        sys.__excepthook__(tipo, valor, tb)
        return
    registrar_excecao(tipo, valor, tb, "não tratado")


def pacote_suporte(destino: Path, pasta: Path | None = None) -> Path:
    """Zip com os logs e um resumo da máquina, para o dono mandar ao fornecedor. Não inclui o banco."""
    pasta = pasta or pasta_logs()
    destino.mkdir(parents=True, exist_ok=True)
    zip_path = destino / f"suporte-{datetime.now():%Y%m%d-%H%M%S}.zip"
    resumo = (f"WillPDV {VERSAO}\nPython {platform.python_version()}\nSistema {platform.platform()}\n"
              f"Gerado em {datetime.now():%d/%m/%Y %H:%M:%S}\n")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("resumo.txt", resumo)
        for p in sorted(pasta.glob("*.log*")) if pasta.exists() else []:
            z.write(p, f"logs/{p.name}")
    return zip_path
