"""Seleção, prévia e impressão/exportação de etiquetas de produto e preço (Tk)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.controllers.etiqueta_controller import TEMPERATURAS, EtiquetaController
from src.core import formatacao as fmt
from src.ui import tema
from src.ui.visualizador import Visualizador

_ROTULOS = {v: k for k, v in TEMPERATURAS.items()}


class DialogoEtiquetas(tk.Toplevel):
    """Escolha os produtos (vários), as cópias e a temperatura; a prévia abre o visualizador,
    que já imprime pelo caminho existente ou salva texto/CSV. Nada é enviado sem o clique do operador."""

    def __init__(self, master, ctx, produtos: list[dict], selecionados: list[int] | None = None):
        super().__init__(master)
        self.ctx, self.produtos = ctx, produtos
        self.ctrl = EtiquetaController(ctx.banco)
        self.title("Etiquetas de produtos e preços")
        self.v_copias, self.v_temp = tk.StringVar(value="1"), tk.StringVar(value=TEMPERATURAS["natural"])
        topo = ttk.Frame(self, padding=10)
        topo.pack(fill="both", expand=True)
        ttk.Label(topo, text="Selecione os produtos (Ctrl/Shift para vários):").pack(anchor="w")
        self.tree = ttk.Treeview(topo, columns=("cod", "nome", "preco"), show="headings", selectmode="extended", height=14)
        for cid, titulo, larg, anc in (("cod", "Código", 80, "w"), ("nome", "Produto", 320, "w"), ("preco", "Preço cadastro", 110, "e")):
            self.tree.heading(cid, text=titulo)
            self.tree.column(cid, width=larg, anchor=anc)
        self.tree.pack(fill="both", expand=True, pady=6)
        precos = {r["id"]: r["preco_cent"] for r in ctx.banco.todos("SELECT id, preco_cent FROM produtos")}
        for p in produtos:
            self.tree.insert("", "end", iid=str(p["id"]),
                             values=(p["codigo"], p["nome"], fmt.fmt_brl(precos.get(p["id"], 0))))
        for pid in selecionados or []:
            if self.tree.exists(str(pid)):
                self.tree.selection_add(str(pid))
        opcoes = ttk.Frame(topo)
        opcoes.pack(fill="x")
        ttk.Label(opcoes, text="Cópias por produto:").pack(side="left")
        self.sp_copias = ttk.Spinbox(opcoes, from_=1, to=99, width=5, textvariable=self.v_copias)
        self.sp_copias.pack(side="left", padx=(6, 16))
        ttk.Label(opcoes, text="Temperatura:").pack(side="left")
        self.cb_temp = ttk.Combobox(opcoes, textvariable=self.v_temp, state="readonly", width=18,
                                    values=list(TEMPERATURAS.values()))
        self.cb_temp.pack(side="left", padx=6)
        botoes = ttk.Frame(topo)
        botoes.pack(fill="x", pady=(10, 0))
        ttk.Button(botoes, text="Prévia / Imprimir / CSV", command=self.previa).pack(side="left")
        ttk.Button(botoes, text="Fechar (Esc)", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())

    def itens(self) -> list[dict]:
        try:
            copias = int(self.v_copias.get())
        except ValueError:
            copias = 0
        temp = _ROTULOS.get(self.v_temp.get(), "natural")
        return [{"produto_id": int(i), "copias": copias, "temperatura": temp} for i in self.tree.selection()]

    def previa(self) -> None:
        ok, etiquetas = tema.tratar(self, self.ctrl.etiquetas, self.itens())
        if ok:
            Visualizador(self, self.ctx, "Etiquetas - prévia", self.ctrl.texto(etiquetas), "etiquetas",
                         csv=self.ctrl.csv(etiquetas), tipo="etiquetas")