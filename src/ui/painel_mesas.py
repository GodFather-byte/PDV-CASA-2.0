"""Painel de mesas e comandas do caixa: a coluna de cartões à esquerda da tela.

Esc (ou F4) leva ao "marcar comanda": o foco vai para o campo da posição e o painel fica à vista. Cada posição aberta é um
cartão com o tipo (comanda, mesa ou garota), o número em destaque, uma linha de identificação (nome da comanda,
pessoas na mesa, itens ou drinks marcados da garota), a situação em uma pílula colorida e o total. O balcão é a primeira
posição, mas aparece como uma faixa fina acima dos cartões, para não ocupar o lugar de uma comanda. A garota com comissão a pagar ganha o próprio cartão (ou um selo na comanda dela, se tem consumo aberto): a
comissão fica à vista na mesma tela do balcão. A busca e as abas (Todas, Abertas, Pago em parte, Aguardando acerto,
Comissões) só controlam o que aparece; não fecham, cancelam nem transferem nada. Tudo é desenhado com formas do Tk.
"""
from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Callable

from src.core import formatacao as fmt
from src.ui import paleta, tema
from src.ui.caixa_tema import CX, FONTE
from src.ui.menu_widgets import misturar

LARGURA, ALTURA, MARGEM = 184, 126, 8   # a célula de cada cartão (com o espaçamento)
ALTURA_FAIXA = 52                       # a célula da faixa do balcão, que ocupa a largura toda acima dos cartões
RESERVA_BARRA = 14                      # espaço da barra de rolagem (sobreposta), reservado sempre para a disposição não oscilar
LARGURA_PADRAO = 640                    # antes de a janela ser mostrada o Tk ainda não sabe a largura real
COLUNAS_PADRAO = 3

ESTADOS = {k: dict(v) for k, v in paleta.ESTADOS[paleta.PADRAO].items()}     # troca com o modo (claro/escuro): ver paleta.aplicar
ROTULOS_ESTADO = {"consumindo": "Aberta", "parada": "Sem movimento", "conta": "Aguard. acerto",
                  "balcao": "Venda de balcão", "garota": "Acerto pendente", "parcial": "Pago em parte",
                  "acerto": "Concluir acerto"}
ROTULOS_PILULA = {"consumindo": "Aberta", "parada": "Parada", "conta": "Acerto", "balcao": "Balcão",
                  "garota": "Comissão", "parcial": "Parcial", "acerto": "Concluir"}
ROTULOS_TIPO = {"balcao": "BALCÃO", "comanda": "COMANDA", "mesa": "MESA", "garota": "GAROTA"}
ABAS = (("Todas", "Todas"), ("Abertas", "Abertas"), ("Pago em parte", "Parciais"),
        ("Aguardando acerto", "Acerto"), ("Comissões", "Comissões"))      # (valor do filtro, rótulo curto da tela estreita)


def montar_tiles(mesas: list[dict], balcao: dict | None = None, garotas=()) -> list[dict]:
    """Modelo dos cartões, sem Tk: o balcão primeiro, depois as mesas e comandas (na ordem recebida) e, por fim, as garotas
    com comissão a pagar.

    `mesas` é o que `CaixaController.mesas()` devolve; `balcao`, a venda de balcão em andamento (ou None); `garotas`, uma
    lista de {'rotulo': a comanda da garota na notação da loja, 'total_cent': o que há a pagar a ela} (e, se houver, 'nome' e
    'marcacoes'). A garota que também tem consumo aberto na comanda não ganha um cartão à parte: o cartão da comanda leva o
    selo `garota` (o total a pagar). Se a comanda dela está aberta mas vazia (o operador só foi ver ou marcar a comissão), o
    cartão é o da garota, como seria fora dela. As chaves de identificação (`nome`, `pessoas`, `itens`, `marcacoes`) só
    existem quando há o que mostrar."""
    tiles = [{"chave": "0", "rotulo": "Balcão", "tipo": "balcao", "estado": "balcao",
              "total": fmt.fmt_num(balcao["total_cent"]) if balcao and balcao["total_cent"] else "", "minutos": 0}]
    a_pagar = {g["rotulo"]: g for g in garotas}
    for m in mesas:
        recebido = m.get("recebido_cent", 0)
        if recebido > 0 and recebido < m["total_cent"]:
            estado = "parcial"
        elif recebido > 0 and recebido >= m["total_cent"]:
            estado = "acerto"
        elif m["status"] == "conta_enviada":
            estado = "conta"
        elif m["inativa"]:
            estado = "parada"
        else:
            estado = "consumindo"
        tile = {"chave": m["rotulo"], "rotulo": m["rotulo"], "tipo": "comanda" if m["comanda"] else "mesa",
                "estado": estado, "total": fmt.fmt_num(m["total_cent"]), "minutos": m["minutos_parada"]}
        if recebido > 0:
            tile["falta"] = fmt.fmt_num(max(0, m["total_cent"] - recebido))
        g = a_pagar.pop(m["rotulo"], None) if m["comanda"] else None
        if g is not None and m.get("n_itens", 1) == 0:
            tile.update(tipo="garota", estado="garota", total=fmt.fmt_num(g["total_cent"]), minutos=0)
            _identificar_garota(tile, g)
        else:
            if g is not None:
                tile["garota"] = fmt.fmt_num(g["total_cent"])
            for chave, valor in (("nome", (m.get("apelido") or m.get("cliente_nome") or "").strip()),
                                 ("pessoas", m.get("pessoas") or 0), ("itens", m.get("n_itens") or 0)):
                if valor:
                    tile[chave] = valor
        tiles.append(tile)
    for g in a_pagar.values():
        tile = {"chave": g["rotulo"], "rotulo": g["rotulo"], "tipo": "garota", "estado": "garota",
                "total": fmt.fmt_num(g["total_cent"]), "minutos": 0}
        _identificar_garota(tile, g)
        tiles.append(tile)
    return tiles


def _identificar_garota(tile: dict, g: dict) -> None:
    if g.get("nome"):
        tile["nome"] = g["nome"]
    if g.get("marcacoes"):
        tile["marcacoes"] = g["marcacoes"]


def idade(minutos: int) -> str:
    """'42 min' ou '1h52': há quanto tempo a posição está aberta sem lançamento."""
    if minutos < 1:
        return "agora"
    return f"{minutos} min" if minutos < 60 else f"{minutos // 60}h{minutos % 60:02d}"


# ------------------------------------------------------------------ desenho
def _cartao(c: tk.Canvas, x1, y1, x2, y2, raio: int = 8, **kw) -> int:
    pontos = [x1 + raio, y1, x2 - raio, y1, x2, y1, x2, y1 + raio, x2, y2 - raio, x2, y2,
              x2 - raio, y2, x1 + raio, y2, x1, y2, x1, y2 - raio, x1, y1 + raio, x1, y1]
    return c.create_polygon(pontos, smooth=True, **kw)


def _estrela(cx: float, cy: float, externo: float, interno: float) -> list[float]:
    pontos = []
    for i in range(10):
        raio = externo if i % 2 == 0 else interno
        angulo = math.radians(-90 + i * 36)
        pontos += [cx + raio * math.cos(angulo), cy + raio * math.sin(angulo)]
    return pontos


def _relogio(c: tk.Canvas, cx: int, cy: int, tags: tuple) -> None:
    cor = tema.COR["perigo"]
    c.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, fill="#ffffff", outline=cor, width=2, tags=tags)
    c.create_line(cx, cy, cx, cy - 4, fill=cor, width=2, tags=tags)
    c.create_line(cx, cy, cx + 3, cy, fill=cor, width=2, tags=tags)


def _selo_garota(c: tk.Canvas, cx: int, cy: int, tags: tuple) -> None:
    """Selo no canto do cartão da comanda: a garota dela tem comissão a pagar."""
    c.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill="#0b7a6b", outline="#075247", tags=tags)
    c.create_polygon(_estrela(cx, cy + 0.3, 6.2, 2.7), fill="#ffd84d", outline="", tags=tags)


class PainelMesas(ttk.Frame):
    """Os cartões, a busca, as abas, a navegação por teclado (setas, Enter, T, digitar o número) e o clique do mouse.

    Quem usa só informa o que fazer ao escolher um cartão (`ao_escolher`), ao pedir para transferir outras posições
    para ele (`ao_transferir`), ao voltar para o campo da posição (`ao_voltar`) e ao digitar um número ou a letra C
    com o foco no painel (`ao_digitar`, que passa o caractere ao campo da posição). `colunas` é quantos cartões cabem por
    linha (3 na tela larga, 2 no notebook, 1 na tela pequena)."""

    LARGURA_CARTAO = LARGURA              # para quem dimensiona a janela: a largura de cada coluna de cartões
    RESERVA = RESERVA_BARRA + 4           # e o que sobra para a barra de rolagem e a margem

    def __init__(self, master, ao_escolher: Callable[[str], None], ao_transferir: Callable[[str], None],
                 ao_voltar: Callable[[], None], ao_digitar: Callable[[str], None], colunas: int = COLUNAS_PADRAO,
                 com_comissoes: bool = True):
        super().__init__(master, style="Cx.TFrame")
        self._lista_abas = tuple(a for a in ABAS if com_comissoes or a[0] != "Comissões")   # casa sem garotas: sem a aba
        self._ao_escolher, self._ao_transferir = ao_escolher, ao_transferir
        self._ao_voltar, self._ao_digitar = ao_voltar, ao_digitar
        self.colunas = colunas
        self._tiles: list[dict] = []
        self._todos_tiles: list[dict] = []
        self._atual: str | None = None        # a posição que está na tela do caixa (borda grossa)
        self._cursor: str | None = None       # onde o teclado está (pontilhado, só com o foco no painel)
        self._com_foco = False
        self._assinatura = None
        self._largura = 0
        self._altura = 0
        self._altura_total = 0
        self._por_linha = max(1, colunas)
        self._id_redesenho = None
        self._f_pilula = tkfont.Font(self, font=(FONTE, 8, "bold"))
        self.configure(width=colunas * LARGURA + RESERVA_BARRA + 4)
        self.pack_propagate(False)

        self.topo = tk.Frame(self, bg=CX["fundo"])
        self.topo.pack(fill="x")
        self.titulos = tk.Frame(self.topo, bg=CX["fundo"])
        tk.Label(self.titulos, text="Mesas e comandas", bg=CX["fundo"], fg=CX["texto"], font=(FONTE, 15, "bold")).pack(anchor="w")
        tk.Label(self.titulos, text="Esc ou F4 busca  ·  clique ou digite o número + Enter", bg=CX["fundo"], fg=CX["suave"],
                 font=(FONTE, 9)).pack(anchor="w", pady=(2, 0))
        self.var_busca = tk.StringVar(self)
        self.busca = tk.Frame(self.topo, bg=CX["fundo"])
        self.ent_busca = ttk.Entry(self.busca, textvariable=self.var_busca, width=24, font=(FONTE, 11), style="Cx.TEntry")
        self.ent_busca.pack(fill="x")
        self.dica_busca = tk.Label(self.ent_busca, text="Buscar nº (ex.: 12 ou M5)", bg=CX["campo"], fg=CX["mudo"], font=(FONTE, 11))
        self.dica_busca.place(x=8, rely=0.5, anchor="w")
        self.topo.columnconfigure(0, weight=1)

        self.var_estado = tk.StringVar(self, value="Todas")
        self.faixa = tk.Frame(self, bg=CX["fundo"])
        self.faixa.pack(fill="x", pady=(10, 8))
        self._abas: dict[str, tk.Label] = {}
        for valor, curto in self._lista_abas:
            aba = tk.Label(self.faixa, text=valor, bg=CX["cartao"], fg=CX["texto"], font=(FONTE, 10, "bold"), padx=12, pady=6,
                           cursor="hand2")
            aba.bind("<Button-1>", lambda e, v=valor: self.var_estado.set(v))
            aba.bind("<Enter>", lambda e, v=valor: self._pintar_abas(passando=v))
            aba.bind("<Leave>", lambda e: self._pintar_abas())
            self._abas[valor] = aba

        self.lbl_resumo = ttk.Label(self, text="", font=(FONTE, 9), style="Cx.TLabel", foreground=CX["suave"])
        self.lbl_resumo.pack(side="bottom", anchor="w", pady=(6, 0))
        c = self.canvas = tk.Canvas(self, bg=CX["fundo"], bd=0, takefocus=True, highlightthickness=1,
                                    highlightbackground=CX["fundo"], highlightcolor=CX["azul"], yscrollincrement=ALTURA)
        c.pack(fill="both", expand=True)
        self.barra = ttk.Scrollbar(c, orient="vertical", command=c.yview, style="Cx.Vertical.TScrollbar")    # sobreposta ao canvas (place)
        c.configure(yscrollcommand=self.barra.set)
        c.bind("<Configure>", self._ao_configurar)
        c.bind("<MouseWheel>", self._roda)
        c.bind("<Button-4>", lambda e: c.yview_scroll(-1, "units"))
        c.bind("<Button-5>", lambda e: c.yview_scroll(1, "units"))
        c.bind("<FocusIn>", lambda ev: self._foco(True))
        c.bind("<FocusOut>", lambda ev: self._foco(False))
        c.bind("<Key>", self._tecla)
        c.bind("<Button-1>", self._clique_fundo)
        c.tag_bind("tile", "<Button-1>", self._clique)
        c.tag_bind("tile", "<Enter>", lambda ev: c.configure(cursor="hand2"))
        c.tag_bind("tile", "<Leave>", lambda ev: c.configure(cursor=""))
        self.var_busca.trace_add("write", lambda *_: self._filtrar(reiniciar=True))
        self.var_estado.trace_add("write", lambda *_: self._filtrar(reiniciar=True))
        self.ent_busca.bind("<Return>", lambda e: (self.focar(), "break")[1])
        self.ent_busca.bind("<Escape>", lambda e: (self.var_busca.set(""), self._ao_voltar(), "break")[2])
        self.ent_busca.bind("<FocusIn>", lambda e: self._pintar_dica())
        self.ent_busca.bind("<FocusOut>", lambda e: self._pintar_dica())
        self.dica_busca.bind("<Button-1>", lambda e: self.ent_busca.focus_set())
        self._largura_painel = 0
        self.bind("<Configure>", self._ao_dimensionar)
        self._dispor(self.winfo_reqwidth())
        self._pintar_abas()

    # -------------------------------------------------------------- disposição responsiva
    def definir_colunas(self, colunas: int) -> None:
        """Muda a largura do painel para `colunas` cartões por linha (a janela do caixa chama ao ser redimensionada)."""
        colunas = max(1, colunas)
        if colunas != self.colunas:
            self.colunas = colunas
            self.configure(width=colunas * LARGURA + RESERVA_BARRA + 4)

    def _ao_dimensionar(self, ev) -> None:
        if ev.widget is self and ev.width != self._largura_painel:
            self._dispor(ev.width)

    def _dispor(self, largura: int) -> None:
        """Reorganiza o cabeçalho e as abas conforme a largura: o título e a busca dividem a linha só se couberem, e as abas
        quebram de linha (com o texto curto quando a largura é pequena)."""
        self._largura_painel = largura
        for filho in (self.titulos, self.busca):
            filho.grid_forget()
        if largura >= 560:
            self.titulos.grid(row=0, column=0, sticky="w")
            self.busca.grid(row=0, column=1, sticky="ne", pady=(2, 0))
        else:
            self.titulos.grid(row=0, column=0, columnspan=2, sticky="w")
            self.busca.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        longas = largura >= 600
        x, linha, coluna = 0, 0, 0
        for valor, curto in self._lista_abas:
            aba = self._abas[valor]
            aba.grid_forget()
            aba.configure(text=valor if longas else curto, padx=12 if longas else 8, font=(FONTE, 10 if longas else 9, "bold"))
            aba.update_idletasks()
            largura_aba = aba.winfo_reqwidth() + 6
            if coluna and x + largura_aba > largura - 4:
                linha, coluna, x = linha + 1, 0, 0
            aba.grid(row=linha, column=coluna, padx=(0, 6), pady=(0, 6) if linha else 0, sticky="w")
            x, coluna = x + largura_aba, coluna + 1

    # -------------------------------------------------------------- abas e busca
    def _pintar_abas(self, passando: str | None = None) -> None:
        ativa = self.var_estado.get()
        for valor, aba in self._abas.items():
            if valor == ativa:
                aba.configure(bg=CX["azul"], fg=CX["sobre_marca"])
            else:
                aba.configure(bg=CX["cartao2"] if valor == passando else CX["cartao"], fg=CX["texto"])

    def _pintar_dica(self) -> None:
        """O texto-guia da busca só aparece com o campo vazio e sem o foco."""
        vazio = not self.var_busca.get() and self.focus_get() is not self.ent_busca
        if vazio:
            self.dica_busca.place(x=8, rely=0.5, anchor="w")
        else:
            self.dica_busca.place_forget()

    # -------------------------------------------------------------- dados
    def atualizar(self, mesas: list[dict], balcao: dict | None = None, atual: str | None = None, garotas=()) -> None:
        tiles = montar_tiles(mesas, balcao, garotas)
        assinatura = ([(t["chave"], t["tipo"], t["estado"], t["total"], t.get("garota"), t.get("falta"),
                        t["minutos"], t.get("nome"), t.get("pessoas"), t.get("itens"), t.get("marcacoes")) for t in tiles], atual)
        if assinatura == self._assinatura:
            return
        self._assinatura = assinatura
        self._todos_tiles, self._atual = tiles, atual
        if self._cursor not in {t["chave"] for t in tiles}:
            self._cursor = atual
        self._filtrar()

    def _filtrar(self, reiniciar: bool = False) -> None:
        busca = self.var_busca.get().strip().lower()
        grupos = {"Abertas": {"consumindo", "parada"}, "Pago em parte": {"parcial"},
                  "Aguardando acerto": {"conta", "acerto", "garota"}, "Comissões": {"garota"}}
        estados = grupos.get(self.var_estado.get())
        self._tiles = [t for t in self._todos_tiles
                       if (not busca or busca in t["rotulo"].lower() or busca in (t.get("nome") or "").lower())
                       and (estados is None or t["estado"] in estados or
                            self.var_estado.get() == "Comissões" and t.get("garota"))]
        if self._cursor not in {t["chave"] for t in self._tiles}:
            self._cursor = None
        parciais = sum(t["estado"] == "parcial" for t in self._todos_tiles)
        acertos = sum(t["estado"] in {"conta", "acerto", "garota"} for t in self._todos_tiles)
        self.lbl_resumo.configure(text=f"Posições: {len(self._todos_tiles) - 1}  |  Parciais: {parciais}  |  Acertos: {acertos}")
        self._pintar_abas()
        self._pintar_dica()
        if reiniciar:
            self.canvas.yview_moveto(0)
        self._desenhar()

    def tiles(self) -> list[dict]:
        return [dict(t) for t in self._tiles]

    def vizinha(self, chave: str | None, passo: int) -> str | None:
        """A chave do cartão `passo` posições depois (ou antes, se negativo) de `chave`, na lista que está à vista (respeita a
        aba e a busca). Sem `chave` na lista, `passo` positivo dá o primeiro cartão e negativo, o último. Nas pontas não dá
        a volta: devolve a própria `chave`."""
        chaves = [t["chave"] for t in self._tiles]
        if not chaves:
            return None
        if chave not in chaves:
            return chaves[0] if passo > 0 else chaves[-1]
        return chaves[max(0, min(len(chaves) - 1, chaves.index(chave) + passo))]

    def _tipo(self, chave: str | None) -> str | None:
        return next((t["tipo"] for t in self._tiles if t["chave"] == chave), None)

    def cursor(self) -> str | None:
        return self._cursor

    def focar(self, chave: str | None = None) -> None:
        """Põe o foco do teclado no painel, no cartão `chave` (ou no atual, ou no primeiro)."""
        chaves = [t["chave"] for t in self._tiles]
        for candidata in (chave, self._cursor, self._atual):
            if candidata in chaves:
                self._cursor = candidata
                break
        else:
            self._cursor = chaves[0] if chaves else None
        self._com_foco = True
        self.canvas.focus_set()
        self._marcar_cursor()
        self._garantir_visivel(self._cursor)

    # ------------------------------------------------------------- desenho
    def _ao_configurar(self, ev) -> None:
        if ev.width != self._largura or ev.height != self._altura:      # a largura muda a disposição; a altura, a rolagem
            self._agendar()

    def _agendar(self) -> None:
        if self._id_redesenho is None:
            self._id_redesenho = self.after_idle(self._redesenhar)

    def _redesenhar(self) -> None:
        self._id_redesenho = None
        try:
            self._desenhar()
        except tk.TclError:                    # janela destruída antes do redesenho
            pass

    def destroy(self) -> None:
        if self._id_redesenho is not None:
            try:
                self.after_cancel(self._id_redesenho)
            except tk.TclError:
                pass
        super().destroy()

    def _tem_faixa(self) -> bool:
        """True quando o balcão está à vista (é sempre o primeiro da lista): ele é a faixa fina, fora da grade de cartões."""
        return bool(self._tiles) and self._tiles[0]["tipo"] == "balcao"

    def _celula(self, i: int) -> tuple[int, int, int, int]:
        """(x, y, largura, altura) da célula do cartão `i` da lista à vista: o balcão ocupa a faixa do alto; os demais ficam
        numa grade logo abaixo dela."""
        faixa = self._tem_faixa()
        if faixa and i == 0:
            return 0, 0, max(LARGURA, self._largura - RESERVA_BARRA), ALTURA_FAIXA
        j = i - 1 if faixa else i
        return (j % self._por_linha) * LARGURA, (ALTURA_FAIXA if faixa else 0) + (j // self._por_linha) * ALTURA, LARGURA, ALTURA

    def _desenhar(self) -> None:
        c = self.canvas
        c.delete("all")
        largura = c.winfo_width() if c.winfo_width() > 1 else LARGURA_PADRAO
        self._largura, self._altura = largura, c.winfo_height()
        self._por_linha = max(1, (largura - RESERVA_BARRA) // LARGURA)
        faixa = self._tem_faixa()
        linhas = max(1, -(-(len(self._tiles) - (1 if faixa else 0)) // self._por_linha))
        self._altura_total = (ALTURA_FAIXA if faixa else 0) + linhas * ALTURA + MARGEM
        c.configure(scrollregion=(0, 0, largura, self._altura_total))
        if self._altura_total > max(self._altura, 1) and self._altura > 1:
            self.barra.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne")
        else:
            self.barra.place_forget()
            c.yview_moveto(0)
        for i, t in enumerate(self._tiles):
            self._desenhar_tile(i, t)
        if not self._tiles:
            c.create_text(largura // 2, ALTURA // 2, text="Nenhuma posição neste filtro.",
                          fill=CX["suave"], font=(FONTE, 11))
        self._marcar_cursor()

    def _detalhes(self, t: dict) -> tuple[str, str, str, str]:
        """(linha de identificação, cor dela, aviso em destaque, cor do aviso) do cartão."""
        if t["tipo"] == "balcao":
            return "Venda rápida", CX["suave"], "", ""
        if t["tipo"] == "garota":
            n = t.get("marcacoes")
            if n:
                return (f"{n} drinks marcados" if n != 1 else "1 drink marcado"), CX["suave"], "", ""
            return ("Comissão a pagar" if t.get("nome") else ""), CX["suave"], "", ""
        if t.get("nome"):
            ident = t["nome"]
        elif t.get("pessoas"):
            ident = f"{t['pessoas']} pessoas" if t["pessoas"] != 1 else "1 pessoa"
        elif t.get("itens"):
            ident = f"{t['itens']} itens" if t["itens"] != 1 else "1 item"
        else:
            ident = ""
        if t.get("falta"):
            return ident, CX["suave"], f"Falta R$ {t['falta']}", CX["ambar"]
        if t["estado"] == "parada":
            return ident, CX["suave"], f"{t['minutos']} min sem lançar", CX["vermelho"]
        if t.get("garota"):
            return ident, CX["suave"], f"Comissão R$ {t['garota']}", ESTADOS["garota"]["texto"]
        return ident, CX["suave"], "", ""

    def _desenhar_faixa(self, i: int, t: dict) -> None:
        """O balcão: uma tira baixa com a pílula, a legenda e o total, na largura toda."""
        c = self.canvas
        x, y, w, h = self._celula(i)
        marca = (f"t:{t['chave']}", "tile")
        e = ESTADOS[t["estado"]]
        atual = t["chave"] == self._atual
        x1, y1, x2, y2 = x + 4, y + 4, x + w - 4, y + h - 4
        _cartao(c, x1, y1, x2, y2, raio=12, fill=e["fundo"], outline=CX["azul"] if atual else e["borda"],
                width=3 if atual else 1, tags=marca + ("fundo",))
        meio = (y1 + y2) / 2
        esquerda, direita = x1 + 12, x2 - 12
        texto = ROTULOS_PILULA[t["estado"]]
        largura_pilula = self._f_pilula.measure(texto) + 18
        _cartao(c, esquerda, meio - 10, esquerda + largura_pilula, meio + 10, raio=10,
                fill=misturar(e["borda"], e["fundo"], 0.62), outline=e["borda"], tags=marca + ("pilula",))
        c.create_text(esquerda + largura_pilula / 2, meio, text=texto, font=(FONTE, 8, "bold"), fill=e["texto"],
                      tags=marca + ("estado",))
        ident = self._detalhes(t)[0]
        if ident:
            c.create_text(esquerda + largura_pilula + 10, meio, text=ident, anchor="w", font=(FONTE, 9), fill=CX["suave"],
                          tags=marca + ("identificacao",))
        c.create_text(direita, meio, text=f"R$ {t['total'] or '0,00'}", anchor="e", font=(FONTE, 11, "bold"),
                      fill=CX["texto"], tags=marca + ("total",))

    def _desenhar_tile(self, i: int, t: dict) -> None:
        if t["tipo"] == "balcao":
            self._desenhar_faixa(i, t)
            return
        c = self.canvas
        x, y, w, h = self._celula(i)
        marca = (f"t:{t['chave']}", "tile")        # o prefixo evita que "5" seja tomado por número de item do Tk
        e = ESTADOS[t["estado"]]
        atual = t["chave"] == self._atual
        x1, y1, x2, y2 = x + 4, y + 4, x + w - 4, y + h - 4
        _cartao(c, x1, y1, x2, y2, raio=14, fill=e["fundo"], outline=CX["azul"] if atual else e["borda"],
                width=3 if atual else 1, tags=marca + ("fundo",))
        pad = 12
        esquerda, direita = x1 + pad, x2 - pad
        tipo_icone = "conta" if t["estado"] == "conta" else t["tipo"]
        rotulo_tipo = ROTULOS_TIPO[t["tipo"]] + (f" {t['rotulo']}" if t["tipo"] == "garota" and t.get("nome") else "")
        c.create_text(esquerda, y1 + 15, text=rotulo_tipo, anchor="w", font=(FONTE, 8, "bold"), fill=CX["suave"],
                      tags=marca + ("icone", f"icone:{tipo_icone}"))
        if t["estado"] == "parada":
            _relogio(c, direita - 7, y1 + 15, marca + ("relogio",))
            direita -= 22
        if t.get("garota"):
            _selo_garota(c, direita - 8, y1 + 15, marca + ("selo",))
            direita -= 22
        if t["tipo"] in ("comanda", "mesa") and t["minutos"] is not None:
            c.create_text(direita, y1 + 15, text=idade(t["minutos"]), anchor="e", font=(FONTE, 9),
                          fill=CX["vermelho"] if t["estado"] == "parada" else CX["suave"], tags=marca + ("idade",))
        titulo = t["nome"] if t["tipo"] == "garota" and t.get("nome") else t["rotulo"]
        c.create_text(esquerda, y1 + 39, text=titulo, anchor="w", font=(FONTE, 19 if len(titulo) <= 8 else 14, "bold"),
                      fill=CX["texto"], tags=marca + ("rotulo",))
        ident, cor_ident, aviso, cor_aviso = self._detalhes(t)
        if ident:
            c.create_text(esquerda, y1 + 64, text=ident, anchor="w", font=(FONTE, 9), fill=cor_ident, tags=marca + ("identificacao",))
        if aviso:
            c.create_text(esquerda, y1 + 79, text=aviso, anchor="w", font=(FONTE, 8, "bold"), fill=cor_aviso, tags=marca + ("detalhe",))
        # pílula da situação (à esquerda) e total (à direita), na linha de baixo
        baixo = y2 - 17
        texto = ROTULOS_PILULA[t["estado"]]
        largura_pilula = self._f_pilula.measure(texto) + 18
        _cartao(c, esquerda, baixo - 10, esquerda + largura_pilula, baixo + 10, raio=10,
                fill=misturar(e["borda"], e["fundo"], 0.62), outline=e["borda"], tags=marca + ("pilula",))
        c.create_text(esquerda + largura_pilula / 2, baixo, text=texto, font=(FONTE, 8, "bold"), fill=e["texto"],
                      tags=marca + ("estado",))
        total = t["total"]
        if total:
            c.create_text(x2 - pad, baixo, text=f"R$ {total}", anchor="e", font=(FONTE, 11, "bold"),
                          fill=CX["texto"], tags=marca + ("total",))

    def _marcar_cursor(self) -> None:
        c = self.canvas
        c.delete("cursor")
        chaves = [t["chave"] for t in self._tiles]
        if self._com_foco and self._cursor in chaves:
            x, y, w, h = self._celula(chaves.index(self._cursor))
            c.create_rectangle(x + 1, y + 1, x + w - 1, y + h - 1, outline=tema.COR["aviso"], width=2,
                               dash=(4, 3), tags=("cursor",))

    def _garantir_visivel(self, chave: str | None) -> None:
        chaves = [t["chave"] for t in self._tiles]
        if chave not in chaves or self._altura_total <= 0:
            return
        _, topo, _, altura = self._celula(chaves.index(chave))
        base = topo + altura
        janela_topo = self.canvas.canvasy(0)
        janela_base = janela_topo + self.canvas.winfo_height()
        if topo < janela_topo:
            self.canvas.yview_moveto(max(0.0, topo / self._altura_total))
        elif base > janela_base:
            self.canvas.yview_moveto(max(0.0, (base - self.canvas.winfo_height()) / self._altura_total))

    # --------------------------------------------------- mouse e teclado
    def _chave_do_item_atual(self) -> str | None:
        itens = self.canvas.find_withtag("current")
        for marca in self.canvas.gettags(itens[0]) if itens else ():
            if marca.startswith("t:"):
                return marca[2:]
        return None

    def _clique(self, _=None) -> None:
        chave = self._chave_do_item_atual()
        if chave is not None:
            self._ao_escolher(chave)

    def _clique_fundo(self, _=None) -> None:
        if self._chave_do_item_atual() is None:       # clicou no espaço vazio: leva o teclado para cá
            self.focar()

    def _roda(self, ev) -> None:
        if self._altura_total > self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 if ev.delta > 0 else 1, "units")

    def _foco(self, com_foco: bool) -> None:
        self._com_foco = com_foco
        if com_foco and self._cursor is None:
            self._cursor = self._atual
        self._marcar_cursor()

    def _mover(self, passo: int) -> None:
        chaves = [t["chave"] for t in self._tiles]
        if not chaves:
            return
        i = chaves.index(self._cursor) if self._cursor in chaves else 0
        self._cursor = chaves[max(0, min(len(chaves) - 1, i + passo))]
        self._marcar_cursor()
        self._garantir_visivel(self._cursor)

    def _vertical(self, i: int, sentido: int) -> int | None:
        """Índice do cartão uma linha abaixo (`sentido` 1) ou acima (-1) de `i`; None = saiu pelo alto do painel. A faixa do balcão
        é a primeira linha: dela se desce ao primeiro cartão, e do primeiro cartão de cada coluna se sobe até ela."""
        faixa = 1 if self._tem_faixa() else 0
        total = len(self._tiles)
        if faixa and i == 0:
            return 1 if sentido > 0 and total > 1 else (None if sentido < 0 else 0)
        j = i - faixa + sentido * self._por_linha
        if j < 0:
            return 0 if faixa else None
        return min(total - 1, j + faixa)

    def _tecla(self, ev) -> str | None:
        k = ev.keysym
        chaves = [t["chave"] for t in self._tiles]
        if k in ("Left", "Right"):
            self._mover(-1 if k == "Left" else 1)
        elif k in ("Down", "Up"):
            destino = self._vertical(chaves.index(self._cursor) if self._cursor in chaves else 0, 1 if k == "Down" else -1)
            if destino is None:
                self._ao_voltar()              # no alto do painel, a seta para cima volta ao campo da posição
            else:
                self._mover(destino - (chaves.index(self._cursor) if self._cursor in chaves else 0))
        elif k in ("Home", "End"):
            self._mover(-len(chaves) if k == "Home" else len(chaves))
        elif k in ("Return", "KP_Enter", "space"):
            if self._cursor:
                self._ao_escolher(self._cursor)
        elif k == "Escape":
            self._ao_voltar()
        elif k in ("t", "T"):
            if self._cursor and self._cursor != "0" and self._tipo(self._cursor) != "garota":
                self._ao_transferir(self._cursor)
        elif ev.char and (ev.char.isdigit() or ev.char in "cCmM"):
            self._ao_digitar(ev.char)
        else:
            return None                        # as teclas F continuam valendo (são tratadas na janela)
        return "break"
