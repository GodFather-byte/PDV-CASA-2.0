"""Tela do Caixa (manual do Caixa). Operação por teclado:

  código + Enter -> quantidade + Enter     Enter com código vazio -> barra de tarefas (setas + Enter)
  6*código + Enter (ou 6* e o leitor) -> lança 6 de uma vez, sem perguntar a quantidade
  Esc -> lista de mesas e comandas         Delete na grade -> cancela item        O -> observação do item
  F2 balança  F3 leitor  F4 mesa/comanda  F5 caderneta  F6 entrega  F7 sangria  F8 pré-conta  F9 repique
  F10 transferir  F11 gaveta  F12 pagar      (F5 e F6 só com a Caderneta e o Delivery ligados em Configurações > Módulos)

Comanda e mesa: no campo da posição digite o número da comanda (ex.: 123) ou M e o número da mesa (ex.: M5). Com
`posicao_padrao = mesa` é o contrário: 5 é a mesa e C2 a comanda. C2 e M5 também valem direto no campo do código.

Comissão das garotas, sem sair desta tela: o código 50 troca a linha de entrada para "Garota nº" e "Valor (R$)" (Enter
confirma e imprime a via da garota; Esc cancela). Na comanda da garota, F12 paga o que está marcado e Delete cancela a
linha selecionada. As garotas com comissão a pagar ganham um cartão no painel de comandas, à esquerda.

Três colunas: o painel de comandas (cartões, busca e abas), a venda atual e o total com as ações. PgUp/PgDn (ou ◀ ▶) passam
pela comanda anterior/seguinte da lista do painel; Enter ou duplo clique numa linha abre as ações dela.
"""
from __future__ import annotations

import base64
import math
import re
import tkinter as tk
from tkinter import ttk

from src.controllers.produto_controller import ProdutoController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.core.identidade_visual import preview_logotipo
from src.core.posicao import nome as nome_posicao
from src.core.posicao import exemplos, parece_posicao, rotulo_do_campo
from src.hardware.dispositivos import DispositivoIndisponivel
from src.hardware.impressora_termica import ErroImpressao
from src.ui import adega_dialogos, cadastro_rapido_ui, caixa_dialogos, caixa_tema, comissao_ui, tema
from src.ui.caixa_pagamento import JanelaPagamento
from src.ui.caixa_tema import CX, FONTE
from src.ui.clientes_ui import JanelaClientes, JanelaEntregas
from src.ui.comissao_ui import JanelaComissoes
from src.ui.fila_impressao_ui import JanelaFilaImpressao
from src.ui.menu_widgets import misturar
from src.ui.painel_mesas import PainelMesas
from src.ui.visualizador import Visualizador, enviar_ou_mostrar

LARGURAS_LADO = {3: 372, 2: 350, 1: 310}     # coluna da direita (total e ações), pelo nº de colunas de cartões do painel
LARGURA_MINIMA_CENTRO = {3: 560, 2: 540, 1: 380}   # o que a venda atual precisa para os campos não ficarem espremidos
QTD_ANTES_DO_CODIGO = re.compile(r"(\d+(?:[.,]\d+)?)\s*\*\s*(\S.*)")   # "6*7891234567890": a quantidade vem antes do código


def _qtd_curta(q) -> str:
    """Quantidade sem zeros sobrando: 5 -> "5", 0,25 -> "0,25"."""
    return fmt.fmt_qtd(q, 3).rstrip("0").rstrip(",")


class _RotuloComDica(ttk.Label):
    """Rótulo que mostra um texto-guia apagado enquanto o texto dele está vazio (o `text` real continua sendo '')."""

    def __init__(self, master, dica: str, **kw):
        super().__init__(master, **kw)
        self._dica = tk.Label(self, text=dica, bg=CX["cartao"], fg=CX["mudo"], font=(FONTE, 12), anchor="w")
        self._pintar_dica()

    def _pintar_dica(self) -> None:
        if str(self.cget("text")):
            self._dica.place_forget()
        else:
            self._dica.place(x=0, rely=0.5, anchor="w")

    def configure(self, cnf=None, **kw):
        resultado = super().configure(cnf, **kw)
        if "text" in kw or (isinstance(cnf, dict) and "text" in cnf):
            self._pintar_dica()
        return resultado

    config = configure


class JanelaCaixa(tk.Toplevel):
    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx = ctx
        self.venda_id: int | None = None
        self.produto: dict | None = None
        self.modo_cancelar = False
        self.mesas_visiveis = False
        self.com_mesas = ctx.banco.cfg_bool("usar_mesas", True)        # desligado: só balcão (adega, comércio)
        self.perfil_adega = ctx.banco.cfg("perfil_operacao", "") == "adega"
        self.painel_fixo = self.com_mesas and ctx.banco.cfg_bool("painel_mesas_fixo", True)
        self._subgrupo_rapido: int | None = None                       # a categoria do último produto cadastrado na hora
        self.indice_barra: int | None = None
        self.comissao_marcada: list[dict] = []     # comissões marcadas na comanda da tela (só se for comanda de garota)
        self._itens_na_grade = 0                   # quantas linhas da lista são itens da venda (o resto é comissão)
        self.modo_comissao = False                 # a linha de entrada está lançando comissão (garota nº + valor), não produto
        self.leitor = bool(ctx.config.maquina()["leitor_optico"])
        self.title(f"Caixa - {ctx.config.nome_loja()}")
        self.configure(bg=CX["fundo"])
        # O painel de comandas ganha 3 colunas de cartões em tela larga, 2 em notebook e 1 em tela pequena; a coluna da direita
        # e o tamanho inicial da janela acompanham, para tudo caber mesmo se o "maximizar" falhar.
        tela = self.winfo_screenwidth()
        self.compacto = tela < 1250                    # tela pequena: campos e colunas laterais mais estreitos
        self.colunas_painel = 3 if tela >= 1500 else 2 if tela >= 1250 else 1
        self.largura_lado = LARGURAS_LADO[self.colunas_painel]
        largura_inicial = ((self.colunas_painel * PainelMesas.LARGURA_CARTAO + PainelMesas.RESERVA) + self.largura_lado
                           + LARGURA_MINIMA_CENTRO[self.colunas_painel] + 64)
        self.geometry(f"{min(max(1180, largura_inicial), tela - 16)}x{min(740, self.winfo_screenheight() - 90)}")
        self.protocol("WM_DELETE_WINDOW", self.sair)
        self.withdraw()
        if ctx.turnos.atual() is None and not caixa_dialogos.abrir_turno(self, ctx):
            self.destroy()
            return
        self._montar()
        self.venda_id = ctx.banco.valor(   # retoma a venda de balcão interrompida (queda de energia, saída do caixa)
            "SELECT id FROM vendas WHERE modalidade = 'balcao' AND status = 'aberta' ORDER BY id DESC LIMIT 1")
        self.deiconify()
        try:
            self.state("zoomed")      # depois de mostrar: antes disso o withdraw() desfaz o zoom e o rodapé fica fora da tela
        except tk.TclError:
            pass
        self.lift()
        self.focus_force()
        self.recarregar()
        self.ent_codigo.focus_set()
        self._relogio()
        self._id_lista = self.after(30000, self._atualizar_painel)

    # ================================================================ layout
    def _montar(self) -> None:
        caixa_tema.aplicar(self)
        self.configure(bg=CX["fundo"])
        self._cabecalho()
        # o rodapé é empacotado antes do corpo: em tela pequena o corpo encolhe, a barra de estado não some
        self.status = ttk.Label(self, text="", style="Cx.Status.TLabel", padding=(16, 6))
        self.status.pack(fill="x", side="bottom")
        corpo = self.corpo = tk.Frame(self, bg=CX["fundo"])
        corpo.pack(fill="both", expand=True, padx=16, pady=(12, 8))
        self._lado_direito(corpo)
        esq = self.esq = tk.Frame(corpo, bg=CX["fundo"])
        esq.pack(side="left", fill="both", expand=True)
        # as comandas ficam numa coluna à esquerda (mostrada por _mostrar_painel); a venda atual, no meio
        self.painel_mesas = PainelMesas(corpo, ao_escolher=self._tile_escolhido, ao_transferir=self.transferir_varias,
                                        ao_voltar=self._painel_voltar, ao_digitar=self._digitar_posicao,
                                        colunas=self.colunas_painel, com_comissoes=self.ctx.comissoes.ligada())

        # --- comanda/mesa e situação da venda: o título, o selo da situação e o campo do número
        linha = tk.Frame(esq, bg=CX["fundo"])
        linha.pack(fill="x")
        quem = tk.Frame(linha, bg=CX["fundo"])
        quem.pack(side="left", fill="y")
        legenda = tk.Frame(quem, bg=CX["fundo"])
        legenda.pack(anchor="w", fill="x")
        ttk.Label(legenda, text="VENDA ATUAL", style="Cx.Rotulo.TLabel").pack(side="left")
        # anterior / próxima comanda da lista (PgUp / PgDn): passa pelas contas dos clientes e das garotas sem voltar ao painel
        self.btn_proxima = ttk.Button(legenda, text="▶", width=2, style="Cx.Mini.TButton", takefocus=False,
                                      command=lambda: self.navegar_comanda(1))
        self.btn_proxima.pack(side="right")
        self.btn_anterior = ttk.Button(legenda, text="◀", width=2, style="Cx.Mini.TButton", takefocus=False,
                                       command=lambda: self.navegar_comanda(-1))
        self.btn_anterior.pack(side="right", padx=(0, 3))
        self.lbl_situacao = ttk.Label(quem, text="Balcão", font=(FONTE, 22, "bold"), style="Cx.TLabel", foreground=CX["azul"])
        self.lbl_situacao.pack(anchor="w")
        if self.com_mesas:
            self.lbl_situacao.bind("<Button-1>", self.nomear_comanda)       # clicar no título dá nome à comanda
            self.lbl_situacao.configure(cursor="hand2")
        bloco = tk.Frame(linha, bg=CX["fundo"])
        bloco.pack(side="right", padx=(12, 0))
        ttk.Label(bloco, text=rotulo_do_campo(self.ctx.caixa.padrao_posicao()), style="Cx.Rotulo.TLabel").pack(anchor="e")
        self.var_pos = tk.StringVar(value="0")
        self.ent_pos = ttk.Entry(bloco, textvariable=self.var_pos, width=7, font=(FONTE, 16, "bold"), justify="center", style="Cx.TEntry")
        self.ent_pos.pack(anchor="e", pady=(2, 0))
        self.lbl_status_venda = tk.Label(linha, text="Balcão", font=(FONTE, 11, "bold"), padx=18, pady=10,
                                         bg=CX["cartao"], fg=CX["verde"], highlightthickness=1, highlightbackground=CX["borda"], highlightcolor=CX["borda"])
        self.lbl_status_venda.pack(side="right")
        self.lbl_leitor = ttk.Label(linha, text="", style="Cx.TLabel", foreground=tema.COR["aviso"], font=(FONTE, 10, "bold"))
        self.lbl_leitor.pack(side="right", anchor="s", padx=(0, 14), pady=(0, 4))
        if not self.com_mesas:          # só balcão: sem o campo da posição nem a troca de comanda
            bloco.pack_forget()
            self.btn_proxima.pack_forget()
            self.btn_anterior.pack_forget()

        self.faixa = tk.Label(esq, text="", font=tema.FONTE_B, fg="white", anchor="w", justify="left", padx=14, pady=6)
        self.faixa.bind("<Configure>", lambda e: self.faixa.configure(wraplength=max(e.width - 30, 200)))

        # --- entrada do item: código, descrição, quantidade e preço
        ent = self.cartao_entrada = tk.Frame(esq, bg=CX["cartao"], highlightthickness=1, highlightbackground=CX["borda"], highlightcolor=CX["borda"], padx=16, pady=12)
        ent.pack(fill="x", pady=(12, 0))
        self.lbl_cod_titulo = ttk.Label(ent, text="Código", style="Cx.CartaoRotulo.TLabel")
        self.lbl_cod_titulo.grid(row=0, column=0, sticky="w")
        self.var_cod = tk.StringVar()
        self.var_cod.trace_add("write", lambda *_: self._comissao_nome() if self.modo_comissao else None)
        self.var_cod.trace_add("write", lambda *_: self._pintar_dica_codigo())
        self.ent_codigo = ttk.Entry(ent, textvariable=self.var_cod, width=10 if self.compacto else 16, font=(FONTE, 18), style="Cx.TEntry")
        self.ent_codigo.grid(row=1, column=0, sticky="w")
        self.dica_codigo = tk.Label(self.ent_codigo, text="Código ou leitor", bg=CX["campo"], fg=CX["mudo"], font=(FONTE, 13))
        self.dica_codigo.bind("<Button-1>", lambda e: self.ent_codigo.focus_set())
        self._pintar_dica_codigo()
        if not self.compacto:        # em tela estreita só o botão Consultar do painel de ações (o espaço é do código e do preço)
            self.btn_consultar = ttk.Button(ent, text="Consultar", style="Cx.TButton", takefocus=False, command=self.consultar)
            self.btn_consultar.grid(row=1, column=1, padx=8)
        ttk.Label(ent, text="Descrição", style="Cx.CartaoRotulo.TLabel").grid(row=0, column=2, sticky="w", padx=(6, 0))
        self.lbl_desc = _RotuloComDica(ent, "Passe o leitor ou digite o código", text="", font=(FONTE, 16, "bold"),
                                       style="Cx.Cartao.TLabel", foreground=CX["texto"], width=10 if self.compacto else 24)
        self.lbl_desc.grid(row=1, column=2, sticky="ew", padx=(6, 10))
        ttk.Label(ent, text="Unidade", style="Cx.CartaoRotulo.TLabel").grid(row=0, column=3, sticky="w")
        self.lbl_un = ttk.Label(ent, text="", font=(FONTE, 12), style="Cx.Cartao.TLabel", width=5)
        self.lbl_un.grid(row=1, column=3, sticky="w")
        self.lbl_qtd_titulo = ttk.Label(ent, text="Quantidade", style="Cx.CartaoRotulo.TLabel")
        self.lbl_qtd_titulo.grid(row=0, column=4, sticky="w")
        self.var_qtd = tk.StringVar()
        self.ent_qtd = ttk.Entry(ent, textvariable=self.var_qtd, width=7 if self.compacto else 9, font=(FONTE, 18), state="disabled", style="Cx.TEntry")
        self.ent_qtd.grid(row=1, column=4, sticky="w", padx=(0, 12))
        ttk.Label(ent, text="Preço", style="Cx.CartaoRotulo.TLabel").grid(row=0, column=5, sticky="w")
        self.lbl_preco = ttk.Label(ent, text="", font=(FONTE, 16, "bold"), style="Cx.Cartao.TLabel", foreground=CX["verde"], width=8)
        self.lbl_preco.grid(row=1, column=5, sticky="w")
        ent.columnconfigure(2, weight=1)
        ent.bind("<Configure>", self._ajustar_entrada)
        if self.perfil_adega:
            self.lbl_oferta = ttk.Label(ent, text="", style="Cx.CartaoRotulo.TLabel", wraplength=600)
            self.lbl_oferta.grid(row=2, column=0, columnspan=6, sticky="w", pady=(10, 0))
            ent.bind("<Configure>", lambda e: self.lbl_oferta.configure(wraplength=max(180, e.width - 32)), add="+")
            self._oferta_adega()

        # --- itens da venda (o código e a unidade ficam guardados, mas fora da vista: a lista é Produto, Preço, Qtd e Total)
        quadro = tk.Frame(esq, bg=CX["fundo"])
        quadro.pack(fill="both", expand=True, pady=(12, 0))
        dica = ("Código + Enter lança  ·  Enter na linha: ações  ·  Delete cancela  ·  O observação  ·  T transfere  ·  PgUp/PgDn troca de comanda  ·  F12 paga"
                if self.com_mesas else
                "Leitor ou código + Enter lança  ·  6* antes do código lança 6  ·  F1 consulta preço  ·  Enter na linha: ações  ·  Delete cancela  ·  F12 paga")
        self.lbl_dica = ttk.Label(esq, text=dica, font=(FONTE, 9), style="Cx.Rotulo.TLabel")
        self.lbl_dica.pack(side="bottom", anchor="w", pady=(8, 0), before=quadro)
        self.grade = tema.Grade(quadro, [("cod", "Código", 150, "w"), ("prod", "Produto", 300, "w"), ("un", "Un", 50, "w"),
                                         ("preco", "Preço", 90, "e"), ("qtd", "Qtd", 90, "e"), ("tot", "Total", 100, "e"),
                                         ("obs", "Observação", 200, "w")], altura=6, estilo="Cx", cor_par=CX["linha_par"])
        self.grade.pack(fill="both", expand=True)
        if self.perfil_adega:
            self.lbl_detalhe_preco = ttk.Label(esq, text="", style="Cx.Rotulo.TLabel", wraplength=600)
            self.lbl_detalhe_preco.pack(fill="x", pady=(4, 0))
            esq.bind("<Configure>", lambda e: self.lbl_detalhe_preco.configure(wraplength=max(180, e.width - 32)), add="+")
            self._detalhes_preco = {}
            self.grade.tree.bind("<<TreeviewSelect>>", lambda e: self._mostrar_detalhe_preco())
        self.grade.tree.bind("<Configure>", self._ajustar_grade)
        self.grade.tag("comissao", foreground=CX["comissao_texto"])       # comissão marcada na comanda da garota: só leitura
        self.grade.tag("comissao_paga", foreground=CX["comissao_paga"])
        self.lbl_vazio = tk.Label(self.grade.tree, text="Nenhum item lançado\nPasse o leitor ou digite o código do produto e tecle Enter",
                                  bg=CX["cartao"], fg=CX["mudo"], font=(FONTE, 13), justify="center")
        if self.perfil_adega:
            self.lbl_vazio.configure(text="Pronto para atender\n\nPasse o leitor ou digite 6*código para lançar 6 unidades.\n"
                                    "Bebida com dois preços? Escolha natural ou gelada.\n"
                                    "Retornável? Informe apenas os cascos que faltam na troca.\n"
                                    "Bebida e casco: cancelamentos independentes; confira as duas linhas.")
            self.grade.tree.bind("<Configure>", lambda e: self.lbl_vazio.configure(wraplength=max(180, e.width - 40)), add="+")

        e = self.ent_codigo
        e.bind("<Return>", self._enter_codigo)
        e.bind("<Escape>", self._esc_codigo)
        e.bind("<Down>", self._baixo_codigo)
        self.ent_qtd.bind("<Return>", lambda ev: self.confirmar_item())
        self.ent_qtd.bind("<Escape>", lambda ev: self.cancelar_item_pendente())
        self.ent_qtd.bind("<Up>", self._cima_valor)
        self.ent_pos.bind("<Return>", lambda ev: self.chamar_mesa())
        self.ent_pos.bind("<Escape>", self._esc_posicao)
        self.ent_pos.bind("<Down>", lambda ev: self.painel_mesas.focar(self._chave_atual()))
        t = self.grade.tree
        t.bind("<Delete>", lambda ev: self.cancelar_item_selecionado())
        t.bind("<Return>", self._enter_grade)
        t.bind("<Double-1>", self._enter_grade)
        t.bind("<Up>", self._cima_grade)
        t.bind("<Prior>", lambda ev: (self.navegar_comanda(-1), "break")[1])
        t.bind("<Next>", lambda ev: (self.navegar_comanda(1), "break")[1])
        t.bind("<Escape>", lambda ev: self._sair_modo_cancelar())
        t.bind("o", lambda ev: self.observacao_item()); t.bind("O", lambda ev: self.observacao_item())
        t.bind("t", lambda ev: self.transferir_item()); t.bind("T", lambda ev: self.transferir_item())
        for tecla, fn in (("F1", self.f1), ("F2", self.balanca), ("F3", self.alternar_leitor), ("F4", self.foco_mesa), ("F5", self.caderneta),
                          ("F6", self.entrega), ("F7", self.sangria), ("F8", self.pre_conta), ("F9", self.repique),
                          ("F10", self.transferir_mesa), ("F11", self.gaveta), ("F12", self.pagar)):
            self.bind(f"<{tecla}>", lambda ev, f=fn: (f(), "break")[1])
            self.opcoes.bind(f"<{tecla}>", lambda ev, f=fn: (self._exec_barra(f), "break")[1])
        self.bind("<Prior>", lambda ev: (self.navegar_comanda(-1), "break")[1])
        self.bind("<Next>", lambda ev: (self.navegar_comanda(1), "break")[1])
        self.bind("<Configure>", self._ao_redimensionar, add="+")
        self.bind("<Left>", lambda ev: self._barra_mover(-1))
        self.bind("<Right>", lambda ev: self._barra_mover(1))
        self.bind("<FocusIn>", self._retomar_atendimento, add="+")
        if self.painel_fixo:
            self._mostrar_painel()

    def _ao_redimensionar(self, evento) -> None:
        """Com a janela menor (ou maior), o painel de comandas ganha ou perde colunas de cartões; a venda atual fica com o resto."""
        if evento.widget is not self or evento.width <= 1:
            return
        espaco = evento.width - self.largura_lado - 64 - 520
        self.painel_mesas.definir_colunas(max(1, min(3, (espaco - PainelMesas.RESERVA) // PainelMesas.LARGURA_CARTAO)))

    def _pintar_dica_codigo(self) -> None:
        """O texto-guia do campo do código some assim que se digita (ou o leitor passa) alguma coisa."""
        if self.var_cod.get():
            self.dica_codigo.place_forget()
        else:
            self.dica_codigo.place(x=8, rely=0.5, anchor="w")

    def _ajustar_entrada(self, evento) -> None:
        """Encolhe os campos ao redimensionar a janela, mantendo a descrição e o preço à vista."""
        estreita = evento.width < 760
        self.ent_codigo.configure(width=11 if estreita else 16, font=(FONTE, 14 if estreita else 18))
        self.dica_codigo.configure(font=(FONTE, 11 if estreita else 13))
        self.lbl_desc._dica.configure(font=(FONTE, 11 if estreita else 12))
        self.ent_qtd.configure(width=6 if estreita else 9, font=(FONTE, 14 if estreita else 18))
        self.lbl_desc.configure(width=1, font=(FONTE, 12 if estreita else 16, "bold"))
        self.lbl_preco.configure(font=(FONTE, 12 if estreita else 16, "bold"))
        if hasattr(self, "btn_consultar"):
            self.btn_consultar.grid_remove() if estreita else self.btn_consultar.grid()
        self.lbl_dica.configure(wraplength=max(evento.width - 40, 200))

    def _ajustar_grade(self, evento) -> None:
        estreita = evento.width < 850
        if getattr(self, "_grade_estreita", None) == estreita:
            return
        self._grade_estreita = estreita
        self.grade.tree.configure(displaycolumns=("prod", "preco", "qtd", "tot") if estreita else ("prod", "preco", "qtd", "tot", "obs"))
        larguras = (130, 220, 35, 80, 60, 90, 120) if estreita else (150, 380, 50, 100, 80, 110, 220)
        for coluna, largura in zip(("cod", "prod", "un", "preco", "qtd", "tot", "obs"), larguras):
            self.grade.tree.column(coluna, width=largura)

    def _cabecalho(self) -> None:
        topo = tk.Frame(self, bg=CX["cabecalho"], padx=20, pady=10)
        topo.pack(fill="x")
        self.slot_sair = tk.Frame(topo, bg=CX["cabecalho"])
        self.slot_sair.pack(side="right", padx=(18, 0))
        nome = self.ctx.config.nome_loja().upper()
        dados_logo = preview_logotipo(self.ctx.config.loja().get("logotipo"), (64, 48))
        self._foto_logo = tk.PhotoImage(master=self, data=base64.b64encode(dados_logo)) if dados_logo else None
        if self._foto_logo:
            tk.Label(topo, image=self._foto_logo, bg=CX["cabecalho"]).pack(side="left")
        else:
            tk.Label(topo, text=(nome[:1] or "W"), bg=CX["azul"], fg=CX["sobre_marca"], font=(FONTE, 15, "bold"), width=2).pack(side="left")
        titulos = tk.Frame(topo, bg=CX["cabecalho"])
        titulos.pack(side="left", padx=(12, 0))
        tk.Label(titulos, text="CAIXA", bg=CX["cabecalho"], fg=CX["suave"], font=(FONTE, 8, "bold")).pack(anchor="w")
        self.lbl_loja = tk.Label(titulos, text=nome, bg=CX["cabecalho"], fg=CX["texto"], font=(FONTE, 15, "bold"))
        self.lbl_loja.pack(anchor="w")
        # os indicadores do turno, da direita para a esquerda: turno e hora, o que está em aberto, acertos e posições abertas
        self.lbl_turno, self.lbl_hora = self._indicador(topo, "TURNO", CX["texto"])
        self.lbl_aberto_casa = self._indicador(topo, "EM ABERTO NA CASA", CX["verde"])[1]
        self.lbl_acertos = self._indicador(topo, "AGUARD. ACERTO", CX["ambar"])[1]
        self.lbl_abertas = self._indicador(topo, "ABERTAS", CX["texto"])[1]
        if not self.com_mesas:          # balcão: não há mesas nem comandas abertas para contar
            for lbl in (self.lbl_aberto_casa, self.lbl_acertos, self.lbl_abertas):
                lbl.master.pack_forget()
        self.lbl_fila = tk.Label(topo, bg=CX["cabecalho"], fg=CX["verde"], font=tema.FONTE_B, cursor="hand2")
        self.lbl_fila.pack(side="right", padx=(0, 6))
        self.lbl_fila.bind("<Button-1>", lambda e: self.abrir_fila())
        tk.Frame(self, height=1, bg=CX["borda"]).pack(fill="x")

    def _indicador(self, pai, titulo: str, cor: str) -> tuple[tk.Label, tk.Label]:
        """Um indicador do cabeçalho (título pequeno e valor em destaque). Devolve (rótulo do título, rótulo do valor)."""
        quadro = tk.Frame(pai, bg=CX["cartao"], highlightthickness=1, highlightbackground=CX["borda"], highlightcolor=CX["borda"], padx=14, pady=5)
        quadro.pack(side="right", padx=(8, 0))
        lbl_titulo = tk.Label(quadro, text=titulo, bg=CX["cartao"], fg=CX["suave"], font=(FONTE, 8, "bold"))
        lbl_titulo.pack(anchor="w")
        lbl_valor = tk.Label(quadro, text="0", bg=CX["cartao"], fg=cor, font=(FONTE, 14, "bold"))
        lbl_valor.pack(anchor="w")
        return lbl_titulo, lbl_valor

    def _lado_direito(self, corpo) -> None:
        """Coluna da direita: o total em destaque, o botão Pagar e as ações do dia a dia, em duas colunas."""
        lado = tk.Frame(corpo, bg=CX["fundo"], width=self.largura_lado)
        lado.pack(side="right", fill="y", padx=(16, 0))
        lado.pack_propagate(False)
        cartao = tk.Frame(lado, bg=CX["cartao"], highlightthickness=1, highlightbackground=CX["borda"], highlightcolor=CX["borda"])
        cartao.pack(fill="x")
        tk.Frame(cartao, height=3, bg=CX["verde"]).pack(fill="x")
        dentro = tk.Frame(cartao, bg=CX["cartao"], padx=16, pady=10)
        dentro.pack(fill="x")
        tk.Label(dentro, text="TOTAL A PAGAR", bg=CX["cartao"], fg=CX["suave"], font=(FONTE, 9, "bold")).pack(anchor="w")
        linha = tk.Frame(dentro, bg=CX["cartao"])
        linha.pack(fill="x")
        tk.Label(linha, text="R$", bg=CX["cartao"], fg=CX["suave"], font=(FONTE, 16, "bold")).pack(side="left", anchor="s", pady=(0, 9))
        self.lbl_total = tk.Label(linha, text="0,00", bg=CX["cartao"], fg=CX["verde"], font=(FONTE, 34, "bold"), anchor="e")
        self.lbl_total.pack(side="right")
        self.lbl_detalhe_total = tk.Label(dentro, text="", bg=CX["cartao"], fg=CX["suave"], font=(FONTE, 10), anchor="w",
                                          justify="left", wraplength=250)
        self.lbl_detalhe_total.pack(fill="x", pady=(4, 0))
        self.lbl_troco = tk.Label(dentro, text="0,00")            # o troco aparece na janela de pagamento; aqui só guarda o valor
        self.lbl_recebido = tk.Label(dentro, text="", bg=CX["cartao"], fg=CX["suave"], font=(FONTE, 10),
                                     wraplength=270, justify="left", anchor="w")
        if self.perfil_adega:
            self.lbl_resumo_adega = tk.Label(dentro, text="", bg=CX["cartao"], fg=CX["texto"],
                                             font=(FONTE, 10), anchor="w", justify="left", wraplength=270)
            self.lbl_resumo_adega.pack(fill="x", pady=(8, 0))
        self.barra = tk.Frame(lado, bg=CX["fundo"])
        self.barra.pack(fill="x", pady=(12, 0))
        self._barra_tarefas()

    def _barra_tarefas(self) -> None:
        principais = [("Pagar (F12)", self.pagar), ("Lançar produto", self.consultar), ("Escolher comanda (F4)", self.foco_mesa)]
        diarias = [("Pré-Conta (F8)", self.pre_conta), ("Transfere (F10)", self.transferir_mesa), ("Repique (F9)", self.repique),
                   ("Comissões", self.comissoes), ("Sangria (F7)", self.sangria), ("Gaveta (F11)", self.gaveta),
                   ("Consulta Comanda", self.consultar_comanda), ("Cancelar", self.menu_cancelar)]
        if not self.ctx.comissoes.ligada():                 # casa sem garotas (perfil do estabelecimento)
            diarias = [d for d in diarias if d[1] != self.comissoes]
        venda = [("Nomear comanda", self.nomear_comanda), ("Delivery (F6)", self.entrega), ("Caderneta (F5)", self.caderneta),
                 ("Rodízio", self.rodizio), ("Recarga", self.recarga)]
        caixa = [("Impressora", self.impressora), ("Balança (F2)", self.balanca), ("Leitor (F3)", self.alternar_leitor),
                 ("Devoluções e trocas", self.abrir_devolucoes),
                 ("Fecha Turno", self.fechar_turno)]
        sair = [("Sair", self.sair)]                       # fica no canto do cabeçalho, longe dos botões de uso diário
        if not self.com_mesas:          # só balcão: sem as ações de mesa e comanda
            so_mesa = {self.foco_mesa, self.pre_conta, self.transferir_mesa, self.repique, self.consultar_comanda,
                       self.nomear_comanda, self.rodizio, self.recarga}
            principais, diarias, venda = ([t for t in lista if t[1] not in so_mesa] for lista in (principais, diarias, venda))
        desligados = {self.entrega: "usar_delivery", self.caderneta: "usar_caderneta",
                      self.rodizio: "usar_rodizio", self.recarga: "usar_prepago"}         # módulos que a casa não usa
        venda = [(r, f) for r, f in venda if f not in desligados or self.ctx.banco.cfg_bool(desligados[f], False)]
        # Os 11 primeiros ficam sempre à vista, na coluna da direita; o resto fica em "Mais opções" (janela à parte).
        self.tarefas = principais + diarias + venda + caixa + sair
        self._n_fixos = len(principais) + len(diarias)
        if self.perfil_adega:
            self._n_fixos += len(venda)  # delivery e fiado à mão, sem abrir "Mais opções"
        self.botoes_tarefa, self._estilos_base = [], []
        self.barra.columnconfigure((0, 1), weight=1, uniform="acoes")
        self.opcoes = tk.Toplevel(self)
        self.opcoes.withdraw()
        self.opcoes.title("Mais opções do caixa")
        self.opcoes.configure(bg=CX["fundo"])
        self.opcoes.resizable(False, False)
        self.opcoes.transient(self)
        self.opcoes.protocol("WM_DELETE_WINDOW", self._sair_barra)
        self.opcoes.bind("<Escape>", self._barra_esc)
        self.opcoes.bind("<Left>", lambda e: self._barra_mover(-1))
        self.opcoes.bind("<Right>", lambda e: self._barra_mover(1))
        self.opcoes.bind("<Return>", self._barra_enter)
        tk.Label(self.opcoes, text="Mais opções", bg=CX["fundo"], fg=CX["texto"], font=(FONTE, 18, "bold")
                 ).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(self.opcoes, text="Setas e Enter escolhem  |  Esc volta ao atendimento", bg=CX["fundo"],
                 fg=CX["suave"], font=(FONTE, 10)).pack(anchor="w", padx=20)
        extras = tk.Frame(self.opcoes, bg=CX["fundo"], padx=18, pady=14)
        extras.pack(fill="both", expand=True)
        extras.columnconfigure((0, 1), weight=1, uniform="acoes")

        def botao(i: int, linha: int, coluna: int, largura: int = 1) -> None:
            rotulo, fn = self.tarefas[i]
            estilo = ("Cx.Pagar.TButton" if i == 0 else "Cx.Perigo.TButton" if fn == self.sair
                      else "Cx.AcaoPerigo.TButton" if fn == self.menu_cancelar
                      else "Cx.Acao.TButton" if i < self._n_fixos else "Cx.TButton")
            pai = self.slot_sair if fn == self.sair else self.barra if i < self._n_fixos else extras
            b = ttk.Button(pai, text=rotulo, style=estilo, takefocus=False,
                           command=lambda f=fn: self._exec_barra(f))
            if fn == self.sair:
                b.pack()
            else:
                b.grid(row=linha, column=coluna, columnspan=largura, padx=3, pady=3, sticky="ew")
            self.botoes_tarefa.append(b)
            self._estilos_base.append(estilo)

        botao(0, 0, 0, 2)                                          # Pagar ocupa a largura toda
        for k in range(1, self._n_fixos):                          # as ações do dia a dia, duas por linha
            botao(k, 1 + (k - 1) // 2, (k - 1) % 2)
        linhas = 1 + (self._n_fixos - 1 + 1) // 2
        self.btn_opcoes = ttk.Button(self.barra, text="Mais opções", style="Cx.TButton", command=self._abrir_opcoes)
        self.btn_opcoes.grid(row=linhas, column=0, columnspan=2, sticky="ew", padx=3, pady=(14, 3))
        dica_opcoes = ("F1 consulta  ·  F3 liga/desliga leitor\nF4 / Esc limpa a entrada  ·  F12 paga"
                       if self.perfil_adega else
                       "Nomear comanda, delivery, caderneta, impressora,\nbalança, leitor e fechamento de turno")
        tk.Label(self.barra, text=dica_opcoes,
                 bg=CX["fundo"], fg=CX["suave"], font=(FONTE, 9), justify="center").grid(row=linhas + 1, column=0, columnspan=2, pady=6)
        linha = 0
        inicio_venda = len(principais) + len(diarias)
        for titulo, qtd, inicio in (("VENDA", 0 if self.perfil_adega else len(venda), inicio_venda),
                                   ("CAIXA", len(caixa), inicio_venda + len(venda))):
            if not qtd:
                continue
            tk.Label(extras, text=titulo, bg=CX["fundo"], fg=CX["suave"], font=(FONTE, 9, "bold"), anchor="w").grid(
                row=linha, column=0, columnspan=2, sticky="w", padx=3, pady=(8, 0))
            linha += 1
            for k in range(qtd):
                botao(inicio + k, linha + k // 2, k % 2)
            linha += (qtd + 1) // 2
        botao(len(self.tarefas) - 1, 0, 0)

    def _mostrar_opcoes(self) -> None:
        self.opcoes.deiconify()
        tema.centralizar(self.opcoes, self)
        self.opcoes.lift()
        self.opcoes.focus_force()

    def _abrir_opcoes(self) -> None:
        self.indice_barra = self._n_fixos
        self._pintar_barra()

    def _ocultar_opcoes(self) -> None:
        if hasattr(self, "opcoes"):
            self.opcoes.withdraw()

    def _retomar_atendimento(self, _=None) -> None:
        foco = self.focus_get()
        if self.opcoes.winfo_viewable() and foco is not None and foco.winfo_toplevel() is self:
            self.indice_barra = None
            self._ocultar_opcoes()
            self._pintar_barra()
            self.avisar("")

    # ============================================================== estado
    def _relogio(self) -> None:
        try:
            self.lbl_hora.configure(text=fmt.agora_dt().strftime("%H:%M"))
            self._atualizar_fila()
            self._id_relogio = self.after(1000, self._relogio)
        except tk.TclError:      # janela já destruída
            pass

    def _atualizar_fila(self) -> None:
        """Indicador da impressora térmica: some quando não há nada a dizer; fica amarelo/vermelho quando há
        documento esperando ou com erro (clique para abrir a fila)."""
        try:
            texto, nivel = self.ctx.impressao.fila.texto_indicador()
            if nivel == "ok" and self.ctx.impressao.modo() != "termica":
                texto = ""
            self.lbl_fila.configure(text=texto, fg={"ok": CX["verde"], "aviso": CX["ambar"], "erro": CX["vermelho"]}[nivel])
        except Exception:  # noqa: BLE001 - um indicador nunca pode derrubar o caixa
            self.lbl_fila.configure(text="")

    def abrir_fila(self) -> None:
        JanelaFilaImpressao(self, self.ctx)

    def abrir_devolucoes(self) -> None:
        from src.ui.devolucoes_ui import abrir
        ok, janela = tema.tratar(self, abrir, self, self.ctx)
        if not ok:
            return
        janela.grab_set()
        self.wait_window(janela)
        if self.venda_id is None:
            balcao = self.ctx.caixa.balcao_aberto()
            self.venda_id = balcao["id"] if balcao else None
        self.recarregar()

    def _atualizar_painel(self) -> None:
        """Com os ícones sempre à vista, a mesa parada precisa ganhar o relógio sozinha, sem o operador agir."""
        try:
            if self.mesas_visiveis:
                self.carregar_mesas()
            self._id_lista = self.after(30000, self._atualizar_painel)
        except tk.TclError:      # janela já destruída
            pass

    def destroy(self) -> None:
        for nome in ("_id_relogio", "_id_lista"):
            try:
                self.after_cancel(getattr(self, nome))
            except (AttributeError, tk.TclError, ValueError):
                pass
        super().destroy()

    def avisar(self, texto: str, cor: str | None = None) -> None:
        self.status.configure(text=texto, foreground=cor or CX["suave"])

    def venda(self) -> dict | None:
        return self.ctx.caixa.obter(self.venda_id) if self.venda_id else None

    def recarregar(self) -> None:
        t = self.ctx.turnos.atual()
        self.lbl_turno.configure(text=f"TURNO {t['numero'] if t else '-'}  ·  {self.ctx.operador.nome.upper()}")
        v = self.venda()
        self.grade.limpar()
        if self.perfil_adega:
            self._detalhes_preco = {}
            self.lbl_detalhe_preco.configure(text="")
        total = 0
        self.comissao_marcada = []
        self._itens_na_grade = 0
        itens = self.ctx.caixa.itens(v["id"]) if v else []
        if v:
            for it in itens:
                nome = it["nome"] + (f"  [{' / '.join(it['partes_nomes'])}]" if it["partes_nomes"] else "")
                observacao = it["observacao"] or ""
                if self.perfil_adega:
                    explicacao = ProdutoController.explicacao_preco_adega(it, v["modalidade"])
                    if it.get("temperatura") == "gelada":
                        observacao = re.sub(r"^Gelada(?: - )?", "", observacao)     # a observação repete o selo; fica só o resto
                    if explicacao["rotulo"]:
                        nome += f"  [{explicacao['rotulo']}]"
                    if explicacao["detalhe"]:
                        observacao = " · ".join(filter(None, (observacao, explicacao["detalhe"])))
                    detalhe = " · ".join(filter(None, (it["nome"], explicacao["rotulo"])))
                    if explicacao["detalhe"]:
                        detalhe += "\n" + explicacao["detalhe"]
                    self._detalhes_preco[str(it["id"])] = detalhe
                self.grade.adicionar([it["codigo"], nome, it["unidade"], fmt.fmt_num(it["preco_unit_cent"]),
                                      fmt.fmt_qtd(it["quantidade"]), fmt.fmt_num(it["total_cent"]), observacao], iid=it["id"])
            self._itens_na_grade = self.grade.total()
            self._linhas_comissao(v, t)
            total = v["total_cent"]
            self.grade.tree.yview_moveto(1.0)
        if self.grade.total():                       # lista vazia: um convite no lugar de uma tabela em branco
            self.lbl_vazio.place_forget()
        else:
            self.lbl_vazio.place(relx=0.5, rely=0.45, anchor="center")
        self.lbl_total.configure(text=fmt.fmt_num(total))
        self.lbl_troco.configure(text="0,00")
        self._detalhe_total(v)
        if self.perfil_adega:
            self._resumo_adega(itens, v)
            self._mostrar_detalhe_preco()
        recebido = sum(p["valor_cent"] for p in self.ctx.caixa.pagamentos(v["id"])) if v else 0
        if v and v["prepago"]:
            s = self.ctx.caixa.saldo_prepago(v["id"])
            self.lbl_recebido.configure(text=f"Crédito: {fmt.fmt_brl(s['credito'])}\nSaldo: {fmt.fmt_brl(s['saldo'])}")
            self.lbl_recebido.pack(fill="x", pady=(8, 0))
        elif recebido:
            self.lbl_recebido.configure(text=f"Recebido: {fmt.fmt_brl(recebido)}\nFalta receber: {fmt.fmt_brl(max(0, total - recebido))}")
            self.lbl_recebido.pack(fill="x", pady=(8, 0))
        else:
            self.lbl_recebido.pack_forget()
        self._situacao(v)
        self._status_venda(v, total, recebido)
        self.lbl_leitor.configure(text="LEITOR ÓPTICO ATIVO" if self.leitor else "")
        self.carregar_mesas()                        # os cartões e os indicadores do cabeçalho acompanham a venda

    def _mostrar_detalhe_preco(self) -> None:
        selecionados = self.grade.tree.selection()
        ultimo = next(reversed(self._detalhes_preco), None)
        chave = selecionados[0] if selecionados else ultimo
        self.lbl_detalhe_preco.configure(text=self._detalhes_preco.get(chave, ""))

    def _resumo_adega(self, itens: list[dict], venda: dict | None) -> None:
        naturais = sum(i["quantidade"] for i in itens if i.get("temperatura", "natural") == "natural")
        geladas = sum(i["quantidade"] for i in itens if i.get("temperatura") == "gelada")
        economia = sum(ProdutoController.explicacao_preco_adega(i, venda["modalidade"])["economia_cent"]
                       for i in itens) if venda else 0
        texto = (f"{len(itens)} linha(s)  ·  Quantidade: {fmt.fmt_qtd(naturais + geladas)}\n"
                 f"Natural: {fmt.fmt_qtd(naturais)}  ·  Gelada: {fmt.fmt_qtd(geladas)}")
        if economia and venda and venda["modalidade"] == "balcao":
            texto += f"\nEconomia no atacado: {fmt.fmt_brl(economia)}"
        self.lbl_resumo_adega.configure(text=texto)

    def _oferta_adega(self) -> None:
        p = self.produto
        if not p:
            self.lbl_oferta.configure(text="QUANTIDADE × CÓDIGO: 6*789…  ·  Natural / gelada  ·  Troca de cascos")
            return
        partes = [f"Natural: {fmt.fmt_brl(self.ctx.produtos.preco_vigente(p))}"]
        if p.get("preco_gelada_cent", 0) > 0:
            partes.append(f"Gelada: {fmt.fmt_brl(p['preco_gelada_cent'])}")
        v = self.venda()
        if v is None or v["modalidade"] == "balcao":
            for rotulo, chave_qtd, chave_preco in (("natural", "atacado_qtd", "preco_atacado_cent"),
                                                   ("gelada", "atacado_gelada_qtd", "preco_atacado_gelada_cent")):
                if p.get(chave_qtd, 0) > 0 and p.get(chave_preco, 0) > 0:
                    qtd = fmt.fmt_qtd(p[chave_qtd], casas=4).rstrip("0").rstrip(",")
                    partes.append(f"Atacado {rotulo}: {qtd}+ por {fmt.fmt_brl(p[chave_preco])}/un")
        else:
            partes.append("Atacado automático somente no balcão")
        if p.get("casco_produto_id"):
            partes.append("Retornável: informe os cascos sem troca ao confirmar")
        self.lbl_oferta.configure(text="  ·  ".join(partes))

    def _detalhe_total(self, v: dict | None) -> None:
        """Sob o total: de onde vem o acréscimo (serviço, taxa, desconto), para o cliente não estranhar o valor."""
        partes = []
        if v:
            if v.get("rodizio"):
                partes.append(f"Rodízio: {v['pessoas']} pessoa(s)")
            if v["desconto_cent"]:
                partes.append(f"Desconto: - {fmt.fmt_brl(v['desconto_cent'])}")
            if v["servico_cent"]:
                pct = "" if v["servico_manual"] else f" ({float(self.ctx.banco.cfg('servico_pct', '10') or 0):g}%)"
                partes.append(f"Serviço{pct}: {fmt.fmt_brl(v['servico_cent'])}")
            if v["taxa_cent"]:
                partes.append(f"{'Compl. consumação' if v['comanda'] else 'Taxa de entrega'}: {fmt.fmt_brl(v['taxa_cent'])}")
            if v["acrescimo_cent"]:
                partes.append(f"Taxa do crédito: {fmt.fmt_brl(v['acrescimo_cent'])}")
        self.lbl_detalhe_total.configure(text="\n".join(partes))

    def _status_venda(self, v: dict | None, total: int, recebido: int) -> None:
        """O selo ao lado do título da venda: Aberta, Conta enviada, Pago em parte... na mesma cor do cartão da comanda."""
        if v is None or v["modalidade"] == "balcao":
            texto, cor = "Balcão", CX["verde"]
        elif v["modalidade"] == "caderneta":
            texto, cor = "Caderneta", CX["vermelho"]
        elif v["modalidade"] == "entrega":
            texto, cor = "Entrega", CX["azul"]
        elif v["prepago"]:                                  # o cliente ainda consome: o que importa é o saldo
            texto, cor = ("Pré-pago", CX["violeta"]) if self.ctx.caixa.saldo_prepago(v["id"])["saldo"] > 0 \
                else ("Sem crédito", CX["vermelho"])
        elif recebido and recebido >= total > 0:
            texto, cor = "Concluir acerto", CX["ambar"]
        elif recebido:
            texto, cor = "Pago em parte", CX["violeta"]
        elif v["status"] == "conta_enviada":
            texto, cor = "Conta enviada", CX["ambar"]
        else:
            texto, cor = "Aberta", CX["verde"]
        self.lbl_status_venda.configure(text=texto, fg=cor, bg=misturar(CX["cartao"], cor, 0.16),
                                        highlightbackground=misturar(CX["borda"], cor, 0.45))

    def _linhas_comissao(self, v: dict, turno: dict | None) -> None:
        """Comanda de garota: o que está marcado nela (comissão a pagar e a paga neste turno) aparece na lista, em cor própria e
        só para leitura. Comissão não é venda: o total da comanda continua sendo só o dos itens."""
        if v["modalidade"] != "mesa" or not v["comanda"] or not self.ctx.comissoes.ligada():
            return
        self.comissao_marcada = self.ctx.comissoes.marcadas(v["posicao"], turno["id"] if turno else None)
        codigo = self.ctx.comissoes.codigo() or "COM"
        for c in self.comissao_marcada:
            paga = c["status"] == "paga"
            quando = f"{fmt.fmt_datahora(c['criado_em'])[11:16]} {c['operador'] or ''}".strip()
            self.grade.adicionar([codigo, "COMISSÃO (paga)" if paga else "COMISSÃO (a pagar)", "", fmt.fmt_num(c["valor_cent"]), "1",
                                  fmt.fmt_num(c["valor_cent"]), quando],
                                 iid=f"c{c['id']}", tags=("comissao_paga" if paga else "comissao",))

    def _linha_de_comissao(self, iid) -> bool:
        """True (e avisa) se a linha escolhida da lista é uma comissão marcada, que não é item da venda (observação e
        transferência não valem para ela)."""
        if iid is not None and str(iid).startswith("c"):
            tema.aviso(self, "Esta linha é uma comissão marcada na comanda da garota.\n"
                             + ("Ela não aceita observação nem transferência: para pagar use F12 e para cancelar, Delete."
                                if self._comissao_na_linha() else "Para pagar ou cancelar, use o botão Comissões."))
            return True
        return False

    def _situacao(self, v: dict | None) -> None:
        if v is None:
            self.lbl_situacao.configure(text="Balcão")
            self.var_pos.set("0")
            self.faixa.pack_forget()
            return
        mod = v["modalidade"]
        if mod == "mesa":
            garota = self.ctx.comissoes.garota(v["posicao"]) if v["comanda"] and self.ctx.comissoes.ligada() else None
            self.lbl_situacao.configure(text=nome_posicao(v["comanda"], v["posicao"])
                                        + (f" - {garota['nome']}" if garota and garota["ativo"] else "")
                                        + (f" · {v['apelido']}" if v["apelido"] else "")
                                        + (" - CONTA ENVIADA" if v["status"] == "conta_enviada" else ""))
            self.var_pos.set(self.ctx.caixa.rotular_posicao(v["comanda"], v["posicao"]))
        else:
            self.lbl_situacao.configure(text={"balcao": "Balcão", "caderneta": "Caderneta", "entrega": f"Entrega {v['posicao']}"}[mod])
            self.var_pos.set("0")
        if mod in ("caderneta", "entrega") and v["cliente_id"]:
            c = self.ctx.caderneta.obter(v["cliente_id"])
            if mod == "caderneta":
                txt = (f"CADERNETA   {c['numero_consulta']}  {c['nome']}      Limite {fmt.fmt_num(c['limite_cent'])}"
                       f"      Saldo {fmt.fmt_num(c['saldo_cent'])}")
                cor = "#b32020"
            else:
                txt = (f"ENTREGA #{v['posicao']}   {c['numero_consulta']}  {c['nome']}   {c['endereco'] or ''}   "
                       f"Taxa {fmt.fmt_num(v['taxa_cent'])}")
                cor = "#1f5fb3"
            self.faixa.configure(text=txt, bg=cor)
            self.faixa.pack(fill="x", pady=(10, 0), before=self.cartao_entrada)
        elif self.comissao_marcada:
            a_pagar = sum(c["valor_cent"] for c in self.comissao_marcada if c["status"] == "pendente")
            paga = sum(c["valor_cent"] for c in self.comissao_marcada if c["status"] == "paga")
            nome = self.ctx.comissoes.nome(v["posicao"])
            txt = f"COMISSÃO MARCADA NA COMANDA {v['posicao']}{' ' + nome if nome else ''}     A pagar: {fmt.fmt_brl(a_pagar)}"
            if paga:
                txt += f"     Paga neste turno: {fmt.fmt_brl(paga)}"
            if a_pagar and self._comissao_na_linha():
                txt += "     F12 paga a garota"
            self.faixa.configure(text=txt, bg=CX["comissao"])
            self.faixa.pack(fill="x", pady=(10, 0), before=self.cartao_entrada)
        else:
            self.faixa.pack_forget()

    # =============================================================== itens
    def _enter_codigo(self, _=None) -> str:
        if self.indice_barra is not None:
            return self._barra_enter()
        if self.modo_comissao:
            self._comissao_ir_ao_valor()
            return "break"
        texto = self.var_cod.get().strip()
        if not texto:
            self._entrar_barra()
            return "break"
        self.resolver_codigo(texto)
        return "break"

    def _baixo_codigo(self, _=None) -> str:
        if self.modo_comissao:
            self._comissao_ir_ao_valor()
        else:
            self._foco_grade()
        return "break"

    def _cima_valor(self, _=None) -> str | None:
        """Lançando comissão, a seta para cima volta do valor para o número da garota."""
        if not self.modo_comissao:
            return None
        self.ent_codigo.focus_set()
        self.ent_codigo.selection_range(0, "end")
        return "break"

    def _esc_codigo(self, _=None) -> str:
        if self.indice_barra is not None:
            return self._barra_esc()
        if self.produto is not None or self.modo_comissao:
            self.cancelar_item_pendente()
        else:
            self.foco_mesa()      # Esc volta ao "marcar comanda": ícones à vista e o campo da posição pronto para digitar
        return "break"

    def resolver_codigo(self, texto: str) -> None:
        qtd = None
        m = QTD_ANTES_DO_CODIGO.fullmatch(texto)
        if m:                                            # "6*" + código: só produto (nem comissão, nem saída, nem mesa)
            qtd, texto = m.group(1), m.group(2).strip()
        elif self.ctx.comissoes.eh_codigo(texto):        # o código da comissão (50) não é produto: lança a comissão da garota
            self.var_cod.set("")
            self.lancar_comissao()
            return
        elif self.ctx.caixa.eh_codigo_saida(texto):      # 1002: comanda sem consumo, libera a saída e imprime o papel
            self.var_cod.set("")
            self.liberar_saida()
            return
        p = self.ctx.produtos.buscar_codigo(texto)
        if p is None and qtd is None and self.com_mesas and parece_posicao(texto):   # "C2"/"M5" troca de posição (produto de mesmo código vence)
            self.var_cod.set("")
            self.var_pos.set(texto.strip())
            self.chamar_mesa()
            return
        if p is None and not texto.isdigit():
            achados = self.ctx.produtos.pesquisar(texto)
            if len(achados) == 1:
                p = achados[0]
            elif achados:
                p = self._escolher_produto(achados, texto)
                if p is None:
                    return
        if p is None and texto.isdigit() and len(texto) >= 8:    # código de barras ainda não cadastrado: cadastra na hora
            self.var_cod.set("")
            p = self._cadastro_rapido(texto)
            if p is None:
                self.ent_codigo.focus_set()
                return
        if p is None:
            self.bell()
            self.avisar(f"Produto '{texto}' não encontrado.", tema.COR["perigo"])
            self.var_cod.set("")
            return
        self.selecionar_produto(p, qtd)

    def _cadastro_rapido(self, cbarra: str) -> dict | None:
        """O leitor passou um código de barras que não está cadastrado: oferece cadastrar o produto ali mesmo (nome, preço e
        categoria) para já lançá-lo. Quem não pode cadastrar produtos precisa da senha de quem pode."""
        if not tema.confirmar(self, f"O código {cbarra} não está cadastrado.\nCadastrar o produto agora?", "Produto novo"):
            return None
        if not self.ctx.acesso.pode(self.ctx.operador, "cad_produtos") and tema.pedir_senha_supervisor(
                self, self.ctx, "cad_produtos", "Cadastrar produto exige autorização:") is None:
            return None
        p = cadastro_rapido_ui.pedir_produto(self, self.ctx, cbarra, self._subgrupo_rapido)
        if p is not None:
            self._subgrupo_rapido = p["subgrupo_id"]
        return p

    def consultar(self) -> None:
        achados = self.ctx.produtos.pesquisar(self.var_cod.get().strip(), limite=500)
        p = self._escolher_produto(achados, self.var_cod.get().strip())
        if p is not None:
            self.selecionar_produto(p)
        else:
            self.ent_codigo.focus_set()

    def _escolher_produto(self, produtos: list[dict], texto: str = "") -> dict | None:
        itens = [(p["id"], (p["codigo"], p["nome"], fmt.fmt_num(self.ctx.produtos.preco_vigente(p)),
                            fmt.fmt_qtd(p["qt_atual"]) if p["controla_estoque"] else "")) for p in produtos]
        cols = [("cod", "Código", 110, "w"), ("nome", "Produto", 280, "w"), ("preco", "Preço", 80, "e"), ("qt", "Estoque", 80, "e")]
        pid = tema.escolher(self, "Consulta de produtos", itens, "Digite parte do nome para filtrar:", colunas=cols, altura=14)
        return self.ctx.produtos.por_id(pid) if pid else None

    def selecionar_produto(self, p: dict, qtd: str | None = None) -> None:
        """`qtd` é a quantidade digitada antes do código ("6*"): o item entra direto com ela."""
        if self.venda_id and self.venda() and self.venda()["modalidade"] == "caderneta" and not self.venda()["cliente_id"]:
            tema.aviso(self, "Escolha o cliente da caderneta (F5).")
            return
        if self.modo_comissao:
            self._limpar_entrada()            # escolheu um produto no meio da comissão: a comissão é descartada
        self.produto = p
        preco = self.ctx.produtos.preco_vigente(p)
        un = self.ctx.banco.valor("SELECT abreviatura FROM unidades WHERE id = ?", (p["unidade_id"],), "")
        self.lbl_desc.configure(text=p["nome"])
        self.lbl_un.configure(text=un)
        self.lbl_preco.configure(text=fmt.fmt_num(preco))
        if self.perfil_adega:
            self._oferta_adega()
        self.var_cod.set(p["codigo"])
        if qtd is not None:
            self.ent_qtd.configure(state="normal")       # se a quantidade for recusada, o operador corrige no campo
            self.var_qtd.set(qtd)
            self.confirmar_item()
            return
        if self.leitor and not p["aceita_decimal"] and p["partes"] <= 1:
            self.var_qtd.set("1")
            self.confirmar_item()
            return
        self.ent_qtd.configure(state="normal")
        if p["balanca"]:          # produto de balança: pesa direto, sem esperar o operador lembrar do F2
            self._capturar_peso()
            return
        self.var_qtd.set("1")
        self.ent_qtd.focus_set()
        self.ent_qtd.selection_range(0, "end")

    def f1(self) -> None:
        """Na entrega libera o troco (manual do Caixa); nas demais telas abre a consulta de produtos."""
        v = self.venda()
        if v and v["modalidade"] == "entrega":
            self.liberar_troco()
        else:
            self.consultar()

    def cancelar_item_pendente(self) -> None:
        self._limpar_entrada()
        self.ent_codigo.focus_set()

    def _limpar_entrada(self) -> None:
        self.produto = None
        if self.modo_comissao:
            self.modo_comissao = False
            self.lbl_cod_titulo.configure(text="Código")
            self.lbl_qtd_titulo.configure(text="Quantidade")
            self.lbl_desc.configure(foreground=CX["texto"])
        self.var_cod.set("")
        self.var_qtd.set("")
        self.ent_qtd.configure(state="disabled")
        for lbl in (self.lbl_desc, self.lbl_un, self.lbl_preco):
            lbl.configure(text="")
        if self.perfil_adega:
            self._oferta_adega()

    def confirmar_item(self) -> None:
        if self.modo_comissao:
            self._comissao_confirmar()
            return
        p = self.produto
        if p is None:
            return
        try:
            qtd = fmt.para_qtd(self.var_qtd.get())
        except ValueError:
            self.avisar("Quantidade inválida.", tema.COR["perigo"])
            return
        if not math.isfinite(qtd) or qtd <= 0 or (not p["aceita_decimal"] and qtd != int(qtd)):
            self.avisar("Informe uma quantidade positiva" + (" e inteira." if not p["aceita_decimal"] else "."),
                        tema.COR["perigo"])
            self.ent_qtd.focus_set()
            return
        partes = None
        if p["partes"] > 1 and (p["composto"] or self.ctx.banco.valor("SELECT COUNT(*) FROM produtos WHERE montagem = 1 AND ativo = 1")):
            partes = caixa_dialogos.dialogo_partes(self, self.ctx, p)
            if partes is None:
                return
        opcoes = {}
        if p.get("preco_gelada_cent", 0) > 0:
            temperatura = adega_dialogos.pedir_temperatura(self, p, self.ctx.produtos.preco_vigente(p))
            if temperatura is None:
                self.cancelar_item_pendente()
                return
            opcoes["temperatura"] = temperatura
        if p.get("casco_produto_id"):
            casco = self.ctx.produtos.por_id(p["casco_produto_id"])
            if casco is None:
                self.avisar("Casco não encontrado. Confira o cadastro da bebida.", tema.COR["perigo"])
                return
            quantidade_cascos = adega_dialogos.pedir_cascos(
                self, p, casco, qtd,
                prever_impacto=lambda n: self.ctx.caixa.previa_cascos(self.venda_id, casco, n))
            if quantidade_cascos is None:
                self.cancelar_item_pendente()
                return
            opcoes["quantidade_cascos"] = quantidade_cascos
        ok, item_id = tema.tratar(self, self._lancar, p["id"], qtd, partes or None, **opcoes)
        if not ok:
            self.ent_qtd.focus_set()
            return
        self.avisar(f"{fmt.fmt_qtd(qtd)} x {p['nome']} lançado.", tema.COR["ok"])
        self._limpar_entrada()
        self.recarregar()
        self.ent_codigo.focus_set()

    def _lancar(self, produto_id: int, qtd: float, partes: list[int] | None, **opcoes) -> int:
        caixa = self.ctx.caixa
        if self.venda_id is None:
            self.venda_id = caixa.abrir_balcao()
        item_id = caixa.adicionar_item(self.venda_id, produto_id, qtd, partes=partes, **opcoes)
        self._enviar_remoto([item_id])
        return item_id

    def _enviar_remoto(self, item_ids: list[int]) -> None:
        """Manda os itens para a cozinha/bar. Falha de impressora remota não bloqueia a venda."""
        try:
            for sub, texto in self.ctx.impressao.pedido_remoto(self.venda_id, item_ids).items():
                setor = self.ctx.impressao.setor_do_subgrupo(sub)
                self.ctx.impressao.enviar_remoto(texto, f"pedido_{sub}", setor=setor)
                self.avisar(f"Pedido enviado à impressora remota: {sub}", tema.COR["ok"])
        except ErroImpressao as e:
            self.avisar(f"Impressora da cozinha/bar indisponível: {e}", tema.COR["perigo"])

    def observacao_item(self) -> None:
        s = self.grade.selecionado()
        if s is None or self._linha_de_comissao(s):
            return
        if not self.ctx.banco.valor("SELECT usa_observacao FROM produtos WHERE id = (SELECT produto_id FROM itens_venda WHERE id = ?)", (int(s),)):
            tema.aviso(self, "Este produto não permite observações (marque 'Permite observações' no cadastro).")
            return
        texto = caixa_dialogos.escolher_observacao(self, self.ctx)
        if texto:
            ok, _ = tema.tratar(self, self.ctx.caixa.definir_observacao, int(s), texto)
            if not ok:
                return
            self._enviar_remoto([int(s)])
            self.recarregar()
            self.grade.selecionar(s)

    # ============================================================ cancelar
    def _autorizar(self, modulo: str, cfg: str, motivo: str) -> bool:
        if not self.ctx.acesso.precisa_senha(self.ctx.operador, modulo, cfg):
            return True
        return tema.pedir_senha_supervisor(self, self.ctx, modulo, motivo) is not None

    def menu_cancelar(self) -> None:
        if self.venda_id is None:
            tema.aviso(self, "Não há venda em andamento.")
            return
        op = tema.escolher(self, "Cancela...", [("item", "Cancela Item"), ("conta", "Cancela Conta (venda inteira)")],
                           "Escolha e tecle Enter:", altura=3)
        if op == "item":
            if self._autorizar("caixa_cancelamento", "exigir_senha_cancelamento", "Cancelar item exige autorização:"):
                self.modo_cancelar = True
                self._foco_grade(ultimo=True)
                self.avisar("Selecione o item com as setas e tecle Enter para cancelar. Esc retorna.", tema.COR["aviso"])
        elif op == "conta":
            self.cancelar_conta()

    def _pedir_motivo(self, titulo: str, rotulo: str, padrao: str) -> str | None:
        """Motivo do cancelamento: obrigatório se a configuração exigir; senão a janela só aparece quando há um padrão."""
        if not self.ctx.banco.cfg_bool("exigir_motivo_cancelamento", False):
            return padrao
        def validar(v: str) -> str:
            if not v:
                raise ValueError("Informe o motivo.")
            return v
        return tema.pedir_texto(self, titulo, rotulo, validar=validar)

    def cancelar_conta(self) -> None:
        if not self._autorizar("caixa_cancelamento", "exigir_senha_cancelamento", "Cancelar a venda exige autorização:"):
            return
        if not tema.confirmar(self, "Cancelar a venda inteira?\nTodos os itens lançados serão eliminados.", "Cancela Venda", padrao_sim=False):
            return
        motivo = self._pedir_motivo("Cancela Venda", "Motivo do cancelamento da venda:", "cancelada no caixa")
        if motivo is None:
            return
        ok, _ = tema.tratar(self, self.ctx.caixa.cancelar_venda, self.venda_id, motivo)
        if ok:
            self.venda_id = None
            self._limpar_entrada()
            self.recarregar()
            self.avisar("Venda cancelada.", tema.COR["aviso"])
            self.ent_codigo.focus_set()

    def _enter_grade(self, _=None) -> str:
        """Enter (ou duplo clique) na linha: no modo cancelar, cancela; fora dele, abre as ações daquela linha."""
        if self.modo_cancelar:
            self.cancelar_item_selecionado()
        else:
            self._menu_linha()
        return "break"

    def _cima_grade(self, _=None) -> str | None:
        """Seta para cima na primeira linha volta ao campo do código (o mesmo caminho da seta para baixo, ao contrário)."""
        if self.grade.indice() <= 0:
            self.ent_codigo.focus_set()
            return "break"
        return None

    def _menu_linha(self) -> None:
        """As ações da linha escolhida na lista: do item (observação, transferir, cancelar) ou, na comanda da garota, do
        lançamento de comissão (pagar a garota, cancelar o lançamento)."""
        s = self.grade.selecionado()
        if s is None:
            return
        if str(s).startswith("c"):
            self._menu_linha_comissao(str(s))
            return
        nome = self.grade.valores(s)[1]
        escolha = tema.escolher(self, "Ações do item", [
            ("obs", "Observação do item (O)"), ("transferir", "Transferir para outra comanda ou mesa (T)"),
            ("cancelar", "Cancelar este item (Delete)")], f"{nome}\nEscolha e tecle Enter:", altura=3)
        if escolha == "obs":
            self.observacao_item()
        elif escolha == "transferir":
            self.transferir_item()
        elif escolha == "cancelar":
            self.cancelar_item_selecionado()

    def _menu_linha_comissao(self, iid: str) -> None:
        c = next((x for x in self.comissao_marcada if f"c{x['id']}" == iid), None)
        if c is None:
            return
        if c["status"] != "pendente":
            tema.aviso(self, "Esta comissão já foi paga neste turno.")
            return
        if not self._comissao_na_linha():
            tema.aviso(self, "Para pagar ou cancelar a comissão, use o botão Comissões.")
            return
        total = sum(x["valor_cent"] for x in self.comissao_marcada if x["status"] == "pendente")
        escolha = tema.escolher(self, "Ações da comissão", [
            ("pagar", f"Pagar a comissão da garota (R$ {fmt.fmt_num(total)})"),
            ("cancelar", f"Cancelar este lançamento (R$ {fmt.fmt_num(c['valor_cent'])})")],
            "Escolha e tecle Enter:", altura=2)
        if escolha == "pagar":
            self._pagar_comissao(self.venda())
        elif escolha == "cancelar":
            self._cancelar_comissao(iid)

    def cancelar_item_selecionado(self) -> None:
        s = self.grade.selecionado()
        if s is not None and str(s).startswith("c") and self._comissao_na_linha():
            self._cancelar_comissao(s)                 # linha de comissão: cancela o lançamento, não um item
            return
        if s is None or self._linha_de_comissao(s):
            return
        if not self.modo_cancelar and not self._autorizar("caixa_cancelamento", "exigir_senha_cancelamento", "Cancelar item exige autorização:"):
            return
        nome = self.grade.valores(s)[1]
        if tema.confirmar(self, f"Cancelar o item '{nome}'?", "Cancela Item", padrao_sim=False):
            ok, info = tema.tratar(self, self.ctx.caixa.info_cancelamento, int(s))
            if not ok:
                return
            qtd = self._pedir_qtd_cancelar(nome, info)
            if qtd is None:
                return
            if qtd < info["quantidade"]:
                motivo = tema.pedir_texto(self, "Cancela Item", f"Motivo do cancelamento parcial de '{nome}' (obrigatório):",
                                          validar=self._motivo_obrigatorio)
            else:
                motivo = self._pedir_motivo("Cancela Item", f"Motivo do cancelamento de '{nome}':", "")
            if motivo is None:
                return
            ok, _ = tema.tratar(self, self.ctx.caixa.cancelar_item, int(s), motivo,
                                qtd if qtd < info["quantidade"] else None)
            if ok:
                self.modo_cancelar = False
                self.recarregar()
                self.avisar("Item cancelado." if qtd >= info["quantidade"] else
                            f"Cancelado {_qtd_curta(qtd)} de '{nome}'.", tema.COR["aviso"])
                self.ent_codigo.focus_set()

    @staticmethod
    def _motivo_obrigatorio(v: str) -> str:
        if not v:
            raise ValueError("Informe o motivo.")
        return v

    def _pedir_qtd_cancelar(self, nome: str, info: dict) -> float | None:
        """Quantidade a cancelar: só pergunta quando há mais de uma unidade ou o produto é fracionado. Sugere a parte
        ainda não paga (a já paga na divisão por item é protegida pelo controlador)."""
        if not info["pergunta_qtd"]:
            return info["quantidade"]
        def validar(v: str) -> float:
            q = fmt.validar_qtd(fmt.para_qtd(v))
            if q <= 0 or q > info["quantidade"]:
                raise ValueError(f"Informe de 0 a {_qtd_curta(info['quantidade'])}.")
            if not info["aceita_decimal"] and q != int(q):
                raise ValueError("Este produto não aceita quantidade fracionada.")
            return q
        pago = f"\nJá pago por item: {_qtd_curta(info['qtd_paga'])}." if info["qtd_paga"] else ""
        return tema.pedir_texto(self, "Cancela Item",
                                f"Quantidade a cancelar de '{nome}' (lançado {_qtd_curta(info['quantidade'])}):{pago}",
                                _qtd_curta(info["qtd_livre"] if info["qtd_paga"] else info["quantidade"]),
                                validar=validar)

    def _sair_modo_cancelar(self) -> None:
        self.modo_cancelar = False
        self.avisar("")
        self.ent_codigo.focus_set()

    def _foco_grade(self, ultimo: bool = False) -> None:
        if self.grade.total():
            self.grade.tree.focus_set()
            if ultimo and self._itens_na_grade:
                self.grade.selecionar_indice(self._itens_na_grade - 1)       # o último ITEM: as comissões são só leitura
            else:
                self.grade.selecionar_indice(10 ** 9 if ultimo else max(self.grade.indice(), 0))

    # ============================================================== mesas e comandas
    def _mostrar_painel(self) -> None:
        self.mesas_visiveis = True
        self.painel_mesas.pack(side="left", fill="y", padx=(0, 16), before=self.esq)

    def _esconder_painel(self) -> None:
        self.mesas_visiveis = False
        self.painel_mesas.pack_forget()

    def _chave_atual(self) -> str | None:
        """O ícone da venda que está na tela: '0' (balcão) ou a comanda/mesa na notação da loja; None na caderneta e na entrega."""
        v = self.venda()
        if v is None or v["modalidade"] == "balcao":
            return "0"
        if v["modalidade"] == "mesa":
            return self.ctx.caixa.rotular_posicao(v["comanda"], v["posicao"])
        return None

    def carregar_mesas(self) -> None:
        garotas = []
        if self.ctx.comissoes.ligada() and self.ctx.banco.cfg_bool("painel_mostra_garotas", True):   # garotas a pagar viram cartões
            garotas = [{"rotulo": self.ctx.caixa.rotular_posicao(True, p["garota"]), "total_cent": p["total_cent"],
                        "nome": p["nome"], "marcacoes": p["lancamentos"]}
                       for p in self.ctx.comissoes.pendentes_por_garota()]
        mesas = self.ctx.caixa.mesas()
        # Somente apresentação: lê pagamentos já registrados, sem recalcular ou fechar vendas.
        recebidos = {r["venda_id"]: r["recebido"] for r in self.ctx.banco.todos(
            """SELECT p.venda_id, SUM(p.valor_cent) AS recebido FROM pagamentos_venda p
               JOIN vendas v ON v.id = p.venda_id
               WHERE v.modalidade = 'mesa' AND v.status IN ('aberta', 'conta_enviada') GROUP BY p.venda_id""")}
        for mesa in mesas:
            mesa["recebido_cent"] = recebidos.get(mesa["id"], 0)
        balcao = self.ctx.caixa.balcao_aberto()
        self.painel_mesas.atualizar(mesas, balcao, self._chave_atual(), garotas)
        self._atualizar_indicadores(mesas, balcao)

    def _atualizar_indicadores(self, mesas: list[dict], balcao: dict | None) -> None:
        """Os indicadores do cabeçalho: posições abertas, as que esperam acerto e o que está em aberto na casa."""
        tiles = self.painel_mesas._todos_tiles
        self.lbl_abertas.configure(text=str(len(mesas)))
        self.lbl_acertos.configure(text=str(sum(t["estado"] in {"conta", "acerto", "garota"} for t in tiles)))
        aberto = sum(m["total_cent"] for m in mesas) + (balcao["total_cent"] if balcao else 0)
        self.lbl_aberto_casa.configure(text=fmt.fmt_brl(aberto))

    def nomear_comanda(self, _=None) -> None:
        """Clique no título (ou Mais opções): dá nome à comanda ou mesa da tela, que aparece no cartão do painel."""
        v = self.venda()
        if v is None or v["modalidade"] != "mesa":
            tema.aviso(self, "Escolha uma comanda ou mesa para dar nome a ela.")
            return
        texto = tema.pedir_texto(self, "Nome da comanda", f"Nome de {nome_posicao(v['comanda'], v['posicao']).lower()} "
                                 "(ex.: Carlos, Aniversário). Vazio tira o nome:", v["apelido"] or "", largura=30)
        if texto is None:
            return
        ok, _ = tema.tratar(self, self.ctx.caixa.definir_apelido, v["id"], texto)
        if ok:
            self.recarregar()
            self.avisar("Nome da comanda gravado." if texto.strip() else "Nome da comanda removido.", tema.COR["ok"])
        self.ent_codigo.focus_set()

    def navegar_comanda(self, passo: int) -> None:
        """PgDn/PgUp (ou ▶ e ◀): vai para a comanda, mesa ou garota seguinte (ou anterior) da lista do painel, que respeita a
        aba e a busca escolhidas. É o jeito de passar pelas contas, dos clientes e das garotas, sem voltar ao campo da posição."""
        if not self.com_mesas:
            return
        self.carregar_mesas()
        atual = self._chave_atual()
        destino = self.painel_mesas.vizinha(atual, passo)
        if destino is None:
            self.avisar("Não há comandas neste filtro.")
        elif destino == atual:
            self.avisar("Esta é a última comanda da lista." if passo > 0 else "Esta é a primeira comanda da lista.")
        else:
            self._tile_escolhido(destino)

    def foco_mesa(self) -> None:
        """Esc ou F4: volta ao 'marcar comanda'. Os ícones aparecem e o campo da posição fica pronto para digitar."""
        if not self.com_mesas:          # só balcão: o Esc só limpa a linha de entrada
            self.cancelar_item_pendente()
            return
        self._mostrar_painel()
        self.carregar_mesas()
        self.ent_pos.focus_set()
        self.ent_pos.selection_range(0, "end")

    def _sair_marcacao(self) -> None:
        """Sai do 'marcar comanda' para o lançamento de itens (com o painel fixo, os ícones continuam à vista)."""
        if not self.painel_fixo:
            self._esconder_painel()
        self.ent_codigo.focus_set()

    def _esc_posicao(self, _=None) -> str:
        """Segundo Esc, já no campo da posição: volta ao balcão, como no manual. Mesas e comandas abertas ficam gravadas."""
        v = self.venda()
        if v and v["modalidade"] == "mesa":
            nome = nome_posicao(v["comanda"], v["posicao"]).lower()
            tinha_itens = bool(self.ctx.caixa.itens(v["id"]))
            self.var_pos.set("0")
            self.chamar_mesa()
            if tinha_itens and self.venda_id != v["id"]:
                self.avisar(f"Balcão. A {nome} continua aberta: tecle Esc e escolha-a para voltar.")
        else:
            self._sair_marcacao()
        return "break"

    def _painel_voltar(self) -> None:
        """Esc (ou seta para cima, no alto) nos ícones: volta ao campo da posição."""
        self.ent_pos.focus_set()
        self.ent_pos.selection_range(0, "end")

    def _tile_escolhido(self, chave: str) -> None:
        self.var_pos.set(chave)
        self.chamar_mesa()

    def _digitar_posicao(self, caractere: str) -> None:
        """Com o foco nos ícones, digitar um número ou C já começa a marcar a posição."""
        self.ent_pos.focus_set()
        self.var_pos.set(caractere.upper())
        self.ent_pos.icursor("end")

    def _descartar_se_vazia(self) -> None:
        """Ao sair de uma venda sem itens (mesa ou comanda recém-aberta) ela é eliminada para não deixar mesa fantasma."""
        v = self.venda()
        if v and not self.ctx.caixa.itens(v["id"]) and v["modalidade"] in ("mesa", "caderneta") and not self.ctx.caixa.pagamentos(v["id"]):
            self.ctx.caixa.cancelar_venda(v["id"])

    def chamar_mesa(self) -> None:
        try:
            comanda, n = self.ctx.caixa.ler_posicao(self.var_pos.get().strip() or "0")
        except ValueError as e:
            tema.aviso(self, str(e))
            return
        atual = self.venda()
        if atual and atual["modalidade"] == "mesa" and atual["posicao"] == n and bool(atual["comanda"]) == comanda:
            self.ent_codigo.focus_set()
            return
        if atual and n == 0 and atual["modalidade"] == "balcao":      # já está no balcão
            self._sair_marcacao()
            return
        if atual and self.ctx.caixa.itens(atual["id"]) and atual["modalidade"] in ("balcao", "caderneta", "entrega"):
            tema.aviso(self, "Conclua, pague ou cancele a venda em andamento antes de chamar uma mesa ou comanda.")
            self.var_pos.set("0")
            return
        self._descartar_se_vazia()
        if self.modo_comissao:
            self._limpar_entrada()      # o número da garota veio da comanda anterior: não pode valer na nova
        if n == 0:
            balcao = self.ctx.caixa.balcao_aberto()
            self.venda_id = balcao["id"] if balcao else None
            self.recarregar()
            self._sair_marcacao()
            return
        pessoas = 0
        existente = self.ctx.banco.valor(
            "SELECT id FROM vendas WHERE modalidade='mesa' AND comanda=? AND posicao=? AND status IN ('aberta','conta_enviada')",
            (int(comanda), n))
        if not existente and not comanda and self.ctx.banco.cfg_bool("pergunta_pessoas"):
            pessoas = tema.pedir_numero(self, f"Mesa {n}", "Número de pessoas na mesa:", 1, 1, 999) or 0
        ok, res = tema.tratar(self, self.ctx.caixa.abrir_mesa, n, pessoas, comanda)
        if ok:
            self.venda_id = res[0]
            self.recarregar()
            self._sair_marcacao()

    def pre_conta(self) -> None:
        v = self.venda()
        if v is None:
            tema.aviso(self, "Não há conta em andamento.")
            return
        if v["modalidade"] == "entrega":
            return self.emitir_pedido_entrega()
        if v["modalidade"] != "mesa":
            tema.aviso(self, "A pré-conta é enviada às mesas e comandas. Escolha uma delas (F4)." if self.com_mesas
                       else "No balcão não há pré-conta: tecle F12 para pagar.")
            return
        ok, _ = tema.tratar(self, self.ctx.caixa.enviar_conta, v["id"])
        if ok:
            arquivo = f"pre_conta_{'comanda' if v['comanda'] else 'mesa'}_{v['posicao']}"
            enviar_ou_mostrar(self, self.ctx, "Pré-conta", self.ctx.impressao.pre_conta(v["id"]), arquivo, tipo="pre_conta")
            self.venda_id = None
            self.recarregar()
            self.ent_codigo.focus_set()

    def _pedir_posicao(self, titulo: str, rotulo: str) -> tuple[bool, int] | None:
        """Pergunta uma comanda ou mesa na notação da loja; devolve (comanda, número) ou None se cancelado."""
        return tema.pedir_texto(self, titulo, rotulo, "", largura=14, validar=self.ctx.caixa.ler_posicao)

    def _exemplos(self) -> tuple[str, str]:
        """Como se digita a posição comum e a outra nesta loja: ('123', 'M5') ou ('5', 'C2')."""
        return exemplos(self.ctx.caixa.padrao_posicao())

    def transferir_mesa(self) -> None:
        if not self.com_mesas:
            return
        v = self.venda()
        if v is None or v["modalidade"] != "mesa":
            tema.aviso(self, "Chame a mesa ou comanda que será transferida (F4) e tecle F10.")
            return
        origem = nome_posicao(v["comanda"], v["posicao"])
        comum, outra = self._exemplos()
        destino = self._pedir_posicao("Transfere mesa ou comanda",
                                      f"Transferir a {origem.lower()} para (ex.: {comum} ou {outra}):")
        if destino is None:
            return
        ok, vid = tema.tratar(self, self.ctx.caixa.transferir_mesa, (bool(v["comanda"]), v["posicao"]), destino)
        if ok:
            self.venda_id = vid
            self.recarregar()
            self.avisar(f"{origem} transferida para {nome_posicao(*destino).lower()}.", tema.COR["ok"])

    def transferir_varias(self, destino_chave: str | None = None) -> None:
        """T nos ícones: outras mesas e comandas vão para a escolhida (`destino_chave`, o rótulo do ícone)."""
        if destino_chave is None or destino_chave == "0":
            return
        destino = self.ctx.caixa.ler_posicao(destino_chave)
        comum, outra = self._exemplos()
        txt = tema.pedir_texto(self, "Transfere várias mesas ou comandas",
                               f"Origens (separe por vírgula, ex.: {comum}, {outra}) que irão para a {nome_posicao(*destino).lower()}:")
        if not txt:
            return
        try:
            origens = [self.ctx.caixa.ler_posicao(x) for x in txt.replace(" ", "").split(",") if x]
        except ValueError as e:
            tema.aviso(self, str(e))
            return
        ok, vid = tema.tratar(self, self.ctx.caixa.transferir_varias, origens, destino)
        if ok:
            if self.venda_id and not self.ctx.banco.valor("SELECT 1 FROM vendas WHERE id = ?", (self.venda_id,)):
                self.venda_id = None
            self.recarregar()

    def transferir_item(self) -> None:
        s = self.grade.selecionado()
        v = self.venda()
        if s is None or v is None or v["modalidade"] != "mesa" or self._linha_de_comissao(s):
            return
        qtd_atual = self.ctx.banco.valor("SELECT quantidade FROM itens_venda WHERE id = ?", (int(s),))
        comum, outra = self._exemplos()
        destino = self._pedir_posicao("Transfere item", f"Comanda ou mesa de destino (ex.: {comum} ou {outra}):")
        if destino is None:
            return
        qtd = tema.pedir_texto(self, "Transfere item", "Quantidade a transferir:", fmt.fmt_qtd(qtd_atual, 0) if qtd_atual == int(qtd_atual) else fmt.fmt_qtd(qtd_atual))
        if not qtd:
            return
        try:
            quantidade = fmt.para_qtd(qtd)
        except ValueError:
            tema.aviso(self, "Quantidade inválida.")
            return
        ok, _ = tema.tratar(self, self.ctx.caixa.transferir_item, int(s), destino, quantidade)
        if ok:
            self.recarregar()
            self.avisar(f"Item transferido para a {nome_posicao(*destino).lower()}.", tema.COR["ok"])

    # ============================================================== pagar
    def pagar(self) -> None:
        v = self.venda()
        if v is None or (not self.ctx.caixa.itens(v["id"]) and v["modalidade"] != "caderneta" and not v["prepago"]):
            so_comissao = v is not None and self._a_pagar_na_comanda()
            if so_comissao and self._comissao_na_linha():
                self._pagar_comissao(v)                  # comanda da garota só com comissão: F12 paga a ela
                return
            if v is not None and not so_comissao and self._acerto_sem_comissao(v):
                self._pagar_comissao(v)                  # garota sem comissão marcada: F12 acerta só os shows dela (ou fecha a conta)
                return
            tema.aviso(self, "Esta comanda só tem comissão marcada.\nPara pagar à garota, use o botão Comissões."
                       if so_comissao else "Lance ao menos um item antes de pagar.")
            return
        itens = self.ctx.caixa.itens(v["id"])
        if itens and self._a_pagar_na_comanda() and self._comissao_na_linha():
            escolha = tema.escolher(self, "Pagar...", [
                ("itens", f"Pagar a comanda (R$ {fmt.fmt_num(v['total_cent'])})"),
                ("comissao", "Pagar a comissão da garota (R$ " + fmt.fmt_num(
                    sum(c["valor_cent"] for c in self.comissao_marcada if c["status"] == "pendente")) + ")")],
                "Esta comanda tem consumo e comissão a pagar. Escolha e tecle Enter:", altura=2)
            if escolha is None:
                return
            if escolha == "comissao":
                self._pagar_comissao(v)
                return
        if v["modalidade"] == "caderneta" and itens:
            c = self.ctx.caderneta.obter(v["cliente_id"])
            if not tema.confirmar(self, f"Lançar {fmt.fmt_brl(v['total_cent'])} na caderneta de {c['nome']}?", "Caderneta"):
                return
            ok, venda = tema.tratar(self, self.ctx.caixa.fechar, v["id"])
            if ok:
                self._pos_fechamento(venda)
            return
        j = JanelaPagamento(self, self.ctx, v["id"])
        if j.fechou:
            self._pos_fechamento(self.ctx.caixa.obter(v["id"]))
        else:
            self.recarregar()
            self.ent_codigo.focus_set()

    def _pos_fechamento(self, venda: dict) -> None:
        if venda["modalidade"] == "caderneta" and self.ctx.banco.cfg_bool("imprimir_cupom", True):
            op = self.ctx.impressao.opcoes_cupom(venda["id"])
            enviar_ou_mostrar(self, self.ctx, f"Cupom {venda['cupom']}", self.ctx.impressao.cupom(venda["id"]),
                              f"cupom_{venda['cupom']}", tipo="cupom", abrir_gaveta=op["abrir_gaveta"], copias=op["copias"],
                              venda_id=venda["id"])
        volta = max(venda["pago_cent"] - venda["total_cent"] - venda["vale_cent"], 0)   # troco + a sobra devolvida do pré-pago
        self.lbl_troco.configure(text=fmt.fmt_num(volta))
        self.venda_id = None
        self._limpar_entrada()
        self.recarregar()
        self.lbl_troco.configure(text=fmt.fmt_num(volta))
        texto = f"Venda {venda['cupom']} fechada. Troco {fmt.fmt_brl(volta)}."
        alerta = self._alerta_gaveta()
        self.avisar(f"{texto}   {alerta}" if alerta else texto, tema.COR["aviso"] if alerta else tema.COR["ok"])
        self.ent_codigo.focus_set()

    def _alerta_gaveta(self) -> str:
        """Dinheiro demais na gaveta é risco: passando do limite configurado, lembra da sangria. Só diz que passou, não quanto
        há: o operador conta a gaveta no fechamento sem ver o esperado."""
        limite = self.ctx.banco.cfg_int("limite_gaveta", 0) * 100
        turno = self.ctx.turnos.atual()
        if turno is None:
            return ""
        horario = self.ctx.turnos.sangria_do_horario(turno["id"])
        if horario:
            return f"ATENÇÃO: está na hora da sangria das {horario}. Faça a sangria (F7)."
        if limite <= 0 or self.ctx.turnos.dinheiro_esperado(turno["id"]) <= limite:
            return ""
        return f"ATENÇÃO: a gaveta passou de {fmt.fmt_brl(limite)}. Faça uma sangria (F7)."

    # ========================================= caderneta / entrega / outros
    def _exigir_venda_vazia(self) -> bool:
        v = self.venda()
        if v and self.ctx.caixa.itens(v["id"]):
            tema.aviso(self, "Conclua, pague ou cancele a venda atual antes de trocar de modalidade.")
            return False
        self._descartar_se_vazia()
        self.venda_id = None
        return True

    def caderneta(self) -> None:
        if not self.ctx.banco.cfg_bool("usar_caderneta", False):     # módulo desligado: F5 não faz nada
            return
        if not self._exigir_venda_vazia():
            return
        j = JanelaClientes(self, self.ctx, "caderneta")
        if j.cliente_id:
            ok, vid = tema.tratar(self, self.ctx.caixa.abrir_caderneta, j.cliente_id)
            if ok:
                self.venda_id = vid
        self.recarregar()
        self.ent_codigo.focus_set()

    def entrega(self) -> None:
        if not self.ctx.banco.cfg_bool("usar_delivery", False):      # módulo desligado: F6 não faz nada
            return
        escolha = tema.escolher(self, "Delivery", [("novo", "Novo pedido de entrega"), ("lista", "Entregas pendentes (receber / entregador)")],
                                "Escolha:", altura=3)
        if escolha == "novo":
            if not self._exigir_venda_vazia():
                return
            j = JanelaClientes(self, self.ctx, "entrega")
            if j.cliente_id:
                ok, vid = tema.tratar(self, self.ctx.entregas.abrir, j.cliente_id)
                if ok:
                    self.venda_id = vid
        elif escolha == "lista":
            if not self._exigir_venda_vazia():
                return
            j = JanelaEntregas(self, self.ctx)
            if j.venda_id:
                self.venda_id = j.venda_id
        self.recarregar()
        self.ent_codigo.focus_set()

    def liberar_troco(self) -> None:
        v = self.venda()
        if v is None or v["modalidade"] != "entrega":
            return
        dlg = tema.Dialogo(self, "Entrega - liberar troco")
        ttk.Label(dlg.corpo, text=f"Total do pedido (com taxa): {fmt.fmt_brl(v['total_cent'])}", font=tema.FONTE_B).pack(anchor="w")
        ttk.Label(dlg.corpo, text="Cliente vai pagar com (R$):", style="Rotulo.TLabel").pack(anchor="w", pady=(8, 0))
        var = tk.StringVar(value=fmt.fmt_num(v["troco_para_cent"]) if v["troco_para_cent"] else "")
        e1 = ttk.Entry(dlg.corpo, textvariable=var, width=16)
        e1.pack(anchor="w")
        lbl = ttk.Label(dlg.corpo, text="", font=tema.FONTE_B, foreground=tema.COR["troco"])
        lbl.pack(anchor="w", pady=4)
        ents = [(r["id"], r["nome"]) for r in self.ctx.cadastros.listar("operadores", apenas_ativos=True) if r["entregador"]]
        ttk.Label(dlg.corpo, text="Entregador (opcional)", style="Rotulo.TLabel").pack(anchor="w")
        var_ent = tk.StringVar(value=next((n for i, n in ents if i == v["entregador_id"]), ""))
        ttk.Combobox(dlg.corpo, textvariable=var_ent, values=[""] + [n for _, n in ents], state="readonly", width=30).pack(anchor="w")
        ttk.Label(dlg.corpo, text="Mensagem para o pedido", style="Rotulo.TLabel").pack(anchor="w", pady=(8, 0))
        var_msg = tk.StringVar(value=v["mensagem"] or "")
        ttk.Entry(dlg.corpo, textvariable=var_msg, width=44).pack(fill="x")

        def calc(*_):
            try:
                c = fmt.para_centavos(var.get())
                lbl.configure(text=f"Troco a levar: {fmt.fmt_brl(max(c - v['total_cent'], 0))}" if c else "")
            except ValueError:
                lbl.configure(text="")
        var.trace_add("write", calc)
        calc()

        def gravar(_=None):
            try:
                troco_para = fmt.para_centavos(var.get()) if var.get().strip() else 0
                eid = next((i for i, n in ents if n == var_ent.get()), None)
                self.ctx.entregas.definir_dados(v["id"], troco_para, eid, var_msg.get())
            except (ValueError, ErroNegocio) as ex:
                tema.erro(dlg, str(ex))
                return
            dlg.ok()
        tema._botoes(dlg, "Gravar", comando_ok=gravar)
        dlg.bind("<Return>", gravar)
        dlg.mostrar(e1)
        self.recarregar()

    def emitir_pedido_entrega(self) -> None:
        v = self.venda()
        ok, _ = tema.tratar(self, self.ctx.entregas.emitir_pedido, v["id"])
        if ok:
            enviar_ou_mostrar(self, self.ctx, "Pedido de entrega", self.ctx.impressao.pedido_entrega(v["id"]),
                              f"entrega_{v['posicao']}", tipo="entrega")
            self.venda_id = None
            self.recarregar()
            self.ent_codigo.focus_set()

    def _comissao_na_linha(self) -> bool:
        """Comissão lançada, paga e cancelada na própria tela do caixa (padrão) ou pelas janelas (config desligada)."""
        return self.ctx.banco.cfg_bool("comissao_na_linha", True)

    def lancar_comissao(self) -> None:
        """Código 50. Na própria linha de entrada: 'Garota nº' (já vem o da comanda) e 'Valor (R$)'. Sem janela."""
        if not self._comissao_na_linha():
            self._lancar_comissao_na_janela()
            return
        if not comissao_ui.autorizar(self, self.ctx, "caixa_comissao", "exigir_senha_comissao", "Lançar comissão exige autorização:"):
            self.ent_codigo.focus_set()
            return
        if self.ctx.turnos.atual() is None:
            tema.aviso(self, "Abra o turno do caixa antes de lançar comissão.")
            return
        self._limpar_entrada()                       # um item esperando quantidade é descartado
        v = self.venda()
        garota = str(v["posicao"]) if v and v["modalidade"] == "mesa" and v["comanda"] else ""
        self.modo_comissao = True
        self.lbl_cod_titulo.configure(text="Garota nº")
        self.lbl_qtd_titulo.configure(text=self.ctx.comissoes.rotulo_valor())
        self.lbl_desc.configure(foreground=CX["comissao_texto"])
        self.ent_qtd.configure(state="normal")
        self.var_cod.set(garota)
        self._comissao_nome()
        if garota:
            oque = "os pontos" if self.ctx.comissoes.em_pontos() else "o valor"
            self.avisar(f"Comissão da garota {garota}: digite {oque} e tecle Enter (Esc cancela).", tema.COR["aviso"])
            self.ent_qtd.focus_set()
        else:
            self.avisar("Comissão: digite o número da garota e tecle Enter (Esc cancela).", tema.COR["aviso"])
            self.ent_codigo.focus_set()
            self.ent_codigo.selection_range(0, "end")

    def _comissao_nome(self) -> None:
        """Mostra na Descrição quem é a garota do número digitado."""
        texto = self.var_cod.get().strip()
        try:
            n = self.ctx.comissoes.validar_numero(texto) if texto else None
        except ErroNegocio:
            n = None
        g = self.ctx.comissoes.garota(n) if n is not None else None
        if n is None:
            desc = "COMISSÃO - digite a garota"
        elif g is not None:
            desc = f"COMISSÃO - {g['nome']}" + ("" if g["ativo"] else " (inativa)")
        elif self.ctx.comissoes.cadastro_vazio():
            desc = f"COMISSÃO - garota {n}"
        else:
            desc = "COMISSÃO - não cadastrada"
        self.lbl_desc.configure(text=desc)

    def _comissao_ir_ao_valor(self) -> None:
        try:
            self.ctx.comissoes.validar_numero(self.var_cod.get())
        except ErroNegocio as e:
            self.bell()
            self.avisar(str(e), tema.COR["perigo"])
            return
        self.ent_qtd.focus_set()
        self.ent_qtd.selection_range(0, "end")

    def _comissao_confirmar(self) -> None:
        """Enter no valor: confere (garota, valor, perguntas de exceção), grava, imprime a via da garota e deixa o caixa livre."""
        try:
            numero = self.ctx.comissoes.validar_numero(self.var_cod.get())
        except ErroNegocio as e:
            self.bell()
            self.avisar(str(e), tema.COR["perigo"])
            self.ent_codigo.focus_set()
            return
        try:
            cent = self.ctx.comissoes.para_centavos(self.var_qtd.get())
        except (ValueError, ErroNegocio) as e:
            self.avisar(str(e) if isinstance(e, ErroNegocio) else "Valor inválido.", tema.COR["perigo"])
            self.ent_qtd.focus_set()
            return
        if cent <= 0:
            self.avisar("Informe " + ("os pontos" if self.ctx.comissoes.em_pontos() else "o valor") + " da comissão.",
                        tema.COR["perigo"])
            self.ent_qtd.focus_set()
            return
        campo = comissao_ui.conferir_lancamento(self, self.ctx, numero, cent)
        if campo is not None:
            (self.ent_codigo if campo == "numero" else self.ent_qtd).focus_set()
            return
        turno = self.ctx.turnos.atual()
        if turno is None:
            tema.aviso(self, "Abra o turno do caixa antes de lançar comissão.")
            return
        if comissao_ui.registrar_comissao(self, self.ctx, turno["id"], numero, cent,
                                          ao_lancar=lambda texto: self.avisar(texto, tema.COR["ok"])) is None:
            self.ent_qtd.focus_set()                 # a mensagem do erro já foi mostrada: o operador corrige e tenta de novo
            return
        self._limpar_entrada()
        self.recarregar()                            # a comissão nova já aparece na comanda da garota e no ícone dela
        self.ent_codigo.focus_set()

    def _lancar_comissao_na_janela(self) -> None:
        """Com 'comissao_na_linha' desligado: na comanda 180 a garota é a 180 (a janela já vem com o número)."""
        v = self.venda()
        sugerida = str(v["posicao"]) if v and v["modalidade"] == "mesa" and v["comanda"] else ""
        comissao_ui.lancar(self, self.ctx, sugerida, ao_lancar=lambda texto: self.avisar(texto, tema.COR["ok"]))
        self.recarregar()                       # a comissão nova já aparece na comanda da garota
        self.ent_codigo.focus_set()

    def _a_pagar_na_comanda(self) -> bool:
        return any(c["status"] == "pendente" for c in self.comissao_marcada)

    def _acerto_sem_comissao(self, v: dict) -> bool:
        """Comanda vazia e sem comissão marcada: dá para acertar a conta da garota só com os shows dela, ou fechá-la sem valor,
        usando o número da própria comanda. Garota cadastrada e ativa abre direto; inativa ou fora do cadastro pergunta antes
        (a comanda de um cliente também chega aqui, e a resposta Não mantém o aviso de sempre)."""
        if not v["comanda"] or not self.ctx.comissoes.ligada():
            return False
        g = self.ctx.comissoes.garota(v["posicao"])
        if g is not None and g["ativo"]:
            return True
        quem = "está inativa" if g is not None else "não está cadastrada"
        return tema.confirmar(self, f"A comanda {v['posicao']} está vazia e a garota {v['posicao']} {quem}.\n"
                                    "Acertar a conta dela mesmo assim (shows ou sem valor)?", "Acertar a garota", padrao_sim=False)

    def _pagar_comissao(self, v: dict) -> None:
        """F12 na comanda da garota: acerta com ela o que está marcado e os shows que o operador lançar (recibo e, se marcado,
        sangria no caixa)."""
        numero = v["posicao"]
        pag = comissao_ui.pagar_garota(self, self.ctx, numero)
        if pag is not None:
            self.recarregar()
            self.avisar(f"Conta da garota {numero} fechada sem valor a pagar." if not pag["total_cent"] else
                        f"Comissão de {fmt.fmt_brl(pag['total_cent'])} paga à garota {numero}." if not pag["shows"] else
                        f"Acerto de {fmt.fmt_brl(pag['total_cent'])} pago à garota {numero} "
                        f"(comissão {fmt.fmt_brl(pag['comissao_cent'])} + {pag['shows']} shows {fmt.fmt_brl(pag['shows_cent'])}).",
                        tema.COR["ok"])
        self.ent_codigo.focus_set()

    def _cancelar_comissao(self, iid) -> None:
        """Delete (ou Enter, no modo cancelar) numa linha de comissão da comanda da garota."""
        lanc = next((c for c in self.comissao_marcada if f"c{c['id']}" == str(iid)), None)
        if lanc is None:
            return
        if lanc["status"] != "pendente":
            tema.aviso(self, "Esta comissão já foi paga: não pode mais ser cancelada.")
            return
        quem = f"a comissão de {fmt.fmt_brl(lanc['valor_cent'])} da garota {lanc['garota']}"
        if comissao_ui.cancelar_lancamento(self, self.ctx, lanc["id"], quem, ja_autorizado=self.modo_cancelar):
            self.modo_cancelar = False
            self.recarregar()
            self.avisar("Comissão cancelada.", tema.COR["aviso"])
            self.ent_codigo.focus_set()

    def comissoes(self) -> None:
        """Botão Comissões: o que há a pagar a cada garota, pagamento com recibo e cancelamento de lançamento."""
        JanelaComissoes(self, self.ctx, ao_mudar=self.recarregar)
        self.ent_codigo.focus_set()

    def liberar_saida(self) -> None:
        """Código 1002 digitado na comanda do cliente que não consumiu nada: libera a posição e imprime o comprovante de
        saída (comanda, data, hora). Sem comanda na tela, pergunta qual."""
        v = self.venda()
        if v and v["modalidade"] == "mesa":
            pos = (bool(v["comanda"]), v["posicao"])
        else:
            comum, outra = self._exemplos()
            pos = self._pedir_posicao("Saída sem consumo", f"Comanda (ex.: {comum}) ou mesa (ex.: {outra}) que vai sair:")
            if pos is None:
                self.ent_codigo.focus_set()
                return
        ok, info = tema.tratar(self, self.ctx.caixa.liberar_saida, *pos)
        if not ok:
            self.ent_codigo.focus_set()
            return
        if self.venda_id and not self.ctx.banco.valor("SELECT 1 FROM vendas WHERE id = ? AND status IN ('aberta','conta_enviada')",
                                                      (self.venda_id,)):
            self.venda_id = None
        enviar_ou_mostrar(self, self.ctx, "Ticket de saída", self.ctx.impressao.comprovante_saida(info, self.ctx.operador.nome),
                          f"saida_{info['rotulo']}", tipo="saida")
        self.recarregar()
        self.avisar(f"Saída liberada: {info['nome']} sem consumo.", tema.COR["ok"])
        self.ent_codigo.focus_set()

    def consultar_comanda(self) -> None:
        """Botão Consulta Comanda (a conferência da saída): a comanda ou mesa está paga? Ainda deve? Sem mexer na venda da tela."""
        comum, outra = self._exemplos()
        pos = self._pedir_posicao("Consulta de comanda", f"Número da comanda (ex.: {comum}) ou da mesa (ex.: {outra}):")
        if pos is None:
            return
        comanda, numero = pos
        s = self.ctx.caixa.situacao_posicao(comanda, numero)
        nome, quando = nome_posicao(comanda, numero), fmt.fmt_datahora(s.get("quando"))[:16]
        if s["situacao"] == "paga":
            texto, tipo = f"{nome}: PAGA\nCupom {s['cupom']}  -  {fmt.fmt_brl(s['total_cent'])}\nem {quando}", "info"
        elif s["situacao"] == "aberta":
            texto, tipo = (f"{nome}: ABERTA - A PAGAR {fmt.fmt_brl(s['total_cent'])}\n{s['itens']} item(ns), desde {quando}"
                           + ("\nA conta já foi enviada ao cliente." if s["conta_enviada"] else ""), "aviso")
        elif s["situacao"] == "vazia":
            texto, tipo = f"{nome}: aberta, sem nenhum consumo.", "info"
        elif s["situacao"] == "cancelada":
            texto, tipo = f"{nome}: a última venda foi CANCELADA ({fmt.fmt_brl(s['total_cent'])}) em {quando}.", "aviso"
        else:
            texto, tipo = f"{nome}: nenhum registro.", "info"
        a_pagar = self.ctx.comissoes.pendente(numero) if comanda else 0
        if a_pagar:
            texto += f"\n\nComissão da garota {numero} a pagar: {fmt.fmt_brl(a_pagar)}."
        tema.mensagem(self, texto, "Consulta de comanda", tipo)
        self.ent_codigo.focus_set()

    def repique(self) -> None:
        if not self.com_mesas:          # a caixinha é deixada na mesa ou comanda: no balcão não existe
            return
        v = self.venda()
        if v and v["modalidade"] == "mesa":
            comanda, pos = bool(v["comanda"]), v["posicao"]
        else:
            comum, outra = self._exemplos()
            r = tema.pedir_texto(self, "Repique", f"Comanda ou mesa (ex.: {comum} ou {outra}) que deixou o repique:", "", largura=14,
                                 validar=self.ctx.caixa.ler_posicao)
            if r is None:
                return
            comanda, pos = r
        valor = tema.pedir_dinheiro(self, "Repique", "Valor deixado pelo cliente (R$):")
        if valor is None:
            return
        t = self.ctx.turnos.atual()
        ok, _ = tema.tratar(self, self.ctx.turnos.repique, t["id"], self.ctx.operador_id, pos, valor, comanda)
        if ok:
            self.avisar(f"Repique de {fmt.fmt_brl(valor)} registrado.", tema.COR["ok"])

    def sangria(self) -> None:
        if not self._autorizar("caixa_sangria", "exigir_senha_sangria", "Sangria exige autorização:"):
            return
        t = self.ctx.turnos.atual()
        if caixa_dialogos.sangria(self, self.ctx, t["id"]):
            self.avisar("Movimento financeiro registrado.", tema.COR["ok"])

    def gaveta(self) -> None:
        if not self._autorizar("caixa_gaveta", "exigir_senha_gaveta", "Abrir a gaveta exige autorização:"):
            return
        self.ctx.banco.log("gaveta", "abertura manual", self.ctx.operador_id)
        try:
            self.ctx.gaveta().abrir()
            self.avisar("Gaveta aberta.", tema.COR["ok"])
        except DispositivoIndisponivel as e:
            tema.aviso(self, f"{e}\nA abertura foi registrada.", "Gaveta")

    def balanca(self) -> None:
        if self.produto is None:
            tema.aviso(self, "Lance o código do produto antes de capturar o peso.")
            return
        self._capturar_peso()

    def _capturar_peso(self) -> None:
        """Lê o peso da balança configurada em Configurações > Máquinas; sem balança (ou se ela não responder),
        pede o peso digitado. Usado pelo F2 e, direto, ao selecionar um produto marcado como 'Balança'."""
        try:
            peso = self.ctx.balanca().ler_peso()
        except DispositivoIndisponivel as e:
            txt = tema.pedir_texto(self, "Balança", f"{e}\nPeso (kg):", self.var_qtd.get())
            if not txt:
                return
            try:
                peso = fmt.para_qtd(txt)
            except ValueError:
                tema.aviso(self, "Peso inválido.")
                return
        self.ent_qtd.configure(state="normal")
        self.var_qtd.set(fmt.fmt_qtd(peso, 3).replace(".", ""))
        self.ent_qtd.focus_set()

    def rodizio(self) -> None:
        """Liga (ou desliga) o rodízio desta mesa/comanda: pergunta quantas pessoas; os produtos do
        subgrupo "incluso no rodízio" passam a entrar na conta pelo preço fixo por pessoa, não por item."""
        v = self.venda()
        if not self.venda_id or not v or v["modalidade"] != "mesa":
            tema.aviso(self, "Chame uma mesa ou comanda antes de ligar o rodízio.")
            return
        ligado = bool(v.get("rodizio"))
        rotulo = "Quantas pessoas estão no rodízio? (0 desliga o rodízio)" if ligado else \
            "Quantas pessoas estão no rodízio desta mesa?"
        pessoas = tema.pedir_numero(self, "Rodízio", rotulo, v["pessoas"] or 1, 0 if ligado else 1, 999)
        if pessoas is None:
            return
        if pessoas == 0:
            ok, _ = tema.tratar(self, self.ctx.caixa.desativar_rodizio, self.venda_id)
        else:
            ok, _ = tema.tratar(self, self.ctx.caixa.ativar_rodizio, self.venda_id, pessoas)
        if ok:
            self.recarregar()
            self.avisar("Rodízio desligado." if pessoas == 0 else f"Rodízio: {pessoas} pessoa(s).", tema.COR["ok"])

    def recarga(self) -> None:
        """Pré-pago: carrega crédito na comanda (ou mesa) que está na tela. Daí em diante ela só consome até o saldo, e na
        saída (F12) a sobra volta ao cliente."""
        v = self.venda()
        if not self.venda_id or not v or v["modalidade"] != "mesa":
            tema.aviso(self, "Chame a comanda do cliente antes de carregar o crédito.")
            return
        onde = nome_posicao(v["comanda"], v["posicao"]).lower()
        valor = tema.pedir_dinheiro(self, "Recarga", f"Crédito a carregar na {onde}:")
        if valor is None:
            return
        formas = self.ctx.caixa.formas_pagamento()
        forma = tema.escolher(self, "Recarga", [(f["id"], f["tipo"]) for f in formas],
                              f"Como o cliente pagou os {fmt.fmt_brl(valor)}?", altura=max(len(formas), 1))
        if forma is None:
            return
        ok, _ = tema.tratar(self, self.ctx.caixa.recarregar, self.venda_id, forma, valor)
        if ok:
            self.recarregar()
            saldo = self.ctx.caixa.saldo_prepago(self.venda_id)["saldo"]
            self.avisar(f"Crédito de {fmt.fmt_brl(valor)} carregado na {onde}. Saldo: {fmt.fmt_brl(saldo)}.", tema.COR["ok"])

    def alternar_leitor(self) -> None:
        self.leitor = not self.leitor
        self.lbl_leitor.configure(text="LEITOR ÓPTICO ATIVO" if self.leitor else "")
        self.avisar("Leitor óptico " + ("ativado: cada item entra com quantidade 1." if self.leitor else "desativado."))

    def impressora(self) -> None:
        op = tema.escolher(self, "Impressora", [
            ("2via_ult", "Reimprimir último cupom (2ª via)"),
            ("2via_num", "Reimprimir cupom por número (2ª via)"),
            ("fila", "Fila de impressão (ver, reenviar, cancelar)"),
            ("x", "Leitura X (parcial do turno - gerencial)"),
            ("z", "Redução Z (fechamento do dia - gerencial)")],
            "Escolha (nenhuma função emite documento fiscal):", altura=5)
        if op == "x":
            t = self.ctx.turnos.atual()
            enviar_ou_mostrar(self, self.ctx, "Leitura X", self.ctx.impressao.leitura_x(t["id"]), "leitura_x", tipo="fechamento")
        elif op == "z":
            enviar_ou_mostrar(self, self.ctx, "Redução Z", self.ctx.impressao.reducao_z(), "reducao_z", tipo="relatorio")
        elif op == "fila":
            self.abrir_fila()
        elif op == "2via_ult":
            self._reimprimir(self._ultimo_cupom())
        elif op == "2via_num":
            n = tema.pedir_numero(self, "Reimprimir cupom", "Número do cupom:", "", 1)
            if n is not None:
                vid = self.ctx.banco.valor("SELECT id FROM vendas WHERE cupom = ? AND status IN ('fechada','cancelada')", (n,))
                if vid is None:
                    tema.aviso(self, f"Cupom {n} não encontrado entre as vendas fechadas/canceladas.")
                else:
                    self._reimprimir(vid)

    def _ultimo_cupom(self) -> int | None:
        return self.ctx.banco.valor(
            "SELECT id FROM vendas WHERE cupom IS NOT NULL AND status IN ('fechada','cancelada') ORDER BY cupom DESC LIMIT 1")

    def _reimprimir(self, venda_id: int | None) -> None:
        if venda_id is None:
            tema.aviso(self, "Ainda não há cupom para reimprimir.")
            return
        texto = self.ctx.impressao.cupom(venda_id, segunda_via=True)
        n = self.ctx.banco.valor("SELECT cupom FROM vendas WHERE id = ?", (venda_id,))
        enviar_ou_mostrar(self, self.ctx, f"2ª via cupom {n}", texto, f"2via_cupom_{n}", tipo="cupom", venda_id=venda_id)

    def fechar_turno(self) -> None:
        v = self.venda()
        if v and self.ctx.caixa.itens(v["id"]) and v["modalidade"] in ("balcao", "caderneta"):
            tema.aviso(self, "Há uma venda em andamento. Conclua ou cancele antes de trocar o turno.")
            return
        self._descartar_se_vazia()
        self.venda_id = None
        if caixa_dialogos.trocar_turno(self, self.ctx):
            self.destroy()

    def sair(self) -> None:
        v = self.venda()
        if v and v["modalidade"] == "balcao" and self.ctx.caixa.itens(v["id"]):
            if not tema.confirmar(self, "Há uma venda em andamento no balcão.\nSair mantém a venda aberta para continuar depois. Sair mesmo?", "Sair do caixa"):
                return
        else:
            try:
                self._descartar_se_vazia()
            except ErroNegocio:
                pass
        self.destroy()

    # ============================================================== barra
    def _entrar_barra(self) -> None:
        self.indice_barra = 0
        self._pintar_barra()
        self.avisar("Barra de tarefas: use as setas e Enter. Esc volta. (Pagar já está selecionado)")

    def _sair_barra(self) -> None:
        self.indice_barra = None
        self._ocultar_opcoes()
        self._pintar_barra()
        self.avisar("")
        self.ent_codigo.focus_set()

    def _barra_mover(self, d: int) -> None:
        if self.indice_barra is not None:
            self.indice_barra = (self.indice_barra + d) % len(self.tarefas)
            self._pintar_barra()

    def _barra_enter(self, _=None) -> str:
        i = self.indice_barra
        self._sair_barra()
        if i is not None:
            self.tarefas[i][1]()
        return "break"

    def _barra_esc(self, _=None) -> str:
        self._sair_barra()
        return "break"

    def _exec_barra(self, fn) -> None:
        self._ocultar_opcoes()
        if self.indice_barra is not None:
            self._sair_barra()
        fn()

    def _pintar_barra(self) -> None:
        for i, b in enumerate(self.botoes_tarefa):
            b.configure(style="Cx.Sel.TButton" if i == self.indice_barra else self._estilos_base[i])
        if self.indice_barra is not None:
            if self._n_fixos <= self.indice_barra < len(self.tarefas) - 1:
                if not self.opcoes.winfo_viewable():
                    self._mostrar_opcoes()
            elif self.opcoes.winfo_viewable():
                self._ocultar_opcoes()
                self.ent_codigo.focus_set()
            self.status.configure(text=self.tarefas[self.indice_barra][0])
