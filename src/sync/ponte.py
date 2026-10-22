"""Ponte com a central do fornecedor (opt-in, Configurações > Nuvem > Central do fornecedor).

Com `central_ponte_ativa = S` o caixa fala com a API (`api_url`) usando o token do PRÓPRIO caixa
(`central_caixa_token`, emitido pelo fornecedor para o `central_caixa_id`; não é o `api_token` da loja):

- GET  /v1/ponte/licenca      -> {id, codigo, expira_em} (404 = nada publicado);
- POST /v1/ponte/contato      {versao, licenca_aplicada_id};
- POST /v1/ponte/solicitacoes {id, tipo: "renovacao"} (idempotente pelo id).

O caixa nunca emite licença: só aplica pelo validador local (`licenca.ativar`) o código assinado pela central e
confirma o id publicado depois de gravar (ou se o código já guardado for o mesmo e ainda válido). Com a ponte ligada a
renovação antiga pela nuvem (`licenca_nuvem`) fica desligada, inclusive no login; desligada, nada aqui faz rede.
Falha de rede não bloqueia nem prorroga nada: as regras de aviso, carência e turno aberto continuam as de `licenca`.
Rede sempre fora da thread da tela (`ServicoPonte` em thread própria, ou a sincronização em processo próprio). O token nunca vai para log nem erro.
"""
from __future__ import annotations

import ipaddress
import json as _json
import logging
import re
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit

from src.core import formatacao as fmt
from src.core import licenca
from src.core.erros import ErroNegocio, ErroValidacao
from src.sync.atualizacoes import url_atualizacoes
from src.versao import VERSAO

log = logging.getLogger("pdv.ponte")

CHAVE_ATIVA = "central_ponte_ativa"
CHAVE_CAIXA_ID = "central_caixa_id"
CHAVE_TOKEN = "central_caixa_token"
CHAVE_TENTATIVA = "central_ponte_tentada_em"
CHAVE_SUCESSO = "central_ponte_sucesso_em"
CHAVE_ERRO = "central_ponte_erro"
CHAVE_FALHAS = "central_ponte_falhas"
CHAVE_LICENCA_APLICADA = "central_licenca_aplicada_id"
CHAVE_LICENCA_RECUSADA = "central_licenca_recusada_id"
CHAVE_LICENCA_ERRO = "central_licenca_erro"
CHAVE_SOLICITACAO = "central_solicitacao_id"
CHAVE_SOLICITACAO_ESTADO = "central_solicitacao_estado"      # pendente | enviada | atendida
CHAVE_SOLICITACAO_BASE = "central_solicitacao_licenca_base"  # licença aplicada na última conferência do pedido
# Valores de fábrica (semeados em src/database/sementes.py).
PADROES = {CHAVE_ATIVA: "N", CHAVE_CAIXA_ID: "", CHAVE_TOKEN: "", CHAVE_TENTATIVA: "", CHAVE_SUCESSO: "",
           CHAVE_ERRO: "", CHAVE_FALHAS: "0", CHAVE_LICENCA_APLICADA: "", CHAVE_LICENCA_RECUSADA: "",
           CHAVE_LICENCA_ERRO: "", CHAVE_SOLICITACAO: "", CHAVE_SOLICITACAO_ESTADO: "", CHAVE_SOLICITACAO_BASE: ""}

INTERVALO_MINUTOS = 60                       # contato normal (inclusive quando a central responde 404)
RETENTATIVAS_MINUTOS = (1, 2, 5, 10, 15, 30, 60)
TIMEOUT = (3, 10)
OK_ESCRITA = (200, 201, 202, 204)
LOOPBACK = {"localhost"}


class ErroPonte(ErroNegocio):
    """Falha de comunicação com a central (mensagem já sem o token)."""


@dataclass(frozen=True)
class Resultado:
    sucesso: bool
    licenca: str = ""        # "" | sem_licenca | ja_aplicada | aplicada | confirmada | recusada
    erro: str = ""


# ------------------------------------------------------------------ configuração
def ativa(banco) -> bool:
    return banco.cfg_bool(CHAVE_ATIVA, False)


def uuid_valido(texto: str) -> str | None:
    """O UUID na forma canônica (minúsculas, com hífens) ou None."""
    try:
        return str(uuid.UUID(str(texto or "").strip()))
    except (ValueError, AttributeError, TypeError):
        return None


def novo_caixa_id() -> str:
    return str(uuid.uuid4())


def garantir_caixa_id(banco) -> str:
    """O id persistente deste caixa; cria um UUID v4 se ainda não houver (ou se o guardado for inválido)."""
    atual = uuid_valido(banco.cfg(CHAVE_CAIXA_ID))
    if atual is None:
        atual = novo_caixa_id()
        banco.cfg_set(CHAVE_CAIXA_ID, atual)
    return atual


def novo_caixa(banco) -> str:
    """Novo provisionamento (token perdido ou revogado): a central nunca reaproveita um ID, então gera outro UUID,
    apaga o token anterior e DESLIGA a ponte até o fornecedor aprovar o ID novo e entregar o token novo.
    A licença já gravada no caixa continua valendo; só o vínculo com a central recomeça."""
    novo = novo_caixa_id()
    with banco.transacao():
        banco.cfg_set(CHAVE_CAIXA_ID, novo)
        banco.cfg_set(CHAVE_TOKEN, "")
        banco.cfg_set(CHAVE_ATIVA, "N")
        for chave in (CHAVE_TENTATIVA, CHAVE_ERRO, CHAVE_LICENCA_APLICADA, CHAVE_LICENCA_RECUSADA, CHAVE_LICENCA_ERRO,
                      CHAVE_SOLICITACAO, CHAVE_SOLICITACAO_ESTADO, CHAVE_SOLICITACAO_BASE):
            banco.cfg_set(chave, "")
        banco.cfg_set(CHAVE_FALHAS, "0")
    log.info("Novo ID do caixa para a central: %s (token anterior apagado; ponte desligada até reaprovar).", novo)
    return novo


def url_segura(url: str) -> bool:
    """HTTPS obrigatório; HTTP só no próprio computador (testes e homologação local)."""
    try:
        partes = urlsplit((url or "").strip())
        host = partes.hostname or ""
    except ValueError:
        return False
    if not host:
        return False
    if partes.scheme == "https":
        return True
    if partes.scheme != "http":
        return False
    if host.lower() in LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def url_ponte(api_url: str, rota: str) -> str:
    """`.../v1/sincronizar` ou a raiz da API -> `<raiz>/v1/ponte/<rota>`."""
    return url_atualizacoes(api_url)[: -len("/atualizacoes")] + f"/ponte/{rota}"


def validar_configuracao(banco) -> None:
    """Confere o necessário para a ponte ligada; levanta ErroValidacao (sem repetir o token na mensagem)."""
    url = banco.cfg("api_url").strip()
    if not url:
        raise ErroValidacao("Para ligar a central do fornecedor, preencha o endereço da nuvem.", {"api_url": "obrigatório"})
    if not url_segura(url):
        raise ErroValidacao("A central do fornecedor exige endereço HTTPS (HTTP só para teste no próprio computador).",
                            {"api_url": "inválido"})
    if uuid_valido(banco.cfg(CHAVE_CAIXA_ID)) is None:
        raise ErroValidacao("O ID do caixa na central precisa ser um UUID válido.", {CHAVE_CAIXA_ID: "inválido"})
    if not banco.cfg(CHAVE_TOKEN).strip():
        raise ErroValidacao("Informe o token do caixa emitido pelo fornecedor (não é o token da API da loja).",
                            {CHAVE_TOKEN: "obrigatório"})


def redigir(texto, *segredos: str) -> str:
    """Tira tokens de uma mensagem antes de log ou config."""
    texto = re.sub(r"(?i)bearer\s+\S+", "Bearer ***", str(texto or ""))
    for segredo in segredos:
        if segredo and len(segredo) >= 4:
            texto = texto.replace(segredo, "***")
    return texto[:300]


def estado(banco) -> dict:
    """Retrato para telas e Telegram (sem o token)."""
    return {"ativa": ativa(banco), "caixa_id": banco.cfg(CHAVE_CAIXA_ID).strip(),
            "token_configurado": bool(banco.cfg(CHAVE_TOKEN).strip()),
            "ultimo_sucesso": banco.cfg(CHAVE_SUCESSO), "ultima_tentativa": banco.cfg(CHAVE_TENTATIVA),
            "erro": banco.cfg(CHAVE_ERRO), "falhas_seguidas": _falhas(banco), "licenca_aplicada_id": banco.cfg(CHAVE_LICENCA_APLICADA),
            "licenca_erro": banco.cfg(CHAVE_LICENCA_ERRO), "solicitacao_id": banco.cfg(CHAVE_SOLICITACAO),
            "solicitacao_estado": banco.cfg(CHAVE_SOLICITACAO_ESTADO)}


def resumo(banco) -> str:
    """Texto da situação da central (sem o token) para a interface Qt."""
    e = estado(banco)
    linhas = [f"Central do fornecedor: {'LIGADA' if e['ativa'] else 'desligada'}.",
              f"ID deste caixa: {e['caixa_id'] or '(vazio)'}",
              f"Token do caixa: {'gravado' if e['token_configurado'] else 'não informado'}.",
              f"Último contato com sucesso: {fmt.fmt_datahora(e['ultimo_sucesso']) if e['ultimo_sucesso'] else 'nunca'}."]
    if e["erro"]:
        linhas.append(f"Último erro ({e['falhas_seguidas']} falha(s) seguida(s)): {e['erro']}")
    if e["licenca_erro"]:
        linhas.append(e["licenca_erro"])
    if e["solicitacao_id"]:
        linhas.append(f"Pedido de renovação {e['solicitacao_id']}: {e['solicitacao_estado'] or '-'}.")
    return "\n".join(linhas)


# ------------------------------------------------------------------ HTTP
class _Resposta:
    def __init__(self, status_code: int, corpo: bytes):
        self.status_code, self._corpo = status_code, corpo

    def json(self):
        return _json.loads(self._corpo.decode("utf-8") or "null")


class _SemRedirecionar(urllib.request.HTTPRedirectHandler):
    """Redirecionamento levaria o Authorization a outro endereço (talvez sem HTTPS): recusado."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpUrllib:
    """Cliente mínimo (biblioteca padrão) com a mesma cara do `requests` usada aqui: get/post -> status_code/json()."""

    def __init__(self):
        self._abrir = urllib.request.build_opener(_SemRedirecionar()).open

    def get(self, url, headers=None, timeout=TIMEOUT):
        return self._pedir("GET", url, headers, None, timeout)

    def post(self, url, json=None, headers=None, timeout=TIMEOUT):
        return self._pedir("POST", url, headers, json, timeout)

    def _pedir(self, metodo, url, headers, corpo, timeout):
        cab = dict(headers or {})
        dados = None
        if corpo is not None:
            dados = _json.dumps(corpo).encode("utf-8")
            cab["Content-Type"] = "application/json"
        espera = max(timeout) if isinstance(timeout, (tuple, list)) else timeout
        pedido = urllib.request.Request(url, data=dados, headers=cab, method=metodo)
        try:
            with self._abrir(pedido, timeout=espera) as r:
                return _Resposta(r.status, r.read())
        except urllib.error.HTTPError as e:
            try:
                return _Resposta(e.code, e.read() or b"")
            finally:
                e.close()


def _cliente(http):
    return http if http is not None else HttpUrllib()


def _cabecalhos(token: str) -> dict:
    return {"Authorization": "Bearer " + token, "Accept": "application/json"}


def _chamar(banco, http, metodo: str, rota: str, corpo=None):
    """Uma chamada à ponte; erros de rede viram ErroPonte com mensagem redigida."""
    url, token = banco.cfg("api_url").strip(), banco.cfg(CHAVE_TOKEN).strip()
    if not url_segura(url):
        raise ErroPonte("Endereço da central sem HTTPS: conexão recusada.")
    try:
        if metodo == "GET":
            return http.get(url_ponte(url, rota), headers=_cabecalhos(token), timeout=TIMEOUT)
        return http.post(url_ponte(url, rota), json=corpo, headers=_cabecalhos(token), timeout=TIMEOUT)
    except (OSError, ValueError, AttributeError) as e:
        raise ErroPonte(redigir(f"Sem comunicação com a central ({rota}): {e}", token)) from None


def _erro_http(rota: str, status: int) -> ErroPonte:
    if status in (401, 403):
        return ErroPonte(f"A central recusou o token deste caixa (HTTP {status} em {rota}). Se o token foi perdido ou revogado, gere um novo ID do caixa e peça a aprovação ao fornecedor.")
    return ErroPonte(f"A central respondeu HTTP {status} em {rota}.")


# ------------------------------------------------------------------ licença
def _codigo_atual_valido(banco, codigo: str) -> bool:
    """O código guardado é este, assinado, da loja e ainda dentro da validade."""
    if "".join(banco.cfg("licenca_token").split()) != codigo:
        return False
    try:
        lic = licenca.ler_licenca(codigo)
    except licenca.LicencaInvalida:
        return False
    loja = banco.cfg("chave_loja").strip()
    if loja and not licenca.mesma_loja(lic["loja"], loja):
        return False
    return lic["expira_em"] >= date.fromisoformat(fmt.hoje())


def _aplicar_publicada(banco, publicada_id: str, codigo: str) -> str:
    """Aplica pelo validador local; só marca o id depois de gravar (ou se o mesmo código já estiver valendo)."""
    if publicada_id == banco.cfg(CHAVE_LICENCA_APLICADA).strip():
        return "ja_aplicada"
    codigo = "".join(codigo.split())
    if _codigo_atual_valido(banco, codigo):
        situacao = "confirmada"
    else:
        try:
            lic = licenca.ativar(banco, codigo)
        except ErroNegocio as e:                     # adulterada, de outra loja, mais curta, vencida...
            with banco.transacao():
                banco.cfg_set(CHAVE_LICENCA_RECUSADA, publicada_id)
                banco.cfg_set(CHAVE_LICENCA_ERRO, redigir(f"Licença publicada pela central não aplicada: {e}"))
            log.info("Licença publicada pela central não aplicada (id %s): %s", publicada_id, e)
            return "recusada"
        situacao = "aplicada"
        log.info("Licença da central aplicada até %s (id %s).", lic["expira_em"].isoformat(), publicada_id)
    with banco.transacao():
        banco.cfg_set(CHAVE_LICENCA_APLICADA, publicada_id)
        banco.cfg_set(CHAVE_LICENCA_RECUSADA, "")
        banco.cfg_set(CHAVE_LICENCA_ERRO, "")
    return situacao


def consultar_licenca(banco, http) -> str:
    r = _chamar(banco, http, "GET", "licenca")
    if r.status_code == 404:
        return "sem_licenca"
    if r.status_code != 200:
        raise _erro_http("licenca", r.status_code)
    try:
        dados = r.json()
    except ValueError:
        raise ErroPonte("Resposta ilegível da central em licenca.") from None
    publicada_id = uuid_valido(dados.get("id")) if isinstance(dados, dict) else None
    codigo = dados.get("codigo") if isinstance(dados, dict) else None
    if publicada_id is None or not isinstance(codigo, str) or not codigo.strip():
        raise ErroPonte("Resposta da central sem id ou código de licença válidos.")
    return _aplicar_publicada(banco, publicada_id, codigo)


def enviar_contato(banco, http) -> None:
    aplicada = banco.cfg(CHAVE_LICENCA_APLICADA).strip() or None
    r = _chamar(banco, http, "POST", "contato", {"versao": VERSAO, "licenca_aplicada_id": aplicada})
    if r.status_code not in OK_ESCRITA:
        raise _erro_http("contato", r.status_code)


# ------------------------------------------------------------------ solicitações
def _postar_solicitacao(banco, http, sid: str) -> str:
    """POST do pedido com o MESMO id (a central deduplica) e grava a situação devolvida: enviada ou atendida."""
    r = _chamar(banco, http, "POST", "solicitacoes", {"id": sid, "tipo": "renovacao"})
    if r.status_code not in OK_ESCRITA:
        raise _erro_http("solicitacoes", r.status_code)
    try:
        dados = r.json()
    except ValueError:
        dados = None
    atendida = isinstance(dados, dict) and dados.get("situacao") == "atendida"
    situacao = "atendida" if atendida else "enviada"   # sem situação (ou "pendente"): entregue, aguardando
    with banco.transacao():
        banco.cfg_set(CHAVE_SOLICITACAO_ESTADO, situacao)
        banco.cfg_set(CHAVE_SOLICITACAO_BASE, banco.cfg(CHAVE_LICENCA_APLICADA))
    log.info("Pedido de renovação %s na central: %s.", sid, "atendido" if atendida else "aguardando")
    return situacao


def _enviar_solicitacao_pendente(banco, http) -> bool:
    """Reenvia o pedido que ainda não chegou à central. True se não ficou nada pendente."""
    sid = banco.cfg(CHAVE_SOLICITACAO).strip()
    if sid and banco.cfg(CHAVE_SOLICITACAO_ESTADO) == "pendente":
        _postar_solicitacao(banco, http, sid)
    return True


def _conferir_atendimento(banco, http) -> None:
    """Depois de aplicar uma licença nova, pergunta (mesmo id) se ela atendeu o pedido entregue.

    Só consulta quando a licença aplicada mudou desde a última conferência, para não repetir o POST a cada hora."""
    sid = banco.cfg(CHAVE_SOLICITACAO).strip()
    aplicada = banco.cfg(CHAVE_LICENCA_APLICADA).strip()
    if (sid and aplicada and banco.cfg(CHAVE_SOLICITACAO_ESTADO) == "enviada"
            and aplicada != banco.cfg(CHAVE_SOLICITACAO_BASE).strip()):
        _postar_solicitacao(banco, http, sid)


def _novo_pedido(banco) -> str:
    sid = str(uuid.uuid4())
    with banco.transacao():
        banco.cfg_set(CHAVE_SOLICITACAO, sid)
        banco.cfg_set(CHAVE_SOLICITACAO_ESTADO, "pendente")
        banco.cfg_set(CHAVE_SOLICITACAO_BASE, banco.cfg(CHAVE_LICENCA_APLICADA))
    return sid


def solicitar_renovacao(banco, http=None) -> str:
    """Pede renovação à central e devolve o id do pedido. Faz rede: não chamar na thread da tela.

    Um pedido por vez: enquanto o anterior não for ATENDIDO pela central, o mesmo id é reenviado (o POST
    devolve a situação atual), então falhas e repetições não criam outro. Só depois de "atendida" nasce um id
    novo. O id é gravado ANTES da rede; falha deixa o pedido como está para a sincronização reenviar e fica em
    `central_ponte_erro` (sem o token). A situação fica em `estado(banco)["solicitacao_estado"]`:
    pendente (não entregue), enviada (aguardando o fornecedor) ou atendida."""
    if not ativa(banco):
        raise ErroNegocio("A central do fornecedor está desligada neste caixa (Configurações > Nuvem).")
    validar_configuracao(banco)
    cliente = _cliente(http)
    sid = uuid_valido(banco.cfg(CHAVE_SOLICITACAO))
    try:
        if sid and banco.cfg(CHAVE_SOLICITACAO_ESTADO) in ("pendente", "enviada"):
            if _postar_solicitacao(banco, cliente, sid) != "atendida":
                return sid                         # o mesmo pedido, ainda aguardando
        sid = _novo_pedido(banco)
        _postar_solicitacao(banco, cliente, sid)
    except ErroPonte as e:
        banco.cfg_set(CHAVE_ERRO, str(e))
        log.warning("Pedido de renovação %s não confirmado pela central: %s", sid, e)
    return sid


# ------------------------------------------------------------------ rodada
def _falhas(banco) -> int:
    try:
        return max(0, int(banco.cfg(CHAVE_FALHAS) or "0"))
    except ValueError:
        return 0


def precisa_rodar(banco) -> bool:
    """Contato a cada hora; depois de falha, 1 a 60 minutos (cresce a cada falha seguida)."""
    ultima = banco.cfg(CHAVE_TENTATIVA)
    if not ultima:
        return True
    falhas = _falhas(banco)
    intervalo = RETENTATIVAS_MINUTOS[min(falhas - 1, len(RETENTATIVAS_MINUTOS) - 1)] if falhas else INTERVALO_MINUTOS
    try:
        passados = fmt.minutos_entre(ultima)
    except ValueError:
        return True
    return passados < 0 or passados >= intervalo


def rodada(banco, http=None, forcar: bool = False) -> Resultado | None:
    """Pedido pendente, licença publicada e contato. None se desligada ou ainda no intervalo (sem rede)."""
    if not ativa(banco) or not (forcar or precisa_rodar(banco)):
        return None
    banco.cfg_set(CHAVE_TENTATIVA, fmt.agora())
    situacao = ""
    try:
        validar_configuracao(banco)
        cliente = _cliente(http)
        _enviar_solicitacao_pendente(banco, cliente)
        situacao = consultar_licenca(banco, cliente)
        enviar_contato(banco, cliente)
        _conferir_atendimento(banco, cliente)          # a central só marca atendido depois do contato
    except ErroNegocio as e:                         # ErroPonte ou configuração incompleta
        erro = redigir(e, banco.cfg(CHAVE_TOKEN).strip())
        with banco.transacao():
            banco.cfg_set(CHAVE_FALHAS, str(_falhas(banco) + 1))
            banco.cfg_set(CHAVE_ERRO, erro)
        log.warning("Central do fornecedor: %s", erro)
        return Resultado(False, situacao, erro)
    with banco.transacao():
        banco.cfg_set(CHAVE_SUCESSO, fmt.agora())
        banco.cfg_set(CHAVE_FALHAS, "0")
        banco.cfg_set(CHAVE_ERRO, "")
    return Resultado(True, situacao)


class ServicoPonte:
    """Thread de segundo plano da ponte, iniciada pela tela antes do login (não depende do --sync).

    Conexão própria com o banco (SQLite não compartilha conexão entre threads), então exige banco em arquivo. A cada
    `intervalo` chama `rodada`, que já respeita o intervalo de contato e o recuo depois de falhas e não faz rede com a
    ponte desligada. Pode conviver com o --sync: os dois usam o mesmo horário da última tentativa gravado no banco."""

    def __init__(self, caminho_banco: str, http=None, intervalo: float = 30.0):
        if str(caminho_banco) == ":memory:":
            raise ErroNegocio("A ponte com a central em segundo plano precisa de banco em arquivo.")
        self.caminho = caminho_banco
        self.http = http
        self.intervalo = intervalo
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self.ultimo_erro: str | None = None

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="ponte-central", daemon=True)
        self._thread.start()

    def parar(self, timeout: float = 3) -> None:
        self._parar.set()
        if self._thread:
            self._thread.join(timeout)

    def _laco(self) -> None:
        from src.database.conexao import BancoDados   # import tardio: evita ciclo na carga dos módulos
        try:
            banco = BancoDados(self.caminho, semear=False)
        except Exception as e:  # noqa: BLE001
            self.ultimo_erro = redigir(f"Ponte com a central não abriu o banco: {e}")
            log.error("%s", self.ultimo_erro)
            return
        try:
            while not self._parar.is_set():
                try:
                    r = rodada(banco, self.http)
                    if r is not None:
                        self.ultimo_erro = r.erro or None
                except Exception as e:  # noqa: BLE001 - a thread não pode morrer
                    self.ultimo_erro = redigir(f"Erro inesperado na ponte com a central: {e}", banco.cfg(CHAVE_TOKEN).strip())
                    log.error("%s", self.ultimo_erro)
                self._parar.wait(self.intervalo)
        finally:
            banco.fechar()
