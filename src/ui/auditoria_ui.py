"""Consulta somente leitura da auditoria estruturada administrativa."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from src.ui import tema

ACOES = (
    "cadastro", "alteracao", "exclusao", "preco_alterado", "desconto_alterado",
    "venda_cancelada", "item_cancelado", "estoque_alterado",
    "permissao_alterada", "credencial_alterada",
)
TAMANHO_PAGINA = 100


class JanelaAuditoria(tk.Toplevel):
    def __init__(self, master, ctx):
        ctx.auditoria._exigir_acesso()
        super().__init__(master)
        self.ctx = ctx
        self.offset = 0
        self.eventos = {}
        self._filtros = {}
        self.title("Auditoria estruturada")
        self.geometry("1100x720")
        self.minsize(780, 520)
        self.configure(bg=tema.COR["fundo"])
        self.transient(master.winfo_toplevel())
        self.bind("<Escape>", lambda e: self.destroy())

        filtros = ttk.LabelFrame(self, text="Critérios de consulta", padding=10)
        filtros.pack(fill="x", padx=10, pady=10)
        self.inicio = tk.StringVar(self)
        self.fim = tk.StringVar(self)
        self.acao = tk.StringVar(self)
        for coluna, (rotulo, variavel) in enumerate((
            ("Início (AAAA-MM-DD)", self.inicio), ("Fim (AAAA-MM-DD)", self.fim),
        )):
            campo = ttk.Frame(filtros)
            campo.grid(row=0, column=coluna, sticky="w", padx=(0, 12))
            ttk.Label(campo, text=rotulo).pack(anchor="w")
            entrada = ttk.Entry(campo, textvariable=variavel, width=22)
            entrada.pack()
            entrada.bind("<Return>", lambda e: self.consultar())
        campo = ttk.Frame(filtros)
        campo.grid(row=0, column=2, sticky="w")
        ttk.Label(campo, text="Ação (vazio = todas)").pack(anchor="w")
        ttk.Combobox(campo, textvariable=self.acao, values=("", *ACOES),
                     state="readonly", width=24).pack()

        barra = ttk.Frame(self, padding=(10, 0, 10, 8))
        barra.pack(fill="x")
        ttk.Button(barra, text="Consultar", command=self.consultar).pack(side="left")
        ttk.Button(barra, text="Limpar filtros", command=self.limpar).pack(side="left", padx=6)
        self.anterior = ttk.Button(barra, text="Anterior", command=self.pagina_anterior)
        self.anterior.pack(side="left", padx=(12, 6))
        self.proxima = ttk.Button(barra, text="Próxima", command=self.proxima_pagina)
        self.proxima.pack(side="left")
        ttk.Button(barra, text="Saída", command=self.destroy).pack(side="right")
        self.situacao = ttk.Label(self, text="")
        self.situacao.pack(anchor="w", padx=10, pady=(0, 6))
        self.grade = tema.Grade(self, [
            ("id", "Evento", 65, "e"), ("quando", "Data/hora", 155, "w"),
            ("operador", "Operador (ID)", 100, "w"), ("origem", "Origem", 85, "w"),
            ("entidade", "Entidade", 135, "w"), ("entidade_id", "Identificador", 200, "w"),
            ("acao", "Ação", 160, "w"),
        ], altura=10)
        self.grade.pack(fill="both", expand=True, padx=10)
        self.grade.tree.bind("<<TreeviewSelect>>", self.detalhar)
        painel = ttk.LabelFrame(self, text="Antes / depois (somente leitura)", padding=6)
        painel.pack(fill="both", expand=True, padx=10, pady=10)
        self.detalhe = tk.Text(painel, height=9, wrap="word", state="disabled",
                               font=tema.FONTE_MONO, bg=tema.COR["campo"], fg=tema.COR["texto"])
        rolagem = ttk.Scrollbar(painel, command=self.detalhe.yview)
        rolagem.pack(side="right", fill="y")
        self.detalhe.configure(yscrollcommand=rolagem.set)
        self.detalhe.pack(fill="both", expand=True)
        self.consultar()

    def _mostrar_detalhe(self, texto=""):
        self.detalhe.configure(state="normal")
        self.detalhe.delete("1.0", "end")
        self.detalhe.insert("1.0", texto)
        self.detalhe.configure(state="disabled")

    def _carregar(self, offset, filtros):
        try:
            eventos = self.ctx.auditoria.listar(
                **filtros, limite=TAMANHO_PAGINA, offset=offset)
        except Exception as erro:
            # Nem dados da página anterior permanecem visíveis após revogar acesso.
            self.eventos = {}
            self.grade.preencher([])
            self._mostrar_detalhe()
            self.anterior.configure(state="disabled")
            self.proxima.configure(state="disabled")
            self.situacao.configure(text="Consulta não concluída.")
            tema.erro(self, str(erro), "Auditoria")
            return False
        self.offset, self._filtros = offset, filtros.copy()
        self.eventos = {str(e["id"]): e for e in eventos}
        self.grade.preencher([
            [e["id"], e["quando"], e["operador_id"] if e["operador_id"] is not None else "—",
             e["origem"], e["entidade"], e["entidade_id"], e["acao"]] for e in eventos
        ], [e["id"] for e in eventos])
        self._mostrar_detalhe()
        self.anterior.configure(state="normal" if offset else "disabled")
        self.proxima.configure(state="normal" if len(eventos) == TAMANHO_PAGINA else "disabled")
        self.situacao.configure(text=(
            f"Página {offset // TAMANHO_PAGINA + 1} — {len(eventos)} evento(s)"
            if eventos else f"Página {offset // TAMANHO_PAGINA + 1} — nenhum evento encontrado."))
        if eventos:
            self.grade.selecionar_indice(0)
            self.detalhar()
        return True

    def consultar(self):
        return self._carregar(0, {
            "inicio": self.inicio.get().strip() or None,
            "fim": self.fim.get().strip() or None,
            "acao": self.acao.get().strip() or None,
        })

    def limpar(self):
        for variavel in (self.inicio, self.fim, self.acao):
            variavel.set("")
        self.consultar()

    def pagina_anterior(self):
        if self.offset:
            self._carregar(max(0, self.offset - TAMANHO_PAGINA), self._filtros)

    def proxima_pagina(self):
        if len(self.eventos) == TAMANHO_PAGINA:
            self._carregar(self.offset + TAMANHO_PAGINA, self._filtros)

    def detalhar(self, evento=None):
        selecionado = self.eventos.get(self.grade.selecionado())
        if selecionado is None:
            self._mostrar_detalhe()
            return
        try:
            self.ctx.auditoria._exigir_acesso()
        except Exception as erro:
            self.eventos = {}
            self.grade.preencher([])
            self._mostrar_detalhe()
            self.anterior.configure(state="disabled")
            self.proxima.configure(state="disabled")
            self.situacao.configure(text="Consulta não concluída.")
            tema.erro(self, str(erro), "Auditoria")
            return
        antes = json.dumps(selecionado["antes"], ensure_ascii=False, indent=2)
        depois = json.dumps(selecionado["depois"], ensure_ascii=False, indent=2)
        self._mostrar_detalhe(
            f"Evento {selecionado['id']} | {selecionado['acao']}\n"
            f"{selecionado['entidade']}: {selecionado['entidade_id']}\n\n"
            f"ANTES\n{antes}\n\nDEPOIS\n{depois}")
