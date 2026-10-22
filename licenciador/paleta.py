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
        "fundo": "#101820", "painel": "#1a2735", "texto": "#f1f5f9", "suave": "#b3c2d1", "borda": "#2b3c4e",
        "marinho": "#1c2b3d", "marinho2": "#2f5fd0", "rotulo": "#78abff", "titulo": "#f1f5f9",
        "ok": "#52dfb4", "perigo": "#ff8d9b", "aviso": "#ffd078", "total": "#ff8d9b", "troco": "#78abff",
        "ok_fundo": "#17805a", "perigo_fundo": "#b83a45", "ok_hover": "#126a49", "perigo_hover": "#a8303b", "aviso_fundo": "#ffd078",
        "btn_hover": "#4170e0", "btn_off": "#34465a", "btn_off_texto": "#8497ad", "sobre": "#ffffff",
        "campo": "#0f1822", "papel": "#0f1822", "linha_par": "#1a2736", "selecao": "#2a4fb0", "selecao_texto": "#ffffff",
        "inativo": "#7d8da1", "virtual": "#7d8da1", "ok_linha": "#17382b", "ponto_linha": "#3d3414", "sem_linha": "#41191f",
    },
    "claro": {
        "fundo": "#eef1f8", "painel": "#ffffff", "texto": "#1c2438", "suave": "#5b6785", "borda": "#c9d1e6",
        "marinho": "#14234d", "marinho2": "#1f3a8a", "rotulo": "#1f3a8a", "titulo": "#14234d",
        "ok": "#157347", "perigo": "#b32d2d", "aviso": "#8a5a00", "total": "#9b1c1c", "troco": "#1f3a8a",
        "ok_fundo": "#157347", "perigo_fundo": "#b32d2d", "ok_hover": "#0f5c38", "perigo_hover": "#8f2323", "aviso_fundo": "#d9981e",
        "btn_hover": "#2c52c4", "btn_off": "#9aa6c6", "btn_off_texto": "#e5e9f5", "sobre": "#ffffff",
        "campo": "#ffffff", "papel": "#ffffff", "linha_par": "#f6f8fd", "selecao": "#cfe0ff", "selecao_texto": "#1c2438",
        "inativo": "#8a93ab", "virtual": "#9aa3b8", "ok_linha": "#cdeedb", "ponto_linha": "#fff0b3", "sem_linha": "#f6c8c8",
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
