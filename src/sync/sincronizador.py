"""Segundo plano do PDV com a nuvem: renova a licença, avisa de versão nova e, se o painel do dono estiver ligado
(Configurações > Nuvem), envia as vendas fechadas e o retrato do caixa para o celular do dono (src/sync/painel_envio.py).

Roda separado da interface (`python -m src.app --sync`, ou `WillPDV.exe --sync` no executável), ou na thread opcional
ServicoSincronizacao com `sync_quase_tempo_real = S`. Lê o endereço, o token e a
chave da loja de Configurações > Nuvem. Sem endereço configurado não faz nada. Falha de rede só espera e tenta de novo.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import time

from src.core.instancia import InstanciaUnica
from src.database.conexao import RAIZ, BancoDados

log = logging.getLogger("pdv.sync")

INTERVALO_MINIMO = 5
ESPERA_MAXIMA = 600


def proxima_espera(base: int, falhas: int) -> int:
    """Segundos até a próxima rodada: o intervalo configurado, dobrando a cada falha seguida (até 10 min)."""
    base = max(base, INTERVALO_MINIMO)
    return min(base * 2 ** min(falhas, 6), max(base, ESPERA_MAXIMA))


class Sincronizador:
    def __init__(self, banco=None, http=None):
        self.banco = banco or BancoDados()
        self._http = http          # qualquer objeto com .get(url, headers=, timeout=) (nos testes, um falso)

    def configuracao(self) -> dict:
        b = self.banco
        return {"url": b.cfg("api_url").strip(), "token": b.cfg("api_token").strip(),
                "loja": b.cfg("chave_loja").strip(),
                "intervalo": INTERVALO_MINIMO if b.cfg_bool("sync_quase_tempo_real") else b.cfg_int("sync_intervalo_seg", 60)}

    def rodada(self) -> bool:
        # A janela e um --sync já instalado podem coexistir, mas só um envia por banco de cada vez.
        trava = InstanciaUnica(self.banco.caminho + ".sync") if self.banco.caminho != ":memory:" else None
        if trava is not None and not trava.adquirir():
            return True
        try:
            if self.banco.cfg_bool("sync_quase_tempo_real"):
                try:
                    desde = time.time() - float(self.banco.cfg("sync_ultima_rodada_epoch", "0"))
                except ValueError:
                    desde = INTERVALO_MINIMO
                if 0 <= desde < INTERVALO_MINIMO:
                    return True
            sucesso = self._rodada()
            if sucesso:
                self.banco.cfg_set("sync_ultima_rodada_epoch", time.time())
            return sucesso
        finally:
            if trava is not None:
                trava.liberar()

    def _rodada(self) -> bool:
        """Uma rodada: vê se há versão nova e renova a licença (cada um no máximo a cada 6 horas). Devolve False se falhou."""
        if not self.configuracao()["url"]:
            return True                              # nuvem desligada: nada a fazer
        self._ponte()
        sucesso = True
        try:
            from src.sync import atualizacoes, licenca_nuvem
            aviso = atualizacoes.verificar(self.banco, self._http)
            if aviso:
                log.info("Versão nova do PDV disponível: %s%s.", aviso["ultima"], " (CRÍTICA)" if aviso["critica"] else "")
            licenca_nuvem.renovar(self.banco, self._http)
        except Exception:
            log.exception("Falha ao consultar atualizações ou licença.")
            sucesso = False
        self._enviar_porteiro()
        self._enviar_cardapio()
        return self._enviar_painel() and sucesso

    def _ponte(self) -> None:
        """Central do fornecedor (opcional, não precisa do token da loja); tem intervalo e espera próprios."""
        try:
            from src.sync import ponte
            ponte.rodada(self.banco, self._http)
        except Exception:
            log.exception("Falha na comunicação com a central do fornecedor.")

    def _enviar_porteiro(self) -> None:
        """Retrato das comandas abertas para o porteiro no 4G. Falha aqui não atrasa a licença: a página local segue."""
        try:
            from src.porteiro import nuvem_envio
            nuvem_envio.enviar_se_preciso(self.banco, self._http)
        except Exception:
            log.exception("Falha ao enviar as comandas abertas para a nuvem.")

    def _enviar_cardapio(self) -> None:
        """Catálogo do cardápio digital. Falha aqui não segura a licença nem o painel: a próxima rodada tenta de novo."""
        try:
            from src.sync import cardapio_envio
            cardapio_envio.enviar(self.banco, self._http)
        except Exception:
            log.exception("Falha ao enviar o cardápio digital.")

    def _enviar_painel(self) -> bool:
        """Painel do dono (opcional): sobe as vendas que faltam e o retrato do caixa. Falha aqui só espera a próxima rodada."""
        try:
            from src.sync import painel_ritmo
            painel_ritmo.enviar_se_preciso(self.banco, self._http)
            return True
        except Exception:
            log.exception("Falha ao enviar os dados do painel do dono.")
            return False

    def iniciar_loop(self, rodadas: int | None = None, dormir=time.sleep) -> None:
        """Repete as rodadas; com falhas seguidas o intervalo dobra. `rodadas` limita o laço (testes)."""
        log.info("Verificação de licença e atualizações iniciada.")
        falhas = feitas = 0
        while rodadas is None or feitas < rodadas:
            feitas += 1
            falhas = 0 if self.rodada() else falhas + 1
            dormir(proxima_espera(self.configuracao()["intervalo"], falhas))


class ServicoSincronizacao:
    """Envio opcional na própria aplicação, com conexão SQLite exclusiva da thread e espera interrompível."""

    def __init__(self, caminho_banco: str, http=None):
        if str(caminho_banco) == ":memory:":
            raise ValueError("A sincronização em segundo plano precisa de banco em arquivo.")
        self.caminho = str(caminho_banco)
        self.http = http
        self._parar = threading.Event()
        self._thread = None

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="nuvem-caixa", daemon=True)
        self._thread.start()

    def parar(self, timeout: float = 3) -> None:
        self._parar.set()
        if self._thread:
            self._thread.join(timeout)

    def _laco(self) -> None:
        try:
            banco = BancoDados(self.caminho, semear=False)
            try:
                sync = Sincronizador(banco, self.http)
                falhas = 0
                proxima = 0.0
                while not self._parar.is_set():
                    if not banco.cfg_bool("sync_quase_tempo_real"):
                        proxima = 0.0
                        falhas = 0
                    elif time.monotonic() >= proxima:
                        try:
                            sucesso = sync.rodada()
                        except Exception:
                            log.exception("Falha na sincronização automática; uma nova tentativa será feita.")
                            sucesso = False
                        falhas = 0 if sucesso else falhas + 1
                        proxima = time.monotonic() + proxima_espera(INTERVALO_MINIMO, falhas)
                    self._parar.wait(1)
            finally:
                banco.fechar()
        except Exception:
            log.exception("Serviço de sincronização indisponível.")


def configurar_log() -> None:
    pasta = RAIZ / "logs"
    pasta.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.handlers.RotatingFileHandler(
        pasta / "sync.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")]
    if sys.stderr is not None:          # no executável sem console não há stderr
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    configurar_log()
    Sincronizador().iniciar_loop()


if __name__ == "__main__":
    main()
