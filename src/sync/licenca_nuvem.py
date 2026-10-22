"""Renovação automática da licença pela nuvem: o PDV pede o código da própria loja (GET /v1/licenca, com o token dela)
e o ativa se estender o prazo. O fornecedor só registra até quando a loja pagou (python -m backend.lojas assinatura);
se ela não pagar, a data não avança e a licença vence normalmente no caixa."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from src.core import formatacao as fmt
from src.core import licenca
from src.core.erros import ErroNegocio
from src.sync.atualizacoes import url_atualizacoes

log = logging.getLogger("pdv.licenca")

INTERVALO_HORAS = 6
CHAVE_CONSULTA = "licenca_nuvem_consultada_em"
CHAVE_SUCESSO = "licenca_nuvem_sucesso_em"
CHAVE_ERRO = "licenca_nuvem_erro"
CHAVE_TENTATIVA = "licenca_nuvem_tentada_em"
CHAVE_FALHAS = "licenca_nuvem_falhas"
RETENTATIVAS_MINUTOS = (1, 2, 5, 10, 15, 30)


@dataclass(frozen=True)
class ResultadoConsulta:
    sucesso: bool
    codigo: str | None = None
    erro: str = ""


def url_licenca(api_url: str) -> str:
    return url_atualizacoes(api_url)[: -len("/atualizacoes")] + "/licenca"


def consultar(api_url: str, token: str, http=None, timeout=(3, 10)) -> str | None:
    """Só a rede: o código emitido pela nuvem, ou None (sem nuvem, sem assinatura, sem rede)."""
    return consultar_resultado(api_url, token, http, timeout).codigo


def consultar_resultado(api_url: str, token: str, http=None, timeout=(3, 10)) -> ResultadoConsulta:
    """Só rede, distinguindo resposta válida (inclusive sem assinatura) de falha transitória."""
    if not (api_url or "").strip() or not (token or "").strip():
        return ResultadoConsulta(False, erro="Endereço ou token da nuvem não configurado.")
    if http is None:
        try:
            import requests as http
        except ImportError:
            log.warning("Consulta de licença indisponível: requests não instalado.")
            return ResultadoConsulta(False, erro="Biblioteca requests não instalada.")
    try:
        r = http.get(url_licenca(api_url), headers={"Authorization": f"Bearer {token.strip()}"}, timeout=timeout)
        if r.status_code != 200:
            log.info("A nuvem não emitiu licença (HTTP %s).", r.status_code)
            sucesso = r.status_code in (404, 409)
            return ResultadoConsulta(sucesso, erro="" if sucesso else f"HTTP {r.status_code}")
        codigo = r.json().get("codigo")
    except (OSError, ValueError, AttributeError) as e:
        log.info("Consulta de licença falhou: %s", e)
        return ResultadoConsulta(False, erro=f"Consulta de licença falhou: {e}")
    if not isinstance(codigo, str) or not codigo.strip():
        log.warning("Resposta de licença sem código válido.")
        return ResultadoConsulta(False, erro="Resposta de licença sem código válido.")
    return ResultadoConsulta(True, codigo)


def _falhas(banco) -> int:
    try:
        return max(0, int(banco.cfg(CHAVE_FALHAS) or "0"))
    except ValueError:
        return 0


def iniciar_consulta(banco, forcar: bool = False) -> bool:
    """Registra a tentativa na thread dona do banco; só sucessos aguardam seis horas.

    Com a central do fornecedor ligada (src/sync/ponte.py) a renovação por aqui fica desligada, inclusive no login."""
    from src.sync import ponte
    if ponte.ativa(banco) or not licenca.exigida(banco):
        return False
    tentativa = banco.cfg(CHAVE_TENTATIVA)
    sucesso = banco.cfg(CHAVE_SUCESSO) or banco.cfg(CHAVE_CONSULTA)
    falhou = tentativa and (not sucesso or tentativa > sucesso or _falhas(banco))
    ultima = tentativa if falhou else sucesso
    intervalo = RETENTATIVAS_MINUTOS[min(max(_falhas(banco) - 1, 0), len(RETENTATIVAS_MINUTOS) - 1)] \
        if falhou else INTERVALO_HORAS * 60
    if not forcar and ultima and 0 <= fmt.minutos_entre(ultima) < intervalo:
        return False
    banco.cfg_set(CHAVE_TENTATIVA, fmt.agora())
    return True


def registrar_resultado(banco, resultado: ResultadoConsulta) -> None:
    """Persiste o resultado na thread dona do banco; erros de gravação não são ocultados."""
    with banco.transacao():
        if resultado.sucesso:
            agora = fmt.agora()
            banco.cfg_set(CHAVE_SUCESSO, agora)
            banco.cfg_set(CHAVE_CONSULTA, agora)
            banco.cfg_set(CHAVE_ERRO, "")
            banco.cfg_set(CHAVE_FALHAS, "0")
        else:
            banco.cfg_set(CHAVE_FALHAS, str(_falhas(banco) + 1))
            banco.cfg_set(CHAVE_ERRO, resultado.erro or "Não foi possível consultar a licença na nuvem.")


def aplicar(banco, codigo: str | None) -> bool:
    """Ativa o código se ele estender o prazo atual. Código igual, mais curto ou inválido é ignorado. True se renovou."""
    if not codigo or codigo == banco.cfg("licenca_token").strip():
        return False
    try:
        lic = licenca.ativar(banco, codigo)
    except ErroNegocio as e:                       # mais antiga que a atual, de outra loja, adulterada...
        log.info("Licença da nuvem não aplicada: %s", e)
        return False
    log.info("Licença renovada pela nuvem até %s.", lic["expira_em"].isoformat())
    return True


def renovar(banco, http=None, forcar: bool = False, timeout=(3, 10)) -> bool:
    """Consulta e aplica; sucessos aguardam seis horas e falhas repetem em 1 a 30 minutos."""
    if not iniciar_consulta(banco, forcar):
        return False
    resultado = consultar_resultado(banco.cfg("api_url"), banco.cfg("api_token"), http, timeout)
    registrar_resultado(banco, resultado)
    return aplicar(banco, resultado.codigo)
