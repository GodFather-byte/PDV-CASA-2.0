"""Instala a atualização sem pedir administrador ao operador.

O programa fica em "Arquivos de Programas", e o instalador do Windows exige administrador. O PDV roda sem esse poder:
disparado por ele, o instalador abria a janela "Deseja permitir que este app faça alterações?" e, sem ninguém para
clicar em Sim, a atualização falhava (e a restauração também, pelo mesmo motivo). Por isso:

1. Na instalação (feita uma vez, já como administrador), o instalador cria a tarefa agendada "<Programa> Atualizacao",
   que roda como SISTEMA e que qualquer usuário pode iniciar, mas não alterar (`instalador/tarefa_atualizacao.ps1`).
2. O PDV baixa e confere o pacote, grava o pedido em `%ProgramData%\\<Programa>\\atualizacao` e inicia a tarefa. Deixa
   rodando um script de espera (sem administrador) que reabre o programa quando sai o resultado.
3. A tarefa roda `<Programa>.exe --aplicar-atualizacao`, que confere tudo de novo (assinatura, edição, versão mais nova,
   tamanho e SHA-256), copia o instalador para uma pasta só do SISTEMA, guarda a cópia do programa e entrega a
   instalação ao script `aplicar.cmd` (instala, confirma a versão nova sem tocar no banco e restaura se falhar).

O pedido fica numa pasta que o usuário pode alterar: por isso o lado do SISTEMA não confia em nada dele além do que a
assinatura cobre. O único campo livre (`id`, que dá nome ao arquivo de resultado) é limitado a letras e números.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from src.atualizacao.manifesto import CAMPOS, conferir
from src.versao import VERSAO, mais_nova, valida

log = logging.getLogger("pdv.atualizacao")

PEDIDO = "pedido.json"
PACOTE = "pacote.exe"
ESPERA_MINUTOS = 25
_ID = re.compile(r"^[a-f0-9]{8,32}$")


class PedidoRecusado(Exception):
    pass


def congelado() -> bool:
    return bool(getattr(sys, "frozen", False))


def nome_programa() -> str:
    """WillPDV, WillAdega ou WillRestaurante: o nome do executável, que é o mesmo do instalador."""
    return Path(sys.executable).stem if congelado() else "WillPDV"


def nome_tarefa(programa: str | None = None) -> str:
    return f"{programa or nome_programa()} Atualizacao"


def pasta_pedidos(programa: str | None = None) -> Path:
    base = os.environ.get("ProgramData") or r"C:\ProgramData"
    return Path(base) / (programa or nome_programa()) / "atualizacao"


def arquivo_resultado(pasta: Path, ident: str) -> Path:
    return pasta / f"resultado-{ident}.txt"


def _sha256(caminho: Path) -> str:
    from src.atualizacao.cliente import sha256_arquivo
    return sha256_arquivo(caminho)


# ------------------------------------------------------------------ lado do operador (sem administrador)
def preparar_pedido(arquivo: Path, pacote: dict, pasta: Path | None = None) -> tuple[Path, str]:
    """Copia o instalador conferido e o pacote assinado para a pasta da tarefa. Devolve (pasta, id do pedido)."""
    pasta = pasta or pasta_pedidos()
    pasta.mkdir(parents=True, exist_ok=True)
    ident = secrets.token_hex(8)
    for antigo in pasta.glob("resultado-*.txt"):
        antigo.unlink(missing_ok=True)
    temporario = pasta / (PACOTE + ".parcial")
    shutil.copyfile(arquivo, temporario)
    temporario.replace(pasta / PACOTE)
    dados = {campo: pacote[campo] for campo in CAMPOS}
    dados["assinatura"] = pacote["assinatura"]
    dados["id"] = ident
    (pasta / PEDIDO).write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return pasta, ident


def script_espera(pasta: Path, ident: str, programa: Path, exe: str, minutos: int = ESPERA_MINUTOS) -> str:
    """Espera o resultado da tarefa e reabre o programa (como o operador, não como SISTEMA)."""
    def q(caminho: Path) -> str:
        return str(caminho).replace('"', "").replace("%", "%%")
    resultado = arquivo_resultado(pasta, ident)
    voltas = max(int(minutos * 60 / 5), 1)
    return "\r\n".join([
        "@echo off", "setlocal DisableDelayedExpansion",
        f"for /L %%i in (1,1,{voltas}) do (",
        f'  if exist "{q(resultado)}" goto reabrir',
        "  ping -n 6 127.0.0.1 >nul",
        ")",
        ":reabrir",
        f'start "" "{q(programa / exe)}"',
        f'start "" "{q(programa / exe)}" --sync',
        "exit /b 0",
    ]) + "\r\n"


def pedir_ao_windows(executar=subprocess.run, programa: str | None = None) -> bool:
    """Inicia a tarefa do SISTEMA. Falso se ela não existe (instalação antiga) ou o Windows recusou."""
    try:
        r = executar(["schtasks", "/Run", "/TN", nome_tarefa(programa)], capture_output=True, text=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, ValueError) as erro:
        log.info("Atualização: tarefa do Windows indisponível (%s).", erro)
        return False
    if r.returncode != 0:
        log.info("Atualização: a tarefa do Windows não iniciou (%s).", (r.stderr or r.stdout or "").strip()[:200])
        return False
    return True


# ------------------------------------------------------------------ lado do SISTEMA (tarefa agendada)
def ler_pedido(pasta: Path, versao_instalada: str, edicao: str, publica_hex: str | None = None) -> dict:
    """Confere tudo o que veio da pasta aberta ao usuário. Lança PedidoRecusado com o motivo."""
    try:
        pedido = json.loads((pasta / PEDIDO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PedidoRecusado("sem pedido válido") from None
    if not isinstance(pedido, dict) or not _ID.match(str(pedido.get("id") or "")):
        raise PedidoRecusado("pedido sem identificação")
    if not (conferir(pedido, publica_hex) if publica_hex else conferir(pedido)):
        raise PedidoRecusado("assinatura inválida")
    if pedido["edicao"] != edicao:
        raise PedidoRecusado(f"pacote de outra edição ({pedido['edicao']})")
    if not valida(str(pedido["versao"])) or not mais_nova(pedido["versao"], versao_instalada):
        raise PedidoRecusado(f"a versão {pedido['versao']} não é mais nova que a instalada ({versao_instalada})")
    pacote = pasta / PACOTE
    if not pacote.is_file() or pacote.stat().st_size != int(pedido["tamanho"]) \
            or _sha256(pacote).lower() != str(pedido["sha256"]).lower():
        raise PedidoRecusado("o instalador não confere com o pacote assinado")
    return pedido


def preparar_aplicacao(pasta: Path, programa: Path, exe: str, versao_instalada: str, edicao: str,
                       publica_hex: str | None = None, temporaria: Path | None = None) -> tuple[Path, str]:
    """Confere o pedido, copia o instalador para uma pasta só do SISTEMA, guarda a cópia do programa e grava o script.
    Devolve (script, id). Lança PedidoRecusado (o resultado já fica gravado com o motivo)."""
    ident = "recusado"
    try:
        bruto = json.loads((pasta / PEDIDO).read_text(encoding="utf-8"))
        if isinstance(bruto, dict) and _ID.match(str(bruto.get("id") or "")):
            ident = bruto["id"]
    except (OSError, ValueError):
        pass
    try:
        pedido = ler_pedido(pasta, versao_instalada, edicao, publica_hex)
        destino = temporaria or Path(tempfile.mkdtemp(prefix="atualizacao-"))
        copia = destino / f"{edicao}-{pedido['versao']}.exe"
        shutil.copyfile(pasta / PACOTE, copia)
        if _sha256(copia).lower() != str(pedido["sha256"]).lower():       # trocado entre a conferência e a cópia
            raise PedidoRecusado("o instalador mudou durante a cópia")
    except PedidoRecusado as erro:
        pasta.mkdir(parents=True, exist_ok=True)
        arquivo_resultado(pasta, ident).write_text(f"recusada: {erro}\n", encoding="utf-8")
        raise
    backup = destino / "anterior"
    if programa.is_dir():
        shutil.copytree(programa, backup)
    else:
        backup.mkdir(parents=True, exist_ok=True)
    from src.atualizacao.cliente import script_aplicar
    script = destino / "aplicar.cmd"
    texto = script_aplicar(copia, programa, backup, exe, pedido["versao"], reabrir=False,
                           resultado=arquivo_resultado(pasta, ident), log_instalador=pasta / "instalador.log")
    script.write_text(texto, encoding="utf-8", newline="")
    for nome in (PEDIDO, PACOTE):                                        # o pedido foi consumido
        (pasta / nome).unlink(missing_ok=True)
    return script, ident


def aplicar_como_sistema(publica_hex: str | None = None) -> int:
    """`<Programa>.exe --aplicar-atualizacao`, chamado pela tarefa agendada. Não abre banco nem janela."""
    from src.core import edicao
    if not congelado() or os.name != "nt":
        log.info("Atualização pela tarefa só roda no programa instalado no Windows.")
        return 2
    programa = Path(sys.executable).resolve().parent
    try:
        script, _ = preparar_aplicacao(pasta_pedidos(), programa, Path(sys.executable).name, VERSAO,
                                       edicao.atual().chave, publica_hex)
    except PedidoRecusado as erro:
        log.warning("Atualização recusada pela tarefa: %s.", erro)
        return 1
    except Exception:
        log.exception("A tarefa não conseguiu preparar a atualização.")
        return 1
    # O instalador encerra todos os <Programa>.exe, inclusive este: quem instala e confere é o cmd, separado.
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
    return 0
