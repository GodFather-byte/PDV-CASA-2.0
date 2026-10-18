"""Janela "Atualização disponível": as notas das versões novas, o link para baixar e, se não for crítica, a opção de não
avisar mais desta versão."""
from __future__ import annotations

import webbrowser
from tkinter import ttk

from src.sync import atualizacoes
from src.ui import tema


def texto_faixa(aviso: dict) -> str:
    if aviso["critica"]:
        return f"⚠ ATUALIZAÇÃO IMPORTANTE: versão {aviso['ultima']} (clique para ver)"
    return f"Nova versão {aviso['ultima']} disponível (clique para ver)"


def mostrar(master, banco, aviso: dict) -> str | None:
    """Abre a janela. Devolve 'baixar', 'dispensar' ou None (fechou)."""
    dlg = tema.Dialogo(master, "Atualização disponível")
    titulo = (f"Versão {aviso['ultima']} disponível. Você usa a {aviso['versao_instalada']}."
              + ("\nEsta atualização é IMPORTANTE: corrige problemas de dinheiro ou de dados." if aviso["critica"] else ""))
    ttk.Label(dlg.corpo, text=titulo, style="Rotulo.TLabel", wraplength=480, justify="left",
              foreground=tema.COR["perigo"] if aviso["critica"] else tema.COR["texto"]).pack(anchor="w")
    for v in aviso["versoes"][:5]:
        ttk.Label(dlg.corpo, text=f"Versão {v['versao']}{' (importante)' if v.get('critica') else ''}",
                  style="Rotulo.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Label(dlg.corpo, text=str(v.get("notas") or ""), wraplength=480, justify="left").pack(anchor="w")
    if not aviso.get("url_download"):
        ttk.Label(dlg.corpo, text="Peça o arquivo da atualização ao fornecedor do sistema.", wraplength=480).pack(
            anchor="w", pady=(10, 0))

    barra = ttk.Frame(dlg.corpo)
    barra.pack(fill="x", pady=(14, 0))
    ttk.Button(barra, text="Fechar", command=dlg.cancelar).pack(side="right")
    if not aviso["critica"]:
        ttk.Button(barra, text="Não avisar desta versão", command=lambda: dlg.ok("dispensar")).pack(side="right", padx=(0, 8))
    if aviso.get("url_download"):
        ttk.Button(barra, text="Baixar a atualização", command=lambda: dlg.ok("baixar")).pack(side="right", padx=(0, 8))
    escolha = dlg.mostrar()
    if escolha == "baixar":
        webbrowser.open(aviso["url_download"])
    elif escolha == "dispensar":
        atualizacoes.dispensar(banco, aviso)
    return escolha
