"""Cadastros rápidos da adega: o produto novo direto do caixa, pelo código de barras que o leitor passou, e o fardo ou a
caixa fechada de um produto (vender 1 baixa as unidades do estoque)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.ui import tema


def _subgrupos(ctx) -> list[tuple[int, str]]:
    return [(r["id"], f"{r['nome']} - {r['grupo']}") for r in ctx.banco.todos(
        "SELECT s.id, s.nome, g.nome AS grupo FROM subgrupos s JOIN grupos g ON g.id = s.grupo_id ORDER BY g.nome, s.nome")]


def _campo(dlg, linha: int, rotulo: str, var: tk.StringVar, largura: int = 34, widget=None):
    ttk.Label(dlg.corpo, text=rotulo).grid(row=linha, column=0, sticky="w", pady=3)
    w = widget or ttk.Entry(dlg.corpo, textvariable=var, width=largura)
    w.grid(row=linha, column=1, sticky="w", padx=(10, 0), pady=3)
    return w


def _botoes(dlg, linha: int, gravar) -> None:
    barra = ttk.Frame(dlg.corpo)
    barra.grid(row=linha, column=0, columnspan=2, sticky="e", pady=(10, 0))
    ttk.Button(barra, text="Cancelar", command=dlg.cancelar).pack(side="right")
    ttk.Button(barra, text="Gravar", style="Ok.TButton", command=gravar).pack(side="right", padx=(0, 8))
    dlg.bind("<Return>", gravar)


def pedir_produto(master, ctx, cbarra: str, subgrupo_id: int | None = None) -> dict | None:
    """Cadastra o produto do código de barras que não foi achado. Devolve o produto gravado, ou None se o operador desistir."""
    dlg = tema.Dialogo(master, "Produto novo")
    ttk.Label(dlg.corpo, text=f"Código de barras: {cbarra}", style="Rotulo.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
    opcoes = _subgrupos(ctx)
    nomes = [n for _, n in opcoes]
    v_nome, v_preco, v_estoque, v_gelada = tk.StringVar(dlg), tk.StringVar(dlg), tk.StringVar(dlg), tk.StringVar(dlg)
    v_sub = tk.StringVar(dlg, value=next((n for i, n in opcoes if i == subgrupo_id), nomes[0] if nomes else ""))
    e_nome = _campo(dlg, 1, "Nome do produto *", v_nome, 40)
    _campo(dlg, 2, "Preço de venda (R$) *", v_preco, 14)
    _campo(dlg, 3, "Categoria", v_sub,
           widget=ttk.Combobox(dlg.corpo, textvariable=v_sub, values=nomes, state="readonly", width=38))
    _campo(dlg, 4, "Quantidade em estoque (opcional)", v_estoque, 14)
    _campo(dlg, 5, "Preço gelada (R$, opcional)", v_gelada, 14)
    ttk.Label(dlg.corpo, text="Com preço gelada, o caixa pergunta natural ou gelada a cada venda; o estoque é o mesmo.",
              foreground=tema.COR["suave"]).grid(row=6, column=0, columnspan=2, sticky="w")
    msg = ttk.Label(dlg.corpo, text="", foreground=tema.COR["perigo"])
    msg.grid(row=7, column=0, columnspan=2, sticky="w")

    def gravar(_=None):
        try:
            preco = fmt.para_centavos(v_preco.get() or "0")
            gelada = fmt.para_centavos(v_gelada.get() or "0")
            estoque = fmt.para_qtd(v_estoque.get()) if v_estoque.get().strip() else None
        except ValueError:
            msg.configure(text="Preço ou quantidade inválidos.")
            return
        sub = next((i for i, n in opcoes if n == v_sub.get()), None)
        try:
            p = ctx.produtos.cadastrar_rapido(cbarra, v_nome.get().strip(), preco, sub, estoque, ctx.operador_id,
                                              preco_gelada_cent=gelada)
        except ErroNegocio as e:
            msg.configure(text=str(e))
            return
        dlg.ok(p)
    _botoes(dlg, 8, gravar)
    return dlg.mostrar(e_nome)


def pedir_embalagem(master, ctx, unitario_id: int) -> int | None:
    """Fardo ou caixa fechada do produto: quantas unidades vêm, o nome, o preço e o código de barras da embalagem. Devolve o
    id do produto criado, ou None se o operador desistir."""
    u = ctx.produtos.por_id(unitario_id)
    dlg = tema.Dialogo(master, "Fardo / caixa fechada")
    ttk.Label(dlg.corpo, text=f"Embalagem de: {u['nome']}", style="Rotulo.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(dlg.corpo, text="Vender 1 fardo ou caixa baixa do estoque as unidades deste produto.",
              foreground=tema.COR["suave"]).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))
    v_qtd, v_nome = tk.StringVar(dlg, value="12"), tk.StringVar(dlg, value=f"{u['nome']} - FARDO")
    v_preco, v_cbarra = tk.StringVar(dlg), tk.StringVar(dlg)
    e_qtd = _campo(dlg, 2, "Unidades no fardo/caixa *", v_qtd, 8)
    _campo(dlg, 3, "Nome *", v_nome, 44)
    _campo(dlg, 4, "Preço do fardo/caixa (R$) *", v_preco, 14)
    _campo(dlg, 5, "Código de barras da embalagem", v_cbarra, 20)
    msg = ttk.Label(dlg.corpo, text="", foreground=tema.COR["perigo"])
    msg.grid(row=6, column=0, columnspan=2, sticky="w")

    def gravar(_=None):
        try:
            qtd = fmt.para_qtd(v_qtd.get() or "0")
            preco = fmt.para_centavos(v_preco.get() or "0")
        except ValueError:
            msg.configure(text="Quantidade ou preço inválidos.")
            return
        try:
            pid = ctx.produtos.criar_embalagem(unitario_id, qtd, v_nome.get().strip(), preco, v_cbarra.get().strip() or None,
                                               ctx.operador_id)
        except ErroNegocio as e:
            msg.configure(text=str(e))
            return
        dlg.ok(pid)
    _botoes(dlg, 7, gravar)
    return dlg.mostrar(e_qtd)
