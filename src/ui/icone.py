"""Ícone do WillPDV nas janelas (barra de título e barra de tarefas). Só no Windows; qualquer falha é ignorada."""
from __future__ import annotations

import sys
from pathlib import Path


def caminho(nome: str = "willpdv.ico") -> Path | None:
    """O .ico: dentro do executável (PyInstaller o põe na pasta temporária `_MEIPASS`) ou em `instalador/` no código-fonte."""
    base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2] / "instalador"
    arquivo = base / nome
    return arquivo if arquivo.is_file() else None


def aplicar(raiz, nome: str = "willpdv.ico") -> bool:
    """Põe o ícone em `raiz` e em todas as janelas filhas. Devolve se conseguiu."""
    if sys.platform != "win32":
        return False                         # o Tk de Linux/Mac não lê .ico
    arquivo = caminho(nome)
    if arquivo is None:
        return False
    try:
        raiz.iconbitmap(default=str(arquivo))
        return True
    except Exception:  # noqa: BLE001 - ícone é enfeite: nunca pode impedir o caixa de abrir
        return False
