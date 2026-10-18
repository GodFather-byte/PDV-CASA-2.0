"""Componentes da tela principal: item de navegação, cartão de indicador, barra de proporção e avisos clicáveis.

Todos reagem ao mouse (hover com transição suave) e, quando têm ação, mudam o cursor e abrem a tela correspondente."""
from __future__ import annotations

import sys
import tkinter as tk

from src.ui import paleta

PAL = dict(paleta.PAL[paleta.PADRAO])      # o conteúdo troca com o modo (claro/escuro): ver paleta.aplicar
FONTE = "Segoe UI" if sys.platform == "win32" else "Helvetica"


def misturar(c1: str, c2: str, t: float) -> str:
    """Cor intermediária entre c1 e c2 (t=0 -> c1, t=1 -> c2)."""
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _cancelar_ao_destruir(widget: tk.Misc, *nomes: str) -> None:
    """Cancela os `after` pendentes (guardados nos atributos `nomes`) quando o widget é destruído: sem isso o Tk
    tenta chamar o quadro de animação de um widget que já não existe."""
    def cancelar(e):
        if e.widget is widget:
            for nome in nomes:
                id_ = getattr(widget, nome, None)
                if id_:
                    try:
                        widget.after_cancel(id_)
                    except tk.TclError:
                        pass
                    setattr(widget, nome, None)
    widget.bind("<Destroy>", cancelar, add="+")


class _Transicao:
    """Move `self._t` suavemente até `self._alvo` (0..1) e chama `self._pintar()` a cada quadro."""
    _t = 0.0
    _alvo = 0.0
    _quadro = None

    def _ir_para(self, alvo: float) -> None:
        self._alvo = alvo
        if self._quadro is None:
            self._passo()

    def _passo(self) -> None:
        self._quadro = None
        try:
            if not self.winfo_exists():
                return
            d = self._alvo - self._t
            self._t = self._alvo if abs(d) < 0.03 else self._t + d * 0.4
            self._pintar()
            if self._t != self._alvo:
                self._quadro = self.after(16, self._passo)
        except tk.TclError:
            pass

    def _pintar(self) -> None:           # pragma: no cover - cada componente define a sua
        raise NotImplementedError


def _ligar(widget: tk.Misc, entrou, saiu, clicou) -> None:
    """Liga os eventos de mouse ao widget e a todos os filhos (o hover não pode piscar ao passar por cima de um rótulo)."""
    widget.bind("<Enter>", entrou, add="+")
    widget.bind("<Leave>", saiu, add="+")
    if clicou is not None:
        widget.bind("<Button-1>", clicou, add="+")
    for filho in widget.winfo_children():
        _ligar(filho, entrou, saiu, clicou)


class ItemNav(_Transicao, tk.Frame):
    """Botão da barra lateral: ícone colorido, nome (com a letra de atalho sublinhada), atalho e barra de destaque."""

    def __init__(self, pai, rotulo: str, icone: str, cor: str, letra: str, comando, destaque: bool = False):
        self.base = misturar(PAL["lateral"], cor, 0.16) if destaque else PAL["lateral"]
        super().__init__(pai, bg=self.base, cursor="hand2", height=52)
        self.pack_propagate(False)
        self.cor, self.comando, self.foco = cor, comando, False
        self.hover = False
        self.barra = tk.Frame(self, width=4, bg=self.base)
        self.barra.pack(side="left", fill="y")
        self.tile = tk.Label(self, text=icone, font=(FONTE, 14, "bold"), fg=cor, bg=misturar(PAL["lateral"], cor, 0.22),
                             width=3)
        self.tile.pack(side="left", padx=(8, 8), pady=9, fill="y")
        i = rotulo.lower().find(letra.lower())
        self.nome = tk.Label(self, text=rotulo, font=(FONTE, 11, "bold" if destaque else "normal"), fg=PAL["texto"],
                             bg=self.base, anchor="w", underline=i)
        self.nome.pack(side="left", fill="x", expand=True)
        self.badge = tk.Label(self, text=letra.upper(), font=(FONTE, 8, "bold"), fg=PAL["mudo"], bg=self.base, width=2)
        self.badge.pack(side="right", padx=(4, 12))
        _cancelar_ao_destruir(self, "_quadro")
        _ligar(self, self._entrou, self._saiu, lambda e: self.comando())
        self._pintar()

    def _entrou(self, _=None) -> None:
        self.hover = True
        self._ir_para(1.0)

    def _saiu(self, _=None) -> None:
        self.hover = False
        self._ir_para(1.0 if self.foco else 0.0)

    def marcar(self, ligado: bool) -> None:
        """Seleção pelo teclado (setas)."""
        self.foco = ligado
        self._ir_para(1.0 if (ligado or self.hover) else 0.0)

    def _pintar(self) -> None:
        bg = misturar(self.base, PAL["cartao_hover"], self._t)
        self.configure(bg=bg)
        self.nome.configure(bg=bg)
        self.badge.configure(bg=bg, fg=misturar(PAL["mudo"], self.cor, self._t))
        self.barra.configure(bg=misturar(self.base, self.cor, self._t))
        self.tile.configure(bg=misturar(misturar(PAL["lateral"], self.cor, 0.22), self.cor, self._t * 0.35))


class Cartao(_Transicao, tk.Frame):
    """Indicador: título, valor grande colorido e detalhe. Com `clique`, vira atalho para a tela do assunto."""

    def __init__(self, pai, titulo: str, cor: str, detalhe: str = "", clique=None, valor_inicial: str = "0"):
        super().__init__(pai, bg=PAL["cartao"], highlightthickness=1, highlightbackground=PAL["borda"],
                         cursor="hand2" if clique else "")
        self.cor, self.clique = cor, clique
        self._flash = 0.0
        self._id_flash = None
        _cancelar_ao_destruir(self, "_quadro", "_id_flash")
        self.topo = tk.Frame(self, height=3, bg=misturar(PAL["cartao"], cor, 0.55))
        self.topo.pack(fill="x")
        self.rotulo = tk.Label(self, text=titulo, font=(FONTE, 9), fg=PAL["suave"], bg=PAL["cartao"], anchor="w")
        self.rotulo.pack(fill="x", padx=14, pady=(7, 0))
        self.valor = tk.Label(self, text=valor_inicial, font=(FONTE, 22, "bold"), fg=cor, bg=PAL["cartao"], anchor="w")
        self.valor.pack(fill="x", padx=14)
        self.detalhe = tk.Label(self, text=detalhe, font=(FONTE, 8), fg=PAL["mudo"], bg=PAL["cartao"], anchor="w")
        self.detalhe.pack(fill="x", padx=14, pady=(0, 7))
        self.bind("<Configure>", self._ajustar_textos)
        _ligar(self, self._entrou, self._saiu, (lambda e: self.clique()) if clique else None)

    def _ajustar_textos(self, evento) -> None:
        largura = max(60, evento.width - 30)
        self.rotulo.configure(wraplength=largura, justify="left")
        self.detalhe.configure(wraplength=largura, justify="left")
        self.valor.configure(font=(FONTE, 18 if largura < 200 else 22, "bold"))

    def definir(self, texto: str, detalhe: str | None = None) -> None:
        """Atualiza o valor; se mudou, o número 'pisca' em branco e volta à cor (chama a atenção sem travar nada)."""
        mudou = str(self.valor.cget("text")) != texto
        self.valor.configure(text=texto)
        if detalhe is not None:
            self.detalhe.configure(text=detalhe)
        if mudou:
            if self._id_flash:                  # mudou de novo no meio do pisca: recomeça, sem deixar duas animações rodando
                self.after_cancel(self._id_flash)
                self._id_flash = None
            self._flash = 1.0
            self._piscar()

    def _piscar(self) -> None:
        try:
            if not self.winfo_exists():
                return
            self.valor.configure(fg=misturar(self.cor, PAL["brilho"], self._flash))
            self._flash = max(0.0, self._flash - 0.1)
            if self._flash > 0:
                self._id_flash = self.after(40, self._piscar)
            else:
                self.valor.configure(fg=self.cor)
        except tk.TclError:
            pass

    def _entrou(self, _=None) -> None:
        self._ir_para(1.0 if self.clique else 0.5)

    def _saiu(self, _=None) -> None:
        self._ir_para(0.0)

    def _pintar(self) -> None:
        bg = misturar(PAL["cartao"], PAL["cartao_hover"], self._t)
        self.configure(bg=bg, highlightbackground=misturar(PAL["borda"], PAL["borda_hover"] if self.clique else PAL["borda"], self._t))
        for w in (self.rotulo, self.valor, self.detalhe):
            w.configure(bg=bg)
        self.topo.configure(bg=misturar(misturar(PAL["cartao"], self.cor, 0.55), self.cor, self._t))


class Aviso(_Transicao, tk.Frame):
    """Pílula de status (backup, versão nova). `definir` troca texto e cor do ponto; clicável quando recebe `clique`."""

    def __init__(self, pai, clique=None, wraplength: int = 0):
        super().__init__(pai, bg=PAL["cartao"], highlightthickness=1, highlightbackground=PAL["borda"],
                         cursor="hand2" if clique else "")
        self.clique = clique
        _cancelar_ao_destruir(self, "_quadro")
        self.ponto = tk.Label(self, text="●", font=(FONTE, 9), fg=PAL["ambar"], bg=PAL["cartao"])
        self.ponto.pack(side="left", padx=(10, 2), pady=6)
        self.texto = tk.Label(self, text="", font=(FONTE, 9, "bold"), fg=PAL["texto"], bg=PAL["cartao"], justify="left",
                              wraplength=wraplength)
        self.texto.pack(side="left", padx=(0, 12), pady=6)
        _ligar(self, self._entrou, self._saiu, (lambda e: self.clique()) if clique else None)

    def definir(self, texto: str, cor: str) -> None:
        self.texto.configure(text=texto)
        self.ponto.configure(fg=cor)

    def _entrou(self, _=None) -> None:
        self._ir_para(1.0 if self.clique else 0.0)

    def _saiu(self, _=None) -> None:
        self._ir_para(0.0)

    def _pintar(self) -> None:
        bg = misturar(PAL["cartao"], PAL["cartao_hover"], self._t)
        self.configure(bg=bg, highlightbackground=misturar(PAL["borda"], PAL["borda_hover"], self._t))
        self.ponto.configure(bg=bg)
        self.texto.configure(bg=bg)


class Atalho(_Transicao, tk.Frame):
    """Botão de ação rápida (chip) da tela principal."""

    def __init__(self, pai, texto: str, cor: str, comando, detalhe: str = "", destaque: bool = False):
        self.base = misturar(PAL["cartao"], cor, 0.16) if destaque else PAL["cartao"]
        super().__init__(pai, bg=self.base, highlightthickness=1, highlightbackground=cor if destaque else PAL["borda"],
                         cursor="hand2", takefocus=True)
        self.cor, self.comando = cor, comando
        _cancelar_ao_destruir(self, "_quadro")
        self.ponto = tk.Label(self, text=">", font=(FONTE, 20 if destaque else 14, "bold"), fg=cor, bg=self.base)
        self.ponto.pack(side="right", padx=14, pady=8)
        self.textos = tk.Frame(self, bg=self.base)
        self.textos.pack(side="left", fill="both", expand=True, padx=(14, 0), pady=10 if detalhe else 6)
        self.texto = tk.Label(self.textos, text=texto, font=(FONTE, 15 if destaque else 10, "bold"),
                              fg=PAL["texto"], bg=self.base, anchor="w")
        self.texto.pack(fill="x")
        self.detalhe = tk.Label(self.textos, text=detalhe, font=(FONTE, 9), fg=PAL["suave"], bg=self.base, anchor="w")
        if detalhe:
            self.detalhe.pack(fill="x", pady=(3, 0))
        self.bind("<Configure>", lambda e: self.detalhe.configure(wraplength=max(60, e.width - 80), justify="left"))
        self.bind("<Return>", lambda e: (self.comando(), "break")[1])
        self.bind("<space>", lambda e: (self.comando(), "break")[1])
        self.bind("<FocusIn>", lambda e: self._ir_para(1.0))
        self.bind("<FocusOut>", lambda e: self._ir_para(0.0))
        _ligar(self, lambda e: self._ir_para(1.0), lambda e: self._ir_para(0.0), lambda e: self.comando())

    def _pintar(self) -> None:
        bg = misturar(self.base, misturar(self.base, self.cor, 0.28), self._t)
        self.configure(bg=bg, highlightbackground=misturar(PAL["borda"], self.cor, self._t))
        self.ponto.configure(bg=bg)
        self.texto.configure(bg=bg)
        self.textos.configure(bg=bg)
        self.detalhe.configure(bg=bg)


class ConteudoRolavel(tk.Frame):
    """Mantém o painel acessível em notebooks, sem rolar a navegação lateral."""

    def __init__(self, pai):
        super().__init__(pai, bg=PAL["fundo"])
        self.canvas = tk.Canvas(self, bg=PAL["fundo"], highlightthickness=0, yscrollincrement=24)
        barra = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview, bg=PAL["lateral"],
                             troughcolor=PAL["fundo"], activebackground=PAL["suave"], width=12)
        barra.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=barra.set)
        self.corpo = tk.Frame(self.canvas, bg=PAL["fundo"], padx=24, pady=20)
        self._janela = self.canvas.create_window(0, 0, window=self.corpo, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._janela, width=e.width))
        self.corpo.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

    def ligar_rolagem(self) -> None:
        def rolar(evento):
            if self.corpo.winfo_height() > self.canvas.winfo_height():
                passo = (-1 if evento.delta > 0 else 1) if evento.num not in (4, 5) else (-1 if evento.num == 4 else 1)
                self.canvas.yview_scroll(passo * 3, "units")
            return "break"

        def ligar(widget):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(seq, rolar, add="+")
            for filho in widget.winfo_children():
                ligar(filho)
        ligar(self)


class BarraProporcao(tk.Canvas):
    """Barra segmentada (sem estoque / ponto de pedido / normal) que cresce até a proporção real quando os dados mudam."""

    def __init__(self, pai, cores: list[str], altura: int = 12):
        super().__init__(pai, height=altura, bg=PAL["fundo"], highlightthickness=0)
        self.cores = cores
        self._alvo = [0.0] * len(cores)
        self._atual = [0.0] * len(cores)
        self._quadro = None
        _cancelar_ao_destruir(self, "_quadro")
        self.bind("<Configure>", lambda e: self._desenhar())

    def definir(self, valores: list[int]) -> None:
        total = sum(valores)
        self._alvo = [v / total for v in valores] if total else [0.0] * len(valores)
        if self._quadro is None:
            self._passo()

    def _passo(self) -> None:
        self._quadro = None
        try:
            if not self.winfo_exists():
                return
            parado = True
            for i, alvo in enumerate(self._alvo):
                d = alvo - self._atual[i]
                if abs(d) < 0.002:
                    self._atual[i] = alvo
                else:
                    self._atual[i] += d * 0.3
                    parado = False
            self._desenhar()
            if not parado:
                self._quadro = self.after(16, self._passo)
        except tk.TclError:
            pass

    def _desenhar(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:
            return
        self.create_rectangle(0, 0, w, h, fill=PAL["borda"], outline="")
        x = 0.0
        for fracao, cor in zip(self._atual, self.cores):
            fim = x + fracao * w
            if fim - x >= 1:
                self.create_rectangle(round(x), 0, round(fim), h, fill=cor, outline="")
            x = fim
