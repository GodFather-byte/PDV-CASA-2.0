"""Escolhas de temperatura e troca de vasilhames antes de lançar a bebida."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

from src.core import formatacao as fmt
from src.ui import tema


def pedir_temperatura(master, produto: dict, preco_natural_cent: int) -> str | None:
    dlg = tema.Dialogo(master, "Temperatura da bebida")
    ttk.Label(dlg.corpo, text=produto["nome"], style="Rotulo.TLabel").pack(anchor="w")
    ttk.Label(dlg.corpo, text="Como o cliente vai levar? Escolha antes de lançar.").pack(anchor="w", pady=(4, 12))
    natural = ttk.Button(dlg.corpo, text=f"Natural (N)  ·  {fmt.fmt_brl(preco_natural_cent)}",
                         command=lambda: dlg.ok("natural"))
    natural.pack(fill="x", pady=3)
    ttk.Button(dlg.corpo, text=f"Gelada (G)  ·  {fmt.fmt_brl(produto['preco_gelada_cent'])}",
               style="Ok.TButton", command=lambda: dlg.ok("gelada")).pack(fill="x", pady=3)
    ttk.Label(dlg.corpo, text="Preço unitário de tabela; atacado automático somente no balcão.",
              foreground=tema.COR["suave"]).pack(anchor="w", pady=(8, 0))
    ttk.Button(dlg.corpo, text="Cancelar (Esc)", command=dlg.cancelar).pack(anchor="e", pady=(12, 0))
    for tecla, temperatura in (("n", "natural"), ("N", "natural"), ("g", "gelada"), ("G", "gelada")):
        dlg.bind(tecla, lambda e, t=temperatura: dlg.ok(t))
    dlg.bind("<Return>", lambda e: dlg.focus_get().invoke() if isinstance(dlg.focus_get(), ttk.Button) else natural.invoke())
    return dlg.mostrar(natural)


def pedir_cascos(master, produto: dict, casco: dict, quantidade: float) -> int | None:
    dlg = tema.Dialogo(master, "Cascos / vasilhames")
    maximo = math.floor(quantidade)
    ttk.Label(dlg.corpo, text=produto["nome"], style="Rotulo.TLabel").pack(anchor="w")
    ttk.Label(dlg.corpo, text=f"Bebidas: {fmt.fmt_qtd(quantidade)}  ·  {casco['nome']}\n"
              f"Cada casco: {fmt.fmt_brl(casco['preco_cent'])}", justify="left").pack(anchor="w", pady=(4, 10))
    ttk.Label(dlg.corpo, text="Quantos cascos cobrar?").pack(anchor="w")
    var = tk.StringVar(dlg, value="0")
    entrada = ttk.Entry(dlg.corpo, textvariable=var, width=12)
    entrada.pack(anchor="w", pady=4)
    ttk.Label(dlg.corpo, text=f"0 = todas as garrafas são trocas. Sem troca: informe {maximo}.\n"
              f"Digite um número inteiro de 0 a {maximo}.", justify="left",
              foreground=tema.COR["suave"]).pack(anchor="w")
    ttk.Label(dlg.corpo, text="Atenção: bebida e casco ficam em linhas independentes.\n"
              "Cancelar a bebida NÃO cancela o casco (nem o contrário).\n"
              "Em caso de desistência, confira e cancele as duas linhas.",
              foreground=tema.COR["perigo"], justify="left").pack(anchor="w", pady=(10, 0))
    erro = ttk.Label(dlg.corpo, text="", foreground=tema.COR["perigo"])
    erro.pack(anchor="w", pady=4)

    def confirmar(_=None):
        texto = var.get().strip()
        if not texto.isascii() or not texto.isdecimal() or not 0 <= int(texto) <= maximo:
            erro.configure(text=f"Informe um número inteiro de 0 a {maximo}.")
            entrada.focus_set()
            entrada.selection_range(0, "end")
            return
        dlg.ok(int(texto))

    botoes = ttk.Frame(dlg.corpo)
    botoes.pack(fill="x", pady=(8, 0))
    ttk.Button(botoes, text="Cancelar (Esc)", command=dlg.cancelar).pack(side="right")
    ttk.Button(botoes, text="Confirmar", style="Ok.TButton", command=confirmar).pack(side="right", padx=8)
    dlg.bind("<Return>", confirmar)
    entrada.selection_range(0, "end")
    return dlg.mostrar(entrada)
