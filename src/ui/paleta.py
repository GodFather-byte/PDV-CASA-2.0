"""Modo claro e modo escuro: as duas paletas e a troca entre elas.

A interface lê as cores de quatro dicionários que existem desde sempre e que as telas importam (`tema.COR` das telas de cadastro,
`menu_widgets.PAL` do menu e da entrada, `caixa_tema.CX` do caixa e `painel_mesas.ESTADOS` dos cartões das comandas). Trocar de
modo é trocar o CONTEÚDO desses dicionários, no mesmo lugar (as telas guardam a referência, não uma cópia); o que for aberto depois
já sai na cor nova. A escolha fica na configuração `tema_visual` (Configurações > Aparência) e vale no começo do programa
(`aplicar_da_configuracao`) e na hora em que o operador grava (o `App` refaz o menu).

O modo claro das telas de cadastro é exatamente o visual que o programa sempre teve; o escuro é o do menu e do caixa estendido a elas.
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

# ------------------------------------------------------------------ menu principal e entrada (menu_widgets.PAL)
PAL = {
    "escuro": {
        "fundo": "#101820", "lateral": "#141f2b", "cabecalho": "#141f2b", "cartao": "#1a2735", "cartao_hover": "#233548",
        "borda": "#2b3c4e", "borda_hover": "#5a7b9b", "texto": "#f1f5f9", "suave": "#b3c2d1", "mudo": "#94a8bd",
        "azul": "#78abff", "verde": "#52dfb4", "ambar": "#ffd078", "vermelho": "#ff8d9b", "violeta": "#b8a1ff",
        "turquesa": "#33c4d8", "ardosia": "#7f93c9",
        "sobre": "#0a1022", "selecao": "#27407f", "selecao_texto": "#ffffff", "brilho": "#ffffff", "logo_texto": "#ffffff",
    },
    "claro": {
        "fundo": "#eef1f8", "lateral": "#ffffff", "cabecalho": "#ffffff", "cartao": "#ffffff", "cartao_hover": "#e4ebfb",
        "borda": "#cfd7ea", "borda_hover": "#8ea3d1", "texto": "#1c2438", "suave": "#4f5b78", "mudo": "#5a6580",
        "azul": "#2a5bd7", "verde": "#0b7d59", "ambar": "#8f5a00", "vermelho": "#c4343f", "violeta": "#6d4bd1",
        "turquesa": "#087487", "ardosia": "#4f69a3",
        "sobre": "#ffffff", "selecao": "#cfe0ff", "selecao_texto": "#1c2438", "brilho": "#14234d", "logo_texto": "#ffffff",
    },
}

# ------------------------------------------------------------------ caixa (caixa_tema.CX): parte própria; o resto vem do PAL
CX = {
    "escuro": {
        "fundo": "#0a1029", "cabecalho": "#0c1432", "cartao": "#111a40", "cartao2": "#1a2656", "borda": "#25336e",
        "campo": "#0a1030", "linha_par": "#141e4a", "selecao": "#2a4fb0", "botao": "#17224f", "botao_hover": "#26367c",
        "sobre": "#04241a", "sobre_marca": "#0b1330", "perigo_texto": "#ffb3bb", "selecao_texto": "#ffffff",
        "comissao": "#0b7a6b", "comissao_texto": "#3fd3bd", "comissao_paga": "#8a94a6",
    },
    "claro": {
        "fundo": "#eef1f8", "cabecalho": "#ffffff", "cartao": "#ffffff", "cartao2": "#e4ebfb", "borda": "#cfd7ea",
        "campo": "#ffffff", "linha_par": "#f3f6fd", "selecao": "#cfe0ff", "botao": "#e6ecfa", "botao_hover": "#d5dff5",
        "sobre": "#ffffff", "sobre_marca": "#ffffff", "perigo_texto": "#8f1d28", "selecao_texto": "#1c2438",
        "comissao": "#0b7a6b", "comissao_texto": "#0a6259", "comissao_paga": "#7a859f",
    },
}
CX_DO_PAL = ("texto", "suave", "mudo", "azul", "verde", "ambar", "vermelho", "violeta", "turquesa")   # o caixa usa as mesmas cores de destaque

# ------------------------------------------------------------------ cartões das comandas (painel_mesas.ESTADOS)
ESTADOS = {
    "escuro": {
        "consumindo": {"fundo": "#121b45", "borda": "#34479a", "texto": "#9ab9ff"},
        "parada": {"fundo": "#34182b", "borda": "#a24a6b", "texto": "#ff8fa6"},
        "conta": {"fundo": "#33280f", "borda": "#a8832b", "texto": "#ffcf6e"},
        "balcao": {"fundo": "#0f2c2a", "borda": "#2e8f6c", "texto": "#5fe0b0"},
        "garota": {"fundo": "#0d3036", "borda": "#2a9d92", "texto": "#4fd8c6"},
        "parcial": {"fundo": "#211c4a", "borda": "#7d63d6", "texto": "#c4b1ff"},
        "acerto": {"fundo": "#33280f", "borda": "#a8832b", "texto": "#ffcf6e"},
    },
    "claro": {
        "consumindo": {"fundo": "#e8eefc", "borda": "#8ea6e0", "texto": "#2a4a9a"},
        "parada": {"fundo": "#fde8ee", "borda": "#d98aa1", "texto": "#a82c55"},
        "conta": {"fundo": "#fdf1d6", "borda": "#d6a93a", "texto": "#7a5200"},
        "balcao": {"fundo": "#dff5ec", "borda": "#59b894", "texto": "#0b6e4d"},
        "garota": {"fundo": "#d9f3f1", "borda": "#4fb5aa", "texto": "#0a6259"},
        "parcial": {"fundo": "#ece6fb", "borda": "#9b84e0", "texto": "#5a3fb0"},
        "acerto": {"fundo": "#fdf1d6", "borda": "#d6a93a", "texto": "#7a5200"},
    },
}

_modo = PADRAO


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
    from src.ui import caixa_tema, menu_widgets, painel_mesas, tema
    _trocar(tema.COR, COR[m])
    _trocar(menu_widgets.PAL, PAL[m])
    cx = dict(CX[m])
    cx.update({k: PAL[m][k] for k in CX_DO_PAL})
    _trocar(caixa_tema.CX, cx)
    _trocar(painel_mesas.ESTADOS, {k: dict(v) for k, v in ESTADOS[m].items()})
    return m


def aplicar_da_configuracao(banco) -> str:
    """Lê `tema_visual` do banco e aplica."""
    return aplicar(banco.cfg(CHAVE, PADRAO))
