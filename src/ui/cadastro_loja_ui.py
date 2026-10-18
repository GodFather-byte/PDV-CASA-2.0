"""Cadastro da casa no primeiro uso: enquanto o nome estiver em branco, os comprovantes saem com "PDV" no cabeçalho.
A janela aparece para quem pode mexer nos dados da loja até o nome ser informado."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.controllers.perfil_controller import PERFIS
from src.core.erros import ErroNegocio
from src.ui import tema

CAMPOS = [("nome_fantasia", "Nome da casa (sai nos comprovantes) *"), ("razao_social", "Razão social"), ("cnpj", "CNPJ"),
          ("endereco", "Endereço"), ("bairro", "Bairro"), ("cidade", "Cidade"), ("uf", "UF"), ("telefone", "Telefone")]


def pedir(master, ctx) -> bool:
    """Mostra o cadastro. Devolve True se a casa foi cadastrada."""
    dlg = tema.Dialogo(master, "Cadastro da casa")
    ttk.Label(dlg.corpo, text="Bem-vindo! Cadastre os dados da sua casa.", style="Rotulo.TLabel").grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(dlg.corpo, text="O nome aparece no cabeçalho dos cupons, dos comprovantes e do fechamento do caixa.\n"
                              "Os outros dados podem ser completados depois em Configurações > Loja.",
              foreground=tema.COR["suave"]).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
    atual = ctx.config.loja()
    variaveis: dict[str, tk.StringVar] = {}
    entradas = []
    for i, (chave, rotulo) in enumerate(CAMPOS, start=2):
        ttk.Label(dlg.corpo, text=rotulo).grid(row=i, column=0, sticky="w", pady=2)
        variaveis[chave] = tk.StringVar(dlg, value=atual.get(chave) or "")
        e = ttk.Entry(dlg.corpo, textvariable=variaveis[chave], width=40)
        e.grid(row=i, column=1, sticky="w", padx=(10, 0), pady=2)
        entradas.append(e)
    linha = len(CAMPOS) + 2
    perfis = {nome: chave for chave, (nome, _, _) in PERFIS.items()}
    var_perfil = None
    if ctx.acesso.pode(ctx.operador, "cfg_configuracoes"):     # o perfil muda as Configurações: só quem pode mexer nelas
        ttk.Label(dlg.corpo, text="Tipo de negócio").grid(row=linha, column=0, sticky="w", pady=(8, 2))
        var_perfil = tk.StringVar(dlg, value=PERFIS[ctx.perfil.atual()][0])
        ttk.Combobox(dlg.corpo, textvariable=var_perfil, values=list(perfis), state="readonly", width=38).grid(
            row=linha, column=1, sticky="w", padx=(10, 0), pady=(8, 2))
        ttk.Label(dlg.corpo, text="Liga os recursos certos para o seu tipo de negócio (dá para trocar depois em Configurações).",
                  foreground=tema.COR["suave"]).grid(row=linha + 1, column=0, columnspan=2, sticky="w")
        linha += 2
    msg = ttk.Label(dlg.corpo, text="", foreground=tema.COR["perigo"])
    msg.grid(row=linha, column=0, columnspan=2, sticky="w")

    def gravar(_=None):
        try:
            with ctx.banco.transacao():
                ctx.config.cadastrar_loja({k: v.get() for k, v in variaveis.items()})
                if var_perfil is not None:
                    ctx.perfil.aplicar(perfis[var_perfil.get()])
        except ErroNegocio as e:
            msg.configure(text=str(e))
            entradas[0].focus_set()
            return
        dlg.ok(True)
    barra = ttk.Frame(dlg.corpo)
    barra.grid(row=linha + 1, column=0, columnspan=2, sticky="e", pady=(10, 0))
    ttk.Button(barra, text="Depois", command=dlg.cancelar).pack(side="right")
    ttk.Button(barra, text="Gravar", style="Ok.TButton", command=gravar).pack(side="right", padx=(0, 8))
    dlg.bind("<Return>", gravar)
    return bool(dlg.mostrar(entradas[0]))
