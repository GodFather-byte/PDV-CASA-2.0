"""Segundo plano do PDV com a nuvem: renova a licença, avisa de versão nova e, se o painel do dono estiver ligado
(Configurações > Nuvem), envia as vendas fechadas e o retrato do caixa para o celular do dono (src/sync/painel_envio.py).

Roda separado da interface (`python -m src.app --sync`, ou `WillPDV.exe --sync` no executável), ou na thread opcional
ServicoSincronizacao com `sync_quase_tempo_real = S`. Lê o endereço, o token e a
chave da loja de Configurações > Nuvem. Sem endereço configurado não faz nada. Falha de rede só espera e tenta de novo.

O banco na nuvem (Neon) só é chamado quando há o que enviar, na hora do fechamento, quando o celular pede,
ou na manutenção de licença/versão. O padrão é um lote a cada 15 minutos (`sync_lote_seg`). A pergunta
"o celular pediu atualização?" lê só a memória do servidor e pode ocorrer a cada 25 s.
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
        self._ultima_sonda = 0.0
        self._pedido_visto = None

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
            from src.sync import ociosidade
            pedido = self._pedido_remoto()
            forcar = pedido is not None or ociosidade.flush_pedido(self.banco)
            try:
                ultimo = float(self.banco.cfg("sync_ultima_rodada_epoch", "0") or 0)
            except ValueError:
                ultimo = 0.0
            agora = time.time()
            if not ociosidade.deve_contato(self.banco, agora, ultimo, forcar):
                return True
            sucesso = self._rodada(forcar=forcar)
            if sucesso:
                self.banco.cfg_set("sync_ultima_rodada_epoch", agora)
                if ociosidade.flush_pedido(self.banco):
                    self.banco.cfg_set(ociosidade.CHAVE_FLUSH, "")
                if pedido is not None:
                    self._avisar_conclusao(pedido)
            return sucesso
        finally:
            if trava is not None:
                trava.liberar()

    def _pedido_remoto(self):
        """Lê o pedido do celular na memória do Render. None se não há pedido ou ainda não deu o intervalo."""
        from src.sync import ociosidade
        agora = time.monotonic()
        if agora - self._ultima_sonda < ociosidade.SONDA_SEG:
            return None
        self._ultima_sonda = agora
        cfg = self.configuracao()
        if not cfg["url"] or not cfg["token"]:
            return None
        http = self._http
        if http is None:
            try:
                import requests as http
            except ImportError:
                return None
        try:
            resposta = http.get(ociosidade.url_pedido(cfg["url"]),
                                headers={"Authorization": f"Bearer {cfg['token']}"}, timeout=(3, 8))
            if getattr(resposta, "status_code", 0) != 200:
                return None
            dados = resposta.json()
        except Exception:
            log.debug("Não consultei o pedido de atualização do celular.", exc_info=True)
            return None
        if not isinstance(dados, dict) or not dados.get("pedido"):
            return None
        ident = dados.get("id")
        if ident == self._pedido_visto:
            return None
        self._pedido_visto = ident
        return ident

    def _avisar_conclusao(self, pedido) -> None:
        from src.core import formatacao as fmt
        from src.sync import ociosidade
        cfg = self.configuracao()
        if not cfg["url"] or not cfg["token"]:
            return
        http = self._http
        if http is None:
            try:
                import requests as http
            except ImportError:
                return
        try:
            http.post(ociosidade.url_concluido(cfg["url"]),
                      json={"momento": fmt.agora(), "id": pedido},
                      headers={"Authorization": f"Bearer {cfg['token']}"}, timeout=(3, 8))
        except Exception:
            log.debug("Não avisei o celular que o envio terminou.", exc_info=True)

    def _rodada(self, forcar: bool = False) -> bool:
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
        self._atualizar_programa()
        self._enviar_porteiro(forcar)
        self._enviar_cardapio()
        return self._enviar_painel(forcar) and sucesso

    def _ponte(self) -> None:
        """Central do fornecedor (opcional, não precisa do token da loja); tem intervalo e espera próprios."""
        try:
            from src.sync import ponte
            ponte.rodada(self.banco, self._http)
        except Exception:
            log.exception("Falha na comunicação com a central do fornecedor.")

    def _atualizar_programa(self) -> None:
        """Baixa a versão assinada e instala só com o caixa livre. Falha aqui não segura a licença."""
        try:
            from src.atualizacao.cliente import disparar_instalacao, rodada
            rodada(self.banco, self._http, instalar=disparar_instalacao)
        except Exception:
            log.exception("Falha ao atualizar o programa.")

    def _enviar_porteiro(self, forcar: bool = False) -> None:
        """Retrato das comandas abertas para o porteiro no 4G. Falha aqui não atrasa a licença: a página local segue."""
        try:
            from src.porteiro import nuvem_envio
            nuvem_envio.enviar_se_preciso(self.banco, self._http, forcar=forcar)
        except Exception:
            log.exception("Falha ao enviar as comandas abertas para a nuvem.")

    def _enviar_cardapio(self) -> None:
        """Catálogo do cardápio digital. Falha aqui não segura a licença nem o painel: a próxima rodada tenta de novo."""
        try:
            from src.sync import cardapio_envio
            cardapio_envio.enviar(self.banco, self._http)
        except Exception:
            log.exception("Falha ao enviar o cardápio digital.")

    def _enviar_painel(self, forcar: bool = False) -> bool:
        """Painel do dono (opcional): sobe as vendas que faltam e o retrato do caixa. Falha aqui só espera a próxima rodada."""
        try:
            from src.sync import painel_ritmo
            painel_ritmo.enviar_se_preciso(self.banco, self._http, forcar_batimento=forcar)
            return True
        except Exception:
            log.exception("Falha ao enviar os dados do painel do dono.")
            return False

    def iniciar_loop(self, rodadas: int | None = None, dormir=time.sleep) -> None:
        """Repete as rodadas. Sem falha, acorda a cada poucos segundos só para olhar a fila local.
        Com falhas seguidas a espera dobra. `rodadas` limita o laço (testes)."""
        from src.sync.ociosidade import ESPERA_LOCAL
        log.info("Verificação de licença e atualizações iniciada.")
        falhas = feitas = 0
        while rodadas is None or feitas < rodadas:
            feitas += 1
            falhas = 0 if self.rodada() else falhas + 1
            dormir(proxima_espera(self.configuracao()["intervalo"], falhas) if falhas else ESPERA_LOCAL)


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
