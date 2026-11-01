"""Baixa e aplica a atualização assinada. Não instala com venda, mesa ou comanda aberta.

Os dados ficam fora da pasta do programa (%LOCALAPPDATA%). O instalador Inno atualiza só o
programa. Se a versão nova não confirmar a subida, o script restaura a cópia anterior.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from src.atualizacao.manifesto import conferir
from src.core import edicao, formatacao as fmt
from src.versao import VERSAO, chave, mais_nova, valida

log = logging.getLogger("pdv.atualizacao")

INTERVALO_HORAS = 6
CANAL = "estavel"
CHAVE_CONSULTA = "atualizacao_pacote_em"
CHAVE_ESTADO = "atualizacao_pacote"
CHAVE_ADIADA = "atualizacao_adiada"
CHAVE_ADIADA_ATE = "atualizacao_adiada_ate"


def url_ultima(api_url: str) -> str:
    base = (api_url or "").strip().rstrip("/")
    if base.endswith("/v1/sincronizar"):
        base = base[: -len("/v1/sincronizar")]
    return f"{base}/v1/atualizacao/ultima"


def url_absoluta(api_url: str, url: str) -> str:
    if url.startswith(("https://", "http://")):
        return url
    base = (api_url or "").strip().rstrip("/")
    if base.endswith("/v1/sincronizar"):
        base = base[: -len("/v1/sincronizar")]
    return base + (url if url.startswith("/") else "/" + url)


def edicao_atual() -> str:
    return edicao.atual().chave


def caixa_ocupado(banco) -> str | None:
    """Venda de balcão, mesa ou comanda ainda aberta: não é hora de trocar o programa."""
    abertas = banco.valor(
        "SELECT COUNT(*) FROM vendas WHERE status IN ('aberta', 'conta_enviada')", (), 0)
    if abertas:
        return "há venda, mesa ou comanda aberta"
    return None


def abaixo_da_minima(instalada: str, minima: str) -> bool:
    if not (minima or "").strip():
        return False
    try:
        return chave(instalada) < chave(minima)
    except ValueError:
        return False


def adiada(banco, versao: str, agora: str | None = None) -> bool:
    if banco.cfg(CHAVE_ADIADA) != versao:
        return False
    ate = banco.cfg(CHAVE_ADIADA_ATE)
    agora = agora or fmt.agora()
    return bool(ate) and ate > agora


def adiar(banco, versao: str, horas: int = 24) -> None:
    from datetime import datetime, timedelta
    banco.cfg_set(CHAVE_ADIADA, versao)
    banco.cfg_set(CHAVE_ADIADA_ATE, (datetime.now() + timedelta(hours=horas)).strftime("%Y-%m-%d %H:%M:%S"))


def pacote_valido(dados: dict, publica_hex: str | None = None) -> bool:
    if not isinstance(dados, dict) or not dados.get("disponivel"):
        return False
    pacote = dados.get("pacote")
    if not isinstance(pacote, dict) or not valida(str(pacote.get("versao") or "")):
        return False
    minima = str(pacote.get("minima") or "")
    if minima and not valida(minima):
        return False
    return conferir(pacote, publica_hex) if publica_hex else conferir(pacote)


def consultar(api_url: str, http, edicao_nome: str | None = None, canal: str = CANAL, versao: str = VERSAO) -> dict | None:
    if not (api_url or "").strip() or http is None:
        return None
    try:
        resposta = http.get(url_ultima(api_url), params={
            "edicao": edicao_nome or edicao_atual(), "canal": canal, "versao": versao,
        }, timeout=(5, 20))
    except (OSError, ValueError, AttributeError) as erro:
        log.info("Atualização: sem resposta da nuvem (%s).", erro)
        return None
    if getattr(resposta, "status_code", None) != 200:
        return None
    try:
        dados = resposta.json()
    except (ValueError, AttributeError):
        return None
    return dados if isinstance(dados, dict) else None


def sha256_arquivo(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        while True:
            bloco = arquivo.read(1024 * 1024)
            if not bloco:
                break
            digest.update(bloco)
    return digest.hexdigest()


def baixar(url: str, destino: Path, sha256: str, tamanho: int, http) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(destino.suffix + ".parcial")
    resposta = http.get(url, timeout=(5, 120))
    if getattr(resposta, "status_code", None) != 200:
        raise RuntimeError(f"Download HTTP {getattr(resposta, 'status_code', '?')}.")
    dados = resposta.content
    with temporario.open("wb") as arquivo:
        arquivo.write(dados)
    if temporario.stat().st_size != int(tamanho) or sha256_arquivo(temporario).lower() != sha256.lower():
        temporario.unlink(missing_ok=True)
        raise RuntimeError("O arquivo baixado não confere com o tamanho ou o SHA-256.")
    temporario.replace(destino)


def copiar_instalacao(origem: Path, backup: Path) -> None:
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(origem, backup)


def script_aplicar(instalador: Path, programa: Path, backup: Path, exe: str) -> str:
    """Script que o Windows roda depois que este processo sai: instala, confirma e restaura se falhar."""
    def q(caminho: Path) -> str:
        return str(caminho).replace('"', "")
    return "\r\n".join([
        "@echo off",
        f'start /wait "" "{q(instalador)}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-',
        f'"{q(programa / exe)}" --confirmar-atualizacao',
        "if errorlevel 1 (",
        f'  xcopy /E /Y /I "{q(backup)}\\*" "{q(programa)}\\"',
        f'  start "" "{q(programa / exe)}"',
        ") else (",
        f'  start "" "{q(programa / exe)}"',
        f'  start "" "{q(programa / exe)}" --sync',
        ")",
    ]) + "\r\n"


def estado(banco) -> dict:
    try:
        dados = json.loads(banco.cfg(CHAVE_ESTADO) or "{}")
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar_estado(banco, dados: dict) -> None:
    banco.cfg_set(CHAVE_ESTADO, json.dumps(dados, ensure_ascii=False))


def precisa_consultar(banco) -> bool:
    ultima = banco.cfg(CHAVE_CONSULTA)
    return not ultima or fmt.minutos_entre(ultima) >= INTERVALO_HORAS * 60 or fmt.minutos_entre(ultima) < 0


def rodada(banco, http=None, forcar: bool = False, instalar=None, publica_hex: str | None = None) -> dict:
    """Consulta, baixa e, se o caixa estiver livre, dispara a instalação. Devolve o que fez."""
    if not banco.cfg("api_url").strip():
        return {"acao": "sem_nuvem"}
    if forcar or precisa_consultar(banco):
        dados = consultar(banco.cfg("api_url"), http)
        banco.cfg_set(CHAVE_CONSULTA, fmt.agora())
        if dados is None or not pacote_valido(dados, publica_hex):
            return {"acao": "sem_pacote" if not dados else "assinatura_invalida"}
        pacote = dados["pacote"]
        if not mais_nova(pacote["versao"], VERSAO):
            _gravar_estado(banco, {})
            return {"acao": "em_dia"}
        guardado = estado(banco)
        destino = Path(guardado.get("arquivo") or "")
        if guardado.get("versao") != pacote["versao"] or not destino.is_file():
            pasta = Path(banco.caminho).resolve().parent / "atualizacao"
            destino = pasta / f"{pacote['edicao']}-{pacote['versao']}.exe"
            baixar(url_absoluta(banco.cfg("api_url"), pacote["url"]), destino, pacote["sha256"], int(pacote["tamanho"]), http)
        _gravar_estado(banco, {"versao": pacote["versao"], "arquivo": str(destino), "obrigatoria": bool(pacote.get("obrigatoria")),
                               "minima": pacote.get("minima") or "", "notas": pacote.get("notas") or ""})
    else:
        pacote = None
    atual = estado(banco)
    if not atual.get("versao") or not mais_nova(atual["versao"], VERSAO):
        return {"acao": "em_dia"}
    forcada = bool(atual.get("obrigatoria")) or abaixo_da_minima(VERSAO, atual.get("minima") or "")
    if not forcada and adiada(banco, atual["versao"]):
        return {"acao": "adiada", "versao": atual["versao"]}
    motivo = caixa_ocupado(banco)
    if motivo:
        return {"acao": "esperar", "versao": atual["versao"], "motivo": motivo}
    if instalar is not None:
        instalar(Path(atual["arquivo"]))
    return {"acao": "instalar", "versao": atual["versao"], "arquivo": atual["arquivo"]}


def aviso(banco) -> dict | None:
    atual = estado(banco)
    if not atual.get("versao") or not mais_nova(atual["versao"], VERSAO):
        return None
    forcada = bool(atual.get("obrigatoria")) or abaixo_da_minima(VERSAO, atual.get("minima") or "")
    return {"ultima": atual["versao"], "notas": atual.get("notas") or "", "obrigatoria": forcada,
            "adiavel": not forcada, "motivo": caixa_ocupado(banco)}


def disparar_instalacao(arquivo: Path) -> Path:
    """Grava o script e, no programa instalado (Windows), deixa ele rodar depois que este processo sai."""
    import sys
    congelado = bool(getattr(sys, "frozen", False))
    programa = Path(sys.executable).resolve().parent if congelado else Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "WillPDV"
    exe = Path(sys.executable).name if congelado else "WillPDV.exe"
    backup = arquivo.parent / "anterior"
    if congelado and programa.is_dir():
        copiar_instalacao(programa, backup)
    else:
        backup.mkdir(parents=True, exist_ok=True)
    script = arquivo.parent / "aplicar.cmd"
    script.write_text(script_aplicar(arquivo, programa, backup, exe), encoding="utf-8")
    if congelado and os.name == "nt":
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0), close_fds=True)
    return script


def ao_iniciar() -> None:
    """Na abertura: se o arquivo já foi conferido e o caixa está livre, instala. Não baixa de novo aqui."""
    from src.database.conexao import BancoDados
    try:
        banco = BancoDados()
    except Exception:
        return
    try:
        if estado(banco).get("arquivo"):
            rodada(banco, http=None, instalar=disparar_instalacao)
    except Exception:
        log.exception("Não consegui retomar a atualização na abertura.")
    finally:
        banco.fechar()


def confirmar_atualizacao(esperada: str | None = None) -> int:
    """A versão nova confirma que subiu. Código 1 pede ao script para restaurar a cópia anterior."""
    from src.database.conexao import BancoDados
    try:
        banco = BancoDados()
        banco.valor("SELECT 1")
        if esperada and esperada != VERSAO:
            return 1
        banco.cfg_set("atualizacao_confirmada", VERSAO)
        banco.fechar()
    except Exception:
        log.exception("A versão nova não confirmou a subida.")
        return 1
    return 0
