"""Campainha dos quartos: um ESP32 por quarto na rede local (Wi-Fi da casa), sem depender de internet.

O aparelho responde a GET http://<endereço>/<comando>, com os comandos:
    ping   -> 'ok' (está ligado e na rede)
    alerta -> LED piscando devagar (o tempo está acabando)
    tocar  -> campainha + LED piscando rápido (o tempo acabou)
    parar  -> desliga tudo
O programa do ESP32 (MicroPython) está em tools/esp32_campainha/main.py; guia em docs/QUARTOS.md.

O envio roda numa thread: a campainha fora do ar nunca trava a tela. O resultado (ligada ou não) volta por callback,
chamado na thread de envio (a tela Qt repassa por sinal).
"""
from __future__ import annotations

import threading
import urllib.request

COMANDOS = ("ping", "alerta", "tocar", "parar")
TIMEOUT_SEG = 2.0


def enviar(endereco: str, comando: str, timeout: float = TIMEOUT_SEG) -> bool:
    """Manda o comando e diz se o aparelho respondeu. Nunca levanta exceção de rede."""
    if comando not in COMANDOS:
        raise ValueError(f"comando de campainha inválido: {comando}")
    try:
        with urllib.request.urlopen(f"http://{endereco}/{comando}", timeout=timeout) as resposta:
            resposta.read(64)
            return 200 <= resposta.status < 300
    except Exception:  # noqa: BLE001 - qualquer falha de rede é só "campainha fora do ar"
        return False


def enviar_em_segundo_plano(endereco: str, comando: str, ao_terminar=None) -> threading.Thread:
    def rodar():
        ok = enviar(endereco, comando)
        if ao_terminar is not None:
            ao_terminar(ok)

    t = threading.Thread(target=rodar, name=f"campainha-{comando}", daemon=True)
    t.start()
    return t
