"""Segundo plano do PDV com a nuvem: renova a licença, avisa de versão nova e, se o painel do dono estiver ligado
(Configurações > Nuvem), envia as vendas fechadas e o retrato do caixa para o celular do dono (src/sync/painel_envio.py).

Roda separado da interface (`python -m src.app --sync`, ou `WillPDV.exe --sync` no executável). Lê o endereço, o token e a
chave da loja de Configurações > Nuvem. Sem endereço configurado não faz nada. Falha de rede só espera e tenta de novo.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import time

from src.database.conexao import RAIZ, BancoDados

log = logging.getLogger("pdv.sync")

INTERVALO_MINIMO = 5
ESPERA_MAXIMA = 600


def proxima_espera(base: int, falhas: int) -> int:
    """Segundos até a próxima rodada: o intervalo configurado, dobrando a cada falha seguida (até 10 min)."""
    return min(max(base, INTERVALO_MINIMO) * 2 ** min(falhas, 6), ESPERA_MAXIMA)


class Sincronizador:
    def __init__(self, banco=None, http=None):
        self.banco = banco or BancoDados()
        self._http = http          # qualquer objeto com .get(url, headers=, timeout=) (nos testes, um falso)

    def configuracao(self) -> dict:
        b = self.banco
        return {"url": b.cfg("api_url").strip(), "token": b.cfg("api_token").strip(),
                "loja": b.cfg("chave_loja").strip(), "intervalo": b.cfg_int("sync_intervalo_seg", 60)}

    def rodada(self) -> bool:
        """Uma rodada: vê se há versão nova e renova a licença (cada um no máximo a cada 6 horas). Devolve False se falhou."""
        if not self.configuracao()["url"]:
            return True                              # nuvem desligada: nada a fazer
        self._ponte()
        try:
            from src.sync import atualizacoes, licenca_nuvem
            aviso = atualizacoes.verificar(self.banco, self._http)
            if aviso:
                log.info("Versão nova do PDV disponível: %s%s.", aviso["ultima"], " (CRÍTICA)" if aviso["critica"] else "")
            licenca_nuvem.renovar(self.banco, self._http)
        except Exception:
            log.exception("Falha ao consultar atualizações ou licença.")
            return False
        return self._enviar_painel()

    def _ponte(self) -> None:
        """Central do fornecedor (opcional, não precisa do token da loja); tem intervalo e espera próprios."""
        try:
            from src.sync import ponte
            ponte.rodada(self.banco, self._http)
        except Exception:
            log.exception("Falha na comunicação com a central do fornecedor.")

    def _enviar_painel(self) -> bool:
        """Painel do dono (opcional): sobe as vendas que faltam e o retrato do caixa. Falha aqui só espera a próxima rodada."""
        try:
            from src.sync import painel_envio
            painel_envio.enviar(self.banco, self._http)
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
