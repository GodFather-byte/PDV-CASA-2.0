"""Caixa adicional: instala a mesma versão do caixa principal quando o principal o recusa por versão diferente.

O adicional não tem banco próprio, então não entra na rodada de atualização do principal (cliente.rodada devolve
"caixa_adicional"). Quando o principal se atualiza, ele passa a recusar o adicional e manda, no canal já cifrado com o
código de ligação, a versão dele, a nuvem e a chave da loja. Com isso o adicional consulta a nuvem, confere a assinatura
e o SHA-256 do pacote como o principal faz, e instala só se a versão publicada for exatamente a do principal.

Ele só instala parado: na abertura (sem ligação não há venda neste computador) ou depois que o operador confirma.
A venda aberta fica no banco do principal e continua lá. Uma tentativa por versão a cada 30 minutos, para não entrar em
laço se o instalador falhar.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from src.atualizacao import cliente
from src.core import edicao
from src.versao import VERSAO, mais_nova

log = logging.getLogger("pdv.atualizacao")

ARQUIVO_TENTATIVA = "atualizacao_adicional.json"
INTERVALO_TENTATIVA = timedelta(minutes=30)


def _pasta(pasta: Path | None = None) -> Path:
    if pasta is not None:
        return pasta
    from src.database.conexao import RAIZ
    return Path(RAIZ) / "atualizacao"


def pode_atualizar(erro) -> bool:
    """O principal está numa versão mais nova e mandou onde fica a nuvem."""
    versao = getattr(erro, "versao_principal", "") or ""
    return bool(versao and getattr(erro, "nuvem", "") and mais_nova(versao, VERSAO))


def _ultima_tentativa(pasta: Path) -> dict:
    try:
        dados = json.loads((pasta / ARQUIVO_TENTATIVA).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def tentou_ha_pouco(versao: str, pasta: Path | None = None, agora: datetime | None = None) -> bool:
    dados = _ultima_tentativa(_pasta(pasta))
    if dados.get("versao") != versao:
        return False
    try:
        quando = datetime.fromisoformat(str(dados.get("em")))
    except ValueError:
        return False
    return (agora or datetime.now()) - quando < INTERVALO_TENTATIVA


def esquecer_tentativa(pasta: Path | None = None) -> None:
    """Botão "Tentar de novo": libera uma nova tentativa da mesma versão."""
    (_pasta(pasta) / ARQUIVO_TENTATIVA).unlink(missing_ok=True)


def atualizar(erro, http=None, instalar=None, pasta: Path | None = None, publica_hex: str | None = None,
              agora: datetime | None = None) -> dict:
    """Baixa e manda instalar a versão do principal. Devolve {"acao": ..., "mensagem": ...} para a tela."""
    versao = getattr(erro, "versao_principal", "") or ""
    if not pode_atualizar(erro):
        if versao and mais_nova(VERSAO, versao):
            return {"acao": "principal_antigo",
                    "mensagem": f"Este caixa está na {VERSAO} e o principal na {versao}. Atualize o caixa principal."}
        return {"acao": "nada", "mensagem": ""}
    pasta = _pasta(pasta)
    if tentou_ha_pouco(versao, pasta, agora):
        return {"acao": "ja_tentou", "mensagem": f"A instalação da {versao} já foi tentada há pouco e este caixa "
                                                 "não subiu nela. Use Tentar de novo ou instale à mão pelo link."}
    if http is None:
        try:
            import requests as http
        except ImportError:
            return {"acao": "sem_cliente_http", "mensagem": "Este computador não consegue baixar a atualização."}
    dados = cliente.consultar(erro.nuvem, http, loja=getattr(erro, "loja", "") or "")
    if dados is None:
        return {"acao": "sem_resposta", "mensagem": "A nuvem não respondeu. Confira a internet e tente de novo."}
    if not cliente.pacote_valido(dados, publica_hex):
        return {"acao": cliente.sem_pacote(dados), "mensagem": "A nuvem não tem um pacote válido para este caixa agora."}
    pacote = dados["pacote"]
    if pacote["versao"] != versao:
        return {"acao": "versao_indisponivel",
                "mensagem": f"O principal está na {versao}, mas a nuvem oferece a {pacote['versao']}. "
                            "Deixe os dois na mesma versão (atualize o principal ou instale à mão)."}
    destino = pasta / f"{pacote['edicao']}-{pacote['versao']}.exe"
    if not destino.is_file() or cliente.sha256_arquivo(destino).lower() != str(pacote["sha256"]).lower():
        cliente.baixar(cliente.url_absoluta(erro.nuvem, pacote["url"]), destino, pacote["sha256"],
                       int(pacote["tamanho"]), http)
    destino.with_suffix(".json").write_text(json.dumps(pacote, ensure_ascii=False), encoding="utf-8")
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / ARQUIVO_TENTATIVA).write_text(json.dumps(
        {"versao": versao, "em": (agora or datetime.now()).isoformat(timespec="seconds")}), encoding="utf-8")
    (instalar or cliente.disparar_instalacao)(destino)
    log.info("Caixa adicional: instalação da %s (igual ao principal) disparada.", versao)
    return {"acao": "instalar", "versao": versao,
            "mensagem": f"Instalando a versão {versao}. O {edicao.atual().nome} reabre sozinho ao terminar."}
