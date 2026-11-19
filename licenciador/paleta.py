"""Modo claro e modo escuro: as duas paletas e a troca entre elas.

Só o gerador de licenças (Tk) usa este módulo: o PDV é Qt (`src/ui_qt/tema.py`). Trocar de modo é trocar o CONTEÚDO de
`tema.COR`, no mesmo lugar (as telas guardam a referência, não uma cópia).
"""
from __future__ import annotations

MODOS = {"escuro": "Escuro", "claro": "Claro"}
PADRAO = "escuro"
CHAVE = "tema_visual"

# ------------------------------------------------------------------ telas de cadastro, relatórios e janelas (tema.COR)
COR = {
    "escuro": {
        "fundo": "#101c20", "painel": "#192a2d", "texto": "#eef5ee", "suave": "#b2c4bd", "borda": "#3d5654",
        "marinho": "#153832", "marinho2": "#16684f", "rotulo": "#67e4b4", "titulo": "#eef5ee",
        "ok": "#68dfb2", "perigo": "#ffa9aa", "aviso": "#ffd18a", "total": "#ffa9aa", "troco": "#67e4b4",
        "ok_fundo": "#16694f", "perigo_fundo": "#9c3743", "ok_hover": "#208461", "perigo_hover": "#b24550", "aviso_fundo": "#ffd18a",
        "btn_hover": "#207c61", "btn_off": "#263b3b", "btn_off_texto": "#93a9a3", "sobre": "#ffffff",
        "campo": "#112123", "papel": "#112123", "linha_par": "#1a2d2e", "selecao": "#235e4e", "selecao_texto": "#ffffff",
        "inativo": "#8ea49d", "virtual": "#8ea49d", "ok_linha": "#173f33", "ponto_linha": "#41341e", "sem_linha": "#492a2e",
    },
    "claro": {
        "fundo": "#f2f3ed", "painel": "#ffffff", "texto": "#1b302e", "suave": "#475f58", "borda": "#bfccc3",
        "marinho": "#163932", "marinho2": "#11694f", "rotulo": "#11694f", "titulo": "#163932",
        "ok": "#126449", "perigo": "#a33640", "aviso": "#78500b", "total": "#9b3340", "troco": "#11694f",
        "ok_fundo": "#126449", "perigo_fundo": "#a33640", "ok_hover": "#0c503a", "perigo_hover": "#852832", "aviso_fundo": "#e9ad4c",
        "btn_hover": "#0c5840", "btn_off": "#dce3dc", "btn_off_texto": "#54645c", "sobre": "#ffffff",
        "campo": "#ffffff", "papel": "#ffffff", "linha_par": "#f0f4ee", "selecao": "#d5ecdb", "selecao_texto": "#1b302e",
        "inativo": "#677971", "virtual": "#6c7971", "ok_linha": "#d7eedf", "ponto_linha": "#fff0c8", "sem_linha": "#f9dcda",
    },
}

def modo() -> str:
    """O modo em uso agora: 'escuro' ou 'claro'."""
    return _modo


def validar(texto) -> str:
    """O código do modo para um texto qualquer da configuração (desconhecido vira o padrão)."""
    t = str(texto or "").strip().lower()
    return t if t in MODOS else PADRAO


def _trocar(destino: dict, origem: dict) -> None:
    destino.clear()
    destino.update(origem)


def aplicar(modo_novo: str) -> str:
    """Põe as cores do modo nos dicionários que as telas usam (no lugar, sem trocar os objetos). Devolve o modo aplicado."""
    global _modo
    m = _modo = validar(modo_novo)
    from licenciador import tema
    _trocar(tema.COR, COR[m])
    return m


def aplicar_da_configuracao(banco) -> str:
    """Lê `tema_visual` do banco e aplica."""
    return aplicar(banco.cfg(CHAVE, PADRAO))
