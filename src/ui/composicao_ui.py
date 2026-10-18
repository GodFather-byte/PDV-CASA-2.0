"""Composição / ficha técnica do produto (manual ADM seção 3.5)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.core import formatacao as fmt
from src.ui import tema


class JanelaComposicao(tk.Toplevel):
    def __init__(self, master, ctx, produto_id: int | None = None):
        super().__init__(master)
        self.ctx = ctx
        self.title("Cadastro de Composições")
        self.configure(bg=tema.COR["fundo"])
        self.geometry("820x560")
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)

        todos = [(r["id"], r["nome"]) for r in ctx.produtos.listar_venda()]
        todos += [(r["id"], r["nome"]) for r in ctx.cadastros.listar("produtos") if (r["id"], r["nome"]) not in todos]
        self.nomes = {i: n for i, n in sorted(todos, key=lambda x: x[1])}
        self.por_nome = {n: i for i, n in self.nomes.items()}
        estoque = [r["nome"] for r in ctx.cadastros.listar("produtos", filtros={"controla_estoque": 1}, apenas_ativos=True)]

        ttk.Label(corpo, text="Produto (o que é vendido)", style="Rotulo.TLabel").grid(row=0, column=0, sticky="w")
        self.var_prod = tk.StringVar(value=self.nomes.get(produto_id, ""))
        self.cb_prod = ttk.Combobox(corpo, textvariable=self.var_prod, values=list(self.por_nome), width=44)
        self.cb_prod.grid(row=1, column=0, sticky="w", padx=(0, 12))
        ttk.Label(corpo, text="Composição (insumo em estoque)", style="Rotulo.TLabel").grid(row=0, column=1, sticky="w")
        self.var_ins = tk.StringVar()
        self.cb_ins = ttk.Combobox(corpo, textvariable=self.var_ins, values=estoque, width=36)
        self.cb_ins.grid(row=1, column=1, sticky="w", padx=(0, 12))
        ttk.Label(corpo, text="Quantidade", style="Rotulo.TLabel").grid(row=0, column=2, sticky="w")
        self.var_qtd = tk.StringVar()
        self.ent_qtd = ttk.Entry(corpo, textvariable=self.var_qtd, width=12)
        self.ent_qtd.grid(row=1, column=2, sticky="w")
        ttk.Label(corpo, text="Ex.: 100 g = 0,1000 (kg)", foreground=tema.COR["suave"]).grid(row=2, column=2, sticky="w")

        botoes = ttk.Frame(corpo)
        botoes.grid(row=3, column=0, columnspan=3, sticky="w", pady=10)
        ttk.Button(botoes, text="Incluir mais uma composição (Enter)", command=self.incluir).pack(side="left")
        ttk.Button(botoes, text="Excluir selecionada", style="Perigo.TButton", command=self.excluir).pack(side="left", padx=8)
        self.lbl_custo = ttk.Label(botoes, text="", font=tema.FONTE_B, foreground=tema.COR["rotulo"])
        self.lbl_custo.pack(side="left", padx=20)

        self.grade = tema.Grade(corpo, [("cod", "Código", 110, "w"), ("nome", "Composição", 300, "w"),
                                        ("un", "Un", 50, "w"), ("qtd", "Quantidade", 100, "e"), ("custo", "Custo", 90, "e")], altura=14)
        self.grade.grid(row=4, column=0, columnspan=3, sticky="nsew")
        corpo.rowconfigure(4, weight=1)
        corpo.columnconfigure(1, weight=1)
        self.cb_prod.bind("<<ComboboxSelected>>", lambda e: self.carregar())
        self.cb_prod.bind("<FocusOut>", lambda e: self.carregar())
        self.ent_qtd.bind("<Return>", lambda e: self.incluir())
        self.bind("<Escape>", lambda e: self.destroy())
        self.carregar()
        tema.centralizar(self, master.winfo_toplevel())
        (self.cb_ins if produto_id else self.cb_prod).focus_set()

    def _produto_id(self) -> int | None:
        return self.por_nome.get(self.var_prod.get().strip())

    def carregar(self) -> None:
        pid = self._produto_id()
        self.grade.limpar()
        if pid is None:
            self.lbl_custo.configure(text="")
            return
        for c in self.ctx.produtos.composicao(pid):
            self.grade.adicionar([c["codigo"], c["nome"], c["unidade"], fmt.fmt_qtd(c["quantidade"], 4),
                                  fmt.fmt_num(fmt.mult_cent(c["ult_preco_cent"], c["quantidade"]))], iid=c["id"])
        self.lbl_custo.configure(text=f"Custo: {fmt.fmt_brl(self.ctx.produtos.custo(pid))}")

    def incluir(self) -> None:
        pid = self._produto_id()
        if pid is None:
            tema.aviso(self, "Escolha o produto que terá a composição.")
            return
        insumo = self.ctx.cadastros.listar("produtos", texto=self.var_ins.get().strip())
        insumo = next((p for p in insumo if p["nome"] == self.var_ins.get().strip()), None)
        if insumo is None:
            tema.aviso(self, "Escolha o insumo na lista (ele precisa estar cadastrado e habilitado no estoque).")
            return
        try:
            qtd = fmt.para_qtd(self.var_qtd.get())
        except ValueError:
            tema.aviso(self, "Quantidade inválida.")
            return
        ok, _ = tema.tratar(self, self.ctx.produtos.incluir_composicao, pid, insumo["id"], qtd)
        if ok:
            self.var_ins.set("")
            self.var_qtd.set("")
            self.carregar()
            self.cb_ins.focus_set()

    def excluir(self) -> None:
        sel = self.grade.selecionado()
        if sel is None:
            return
        self.ctx.produtos.excluir_composicao(int(sel))
        self.carregar()
