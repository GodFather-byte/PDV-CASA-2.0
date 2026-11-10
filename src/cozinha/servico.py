"""Mantém a cozinha web no caixa principal e acompanha liga/desliga e troca de porta."""
import logging
import re
import sqlite3
import threading
from src.core import seguranca
from src.core.erros import ErroNegocio
from src.controllers.acesso_controller import AcessoController
from src.porteiro.servico import ips_da_rede, porta_configurada
from src.cozinha.servidor import ServidorCozinha

PORTA_PADRAO = 8766
log = logging.getLogger("pdv.cozinha_web")


def configurar(banco, ativo, porta, pin, operador_id, autor_id):
    if banco.remoto:
        raise ErroNegocio("Configure a cozinha web no caixa principal.")
    acesso = AcessoController(banco)
    autor = banco.um("SELECT id FROM operadores WHERE id = ? AND ativo = 1", (autor_id,))
    if autor is None:
        raise ErroNegocio("Operador inativo.")
    acesso.exigir(acesso.operador(autor_id), "cfg_configuracoes")
    porta = porta_configurada(porta, PORTA_PADRAO)
    if porta is None:
        raise ErroNegocio("Porta de 1024 a 65535.")
    if ativo and not banco.cfg_bool("usar_cozinha_bar"):
        raise ErroNegocio("Ligue o módulo Cozinha/Bar primeiro.")
    if ativo:
        if type(operador_id) is not int or not banco.um("SELECT id FROM operadores WHERE id = ? AND ativo = 1", (operador_id,)):
            raise ErroNegocio("Escolha um operador ativo para identificar as ações da cozinha.")
        acesso.exigir(acesso.operador(operador_id), "util_cozinha")
    if pin and not re.fullmatch(r"[0-9]{6,8}", pin):
        raise ErroNegocio("O PIN da cozinha deve ter de 6 a 8 números.")
    if ativo and not pin and not banco.cfg("cozinha_web_pin_hash"):
        raise ErroNegocio("Defina o PIN da cozinha.")
    with banco.transacao():
        if pin:
            banco.cfg_set("cozinha_web_pin_hash", seguranca.gerar_hash(pin))
        banco.cfg_set("cozinha_web_porta", str(porta))
        banco.cfg_set("cozinha_web_operador_id", str(operador_id or ""))
        banco.cfg_set("cozinha_web_ativo", "S" if ativo else "N")
        banco.log("cozinha_web_config", "Configuração da cozinha web atualizada", autor_id)


def urls(porta):
    return [f"http://{ip}:{porta}/cozinha/" for ip in (ips_da_rede() or ["127.0.0.1"])]


class ServicoCozinha:
    def __init__(self, caminho_banco, intervalo=2, host="0.0.0.0"):
        if str(caminho_banco) == ":memory:":
            raise ErroNegocio("A cozinha web precisa de banco em arquivo.")
        self.caminho, self.intervalo, self.host = caminho_banco, intervalo, host
        self.erro_cozinha = None
        self._parar = threading.Event()
        self._thread = None
        self._servidor = None
        self._lock = threading.Lock()

    @property
    def ativo(self):
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self):
        if self.ativo:
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="cozinha-web", daemon=True)
        self._thread.start()

    def parar(self, timeout=3):
        self._parar.set()
        if self._thread:
            self._thread.join(timeout)
        with self._lock:
            self._desligar()

    def _laco(self):
        try:
            while not self._parar.is_set():
                try:
                    self._sincronizar()
                except (sqlite3.Error, OSError):
                    self.erro_cozinha = "Não foi possível acessar o banco da cozinha."
                    log.warning("Cozinha web: banco temporariamente indisponível.")
                self._parar.wait(self.intervalo)
        finally:
            with self._lock:
                self._desligar()

    def _desligar(self):
        servidor, self._servidor = self._servidor, None
        if servidor:
            servidor.parar()

    def _sincronizar(self):
        con = sqlite3.connect(self.caminho, timeout=5)
        try:
            cfg = dict(con.execute("SELECT chave, valor FROM config WHERE chave IN "
                "('cozinha_web_ativo','cozinha_web_porta','cozinha_web_pin_hash','usar_cozinha_bar')"))
        except sqlite3.Error:
            self.erro_cozinha = "Não foi possível ler a configuração da cozinha."
            return
        finally:
            con.close()
        porta = porta_configurada(cfg.get("cozinha_web_porta"), PORTA_PADRAO)
        ligado = cfg.get("cozinha_web_ativo") == "S" and cfg.get("usar_cozinha_bar") == "S" and cfg.get("cozinha_web_pin_hash")
        with self._lock:
            if self._parar.is_set():
                self._desligar()
                return
            if not ligado or porta is None:
                self._desligar()
                return
            if self._servidor and self._servidor.ativo and self._servidor.porta == porta:
                return
            self._desligar()
            try:
                servidor = ServidorCozinha(self.caminho, porta, self.host)
                servidor.iniciar()
                self._servidor = servidor
                self.erro_cozinha = None
            except OSError:
                self.erro_cozinha = f"A porta {porta} não abriu; confira se já está em uso."
                log.warning("Cozinha web: não foi possível abrir a porta %s.", porta)
