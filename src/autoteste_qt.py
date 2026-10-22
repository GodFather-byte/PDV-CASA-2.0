"""Autoteste isolado da interface Qt: não usa o banco da loja."""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path


def _backup_seguro(pasta: Path) -> str:
    from src.controllers.utilitario_controller import UtilitarioController
    from src.database.conexao import BancoDados
    banco = BancoDados(str(pasta / "backup-teste.db"))
    try:
        util = UtilitarioController(banco)
        banco.cfg_set("pasta_backup", str(pasta / "local"))
        senha = "senha-ficticia-apenas-autoteste"
        if sys.platform == "win32":
            util.configurar_backup_externo(str(pasta / "externo"), senha)
            arquivo = util.backup_externo()
        else:
            banco.cfg_set("backup_externo_pasta", str(pasta / "externo"))
            arquivo = util.backup_externo(senha=senha)
        util.verificar_backup_externo(arquivo, senha)
    finally:
        banco.fechar()
    return "backup criptografado gerado e recuperado; cofre DPAPI conferido no Windows"


def executar(saida: str | None = None) -> int:
    from src.versao import VERSAO
    linhas = [f"WillPDV {VERSAO} — autoteste Qt"]
    resultado = 0
    try:
        from src.ui_qt.app import autoteste
        with tempfile.TemporaryDirectory(prefix="willpdv_autoteste_qt_") as pasta:
            linhas.extend(f"OK    Qt: {texto}" for texto in autoteste(Path(pasta)))
            linhas.append(f"OK    backup: {_backup_seguro(Path(pasta))}")
    except Exception as e:
        resultado = 1
        linhas.append(f"FALHA Qt: {type(e).__name__}: {e}")
        linhas.extend(traceback.format_exc().splitlines()[-8:])
    linhas.append("RESULTADO: TUDO CERTO" if resultado == 0 else "RESULTADO: COM FALHAS")
    texto = "\n".join(linhas) + "\n"
    if saida is not None:
        Path(saida).write_text(texto, encoding="utf-8")
    if sys.stdout is not None:
        print(texto, end="")
    return resultado
