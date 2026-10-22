"""Tema visual, componentes (Grade) e diálogos reutilizáveis da interface Tkinter."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from licenciador import paleta

COR = dict(paleta.COR[paleta.PADRAO])        # o conteúdo troca com o modo (claro/escuro): ver paleta.aplicar
FONTE = ("Segoe UI", 10)
FONTE_B = ("Segoe UI", 10, "bold")
FONTE_G = ("Segoe UI", 14, "bold")
FONTE_MONO = ("Consolas", 10)


def aplicar_tema(root: tk.Misc) -> None:
    """Estilos das telas de cadastro, relatórios e janelas, com as cores do modo em uso (claro ou escuro). Pode ser chamada de novo
    depois de trocar o modo: os widgets ttk já abertos mudam na hora."""
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    c = COR
    root.configure(bg=c["fundo"])
    s.configure(".", font=FONTE, background=c["fundo"], foreground=c["texto"], bordercolor=c["borda"],
                lightcolor=c["borda"], darkcolor=c["borda"], troughcolor=c["campo"], focuscolor=c["fundo"])
    s.configure("TFrame", background=c["fundo"])
    s.configure("Painel.TFrame", background=c["painel"], relief="solid", borderwidth=1)
    s.configure("TLabel", background=c["fundo"], foreground=c["texto"])
    s.configure("Painel.TLabel", background=c["painel"])
    s.configure("Rotulo.TLabel", font=("Segoe UI", 9, "bold"), foreground=c["rotulo"])
    s.configure("Titulo.TLabel", font=FONTE_G, foreground=c["titulo"])
    s.configure("TButton", padding=(10, 5), background=c["marinho2"], foreground=c["sobre"], borderwidth=0)
    s.map("TButton", background=[("active", c["btn_hover"]), ("disabled", c["btn_off"])],
          foreground=[("disabled", c["btn_off_texto"])])
    s.configure("Perigo.TButton", background=c["perigo_fundo"])
    s.map("Perigo.TButton", background=[("active", c["perigo_hover"])])
    s.configure("Ok.TButton", background=c["ok_fundo"])
    s.map("Ok.TButton", background=[("active", c["ok_hover"])])
    s.configure("Barra.TButton", padding=(8, 6), background=c["marinho"], foreground=c["sobre"], font=("Segoe UI", 9))
    s.map("Barra.TButton", background=[("active", c["marinho2"])])
    s.configure("Sel.TButton", background=c["aviso_fundo"], foreground="black")
    for campo in ("TEntry", "TCombobox", "TSpinbox"):
        s.configure(campo, padding=4, fieldbackground=c["campo"], foreground=c["texto"], insertcolor=c["texto"],
                    background=c["painel"], arrowcolor=c["texto"], bordercolor=c["borda"], lightcolor=c["borda"],
                    darkcolor=c["borda"])
        s.map(campo, fieldbackground=[("readonly", c["campo"]), ("disabled", c["fundo"])],
              foreground=[("disabled", c["suave"])], selectbackground=[("readonly", c["campo"])],
              selectforeground=[("readonly", c["texto"])], bordercolor=[("focus", c["marinho2"])])
    root.option_add("*TCombobox*Listbox.background", c["campo"])           # a lista que abre no combo
    root.option_add("*TCombobox*Listbox.foreground", c["texto"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["selecao"])
    root.option_add("*TCombobox*Listbox.selectForeground", c["selecao_texto"])
    root.option_add("*Menu.background", c["painel"])                       # menus de contexto
    root.option_add("*Menu.foreground", c["texto"])
    root.option_add("*Menu.activeBackground", c["selecao"])
    root.option_add("*Menu.activeForeground", c["selecao_texto"])
    s.configure("Treeview", rowheight=24, font=FONTE, background=c["campo"], fieldbackground=c["campo"], foreground=c["texto"],
                bordercolor=c["borda"])
    s.configure("Treeview.Heading", font=FONTE_B, background=c["marinho"], foreground=c["sobre"], padding=5)
    s.map("Treeview.Heading", background=[("active", c["marinho2"])])
    s.map("Treeview", background=[("selected", c["selecao"])], foreground=[("selected", c["selecao_texto"])])
    s.configure("TNotebook", background=c["fundo"], bordercolor=c["borda"])
    s.configure("TNotebook.Tab", padding=(12, 5), font=FONTE_B, background=c["painel"], foreground=c["suave"])
    s.map("TNotebook.Tab", background=[("selected", c["campo"]), ("active", c["selecao"])],
          foreground=[("selected", c["texto"]), ("active", c["selecao_texto"])])
    s.configure("TLabelframe", background=c["fundo"], bordercolor=c["borda"])
    s.configure("TLabelframe.Label", background=c["fundo"], font=FONTE_B, foreground=c["rotulo"])
    for nome in ("TCheckbutton", "TRadiobutton"):
        s.configure(nome, background=c["fundo"], foreground=c["texto"], indicatorbackground=c["campo"],
                    indicatorforeground=c["texto"], indicatorcolor=c["campo"])
        s.map(nome, background=[("active", c["fundo"])], indicatorcolor=[("selected", c["marinho2"])],
              foreground=[("disabled", c["suave"])])
    for eixo in ("Vertical", "Horizontal"):
        s.configure(f"{eixo}.TScrollbar", background=c["borda"], troughcolor=c["fundo"], bordercolor=c["fundo"],
                    arrowcolor=c["suave"], lightcolor=c["borda"], darkcolor=c["borda"])
        s.map(f"{eixo}.TScrollbar", background=[("active", c["suave"])])
    s.configure("TSeparator", background=c["borda"])
    s.configure("TProgressbar", background=c["marinho2"], troughcolor=c["campo"], bordercolor=c["borda"])
    s.configure("TMenubutton", background=c["painel"], foreground=c["texto"])
    s.configure("TPanedwindow", background=c["fundo"])


def centralizar(janela: tk.Toplevel, pai: tk.Misc | None = None) -> None:
    janela.update_idletasks()
    w, h = janela.winfo_reqwidth(), janela.winfo_reqheight()
    if pai is not None and pai.winfo_ismapped():
        x = pai.winfo_rootx() + (pai.winfo_width() - w) // 2
        y = pai.winfo_rooty() + (pai.winfo_height() - h) // 3
    else:
        x = (janela.winfo_screenwidth() - w) // 2
        y = (janela.winfo_screenheight() - h) // 3
    janela.geometry(f"+{max(x, 0)}+{max(y, 0)}")


def modalizar(janela: tk.Toplevel) -> None:
    """Torna a janela modal. `grab_set` falha se a janela ainda não estiver visível, então espera o mapeamento.

    Se a janela é `transient` de uma janela escondida ou minimizada, ela nunca ficaria visível e a espera travaria o
    caixa para sempre: nesse caso não espera nem prende o teclado (a janela abre normalmente, só não é modal)."""
    try:
        if not janela.winfo_viewable():
            mestre = janela.wm_transient()
            if mestre and not janela.nametowidget(str(mestre)).winfo_viewable():
                return
            janela.wait_visibility()
        janela.grab_set()
    except (tk.TclError, KeyError):
        pass


# ---------------------------------------------------------------- Grade
class Grade(ttk.Frame):
    """Treeview com barra de rolagem e linhas alternadas.

    `colunas`: lista de (id, título, largura_px, alinhamento['w'|'e'|'center']).
    `estilo`: prefixo de um conjunto de estilos próprio (ex.: "Cx" usa Cx.Treeview e Cx.Vertical.TScrollbar, do caixa escuro);
    `cor_par`: cor da listra das linhas pares nesse estilo."""

    def __init__(self, master, colunas, altura: int = 10, selectmode: str = "browse", estilo: str = "",
                 cor_par: str | None = None):
        super().__init__(master)
        self.colunas = colunas
        pre = f"{estilo}." if estilo else ""
        self.tree = ttk.Treeview(self, columns=[c[0] for c in colunas], show="headings", height=altura,
                                 selectmode=selectmode, style=f"{pre}Treeview")
        for cid, titulo, largura, anchor in colunas:
            self.tree.heading(cid, text=titulo, anchor=anchor if estilo else "center")
            self.tree.column(cid, width=largura, anchor=anchor, stretch=anchor == "w")
        barra = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview, style=f"{pre}Vertical.TScrollbar")
        horiz = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview, style=f"{pre}Horizontal.TScrollbar")
        self.tree.configure(yscrollcommand=barra.set, xscrollcommand=horiz.set)
        horiz.pack(side="bottom", fill="x")
        barra.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("par", background=cor_par or COR["linha_par"])
        self._n = 0

    def limpar(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._n = 0

    def adicionar(self, valores, iid: str | int | None = None, tags=()) -> str:
        tags = tuple(tags)
        if not tags and self._n % 2:      # listra só onde não há cor de situação (a listra venceria a cor)
            tags = ("par",)
        self._n += 1
        kw = {"iid": str(iid)} if iid is not None else {}
        return self.tree.insert("", "end", values=list(valores), tags=tags, **kw)

    def preencher(self, linhas, ids=None, tags=None) -> None:
        self.limpar()
        for i, ln in enumerate(linhas):
            self.adicionar(ln, ids[i] if ids else None, tags[i] if tags else ())

    def selecionado(self) -> str | None:
        s = self.tree.selection()
        return s[0] if s else None

    def selecionar(self, iid: str | int | None) -> None:
        if iid is None:
            return
        iid = str(iid)
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)

    def selecionar_indice(self, i: int) -> None:
        filhos = self.tree.get_children()
        if filhos:
            self.selecionar(filhos[max(0, min(i, len(filhos) - 1))])

    def indice(self) -> int:
        s = self.selecionado()
        return self.tree.get_children().index(s) if s else -1

    def valores(self, iid) -> list:
        return list(self.tree.item(str(iid), "values"))

    def tag(self, nome: str, **kw) -> None:
        self.tree.tag_configure(nome, **kw)

    def total(self) -> int:
        return len(self.tree.get_children())


# --------------------------------------------------------------- diálogos
class Dialogo(tk.Toplevel):
    def __init__(self, master, titulo: str):
        super().__init__(master)
        self.withdraw()
        self.title(titulo)
        self.configure(bg=COR["fundo"])
        self.resizable(False, False)
        self.resultado = None
        self._pai = master
        self.corpo = ttk.Frame(self, padding=14)
        self.corpo.pack(fill="both", expand=True)
        self.bind("<Escape>", lambda e: self.cancelar())
        self.protocol("WM_DELETE_WINDOW", self.cancelar)

    def ok(self, valor=True) -> None:
        self.resultado = valor
        self.destroy()

    def cancelar(self) -> None:
        self.resultado = None
        self.destroy()

    def mostrar(self, foco: tk.Misc | None = None):
        topo = self._pai.winfo_toplevel()
        try:
            if topo.winfo_viewable():      # transient de janela oculta também ficaria oculto
                self.transient(topo)
        except tk.TclError:
            pass
        centralizar(self, topo)
        self.deiconify()
        self.lift()
        modalizar(self)
        (foco or self).focus_force()   # modal: o teclado precisa cair aqui mesmo que o app esteja em segundo plano
        self.wait_window(self)
        return self.resultado


def _botoes(dlg: Dialogo, ok_texto="OK", cancelar_texto="Cancelar", estilo_ok="TButton", comando_ok=None):
    barra = ttk.Frame(dlg.corpo)
    barra.pack(fill="x", pady=(12, 0))
    b_ok = ttk.Button(barra, text=ok_texto, style=estilo_ok, command=comando_ok or dlg.ok)
    b_ok.pack(side="right")
    if cancelar_texto:
        ttk.Button(barra, text=cancelar_texto, command=dlg.cancelar).pack(side="right", padx=(0, 8))
    return b_ok


def mensagem(master, texto: str, titulo: str = "Aviso", tipo: str = "info") -> None:
    dlg = Dialogo(master, titulo)
    cor = {"info": COR["marinho2"], "erro": COR["perigo"], "aviso": COR["aviso"]}[tipo]
    ttk.Label(dlg.corpo, text=texto, wraplength=420, justify="left", foreground=cor if tipo == "erro" else COR["texto"],
              font=FONTE_B if tipo == "erro" else FONTE).pack(anchor="w")
    b = _botoes(dlg, "OK", None)
    dlg.bind("<Return>", lambda e: dlg.ok())
    dlg.mostrar(b)


def erro(master, texto: str, titulo: str = "Atenção") -> None:
    mensagem(master, texto, titulo, "erro")


def aviso(master, texto: str, titulo: str = "Aviso") -> None:
    mensagem(master, texto, titulo, "aviso")


def confirmar(master, texto: str, titulo: str = "Confirma", sim="Sim", nao="Não", padrao_sim: bool = True) -> bool:
    dlg = Dialogo(master, titulo)
    ttk.Label(dlg.corpo, text=texto, wraplength=420, justify="left").pack(anchor="w")
    barra = ttk.Frame(dlg.corpo)
    barra.pack(fill="x", pady=(14, 0))
    b_sim = ttk.Button(barra, text=f"{sim} (S)", command=lambda: dlg.ok(True))
    b_nao = ttk.Button(barra, text=f"{nao} (N)", command=lambda: dlg.ok(False))
    b_nao.pack(side="right")
    b_sim.pack(side="right", padx=(0, 8))
    dlg.bind("<s>", lambda e: dlg.ok(True)); dlg.bind("<S>", lambda e: dlg.ok(True))
    dlg.bind("<n>", lambda e: dlg.ok(False)); dlg.bind("<N>", lambda e: dlg.ok(False))
    foco = b_sim if padrao_sim else b_nao
    for b, v in ((b_sim, True), (b_nao, False)):
        b.bind("<Return>", lambda e, v=v: (dlg.ok(v), "break")[1])   # Enter no botão = a escolha do botão
    dlg.bind("<Return>", lambda e: dlg.ok(padrao_sim))
    dlg.cancelar = lambda: dlg.ok(False)   # Esc e fechar a janela = Não
    dlg.bind("<Escape>", lambda e: dlg.ok(False))
    dlg.protocol("WM_DELETE_WINDOW", lambda: dlg.ok(False))
    return bool(dlg.mostrar(foco))


def pedir_texto(master, titulo: str, rotulo: str, inicial: str = "", senha: bool = False, largura: int = 34,
                validar=None) -> str | None:
    dlg = Dialogo(master, titulo)
    ttk.Label(dlg.corpo, text=rotulo, style="Rotulo.TLabel").pack(anchor="w")
    var = tk.StringVar(value=inicial)
    ent = ttk.Entry(dlg.corpo, textvariable=var, width=largura, show="*" if senha else "")
    ent.pack(fill="x", pady=(4, 0))
    msg = ttk.Label(dlg.corpo, text="", foreground=COR["perigo"])
    msg.pack(anchor="w")

    def aceitar(_=None):
        v = var.get().strip()
        if validar:
            try:
                v = validar(v)
            except (ValueError, ErroNegocio) as e:
                msg.configure(text=str(e))
                return
        dlg.ok(v)
    _botoes(dlg, comando_ok=aceitar)
    dlg.bind("<Return>", aceitar)
    ent.selection_range(0, "end")
    return dlg.mostrar(ent)


def pedir_dinheiro(master, titulo: str, rotulo: str, inicial_cent: int | None = None, permitir_zero: bool = False) -> int | None:
    def validar(v):
        c = fmt.para_centavos(v)
        if c < 0 or (c == 0 and not permitir_zero):
            raise ValueError("Informe um valor maior que zero." if not permitir_zero else "Valor inválido.")
        return c
    r = pedir_texto(master, titulo, rotulo, fmt.fmt_num(inicial_cent) if inicial_cent is not None else "",
                    largura=18, validar=validar)
    return r


def pedir_numero(master, titulo: str, rotulo: str, inicial: int | str = "", minimo: int = 0, maximo: int | None = None) -> int | None:
    def validar(v):
        try:
            n = int(v)
        except ValueError:
            raise ValueError("Digite um número inteiro.") from None
        if n < minimo or (maximo is not None and n > maximo):
            raise ValueError(f"Use um número de {minimo}" + (f" a {maximo}." if maximo is not None else " em diante."))
        return n
    return pedir_texto(master, titulo, rotulo, str(inicial), largura=14, validar=validar)


def escolher(master, titulo: str, itens: list[tuple], rotulo: str = "Digite para filtrar", largura: int = 460,
             altura: int = 12, colunas: list[tuple] | None = None):
    """Lista com filtro por digitação. `itens` = [(valor, texto)] ou [(valor, (col1, col2...))] com `colunas`.
    Enter ou duplo clique escolhem; Esc cancela. Devolve o valor ou None."""
    dlg = Dialogo(master, titulo)
    ttk.Label(dlg.corpo, text=rotulo, style="Rotulo.TLabel").pack(anchor="w")
    var = tk.StringVar()
    ent = ttk.Entry(dlg.corpo, textvariable=var)
    ent.pack(fill="x", pady=(2, 8))
    cols = colunas or [("t", "", largura, "w")]
    grade = Grade(dlg.corpo, cols, altura=altura)
    grade.pack(fill="both", expand=True)

    def textos(texto):
        return texto if isinstance(texto, (tuple, list)) else (texto,)

    def montar(*_):
        filtro = var.get().strip().lower()
        grade.limpar()
        for i, (valor, texto) in enumerate(itens):
            if not filtro or filtro in " ".join(str(x) for x in textos(texto)).lower():
                grade.adicionar(textos(texto), iid=i)
        grade.selecionar_indice(0)

    def escolher_atual(_=None):
        s = grade.selecionado()
        if s is not None:
            dlg.ok(itens[int(s)][0])

    var.trace_add("write", montar)
    montar()
    ent.bind("<Down>", lambda e: (grade.selecionar_indice(grade.indice() + 1), "break")[1])
    ent.bind("<Up>", lambda e: (grade.selecionar_indice(grade.indice() - 1), "break")[1])
    grade.tree.bind("<Double-1>", escolher_atual)
    grade.tree.bind("<Return>", escolher_atual)
    dlg.bind("<Return>", escolher_atual)
    _botoes(dlg, "Escolher", comando_ok=escolher_atual)
    return dlg.mostrar(ent)


def pedir_senha_supervisor(master, ctx, modulo: str, motivo: str = ""):
    """Janela 'Digite uma Senha Válida'. Devolve o Operador autorizado ou None."""
    for tentativa in range(3):
        senha = pedir_texto(master, "Autorização", (motivo + "\n" if motivo else "") + "Digite uma senha válida:", senha=True,
                            largura=22)
        if senha is None:
            return None
        try:
            sup = ctx.acesso.validar_supervisor(senha, modulo)
        except ErroNegocio as e:          # bloqueada por senhas erradas demais
            erro(master, str(e))
            return None
        if sup is not None:
            return sup
        erro(master, "Senha inválida ou sem permissão para esta operação.")
    return None


def tratar(master, funcao, *args, **kwargs):
    """Executa `funcao` e mostra erros de negócio ao operador. Devolve (ok, resultado)."""
    try:
        return True, funcao(*args, **kwargs)
    except ErroNegocio as e:
        erro(master, str(e))
    except Exception as e:  # noqa: BLE001 - nunca deixar a tela morrer no caixa
        from src.core import registro
        import sys
        registro.registrar_excecao(*sys.exc_info(), origem=getattr(funcao, "__name__", "tratar"))
        erro(master, f"Erro inesperado: {e}\nO movimento já gravado foi preservado.", "Erro")
    return False, None
