"""Atualização independente do envio de vendas: não exige sincronização quase em tempo real."""
import logging
import threading
from src.database.conexao import BancoDados
from src.atualizacao.cliente import rodada, disparar_instalacao

log = logging.getLogger('pdv.atualizacao')

class ServicoAtualizacao:
    def __init__(self, caminho_banco):
        if str(caminho_banco) == ':memory:':
            raise ValueError('Atualização automática exige banco em arquivo.')
        self.caminho = str(caminho_banco)
        self._parar = threading.Event()
        self._thread = None

    @property
    def ativo(self):
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self):
        if self.ativo:
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name='atualizacao-programa', daemon=True)
        self._thread.start()

    def parar(self, timeout=3):
        self._parar.set()
        if self._thread:
            self._thread.join(timeout)

    def _laco(self):
        banco = None
        try:
            banco = BancoDados(self.caminho, semear=False)
            if banco.remoto:
                return
            central = None
            while not self._parar.is_set():
                try:
                    rodada(banco, instalar=disparar_instalacao)
                except Exception:
                    log.exception('Atualização automática não concluída; o caixa continua disponível.')
                if not banco.cfg_bool('sync_quase_tempo_real'):       # ligado, a sincronização do próprio PDV já ouve
                    try:
                        if central is None:
                            from src.sync.sincronizador import Sincronizador
                            central = Sincronizador(banco)
                        central.atender_central()
                    except Exception:
                        log.exception('Não consegui ouvir o pedido de atualização da central.')
                self._parar.wait(30)
        except Exception:
            log.exception('Não foi possível iniciar o verificador de atualização.')
        finally:
            if banco is not None:
                banco.fechar()
