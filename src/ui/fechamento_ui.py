"""Coleta explícita de valores e justificativa do fechamento, sem encerrar turno."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio


class DialogoFechamento(tk.Toplevel):
    def __init__(self, master, ctx, turno_id: int, valor_final_cent: int):
        self.ctx, self.turno_id, self.valor_final_cent = ctx, turno_id, valor_final_cent
        self.operador_id = ctx.operador_id
        self.formas = ctx.turnos.formas_conferencia(turno_id, self.operador_id)
        self.resultado = None
        self.previa = None
        super().__init__(master)
        self.title("Conferência por forma")
        self.transient(master)
        corpo = ttk.Frame(self, padding=14)
        corpo.pack(fill="both", expand=True)
        ttk.Label(corpo, text="Informe todas as formas, inclusive zero. Não copie o esperado.").grid(
            row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(corpo, text=f"Gaveta declarada: {fmt.fmt_brl(valor_final_cent)}").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=8)
        for coluna, titulo in enumerate(("Forma", "Informado (R$)", "Esperado", "Diferença")):
            ttk.Label(corpo, text=titulo).grid(row=2, column=coluna, padx=6)
        self.campos, self.esperados, self.diferencas = {}, {}, {}
        for linha, forma in enumerate(self.formas, 3):
            chave = forma["tipo_id"]
            ttk.Label(corpo, text=forma["tipo"]).grid(row=linha, column=0, sticky="w")
            campo = ttk.Entry(corpo, width=18)
            campo.grid(row=linha, column=1, padx=6, pady=3)
            self.campos[chave] = campo
            self.esperados[chave] = ttk.Label(corpo, text="Não revelado")
            self.diferencas[chave] = ttk.Label(corpo, text="—")
            self.esperados[chave].grid(row=linha, column=2, padx=6)
            self.diferencas[chave].grid(row=linha, column=3, padx=6)
        linha = len(self.formas) + 3
        self.gaveta = ttk.Label(corpo, text="Dinheiro inclui fundo, suprimentos e sangrias; recebido já líquido de troco.")
        self.gaveta.grid(row=linha, column=0, columnspan=4, sticky="w", pady=8)
        self.rotulo_motivo = ttk.Label(corpo, text="Justificativa (obrigatória se houver diferença)")
        self.rotulo_motivo.grid(row=linha + 1, column=0, columnspan=4, sticky="w")
        self.motivo = ttk.Entry(corpo, width=75)
        self.motivo.grid(row=linha + 2, column=0, columnspan=4, sticky="ew")
        self.mensagem = ttk.Label(corpo, text="", wraplength=650)
        self.mensagem.grid(row=linha + 3, column=0, columnspan=4, sticky="w", pady=8)
        barra = ttk.Frame(corpo)
        barra.grid(row=linha + 4, column=0, columnspan=4, sticky="e")
        ttk.Button(barra, text="Conferir", command=self.conferir).pack(side="left", padx=4)
        self.btn_aceitar = ttk.Button(barra, text="Usar declaração", command=self.aceitar, state="disabled")
        self.btn_aceitar.pack(side="left", padx=4)
        ttk.Button(barra, text="Cancelar", command=self.destroy).pack(side="left", padx=4)
        self.bind("<Escape>", lambda _e: self.destroy())

    def _comparar(self):
        if self.ctx.operador_id != self.operador_id:
            raise ErroNegocio("O operador mudou. Cancele e inicie novamente a conferência.")
        valores = {}
        for forma in self.formas:
            texto = self.campos[forma["tipo_id"]].get().strip()
            if not texto or not any(c.isdigit() for c in texto):
                raise ErroNegocio(f"Informe o valor de {forma['tipo']}, inclusive zero.")
            valores[forma["tipo_id"]] = fmt.para_centavos(texto)
        previa = self.ctx.turnos.conferencia_fechamento(
            self.turno_id, self.operador_id, self.valor_final_cent, informados_por_forma=valores)
        return valores, previa

    def _mostrar(self, previa):
        self.previa = previa
        for linha in previa["linhas"]:
            self.esperados[linha["tipo_id"]].configure(text=fmt.fmt_brl(linha["esperado_cent"]))
            self.diferencas[linha["tipo_id"]].configure(text=fmt.fmt_brl(linha["diferenca_cent"]))
        g = previa["gaveta"]
        self.gaveta.configure(text=f"Gaveta: esperado {fmt.fmt_brl(g['esperado_cent'])} / "
                             f"informado {fmt.fmt_brl(g['informado_cent'])} / diferença {fmt.fmt_brl(g['diferenca_cent'])}")
        self.mensagem.configure(text="Há diferença: justifique para continuar." if previa["tem_diferenca"]
                                else "Valores conferidos. Confirme para usar esta declaração.")
        self.btn_aceitar.configure(state="normal")

    def conferir(self):
        try:
            _, previa = self._comparar()
            self._mostrar(previa)
            return True
        except (ErroNegocio, ValueError, OverflowError) as erro:
            self.previa = None
            self.btn_aceitar.configure(state="disabled")
            self.mensagem.configure(text=str(erro))
            return False

    def aceitar(self):
        try:
            valores, previa = self._comparar()
            if self.previa != previa:
                self._mostrar(previa)
                self.mensagem.configure(text="A conferência mudou. Revise os valores e confirme novamente.")
                return False
            motivo = self.motivo.get().strip()
            if previa["tem_diferenca"] and not motivo:
                raise ErroNegocio("Informe a justificativa obrigatória da diferença.")
            self.resultado = {"informados_por_forma": valores, "justificativa": motivo}
            self.destroy()
            return True
        except (ErroNegocio, ValueError, OverflowError) as erro:
            self.mensagem.configure(text=str(erro))
            return False


def coletar(master, ctx, turno_id: int, valor_final_cent: int) -> dict | None:
    dialogo = DialogoFechamento(master, ctx, turno_id, valor_final_cent)
    dialogo.grab_set()
    master.wait_window(dialogo)
    return dialogo.resultado
