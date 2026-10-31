"""Liga e desliga a página do porteiro conforme a configuração do caixa.

A thread só existe com banco em arquivo (o SQLite em memória não é compartilhado). O HTTP sobe
quando o porteiro está ligado, o PIN existe e a casa usa mesas ou comandas. Fora isso, a porta fecha.
"""
from __future__ import annotations

import io
import logging
import re
import socket
import sqlite3
import threading

from src.core import seguranca
from src.core.erros import ErroNegocio
from src.porteiro.servidor import ServidorPorteiro

log = logging.getLogger("pdv.porteiro")

PORTA_PADRAO = 8765
_PIN = re.compile(r"\d{4,8}")
_CHAVES = ("porteiro_ativo", "porteiro_porta", "porteiro_pin_hash", "usar_mesas")


def definir_pin(banco, pin: str) -> None:
    """Grava só o hash. O PIN em claro não fica no banco nem no log."""
    pin = (pin or "").strip()
    if not _PIN.fullmatch(pin):
        raise ErroNegocio("O PIN do porteiro precisa ter de 4 a 8 números.")
    banco.cfg_set("porteiro_pin_hash", seguranca.gerar_hash(pin))
    banco.log("porteiro_pin", "PIN do porteiro atualizado")


def porta_configurada(valor, padrao: int = PORTA_PADRAO) -> int | None:
    try:
        porta = int(str(valor).strip() or padrao)
    except ValueError:
        return None
    if 1024 <= porta <= 65535:
        return porta
    return None


def ips_da_rede() -> list[str]:
    """Endereço de saída deste computador, sem consulta de DNS (o nome da máquina pode não resolver)."""
    achados: list[str] = []
    sonda = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP não envia pacote ao conectar: só descobre a interface de saída.
        sonda.settimeout(0.2)
        sonda.connect(("192.0.2.1", 9))
        achados.append(sonda.getsockname()[0])
    except OSError:
        pass
    finally:
        sonda.close()
    vistos = []
    for ip in achados:
        if ip and not ip.startswith("127.") and ip not in vistos:
            vistos.append(ip)
    return vistos


def urls_publicas(porta: int) -> list[str]:
    ips = ips_da_rede() or ["127.0.0.1"]
    return [f"http://{ip}:{porta}/porteiro" for ip in ips]


def url_do_qr(urls: list[str]) -> str:
    for url in urls:
        if "://127." not in url and "://localhost" not in url:
            return url
    return urls[0] if urls else ""


def png_qr(texto: str, escala: int = 8) -> bytes:
    """QR do endereço, para o celular abrir a página. A biblioteca segno não usa a rede."""
    import segno
    buf = io.BytesIO()
    segno.make(texto, error="m").save(buf, kind="png", scale=escala, border=2, dark="#0b1220", light="#ffffff")
    return buf.getvalue()


def _ler_config(caminho: str) -> dict:
    con = sqlite3.connect(caminho, timeout=5)
    try:
        marcas = ",".join("?" * len(_CHAVES))
        linhas = con.execute(f"SELECT chave, valor FROM config WHERE chave IN ({marcas})", _CHAVES)
        return {chave: valor for chave, valor in linhas}
    finally:
        con.close()


def _ligado(cfg: dict) -> bool:
    return str(cfg.get("porteiro_ativo", "N")).strip().upper() in ("S", "1", "SIM", "TRUE")


def _mesas(cfg: dict) -> bool:
    return str(cfg.get("usar_mesas", "S")).strip().upper() in ("S", "1", "SIM", "TRUE")


def porta_desejada(cfg: dict) -> int | None:
    """A porta em que escutar, ou None se a página deve ficar fechada."""
    if not _mesas(cfg) or not _ligado(cfg) or not (cfg.get("porteiro_pin_hash") or "").strip():
        return None
    return porta_configurada(cfg.get("porteiro_porta", PORTA_PADRAO))


def descrever(banco, erro: str | None = None) -> str:
    """Texto curto para o menu do caixa. Vazio se a casa não usa comanda."""
    if not banco.cfg_bool("usar_mesas", True):
        return ""
    if not banco.cfg_bool("porteiro_ativo", False):
        return "Porteiro no celular desligado. Abra o menu Porteiro no celular para ligar."
    if not (banco.cfg("porteiro_pin_hash") or "").strip():
        return "Porteiro no celular: falta o PIN. Defina no menu Porteiro no celular."
    if erro:
        return f"Porteiro no celular: {erro}"
    porta = porta_configurada(banco.cfg("porteiro_porta", str(PORTA_PADRAO)))
    if porta is None:
        return "Porteiro no celular: porta inválida. Use um número de 1024 a 65535."
    urls = urls_publicas(porta)
    if urls and all("://127." in url for url in urls):
        return ("Porteiro no celular: não achei o IP desta rede. "
                f"{urls[0]} (só neste computador).")
    return "Porteiro no celular: " + " · ".join(urls)


class ServicoPorteiro:
    """Acompanha a configuração e mantém o HTTP no ar só enquanto o porteiro está ligado."""

    def __init__(self, caminho_banco: str, intervalo: float = 2.0, host: str = "0.0.0.0"):
        if str(caminho_banco) == ":memory:":
            raise ErroNegocio("O porteiro em segundo plano precisa de banco em arquivo.")
        self.caminho = caminho_banco
        self.intervalo = intervalo
        self.host = host
        self.erro_porteiro: str | None = None
        self._parar = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._servidor: ServidorPorteiro | None = None

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="porteiro", daemon=True)
        self._thread.start()

    def parar(self, timeout: float = 3) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout)
        with self._lock:
            self._desligar()

    def _laco(self) -> None:
        while not self._parar.is_set():
            self._sincronizar()
            self._enviar_nuvem()
            if self._parar.wait(self.intervalo):
                break
        with self._lock:
            self._desligar()

    def _enviar_nuvem(self) -> None:
        """Fora do cadeado do HTTP: um envio lento não impede a página local de subir ou descer.
        Sem nuvem configurada nem abre o banco inteiro (a maioria das casas não usa o 4G)."""
        if self._parar.is_set():
            return
        try:
            cfg = _ler_config(self.caminho)
            con = sqlite3.connect(self.caminho, timeout=5)
            try:
                extras = dict(con.execute(
                    "SELECT chave, valor FROM config WHERE chave IN ('api_url', 'api_token')"))
            finally:
                con.close()
        except sqlite3.Error:
            return
        cfg.update(extras)
        if porta_desejada(cfg) is None or not (cfg.get("api_url") or "").strip() or not (cfg.get("api_token") or "").strip():
            return
        try:
            from src.database.conexao import BancoDados
            from src.porteiro import nuvem_envio
            banco = BancoDados(self.caminho, semear=False)
            try:
                nuvem_envio.enviar_se_preciso(banco)
            finally:
                banco.fechar()
        except Exception:
            log.exception("Falha ao enviar as comandas para a nuvem.")

    def _sincronizar(self) -> None:
        with self._lock:
            if self._parar.is_set():
                return
            try:
                porta = porta_desejada(_ler_config(self.caminho))
            except sqlite3.Error as exc:
                self.erro_porteiro = "não consegui ler a configuração do caixa."
                log.warning("Porteiro sem configuração: %s", exc)
                return
            if porta is None:
                self._desligar()
                self.erro_porteiro = None
                return
            if self._servidor is not None and self._servidor.ativo and self._servidor.porta == porta:
                return
            self._desligar()
            try:
                self._servidor = ServidorPorteiro(self.caminho, porta, self.host)
                self._servidor.iniciar()
            except OSError as exc:
                self._servidor = None
                self.erro_porteiro = f"a porta {porta} não abriu (já está em uso?)."
                log.warning("Porteiro não escutou na porta %s: %s", porta, exc)
            else:
                self.erro_porteiro = None
                log.info("Porteiro escutando em %s:%s", self.host, self._servidor.porta)

    def _desligar(self) -> None:
        servidor, self._servidor = self._servidor, None
        if servidor is not None:
            servidor.parar()
