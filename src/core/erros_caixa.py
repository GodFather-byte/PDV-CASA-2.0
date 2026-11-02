"""Fila local dos erros do caixa. Sobe no mesmo lote da nuvem, sem chamada extra.

Não grava segredo: token, senha, autorização, e-mail, telefone e documento saem do texto
antes de gravar. Erros iguais somam em `vezes`.
"""
from __future__ import annotations

import hashlib
import re
import traceback

from src.core import formatacao as fmt
from src.versao import VERSAO

LIMITE_FILA = 80
LIMITE_TEXTO = 2000
_banco = None

_BEARER = re.compile(r"(?i)bearer\s+\S+")
_SEGREDO = re.compile(r"(?i)\b(api[_-]?token|token|senha|password|authorization|secret)\b\s*[=:]\s*\S+")
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_FONE = re.compile(r"\b(?:\+55\s?)?\(?\d{2}\)?\s?9\d{4}-?\d{4}\b")


def ligar(banco) -> None:
    global _banco
    _banco = banco


def limpar_texto(texto: str) -> str:
    texto = texto or ""
    texto = _BEARER.sub("Bearer [omitido]", texto)
    texto = _SEGREDO.sub(lambda m: f"{m.group(1)}=[omitido]", texto)
    texto = _EMAIL.sub("[omitido]", texto)
    texto = _CPF.sub("[omitido]", texto)
    texto = _FONE.sub("[omitido]", texto)
    return texto.replace("\x00", "")[:LIMITE_TEXTO]


def assinatura(nivel: str, modulo: str, mensagem: str, trilha: str) -> str:
    miolo = "\n".join((trilha or "").splitlines()[:8])
    bruto = f"{nivel}|{modulo}|{mensagem}|{miolo}".encode("utf-8", "replace")
    return hashlib.sha256(bruto).hexdigest()


def registrar(nivel: str, modulo: str, mensagem: str, trilha: str = "", contexto: str = "", banco=None) -> None:
    """Grava ou soma o erro. Nunca levanta: um erro no registro não pode derrubar o caixa."""
    alvo = banco if banco is not None else _banco
    if alvo is None:
        return
    try:
        nivel = (nivel or "error")[:20]
        modulo = limpar_texto(modulo or "caixa")[:80]
        mensagem = limpar_texto(mensagem or "")[:300]
        trilha = limpar_texto(trilha or "")
        contexto = limpar_texto(f"versao={VERSAO} {contexto or ''}")[:300]
        chave = assinatura(nivel, modulo, mensagem, trilha)
        agora = fmt.agora()
        existente = alvo.um("SELECT id, vezes FROM erros_caixa WHERE assinatura = ?", (chave,))
        if existente:
            alvo.executar("UPDATE erros_caixa SET vezes = ?, atualizado_em = ?, enviado = 0 WHERE id = ?",
                          (int(existente["vezes"]) + 1, agora, existente["id"]))
        else:
            alvo.inserir("erros_caixa", {
                "criado_em": agora, "atualizado_em": agora, "nivel": nivel, "modulo": modulo,
                "mensagem": mensagem, "traceback": trilha, "contexto": contexto,
                "assinatura": chave, "vezes": 1, "enviado": 0})
        _podar(alvo)
    except Exception:
        return


def pendentes(banco) -> list[dict]:
    try:
        return [dict(r) for r in banco.todos(
            "SELECT * FROM erros_caixa WHERE enviado = 0 ORDER BY id LIMIT 20")]
    except Exception:
        return []


def marcar_enviados(banco, assinaturas: list[str]) -> None:
    if not assinaturas:
        return
    marcas = ",".join("?" for _ in assinaturas)
    banco.executar(f"UPDATE erros_caixa SET enviado = 1 WHERE assinatura IN ({marcas})", tuple(assinaturas))


def _podar(banco) -> None:
    sobra = banco.valor("SELECT COUNT(*) FROM erros_caixa", (), 0) - LIMITE_FILA
    if sobra > 0:
        banco.executar(
            "DELETE FROM erros_caixa WHERE id IN (SELECT id FROM erros_caixa ORDER BY enviado DESC, id LIMIT ?)",
            (sobra,))


def texto_excecao(tipo, valor, tb) -> tuple[str, str]:
    mensagem = limpar_texto("".join(traceback.format_exception_only(tipo, valor)).strip())
    trilha = limpar_texto("".join(traceback.format_exception(tipo, valor, tb)))
    return mensagem, trilha
