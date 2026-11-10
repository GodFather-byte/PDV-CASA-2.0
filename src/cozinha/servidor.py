"""HTTP local da cozinha: PIN próprio, sessão limitada à cozinha e transições explícitas."""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from src.controllers.acesso_controller import AcessoController
from src.controllers.preparo_controller import PreparoController
from src.core import seguranca
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.porteiro.servidor import Sessoes, _cookie

log = logging.getLogger("pdv.cozinha_web")
MAX_CORPO = 4096
ARQUIVOS = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
            "estilo.css": "text/css; charset=utf-8"}


def pasta_web():
    import sys
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", "")) / "cozinha_web"
    return Path(__file__).resolve().parent / "web"


def resposta(status, dados, extras=None):
    return status, [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")] + (extras or []), json.dumps(dados, ensure_ascii=False).encode()


def cookie(token="", apagar=False):
    return ("Set-Cookie", f"cozinha={token}; HttpOnly; SameSite=Strict; Path=/cozinha; Max-Age={0 if apagar else 43200}")


class _HTTP(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class ServidorCozinha:
    def __init__(self, caminho_banco, porta=8766, host="0.0.0.0"):
        self.caminho, self.porta, self.host = caminho_banco, porta, host
        self.sessoes, self.modos = Sessoes(), {}
        self._assinatura = None
        self._lock = threading.Lock()
        self._httpd = self._thread = None

    @property
    def ativo(self):
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self):
        if self.ativo:
            return
        self._httpd = _HTTP((self.host, self.porta), handler(self))
        self.porta = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="cozinha-http", daemon=True)
        self._thread.start()

    def parar(self, timeout=3):
        httpd, thread = self._httpd, self._thread
        self._httpd = self._thread = None
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        if thread:
            thread.join(timeout)

    def _contexto(self, banco):
        if not banco.cfg_bool("cozinha_web_ativo") or not banco.cfg_bool("usar_cozinha_bar"):
            raise ErroNegocio("A cozinha web está desligada no caixa.")
        guardado = banco.cfg("cozinha_web_pin_hash")
        uid = banco.cfg_int("cozinha_web_operador_id", 0)
        linha = banco.um("SELECT id FROM operadores WHERE id = ? AND ativo = 1", (uid,))
        if not guardado or linha is None:
            raise ErroNegocio("Configure o PIN e o operador da cozinha no caixa.")
        acesso = AcessoController(banco)
        operador = acesso.operador(uid)
        acesso.exigir(operador, "util_cozinha")
        assinatura = (guardado, uid)
        with self._lock:
            if self._assinatura != assinatura:
                self.sessoes, self.modos = Sessoes(), {}
                self._assinatura = assinatura
        return guardado, operador

    def tratar(self, metodo, alvo, cabecalhos, corpo, ip):
        partes = urlsplit(alvo)
        caminho = unquote(partes.path)
        if "\\" in caminho or "\x00" in caminho or ".." in caminho.split("/"):
            return resposta(404, {"erro": "Não encontrado."})
        if caminho == "/cozinha" and metodo == "GET":
            return 302, [("Location", "/cozinha/")], b""
        if metodo in ("GET", "HEAD") and caminho.startswith("/cozinha/") and not caminho.startswith("/cozinha/api/"):
            rel = "index.html" if caminho == "/cozinha/" else caminho[len("/cozinha/"):]
            if rel not in ARQUIVOS:
                return resposta(404, {"erro": "Não encontrado."})
            arquivo = pasta_web() / rel
            if not arquivo.is_file():
                return resposta(404, {"erro": "Página não encontrada."})
            return 200, [("Content-Type", ARQUIVOS[rel]), ("Cache-Control", "no-cache")], arquivo.read_bytes()
        if not caminho.startswith("/cozinha/api/"):
            return resposta(404, {"erro": "Não encontrado."})
        if metodo not in ("GET", "POST"):
            return resposta(405, {"erro": "Método não permitido."})
        dados = {}
        if metodo == "POST":
            origem = cabecalhos.get("Origin")
            host = cabecalhos.get("Host", "")
            if origem and urlsplit(origem).netloc != host:
                return resposta(403, {"erro": "Origem não permitida."})
            if cabecalhos.get("X-Cozinha-Acao") != "1":
                return resposta(403, {"erro": "Reabra a página da cozinha."})
            if "application/json" not in cabecalhos.get("Content-Type", ""):
                return resposta(415, {"erro": "Envie JSON."})
            try:
                if len(corpo) > MAX_CORPO:
                    raise ValueError
                dados = json.loads(corpo or b"{}")
                if not isinstance(dados, dict):
                    raise ValueError
            except (ValueError, UnicodeDecodeError):
                return resposta(400, {"erro": "Pedido inválido."})
        banco = BancoDados(self.caminho, semear=False)
        try:
            try:
                guardado, operador = self._contexto(banco)
            except ErroNegocio as exc:
                return resposta(403, {"erro": str(exc)})
            if caminho == "/cozinha/api/entrar" and metodo == "POST":
                espera = self.sessoes.bloqueado(ip)
                if espera:
                    return resposta(429, {"erro": "Aguarde um minuto antes de tentar novamente."})
                pin = dados.get("pin")
                if not isinstance(pin, str) or len(pin) > 16 or not seguranca.conferir(pin, guardado):
                    self.sessoes.falhou(ip)
                    return resposta(401, {"erro": "PIN incorreto."})
                token = self.sessoes.abrir(ip)
                with self._lock:
                    self.modos[token] = "tv" if dados.get("modo") == "tv" else "operacao"
                return resposta(200, {"ok": True}, [cookie(token)])
            token = _cookie(cabecalhos, "cozinha")
            if not self.sessoes.valida(token):
                return resposta(401, {"erro": "Entre com o PIN da cozinha."})
            modo = self.modos.get(token, "tv")
            if caminho == "/cozinha/api/sessao" and metodo == "GET":
                return resposta(200, {"modo": modo})
            if caminho == "/cozinha/api/sair" and metodo == "POST":
                self.sessoes.fechar(token)
                with self._lock:
                    self.modos.pop(token, None)
                return resposta(200, {"ok": True}, [cookie(apagar=True)])
            preparo = PreparoController(banco, operador.id)
            if caminho == "/cozinha/api/fila" and metodo == "GET":
                campos = parse_qs(partes.query, max_num_fields=4)
                bruto = (campos.get("setor") or [""])[0]
                if bruto and (not bruto.isdecimal() or len(bruto) > 9):
                    return resposta(400, {"erro": "Setor inválido."})
                setor = int(bruto) if bruto else None
                setores = [dict(r) for r in banco.todos("SELECT id, nome FROM setores_impressao WHERE ativo = 1 ORDER BY ordem, nome")]
                if setor is not None and setor not in {s["id"] for s in setores}:
                    return resposta(400, {"erro": "Setor não encontrado."})
                itens = preparo.fila(setor)
                publico = [{k: r[k] for k in ("id", "quantidade", "produto", "observacao", "minutos",
                                              "status_preparo", "posicao_rotulo")} for r in itens[:300]]
                from src.core import formatacao as fmt
                return resposta(200, {"itens": publico, "total": len(itens), "setores": setores, "momento": fmt.agora(), "modo": modo})
            if caminho == "/cozinha/api/preparo" and metodo == "POST":
                if modo == "tv":
                    return resposta(403, {"erro": "Esta sessão é somente leitura (TV)."})
                uid, anterior, novo = dados.get("item_id"), dados.get("de"), dados.get("para")
                if type(uid) is not int or uid <= 0 or (anterior, novo) not in (
                        ("pendente", "em_preparo"), ("em_preparo", "entregue")):
                    return resposta(400, {"erro": "Transição inválida."})
                with banco.transacao():
                    try:
                        self._contexto(banco)
                    except ErroNegocio as exc:
                        return resposta(403, {"erro": str(exc)})
                    if not self.sessoes.valida(token):
                        return resposta(401, {"erro": "A configuração mudou. Entre novamente."})
                    item = next((r for r in preparo.fila() if r["id"] == uid), None)
                    if item is None or item["status_preparo"] != anterior:
                        return resposta(409, {"erro": "O item já mudou. Atualize a fila."})
                    preparo.marcar(uid, novo)
                    banco.log("cozinha_web_preparo", f"Item {uid}: {anterior} -> {novo}", operador.id)
                return resposta(200, {"ok": True, "situacao": novo})
            return resposta(404, {"erro": "Não encontrado."})
        finally:
            banco.fechar()


def handler(servidor):
    class Tratador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, formato, *args):
            log.info("%s %s", self.command, self.path.split("?", 1)[0])

        def do_GET(self):
            self._atender()

        def do_POST(self):
            self._atender()

        def do_HEAD(self):
            self._atender()

        def _atender(self):
            try:
                tamanho = int(self.headers.get("Content-Length", "0"))
                if tamanho < 0 or tamanho > MAX_CORPO:
                    status, cabecalhos, corpo = resposta(413, {"erro": "Pedido grande demais."})
                else:
                    if self.command == "POST":
                        self.connection.settimeout(5)
                    bruto = self.rfile.read(tamanho) if tamanho else b""
                    status, cabecalhos, corpo = servidor.tratar(self.command, self.path, self.headers, bruto, self.client_address[0])
            except Exception:
                log.exception("Falha no HTTP da cozinha.")
                status, cabecalhos, corpo = resposta(503, {"erro": "O caixa está ocupado. Tente novamente."})
            self.send_response(status)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            for nome, valor in cabecalhos:
                self.send_header(nome, valor)
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(corpo)
    return Tratador
