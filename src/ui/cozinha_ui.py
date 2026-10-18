"""Painel da Cozinha/Bar (módulo de operação usar_cozinha_bar): acompanha o preparo dos itens
que já foram enviados para a impressora remota, do pedido até a entrega."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.ui import tema

SITUACAO = {"pendente": "Pendente", "em_preparo": "Em preparo", "entregue": "Entregue"}


class JanelaCozinha(tk.Toplevel):
    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx, self.preparo = ctx, ctx.preparo
        self._id_after = None
        self.title("Painel da Cozinha/Bar")
        self.configure(bg=tema.COR["fundo"])
        self.geometry("980x560")
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)
        topo = ttk.Frame(corpo)
        topo.pack(fill="x", pady=(0, 8))
        ttk.Label(topo, text="Setor:").pack(side="left")
        self.setores = [(0, "Todos")] + [(r["id"], r["nome"]) for r in
                                          self.ctx.banco.todos("SELECT id, nome FROM setores_impressao WHERE ativo = 1 "
                                                                "ORDER BY ordem, nome")]
        self.setor_var = tk.StringVar(value=self.setores[0][1])
        combo = ttk.Combobox(topo, textvariable=self.setor_var, values=[s[1] for s in self.setores],
                              state="readonly", width=24)
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", lambda e: self.atualizar())
        if len(self.setores) <= 1:
            topo.pack_forget()
        self.grade = tema.Grade(corpo, [("pos", "Posição", 160, "w"), ("produto", "Produto", 220, "w"),
                                        ("qtd", "Qtd", 60, "e"), ("obs", "Observação", 220, "w"),
                                        ("min", "Minutos", 70, "e"), ("sit", "Situação", 110, "w")], altura=16)
        self.grade.pack(fill="both", expand=True)
        self.grade.tag("pendente", foreground=tema.COR["aviso"])
        self.grade.tag("em_preparo", foreground=tema.COR["ok"])
        self.grade.tree.bind("<Double-1>", lambda e: self.avancar())
        barra = ttk.Frame(corpo)
        barra.pack(fill="x", pady=(10, 0))
        ttk.Button(barra, text="Iniciar preparo", command=lambda: self._marcar("em_preparo")).pack(side="left")
        ttk.Button(barra, text="Marcar pronto", command=lambda: self._marcar("entregue")).pack(side="left", padx=6)
        ttk.Button(barra, text="Avançar (clique duplo)", command=self.avancar).pack(side="left")
        ttk.Button(barra, text="Fechar (Esc)", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.atualizar()
        tema.centralizar(self, master.winfo_toplevel())
        self.transient(master.winfo_toplevel())

    def _setor_id(self) -> int | None:
        nome = self.setor_var.get()
        for id_, n in self.setores:
            if n == nome:
                return id_ or None
        return None

    def _cancelar_agendamento(self) -> None:
        if self._id_after:
            try:
                self.after_cancel(self._id_after)
            except (tk.TclError, ValueError):
                pass
            self._id_after = None

    def destroy(self) -> None:
        self._cancelar_agendamento()
        super().destroy()

    def atualizar(self) -> None:
        self._cancelar_agendamento()
        try:
            atual = self.grade.selecionado()
            itens = self.preparo.fila(self._setor_id())
            self.grade.preencher(
                [[i["posicao_rotulo"], i["produto"], i["quantidade"], i["observacao"] or "", i["minutos"],
                  SITUACAO.get(i["status_preparo"], i["status_preparo"])] for i in itens],
                [i["id"] for i in itens], [(i["status_preparo"],) for i in itens])
            if atual:
                self.grade.selecionar(atual)
            self._id_after = self.after(2000, self.atualizar)
        except tk.TclError:
            pass

    def _selecionado(self) -> int | None:
        s = self.grade.selecionado()
        if s is None:
            tema.aviso(self, "Selecione um item da lista.")
            return None
        return int(s)

    def _marcar(self, status: str) -> None:
        i = self._selecionado()
        if i is not None:
            ok, _ = tema.tratar(self, self.preparo.marcar, i, status)
            if ok:
                self.atualizar()

    def avancar(self) -> None:
        i = self._selecionado()
        if i is not None:
            ok, _ = tema.tratar(self, self.preparo.avancar, i)
            if ok:
                self.atualizar()
