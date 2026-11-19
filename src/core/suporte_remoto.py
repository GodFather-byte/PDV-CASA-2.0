"""Suporte remoto pelo RustDesk: achar o programa, ler o ID deste computador e abrir a janela dele.

O PDV não instala nem configura o RustDesk, não lê nem guarda senha e não aceita conexão sozinho. Só abre o programa que
a loja instalou e mostra o ID para passar ao suporte. Quem libera a conexão é quem está na frente do caixa, na janela do
próprio RustDesk.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

SITE = "https://rustdesk.com/"
CHAVE_ID = "rustdesk_id"                # último ID lido neste computador ("id|computador"): vai no retrato da central
TEMPO_LIMITE = 4                        # segundos para o RustDesk responder o ID
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{5,31}")     # 9 ou 10 dígitos; ID escolhido pelo dono começa com letra


def candidatos(configurado: str = "") -> list[Path]:
    """Onde o RustDesk pode estar, na ordem de procura. `configurado` é o Programa de comunicação das Configurações:
    vale quando aponta para o RustDesk (é assim que a versão portátil, sem instalar, é encontrada)."""
    achados = []
    if configurado.strip() and "rustdesk" in Path(configurado.strip()).name.lower():
        achados.append(Path(configurado.strip()))
    for variavel in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        pasta = os.environ.get(variavel)
        if pasta:
            achados.append(Path(pasta) / "RustDesk" / "rustdesk.exe")
    no_caminho = shutil.which("rustdesk")
    if no_caminho:
        achados.append(Path(no_caminho))
    return achados


def localizar(configurado: str = "") -> Path | None:
    """O executável do RustDesk, ou None se não está neste computador."""
    return next((caminho for caminho in candidatos(configurado) if caminho.is_file()), None)


def id_valido(texto: str) -> str:
    """O ID sem espaços, ou "" se o texto não tem cara de ID do RustDesk."""
    limpo = "".join(str(texto or "").split())
    return limpo if _ID.fullmatch(limpo) else ""


def formatar_id(id_: str) -> str:
    """Como o RustDesk mostra: números em grupos de três (123 456 789). ID com letra fica como está."""
    if not id_.isdigit():
        return id_
    grupos = []
    while id_:
        grupos.append(id_[-3:])
        id_ = id_[:-3]
    return " ".join(reversed(grupos))


def ler_id(executavel: Path) -> str:
    """Pergunta o ID ao próprio RustDesk (`--get-id`). "" se ele não respondeu a tempo ou respondeu outra coisa.

    No Windows o RustDesk só escreve a resposta quando a saída está ligada a um cano, que é o caso aqui."""
    opcoes = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        saida = subprocess.run([str(executavel), "--get-id"], capture_output=True, text=True, timeout=TEMPO_LIMITE,
                               stdin=subprocess.DEVNULL, **opcoes).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""
    linhas = [linha for linha in (saida or "").splitlines() if linha.strip()]
    return id_valido(linhas[-1]) if linhas else ""


def abrir(executavel: Path) -> None:
    """Abre a janela do RustDesk (se já estava aberto, ele mesmo traz a janela para a frente)."""
    subprocess.Popen([str(executavel)])


def guardar_id(banco, id_: str) -> None:
    """Guarda o ID lido junto com o nome deste computador: se o banco for restaurado em outra máquina, o ID velho
    não vale mais."""
    valor = f"{id_}|{socket.gethostname()}" if id_valido(id_) else ""
    if banco.cfg(CHAVE_ID) != valor:
        banco.cfg_set(CHAVE_ID, valor)


def id_guardado(banco) -> str:
    """O último ID lido NESTE computador, para a central do fornecedor ("" se nunca leu ou o banco veio de outro)."""
    id_, _, computador = banco.cfg(CHAVE_ID).strip().partition("|")
    return id_valido(id_) if computador and computador == socket.gethostname() else ""
