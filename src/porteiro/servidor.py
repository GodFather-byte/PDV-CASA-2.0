"""Servidor HTTP da página do porteiro. Só a rede local: não fala com a internet.

A página e os arquivos estáticos ficam em /porteiro. A consulta é somente leitura.
O PIN vira um cookie de sessão (não vai na URL). Sem o PIN, a consulta não responde.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from src.core import seguranca
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.porteiro.consulta import consultar

log = logging.getLogger("pdv.porteiro")

COOKIE = "porteiro"
PREFIXO = "/porteiro"
SESSAO_SEGUNDOS = 12 * 60 * 60
MAX_FALHAS = 5
BLOQUEIO_SEGUNDOS = 60
MAX_CORPO = 2048
ARQUIVOS = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "estilo.css": "text/css; charset=utf-8",
    "manifest.webmanifest": "application/manifest+json; charset=utf-8",
    "sw.js": "text/javascript; charset=utf-8",
    "icones/icone-192.png": "image/png",
    "icones/icone-512.png": "image/png",
    "icones/icone-maskable-192.png": "image/png",
    "icones/icone-maskable-512.png": "image/png",
}


def pasta_web() -> Path:
    """Arquivos da página. No executável, o build copia a pasta para porteiro_web."""
    import sys
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", "")) / "porteiro_web"
    return Path(__file__).resolve().parent / "web"


class Sessoes:
    """PIN conferido vira um token na memória. Reiniciar o caixa desliga as sessões."""

    def __init__(self, max_falhas: int = MAX_FALHAS, bloqueio_segundos: int = BLOQUEIO_SEGUNDOS):
        self.max_falhas = max_falhas
        self.bloqueio_segundos = bloqueio_segundos
        self._lock = threading.Lock()
        self._tokens: dict[str, float] = {}
        self._falhas: dict[str, tuple[int, float]] = {}

    def bloqueado(self, ip: str) -> int:
        """Segundos que este endereço ainda tem de esperar. 0 se pode tentar."""
        with self._lock:
            _n, ate = self._falhas.get(ip, (0, 0.0))
            falta = ate - time.monotonic()
            if falta > 0:
                return int(falta) + 1
            return 0

    def falhou(self, ip: str) -> int:
        """Registra um PIN errado. Devolve os segundos de bloqueio se acabou de estourar o limite."""
        with self._lock:
            n, ate = self._falhas.get(ip, (0, 0.0))
            if ate > time.monotonic():
                return int(ate - time.monotonic()) + 1
            n += 1
            if n >= self.max_falhas:
                self._falhas[ip] = (0, time.monotonic() + self.bloqueio_segundos)
                return self.bloqueio_segundos
            self._falhas[ip] = (n, 0.0)
            return 0

    def abrir(self, ip: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens[token] = time.monotonic() + SESSAO_SEGUNDOS
            self._falhas.pop(ip, None)
        return token

    def valida(self, token: str) -> bool:
        if not token or len(token) > 200:
            return False
        with self._lock:
            expira = self._tokens.get(token)
            if expira is None:
                return False
            if expira < time.monotonic():
                self._tokens.pop(token, None)
                return False
            return True

    def fechar(self, token: str) -> None:
        with self._lock:
            self._tokens.pop(token, None)

    def zerar(self, ip: str) -> None:
        with self._lock:
            self._falhas.pop(ip, None)


def _credencial(cabecalhos) -> str:
    """O PIN vira um token: no cookie (mesma origem) ou no cabeçalho, para a página na nuvem chamar o caixa."""
    autorizacao = ""
    if cabecalhos is not None:
        autorizacao = cabecalhos.get("Authorization") or cabecalhos.get("authorization") or ""
    if autorizacao.lower().startswith("bearer "):
        return autorizacao[7:].strip()
    return _cookie(cabecalhos, COOKIE)


def _cookie(cabecalhos, nome: str) -> str:
    bruto = ""
    if cabecalhos is not None:
        bruto = cabecalhos.get("Cookie") or cabecalhos.get("cookie") or ""
    for parte in bruto.split(";"):
        if "=" not in parte:
            continue
        chave, valor = parte.strip().split("=", 1)
        if chave == nome:
            return valor.strip()
    return ""


def _cabecalho_cookie(token: str, apagar: bool = False) -> tuple[str, str]:
    idade = "0" if apagar else str(SESSAO_SEGUNDOS)
    valor = "" if apagar else token
    return ("Set-Cookie",
            f"{COOKIE}={valor}; HttpOnly; SameSite=Strict; Path={PREFIXO}; Max-Age={idade}")


class _HTTP(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class ServidorPorteiro:
    """Escuta na rede local e entrega a página e a consulta. Não altera vendas."""

    def __init__(self, caminho_banco: str, porta: int, host: str = "0.0.0.0"):
        self.caminho = caminho_banco
        self.host = host
        self.sessoes = Sessoes()
        self._httpd: _HTTP | None = None
        self._thread: threading.Thread | None = None
        self.porta = porta

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._httpd = _HTTP((self.host, self.porta), _montar_handler(self))
        self._httpd.timeout = 1
        self.porta = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="porteiro-http", daemon=True)
        self._thread.start()

    def parar(self, timeout: float = 3) -> None:
        httpd, thread = self._httpd, self._thread
        self._httpd = None
        self._thread = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout)

    def tratar(self, metodo: str, alvo: str, cabecalhos, corpo: bytes, ip: str):
        """Devolve (status, cabeçalhos extras, corpo). Usado pelo HTTP e pelos testes."""
        partes = urlparse(alvo)
        caminho = unquote(partes.path or "/")
        if _caminho_perigoso(caminho):
            return _json(404, {"erro": "Não encontrado."})
        if caminho == "/porteiro":
            return 302, [("Location", "/porteiro/")], b""
        if caminho == "/porteiro/api/saude" and metodo == "GET":
            return _json(200, {"ok": True, "modo": "caixa"})
        if caminho == "/porteiro/api/entrar" and metodo == "POST":
            return self._entrar(cabecalhos, corpo, ip)
        if caminho == "/porteiro/api/sair" and metodo == "POST":
            return self._sair(cabecalhos)
        if caminho == "/porteiro/api/sessao" and metodo == "GET":
            if self.sessoes.valida(_credencial(cabecalhos)):
                return _json(200, {"ok": True})
            return _json(401, {"erro": "Informe o PIN."})
        if caminho == "/porteiro/api/config" and metodo == "GET":
            return self._config(cabecalhos)
        if caminho == "/porteiro/api/consulta" and metodo == "GET":
            return self._consulta(cabecalhos, partes.query)
        if caminho == "/porteiro/api/abertas" and metodo == "GET":
            return self._abertas(cabecalhos)
        if metodo in ("GET", "HEAD") and caminho.startswith("/porteiro/"):
            return _arquivo(caminho)
        if metodo not in ("GET", "POST", "HEAD"):
            return _json(405, {"erro": "Esta página só consulta. Não altera a comanda."})
        return _json(404, {"erro": "Não encontrado."})

    def _entrar(self, cabecalhos, corpo: bytes, ip: str):
        espera = self.sessoes.bloqueado(ip)
        if espera:
            return _json(429, {"erro": "Muitas tentativas. Espere um minuto e tente de novo."},
                         [("Retry-After", str(espera))])
        try:
            pin = _pin_do_corpo(corpo)
        except ValueError:
            return _json(400, {"erro": "Pedido inválido."})
        banco = self._abrir_banco()
        try:
            guardado = banco.cfg("porteiro_pin_hash")
            if not guardado:
                return _json(503, {"erro": "O PIN do porteiro ainda não foi definido no caixa."})
            if not seguranca.conferir(pin, guardado):
                if self.sessoes.falhou(ip):
                    return _json(429, {"erro": "Muitas tentativas. Espere um minuto e tente de novo."},
                                 [("Retry-After", str(BLOQUEIO_SEGUNDOS))])
                return _json(401, {"erro": "PIN incorreto."})
        finally:
            banco.fechar()
        token = self.sessoes.abrir(ip)
        return _json(200, {"ok": True, "token": token}, [_cabecalho_cookie(token)])

    def _sair(self, cabecalhos):
        self.sessoes.fechar(_credencial(cabecalhos))
        return _json(200, {"ok": True}, [_cabecalho_cookie("", apagar=True)])

    def _config(self, cabecalhos):
        """Endereço da nuvem para o celular usar quando o caixa não responde. Sem o token da loja."""
        if not self.sessoes.valida(_credencial(cabecalhos)):
            return _json(401, {"erro": "Informe o PIN."})
        banco = self._abrir_banco()
        try:
            from src.porteiro.nuvem_envio import url_da_pagina
            return _json(200, {"nuvem": url_da_pagina(banco.cfg("api_url")),
                               "chave": (banco.cfg("chave_loja") or "").strip()})
        finally:
            banco.fechar()

    def _consulta(self, cabecalhos, query: str):
        if not self.sessoes.valida(_credencial(cabecalhos)):
            return _json(401, {"erro": "Informe o PIN."})
        texto = (parse_qs(query, max_num_fields=5).get("q") or [""])[0]
        if len(texto) > 32:
            return _json(400, {"erro": "Número da comanda longo demais."})
        banco = self._abrir_banco()
        try:
            try:
                return _json(200, consultar(banco, texto))
            except ErroNegocio as exc:
                return _json(400, {"erro": str(exc)})
        finally:
            banco.fechar()

    def _abertas(self, cabecalhos):
        if not self.sessoes.valida(_credencial(cabecalhos)):
            return _json(401, {"erro": "Informe o PIN."})
        from src.porteiro.consulta import listar_abertas
        banco = self._abrir_banco()
        try:
            return _json(200, listar_abertas(banco))
        finally:
            banco.fechar()

    def _abrir_banco(self):
        try:
            return BancoDados(self.caminho, semear=False)
        except Exception:
            log.exception("O porteiro não abriu o banco do caixa.")
            raise _Indisponivel()


class _Indisponivel(Exception):
    pass


def _pin_do_corpo(corpo: bytes) -> str:
    if len(corpo) > MAX_CORPO:
        raise ValueError("corpo grande")
    try:
        dados = json.loads(corpo.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("json") from None
    if not isinstance(dados, dict):
        raise ValueError("json")
    pin = dados.get("pin", "")
    if isinstance(pin, bool) or not isinstance(pin, (str, int)):
        return ""
    pin = str(pin).strip()
    if len(pin) > 32:
        return ""
    return pin


def _caminho_perigoso(caminho: str) -> bool:
    if "\\" in caminho or "\x00" in caminho:
        return True
    partes = [p for p in caminho.split("/") if p]
    return any(p == ".." for p in partes)


def _arquivo(caminho: str):
    rel = "index.html" if caminho in ("/porteiro/", "/porteiro/index.html") else caminho[len("/porteiro/"):]
    if rel not in ARQUIVOS:
        return _json(404, {"erro": "Não encontrado."})
    raiz = pasta_web().resolve()
    arquivo = (raiz / rel).resolve()
    if not arquivo.is_relative_to(raiz) or not arquivo.is_file():
        return _json(404, {"erro": "Não encontrado."})
    return 200, [("Content-Type", ARQUIVOS[rel]), ("Cache-Control", "no-cache")], arquivo.read_bytes()


def _json(status: int, dados: dict, extras: list | None = None):
    corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
    cabecalhos = [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")]
    if extras:
        cabecalhos.extend(extras)
    return status, cabecalhos, corpo


def _montar_handler(servidor: ServidorPorteiro):
    class Tratador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, formato, *args):
            caminho = self.path.split("?", 1)[0]
            log.info("%s %s", self.command, caminho)

        def do_GET(self):
            self._despachar()

        def do_POST(self):
            self._despachar()

        def do_HEAD(self):
            self._despachar()

        def do_OPTIONS(self):
            if urlparse(self.path).path.startswith("/porteiro/api/"):
                self._escrever(204, [], b"")
            else:
                self._recusar()

        def do_PUT(self):
            self._recusar()

        def do_DELETE(self):
            self._recusar()

        def _recusar(self):
            self._escrever(*_json(405, {"erro": "Esta página só consulta. Não altera a comanda."}))

        def _despachar(self):
            try:
                tamanho = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                tamanho = MAX_CORPO + 1
            if tamanho > MAX_CORPO:
                self._escrever(*_json(413, {"erro": "Pedido grande demais."}))
                return
            corpo = self.rfile.read(tamanho) if tamanho else b""
            try:
                resposta = servidor.tratar(self.command, self.path, self.headers, corpo, self.client_address[0])
            except _Indisponivel:
                resposta = _json(503, {"erro": "O caixa está ocupado. Tente de novo."})
            except Exception:
                log.exception("Falha ao atender o porteiro.")
                resposta = _json(500, {"erro": "Não foi possível consultar agora."})
            self._escrever(*resposta)

        def _escrever(self, status: int, cabecalhos, corpo: bytes):
            self.send_response(status)
            tipos = {nome for nome, _valor in cabecalhos}
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Robots-Tag", "noindex")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                             "script-src 'self'; manifest-src 'self'; worker-src 'self'; connect-src 'self' https:")
            if urlparse(self.path).path.startswith("/porteiro/api/"):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            for nome, valor in cabecalhos:
                self.send_header(nome, valor)
            if "Cache-Control" not in tipos:
                self.send_header("Cache-Control", "no-store")
            if "Content-Type" not in tipos:
                self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            if self.command != "HEAD" and corpo:
                self.wfile.write(corpo)

    return Tratador
