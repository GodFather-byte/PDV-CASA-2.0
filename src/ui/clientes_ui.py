"""Sistema de Caderneta e de Entrega (manual do Caixa): escolher/incluir cliente, consultar
débitos e créditos e acompanhar as entregas pendentes."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.ui import tema
from src.ui.visualizador import Visualizador


class JanelaClientes(tk.Toplevel):
    """Modal. Ao fechar, `self.cliente_id` tem o cliente escolhido (ou None)."""

    def __init__(self, master, ctx, modo: str = "caderneta", modal: bool = True):
        super().__init__(master)
        self.ctx, self.modo, self.cliente_id = ctx, modo, None
        self.cad = ctx.caderneta
        self.title("Sistema de Caderneta" if modo == "caderneta" else "Sistema de Entrega")
        self.configure(bg=tema.COR["fundo"])
        self.geometry("980x620")
        faixa = tk.Frame(self, bg=tema.COR["marinho"], padx=12, pady=8)
        faixa.pack(fill="x")
        tk.Label(faixa, text=self.title(), bg=tema.COR["marinho"], fg="white", font=tema.FONTE_G).pack(side="left")
        self.abas = ttk.Notebook(self)
        self.abas.pack(fill="both", expand=True, padx=10, pady=10)
        self._aba_escolher()
        self._aba_incluir()
        if modo == "caderneta":
            self._aba_consultar()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<F2>", lambda e: self.abas.select(0))
        tema.centralizar(self, master.winfo_toplevel())
        self.transient(master.winfo_toplevel())
        self.ent_busca.focus_set()
        if modal:        # modal=False é para testes e telas que não devem bloquear
            tema.modalizar(self)
            self.wait_window(self)

    # ---------------------------------------------------------- escolher
    def _aba_escolher(self) -> None:
        f = ttk.Frame(self.abas, padding=10)
        self.abas.add(f, text="Escolher Cliente")
        ttk.Label(f, text="Digite o número ou o nome do cliente e tecle Enter", style="Rotulo.TLabel").pack(anchor="w")
        self.var_busca = tk.StringVar()
        self.ent_busca = ttk.Entry(f, textvariable=self.var_busca, width=50)
        self.ent_busca.pack(anchor="w", pady=(2, 8))
        self.grade = tema.Grade(f, [("num", "Número", 90, "w"), ("nome", "Cliente", 260, "w"), ("tel", "Telefone", 110, "w"),
                                    ("bairro", "Bairro", 130, "w"), ("saldo", "Saldo", 90, "e"), ("lim", "Limite", 90, "e")], altura=8)
        self.grade.pack(fill="x")
        ttk.Label(f, text="Últimas compras do cliente", style="Rotulo.TLabel").pack(anchor="w", pady=(10, 0))
        self.grade_compras = tema.Grade(f, [("cup", "Cupom", 70, "w"), ("data", "Data", 90, "w"), ("prod", "Produto", 300, "w"),
                                            ("qt", "Quant", 70, "e"), ("tot", "Total", 90, "e")], altura=6)
        self.grade_compras.pack(fill="both", expand=True)
        self.ent_busca.bind("<Return>", self._buscar)
        self.ent_busca.bind("<Down>", lambda e: (self.grade.tree.focus_set(), self.grade.selecionar_indice(0), "break")[2])
        self.grade.tree.bind("<Return>", self._escolher)
        self.grade.tree.bind("<Double-1>", self._escolher)
        self.grade.tree.bind("<<TreeviewSelect>>", self._mostrar_compras)
        self._buscar()

    def _buscar(self, _=None) -> None:
        t = self.var_busca.get().strip()
        clientes = self.cad.buscar(t) if t else [dict(r) for r in self.ctx.banco.todos(
            "SELECT c.*, b.nome AS bairro FROM clientes c LEFT JOIN bairros b ON b.id = c.bairro_id WHERE c.ativo = 1 ORDER BY c.nome LIMIT 200")]
        self.grade.preencher([[c["numero_consulta"], c["nome"], c["telefone"] or "", c["bairro"] or "", fmt.fmt_num(c["saldo_cent"]),
                               fmt.fmt_num(c["limite_cent"])] for c in clientes], [c["id"] for c in clientes])
        if len(clientes) == 1 and t:
            self.grade.selecionar_indice(0)
            self.grade.tree.focus_set()
        elif clientes:
            self.grade.selecionar_indice(0)

    def _mostrar_compras(self, _=None) -> None:
        s = self.grade.selecionado()
        self.grade_compras.limpar()
        if s is not None:
            for c in self.cad.ultimas_compras(int(s)):
                self.grade_compras.adicionar([c["cupom"], fmt.fmt_data(c["data"]), c["nome"], fmt.fmt_qtd(c["quantidade"]), fmt.fmt_num(c["total_cent"])])

    def _escolher(self, _=None) -> str:
        s = self.grade.selecionado()
        if s is None:
            return "break"
        c = self.cad.obter(int(s))
        if tema.confirmar(self, f"Confirma a escolha?\n\n{c['numero_consulta']} - {c['nome']}\nSaldo {fmt.fmt_brl(c['saldo_cent'])}", "Confirm"):
            self.cliente_id = int(s)
            self.destroy()
        return "break"

    # ----------------------------------------------------------- incluir
    def _aba_incluir(self) -> None:
        f = ttk.Frame(self.abas, padding=14)
        self.abas.add(f, text="Incluir Cliente")
        self.campos: dict[str, tk.StringVar] = {}
        bairros = self.ctx.cadastros.opcoes("bairros")
        self.mapa_bairros = {r: i for i, r in bairros}
        defs = [("numero_consulta", "Número para consulta *", 14), ("nome", "Nome do cliente *", 40), ("telefone", "Telefone", 16),
                ("endereco", "Endereço", 40), ("complemento", "Complemento", 20), ("cep", "CEP", 12), ("bairro", "Bairro", 24),
                ("cidade", "Cidade", 24), ("rg", "RG", 16), ("cpf", "CPF", 16), ("limite_cent", "Limite (caderneta, 0 = sem limite)", 14),
                ("obs", "Observações", 40)]
        for i, (nome, rotulo, larg) in enumerate(defs):
            q = ttk.Frame(f)
            q.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 16), pady=(0, 8))
            ttk.Label(q, text=rotulo, style="Rotulo.TLabel").pack(anchor="w")
            var = tk.StringVar()
            self.campos[nome] = var
            if nome == "bairro":
                ttk.Combobox(q, textvariable=var, values=[""] + [r for _, r in bairros], state="readonly", width=larg).pack(anchor="w")
            else:
                ttk.Entry(q, textvariable=var, width=larg).pack(anchor="w")
        self.campos["numero_consulta"].set(self.ctx.cadastros.valores_iniciais("clientes")["numero_consulta"])
        barra = ttk.Frame(f)
        barra.grid(row=5, column=0, columnspan=3, sticky="w", pady=10)
        ttk.Button(barra, text="Gravar e escolher este cliente", style="Ok.TButton", command=self._gravar).pack(side="left")
        ttk.Button(barra, text="Bairros e taxas...", command=self._bairros).pack(side="left", padx=8)

    def _bairros(self) -> None:
        from src.ui.cadastros_tk import JanelaCadastro
        j = JanelaCadastro(self, self.ctx, "bairros")
        self.wait_window(j)

    def _gravar(self) -> None:
        valores = {n: v.get() for n, v in self.campos.items() if n != "bairro"}
        b = self.campos["bairro"].get()
        if b:
            valores["bairro_id"] = str(self.mapa_bairros.get(b, ""))
        ok, cid = tema.tratar(self, self.ctx.cadastros.salvar, "clientes", valores)
        if ok:
            self.cliente_id = cid
            self.destroy()

    # --------------------------------------------------------- consultar
    def _aba_consultar(self) -> None:
        f = ttk.Frame(self.abas, padding=10)
        self.abas.add(f, text="Consultar")
        topo = ttk.Frame(f)
        topo.pack(fill="x")
        self.var_devedores = tk.BooleanVar()
        ttk.Checkbutton(topo, text="Somente os devedores", variable=self.var_devedores, command=self._lista_consulta).pack(side="left")
        ttk.Button(topo, text="Imprimir extrato", command=self._imprimir_extrato).pack(side="right")
        meio = ttk.Frame(f)
        meio.pack(fill="both", expand=True, pady=8)
        self.grade_cons = tema.Grade(meio, [("num", "Número", 80, "w"), ("nome", "Cliente", 220, "w"), ("saldo", "Saldo", 90, "e")], altura=12)
        self.grade_cons.pack(side="left", fill="y")
        dir_ = ttk.Frame(meio)
        dir_.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.lbl_cons = ttk.Label(dir_, text="", font=tema.FONTE_B)
        self.lbl_cons.pack(anchor="w")
        self.grade_lan = tema.Grade(dir_, [("data", "Data", 90, "w"), ("cup", "Cupom", 60, "w"), ("tipo", "Tipo", 70, "w"),
                                           ("valor", "Valor", 90, "e"), ("desc", "Descrição", 200, "w")], altura=7)
        self.grade_lan.pack(fill="x")
        ttk.Label(dir_, text="Produtos / pagamento do lançamento selecionado", style="Rotulo.TLabel").pack(anchor="w", pady=(8, 0))
        self.grade_det = tema.Grade(dir_, [("nome", "Descrição", 260, "w"), ("qt", "Quant", 70, "e"), ("val", "Valor", 90, "e")], altura=6)
        self.grade_det.pack(fill="both", expand=True)
        self.grade_lan.tag("debito", foreground=tema.COR["perigo"])
        self.grade_lan.tag("credito", foreground=tema.COR["ok"])
        self.grade_cons.tree.bind("<<TreeviewSelect>>", self._consulta_cliente)
        self.grade_lan.tree.bind("<<TreeviewSelect>>", self._consulta_detalhe)
        self._lista_consulta()

    def _lista_consulta(self) -> None:
        if self.var_devedores.get():
            cs = self.cad.devedores()
        else:
            cs = [dict(r) for r in self.ctx.banco.todos("SELECT * FROM clientes WHERE ativo = 1 ORDER BY nome")]
        self.grade_cons.preencher([[c["numero_consulta"], c["nome"], fmt.fmt_num(c["saldo_cent"])] for c in cs], [c["id"] for c in cs])
        self.grade_cons.selecionar_indice(0)

    def _consulta_cliente(self, _=None) -> None:
        s = self.grade_cons.selecionado()
        self.grade_lan.limpar()
        self.grade_det.limpar()
        if s is None:
            return
        c = self.cad.obter(int(s))
        self.lbl_cons.configure(text=f"{c['nome']}   |   Limite {fmt.fmt_brl(c['limite_cent'])}   |   Saldo {fmt.fmt_brl(c['saldo_cent'])}")
        for l in self.cad.lancamentos(int(s)):
            self.grade_lan.adicionar([fmt.fmt_data(l["criado_em"][:10]), l["cupom"] or "", "Débito" if l["tipo"] == "debito" else "Crédito",
                                      fmt.fmt_num(l["valor_cent"]), l["descricao"] or ""], iid=l["id"], tags=(l["tipo"],))

    def _consulta_detalhe(self, _=None) -> None:
        self.grade_det.limpar()
        s = self.grade_lan.selecionado()
        if s is None:
            return
        venda = self.ctx.banco.valor("SELECT venda_id FROM caderneta WHERE id = ?", (int(s),))
        if not venda:
            return
        for p in self.cad.produtos_da_venda(venda):
            self.grade_det.adicionar([p["nome"], fmt.fmt_qtd(p["quantidade"]), fmt.fmt_num(p["total_cent"])])
        for p in self.cad.pagamentos_da_venda(venda):
            self.grade_det.adicionar([f"Pagamento em {p['tipo']}", "", fmt.fmt_num(p["valor_cent"])])

    def _imprimir_extrato(self) -> None:
        s = self.grade_cons.selecionado()
        if s is not None:
            Visualizador(self, self.ctx, "Extrato da caderneta", self.cad.texto_extrato(int(s), self.ctx.impressao.largura()), "caderneta")


class JanelaEntregas(tk.Toplevel):
    """Entregas pendentes. Tecla E escolhe o entregador; Enter leva o pedido ao caixa para receber."""

    def __init__(self, master, ctx, modal: bool = True):
        super().__init__(master)
        self.ctx, self.venda_id = ctx, None
        self.title("Entregas pendentes")
        self.configure(bg=tema.COR["fundo"])
        self.geometry("1020x460")
        corpo = ttk.Frame(self, padding=10)
        corpo.pack(fill="both", expand=True)
        self.grade = tema.Grade(corpo, [("ped", "Pedido", 70, "w"), ("hora", "Hora", 60, "w"), ("cli", "Cliente", 170, "w"),
                                        ("end", "Endereço", 220, "w"), ("bai", "Bairro", 110, "w"), ("tp", "T.Pedido", 70, "e"),
                                        ("te", "T.Entrega", 70, "e"), ("ent", "Entregador", 110, "w"), ("tot", "Total", 80, "e")], altura=12)
        self.grade.pack(fill="both", expand=True)
        self.grade.tag("atrasada", foreground=tema.COR["perigo"])
        ttk.Label(corpo, text="E = escolher entregador   |   Enter = receber o pagamento   |   Delete = cancelar pedido   |   Esc = fechar",
                  foreground=tema.COR["suave"]).pack(anchor="w", pady=(8, 0))
        t = self.grade.tree
        t.bind("<Return>", self._receber)
        t.bind("<Double-1>", self._receber)
        t.bind("e", self._entregador)
        t.bind("E", self._entregador)
        t.bind("<Delete>", self._cancelar)
        self.bind("<Escape>", lambda e: self.destroy())
        self.carregar()
        tema.centralizar(self, master.winfo_toplevel())
        self.transient(master.winfo_toplevel())
        t.focus_set()
        if modal:
            tema.modalizar(self)
            self.wait_window(self)

    def carregar(self, manter: str | None = None) -> None:
        pend = self.ctx.entregas.pendentes()
        self.grade.preencher([[e["posicao"], e["hora_pedido"], e["cliente"], e["endereco"] or "", e["bairro"] or "", e["t_pedido"],
                               e["t_entrega"] or "", e["entregador"] or "", fmt.fmt_num(e["total_cent"])] for e in pend],
                             [e["id"] for e in pend], [("atrasada",) if e["t_pedido"] >= 60 else () for e in pend])
        self.grade.selecionar(manter) if manter else self.grade.selecionar_indice(0)

    def _entregador(self, _=None) -> str:
        s = self.grade.selecionado()
        if s is None:
            return "break"
        ents = [(r["id"], r["nome"]) for r in self.ctx.cadastros.listar("operadores", apenas_ativos=True) if r["entregador"]]
        if not ents:
            tema.aviso(self, "Nenhum entregador cadastrado. Marque 'É entregador' no cadastro de operadores.")
            return "break"
        ent = tema.escolher(self, "Entregador", ents, "Quem leva este pedido?")
        if ent is not None:
            ok, _ = tema.tratar(self, self.ctx.entregas.atribuir_entregador, int(s), ent)
            if ok:
                self.carregar(s)
        return "break"

    def _receber(self, _=None) -> str:
        s = self.grade.selecionado()
        if s is not None:
            self.venda_id = int(s)
            self.destroy()
        return "break"

    def _cancelar(self, _=None) -> None:
        s = self.grade.selecionado()
        if s is not None and tema.confirmar(self, "Cancelar este pedido de entrega?", "Cancelar", padrao_sim=False):
            ok, _ = tema.tratar(self, self.ctx.caixa.cancelar_venda, int(s), "pedido de entrega cancelado")
            if ok:
                self.carregar()
