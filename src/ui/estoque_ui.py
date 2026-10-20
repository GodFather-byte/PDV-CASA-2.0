"""Painel de Estoque: a visão geral do estoque num lugar só, no mesmo visual escuro do menu principal.

Mostra quantos produtos estão sem estoque / para repor / normais e o valor parado, deixa filtrar e procurar enquanto
digita, e permite dar entrada, saída, perda, contar e mudar o mínimo de um produto em dois cliques (sem montar lançamento
na mão). Os lançamentos completos (compra com nota, pedido, inicial...) continuam na janela "Novo lançamento"."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.core import formatacao as fmt
from src.ui import tema
from src.ui.menu_widgets import PAL, Cartao, misturar
from src.ui.visualizador import Visualizador

FONTE = "Segoe UI"
SITUACAO = {"sem": ("Sem estoque", PAL["vermelho"]), "ponto": ("Repor", PAL["ambar"]), "normal": ("Normal", PAL["verde"]),
             "livre": ("Sem controle", PAL["suave"])}
FILTROS = [("todos", "Todos"), ("sem", "Sem estoque"), ("ponto", "Repor"), ("normal", "Normal"), ("livre", "Sem controle")]
# Cada ação rápida: rótulo do botão, tipo de movimento, cor, título/pergunta do diálogo.
ACOES = [
    ("entrada", "＋  Entrada", PAL["verde"], "Chegou mercadoria", "Quantas unidades entraram?"),
    ("saida", "－  Saída", PAL["azul"], "Saiu mercadoria", "Quantas unidades saíram (sem ser venda)?"),
    ("descarte", "Perda / quebra", PAL["vermelho"], "Perda ou quebra", "Quantas unidades foram perdidas?"),
    ("quebra", "Quebra", PAL["vermelho"], "Perda por quebra", "Quantas unidades quebraram?"),
    ("oxidacao", "Oxidação", PAL["ambar"], "Perda por oxidação", "Quantas unidades oxidaram?"),
    ("devolucao", "Devolução", PAL["violeta"], "Devolução", "Quantas unidades foram devolvidas?"),
    ("contagem", "Contei e ajustar", PAL["ambar"], "Contagem na prateleira", "Quantas unidades existem de verdade agora?"),
]


def curta(q: float) -> str:
    """Quantidade sem zeros sobrando: 24 (não 24,000) e 2,5 (não 2,500)."""
    t = fmt.fmt_qtd(q)
    return t.rstrip("0").rstrip(",") if "," in t else t


def nivel(p: dict, largura: int = 10) -> str:
    """Barrinha de texto: cheia quando o estoque chega ao dobro do mínimo (folga confortável)."""
    if p["situacao"] == "livre":
        return "—"
    if p["estoque_minimo"] <= 0:
        return "sem mínimo" if p["qt_atual"] > 0 else "▱" * largura
    cheio = round(min(max(p["qt_atual"], 0) / (p["estoque_minimo"] * 2), 1) * largura)
    return "▰" * cheio + "▱" * (largura - cheio)


def _estilos(root: tk.Misc) -> None:
    s = ttk.Style(root)
    s.configure("Estoque.Treeview", background=PAL["cartao"], fieldbackground=PAL["cartao"], foreground=PAL["texto"],
                rowheight=28, borderwidth=0, font=(FONTE, 10))
    s.configure("Estoque.Treeview.Heading", background=PAL["lateral"], foreground=PAL["suave"], relief="flat",
                font=(FONTE, 9, "bold"), padding=(6, 7))
    s.map("Estoque.Treeview", background=[("selected", PAL["selecao"])], foreground=[("selected", PAL["selecao_texto"])])
    s.map("Estoque.Treeview.Heading", background=[("active", PAL["cartao_hover"])])
    s.configure("Estoque.TCombobox", fieldbackground=PAL["cartao"], background=PAL["cartao"], foreground=PAL["texto"],
                arrowcolor=PAL["suave"], bordercolor=PAL["borda"], lightcolor=PAL["cartao"], darkcolor=PAL["cartao"], padding=4)
    s.map("Estoque.TCombobox", fieldbackground=[("readonly", PAL["cartao"])], foreground=[("readonly", PAL["texto"])],
          selectbackground=[("readonly", PAL["cartao"])], selectforeground=[("readonly", PAL["texto"])])
    root.option_add("*TCombobox*Listbox.background", PAL["cartao"])
    root.option_add("*TCombobox*Listbox.foreground", PAL["texto"])
    root.option_add("*TCombobox*Listbox.selectBackground", PAL["selecao"])
    s.configure("Estoque.Vertical.TScrollbar", background=PAL["borda"], troughcolor=PAL["fundo"], bordercolor=PAL["fundo"],
                arrowcolor=PAL["suave"])


class Chip(tk.Label):
    """Botão de filtro em formato de pílula; o selecionado fica preenchido com a cor dele."""

    def __init__(self, pai, texto: str, cor: str, comando):
        super().__init__(pai, text=texto, font=(FONTE, 9, "bold"), padx=14, pady=5, cursor="hand2")
        self.cor, self.comando = cor, comando
        self.bind("<Button-1>", lambda e: self.comando())
        self.marcar(False)

    def marcar(self, ligado: bool) -> None:
        self.ligado = ligado
        if ligado:
            self.configure(bg=self.cor, fg=PAL["sobre"])
        else:
            self.configure(bg=PAL["cartao"], fg=PAL["suave"])


class Botao(tk.Label):
    """Botão grande do painel de detalhes (cor própria, realça ao passar o mouse)."""

    def __init__(self, pai, texto: str, cor: str, comando):
        super().__init__(pai, text=texto, font=(FONTE, 10, "bold"), fg=cor, bg=PAL["cartao"], pady=6, cursor="hand2",
                         highlightthickness=1, highlightbackground=misturar(PAL["borda"], cor, 0.5))
        self.cor, self.comando, self.ativo = cor, comando, True
        self.bind("<Enter>", lambda e: self.ativo and self.configure(bg=misturar(PAL["cartao"], cor, 0.22)))
        self.bind("<Leave>", lambda e: self.configure(bg=PAL["cartao"]))
        self.bind("<Button-1>", lambda e: self.comando() if self.ativo else None)

    def habilitar(self, sim: bool) -> None:
        self.ativo = sim
        self.configure(fg=self.cor if sim else PAL["mudo"], cursor="hand2" if sim else "")


class PainelEstoque(tk.Toplevel):
    def __init__(self, master, ctx, filtro: str = "todos"):
        super().__init__(master)
        self.ctx, self.est = ctx, ctx.estoque
        self.title("Estoque")
        self.configure(bg=PAL["fundo"])
        self.geometry("1280x840")
        self.minsize(1000, 700)
        _estilos(self)
        self.filtro = filtro if filtro in dict(FILTROS) else "todos"
        self.produto: dict | None = None
        self.linhas: list[dict] = []
        self._ordenar: tuple[str, bool] = ("nome", False)
        self.v_busca, self.v_grupo = tk.StringVar(), tk.StringVar(value="Todos os grupos")
        self.v_visao = tk.StringVar(value="Geral")
        self._montar()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<F5>", lambda e: self.atualizar())
        self.bind("<Control-f>", lambda e: (self.e_busca.focus_set(), "break")[1])
        self.bind("<Control-n>", lambda e: self.novo_lancamento())
        self.v_busca.trace_add("write", lambda *_: self.atualizar())
        self.atualizar()
        self.e_busca.focus_set()

    # ------------------------------------------------------------- layout
    def _montar(self) -> None:
        topo = tk.Frame(self, bg=PAL["fundo"])
        topo.pack(fill="x", padx=22, pady=(18, 0))
        tit = tk.Frame(topo, bg=PAL["fundo"])
        tit.pack(side="left")
        tk.Label(tit, text="Estoque", font=(FONTE, 22, "bold"), fg=PAL["texto"], bg=PAL["fundo"]).pack(anchor="w")
        self.lbl_sub = tk.Label(tit, text="", font=(FONTE, 10), fg=PAL["suave"], bg=PAL["fundo"])
        self.lbl_sub.pack(anchor="w")
        acoes = tk.Frame(topo, bg=PAL["fundo"])
        acoes.pack(side="right")
        self.b_novo = Botao(acoes, "Novo lançamento  (Ctrl+N)", PAL["azul"], self.novo_lancamento)
        self.b_pedido = Botao(acoes, "Gerar pedido do que falta", PAL["ambar"], self.gerar_pedido)
        self.b_lista = Botao(acoes, "Lista de compras", PAL["turquesa"], self.lista_de_compras)
        for b in (self.b_novo, self.b_pedido, self.b_lista):
            b.configure(padx=14)
            b.pack(side="left", padx=(8, 0))

        cards = tk.Frame(self, bg=PAL["fundo"])
        cards.pack(fill="x", padx=22, pady=(16, 0))
        self.cartoes: dict[str, Cartao] = {}
        for i, (chave, titulo, cor, destino) in enumerate([
                ("total", "Produtos controlados", PAL["azul"], "todos"), ("sem", "Sem estoque", PAL["vermelho"], "sem"),
                ("ponto", "Para repor", PAL["ambar"], "ponto"), ("normal", "Estoque normal", PAL["verde"], "normal"),
                ("valor", "Valor em estoque", PAL["violeta"], None)]):
            c = Cartao(cards, titulo, cor, "", (lambda d=destino: self.filtrar(d)) if destino else None)
            c.grid(row=0, column=i, sticky="nsew", padx=(0, 0 if i == 4 else 12))
            cards.columnconfigure(i, weight=1, uniform="c")
            self.cartoes[chave] = c

        barra = tk.Frame(self, bg=PAL["fundo"])
        barra.pack(fill="x", padx=22, pady=(16, 0))
        self.chips: dict[str, Chip] = {}
        for chave, rotulo in FILTROS:
            cor = SITUACAO[chave][1] if chave in SITUACAO else PAL["azul"]
            ch = Chip(barra, rotulo, cor, lambda c=chave: self.filtrar(c))
            ch.pack(side="left", padx=(0, 6))
            self.chips[chave] = ch
        caixa = tk.Frame(barra, bg=PAL["cartao"], highlightthickness=1, highlightbackground=PAL["borda"])
        caixa.pack(side="left", padx=(14, 0))
        tk.Label(caixa, text="🔍", bg=PAL["cartao"], fg=PAL["suave"]).pack(side="left", padx=(8, 0))
        self.e_busca = tk.Entry(caixa, textvariable=self.v_busca, width=30, bg=PAL["cartao"], fg=PAL["texto"], relief="flat",
                                insertbackground=PAL["texto"], font=(FONTE, 11))
        self.e_busca.pack(side="left", padx=6, pady=5)
        self.cb_grupo = ttk.Combobox(barra, textvariable=self.v_grupo, state="readonly", width=24, style="Estoque.TCombobox",
                                     values=["Todos os grupos", *self.est.grupos()])
        self.cb_grupo.pack(side="left", padx=(12, 0))
        self.cb_grupo.bind("<<ComboboxSelected>>", lambda e: self.atualizar())
        self.lbl_cont = tk.Label(barra, text="", font=(FONTE, 9), fg=PAL["mudo"], bg=PAL["fundo"])
        self.lbl_cont.pack(side="right")

        visao = tk.Frame(self, bg=PAL["fundo"])
        visao.pack(fill="x", padx=22, pady=(8, 0))
        tk.Label(visao, text="Visão:", bg=PAL["fundo"], fg=PAL["suave"]).pack(side="left")
        self.cb_visao = ttk.Combobox(visao, textvariable=self.v_visao, values=["Geral", "Adega"],
                                     state="readonly", width=12, style="Estoque.TCombobox")
        self.cb_visao.pack(side="left", padx=8)
        self.cb_visao.bind("<<ComboboxSelected>>", lambda e: self.atualizar())
        tk.Label(visao, text="Adega: categorias típicas e produtos configurados; prioridade alta = sem estoque, média = repor. "
                            "Pedidos e lista de compras são gerais.",
                 bg=PAL["fundo"], fg=PAL["suave"]).pack(side="left")

        corpo = tk.Frame(self, bg=PAL["fundo"])
        corpo.pack(fill="both", expand=True, padx=22, pady=(12, 8))
        self._montar_detalhe(corpo)          # empacotado primeiro: a lista toma só o que sobrar, o painel nunca é espremido
        lista = tk.Frame(corpo, bg=PAL["fundo"])
        lista.pack(side="left", fill="both", expand=True)
        colunas = [("situ", "Situação", 118, "w"), ("cod", "Código", 60, "w"), ("nome", "Produto", 175, "w"),
                   ("grupo", "Grupo", 100, "w"), ("qtd", "Qtd.", 85, "e"), ("min", "Mínimo", 65, "e"),
                   ("nivel", "Nível", 95, "w"), ("repor", "Repor", 60, "e"), ("valor", "Valor parado", 100, "e")]
        self.tree = ttk.Treeview(lista, columns=[c[0] for c in colunas], show="headings", style="Estoque.Treeview", selectmode="browse")
        for cid, titulo, largura, anc in colunas:
            self.tree.heading(cid, text=titulo, anchor=anc, command=lambda c=cid: self.ordenar(c))
            self.tree.column(cid, width=largura, anchor=anc, stretch=cid == "nome")
        rolagem = ttk.Scrollbar(lista, orient="vertical", command=self.tree.yview, style="Estoque.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        for sit, (_, cor) in SITUACAO.items():
            self.tree.tag_configure(sit, foreground=cor if sit != "normal" else PAL["texto"])
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._selecionou())
        self.tree.bind("<Double-1>", lambda e: self.registrar_dialogo("entrada"))
        self.tree.bind("<Return>", lambda e: self.registrar_dialogo("entrada"))
        self.lbl_vazio = tk.Label(lista, text="", font=(FONTE, 11), fg=PAL["suave"], bg=PAL["cartao"])
        tk.Label(self, text="Dica: clique num produto para ver o histórico e agir.  Duplo clique ou Enter = dar entrada.  "
                            "Clique no título da coluna para ordenar.  F5 atualiza.", font=(FONTE, 9), fg=PAL["mudo"],
                 bg=PAL["fundo"], anchor="w").pack(fill="x", padx=22, pady=(0, 12))

    def _montar_detalhe(self, pai) -> None:
        d = tk.Frame(pai, bg=PAL["cartao"], width=340, highlightthickness=1, highlightbackground=PAL["borda"])
        d.pack(side="right", fill="y", padx=(14, 0))
        d.pack_propagate(False)
        self.d_nome = tk.Label(d, text="Selecione um produto", font=(FONTE, 14, "bold"), fg=PAL["texto"], bg=PAL["cartao"],
                               wraplength=300, justify="left", anchor="w")
        self.d_nome.pack(fill="x", padx=16, pady=(16, 0))
        self.d_situ = tk.Label(d, text="", font=(FONTE, 9, "bold"), fg=PAL["suave"], bg=PAL["cartao"], anchor="w")
        self.d_situ.pack(fill="x", padx=16)
        self.d_qtd = tk.Label(d, text="", font=(FONTE, 22, "bold"), fg=PAL["texto"], bg=PAL["cartao"], anchor="w")
        self.d_qtd.pack(fill="x", padx=16, pady=(6, 0))
        self.d_barra = tk.Canvas(d, height=10, bg=PAL["cartao"], highlightthickness=0)
        self.d_barra.pack(fill="x", padx=16, pady=(2, 6))
        self.d_barra.bind("<Configure>", lambda e: self._desenhar_barra())
        self.d_info = tk.Label(d, text="", font=(FONTE, 9), fg=PAL["suave"], bg=PAL["cartao"], justify="left", anchor="w", wraplength=300)
        self.d_info.pack(fill="x", padx=16)
        self.botoes: dict[str, Botao] = {}
        grade = tk.Frame(d, bg=PAL["cartao"])
        grade.pack(fill="x", padx=16, pady=(12, 0))
        for i, (tipo, rotulo, cor, _, _) in enumerate(ACOES):
            b = Botao(grade, rotulo, cor, lambda t=tipo: self.registrar_dialogo(t))
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 6 if i % 2 == 0 else 0), pady=(0, 6))
            grade.columnconfigure(i % 2, weight=1, uniform="b")
            self.botoes[tipo] = b
        self.b_minimo = Botao(d, "Definir estoque mínimo", PAL["violeta"], self.definir_minimo)
        self.b_minimo.pack(fill="x", padx=16)
        self.b_cadastro = Botao(d, "Editar cadastro do produto", PAL["turquesa"], self.editar_cadastro)
        self.b_cadastro.pack(fill="x", padx=16, pady=(6, 0))
        tk.Label(d, text="ÚLTIMOS MOVIMENTOS", font=(FONTE, 8, "bold"), fg=PAL["mudo"], bg=PAL["cartao"], anchor="w").pack(
            fill="x", padx=16, pady=(14, 4))
        self.hist = ttk.Treeview(d, columns=("quando", "tipo", "qtd", "apos"), show="headings", style="Estoque.Treeview", height=5,
                                 selectmode="none")
        for cid, titulo, largura, anc in (("quando", "Quando", 92, "w"), ("tipo", "O quê", 96, "w"), ("qtd", "Qtd.", 52, "e"),
                                          ("apos", "Ficou", 52, "e")):
            self.hist.heading(cid, text=titulo, anchor=anc)
            self.hist.column(cid, width=largura, anchor=anc, stretch=cid == "tipo")
        self.hist.tag_configure("mais", foreground=PAL["verde"])
        self.hist.tag_configure("menos", foreground=PAL["vermelho"])
        self.hist.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        self._habilitar(False)

    # ------------------------------------------------------------- dados
    def atualizar(self) -> None:
        """Recarrega tudo respeitando filtro, busca e grupo. Mantém o produto selecionado, se ele ainda estiver na lista."""
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        adega = self.v_visao.get() == "Adega"
        r = self.est.resumo(adega=adega)
        self.cartoes["total"].definir(str(r["total"]), "controlados e ativos")
        for chave in ("sem", "ponto", "normal"):
            self.cartoes[chave].definir(str(r[chave]), f"{round(r[chave] * 100 / r['total'])}% dos produtos" if r["total"] else "")
        self.cartoes["valor"].definir(fmt.fmt_brl(r["valor_cent"]), "quantidade × último preço de compra")
        grupo = self.v_grupo.get()
        self.linhas = self.est.painel(None if self.filtro == "todos" else self.filtro, self.v_busca.get(),
                                      None if grupo.startswith("Todos") else grupo, adega=adega)
        coluna, invertido = self._ordenar
        chaves = {"situ": lambda p: ("sem", "ponto", "normal", "livre").index(p["situacao"]), "cod": lambda p: p["codigo"],
                  "nome": lambda p: p["nome"].casefold(), "grupo": lambda p: p["grupo"].casefold(), "qtd": lambda p: p["qt_atual"],
                  "min": lambda p: p["estoque_minimo"], "nivel": lambda p: p["qt_atual"] / p["estoque_minimo"] if p["estoque_minimo"] else 0,
                  "repor": lambda p: p["repor"], "valor": lambda p: p["valor_cent"]}
        if not adega or coluna != "nome":
            self.linhas.sort(key=chaves[coluna], reverse=invertido)
        atual = self.produto["id"] if self.produto else None
        self.tree.delete(*self.tree.get_children())
        for p in self.linhas:
            rotulo, _ = SITUACAO[p["situacao"]]
            if adega:
                rotulo = f"{p['prioridade']} · {rotulo}"
            self.tree.insert("", "end", iid=str(p["id"]), tags=(p["situacao"],), values=[
                f"● {rotulo}", p["codigo"].lstrip("0") or "0", p["nome"],
                f"{p['grupo']} / {p['categoria']}" if adega else p["grupo"],
                "—" if p["situacao"] == "livre" else f"{curta(p['qt_atual'])} {p['unidade']}",
                curta(p["estoque_minimo"]) if p["estoque_minimo"] else "-", nivel(p),
                curta(p["repor"]) if p["repor"] else "",
                "—" if p["situacao"] == "livre" else fmt.fmt_brl(p["valor_cent"])])
        for chave, chip in self.chips.items():
            chip.marcar(chave == self.filtro)
        falta = r["sem"] + r["ponto"]
        sub = (f"{falta} produto(s) precisam de atenção." if falta else "Tudo certo: nenhum produto precisa de reposição.") \
            if r["total"] else "Nenhum produto controla estoque ainda."
        if r["livre"]:
            sub += f"  {r['livre']} produto(s) ainda não controlam estoque (filtro 'Sem controle')."
        self.lbl_sub.configure(text=("Visão Adega · " if adega else "") + sub)
        self.lbl_cont.configure(text=f"{len(self.linhas)} de {r['total']} produtos")
        if not self.linhas:
            self.lbl_vazio.configure(text="Nenhum produto encontrado com esse filtro." if r["total"] or self.filtro == "livre" or
                                          self.v_busca.get() else
                                          "Nenhum produto controla estoque ainda.\nEscolha 'Sem controle', clique no produto e use\n'Contei e ajustar' para começar.")
            self.lbl_vazio.place(relx=0.5, rely=0.4, anchor="center")
        else:
            self.lbl_vazio.place_forget()
        self.b_pedido.habilitar(any(p["repor"] > 0 for p in self.est.painel()))
        if atual is not None and self.tree.exists(str(atual)):
            self.tree.selection_set(str(atual))
        else:
            self.produto = None
            self._mostrar_detalhe()

    def filtrar(self, situacao: str) -> None:
        self.filtro = situacao
        self.atualizar()

    def ordenar(self, coluna: str) -> None:
        antiga, invertido = self._ordenar
        self._ordenar = (coluna, not invertido if coluna == antiga else coluna in ("qtd", "valor", "repor"))
        self.atualizar()

    def _selecionou(self) -> None:
        s = self.tree.selection()
        self.produto = next((p for p in self.linhas if str(p["id"]) == s[0]), None) if s else None
        self._mostrar_detalhe()

    # ----------------------------------------------------------- detalhe
    def _habilitar(self, sim: bool) -> None:
        for b in (*self.botoes.values(), self.b_minimo, self.b_cadastro):
            b.habilitar(sim)

    def _mostrar_detalhe(self) -> None:
        p = self.produto
        self.hist.delete(*self.hist.get_children())
        self._habilitar(p is not None)
        if p is None:
            self.d_nome.configure(text="Selecione um produto")
            self.d_situ.configure(text="")
            self.d_qtd.configure(text="")
            self.d_info.configure(text="Clique num produto da lista para ver o histórico\ne dar entrada, saída ou ajustar a contagem.")
            self._desenhar_barra()
            return
        rotulo, cor = SITUACAO[p["situacao"]]
        livre = p["situacao"] == "livre"
        for tipo in ("saida", "descarte"):                 # sem controle não há o que tirar: primeiro dê entrada ou conte
            self.botoes[tipo].habilitar(not livre)
        self.d_nome.configure(text=p["nome"])
        self.d_situ.configure(text=f"● {rotulo.upper()}", fg=cor)
        self.d_qtd.configure(text="—" if livre else f"{curta(p['qt_atual'])} {p['unidade']}",
                             fg=cor if p["situacao"] != "normal" else PAL["texto"])
        emb = self.est.produtos.embalagem(p["id"]) if livre else None
        if emb:                                            # fardo/caixa: entrada, saída e perda vão para as unidades
            for tipo in ("saida", "descarte"):
                self.botoes[tipo].habilitar(True)
            self.botoes["contagem"].habilitar(False)
            self.d_situ.configure(text="● FARDO / CAIXA", fg=PAL["suave"])
            self.d_info.configure(text=f"Fardo/caixa de {emb['quantidade']} '{emb['unitario']}': não tem estoque próprio. "
                                       f"Vender 1 baixa {emb['quantidade']} unidades; a entrada de fardos aqui vai para as unidades. "
                                       f"A contagem se faz no '{emb['unitario']}'.")
            self._desenhar_barra()
            self.hist.insert("", "end", values=["", "Nenhum", "", ""])
            return
        if livre:
            self.d_info.configure(text="Este produto ainda não controla estoque. Toque em 'Contei e ajustar' (ou em Entrada) e "
                                       "informe quanto tem agora: o controle liga sozinho e ele passa a aparecer na lista.")
            self._desenhar_barra()
            self.hist.insert("", "end", values=["", "Nenhum", "", ""])
            return
        linhas = [f"Mínimo: {curta(p['estoque_minimo'])}" if p["estoque_minimo"] else "Mínimo: não definido",
                  f"Último preço de compra: {fmt.fmt_brl(p['ult_preco_cent'])}", f"Valor parado: {fmt.fmt_brl(p['valor_cent'])}"]
        if p["repor"]:
            linhas.append(f"Sugestão: comprar {curta(p['repor'])} {p['unidade']}")
        if p["ult_atualizacao"]:
            linhas.append(f"Última movimentação: {fmt.fmt_datahora(p['ult_atualizacao'])}")
        self.d_info.configure(text="\n".join(linhas))
        self._desenhar_barra()
        historico = self.est.historico(p["id"], 12)
        if not historico:
            self.hist.insert("", "end", values=["", "Nenhum", "", ""])
        for m in historico:
            self.hist.insert("", "end", tags=("mais" if m["quantidade"] > 0 else "menos",), values=[
                fmt.fmt_datahora(m["criado_em"])[:16], m["rotulo"], ("+" if m["quantidade"] > 0 else "") + curta(m["quantidade"]), curta(m["qt_apos"])])

    def _desenhar_barra(self) -> None:
        c = self.d_barra
        c.delete("all")
        w = max(c.winfo_width(), 10)
        c.create_rectangle(0, 2, w, 8, fill=PAL["borda"], outline="")
        p = self.produto
        if p is None or p["estoque_minimo"] <= 0:
            return
        teto = p["estoque_minimo"] * 2
        c.create_rectangle(0, 2, w * min(max(p["qt_atual"], 0) / teto, 1), 8, fill=SITUACAO[p["situacao"]][1], outline="")
        c.create_line(w / 2, 0, w / 2, 10, fill=PAL["texto"])       # marca do estoque mínimo

    # ------------------------------------------------------------- ações
    def registrar(self, tipo: str, quantidade: float, observacao: str | None = None) -> bool:
        """Grava o movimento rápido do produto selecionado e atualiza a tela."""
        if self.produto is None:
            return False
        ok, _ = tema.tratar(self, self.est.registrar_rapido, self.produto["id"], tipo, quantidade, observacao)
        if ok:
            self.atualizar()
        return ok

    def registrar_dialogo(self, tipo: str) -> None:
        if self.produto is None:
            return
        _, _, cor, titulo, pergunta = next(a for a in ACOES if a[0] == tipo)
        self._observacao_perda = None
        q = self._pedir_quantidade(titulo, pergunta, tipo)
        if q is not None:
            self.registrar(tipo, q, self._observacao_perda)

    def _pedir_quantidade(self, titulo: str, pergunta: str, tipo: str) -> float | None:
        """Diálogo com a quantidade e uma prévia de quanto o produto vai ficar (evita erro de digitação no estoque)."""
        p = self.produto
        dlg = tema.Dialogo(self, titulo)
        ttk.Label(dlg.corpo, text=p["nome"], font=tema.FONTE_G, foreground=tema.COR["titulo"]).pack(anchor="w")
        hoje = "Ainda não controla estoque (vai passar a controlar)" if p["situacao"] == "livre" else f"Hoje há {curta(p['qt_atual'])} {p['unidade']}"
        emb = self.est.produtos.embalagem(p["id"])
        if emb:                                  # a quantidade é de fardos; a prévia mostra as unidades, que é onde o estoque fica
            u = self.est.produtos.por_id(emb["unitario_id"])
            p = {**p, "qt_atual": u["qt_atual"], "unidade": emb["unidade"], "fator": emb["quantidade"]}
            hoje = f"Em fardos/caixas de {emb['quantidade']}. Hoje há {curta(u['qt_atual'])} {emb['unidade']} de '{u['nome']}'"
            pergunta = {"entrada": "Quantos fardos/caixas entraram?", "saida": "Quantos fardos/caixas saíram (sem ser venda)?",
                        "descarte": "Quantos fardos/caixas foram perdidos?"}.get(tipo, pergunta)
        ttk.Label(dlg.corpo, text=hoje, foreground=tema.COR["suave"]).pack(anchor="w", pady=(0, 10))
        ttk.Label(dlg.corpo, text=pergunta, style="Rotulo.TLabel").pack(anchor="w")
        v = tk.StringVar()
        ent = ttk.Entry(dlg.corpo, textvariable=v, width=18, font=("Segoe UI", 14))
        ent.pack(anchor="w", pady=(4, 0))
        observacao = tk.StringVar()
        if tipo in ("quebra", "oxidacao", "devolucao"):
            ttk.Label(dlg.corpo, text="Observação (opcional)", style="Rotulo.TLabel").pack(anchor="w", pady=(8, 0))
            ttk.Entry(dlg.corpo, textvariable=observacao, width=44).pack(anchor="w")
        previa = ttk.Label(dlg.corpo, text="", foreground=tema.COR["rotulo"], font=tema.FONTE_B)
        previa.pack(anchor="w", pady=(8, 0))
        msg = ttk.Label(dlg.corpo, text="", foreground=tema.COR["perigo"])
        msg.pack(anchor="w")

        def calcular():
            try:
                q = fmt.para_qtd(v.get())
            except ValueError:
                return None
            if q < 0 or (q == 0 and tipo != "contagem"):
                return None
            return q

        def atualizar_previa(*_):
            q = calcular()
            if q is None:
                previa.configure(text="")
                return
            q *= p.get("fator", 1)
            depois = p["qt_atual"] + q if tipo == "entrada" else q if tipo == "contagem" else p["qt_atual"] - q
            previa.configure(text=f"Vai ficar com {curta(depois)} {p['unidade']}")

        def aceitar(_=None):
            q = calcular()
            if q is None:
                msg.configure(text="Digite uma quantidade válida.")
                return
            self._observacao_perda = observacao.get().strip() or None
            dlg.ok(q)
        v.trace_add("write", atualizar_previa)
        tema._botoes(dlg, ok_texto="Confirmar", comando_ok=aceitar)
        dlg.bind("<Return>", aceitar)
        return dlg.mostrar(ent)

    def definir_minimo(self) -> None:
        p = self.produto
        if p is None:
            return
        r = tema.pedir_texto(self, "Estoque mínimo", f"Avisar quando '{p['nome']}' chegar a quantas unidades?",
                             curta(p["estoque_minimo"]) if p["estoque_minimo"] else "",
                             validar=lambda t: self._validar_minimo(t))
        if r is not None:
            self.est.definir_minimo(p["id"], r)
            self.atualizar()

    @staticmethod
    def _validar_minimo(texto: str) -> float:
        q = fmt.para_qtd(texto)
        if q < 0:
            raise ValueError("O mínimo não pode ser negativo.")
        return q

    def editar_cadastro(self) -> None:
        """Abre o cadastro de produtos já no produto selecionado (preço, nome, 'controla estoque', composição...)."""
        if self.produto is None:
            return
        from src.ui.cadastros_tk import JanelaCadastro
        j = JanelaCadastro(self, self.ctx, "produtos")
        j.carregar(self.produto["id"])
        j.bind("<Destroy>", lambda e, j=j: self.atualizar() if e.widget is j else None, add="+")

    # ---------------------------------------------- lançamentos e pedidos
    def novo_lancamento(self, lanc_id: int | None = None):
        from src.ui.lancamentos_ui import JanelaEstoque
        j = JanelaEstoque(self, self.ctx)
        if lanc_id is not None:
            j.carregar(lanc_id)
        j.bind("<Destroy>", lambda e, j=j: self.atualizar() if e.widget is j else None, add="+")
        return j

    def gerar_pedido(self) -> None:
        falta = [p for p in self.est.painel() if p["repor"] > 0]
        if not falta:
            tema.aviso(self, "Nenhum produto precisa de reposição agora.\n(Produtos sem estoque mínimo definido não entram na sugestão.)")
            return
        forn = self.ctx.cadastros.opcoes("fornecedores")
        if not forn:
            tema.aviso(self, "Cadastre um fornecedor primeiro (Manutenção de Cadastros > Fornecedores).")
            return
        fid = tema.escolher(self, "Gerar pedido", forn, f"{len(falta)} produto(s) serão incluídos. Para qual fornecedor é o pedido?")
        if fid is None:
            return
        ok, lanc = tema.tratar(self, self.est.pedido_sugerido, fid)
        if ok:
            self.atualizar()
            self.novo_lancamento(lanc)

    def lista_de_compras(self) -> None:
        itens = self.est.lista_de_compras()
        if not itens:
            tema.aviso(self, "Nenhum produto precisa de reposição agora.")
            return
        linhas = [f"LISTA DE COMPRAS - {fmt.fmt_data(fmt.hoje())}", "-" * 64,
                  f"{'Produto':<32}{'Tem':>9}{'Mínimo':>9}{'Comprar':>10}", "-" * 64]
        for p in itens:
            linhas.append(f"{p['nome'][:31]:<32}{curta(p['qt_atual']):>9}{curta(p['estoque_minimo']):>9}"
                          f"{curta(p['repor']):>10}")
        Visualizador(self, self.ctx, "Lista de compras", "\n".join(linhas), "lista_de_compras")
