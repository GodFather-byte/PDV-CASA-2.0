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
RETENTAR_MINUTOS = 15             # nuvem sem resposta (o Render acorda devagar): tenta de novo logo, não em 6 horas
OCIOSO_MINUTOS = 10               # instalação automática só com o turno fechado há este tempo
CANAL = "estavel"
CHAVE_CONSULTA = "atualizacao_pacote_em"
CHAVE_ESTADO = "atualizacao_pacote"
CHAVE_ADIADA = "atualizacao_adiada"
CHAVE_ADIADA_ATE = "atualizacao_adiada_ate"
CHAVE_TENTATIVA = "atualizacao_tentativa"
CHAVE_FALHA_CONSULTA = "atualizacao_consulta_falhou_em"
CHAVE_RESULTADO = "atualizacao_resultado"        # JSON {versao, situacao, detalhe, em}: o que houve na última tentativa
FALHAS = ("nao_iniciada", "nao_confirmada", "recusada", "restaurada", "falha_na_restauracao")


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


def motivo_automatico(banco, agora=None) -> str | None:
    """Sem o operador pedir, o programa só fecha para instalar com a loja parada: sem venda aberta, sem turno aberto,
    sem impressão na fila e com o último turno fechado há pelo menos OCIOSO_MINUTOS (o fechamento ainda imprime)."""
    motivo = caixa_ocupado(banco)
    if motivo:
        return motivo
    if banco.valor("SELECT COUNT(*) FROM turnos WHERE status = 'aberto'", (), 0):
        return "há turno aberto; a atualização automática aguarda o fechamento"
    if banco.valor("SELECT COUNT(*) FROM fila_impressao WHERE status IN ('pendente', 'enviando')", (), 0):
        return "há impressão na fila"
    fechado = banco.valor("SELECT MAX(fechado_em) FROM turnos WHERE fechado_em IS NOT NULL", (), None)
    if fechado:
        minutos = fmt.minutos_entre(fechado, agora)
        if 0 <= minutos < OCIOSO_MINUTOS:
            return f"o turno fechou há pouco; instala {OCIOSO_MINUTOS} minutos depois do fechamento"
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


def pacote_valido(dados: dict, publica_hex: str | None = None, edicao_nome: str | None = None) -> bool:
    if not isinstance(dados, dict) or not dados.get("disponivel"):
        return False
    pacote = dados.get("pacote")
    if not isinstance(pacote, dict) or not valida(str(pacote.get("versao") or "")):
        return False
    if pacote.get("edicao") != (edicao_nome or edicao_atual()):     # nunca instala o programa de outra edição
        return False
    minima = str(pacote.get("minima") or "")
    if minima and not valida(minima):
        return False
    return conferir(pacote, publica_hex) if publica_hex else conferir(pacote)


def sem_pacote(dados: dict | None) -> str:
    """Por que a resposta da nuvem não trouxe pacote para instalar (o que vai para o diagnóstico)."""
    if dados is None:
        return "sem_resposta"
    if dados.get("pausada"):
        return "pausada"
    if dados.get("instalacao_manual_necessaria"):
        return "instalacao_manual_necessaria"
    if not dados.get("disponivel") or not isinstance(dados.get("pacote"), dict):
        return "em_dia"
    if dados["pacote"].get("edicao") != edicao_atual():
        return "outra_edicao"
    return "assinatura_invalida"


def consultar(api_url: str, http, edicao_nome: str | None = None, canal: str = CANAL, versao: str = VERSAO,
              loja: str = "") -> dict | None:
    """`loja` (a chave da loja) só serve para a nuvem liberar a versão a lojas piloto enquanto as outras esperam."""
    if not (api_url or "").strip() or http is None:
        return None
    parametros = {"edicao": edicao_nome or edicao_atual(), "canal": canal, "versao": versao}
    if (loja or "").strip():
        parametros["loja"] = loja.strip()[:64]
    try:
        resposta = http.get(url_ultima(api_url), params=parametros, timeout=(10, 60))                    # o Render pode levar perto de um minuto para acordar
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


def script_aplicar(instalador: Path, programa: Path, backup: Path, exe: str,
                   esperada: str = VERSAO, reabrir: bool = True, resultado: Path | None = None,
                   log_instalador: Path | None = None) -> str:
    """Confere saída e confirmação nova antes de reiniciar; não aceita confirmação de executável antigo.

    `reabrir=False` é o caso da tarefa do SISTEMA: não abre o programa (abriria invisível, como SISTEMA) e a
    confirmação não toca no banco (o banco é do operador); quem reabre é o script de espera do operador."""
    def q(caminho: Path) -> str:
        return str(caminho).replace('"', "").replace("%", "%%")
    confirmacao = instalador.parent / "confirmacao.txt"
    resultado = resultado or instalador.parent / "resultado.txt"
    log_instalador = log_instalador or instalador.parent / "instalador.log"
    sem_banco = "" if reabrir else " --sem-banco"
    abrir = [f'start "" "{q(programa / exe)}"', f'start "" "{q(programa / exe)}" --sync'] if reabrir else []
    abrir_restaurado = [f'start "" "{q(programa / exe)}"'] if reabrir else []
    return "\r\n".join([
        "@echo off", "chcp 65001 >nul", "setlocal DisableDelayedExpansion",
        f'if exist "{q(confirmacao)}" del /Q "{q(confirmacao)}"',
        f'if exist "{q(confirmacao)}" goto falha',
        "cmd /d /c exit 0",
        f'start /wait "" "{q(instalador)}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR="{q(programa)}" /LOG="{q(log_instalador)}"',
        "if errorlevel 1 goto restaurar",
        f'"{q(programa / exe)}" --confirmar-atualizacao "{esperada}" "{q(confirmacao)}"{sem_banco}',
        "if errorlevel 1 goto restaurar",
        f'if not exist "{q(confirmacao)}" goto restaurar',
        f'findstr /X /L /C:"{esperada}" < "{q(confirmacao)}" >nul',
        "if errorlevel 1 goto restaurar",
        f'echo instalada>"{q(resultado)}"',
        *abrir,
        "exit /b 0", ":restaurar",
        f'xcopy /E /Y /I "{q(backup)}\\*" "{q(programa)}\\"',
        "if errorlevel 1 goto falha",
        f'echo restaurada>"{q(resultado)}"',
        *abrir_restaurado,
        "exit /b 1", ":falha",
        f'echo falha_na_restauracao>"{q(resultado)}"',
        "exit /b 2",
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
    falhou = banco.cfg(CHAVE_FALHA_CONSULTA)
    if falhou and 0 <= fmt.minutos_entre(falhou) < RETENTAR_MINUTOS:
        return False
    ultima = banco.cfg(CHAVE_CONSULTA)
    if falhou and (not ultima or falhou > ultima):
        return True                                   # a última consulta não teve resposta: tenta de novo já
    return not ultima or fmt.minutos_entre(ultima) >= INTERVALO_HORAS * 60 or fmt.minutos_entre(ultima) < 0


def registrar_resultado(banco, versao: str, situacao: str, detalhe: str = "") -> None:
    banco.cfg_set(CHAVE_RESULTADO, json.dumps({"versao": versao, "situacao": situacao, "detalhe": detalhe[:200],
                                               "em": fmt.agora()}, ensure_ascii=False))


def ultimo_resultado(banco) -> dict:
    try:
        dados = json.loads(banco.cfg(CHAVE_RESULTADO) or "{}")
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def conferir_tentativa(banco) -> dict | None:
    """Na abertura: a tentativa anterior subiu? Se esta é a versão tentada, confirma e libera; se não, guarda o motivo
    (lido do resultado da tarefa) e devolve a situação, que aparece no menu e vai para a central."""
    tentativa = banco.cfg(CHAVE_TENTATIVA)
    if not tentativa:
        return None
    if tentativa == VERSAO or not mais_nova(tentativa, VERSAO):
        banco.cfg_set(CHAVE_TENTATIVA, "")
        banco.cfg_set("atualizacao_confirmada", VERSAO)
        registrar_resultado(banco, VERSAO, "instalada")
        return None
    anterior = ultimo_resultado(banco)
    if anterior.get("versao") == tentativa and anterior.get("situacao") in FALHAS:
        return anterior
    detalhe, situacao = "a versão nova não confirmou a subida", "nao_confirmada"
    from src.atualizacao import tarefa
    ident = (estado(banco).get("pedido") or anterior.get("pedido") or "")
    arquivo = tarefa.arquivo_resultado(tarefa.pasta_pedidos(), ident) if ident else None
    try:
        texto = arquivo.read_text(encoding="utf-8").strip() if arquivo and arquivo.is_file() else ""
    except OSError:
        texto = ""
    if texto.startswith("recusada"):
        situacao, detalhe = "recusada", texto.partition(":")[2].strip() or "o Windows recusou o pacote"
    elif texto == "restaurada":
        situacao, detalhe = "restaurada", "o instalador falhou e a versão anterior foi restaurada"
    elif texto == "falha_na_restauracao":
        situacao, detalhe = "falha_na_restauracao", "o instalador falhou e a restauração também; reinstale à mão"
    registrar_resultado(banco, tentativa, situacao, detalhe)
    return ultimo_resultado(banco)


def rodada(banco, http=None, forcar: bool = False, instalar=None, publica_hex: str | None = None,
           somente_local: bool = False) -> dict:
    """Serializa a atualização por banco, inclusive entre o aplicativo e o --sync."""
    from src.core.instancia import InstanciaUnica
    if getattr(banco, "remoto", False):
        return {"acao": "caixa_adicional"}
    caminho = getattr(banco, "caminho", ":memory:")
    trava = InstanciaUnica(str(caminho) + ".atualizacao") if caminho != ":memory:" else None
    if trava is not None and not trava.adquirir():
        return {"acao": "em_andamento"}
    try:
        return _rodada(banco, http, forcar, instalar, publica_hex, somente_local)
    finally:
        if trava is not None:
            trava.liberar()


def _rodada(banco, http=None, forcar: bool = False, instalar=None, publica_hex: str | None = None,
           somente_local: bool = False) -> dict:
    """Consulta, baixa e, se o caixa estiver livre, dispara a instalação. Devolve o que fez."""
    if not banco.cfg("api_url").strip():
        return {"acao": "sem_nuvem"}
    tentativa = banco.cfg(CHAVE_TENTATIVA)
    if tentativa and not forcar:
        return {"acao": "requer_conferencia", "versao": tentativa}
    if not somente_local and (forcar or precisa_consultar(banco)):
        if http is None:
            try:
                import requests as http
            except ImportError:
                return {"acao": "sem_cliente_http"}
        dados = consultar(banco.cfg("api_url"), http, loja=banco.cfg("chave_loja") or "")
        if dados is None:
            banco.cfg_set(CHAVE_FALHA_CONSULTA, fmt.agora())
            return {"acao": "sem_resposta"}
        banco.cfg_set(CHAVE_CONSULTA, fmt.agora())
        banco.cfg_set(CHAVE_FALHA_CONSULTA, "")
        if not pacote_valido(dados, publica_hex):
            return {"acao": sem_pacote(dados)}
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
        # O pacote assinado vai junto: a tarefa do SISTEMA confere de novo antes de instalar.
        destino.with_suffix(".json").write_text(json.dumps(pacote, ensure_ascii=False), encoding="utf-8")
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
    motivo = caixa_ocupado(banco) if forcar else motivo_automatico(banco)
    if motivo:
        return {"acao": "esperar", "versao": atual["versao"], "motivo": motivo}
    if instalar is not None:
        # Consome o pendente antes de fechar o processo. Uma cópia restaurada não pode repetir a instalação na abertura.
        with banco.transacao():
            banco.cfg_set(CHAVE_TENTATIVA, atual["versao"])
            registrar_resultado(banco, atual["versao"], "em_andamento")
            _gravar_estado(banco, {})
        try:
            pedido = instalar(Path(atual["arquivo"]))
        except Exception as erro:
            with banco.transacao():           # não repete sozinho: fica visível até alguém conferir
                registrar_resultado(banco, atual["versao"], "nao_iniciada", str(erro))
                _gravar_estado(banco, atual)
            raise
        if isinstance(pedido, str) and pedido:
            dados_resultado = ultimo_resultado(banco)
            dados_resultado["pedido"] = pedido
            banco.cfg_set(CHAVE_RESULTADO, json.dumps(dados_resultado, ensure_ascii=False))
    return {"acao": "instalar", "versao": atual["versao"], "arquivo": atual["arquivo"]}


def falha_pendente(banco) -> dict | None:
    """Tentativa que não subiu: a atualização automática fica parada até alguém conferir (botão Tentar de novo)."""
    tentativa = banco.cfg(CHAVE_TENTATIVA)
    if not tentativa or not mais_nova(tentativa, VERSAO):
        return None
    dados = ultimo_resultado(banco)
    return dados if dados.get("versao") == tentativa and dados.get("situacao") in FALHAS else None


def aviso(banco) -> dict | None:
    falha = falha_pendente(banco)
    if falha:
        return {"ultima": falha["versao"], "notas": "", "obrigatoria": False, "adiavel": False, "falha": True,
                "motivo": f"a atualização não foi concluída: {falha.get('detalhe') or falha.get('situacao')}. "
                          "Abra Atualizações do programa e use Instalar com o caixa livre."}
    atual = estado(banco)
    if not atual.get("versao") or not mais_nova(atual["versao"], VERSAO):
        return None
    forcada = bool(atual.get("obrigatoria")) or abaixo_da_minima(VERSAO, atual.get("minima") or "")
    return {"ultima": atual["versao"], "notas": atual.get("notas") or "", "obrigatoria": forcada,
            "adiavel": not forcada, "motivo": motivo_automatico(banco)}


def disparar_instalacao(arquivo: Path):
    """Entrega a instalação à tarefa do SISTEMA (sem a janela de administrador). Devolve o id do pedido.
    Instalação antiga, sem a tarefa: cai no caminho de antes, que pede administrador ao Windows."""
    import sys
    if not arquivo.is_file():
        raise RuntimeError("Instalador não encontrado. Baixe o pacote novamente.")
    pacote = None
    try:
        pacote = json.loads(arquivo.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pacote = None
    if isinstance(pacote, dict) and getattr(sys, "frozen", False) and _windows():
        from src.atualizacao import tarefa
        try:
            pasta, ident = tarefa.preparar_pedido(arquivo, pacote)
        except (OSError, KeyError) as erro:
            log.info("Atualização: não consegui preparar o pedido para a tarefa (%s).", erro)
        else:
            programa = Path(sys.executable).resolve().parent
            espera = pasta / f"esperar-{ident}.cmd"
            espera.write_text(tarefa.script_espera(pasta, ident, programa, Path(sys.executable).name),
                              encoding="utf-8", newline="")
            if tarefa.pedir_ao_windows():
                subprocess.Popen(["cmd", "/c", str(espera)], close_fds=True,
                                 creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                                 | getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return ident
            espera.unlink(missing_ok=True)
            for nome in (tarefa.PEDIDO, tarefa.PACOTE):
                (pasta / nome).unlink(missing_ok=True)
            log.warning("Atualização: sem a tarefa do Windows; o instalador vai pedir permissão de administrador.")
    return _disparar_com_administrador(arquivo)


def _windows() -> bool:
    return os.name == "nt"


def _disparar_com_administrador(arquivo: Path) -> Path:
    """Caminho antigo: o próprio instalador pede administrador ao Windows (precisa de alguém para clicar em Sim)."""
    import sys
    esperada = arquivo.stem.rsplit("-", 1)[-1]
    if not valida(esperada):
        raise RuntimeError("Nome do instalador não identifica a versão esperada.")
    congelado = bool(getattr(sys, "frozen", False))
    programa = Path(sys.executable).resolve().parent if congelado else Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "WillPDV"
    exe = Path(sys.executable).name if congelado else "WillPDV.exe"
    backup = arquivo.parent / ("anterior-" + esperada)
    if not backup.exists():
        if congelado and programa.is_dir():
            copiar_instalacao(programa, backup)
        else:
            backup.mkdir(parents=True, exist_ok=True)
    script = arquivo.parent / "aplicar.cmd"
    script.write_text(script_aplicar(arquivo, programa, backup, exe, esperada), encoding="utf-8", newline="")
    if congelado and _windows():
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0), close_fds=True)
    return script


def ao_iniciar() -> bool:
    """Na abertura: confere a tentativa anterior e, se há pacote conferido e a loja está parada, instala.
    Não baixa de novo aqui. Devolve True quando a instalação foi disparada: aí o programa não abre a tela agora
    (seria derrubado pelo instalador) e reabre sozinho quando terminar."""
    from src.database.conexao import BancoDados
    try:
        banco = BancoDados()
    except Exception:
        return False
    try:
        if banco.remoto:                 # caixa adicional: o pacote baixado está no computador do caixa principal
            return False
        conferir_tentativa(banco)
        if estado(banco).get("arquivo"):
            return rodada(banco, instalar=disparar_instalacao, somente_local=True).get("acao") == "instalar"
    except Exception:
        log.exception("Não consegui retomar a atualização na abertura.")
    finally:
        banco.fechar()
    return False


def confirmar_atualizacao(esperada: str | None = None, comprovante: Path | None = None, sem_banco: bool = False) -> int:
    """A versão nova confirma que subiu. Código 1 pede ao script para restaurar a cópia anterior.
    `sem_banco`: chamada pela tarefa do SISTEMA, que não tem o banco do operador (a abertura seguinte confirma)."""
    from src.database.conexao import BancoDados
    if esperada and esperada != VERSAO:
        return 1
    banco = None
    try:
        from PySide6 import QtWidgets  # Não confirma uma instalação sem as dependências da interface.
        if sem_banco:
            if comprovante is not None:
                comprovante.write_text(VERSAO + "\n", encoding="utf-8")
            return 0
        banco = BancoDados()
        banco.valor("SELECT 1")
        banco.cfg_set("atualizacao_confirmada", VERSAO)
        banco.cfg_set(CHAVE_TENTATIVA, "")
        if comprovante is not None:
            comprovante.write_text(VERSAO + "\n", encoding="utf-8")
    except Exception:
        log.exception("A versão nova não confirmou a subida.")
        return 1
    finally:
        if banco is not None:
            banco.fechar()
    return 0
