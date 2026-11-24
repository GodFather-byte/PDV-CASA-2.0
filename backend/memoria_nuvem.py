"""Pedido de sincronização e credenciais em memória.

O Render pago fica ligado; o Neon não. Estas estruturas nunca abrem banco: o botão do celular
grava um pedido por loja, e o caixa lê esse pedido num GET leve. O token da loja e a sessão do
painel só entram aqui depois de uma autenticação que já aconteceu (login ou envio). Sem isso na
memória, a resposta é "não conhecido" — não há consulta ao PostgreSQL para descobrir.
"""
from __future__ import annotations

import hashlib
import threading
import time

TTL_TOKEN_SEG = 24 * 3600
TTL_SESSAO_SEG = 12 * 3600
TTL_PEDIDO_SEG = 90
TTL_TOKEN_NEGATIVO_SEG = 10 * 60
TTL_CONCLUSAO_SEG = 10 * 60
TTL_ATUALIZAR_SEG = 6 * 3600     # o botão "Atualizar o caixa agora" da central vale por 6 horas (caixa desligado pega quando ligar)


class MemoriaNuvem:
    def __init__(self):
        self._trava = threading.Lock()
        self._tokens: dict[str, tuple[str, float]] = {}
        self._sessoes: dict[str, tuple[str, float]] = {}
        self._pedidos: dict[str, dict] = {}
        self._conclusoes: dict[str, dict] = {}
        self._tokens_desconhecidos: dict[str, float] = {}
        self._atualizar: dict[str, dict] = {}
        self._seq = 0

    def zerar(self) -> None:
        with self._trava:
            self._tokens.clear()
            self._sessoes.clear()
            self._pedidos.clear()
            self._conclusoes.clear()
            self._tokens_desconhecidos.clear()
            self._atualizar.clear()
            self._seq = 0

    def lembrar_token(self, token: str, chave: str) -> None:
        self._guardar(self._tokens, token, chave, TTL_TOKEN_SEG)

    def lembrar_sessao(self, token: str, chave: str) -> None:
        self._guardar(self._sessoes, token, chave, TTL_SESSAO_SEG)

    def _guardar(self, tabela: dict, token: str, chave: str, ttl: float) -> None:
        if not token or not chave:
            return
        with self._trava:
            tabela[_hash(token)] = (chave, time.monotonic() + ttl)

    def chave_do_token(self, token: str) -> str | None:
        return self._ler(self._tokens, token)

    def chave_da_sessao(self, token: str) -> str | None:
        return self._ler(self._sessoes, token)

    def _ler(self, tabela: dict, token: str) -> str | None:
        if not token:
            return None
        agora = time.monotonic()
        with self._trava:
            achado = tabela.get(_hash(token))
            if achado is None:
                return None
            chave, expira = achado
            if expira < agora:
                tabela.pop(_hash(token), None)
                return None
            return chave

    def pedir(self, chave: str) -> dict:
        agora = time.monotonic()
        with self._trava:
            self._seq += 1
            self._pedidos[chave] = {"id": self._seq, "em": agora}
            return {"conhecido": True, "pedido": True, "id": self._seq}

    def pedir_atualizacao(self, chave: str) -> int:
        """A central pede que os caixas da loja instalem a versão nova já. Cada caixa guarda o id que já atendeu."""
        with self._trava:
            # Segundos do relógio, não o contador: depois de um reinício do servidor o número não se repete.
            anterior = self._atualizar.get(chave, {}).get("id", 0)
            ident = max(int(time.time()), anterior + 1)
            self._atualizar[chave] = {"id": ident, "em": time.monotonic()}
            return ident

    def _atualizacao_pedida(self, chave: str, agora: float) -> int:
        """Chamado com a trava já tomada."""
        ped = self._atualizar.get(chave)
        if ped is None:
            return 0
        if agora - ped["em"] > TTL_ATUALIZAR_SEG:
            self._atualizar.pop(chave, None)
            return 0
        return ped["id"]

    def token_ja_descartado(self, token: str) -> bool:
        """Token que não é de loja: não consulta o banco de novo por alguns minutos."""
        if not token:
            return True
        agora = time.monotonic()
        with self._trava:
            expira = self._tokens_desconhecidos.get(_hash(token))
            if expira is None:
                return False
            if expira < agora:
                self._tokens_desconhecidos.pop(_hash(token), None)
                return False
            return True

    def descartar_token(self, token: str) -> None:
        if not token:
            return
        with self._trava:
            self._tokens_desconhecidos[_hash(token)] = time.monotonic() + TTL_TOKEN_NEGATIVO_SEG

    def consultar_loja(self, token: str) -> dict:
        """O caixa pergunta se o celular pediu envio. Não abre banco."""
        chave = self.chave_do_token(token)
        if not chave:
            return {"conhecido": False, "pedido": False}
        agora = time.monotonic()
        with self._trava:
            atualizar = self._atualizacao_pedida(chave, agora)
            extra = {"atualizar": atualizar} if atualizar else {}
            ped = self._pedidos.get(chave)
            if ped is None or agora - ped["em"] > TTL_PEDIDO_SEG:
                self._pedidos.pop(chave, None)
                return {"conhecido": True, "pedido": False, **extra}
            return {"conhecido": True, "pedido": True, "id": ped["id"], **extra}

    def concluir(self, token: str, momento: str, pedido_id: int | None = None) -> dict:
        chave = self.chave_do_token(token)
        if not chave:
            return {"conhecido": False}
        with self._trava:
            ped = self._pedidos.get(chave)
            ident = int(pedido_id or 0) or (ped["id"] if ped else 0)
            self._conclusoes[chave] = {"id": ident, "momento": (momento or "")[:19], "em": time.monotonic()}
            if ped and ped["id"] == ident:
                self._pedidos.pop(chave, None)
            return {"conhecido": True, "id": ident, "momento": self._conclusoes[chave]["momento"]}

    def estado(self, token: str) -> dict:
        """O celular espera o caixa terminar. Só memória."""
        chave = self.chave_da_sessao(token)
        if chave is None:
            chave = self._sessao_porteiro(token)
        if not chave:
            return {"conhecido": False, "momento": "", "id": 0}
        agora = time.monotonic()
        with self._trava:
            conc = self._conclusoes.get(chave)
            if conc is None or agora - conc["em"] > TTL_CONCLUSAO_SEG:
                return {"conhecido": True, "momento": "", "id": 0}
            return {"conhecido": True, "momento": conc["momento"], "id": conc["id"]}

    def _sessao_porteiro(self, token: str) -> str | None:
        """A sessão do porteiro já nasce na memória do processo (PIN). Não consulta o banco."""
        try:
            from backend.porteiro import sessoes
        except Exception:
            return None
        achado = sessoes.ler(token)
        if achado is None:
            return None
        return achado[0]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


memoria = MemoriaNuvem()


def token_do_cabecalho(authorization: str | None) -> str:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:].strip()
    return ""
