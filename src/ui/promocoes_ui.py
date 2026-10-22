"""Gestão Tk das promoções e da única faixa por temperatura já cadastradas."""
import tkinter as tk
from tkinter import messagebox, ttk

from src.controllers.promocoes_controller import AVISO, CAMPOS, PromocoesController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio


class JanelaPromocoes(tk.Toplevel):
    def __init__(self, master, ctx):
        self.ctx = ctx
        self.controller = PromocoesController(ctx)
        self.controller.exigir_acesso()
        super().__init__(master)
        self.title("Promoções e faixas — sem acúmulo")
        self.geometry("930x720")
        self.produto_id = None
        self.campos = {}
        self.linhas = []
        conteudo = ttk.Frame(self, padding=12)
        conteudo.pack(fill="both", expand=True)
        ttk.Label(conteudo, text=AVISO, wraplength=880).pack(fill="x", pady=(0, 8))
        busca = ttk.Frame(conteudo)
        busca.pack(fill="x")
        ttk.Label(busca, text="Buscar produto:").pack(side="left")
        self.busca = ttk.Entry(busca)
        self.busca.pack(side="left", fill="x", expand=True, padx=6)
        self.busca.bind("<Return>", lambda _e: self.pesquisar())
        ttk.Button(busca, text="Pesquisar / recarregar", command=self.pesquisar).pack(side="left")
        self.produto = ttk.Combobox(conteudo, state="readonly")
        self.produto.pack(fill="x", pady=6)
        self.produto.bind("<<ComboboxSelected>>", self.carregar)
        abas = ttk.Notebook(conteudo)
        abas.pack(fill="x")
        secoes = {}
        for campo in CAMPOS:
            secao = "Promoções" if campo.secao == "Promoções" else "Preços e faixas"
            if secao not in secoes:
                pagina = ttk.Frame(abas, padding=8)
                pagina.columnconfigure(1, weight=1)
                abas.add(pagina, text=secao)
                secoes[secao] = pagina
            pagina = secoes[secao]
            linha = len(pagina.grid_slaves()) // 2
            ttk.Label(pagina, text=campo.rotulo + (" (R$)" if campo.tipo == "dinheiro" else "")).grid(
                row=linha, column=0, sticky="w", padx=4, pady=2)
            if campo.tipo == "escolha":
                editor = ttk.Combobox(pagina, state="readonly",
                                      values=[""] + [rotulo for _, rotulo in campo.opcoes])
            else:
                editor = ttk.Entry(pagina)
            editor.grid(row=linha, column=1, sticky="ew", padx=4, pady=2)
            self.campos[campo.nome] = editor
        ttk.Button(conteudo, text="Salvar regras do produto", command=self.salvar).pack(anchor="e", pady=6)
        simulacao = ttk.LabelFrame(conteudo, text="Simular os campos acima (não salva)", padding=8)
        simulacao.pack(fill="x")
        ttk.Label(simulacao, text="Quantidade").grid(row=0, column=0, sticky="w")
        self.quantidade = ttk.Entry(simulacao, width=12)
        self.quantidade.insert(0, "1")
        self.quantidade.grid(row=0, column=1, padx=6)
        self.temperatura = ttk.Combobox(simulacao, state="readonly", values=["natural", "gelada"], width=12)
        self.temperatura.set("natural")
        self.temperatura.grid(row=0, column=2, padx=6)
        ttk.Label(simulacao, text="Data/hora local").grid(row=1, column=0, sticky="w")
        self.quando = ttk.Entry(simulacao, width=24)
        self.quando.insert(0, fmt.agora())
        self.quando.grid(row=1, column=1, columnspan=2, sticky="ew", padx=6)
        ttk.Button(simulacao, text="Simular", command=self.simular).grid(row=1, column=3, padx=6)
        self.resultado = tk.Text(conteudo, height=10, wrap="word", state="disabled")
        self.resultado.pack(fill="both", expand=True, pady=8)
        self.pesquisar()

    def exigir_acesso(self):
        self.controller.exigir_acesso()

    def _mostrar(self, texto):
        self.resultado.configure(state="normal")
        self.resultado.delete("1.0", "end")
        self.resultado.insert("1.0", texto)
        self.resultado.configure(state="disabled")

    def pesquisar(self):
        try:
            self.linhas = self.controller.listar(self.busca.get())
            self.produto.configure(values=[f"{p['codigo']} — {p['nome']}" for p in self.linhas])
            self.produto_id = None
            self.produto.set("")
            self._mostrar("Selecione um produto. Pesquisar/recarregar descarta alterações não salvas.")
            if self.linhas:
                self.produto.current(0)
                self.carregar()
        except ErroNegocio as erro:
            messagebox.showerror("Promoções", str(erro), parent=self)

    def carregar(self, _evento=None):
        self.produto_id = None
        try:
            indice = self.produto.current()
            if indice < 0:
                return
            p = self.controller.obter(self.linhas[indice]["id"])
            self.produto_id = p["id"]
            valores = self.ctx.cadastros.exibir("produtos", p)
            for nome, editor in self.campos.items():
                if isinstance(editor, ttk.Combobox):
                    editor.set(valores.get(nome, "") or "")
                else:
                    editor.delete(0, "end")
                    editor.insert(0, valores.get(nome, "") or "")
            self._mostrar("Cadastro carregado. Simular avalia os campos atuais, mesmo antes de salvar.")
        except ErroNegocio as erro:
            messagebox.showerror("Promoções", str(erro), parent=self)

    def valores(self):
        return {nome: editor.get() for nome, editor in self.campos.items()}

    def salvar(self):
        try:
            if self.produto_id is None:
                return
            self.controller.salvar(self.produto_id, self.valores())
            self._mostrar("Regras salvas. Vendas e retratos existentes não foram alterados.")
        except ErroNegocio as erro:
            messagebox.showerror("Promoções", str(erro), parent=self)

    def simular(self):
        try:
            if self.produto_id is None:
                return
            resultado = self.controller.simular(self.produto_id, self.quantidade.get(),
                                                self.temperatura.get(), self.quando.get(), self.valores())
            self._mostrar(self.controller.descrever(resultado))
        except ErroNegocio as erro:
            self._mostrar(str(erro))


def abrir(master, ctx):
    return JanelaPromocoes(master, ctx)
