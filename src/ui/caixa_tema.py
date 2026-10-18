"""Visual do caixa (no escuro, o azul-noite do menu principal; no claro, branco e azul-claro): cores e estilos ttk próprios,
prefixo "Cx".

Os estilos só valem para quem os pede pelo nome (`style="Cx.TButton"`...); as outras telas usam os estilos de `tema.aplicar_tema`."""
from __future__ import annotations

from tkinter import ttk

from src.ui import paleta
from src.ui.menu_widgets import PAL, FONTE, misturar

CX = dict(paleta.CX[paleta.PADRAO])          # o conteúdo troca com o modo (claro/escuro): ver paleta.aplicar
CX.update({k: PAL[k] for k in paleta.CX_DO_PAL})


def aplicar(root) -> None:
    """Cria (ou refaz) os estilos escuros. Idempotente."""
    s = ttk.Style(root)
    c = CX
    s.configure("Cx.TFrame", background=c["fundo"])
    s.configure("Cx.Cartao.TFrame", background=c["cartao"])
    s.configure("Cx.TLabel", background=c["fundo"], foreground=c["texto"], font=(FONTE, 10))
    s.configure("Cx.Cartao.TLabel", background=c["cartao"], foreground=c["texto"], font=(FONTE, 10))
    s.configure("Cx.Rotulo.TLabel", background=c["fundo"], foreground=c["suave"], font=(FONTE, 8, "bold"))
    s.configure("Cx.CartaoRotulo.TLabel", background=c["cartao"], foreground=c["suave"], font=(FONTE, 8, "bold"))
    s.configure("Cx.Status.TLabel", background=c["cabecalho"], foreground=c["suave"], font=(FONTE, 10))

    s.configure("Cx.TEntry", padding=6, fieldbackground=c["campo"], foreground=c["texto"], insertcolor=c["texto"],
                bordercolor=c["borda"], lightcolor=c["borda"], darkcolor=c["borda"])
    s.map("Cx.TEntry", bordercolor=[("focus", c["azul"])], lightcolor=[("focus", c["azul"])],
          darkcolor=[("focus", c["azul"])], fieldbackground=[("disabled", c["fundo"])],
          foreground=[("disabled", c["mudo"])])
    s.configure("Cx.TCombobox", padding=5, fieldbackground=c["campo"], foreground=c["texto"],
                background=c["botao"], arrowcolor=c["texto"], bordercolor=c["borda"])
    s.map("Cx.TCombobox", fieldbackground=[("readonly", c["campo"])], foreground=[("readonly", c["texto"])])

    base = dict(padding=(8, 5), borderwidth=0, focusthickness=0, font=(FONTE, 9, "bold"))
    s.configure("Cx.TButton", background=c["botao"], foreground=c["texto"], **base)
    s.map("Cx.TButton", background=[("active", c["botao_hover"]), ("disabled", c["cartao"])],
          foreground=[("disabled", c["mudo"])])
    s.configure("Cx.Sel.TButton", background=c["ambar"], foreground=c["sobre"], **base)       # escolhido pelo teclado (setas)
    s.map("Cx.Sel.TButton", background=[("active", misturar(c["ambar"], PAL["brilho"], 0.2))])
    s.configure("Cx.Perigo.TButton", background=misturar(c["fundo"], c["vermelho"], 0.2), foreground=c["perigo_texto"], **base)
    s.map("Cx.Perigo.TButton", background=[("active", misturar(c["fundo"], c["vermelho"], 0.4))])
    s.configure("Cx.Mini.TButton", background=c["botao"], foreground=c["texto"], **dict(base, padding=(4, 1), font=(FONTE, 8, "bold")))
    s.map("Cx.Mini.TButton", background=[("active", c["botao_hover"]), ("disabled", c["cartao"])])
    forte = dict(base, padding=(12, 10), font=(FONTE, 15, "bold"))
    s.configure("Cx.Pagar.TButton", background=c["verde"], foreground=c["sobre"], **forte)
    s.map("Cx.Pagar.TButton", background=[("active", misturar(c["verde"], PAL["brilho"], 0.25)), ("disabled", c["cartao"])])
    acao = dict(base, padding=(6, 11), font=(FONTE, 10, "bold"))              # as ações do dia a dia, na coluna da direita
    s.configure("Cx.Acao.TButton", background=c["botao"], foreground=c["texto"], **acao)
    s.map("Cx.Acao.TButton", background=[("active", c["botao_hover"]), ("disabled", c["cartao"])],
          foreground=[("disabled", c["mudo"])])
    s.configure("Cx.AcaoPerigo.TButton", background=misturar(c["fundo"], c["vermelho"], 0.2), foreground=c["perigo_texto"], **acao)
    s.map("Cx.AcaoPerigo.TButton", background=[("active", misturar(c["fundo"], c["vermelho"], 0.4))])
    medio = dict(base, padding=(12, 9), font=(FONTE, 11, "bold"))
    s.configure("Cx.Principal.TButton", background=c["botao"], foreground=c["texto"], **medio)
    s.map("Cx.Principal.TButton", background=[("active", c["botao_hover"])])
    s.configure("Cx.Ok.TButton", background=c["verde"], foreground=c["sobre"], **medio)
    s.map("Cx.Ok.TButton", background=[("active", misturar(c["verde"], PAL["brilho"], 0.25)), ("disabled", c["cartao"])],
          foreground=[("disabled", c["mudo"])])

    for nome, altura, fonte in (("Cx", 30, 12), ("CxForma", 46, 15)):        # CxForma: linhas altas, fáceis de tocar
        s.configure(f"{nome}.Treeview", rowheight=altura, font=(FONTE, fonte), background=c["cartao"],
                    fieldbackground=c["cartao"], foreground=c["texto"], bordercolor=c["borda"], lightcolor=c["borda"],
                    darkcolor=c["borda"], borderwidth=1)
        s.configure(f"{nome}.Treeview.Heading", font=(FONTE, 9, "bold"), background=c["cabecalho"], foreground=c["suave"],
                    padding=7, relief="flat", borderwidth=0)
        s.map(f"{nome}.Treeview.Heading", background=[("active", c["cabecalho"])])
        s.map(f"{nome}.Treeview", background=[("selected", c["selecao"])], foreground=[("selected", c["selecao_texto"])])
        for eixo in ("Vertical", "Horizontal"):
            s.configure(f"{nome}.{eixo}.TScrollbar", background=c["botao"], troughcolor=c["fundo"], bordercolor=c["fundo"],
                        arrowcolor=c["suave"], lightcolor=c["botao"], darkcolor=c["botao"], relief="flat")
            s.map(f"{nome}.{eixo}.TScrollbar", background=[("active", c["botao_hover"])])
