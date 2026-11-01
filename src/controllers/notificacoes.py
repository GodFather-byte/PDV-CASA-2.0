"""Gancho antigo dos avisos do caixa.

O Telegram saiu. Quem chama `avisar` (fechamento, cancelamento, sangria, backup) continua
igual: a função não faz rede e não grava fila. O resumo do dono sai no WhatsApp, no fechamento
e no botão do painel.
"""
from __future__ import annotations


def avisar(banco, tipo: str, montar, *args) -> None:
    """Não envia nada. Existe para o caixa não depender de um bot."""
    return None
