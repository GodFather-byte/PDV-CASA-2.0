"""Avisos do caixa para o celular do dono (Telegram).

Os controladores do caixa chamam `avisar(...)` quando algo importante acontece (caixa fechou, cupom cancelado, sangria...).
Aqui o aviso só é GRAVADO na fila (milissegundos) e uma thread o envia depois, então internet fora do ar nunca atrasa nem
derruba o caixa. `avisar` NUNCA levanta erro: no pior caso o aviso se perde, a venda não.
"""
from __future__ import annotations

import logging
import threading

from src.core import formatacao as fmt

log = logging.getLogger("pdv.telegram")

# Acorda a thread de envio assim que entra um aviso (senão ela só olha de tempos em tempos).
ACORDAR = threading.Event()

# tipo do aviso -> chave de configuração que liga/desliga (None = sempre que o Telegram estiver ligado)
CHAVES = {"turno": "telegram_avisa_turno", "cancelamento": "telegram_avisa_cancelamento", "item": "telegram_avisa_item",
          "sangria": "telegram_avisa_sangria", "backup": "telegram_avisa_backup", "venda": "telegram_avisa_venda",
          "estoque": "telegram_avisa_estoque", "resumo": None}
# Quando a chave ainda não existe no banco (instalação antiga): o que vale. Só o aviso de cada venda nasce desligado.
PADRAO = {"venda": False}


def ligado(banco, tipo: str | None = None) -> bool:
    """O Telegram está pronto (ligado, com token e ao menos um celular pareado) e este tipo de aviso está permitido."""
    if not banco.cfg_bool("telegram_ativo", False) or not banco.cfg("telegram_token").strip():
        return False
    chave = CHAVES.get(tipo)
    if chave and not banco.cfg_bool(chave, PADRAO.get(tipo, True)):
        return False
    return bool(banco.valor("SELECT 1 FROM telegram_chats LIMIT 1"))


def enfileirar(banco, tipo: str, texto: str) -> int:
    item_id = banco.inserir("telegram_fila", {"criado_em": fmt.agora(), "tipo": tipo, "texto": texto})
    ACORDAR.set()
    return item_id


def avisar(banco, tipo: str, montar, *args) -> None:
    """Grava o aviso na fila se o Telegram estiver ligado para este tipo.

    `montar` diz como escrever o texto e só roda quando o aviso realmente vai sair (com o Telegram desligado o custo é a
    leitura de uma configuração): um nome de função de `telegram_textos` (chamada com `banco, *args`), uma função sem
    argumentos ou o próprio texto. O nome em vez do import evita ciclo (os textos usam os mesmos controladores que avisam)."""
    try:
        if not ligado(banco, tipo):
            return
        if isinstance(montar, str) and hasattr(_textos(), montar):
            texto = getattr(_textos(), montar)(banco, *args)
        else:
            texto = montar() if callable(montar) else montar
        if texto:
            enfileirar(banco, tipo, texto)
    except Exception:  # noqa: BLE001 - aviso é acessório: jamais pode atrapalhar o caixa
        log.exception("Não foi possível gravar o aviso do Telegram (%s).", tipo)


def _textos():
    import importlib
    return importlib.import_module("src.controllers.telegram_textos")
