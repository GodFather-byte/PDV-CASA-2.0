"""Consulta e registro explícito de posse de retornáveis por cliente (Tk)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.controllers.retornaveis_controller import AVISO, TIPOS, RetornaveisController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao


class JanelaRetornaveis(tk.Toplevel):
    def __init__(self, master, ctx):
        self.ctx = ctx
        self.exigir_acesso()
        super().__init__(master)
        self.title("Retornáveis por cliente")
        self.geometry("1080x760")
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)
        ttk.Label(corpo, text=AVISO, wraplength=1000).pack(fill="x", pady=(0, 12))

        formulario = ttk.Frame(corpo)
        formulario.pack(fill="x")
        formulario.columnconfigure(1, weight=1)
        self.cliente = ttk.Combobox(formulario, state="readonly")
        self.produto = ttk.Combobox(formulario, state="readonly")
        self.tipo = ttk.Combobox(formulario, state="readonly", values=list(TIPOS.values()))
        self.tipo.current(0)
        self.quantidade = ttk.Entry(formulario)
        self.motivo = ttk.Entry(formulario)
        for linha, (rotulo, campo) in enumerate((
                ("Cliente (inativos: somente consulta)", self.cliente),
                ("Produto", self.produto), ("Movimento", self.tipo),
                ("Quantidade (até 4 casas)", self.quantidade), ("Motivo obrigatório", self.motivo))):
            ttk.Label(formulario, text=rotulo).grid(row=linha, column=0, sticky="w", padx=(0, 10))
            campo.grid(row=linha, column=1, sticky="ew", pady=3)
        self.cliente.bind("<<ComboboxSelected>>", lambda _evento: self.atualizar())

        acoes = ttk.Frame(corpo)
        acoes.pack(fill="x", pady=8)
        self.btn_registrar = ttk.Button(acoes, text="Registrar movimento", command=self.registrar)
        self.btn_registrar.pack(side="left")
        ttk.Button(acoes, text="Atualizar", command=self.atualizar).pack(side="left", padx=8)
        ttk.Button(acoes, text="Fechar", command=self.destroy).pack(side="right")
        self.mensagem = ttk.Label(corpo, text="")
        self.mensagem.pack(fill="x")
        ttk.Label(corpo, text="Saldo em posse do cliente, por produto").pack(anchor="w")
        self.grade_saldos = self._tabela(corpo, ("Código", "Produto", "Saldo"), 4)
        ttk.Label(corpo, text="Histórico permanente — movimentos mais recentes primeiro").pack(anchor="w")
        self.grade_historico = self._tabela(
            corpo, ("Data", "Produto", "Movimento", "Quantidade", "Saldo após", "Motivo", "Operador"), 9)
        self.clientes = []
        self.produtos = []
        self.atualizar()

    @staticmethod
    def _tabela(pai, colunas, altura):
        quadro = ttk.Frame(pai)
        quadro.pack(fill="both", expand=True, pady=6)
        tabela = ttk.Treeview(quadro, columns=colunas, show="headings", height=altura)
        for coluna in colunas:
            tabela.heading(coluna, text=coluna)
            tabela.column(coluna, width=145, minwidth=75)
        vertical = ttk.Scrollbar(quadro, orient="vertical", command=tabela.yview)
        horizontal = ttk.Scrollbar(quadro, orient="horizontal", command=tabela.xview)
        tabela.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        quadro.columnconfigure(0, weight=1)
        quadro.rowconfigure(0, weight=1)
        tabela.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        return tabela

    def _controller(self):
        return RetornaveisController(self.ctx.banco, self.ctx.operador_id)

    def exigir_acesso(self):
        self._controller().exigir_acesso()

    @staticmethod
    def _selecionado(campo, opcoes):
        indice = campo.current()
        return opcoes[indice]["id"] if 0 <= indice < len(opcoes) else None

    def _carregar_opcoes(self):
        cliente_id = self._selecionado(self.cliente, self.clientes)
        produto_id = self._selecionado(self.produto, self.produtos)
        self.clientes = self.ctx.banco.todos("SELECT id, nome, ativo FROM clientes ORDER BY nome, id")
        self.produtos = self.ctx.banco.todos(
            "SELECT id, codigo, nome FROM produtos WHERE ativo = 1 ORDER BY nome")
        for campo, opcoes, escolhido, rotulos in (
            (self.cliente, self.clientes, cliente_id, [
                f"{c['id']} — {c['nome']}" + (" (inativo)" if not c["ativo"] else "")
                for c in self.clientes]),
            (self.produto, self.produtos, produto_id, [
                f"{p['codigo']} — {p['nome']}" for p in self.produtos]),
        ):
            campo.configure(values=rotulos)
            campo.set("")
            for indice, registro in enumerate(opcoes):
                if registro["id"] == escolhido:
                    campo.current(indice)
                    break

    def _limpar_grades(self):
        for grade in (self.grade_saldos, self.grade_historico):
            for item in grade.get_children():
                grade.delete(item)

    def _erro(self, erro):
        if isinstance(erro, ErroPermissao):
            self._limpar_grades()
            self.cliente.set("")
            self.produto.set("")
            self.cliente.configure(values=())
            self.produto.configure(values=())
            self.clientes = []
            self.produtos = []
        self.mensagem.configure(text=str(erro))
        return False

    def atualizar(self):
        try:
            self.exigir_acesso()
            self._carregar_opcoes()
            self._limpar_grades()
            cliente_id = self._selecionado(self.cliente, self.clientes)
            if cliente_id is None:
                self.mensagem.configure(text="Selecione um cliente para consultar seu saldo e histórico.")
                return True
            controle = self._controller()
            for saldo in controle.saldos(cliente_id):
                self.grade_saldos.insert("", "end", values=(
                    saldo["codigo"], saldo["produto"], fmt.fmt_qtd(saldo["saldo"], 4)))
            for movimento in controle.historico(cliente_id):
                self.grade_historico.insert("", "end", values=(
                    movimento["criado_em"], movimento["produto"], TIPOS[movimento["tipo"]],
                    fmt.fmt_qtd(movimento["quantidade"], 4), fmt.fmt_qtd(movimento["saldo_apos"], 4),
                    movimento["motivo"], movimento["operador"]))
            self.mensagem.configure(text="Saldos somente de empréstimos e devoluções registrados aqui.")
            return True
        except ErroNegocio as erro:
            return self._erro(erro)

    def registrar(self):
        try:
            self.exigir_acesso()
            indice = self.tipo.current()
            tipo = list(TIPOS)[indice] if indice >= 0 else ""
            self._controller().registrar(
                self._selecionado(self.cliente, self.clientes),
                self._selecionado(self.produto, self.produtos), tipo,
                self.quantidade.get(), self.motivo.get())
            self.quantidade.delete(0, "end")
            self.motivo.delete(0, "end")
            self.atualizar()
            self.mensagem.configure(text="Movimento registrado. Nenhuma venda, cobrança ou alteração de estoque.")
            return True
        except ErroNegocio as erro:
            return self._erro(erro)


def abrir(master, ctx):
    return JanelaRetornaveis(master, ctx)
