"""NFC-e em segundo plano no caixa principal: põe as vendas fechadas na fila e envia ao provedor.

Roda a cada poucos segundos (o cupom fiscal sai logo depois do fechamento). Desligada (o padrão), só olha a
configuração. Caixa adicional não envia: o banco e a fila são do caixa principal.
"""
from __future__ import annotations

import logging
import threading

from src.database.conexao import BancoDados

log = logging.getLogger("pdv.fiscal")
INTERVALO_SEG = 4


class ServicoFiscal:
    def __init__(self, caminho_banco, intervalo: float = INTERVALO_SEG):
        if str(caminho_banco) == ":memory:":
            raise ValueError("A NFC-e em segundo plano exige banco em arquivo.")
        self.caminho = str(caminho_banco)
        self.intervalo = intervalo
        self._parar = threading.Event()
        self._thread = None

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="nfce", daemon=True)
        self._thread.start()

    def parar(self, timeout: float = 3) -> None:
        self._parar.set()
        if self._thread:
            self._thread.join(timeout)

    def _laco(self) -> None:
        from src.controllers.fiscal_controller import FiscalController
        banco = None
        try:
            banco = BancoDados(self.caminho, semear=False)
            if banco.remoto:
                return
            controle = FiscalController(banco)
            ambiente = None
            while not self._parar.is_set():
                try:
                    atual = controle.ambiente()
                    if atual != ambiente:                     # trocou de ambiente: outro token, outro endereço
                        controle = FiscalController(banco)
                        ambiente = atual
                    if atual:
                        controle.processar()
                except Exception:
                    log.exception("NFC-e: rodada não concluída; o caixa continua vendendo.")
                self._parar.wait(self.intervalo)
        except Exception:
            log.exception("Não foi possível iniciar a NFC-e em segundo plano.")
        finally:
            if banco is not None:
                banco.fechar()
