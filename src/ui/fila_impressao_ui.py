"""Janela da fila de impressão: o que está esperando, o que deu erro, reenviar e cancelar."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.core import formatacao as fmt
from src.ui import tema

STATUS = {"pendente": "Aguardando", "enviado": "Impresso", "erro": "Erro", "cancelado": "Cancelado"}
DESTINO = {"caixa": "Caixa", "remota": "Cozinha/bar"}


class JanelaFilaImpressao(tk.Toplevel):
    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx, self.fila = ctx, ctx.impressao.fila
        self._id_after = None
        self.title("Fila de impressão")
        self.configure(bg=tema.COR["fundo"])
        self.geometry("1060x560")
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)
        self.lbl = ttk.Label(corpo, text="", font=tema.FONTE_B)
        self.lbl.pack(anchor="w", pady=(0, 6))
        ttk.Label(corpo, text="Os documentos da impressora térmica e da cozinha/bar são gravados aqui antes de imprimir. Se a "
                              "impressora estiver desligada ou fora da rede, eles esperam e saem sozinhos quando ela voltar. Falta de papel e "
                              "tampa aberta não são detectadas: o documento conta como impresso.",
                  wraplength=1000, foreground=tema.COR["suave"]).pack(anchor="w", pady=(0, 8))
        self.grade = tema.Grade(corpo, [("id", "Nº", 50, "e"), ("hora", "Gerado em", 130, "w"), ("dest", "Destino", 90, "w"),
                                        ("doc", "Documento", 170, "w"), ("status", "Situação", 90, "w"), ("tent", "Tentativas", 86, "e"),
                                        ("prox", "Próxima", 120, "w"), ("erro", "Último erro", 284, "w")], altura=14)
        self.grade.pack(fill="both", expand=True)
        self.grade.tag("pendente", foreground=tema.COR["aviso"])
        self.grade.tag("erro", foreground=tema.COR["perigo"])
        self.grade.tag("enviado", foreground=tema.COR["suave"])
        self.grade.tag("cancelado", foreground=tema.COR["virtual"])
        barra = ttk.Frame(corpo)
        barra.pack(fill="x", pady=(10, 0))
        ttk.Button(barra, text="Reenviar selecionado", command=self.reenviar).pack(side="left")
        ttk.Button(barra, text="Reenviar tudo que está esperando", command=self.reenviar_todos).pack(side="left", padx=6)
        ttk.Button(barra, text="Cancelar selecionado", style="Perigo.TButton", command=self.cancelar).pack(side="left")
        ttk.Button(barra, text="Imprimir página de teste", command=self.teste).pack(side="left", padx=6)
        ttk.Button(barra, text="Limpar impressos", command=self.limpar).pack(side="left")
        ttk.Button(barra, text="Assistente de impressora", command=self.assistente).pack(side="left", padx=6)
        ttk.Button(barra, text="Fechar (Esc)", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.atualizar()
        tema.centralizar(self, master.winfo_toplevel())
        self.transient(master.winfo_toplevel())

    def assistente(self) -> None:
        from src.ui.assistente_impressora_ui import JanelaAssistenteImpressora
        JanelaAssistenteImpressora(self, self.ctx, self.atualizar)

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
        self._cancelar_agendamento()   # os botões chamam isto direto: sem isto cada clique deixaria um temporizador a mais
        try:
            atual = self.grade.selecionado()
            itens = self.fila.listar(300)
            self.grade.preencher(
                [[i["id"], fmt.fmt_datahora(i["criado_em"]), DESTINO.get(i["destino"], i["destino"]), i["nome"],
                  STATUS.get(i["status"], i["status"]), i["tentativas"],
                  fmt.fmt_hora(i["proxima_tentativa"]) if i["proxima_tentativa"] and i["status"] == "pendente" else "",
                  i["ultimo_erro"] or ""] for i in itens],
                [i["id"] for i in itens], [(i["status"],) for i in itens])
            if atual:
                self.grade.selecionar(atual)
            texto, nivel = self.fila.texto_indicador()
            cor = {"ok": tema.COR["ok"], "aviso": tema.COR["aviso"], "erro": tema.COR["perigo"]}[nivel]
            self.lbl.configure(text=texto, foreground=cor)
            self._id_after = self.after(2000, self.atualizar)
        except tk.TclError:
            pass

    def _selecionado(self) -> int | None:
        s = self.grade.selecionado()
        if s is None:
            tema.aviso(self, "Selecione um item da lista.")
            return None
        return int(s)

    def reenviar(self) -> None:
        i = self._selecionado()
        if i is not None:
            ok, _ = tema.tratar(self, self.fila.reenviar, i)
            if ok:
                self.atualizar()

    def reenviar_todos(self) -> None:
        n = self.fila.reenviar_todos()
        tema.mensagem(self, f"{n} item(ns) devolvido(s) à fila para imprimir agora." if n else "Não há nada esperando.", "Fila de impressão")
        self.atualizar()

    def cancelar(self) -> None:
        i = self._selecionado()
        if i is not None and tema.confirmar(self, "Cancelar este documento? Ele não será impresso.", "Cancelar", padrao_sim=False):
            ok, _ = tema.tratar(self, self.fila.cancelar, i)
            if ok:
                self.atualizar()

    def teste(self) -> None:
        ok, _ = tema.tratar(self, self.ctx.impressao.imprimir_teste)
        if ok:
            tema.mensagem(self, "Página de teste enviada diretamente à impressora térmica.", "Teste de impressão")

    def limpar(self) -> None:
        n = self.fila.limpar_antigos(0)
        tema.mensagem(self, f"{n} registro(s) de documentos já impressos ou cancelados removido(s).", "Fila de impressão")
        self.atualizar()
