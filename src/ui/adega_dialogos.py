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


def pedir_cascos(master, produto: dict, casco: dict, quantidade: float, *, prever_impacto=None) -> int | None:
    dlg = tema.Dialogo(master, "Cascos / vasilhames")
    maximo = math.floor(quantidade)
    ttk.Label(dlg.corpo, text=produto["nome"], style="Rotulo.TLabel").pack(anchor="w")
    ttk.Label(dlg.corpo, text=f"Bebidas: {fmt.fmt_qtd(quantidade)}  ·  {casco['nome']}\n"
              f"Cada casco (tabela): {fmt.fmt_brl(casco['preco_cent'])}", justify="left").pack(anchor="w", pady=(4, 10))
    ttk.Label(dlg.corpo, text="Quantos cascos cobrar?").pack(anchor="w")
    var = tk.StringVar(dlg, value="0")
    entrada = ttk.Entry(dlg.corpo, textvariable=var, width=12)
    entrada.pack(anchor="w", pady=4)
    atalhos = ttk.Frame(dlg.corpo)
    atalhos.pack(fill="x", pady=4)
    ttk.Button(atalhos, text="Todas trocas (F2)", command=lambda: var.set("0")).pack(side="left")
    ttk.Button(atalhos, text="Sem troca (F3)", command=lambda: var.set(str(maximo))).pack(side="left", padx=8)
    ttk.Label(dlg.corpo, text=f"0 = todas as garrafas são trocas. Sem troca: informe {maximo}.\n"
              f"Digite um número inteiro de 0 a {maximo}.", justify="left",
              foreground=tema.COR["suave"]).pack(anchor="w")
    if quantidade != maximo:
        ttk.Label(dlg.corpo, text=f"A fração da bebida não gera casco: no máximo {maximo} casco(s).",
                 foreground=tema.COR["suave"]).pack(anchor="w")
    previa = ttk.Label(dlg.corpo, text="", style="Rotulo.TLabel")
    previa.pack(anchor="w", pady=(8, 0))
    ttk.Label(dlg.corpo, text="Prévia dos itens de casco; não inclui taxas ou desconto global.",
              foreground=tema.COR["suave"]).pack(anchor="w")
    ttk.Label(dlg.corpo, text="Atenção: bebida e casco ficam em linhas independentes.\n"
              "Cancelar a bebida NÃO cancela o casco (nem o contrário).\n"
              "Em caso de desistência, confira e cancele as duas linhas.",
              foreground=tema.COR["perigo"], justify="left").pack(anchor="w", pady=(10, 0))
    erro = ttk.Label(dlg.corpo, text="", foreground=tema.COR["perigo"])
    erro.pack(anchor="w", pady=4)

    def quantidade_valida():
        texto = var.get().strip()
        try:
            valor = int(texto) if texto.isascii() and texto.isdecimal() else -1
        except ValueError:
            return None
        return valor if 0 <= valor <= maximo else None

    def atualizar_previa(*_):
        valor = quantidade_valida()
        if valor is None:
            previa.configure(text="Impacto indisponível: corrija a quantidade.")
        else:
            impacto = prever_impacto(valor) if prever_impacto else valor * casco["preco_cent"]
            sinal = "+" if impacto >= 0 else "-"
            previa.configure(text=f"Impacto dos cascos: {sinal} {fmt.fmt_brl(abs(impacto))}")
        erro.configure(text="")

    def confirmar(_=None):
        valor = quantidade_valida()
        if valor is None:
            erro.configure(text=f"Informe um número inteiro de 0 a {maximo}.")
            entrada.focus_set()
            entrada.selection_range(0, "end")
            return
        dlg.ok(valor)

    botoes = ttk.Frame(dlg.corpo)
    botoes.pack(fill="x", pady=(8, 0))
    ttk.Button(botoes, text="Cancelar (Esc)", command=dlg.cancelar).pack(side="right")
    ttk.Button(botoes, text="Confirmar", style="Ok.TButton", command=confirmar).pack(side="right", padx=8)
    dlg.bind("<Return>", confirmar)
    dlg.bind("<F2>", lambda e: (var.set("0"), "break")[1])
    dlg.bind("<F3>", lambda e: (var.set(str(maximo)), "break")[1])
    var.trace_add("write", atualizar_previa)
    atualizar_previa()
    entrada.selection_range(0, "end")
    return dlg.mostrar(entrada)
