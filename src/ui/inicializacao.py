"""Antes da janela principal: instância única, restauração marcada e checagem de integridade do banco.

Usa um Tk escondido só para as perguntas; a lógica está em src/database/protecao.py e src/core/instancia.py (testadas
sem tela). Qualquer coisa que dê errado aqui é registrada e nunca impede o PDV de abrir sem necessidade.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from src.core import registro
from src.core.instancia import InstanciaUnica
from src.database import protecao
from src.database.conexao import caminho_padrao


def iniciar() -> InstanciaUnica | None:
    """Prepara tudo para abrir o PDV. Devolve a trava da instância (guardar até sair) ou None se não deve abrir."""
    registro.configurar_logs()
    caminho = caminho_padrao()
    raiz = tk.Tk()
    raiz.withdraw()
    try:
        trava = InstanciaUnica(caminho)
        if not trava.adquirir():
            messagebox.showwarning("WillPDV", "O WillPDV já está aberto neste computador.\n"
                                              "Use a janela que já está aberta (veja a barra de tarefas).")
            return None
        resultado = protecao.preparar_banco(caminho, lambda t, m: messagebox.askyesno(t, m, icon="warning"))
        if resultado == "restaurado":
            messagebox.showinfo("WillPDV", "Backup restaurado. O programa vai abrir com os dados dele.")
        elif resultado == "cancelado":
            trava.liberar()
            return None
        return trava
    finally:
        raiz.destroy()
