"""Painel de pagamento do caixa (manual do Caixa: 'Fechar uma venda escolhendo a forma de pagamento').

Fluxo por teclado: forma de pagamento (setas, o número da forma ou a inicial) -> Enter -> valor -> Enter.
Seta para cima chega a Desconto/Serviço; Esc volta ao lançamento de itens sem fechar a venda.
Com o mouse (ou o toque): um clique na forma já leva ao valor; os botões da direita lançam e removem.

Proteções contra erro de digitação (o caixa não pode travar nem fechar com um valor absurdo): o valor só aceita número
(sem 1e5, sem sinal, no máximo 2 casas); forma que não dá troco (débito, crédito, Pix) não aceita mais do que falta; troco
alto pede confirmação; fechar duas vezes seguidas não grava duas vezes."""
from __future__ import annotations

import re
import tkinter as tk
from decimal import Decimal
from tkinter import ttk

from src.controllers.caixa_controller import LIMITE_PARTES_DIVISAO
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.ui import caixa_dialogos, caixa_tema, tema
from src.ui.caixa_tema import CX
from src.ui.visualizador import enviar_ou_mostrar

LIMITE_VALOR_CENT = 100_000_000       # R$ 1.000.000,00: acima disso é erro de digitação (e estoura o banco de dados)
LIMITE_TROCO_CENT = 50_000            # troco acima de R$ 500,00 pede confirmação
_PADRAO_VALOR = re.compile(r"^(?:[0-9]{1,3}(?:\.[0-9]{3})+(?:,[0-9]{1,2})?|[0-9]+(?:[.,][0-9]{1,2})?|[.,][0-9]{1,2})$")


def ler_valor_pagamento(texto: str) -> int:
    """Valor digitado -> centavos. Aceita '25', '25,5', '25.50', '1.000' (mil) e '1.000,50'; recusa letras, sinal, notação
    científica ('1e5'), mais de 2 casas decimais, zero e valores absurdos. Levanta ValueError com a mensagem para o operador."""
    s = (texto or "").strip().replace("R$", "").replace(" ", "")
    if not s:
        raise ValueError("Digite o valor recebido.")
    if not _PADRAO_VALOR.match(s):
        raise ValueError("Valor inválido. Digite só números, com vírgula nos centavos (ex.: 25,50).")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"[0-9]{1,3}\.[0-9]{3}", s):      # 1.000 e 1.000.000 são milhares
        s = s.replace(".", "")
    cent = int((Decimal(s) * 100).to_integral_value())
    if cent <= 0:
        raise ValueError("O valor deve ser maior que zero.")
    if cent > LIMITE_VALOR_CENT:
        raise ValueError(f"Valor alto demais (acima de {fmt.fmt_brl(LIMITE_VALOR_CENT)}). Confira a digitação.")
    return cent


class JanelaPagamento(tk.Toplevel):
    def __init__(self, master, ctx, venda_id: int):
        super().__init__(master)
        self.ctx, self.venda_id = ctx, venda_id
        self.caixa = ctx.caixa
        self.fechou = False
        self._fechando = False
        self._falta = 0
        self._divisao: list[int] | None = None
        self._parte_atual = 0
        try:
            self._abrir(master, venda_id)
        except Exception:
            self.destroy()          # nunca deixa uma janela vazia (ou uma trava de teclado) para trás
            raise

    def _abrir(self, master, venda_id: int) -> None:
        self.formas = self.caixa.formas_pagamento()
        if not self.formas:
            self.withdraw()
            tema.aviso(master, "Nenhuma forma de pagamento está habilitada para o caixa.\n"
                               "Ative em Manutenção de Cadastros > Tipos de Pagamento (marque 'Caixa').")
            self.destroy()
            return
        self.desconto_autorizado = not self.ctx.acesso.precisa_senha(self.ctx.operador, "caixa_desconto", "exigir_senha_desconto")
        self.title("Pagamento")
        caixa_tema.aplicar(self)
        self.configure(bg=CX["fundo"])
        v = self.caixa.obter(venda_id)
        self.eh_credito = v["modalidade"] == "caderneta" and not self.caixa.itens(venda_id)
        self._montar(v)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<F10>", lambda e: self.fechar_venda())
        self.atualizar()
        # transient ANTES de centralizar (centralizar mapeia a janela), e só se a janela-mãe está à vista
        topo = master.winfo_toplevel()
        try:
            if topo.winfo_viewable():
                self.transient(topo)
        except tk.TclError:
            pass
        tema.centralizar(self, topo)
        tema.modalizar(self)
        self.grade_formas.tree.focus_set()
        self.grade_formas.selecionar_indice(0)
        self.wait_window(self)

    # --------------------------------------------------------------- layout
    def _montar(self, v: dict) -> None:
        corpo = tk.Frame(self, bg=CX["fundo"], padx=18, pady=16)
        corpo.pack(fill="both", expand=True)
        esq = tk.Frame(corpo, bg=CX["fundo"], width=330)
        esq.grid(row=0, column=0, sticky="ns", padx=(0, 18))
        esq.grid_propagate(True)

        cartao = tk.Frame(esq, bg=CX["cartao"], highlightthickness=1, highlightbackground=CX["borda"])
        cartao.pack(fill="x")
        tk.Frame(cartao, height=3, bg=CX["verde"]).pack(fill="x")
        dentro = tk.Frame(cartao, bg=CX["cartao"], padx=16, pady=8)
        dentro.pack(fill="x")
        tk.Label(dentro, text="TOTAL A PAGAR" if not self.eh_credito else "RECEBIDO", bg=CX["cartao"], fg=CX["suave"],
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        linha = tk.Frame(dentro, bg=CX["cartao"])
        linha.pack(fill="x")
        tk.Label(linha, text="R$", bg=CX["cartao"], fg=CX["suave"], font=("Segoe UI", 16, "bold")).pack(side="left", anchor="s", pady=(0, 10))
        self.lbl_total = tk.Label(linha, text="0,00", bg=CX["cartao"], fg=CX["verde"], font=("Segoe UI", 38, "bold"), anchor="e")
        self.lbl_total.pack(side="right")
        tk.Frame(dentro, height=1, bg=CX["borda"]).pack(fill="x", pady=(2, 6))
        trc = tk.Frame(dentro, bg=CX["cartao"])
        trc.pack(fill="x")
        self.lbl_troco_rotulo = tk.Label(trc, text="Troco:", bg=CX["cartao"], fg=CX["suave"], font=("Segoe UI", 13, "bold"))
        self.lbl_troco_rotulo.pack(side="left")
        self.lbl_troco = tk.Label(trc, text="0,00", bg=CX["cartao"], fg=CX["azul"], font=("Segoe UI", 24, "bold"))
        self.lbl_troco.pack(side="right")

        grade = tk.Frame(esq, bg=CX["fundo"])
        grade.pack(fill="x", pady=(12, 0))
        self.var_pct, self.var_desc, self.var_serv = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Label(grade, text="Desc. %", style="Cx.Rotulo.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(grade, text="Desc. R$", style="Cx.Rotulo.TLabel").grid(row=0, column=1, sticky="w")
        self.e_pct = ttk.Entry(grade, textvariable=self.var_pct, width=8, style="Cx.TEntry")
        self.e_desc = ttk.Entry(grade, textvariable=self.var_desc, width=14, style="Cx.TEntry")
        self.e_pct.grid(row=1, column=0, padx=(0, 8))
        self.e_desc.grid(row=1, column=1)
        ttk.Label(grade, text="Serviço R$", style="Cx.Rotulo.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.e_serv = ttk.Entry(grade, textvariable=self.var_serv, width=14, style="Cx.TEntry")
        self.e_serv.grid(row=3, column=0, columnspan=2, sticky="w")
        self.lbl_resumo = ttk.Label(esq, text="", justify="left", font=tema.FONTE_MONO, style="Cx.TLabel")
        self.lbl_resumo.pack(anchor="w", pady=(12, 0))
        self.lbl_msg = ttk.Label(esq, text="", style="Cx.TLabel", foreground=CX["vermelho"], wraplength=320, justify="left",
                                 font=("Segoe UI", 10, "bold"))
        self.lbl_msg.pack(anchor="w", pady=(8, 0))

        dir_ = tk.Frame(corpo, bg=CX["fundo"])
        dir_.grid(row=0, column=1, sticky="nsew")
        corpo.columnconfigure(1, weight=1)
        ttk.Label(dir_, text="FORMA DE PAGAMENTO   (setas, o número ou a inicial)", style="Cx.Rotulo.TLabel").pack(anchor="w")
        self.grade_formas = tema.Grade(dir_, [("tipo", "Forma", 300, "w"), ("tecla", "Tecla", 70, "center")], altura=min(max(len(self.formas), 3), 5),
                                       estilo="CxForma", cor_par=CX["linha_par"])
        self.grade_formas.pack(fill="x", pady=(4, 0))
        for n, f in enumerate(self.formas, start=1):
            self.grade_formas.adicionar([f["tipo"], str(n) if n <= 9 else ""], iid=f["id"])
        ttk.Label(dir_, text="VALOR RECEBIDO (R$)   Enter lança", style="Cx.Rotulo.TLabel").pack(anchor="w", pady=(12, 0))
        self.var_valor = tk.StringVar()
        self.e_valor = ttk.Entry(dir_, textvariable=self.var_valor, width=16, font=("Segoe UI", 20, "bold"), style="Cx.TEntry")
        self.e_valor.pack(anchor="w", pady=(4, 0))
        cab = tk.Frame(dir_, bg=CX["fundo"])
        cab.pack(fill="x", pady=(12, 0))
        ttk.Label(cab, text="PAGAMENTOS LANÇADOS", style="Cx.Rotulo.TLabel").pack(side="left")
        self.btn_remover = ttk.Button(cab, text="Remover (Delete)", style="Cx.Perigo.TButton", takefocus=False,
                                      command=self._remover_pagamento)
        self.btn_remover.pack(side="right")
        if not self.eh_credito:        # dívida de caderneta não se divide entre pessoas
            ttk.Button(cab, text="Dividir conta", takefocus=False, command=self._dividir_conta).pack(
                side="right", padx=(0, 6))
        self.grade_pag = tema.Grade(dir_, [("tipo", "Pagamento", 220, "w"), ("valor", "Valor", 110, "e")], altura=4,
                                    estilo="Cx", cor_par=CX["linha_par"])
        self.grade_pag.pack(fill="x", pady=(4, 0))
        texto_botao = "Lançar crédito (F10)" if self.eh_credito else "Gravar conta / imprimir (F10)"
        self.btn_fechar = ttk.Button(dir_, text=texto_botao, style="Cx.Pagar.TButton", command=self.fechar_venda)
        self.btn_fechar.pack(fill="x", pady=(16, 0))
        self.btn_fechar.bind("<Return>", lambda ev: (self.fechar_venda(), "break")[1])
        ttk.Button(dir_, text="Voltar para os itens (Esc)", style="Cx.TButton", command=self.destroy).pack(fill="x", pady=(6, 0))

        t = self.grade_formas.tree
        t.bind("<Return>", self._forma_escolhida)
        t.bind("<Up>", self._acima_da_lista)
        t.bind("<Key>", self._tecla_forma)
        t.bind("<ButtonRelease-1>", lambda e: self.after_idle(self._clique_na_forma))
        t.bind("<<TreeviewSelect>>", lambda e: self._sugerir_valor(self._falta))     # crédito: o valor sugerido já vem com a taxa
        self.e_valor.bind("<Return>", self._lancar_valor)
        self.e_valor.bind("<Escape>", lambda e: (self.grade_formas.tree.focus_set(), "break")[1])
        self.grade_pag.tree.bind("<Delete>", self._remover_pagamento)
        for e in (self.e_pct, self.e_desc):
            e.bind("<Return>", self._aplicar_desconto)
        self.e_pct.bind("<Down>", lambda e: self.e_desc.focus_set())
        self.e_desc.bind("<Down>", lambda e: self.e_serv.focus_set())
        self.e_serv.bind("<Return>", self._aplicar_servico)
        self.e_serv.bind("<Down>", lambda e: self.grade_formas.tree.focus_set())
        for e in (self.e_pct, self.e_desc, self.e_serv):
            e.bind("<Escape>", lambda ev: (self.grade_formas.tree.focus_set(), "break")[1])
        if v["modalidade"] != "mesa":
            self.e_serv.configure(state="disabled")
        if self.eh_credito or not self.ctx.banco.cfg_bool("usar_desconto", False):     # boate: sem desconto (configurável)
            for e in (self.e_pct, self.e_desc):
                e.configure(state="disabled")
        desligados = [e for e in (self.e_pct, self.e_desc, self.e_serv) if str(e.cget("state")) == "disabled"]
        if len(desligados) == 3:
            grade.pack_forget()                      # sem desconto nem serviço: nada de campos mortos na tela
        else:
            for e in desligados:
                e.grid_remove()

    # ----------------------------------------------------------- atualização
    def atualizar(self) -> None:
        self.caixa.recalcular(self.venda_id)
        v = self.caixa.obter(self.venda_id)
        pags = self.caixa.pagamentos(self.venda_id)
        self.grade_pag.preencher([[p["tipo"], fmt.fmt_num(p["valor_cent"])] for p in pags], [p["id"] for p in pags])
        pago = sum(p["valor_cent"] for p in pags)
        total = v["total_cent"]
        self.lbl_total.configure(text=fmt.fmt_num(total if not self.eh_credito else max(pago, 0)))
        linhas = [f"Desc.    : {fmt.fmt_num(v['desconto_cent']):>10}", f"Serviço  : {fmt.fmt_num(v['servico_cent']):>10}",
                  f"{'Compl.' if v.get('comanda') else 'Taxa'}    : {fmt.fmt_num(v['taxa_cent']):>10}", f"Produtos : {fmt.fmt_num(v['subtotal_cent']):>10}",
                  f"Pago     : {fmt.fmt_num(pago):>10}"]
        if v["acrescimo_cent"]:
            linhas.insert(3, f"Tx créd. : {fmt.fmt_num(v['acrescimo_cent']):>10}")
        self.lbl_resumo.configure(text="\n".join(linhas))
        self.lbl_msg.configure(text="")
        if self.eh_credito:
            info = self.caixa.info_credito(self.venda_id)
            self.lbl_troco_rotulo.configure(text="Dívida:")
            self.lbl_troco.configure(text=fmt.fmt_num(info["divida"]), fg=CX["vermelho"])
            return
        try:
            liq = self.caixa.liquidar(self.venda_id, total)
        except ErroNegocio as e:
            self.lbl_msg.configure(text=str(e), foreground=CX["vermelho"])
            self.lbl_troco_rotulo.configure(text="Troco:")
            self.lbl_troco.configure(text="--", fg=CX["vermelho"])
            return
        if liq["falta"] > 0:
            self.lbl_troco_rotulo.configure(text="Falta:")
            self.lbl_troco.configure(text=fmt.fmt_num(liq["falta"]), fg=CX["vermelho"])
            if self._divisao:
                self._aviso(f"Dividir conta: parte {self._parte_atual + 1} de {len(self._divisao)} — "
                            f"{fmt.fmt_brl(self._divisao[self._parte_atual])}", CX["azul"])
        else:
            self.lbl_troco_rotulo.configure(text="Troco:")
            self.lbl_troco.configure(text=fmt.fmt_num(liq["troco"]), fg=CX["azul"])
            if liq["vale"]:
                self.lbl_msg.configure(text=f"Será emitido contra-vale de {fmt.fmt_brl(liq['vale'])}.",
                                       foreground=CX["ambar"])
        self._sugerir_valor(liq["falta"])

    def _sugerir_valor(self, falta: int) -> None:
        """O que falta receber; se a forma escolhida tem acréscimo (crédito: R$ 5,00) e a venda ainda não o cobra, já vem somado,
        para o cartão passar com a taxa e a conta fechar. Durante a divisão da conta, sugere a parte atual em vez da falta inteira."""
        self._falta = falta
        if self._divisao:
            self.var_valor.set(fmt.fmt_num(self._divisao[self._parte_atual]))
            return
        forma = self.grade_formas.selecionado() if hasattr(self, "grade_formas") else None
        acrescimo = self.caixa.acrescimo_da_forma(self.venda_id, int(forma)) if forma is not None and falta > 0 else 0
        self.var_valor.set(fmt.fmt_num(falta + acrescimo) if falta > 0 else "")
        if acrescimo:
            self._aviso(f"Crédito: taxa de {fmt.fmt_brl(acrescimo)} acrescentada ao total.", CX["ambar"])
        elif forma is not None and self.lbl_msg.cget("text").startswith("Crédito: taxa"):
            self.lbl_msg.configure(text="")

    def _aviso(self, texto: str, cor: str | None = None) -> None:
        self.lbl_msg.configure(text=texto, foreground=cor or CX["vermelho"])

    # --------------------------------------------------------------- teclado
    def _tecla_forma(self, e) -> str | None:
        if len(e.char) == 1 and e.char.isalnum():
            filhos = self.grade_formas.tree.get_children()
            if e.char.isdigit():                                  # 1 = primeira forma da lista, 2 = segunda...
                n = int(e.char)
                if 1 <= n <= len(filhos):
                    self.grade_formas.selecionar_indice(n - 1)
                    self._forma_escolhida()
                return "break"
            letra = e.char.lower()
            atual = self.grade_formas.indice()
            ordem = [(i, self.grade_formas.valores(filhos[i])[0].lower().split())
                     for i in list(range(atual + 1, len(filhos))) + list(range(0, atual + 1))]
            # a inicial da última palavra vale primeiro (Cartão Crédito = C, Cartão Débito = D, Pix = P); sem ela, a de qualquer palavra
            for acerta in (lambda palavras: palavras[-1].startswith(letra), lambda palavras: any(p.startswith(letra) for p in palavras)):
                achou = next((i for i, palavras in ordem if palavras and acerta(palavras)), None)
                if achou is not None:
                    self.grade_formas.selecionar_indice(achou)
                    break
            return "break"
        return None

    def _acima_da_lista(self, e) -> str | None:
        if self.grade_formas.indice() <= 0:
            (self.e_pct if str(self.e_pct.cget("state")) != "disabled" else self.e_serv).focus_set()
            return "break"
        return None

    def _clique_na_forma(self) -> None:
        if self.winfo_exists() and self.grade_formas.selecionado() is not None:
            self._forma_escolhida()

    def _forma_escolhida(self, e=None) -> str:
        if self.grade_formas.selecionado() is None:
            return "break"
        self.e_valor.focus_set()
        self.e_valor.selection_range(0, "end")
        return "break"

    def _receber(self, forma_id: int, cent: int) -> tuple[int, dict]:
        """Grava o pagamento e confere o fechamento da conta; se a forma não pode ficar com a sobra (troco), desfaz tudo."""
        pago_antes = sum(p["valor_cent"] for p in self.caixa.pagamentos(self.venda_id))
        with self.ctx.banco.transacao():
            pid = self.caixa.adicionar_pagamento(self.venda_id, forma_id, cent)
            if self.eh_credito:
                return pid, {"troco": 0}
            total = self.caixa.obter(self.venda_id)["total_cent"]       # já com a taxa do crédito, se esta forma a cobra
            try:
                return pid, self.caixa.liquidar(self.venda_id, total)
            except ErroNegocio:
                nome = next((f["tipo"] for f in self.formas if int(f["id"]) == forma_id), "Esta forma")
                raise ErroNegocio(f"{nome} não dá troco: o valor não pode passar do que falta ({fmt.fmt_brl(max(total - pago_antes, 0))}).") from None

    def _lancar_valor(self, e=None) -> str:
        forma = self.grade_formas.selecionado()
        if forma is None:
            self._aviso("Escolha a forma de pagamento (setas ou o número da forma).")
            self.grade_formas.tree.focus_set()
            return "break"
        try:
            cent = ler_valor_pagamento(self.var_valor.get())
        except ValueError as ex:
            self._aviso(str(ex))
            self.e_valor.focus_set()
            self.e_valor.selection_range(0, "end")
            return "break"
        ok, r = tema.tratar(self, self._receber, int(forma), cent)
        if not ok:
            self.atualizar()
            return "break"
        pid, liq = r
        if liq.get("troco", 0) > LIMITE_TROCO_CENT and not tema.confirmar(
                self, f"O troco será de {fmt.fmt_brl(liq['troco'])} (recebido: {fmt.fmt_brl(cent)}).\nO valor recebido está certo?",
                "Troco alto", sim="Está certo", nao="Corrigir"):
            tema.tratar(self, self.caixa.remover_pagamento, pid)
            self._divisao = None           # desfez o lançamento: sai da divisão para não ficar com estado incoerente
            self.atualizar()
            self.e_valor.focus_set()
            self.e_valor.selection_range(0, "end")
            return "break"
        if self._divisao:
            self._parte_atual += 1
            if self._parte_atual >= len(self._divisao) or self.caixa.liquidar(self.venda_id)["falta"] <= 0:
                self._divisao = None       # dividiu tudo (ou alguém já cobriu o resto)
        self.atualizar()
        pago = sum(p["valor_cent"] for p in self.caixa.pagamentos(self.venda_id))
        if self.eh_credito or pago >= self.caixa.obter(self.venda_id)["total_cent"]:
            self.btn_fechar.focus_set()
        else:
            self.grade_formas.tree.focus_set()
        return "break"

    def _remover_pagamento(self, e=None) -> str:
        s = self.grade_pag.selecionado()
        if s is None and self.grade_pag.total():
            s = self.grade_pag.tree.get_children()[-1]          # sem seleção: o último lançado (o erro mais comum)
        if s is None:
            self._aviso("Não há pagamento lançado para remover.", CX["ambar"])
            return "break"
        ok, _ = tema.tratar(self, self.caixa.remover_pagamento, int(s))
        if ok:
            self._divisao = None           # removeu um pagamento no meio da divisão: recomeça do zero se precisar
        self.atualizar()
        if ok:
            self._aviso("Pagamento removido.", CX["ambar"])
            self.grade_formas.tree.focus_set()
        return "break"

    def _dividir_conta(self, e=None) -> str:
        n = tema.pedir_numero(self, "Dividir conta", "Dividir o restante em quantas partes?", 2, 2, LIMITE_PARTES_DIVISAO)
        if n is None:
            return "break"
        ok, partes = tema.tratar(self, self.caixa.dividir_restante, self.venda_id, n)
        if not ok:
            return "break"
        self._divisao, self._parte_atual = partes, 0
        self.atualizar()
        self.grade_formas.selecionar_indice(0)
        self.grade_formas.tree.focus_set()
        return "break"

    def _autorizar_desconto(self) -> bool:
        if self.desconto_autorizado:
            return True
        sup = tema.pedir_senha_supervisor(self, self.ctx, "caixa_desconto", "Desconto exige autorização:")
        self.desconto_autorizado = sup is not None
        return self.desconto_autorizado

    def _aplicar_desconto(self, e=None) -> str:
        if not self._autorizar_desconto():
            return "break"
        pct, valor = self.var_pct.get().strip(), self.var_desc.get().strip()
        try:
            if pct:
                self.caixa.definir_desconto(self.venda_id, pct=float(pct.replace(",", ".")))
            else:
                self.caixa.definir_desconto(self.venda_id, valor_cent=fmt.para_centavos(valor) if valor else 0)
        except (ErroNegocio, ValueError) as ex:
            tema.erro(self, str(ex) if isinstance(ex, ErroNegocio) else "Valor de desconto inválido.")
            return "break"
        self.var_pct.set("")
        self.var_desc.set("")
        self.atualizar()
        self.grade_formas.tree.focus_set()
        return "break"

    def _aplicar_servico(self, e=None) -> str:
        texto = self.var_serv.get().strip()
        try:
            self.caixa.definir_servico(self.venda_id, fmt.para_centavos(texto) if texto else None)
        except (ErroNegocio, ValueError) as ex:
            tema.erro(self, str(ex) if isinstance(ex, ErroNegocio) else "Valor de serviço inválido.")
            return "break"
        self.var_serv.set("")
        self.atualizar()
        self.grade_formas.tree.focus_set()
        return "break"

    # -------------------------------------------------------------- fechamento
    def fechar_venda(self) -> None:
        if self._fechando or self.fechou or not self.winfo_exists():       # duas teclas F10 seguidas não gravam duas vezes
            return
        self._fechando = True
        try:
            self._fechar_venda()
        finally:
            self._fechando = False

    def _fechar_venda(self) -> None:
        v = self.caixa.obter(self.venda_id)
        garcom = pessoas = None
        if v["modalidade"] == "mesa":
            if self.ctx.banco.cfg_bool("controle_garcom") and not v["garcom_id"]:
                garcom = caixa_dialogos.escolher_garcom(self, self.ctx)
                if garcom is None:
                    return
            if self.ctx.banco.cfg_bool("pergunta_pessoas") and not v["pessoas"] and not v["comanda"]:
                pessoas = tema.pedir_numero(self, "Mesa", "Número de pessoas na mesa:", 1, 1, 999)
                if pessoas is None:
                    return
        credito = None
        if self.eh_credito:
            info = self.caixa.info_credito(self.venda_id)
            if info["excedente"] > 0:
                credito = tema.confirmar(
                    self, f"O valor excede a dívida do cliente em {fmt.fmt_brl(info['excedente'])}.\n"
                          "Acrescentar o excedente ao crédito do cliente?\n(Não = devolver como troco)", "Caderneta")
        ok, venda = tema.tratar(self, self.caixa.fechar, self.venda_id, garcom, pessoas, credito)
        if not ok:
            self.atualizar()
            return
        self.fechou = True
        master = self.master
        try:
            saida = self.ctx.impressao.saida_da_venda(self.venda_id)   # comanda/mesa paga: o ticket da portaria vai junto
        except Exception as e:  # noqa: BLE001 - a venda já está gravada: nada aqui pode impedir de fechar a janela
            saida = None
            self._registrar_falha_de_impressao(e)
        self.destroy()
        try:
            if self.ctx.banco.cfg_bool("imprimir_cupom", True):
                texto = self.ctx.impressao.cupom(self.venda_id)
                op = self.ctx.impressao.opcoes_cupom(self.venda_id)    # vias e gaveta conforme as formas de pagamento
                enviar_ou_mostrar(master, self.ctx, f"Cupom {venda['cupom']}", texto, f"cupom_{venda['cupom']}",
                                  tipo="cupom", abrir_gaveta=op["abrir_gaveta"], copias=op["copias"], venda_id=self.venda_id)
            if saida:
                enviar_ou_mostrar(master, self.ctx, "Ticket de saída", saida, f"saida_cupom_{venda['cupom']}", tipo="saida")
        except Exception as e:  # noqa: BLE001 - venda gravada: um erro de impressão não pode derrubar o caixa
            self._registrar_falha_de_impressao(e)
            tema.erro(master, f"A venda foi gravada (cupom {venda['cupom']}), mas não foi possível preparar a impressão:\n{e}\n"
                              "Reimprima o cupom pelo botão Impressora.")

    @staticmethod
    def _registrar_falha_de_impressao(e: Exception) -> None:
        from src.core import registro
        registro.registrar_excecao(type(e), e, e.__traceback__, origem="pagamento")
