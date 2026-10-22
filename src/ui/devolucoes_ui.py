"""Devolução/troca de venda fechada pelo cupom original (Tk). Regras em docs/DEVOLUCOES.md."""
from __future__ import annotations

import tkinter as tk
import uuid as _uuid
from tkinter import ttk

from src.controllers.devolucoes_controller import MODULO, MODOS, DevolucoesController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.ui import tema

COLUNAS = ("Produto", "Vendida", "Devolvida", "Saldo", "Líquido", "A devolver", "Estoque")


class JanelaDevolucoes(tk.Toplevel):
    def __init__(self, master, ctx):
        self.ctx = ctx
        self.exigir_acesso()
        super().__init__(master)
        self.title("Devolução / troca de venda")
        self.geometry("1100x760")
        self.situacao = None
        self.escolhas: dict[int, dict] = {}
        self.ultima = None
        self._novo_uuid()
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)

        busca = ttk.Frame(corpo)
        busca.pack(fill="x")
        ttk.Label(busca, text="Cupom original").pack(side="left")
        self.cupom = ttk.Entry(busca, width=12)
        self.cupom.pack(side="left", padx=6)
        self.cupom.bind("<Return>", lambda _e: self.buscar())
        ttk.Button(busca, text="Buscar", command=self.buscar).pack(side="left")
        self.cabecalho = ttk.Label(busca, text="")
        self.cabecalho.pack(side="left", padx=12)

        quadro = ttk.Frame(corpo)
        quadro.pack(fill="both", expand=True, pady=8)
        self.grade = ttk.Treeview(quadro, columns=COLUNAS, show="headings", height=10, selectmode="browse")
        for c in COLUNAS:
            self.grade.heading(c, text=c)
            self.grade.column(c, width=300 if c == "Produto" else 110, anchor="w" if c == "Produto" else "e")
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=self.grade.yview)
        self.grade.configure(yscrollcommand=rolagem.set)
        self.grade.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")
        self.grade.bind("<<TreeviewSelect>>", lambda _e: self._carregar_linha())

        linha = ttk.Frame(corpo)
        linha.pack(fill="x")
        ttk.Label(linha, text="Quantidade a devolver (até 4 casas)").pack(side="left")
        self.quantidade = ttk.Entry(linha, width=12)
        self.quantidade.pack(side="left", padx=6)
        self.estoque = tk.BooleanVar(value=False)
        ttk.Checkbutton(linha, text="Volta ao estoque", variable=self.estoque).pack(side="left", padx=6)
        ttk.Button(linha, text="Aplicar ao item", command=self.aplicar).pack(side="left", padx=6)
        ttk.Button(linha, text="Devolver tudo", command=self.tudo).pack(side="left")
        ttk.Button(linha, text="Limpar", command=self.limpar_escolhas).pack(side="left", padx=6)

        form = ttk.Frame(corpo)
        form.pack(fill="x", pady=8)
        form.columnconfigure(1, weight=1)
        self.modo = ttk.Combobox(form, state="readonly")
        self.forma = ttk.Combobox(form, state="readonly")
        self.referencia = ttk.Entry(form)
        self.motivo = ttk.Entry(form)
        for i, (rotulo, campo) in enumerate((("Reembolso", self.modo), ("Forma", self.forma),
                                             ("Referência do estorno externo (NSU/Pix)", self.referencia),
                                             ("Motivo (obrigatório)", self.motivo))):
            ttk.Label(form, text=rotulo).grid(row=i, column=0, sticky="w", padx=(0, 10))
            campo.grid(row=i, column=1, sticky="ew", pady=2)
        self.modo.bind("<<ComboboxSelected>>", lambda _e: self._carregar_formas())
        opcoes = ttk.Frame(corpo)
        opcoes.pack(fill="x")
        self.troca = tk.BooleanVar(value=False)
        self.extras = tk.BooleanVar(value=True)
        ttk.Checkbutton(opcoes, text="É troca (abre nova venda depois)", variable=self.troca).pack(side="left")
        ttk.Checkbutton(opcoes, text="Devolver taxa/acréscimo se completar a venda", variable=self.extras,
                        command=self.atualizar_previa).pack(side="left", padx=12)

        self.previa = ttk.Label(corpo, text="", justify="left")
        self.previa.pack(fill="x", pady=6)
        acoes = ttk.Frame(corpo)
        acoes.pack(fill="x")
        self.btn_registrar = ttk.Button(acoes, text="Registrar devolução", command=self.registrar)
        self.btn_registrar.pack(side="left")
        self.btn_reimprimir = ttk.Button(acoes, text="Reimprimir comprovante", command=self.reimprimir,
                                         state="disabled")
        self.btn_reimprimir.pack(side="left", padx=8)
        self.btn_troca = ttk.Button(acoes, text="Abrir venda da troca", command=self.abrir_troca, state="disabled")
        self.btn_troca.pack(side="left")
        ttk.Button(acoes, text="Fechar", command=self.destroy).pack(side="right")
        self.mensagem = ttk.Label(corpo, text="")
        self.mensagem.pack(fill="x", pady=4)
        self.cupom.focus_set()

    # ------------------------------------------------------------ apoio
    def _controller(self) -> DevolucoesController:
        return DevolucoesController(self.ctx.banco, self.ctx.operador_id)

    def exigir_acesso(self) -> None:
        self._controller().exigir_acesso()

    def _novo_uuid(self) -> None:
        self.uuid = str(_uuid.uuid4())       # um por tentativa: repetir o clique não grava duas vezes

    def buscar(self):
        try:
            self.exigir_acesso()
            v = self._controller().venda_por_cupom(self.cupom.get())
            self.situacao = self._controller().situacao(v["id"])
        except ErroNegocio as e:
            self.situacao = None
            self._preencher()
            self.mensagem.configure(text=str(e))
            return False
        self.escolhas = {}
        self._novo_uuid()
        self._preencher()
        self.mensagem.configure(text="")
        return True

    def _preencher(self):
        for i in self.grade.get_children():
            self.grade.delete(i)
        s = self.situacao
        if s is None:
            self.cabecalho.configure(text="")
            self.modo.configure(values=())
            self.previa.configure(text="")
            return
        v = s["venda"]
        self.cabecalho.configure(text=f"Cupom {v['cupom']} — {fmt.fmt_datahora(v['fechada_em'])} — total "
                                      f"{fmt.fmt_brl(s['total_cent'])} — já devolvido {fmt.fmt_brl(s['devolvido_cent'])}")
        for it in s["itens"]:
            e = self.escolhas.get(it["item_id"])
            self.grade.insert("", "end", iid=str(it["item_id"]), values=(
                it["nome"], fmt.fmt_qtd(it["quantidade"], 4), fmt.fmt_qtd(it["devolvida"], 4),
                fmt.fmt_qtd(it["saldo"], 4), fmt.fmt_brl(it["liquido_cent"]),
                fmt.fmt_qtd(e["quantidade"], 4) if e else "", ("Sim" if e["retorna_estoque"] else "Não") if e else ""))
        rotulos = [MODOS[m] for m in s["modos"]]
        atual = self.modo.get()
        self.modo.configure(values=rotulos)
        if atual not in rotulos:
            self.modo.current(0)
        self._carregar_formas()
        self.atualizar_previa()

    def _modo(self) -> str | None:
        if self.situacao is None or self.modo.current() < 0:
            return None
        return self.situacao["modos"][self.modo.current()]

    def _carregar_formas(self):
        modo = self._modo()
        if modo == "dinheiro_gaveta":
            self.formas = [(f["id"], f["tipo"]) for f in self._controller().formas_dinheiro()]
        elif modo == "externo":
            self.formas = [(f["tipo_pagamento_id"], f"{f['tipo']} (pago {fmt.fmt_brl(f['pago_cent'])}, estornado "
                            f"{fmt.fmt_brl(f['estornado_externo_cent'])})")
                           for f in self.situacao["formas"] if not f["na_gaveta"]]
        else:
            self.formas = []
        self.forma.configure(values=[r for _, r in self.formas])
        self.forma.set("")
        if self.formas:
            self.forma.current(0)

    def _carregar_linha(self):
        sel = self.grade.selection()
        if not sel or self.situacao is None:
            return
        item_id = int(sel[0])
        it = next(i for i in self.situacao["itens"] if i["item_id"] == item_id)
        e = self.escolhas.get(item_id)
        self.quantidade.delete(0, "end")
        self.quantidade.insert(0, fmt.fmt_qtd(e["quantidade"] if e else it["saldo"], 4))
        self.estoque.set(e["retorna_estoque"] if e else it["sugere_estoque"])

    def aplicar(self):
        sel = self.grade.selection()
        if not sel:
            self.mensagem.configure(text="Escolha o item na lista.")
            return False
        try:
            q = fmt.para_qtd(self.quantidade.get())
        except (ErroNegocio, ValueError) as e:
            self.mensagem.configure(text=str(e) or "Quantidade inválida.")
            return False
        item_id = int(sel[0])
        if q <= 0:
            self.escolhas.pop(item_id, None)
        else:
            self.escolhas[item_id] = {"item_id": item_id, "quantidade": q, "retorna_estoque": bool(self.estoque.get())}
        self._preencher()
        return True

    def tudo(self):
        if self.situacao is None:
            return
        self.escolhas = {i["item_id"]: {"item_id": i["item_id"], "quantidade": i["saldo"],
                                        "retorna_estoque": i["sugere_estoque"]}
                         for i in self.situacao["itens"] if i["saldo"] > 0}
        self._preencher()

    def limpar_escolhas(self):
        self.escolhas = {}
        self._preencher()

    def atualizar_previa(self):
        if self.situacao is None or not self.escolhas:
            self.previa.configure(text="Escolha os itens e as quantidades a devolver." if self.situacao else "")
            return None
        try:
            p = self._controller().previa(self.situacao["venda"]["id"], list(self.escolhas.values()),
                                          bool(self.extras.get()))
        except ErroNegocio as e:
            self.previa.configure(text=str(e))
            return None
        self.previa.configure(text=(
            f"Itens {fmt.fmt_brl(p['itens_bruto_cent'])}  − desconto rateado {fmt.fmt_brl(p['desconto_rateado_cent'])}"
            f"  + serviço rateado {fmt.fmt_brl(p['servico_rateado_cent'])}  + taxa/acréscimo "
            f"{fmt.fmt_brl(p['extras_cent'])}\nA DEVOLVER: {fmt.fmt_brl(p['valor_cent'])}"
            + ("  (completa a venda)" if p["completa"] else "")))
        return p
    # ------------------------------------------------------------ gravação
    def _autorizador(self) -> int | None:
        c = self._controller()
        if c.operador_autoriza():
            return self.ctx.operador_id
        sup = tema.pedir_senha_supervisor(self, self.ctx, MODULO, "Devolução de venda")
        return sup.id if sup is not None else None

    def registrar(self):
        try:
            self.exigir_acesso()
        except ErroNegocio as e:
            self.mensagem.configure(text=str(e))
            return None
        if self.situacao is None:
            self.mensagem.configure(text="Busque o cupom original.")
            return None
        if not self.escolhas:
            self.mensagem.configure(text="Escolha pelo menos um item a devolver.")
            return None
        if not " ".join(self.motivo.get().split()):
            self.mensagem.configure(text="Informe o motivo da devolução.")
            return None
        modo = self._modo()
        indice = self.forma.current()
        forma = self.formas[indice][0] if 0 <= indice < len(self.formas) else None
        p = self.atualizar_previa()
        if p is None:
            return None
        if not tema.confirmar(self, f"Registrar devolução de {fmt.fmt_brl(p['valor_cent'])} como "
                                    f"'{MODOS[modo]}'?\nO registro não pode ser desfeito."):
            return None
        autorizado = self._autorizador()
        if autorizado is None:
            self.mensagem.configure(text="Devolução não autorizada.")
            return None
        ok, dev = tema.tratar(self, self.ctx.caixa.devolver, self.situacao["venda"]["id"],
                              list(self.escolhas.values()), self.motivo.get(), autorizado, modo, self.uuid,
                              tipo_pagamento_id=forma, referencia_externa=self.referencia.get(),
                              troca=bool(self.troca.get()), reembolsar_extras=bool(self.extras.get()))
        if not ok:
            return None                     # mesmo uuid: tentar de novo não duplica se algo já tiver sido gravado
        self.ultima = dev
        self._novo_uuid()
        self.motivo.delete(0, "end")
        self.referencia.delete(0, "end")
        self.escolhas = {}
        self.btn_reimprimir.configure(state="normal")
        self.btn_troca.configure(state="normal" if dev["troca"] else "disabled")
        aviso = "" if not dev.get("repetida") else " (já estava registrada)"
        self.mensagem.configure(text=f"Devolução registrada{aviso}: {fmt.fmt_brl(dev['valor_cent'])}.")
        try:
            self.situacao = self._controller().situacao(dev["venda_id"])
        except ErroNegocio:
            self.situacao = None
        self._preencher()
        if not dev.get("repetida"):
            self._imprimir(abrir_gaveta=dev["reembolso_modo"] == "dinheiro_gaveta" and dev["valor_cent"] > 0)
        return dev

    def _imprimir(self, abrir_gaveta: bool = False) -> bool:
        """Falha de impressão nunca refaz a devolução: o registro já está gravado; resta reimprimir."""
        if self.ultima is None:
            return False
        try:
            texto = self._controller().comprovante(self.ultima["id"], self.ctx.impressao.largura())
            self.ctx.impressao.enviar(texto, nome=f"devolucao_{self.ultima['id']}", abrir_gaveta=abrir_gaveta)
            return True
        except Exception as e:  # noqa: BLE001 - a devolução já foi gravada
            tema.aviso(self, f"A devolução foi gravada, mas o comprovante não imprimiu:\n{e}\n"
                             "Use 'Reimprimir comprovante'. Não registre de novo.")
            return False

    def reimprimir(self):
        return self._imprimir(abrir_gaveta=False)

    def abrir_troca(self):
        if self.ultima is None:
            return None
        ok, venda_id = tema.tratar(self, self.ctx.caixa.abrir_troca, self.ultima["id"])
        if ok:
            self.mensagem.configure(text="Venda da troca aberta no balcão: lance o produto novo pelo caixa.")
        return venda_id if ok else None


def abrir(master, ctx):
    return JanelaDevolucoes(master, ctx)