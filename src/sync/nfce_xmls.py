"""Cópia dos XMLs da NFC-e de produção para a nuvem (backend/nfce_xmls.py).

A emissão própria grava em `nfce/producao/` (ao lado do banco) o nfeProc (`<chave>-nfe.xml`), o retorno do
cancelamento (`<chave>-cancelamento.xml`) e o da inutilização (`inutilizacao-<série>-<ini>-<fim>.xml`). Aqui eles
sobem comprimidos, em lotes, com o endereço e o token da loja; o que a nuvem confirma fica em `nfce_xmls_enviados`
e não sobe de novo. Homologação não sobe (não tem valor fiscal). Sem endereço ou token: não faz nada.
Erro de rede vira RuntimeError; a próxima rodada tenta de novo.
"""
from __future__ import annotations

import base64
import gzip
import re
from pathlib import Path

from src.core import formatacao as fmt

LOTE = 20
LIMITE_BYTES = 1024 * 1024
TIPOS = (("-nfe.xml", "nfe"), ("-cancelamento.xml", "cancelamento"))
DATA = re.compile(rb"<(?:dhEmi|dhRegEvento|dhRecbto)>(\d{4}-\d{2})-\d{2}T")


def pasta(banco) -> Path | None:
    caminho = getattr(banco, "caminho", None)
    if not caminho or str(caminho) == ":memory:":
        return None
    return Path(caminho).resolve().parent / "nfce" / "producao"


AVISO = "nfce_xmls_pendente"         # "S" quando a emissão própria gravou XML de produção novo
VARRIDO = "nfce_xmls_varrido"        # quando a pasta foi conferida inteira pela última vez


def avisar(banco) -> None:
    """Chamado pela emissão própria ao gravar XML de produção: o sincronizador sabe que há o que subir sem listar a
    pasta a cada poucos segundos."""
    if banco.cfg(AVISO) != "S":
        banco.cfg_set(AVISO, "S")


def ha_pendente(banco) -> bool:
    return configurado(banco) and (banco.cfg(AVISO) == "S" or not (banco.cfg(VARRIDO) or "").strip())


def configurado(banco) -> bool:
    return bool((banco.cfg("api_url") or "").strip()) and bool((banco.cfg("api_token") or "").strip())


def _tipo(nome: str) -> str | None:
    if nome.startswith("inutilizacao-") and nome.endswith(".xml"):
        return "inutilizacao"
    for final, tipo in TIPOS:
        if nome.endswith(final):
            return tipo
    return None


def pendentes(banco, limite: int | None = None) -> list[Path]:
    """Arquivos de produção ainda não confirmados pela nuvem (mais antigos primeiro)."""
    base = pasta(banco)
    if base is None or not base.is_dir():
        return []
    enviados = {r["arquivo"] for r in banco.todos("SELECT arquivo FROM nfce_xmls_enviados")}
    arquivos = sorted((a for a in base.iterdir() if a.is_file() and _tipo(a.name) and a.name not in enviados),
                      key=lambda a: (a.stat().st_mtime, a.name))
    return arquivos[:limite] if limite else arquivos


def descrever(arquivo: Path) -> dict | None:
    """O que vai no lote: nome, tipo, chave, mês (da emissão ou do evento) e o XML em gzip/Base64."""
    dados = arquivo.read_bytes()
    if not dados or len(dados) > LIMITE_BYTES:
        return None
    achado = DATA.search(dados)
    mes = achado.group(1).decode() if achado else fmt.agora()[:7]
    chave = arquivo.name.split("-", 1)[0] if _tipo(arquivo.name) != "inutilizacao" else ""
    return {"nome": arquivo.name, "tipo": _tipo(arquivo.name), "chave": chave if chave.isdigit() else "", "mes": mes,
            "conteudo_gz_b64": base64.b64encode(gzip.compress(dados, mtime=0)).decode("ascii")}


def _postar(banco, corpo: dict, http=None) -> dict:
    from src.sync.painel_envio import _base_nuvem
    if http is None:
        import requests as http
    url = f"{_base_nuvem(banco.cfg('api_url'))}/v1/nfce/xmls"
    try:
        r = http.post(url, json=corpo, headers={"Authorization": f"Bearer {banco.cfg('api_token').strip()}"},
                      timeout=(5, 60))
    except OSError as e:
        raise RuntimeError("XMLs da NFC-e: sem conexão com a nuvem.") from e
    if r.status_code == 404:
        raise RuntimeError("XMLs da NFC-e: a nuvem ainda não tem este recurso.")
    if r.status_code != 200:
        raise RuntimeError(f"XMLs da NFC-e: a nuvem respondeu HTTP {r.status_code}.")
    dados = r.json()
    if not isinstance(dados, dict):
        raise RuntimeError("XMLs da NFC-e: resposta inválida da nuvem.")
    return dados


def sincronizar(banco, http=None, max_lotes: int = 10) -> int:
    """Manda os pendentes em até `max_lotes` lotes. Devolve quantos a nuvem confirmou."""
    if not configurado(banco):
        return 0
    confirmados = 0
    for _ in range(max_lotes):
        arquivos = pendentes(banco, LOTE)
        if not arquivos:
            break
        lote = [d for d in (descrever(a) for a in arquivos) if d]
        if not lote:
            break
        resposta = _postar(banco, {"arquivos": lote}, http)
        aceitos = {n for n in resposta.get("recebidos") or [] if isinstance(n, str)} & {d["nome"] for d in lote}
        recusados = {n for n in resposta.get("recusados") or [] if isinstance(n, str)} & {d["nome"] for d in lote}
        with banco.transacao():
            for nome in aceitos | recusados:          # recusado (corrompido) não volta a cada rodada
                banco.executar("INSERT OR IGNORE INTO nfce_xmls_enviados(arquivo, enviado_em) VALUES (?, ?)",
                               (nome, fmt.agora() + (" recusado" if nome in recusados else "")))
        confirmados += len(aceitos)
        if not aceitos and not recusados or len(arquivos) < LOTE:
            break
    if not pendentes(banco, 1):
        banco.cfg_set(AVISO, "")
        banco.cfg_set(VARRIDO, fmt.agora())
    return confirmados
