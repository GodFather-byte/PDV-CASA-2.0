"""Seletor de impressora: lista o que este computador enxerga em vez de o operador digitar o nome.

Mostra as impressoras instaladas no Windows (as que parecem de cupom primeiro) e as portas COM. Dá para imprimir uma
página de teste na linha escolhida antes de usá-la. A janela não grava nada: devolve (conexão, endereço) a quem a abriu.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.hardware import impressoras_so
from src.ui import tema

TITULOS = {"termica": "Impressora do caixa", "remota": "Impressora da cozinha/bar"}


class JanelaEscolherImpressora(tk.Toplevel):
    """`alvo`: 'termica' (caixa: impressoras do Windows e portas COM) ou 'remota' (cozinha/bar: só impressoras do Windows).
    `ao_escolher(conexao, endereco)` recebe ('spooler', nome da impressora) ou ('serial', 'COM3')."""

    def __init__(self, master, ctx, alvo: str, ao_escolher):
        super().__init__(master)
        self.ctx, self.alvo, self.ao_escolher = ctx, alvo, ao_escolher
        self.itens: dict[str, dict] = {}
        self.title(f"Impressoras deste computador - {TITULOS.get(alvo, alvo)}")
        self.configure(bg=tema.COR["fundo"])
        self.geometry("980x540")
        self.minsize(760, 380)
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)
        # Rodapé e dica são empacotados primeiro: numa janela baixa a lista encolhe, os botões nunca somem.
        barra = ttk.Frame(corpo)
        barra.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Label(corpo, wraplength=920, foreground=tema.COR["suave"], text=(
            "Não apareceu a sua? Instale o driver da impressora no Windows (Painel de Controle, Dispositivos e Impressoras), "
            "ligue o cabo e clique em Atualizar. Para impressora de rede sem driver, volte e escolha Rede (TCP/IP) com o IP dela."
        )).pack(side="bottom", anchor="w", pady=(8, 0))
        self.lbl = ttk.Label(corpo, text="", wraplength=920, font=tema.FONTE_B)
        self.lbl.pack(side="top", anchor="w", pady=(0, 6))
        self.grade = tema.Grade(corpo, [("tipo", "Tipo", 150, "w"), ("nome", "Nome", 250, "w"), ("detalhe", "Porta e driver", 330, "w"),
                                        ("situacao", "Situação", 200, "w")], altura=10)
        self.grade.pack(fill="both", expand=True)
        self.grade.tag("termica", foreground=tema.COR["ok"])
        self.grade.tag("virtual", foreground=tema.COR["virtual"])
        self.grade.tag("problema", foreground=tema.COR["perigo"])
        self.grade.tree.bind("<Double-1>", lambda e: self.usar())
        self.grade.tree.bind("<Return>", lambda e: self.usar())
        ttk.Button(barra, text="Usar esta", style="Ok.TButton", command=self.usar).pack(side="left")
        ttk.Button(barra, text="Imprimir página de teste", command=self.testar).pack(side="left", padx=6)
        ttk.Button(barra, text="Atualizar (F5)", command=self.atualizar).pack(side="left")
        ttk.Button(barra, text="Fechar (Esc)", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<F5>", lambda e: self.atualizar())
        self.atualizar()
        tema.centralizar(self, master.winfo_toplevel())
        self.transient(master.winfo_toplevel())
        self.grade.tree.focus_set()

    # ------------------------------------------------------------------ lista
    def atualizar(self) -> None:
        self.itens.clear()
        linhas, ids, tags = [], [], []
        for n, i in enumerate(impressoras_so.listar_impressoras()):
            if i.virtual:
                tipo, marca = "PDF ou fax (virtual)", "virtual"
            elif i.termica_provavel:
                tipo, marca = "Cupom (térmica)", "termica"
            else:
                tipo, marca = "Impressora", ""
            if not i.pronta and not i.virtual:
                marca = "problema"
            chave = f"imp:{n}"
            self.itens[chave] = {"conexao": "spooler", "endereco": i.nome, "virtual": i.virtual, "nome": i.nome}
            detalhe = " · ".join(x for x in (i.porta, i.driver) if x)
            linhas.append([tipo, i.nome + ("  (padrão do Windows)" if i.padrao else ""), detalhe, i.situacao])
            ids.append(chave)
            tags.append((marca,) if marca else ())
        if self.alvo == "termica":
            for n, p in enumerate(impressoras_so.listar_portas_seriais()):
                chave = f"com:{n}"
                self.itens[chave] = {"conexao": "serial", "endereco": p.porta, "virtual": False, "nome": p.porta}
                linhas.append(["Porta serial", p.porta, p.descricao, ""])
                ids.append(chave)
                tags.append(())
        self.grade.preencher(linhas, ids, tags)
        if ids:
            primeiro_cupom = next((c for c, t in zip(ids, tags) if t == ("termica",)), ids[0])
            self.grade.selecionar(primeiro_cupom)
            achadas = sum(1 for c in ids if c.startswith("imp:"))
            self.lbl.configure(text=f"{achadas} impressora(s) neste computador. Escolha a do "
                                    f"{'caixa' if self.alvo == 'termica' else 'bar ou cozinha'} e clique em Usar esta.",
                               foreground=tema.COR["titulo"])
        else:
            self.lbl.configure(text="Nenhuma impressora encontrada neste computador.", foreground=tema.COR["perigo"])

    def _escolhida(self) -> dict | None:
        chave = self.grade.selecionado()
        if chave is None or chave not in self.itens:
            tema.aviso(self, "Escolha uma linha da lista.")
            return None
        return self.itens[chave]

    # ------------------------------------------------------------------ ações
    def usar(self) -> None:
        item = self._escolhida()
        if item is None:
            return
        if item["virtual"] and not tema.confirmar(
                self, f"'{item['nome']}' é uma impressora virtual (PDF ou fax) e não imprime cupom no papel.\nUsar mesmo assim?",
                "Impressora virtual", padrao_sim=False):
            return
        escolha = (item["conexao"], item["endereco"])
        self.destroy()
        self.ao_escolher(*escolha)

    def testar(self) -> None:
        item = self._escolhida()
        if item is None:
            return
        if item["virtual"]:
            tema.aviso(self, "Esta é uma impressora virtual (PDF ou fax): o teste não sairia no papel.")
            return
        ok, _ = tema.tratar(self, self.ctx.impressao.imprimir_teste,
                            self.ctx.impressao.impressora_de(item["conexao"], item["endereco"]))
        if ok:
            tema.mensagem(self, f"Página de teste enviada para '{item['nome']}'.\n"
                                "Se ela saiu certa (acentos e corte), clique em Usar esta.", "Teste de impressão")
