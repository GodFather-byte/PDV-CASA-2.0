"""Cliente mínimo da Bot API do Telegram (só biblioteca padrão: nada a instalar no computador da loja).

O PDV só faz conexões DE SAÍDA para api.telegram.org (HTTPS, porta 443): não abre porta, não precisa de IP fixo nem de
servidor. O token do bot nunca entra em mensagens de erro nem em log.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

URL_BASE = "https://api.telegram.org"
LIMITE_TEXTO = 4096       # o Telegram recusa mensagem maior que isto


class ErroTelegram(Exception):
    """Falha ao falar com o Telegram. `codigo` é o código HTTP/Telegram quando houve resposta (401 = token errado,
    403 = o dono bloqueou o bot, 429 = muitas mensagens), ou None quando nem chegou lá (sem internet)."""

    def __init__(self, mensagem: str, codigo: int | None = None):
        super().__init__(mensagem)
        self.codigo = codigo

    @property
    def definitivo(self) -> bool:
        """Repetir não adianta: o token está errado ou o dono bloqueou/removeu o bot."""
        return self.codigo in (400, 401, 403, 404)


def _http_padrao(url: str, dados: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(dados).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:      # usa o proxy do sistema, se houver
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except (ValueError, OSError):
            raise ErroTelegram(f"O Telegram respondeu com erro HTTP {e.code}.", e.code) from None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        # a URL (que contém o token) fica de fora da mensagem de propósito
        raise ErroTelegram("Sem conexão com o Telegram. Confira a internet do computador do caixa.") from None


class ClienteTelegram:
    def __init__(self, token: str, http=None):
        self.token = (token or "").strip()
        self._http = http or _http_padrao          # nos testes, um falso: http(url, dados, timeout) -> dict

    def _chamar(self, metodo: str, dados: dict | None = None, timeout: float = 15):
        if not self.token:
            raise ErroTelegram("Informe o token do bot.", 401)
        resposta = self._http(f"{URL_BASE}/bot{self.token}/{metodo}", dados or {}, timeout)
        if not resposta.get("ok"):
            raise ErroTelegram(resposta.get("description") or "O Telegram recusou o pedido.", resposta.get("error_code"))
        return resposta.get("result")

    def quem_sou(self) -> dict:
        """Dados do bot (confirma que o token é válido): {'id', 'username', 'first_name', ...}."""
        return self._chamar("getMe")

    def enviar(self, chat_id: int, texto: str, teclado: list[list[str]] | None = None) -> None:
        dados: dict = {"chat_id": chat_id, "text": texto[:LIMITE_TEXTO], "disable_web_page_preview": True}
        if teclado:
            dados["reply_markup"] = {"keyboard": [[{"text": t} for t in linha] for linha in teclado],
                                     "resize_keyboard": True, "is_persistent": True}
        self._chamar("sendMessage", dados)

    def atualizacoes(self, offset: int, espera: int = 25) -> list[dict]:
        """Mensagens novas. Com `espera`, o Telegram segura a conexão até chegar algo (resposta quase instantânea)."""
        return self._chamar("getUpdates", {"offset": offset, "timeout": espera, "allowed_updates": ["message"]},
                            timeout=espera + 10) or []
