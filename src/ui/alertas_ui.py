"""Painel de alertas operacionais (Tk): estoque, mesas paradas, entregas, filas e integrações, só do banco local.

Abrir: `abrir(master, ctx)` devolve a janela (ou levanta ErroPermissão antes de criá-la). Ao reabrir uma instância já
existente, o menu chama `exigir_acesso()`, que reconsulta o operador e recorta as seções permitidas.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.controllers.alertas_controller import CATEGORIAS, ROTULO_NIVEL, AlertasController
from src.core.erros import ErroPermissao
from src.ui import tema

ROTULO_SECAO = {"estoque": "estoque (Relatórios de estoque)", "operacao": "operação (Relatórios informativos)"}


class JanelaAlertas(tk.Toplevel):
    def __init__(self, master, ctx):
        self.ctx = ctx
        self.alertas = AlertasController(ctx.banco)
        self.secoes = self.alertas.exigir_secoes(ctx.operador_id)   # sem permissão nenhuma, nem cria a janela
        super().__init__(master)
        self.title("Alertas da casa")
        self.configure(bg=tema.COR["fundo"])
        self.geometry("1000x540")
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)
        self.lbl = ttk.Label(corpo, text="", font=tema.FONTE_B)
        self.lbl.pack(anchor="w", pady=(0, 4))
        self.lbl_secoes = ttk.Label(corpo, text="", foreground=tema.COR["suave"], wraplength=960)
        self.lbl_secoes.pack(anchor="w", pady=(0, 8))
        self.grade = tema.Grade(corpo, [("nivel", "Nível", 100, "w"), ("cat", "Área", 130, "w"),
                                        ("titulo", "Alerta", 360, "w"), ("detalhe", "Detalhe", 380, "w")], altura=16)
        self.grade.pack(fill="both", expand=True)
        self.grade.tag("critico", foreground=tema.COR["perigo"])
        self.grade.tag("aviso", foreground=tema.COR["aviso"])
        self.grade.tag("info", foreground=tema.COR["suave"])
        barra = ttk.Frame(corpo)
        barra.pack(fill="x", pady=(10, 0))
        ttk.Button(barra, text="Atualizar (F5)", command=self.atualizar).pack(side="left")
        ttk.Button(barra, text="Fechar (Esc)", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<F5>", lambda e: self.atualizar())
        self.atualizar()
        tema.centralizar(self, master.winfo_toplevel())
        self.transient(master.winfo_toplevel())

    def exigir_acesso(self) -> set[str]:
        """Reconsulta o operador no banco: recorta as seções permitidas e atualiza; sem nenhuma, limpa e levanta."""
        secoes = self.alertas.secoes_permitidas(self.ctx.operador_id)
        self.secoes = secoes
        if not secoes:
            self._limpar("Acesso aos alertas não permitido para o operador atual.")
            raise ErroPermissao("Seu nível de acesso não permite ver os alertas (relatórios de estoque ou informativos).")
        self._preencher()
        return secoes

    def atualizar(self) -> None:
        try:
            self.exigir_acesso()
        except ErroPermissao:
            pass

    def _limpar(self, texto: str) -> None:
        self.grade.limpar()
        self.lbl.configure(text=texto, foreground=tema.COR["perigo"])
        self.lbl_secoes.configure(text="")

    def _preencher(self) -> None:
        lista = self.alertas.alertas(self.secoes)
        self.grade.preencher([[ROTULO_NIVEL[a["nivel"]], CATEGORIAS[a["categoria"]], a["titulo"], a["detalhe"]] for a in lista],
                             list(range(len(lista))), [(a["nivel"],) for a in lista])
        c = self.alertas.contagem(lista)
        if not lista:
            self.lbl.configure(text="Nenhum alerta agora.", foreground=tema.COR["ok"])
        else:
            cor = tema.COR["perigo"] if c["critico"] else tema.COR["aviso"] if c["aviso"] else tema.COR["suave"]
            self.lbl.configure(text=f"{c['critico']} crítico(s), {c['aviso']} de atenção, {c['info']} informativo(s)",
                               foreground=cor)
        vistas = ", ".join(ROTULO_SECAO[s] for s in sorted(self.secoes))
        ocultas = [ROTULO_SECAO[s] for s in sorted(set(ROTULO_SECAO) - self.secoes)]
        self.lbl_secoes.configure(text=f"Mostrando: {vistas}." + (f" Sem permissão para: {', '.join(ocultas)}." if ocultas else "")
                                  + " Consulta só leitura do banco deste caixa; atualização manual.")


def abrir(master, ctx) -> JanelaAlertas:
    return JanelaAlertas(master, ctx)
