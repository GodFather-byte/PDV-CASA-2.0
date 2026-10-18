"""Uma só janela do PDV por banco: duas abertas ao mesmo tempo poderiam repetir cupom ou travar o banco."""
from __future__ import annotations

import os
from pathlib import Path


class InstanciaUnica:
    """Trava um arquivo ao lado do banco enquanto o programa roda. O sistema operacional solta a trava sozinho se o
    programa cair, então não sobra "trava velha" depois de uma queda de energia."""

    def __init__(self, caminho_db: str | Path):
        self.arquivo = Path(str(caminho_db) + ".lock")
        self._f = None

    def adquirir(self) -> bool:
        try:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            f = open(self.arquivo, "a+b")
        except OSError:
            return True              # sem permissão para a trava: não impede de vender
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._f = f
        return True

    def liberar(self) -> None:
        f, self._f = self._f, None
        if f is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            f.close()
        except OSError:
            pass
