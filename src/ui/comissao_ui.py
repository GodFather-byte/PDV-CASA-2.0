"""Comissão das garotas: lançar (o código 50 do caixa), imprimir a via dela, ver o que há a pagar, pagar com recibo e cancelar.

As funções soltas (`registrar_comissao`, `pagar_garota`, `cancelar_lancamento`, `conferir_lancamento`) são o que a tela do caixa
usa na linha de entrada, no F12 e no Delete; a janela do código 50 e a `JanelaComissoes` chamam as mesmas."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.controllers.comissao_controller import LIMITE_CONFIRMAR_CENT
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.ui import tema
from src.ui.visualizador import enviar_ou_mostrar


def autorizar(master, ctx, modulo: str, cfg: str, motivo: str) -> bool:
    """Pede a senha de supervisor quando a operação está configurada para exigi-la e o operador não tem nível."""
    if not ctx.acesso.precisa_senha(ctx.operador, modulo, cfg):
        return True
    return tema.pedir_senha_supervisor(master, ctx, modulo, motivo) is not None


def conferir_lancamento(master, ctx, numero: int, cent: int) -> str | None:
    """As perguntas antes de lançar: garota não cadastrada, inativa e valor alto. Devolve None se tudo foi confirmado, ou o
    campo a corrigir ('numero' ou 'valor') quando o operador respondeu Não."""
    g = ctx.comissoes.garota(numero)
    if g is None and not ctx.comissoes.cadastro_vazio():
        if not tema.confirmar(master, f"A garota {numero} não está cadastrada.\nLançar a comissão assim mesmo?",
                              "Garota não cadastrada", padrao_sim=False):
            return "numero"
    elif g is not None and not g["ativo"]:
        if not tema.confirmar(master, f"A garota {numero} - {g['nome']} está inativa.\nLançar a comissão assim mesmo?",
                              "Garota inativa", padrao_sim=False):
            return "numero"
    if cent > LIMITE_CONFIRMAR_CENT and not tema.confirmar(
            master, f"Valor alto: {fmt.fmt_brl(cent)} para a garota {numero}.\nConfirma?", "Confirma o valor", padrao_sim=False):
        return "valor"
    return None


def dialogo_comissao(master, ctx, sugerida: str = "") -> tuple[int, int] | None:
    """A janela do código 50: número da garota (já preenchido com o da comanda) e valor. Devolve (número, centavos) ou None."""
    dlg = tema.Dialogo(master, "Comissão da garota")
    ttk.Label(dlg.corpo, text="Número da garota", style="Rotulo.TLabel").pack(anchor="w")
    linha = ttk.Frame(dlg.corpo)
    linha.pack(fill="x")
    numero = tk.StringVar(value=str(sugerida or ""))
    en = ttk.Entry(linha, textvariable=numero, width=9, font=("Segoe UI", 18, "bold"), justify="center")
    en.pack(side="left")
    lbl_nome = ttk.Label(linha, text="", font=("Segoe UI", 14, "bold"), foreground=tema.COR["rotulo"])
    lbl_nome.pack(side="left", padx=12)
    ttk.Label(dlg.corpo, text=f"Comissão: {ctx.comissoes.rotulo_valor()}", style="Rotulo.TLabel").pack(anchor="w", pady=(12, 0))
    valor = tk.StringVar()
    ev = ttk.Entry(dlg.corpo, textvariable=valor, width=14, font=("Segoe UI", 18, "bold"), justify="right")
    ev.pack(anchor="w")
    msg = ttk.Label(dlg.corpo, text="", foreground=tema.COR["perigo"], wraplength=380)
    msg.pack(anchor="w", pady=(6, 0))

    def mostrar_nome(_=None) -> None:
        texto = numero.get().strip()
        try:
            n = ctx.comissoes.validar_numero(texto) if texto else None
        except ErroNegocio:
            n = None
        g = ctx.comissoes.garota(n) if n is not None else None
        if g is not None:
            lbl_nome.configure(text=g["nome"] + ("" if g["ativo"] else " (inativa)"),
                               foreground=tema.COR["rotulo"] if g["ativo"] else tema.COR["aviso"])
        elif n is not None and not ctx.comissoes.cadastro_vazio():
            lbl_nome.configure(text="não cadastrada", foreground=tema.COR["aviso"])
        else:
            lbl_nome.configure(text="")

    def gravar(_=None) -> None:
        try:
            n = ctx.comissoes.validar_numero(numero.get())
        except ErroNegocio as e:
            msg.configure(text=str(e))
            en.focus_set()
            return
        try:
            cent = ctx.comissoes.para_centavos(valor.get())
        except (ValueError, ErroNegocio) as e:
            msg.configure(text=str(e) if isinstance(e, ErroNegocio) else "Valor inválido.")
            ev.focus_set()
            return
        if cent <= 0:
            msg.configure(text="Informe o valor da comissão.")
            ev.focus_set()
            return
        campo = conferir_lancamento(dlg, ctx, n, cent)
        if campo is not None:
            (en if campo == "numero" else ev).focus_set()
            return
        dlg.ok((n, cent))

    tema._botoes(dlg, "Lançar", comando_ok=gravar)
    en.bind("<KeyRelease>", mostrar_nome)
    en.bind("<Return>", lambda e: (ev.focus_set(), "break")[1])
    ev.bind("<Return>", lambda e: (gravar(), "break")[1])
    mostrar_nome()
    if sugerida:
        ev.focus_set()
    return dlg.mostrar(ev if sugerida else en)


def entregar_via(ctx, lancamento_id: int) -> str:
    """Imprime a via que a garota leva a cada comissão lançada (config 'imprimir_via_comissao'). Devolve a frase para o status
    da tela. Sem impressora (modo tela) a via só fica gravada no histórico: abrir uma janela a cada lançamento travaria o caixa."""
    if not ctx.banco.cfg_bool("imprimir_via_comissao", True):
        return ""
    try:
        ctx.impressao.imprimir_via_comissao(lancamento_id, ctx.operador.nome)
    except Exception as e:  # noqa: BLE001 - a comissão já está gravada: falha de impressão nunca pode parecer falha do lançamento
        ctx.banco.log("via_comissao_falhou", f"lançamento {lancamento_id}: {e}"[:300], ctx.operador_id)
        return f" ATENÇÃO: a via da garota não foi impressa ({e})."
    if ctx.impressao.deve_mostrar_na_tela():
        return " Sem impressora configurada: a via ficou só no histórico."
    return " Via da garota enviada para a impressora."


def registrar_comissao(master, ctx, turno_id: int, numero: int, cent: int, ao_lancar=None) -> int | None:
    """Grava a comissão, imprime a via da garota e avisa o operador. Devolve o id do lançamento ou None se não gravou."""
    ok, lancamento_id = tema.tratar(master, ctx.comissoes.lancar, numero, cent, turno_id, ctx.operador_id)
    if not ok:
        return None
    nome = ctx.comissoes.nome(numero)
    texto = (f"Comissão de {fmt.fmt_brl(cent)} lançada para a garota {numero}{' ' + nome if nome else ''}. "
             f"A pagar a ela: {fmt.fmt_brl(ctx.comissoes.pendente(numero))}.") + entregar_via(ctx, lancamento_id)
    if ao_lancar:
        ao_lancar(texto)
    return lancamento_id


def lancar(master, ctx, sugerida: str = "", ao_lancar=None) -> int | None:
    """O fluxo inteiro do código 50 pela janela: autoriza, abre a janela, grava e avisa. Devolve o número da garota ou None."""
    if not autorizar(master, ctx, "caixa_comissao", "exigir_senha_comissao", "Lançar comissão exige autorização:"):
        return None
    turno = ctx.turnos.atual()
    if turno is None:
        tema.aviso(master, "Abra o turno do caixa antes de lançar comissão.")
        return None
    escolha = dialogo_comissao(master, ctx, sugerida)
    if escolha is None:
        return None
    numero, cent = escolha
    return numero if registrar_comissao(master, ctx, turno["id"], numero, cent, ao_lancar) is not None else None


def dialogo_pagar(master, ctx, numero: int, nome: str, comissao_cent: int, quantidade: int,
                  do_caixa_padrao: bool = False) -> dict | None:
    """O acerto da garota: a comissão marcada e, se a casa pergunta (`comissao_pede_shows`), os shows que o OPERADOR lança aqui
    (quantidade e valor de cada um; nada é contado sozinho). Devolve {"do_caixa", "shows", "valor_show_cent", "pix_cent",
    "vale_cent"} ou None.
    `do_caixa` True = o dinheiro sai da gaveta; False = pago fora do caixa. `pix_cent` é a parte paga por Pix (sem dinheiro no
    caixa, ou só parte dele): o resto é dinheiro e o Pix nunca passa pela gaveta. `vale_cent` é o vale que a garota já pegou: é
    descontado do total do acerto (dinheiro ou Pix), mas não sai do caixa de novo, pois aquele dinheiro já saiu quando ela o pegou.
    O Pix digitado é sobre o que sobra depois do vale."""
    # Sem comissão marcada (a garota fez show mas não tem comissão) os shows aparecem sempre, mesmo com a pergunta desligada.
    pede_shows = ctx.comissoes.pede_shows() or not quantidade
    dlg = tema.Dialogo(master, "Pagar comissão")
    ttk.Label(dlg.corpo, text=f"Garota {numero} {nome}".strip(), font=tema.FONTE_B).pack(anchor="w")
    ttk.Label(dlg.corpo, text=f"{quantidade} lançamento(s) de comissão a pagar" if quantidade else
              "Sem comissão marcada: informe os shows, ou feche a conta sem valor",
              foreground=tema.COR["suave"], wraplength=400, justify="left").pack(anchor="w")
    ttk.Label(dlg.corpo, text=f"Comissão: {fmt.fmt_brl(comissao_cent)}", font=("Georgia", 14, "bold")).pack(anchor="w", pady=(6, 0))
    qtd = tk.StringVar(master=dlg)
    valor_show = tk.IntVar(master=dlg, value=0)                    # centavos de cada show; 0 = ainda não escolhido
    total_txt = tk.StringVar(master=dlg)
    pix = tk.StringVar(master=dlg)
    vale = tk.StringVar(master=dlg)
    vale_txt = tk.StringVar(master=dlg)
    divisao_txt = tk.StringVar(master=dlg)
    msg = ttk.Label(dlg.corpo, text="", foreground=tema.COR["perigo"], wraplength=400)
    en_qtd = None

    def pix_digitado(total: int) -> int | None:
        """O Pix em centavos (vazio = 0), ou None se o que foi digitado não é um valor entre 0 e o que há a pagar."""
        try:
            cent = fmt.para_centavos(pix.get()) if pix.get().strip() else 0
        except ValueError:
            return None
        return cent if 0 <= cent <= total else None

    def vale_digitado(total: int) -> int | None:
        """O vale em centavos (vazio = 0), ou None se inválido ou maior que o total do acerto."""
        try:
            cent = fmt.para_centavos(vale.get()) if vale.get().strip() else 0
        except ValueError:
            return None
        return cent if 0 <= cent <= total else None

    def calcular(*_) -> tuple[int, int] | None:
        """(quantidade, valor) se o que está na tela é válido; atualiza o total e a divisão dinheiro/Pix. Sem shows, o total é
        só a comissão."""
        try:
            n, v = ctx.comissoes.validar_shows(qtd.get(), valor_show.get())
        except ErroNegocio:
            n, v = 0, 0
            ok = None
        else:
            ok = (n, v)
        total = comissao_cent + n * v
        vl = vale_digitado(total)
        a_pagar = total - (vl or 0)
        total_txt.set(fmt.fmt_brl(a_pagar))
        vale_txt.set("O vale é inválido ou maior que o total do acerto." if vl is None else
                     f"Total {fmt.fmt_brl(total)}  -  vale {fmt.fmt_brl(vl)}  =  {fmt.fmt_brl(a_pagar)}" if vl else "")
        p = pix_digitado(a_pagar)
        divisao_txt.set("Pix maior que o total ou inválido." if p is None else
                        f"Dinheiro {fmt.fmt_brl(a_pagar - p)}  +  Pix {fmt.fmt_brl(p)}")
        return ok

    if pede_shows:
        quadro = ttk.LabelFrame(dlg.corpo, text="Shows (lançados por você)", padding=8)
        quadro.pack(fill="x", pady=(10, 0))
        linha = ttk.Frame(quadro)
        linha.pack(fill="x")
        ttk.Label(linha, text="Quantidade de shows:").pack(side="left")
        en_qtd = ttk.Entry(linha, textvariable=qtd, width=6, font=("Segoe UI", 16, "bold"), justify="center")
        en_qtd.pack(side="left", padx=8)
        valores = ttk.Frame(quadro)
        valores.pack(fill="x", pady=(6, 0))
        ttk.Label(valores, text="Valor de cada show:").pack(side="left")
        for cent in ctx.comissoes.valores_show():
            ttk.Radiobutton(valores, text=fmt.fmt_brl(cent), value=cent, variable=valor_show).pack(side="left", padx=8)
        qtd.trace_add("write", calcular)
        valor_show.trace_add("write", calcular)
    linha_vale = ttk.Frame(dlg.corpo)
    linha_vale.pack(fill="x", pady=(10, 0))
    ttk.Label(linha_vale, text="A garota pegou vale? Valor do vale (R$):").pack(side="left")
    en_vale = ttk.Entry(linha_vale, textvariable=vale, width=10, font=("Segoe UI", 14, "bold"), justify="right")
    en_vale.pack(side="left", padx=8)
    ttk.Label(dlg.corpo, text="O vale é descontado do total (pago em dinheiro ou em Pix) e não sai do caixa de novo: aquele dinheiro já saiu "
                              "quando ela o pegou. Deixe vazio se não tem vale.",
              foreground=tema.COR["suave"], wraplength=400, justify="left").pack(anchor="w")
    ttk.Label(dlg.corpo, textvariable=vale_txt, foreground=tema.COR["suave"]).pack(anchor="w")
    ttk.Label(dlg.corpo, text="TOTAL A PAGAR", style="Rotulo.TLabel").pack(anchor="w", pady=(10, 0))
    ttk.Label(dlg.corpo, textvariable=total_txt, font=("Georgia", 28, "bold"), foreground=tema.COR["total"]).pack(anchor="w")
    # Sem dinheiro no caixa (ou só parte dele): a parte paga por Pix não sai da gaveta; o resto é dinheiro. Tudo sobre o que sobra
    # depois do vale.
    quadro_pix = ttk.LabelFrame(dlg.corpo, text="Pagamento", padding=8)
    quadro_pix.pack(fill="x", pady=(6, 0))
    linha_pix = ttk.Frame(quadro_pix)
    linha_pix.pack(fill="x")
    ttk.Label(linha_pix, text="Parte paga por Pix (R$):").pack(side="left")
    en_pix = ttk.Entry(linha_pix, textvariable=pix, width=10, font=("Segoe UI", 14, "bold"), justify="right")
    en_pix.pack(side="left", padx=8)

    def tudo_no_pix() -> None:
        try:
            n, v = ctx.comissoes.validar_shows(qtd.get(), valor_show.get())
        except ErroNegocio:
            n, v = 0, 0                                   # shows ainda incompletos: o Pix cobre ao menos a comissão
        total = comissao_cent + n * v
        pix.set(fmt.fmt_num(total - (vale_digitado(total) or 0)))
        en_pix.focus_set()

    ttk.Button(linha_pix, text="Tudo no Pix", command=tudo_no_pix).pack(side="left")
    ttk.Label(quadro_pix, textvariable=divisao_txt, foreground=tema.COR["suave"]).pack(anchor="w", pady=(4, 0))
    pix.trace_add("write", calcular)
    vale.trace_add("write", calcular)
    calcular()
    # Nem sempre sobra dinheiro no caixa: por padrão o pagamento só fica registrado (comissao_paga_do_caixa = N).
    do_caixa = tk.BooleanVar(master=dlg, value=do_caixa_padrao)
    ttk.Checkbutton(dlg.corpo, text="O dinheiro sai da gaveta do caixa (registra uma sangria e abre a gaveta)",
                    variable=do_caixa).pack(anchor="w", pady=(6, 0))
    ttk.Label(dlg.corpo, text="Desmarcado: o acerto fica registrado como pago, sem mexer no dinheiro do caixa. O Pix nunca sai da gaveta.",
              foreground=tema.COR["suave"], wraplength=400, justify="left").pack(anchor="w")
    msg.pack(anchor="w", pady=(6, 0))

    def confirmar(_=None) -> None:
        try:
            n, v = ctx.comissoes.validar_shows(qtd.get() if pede_shows else 0, valor_show.get())
        except ErroNegocio as e:
            msg.configure(text=str(e))
            return
        total = comissao_cent + n * v
        if not total and not tema.confirmar(
                dlg, f"A garota {f'{numero} {nome}'.strip()} não tem comissão nem shows.\nFechar a conta dela sem valor (R$ 0,00)?",
                "Fechar sem valor", padrao_sim=False):
            if en_qtd is not None:
                en_qtd.focus_set()
            return
        vl = vale_digitado(total)
        if vl is None:
            msg.configure(text="O vale é inválido ou maior que o total do acerto.")
            en_vale.focus_set()
            return
        p = pix_digitado(total - vl)
        if p is None:
            msg.configure(text="O valor do Pix é inválido ou maior que o total a pagar.")
            en_pix.focus_set()
            return
        dlg.ok({"do_caixa": bool(do_caixa.get()), "shows": n, "valor_show_cent": v, "pix_cent": p, "vale_cent": vl,
                "zerado": not total})

    b = tema._botoes(dlg, "Pagar", comando_ok=confirmar)
    dlg.bind("<Return>", confirmar)
    try:
        return dlg.mostrar(en_qtd if en_qtd is not None else b)
    finally:
        try:
            for variavel in (qtd, valor_show, pix, vale):       # desfaz os ciclos variável <-> função: nada fica para o coletor de lixo
                for _modo, comando in variavel.trace_info():
                    variavel.trace_remove("write", comando)
        except tk.TclError:
            pass


def pagar_garota(master, ctx, numero: int) -> dict | None:
    """Acerta a conta da garota: autoriza, confirma (com os shows que o operador lançar), tira do caixa (se for o caso) e entrega o
    recibo. Devolve o pagamento, ou None se não houve (sem autorização, nada a pagar, desistência ou erro)."""
    if not autorizar(master, ctx, "caixa_pagar_comissao", "exigir_senha_sangria", "Pagar comissão exige autorização:"):
        return None
    itens = ctx.comissoes.lancamentos(numero)
    escolha = dialogo_pagar(master, ctx, numero, ctx.comissoes.nome(numero), sum(i["valor_cent"] for i in itens), len(itens),
                            ctx.banco.cfg_bool("comissao_paga_do_caixa", False))
    if escolha is None:
        return None
    turno = ctx.turnos.atual()
    ok, pag = tema.tratar(master, ctx.comissoes.pagar, numero, turno["id"] if turno else None, ctx.operador_id,
                          escolha["do_caixa"], escolha["shows"], escolha["valor_show_cent"], escolha["pix_cent"],
                          escolha["vale_cent"], permitir_zerado=escolha["zerado"])
    if not ok:
        return None
    enviar_ou_mostrar(master, ctx, "Recibo de acerto" if pag["shows"] or not pag["quantidade"] else "Recibo de comissão",
                      ctx.impressao.recibo_comissao(pag, ctx.operador.nome),
                      f"recibo_comissao_{numero}", tipo="recibo_garota", abrir_gaveta=pag["tirou_do_caixa"])
    if pag["tirou_do_caixa"]:
        # O dinheiro saiu da gaveta: sai também o comprovante da saída financeira (o mesmo da sangria), só com o que saiu do
        # caixa (o Pix não passa por ela). A gaveta já foi aberta pelo recibo.
        enviar_ou_mostrar(master, ctx, "Comprovante de saída",
                          ctx.impressao.comprovante_movimento("saida", pag["dinheiro_cent"], pag["movimento_descricao"],
                                                              ctx.operador.nome),
                          f"saida_comissao_{numero}", tipo="saida_garota")
    return pag


def cancelar_lancamento(master, ctx, lancamento_id: int, rotulo: str, ja_autorizado: bool = False) -> bool:
    """Cancela um lançamento de comissão (senha de cancelamento e confirmação). `rotulo` o descreve na pergunta;
    `ja_autorizado` dispensa a senha quando o operador já a deu (modo cancelar do caixa)."""
    if not ja_autorizado and not autorizar(master, ctx, "caixa_cancelamento", "exigir_senha_cancelamento",
                                           "Cancelar comissão exige autorização:"):
        return False
    if not tema.confirmar(master, f"Cancelar {rotulo}?\nEle deixa de contar como comissão a pagar.", "Cancelar comissão",
                          padrao_sim=False):
        return False
    ok, _ = tema.tratar(master, ctx.comissoes.cancelar, int(lancamento_id), ctx.operador_id, "cancelado no caixa")
    return ok


class JanelaComissoes(tk.Toplevel):
    """Comissões a pagar: uma linha por garota e, ao lado, os lançamentos dela. Paga (com recibo) e cancela lançamento."""

    def __init__(self, master, ctx, ao_mudar=None):
        super().__init__(master)
        self.ctx = ctx
        self.ao_mudar = ao_mudar or (lambda: None)       # o caixa recarrega a comanda que está na tela
        self.title("Comissões das garotas")
        self.configure(bg=tema.COR["fundo"])
        self.geometry("1000x540")
        self.minsize(780, 400)
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)
        barra = ttk.Frame(corpo)
        barra.pack(side="bottom", fill="x", pady=(10, 0))
        self.status = ttk.Label(corpo, text="", foreground=tema.COR["ok"], wraplength=940)
        self.status.pack(side="bottom", anchor="w", pady=(6, 0))
        self.lbl = ttk.Label(corpo, text="", font=tema.FONTE_B)
        self.lbl.pack(side="top", anchor="w", pady=(0, 6))
        meio = ttk.Frame(corpo)
        meio.pack(fill="both", expand=True)
        esq = ttk.LabelFrame(meio, text="Garotas com comissão a pagar", padding=6)
        esq.pack(side="left", fill="both", expand=True)
        dir_ = ttk.LabelFrame(meio, text="Lançamentos da garota escolhida", padding=6)
        dir_.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.grade = tema.Grade(esq, [("num", "Nº", 60, "e"), ("nome", "Nome", 170, "w"), ("qtd", "Lanç.", 55, "e"),
                                      ("total", "A pagar", 105, "e")], altura=12)
        self.grade.pack(fill="both", expand=True)
        self.itens = tema.Grade(dir_, [("id", "Nº", 50, "e"), ("quando", "Quando", 110, "w"), ("valor", "Valor", 90, "e"),
                                       ("op", "Operador", 100, "w"), ("obs", "Observação", 120, "w")], altura=12)
        self.itens.pack(fill="both", expand=True)
        self.grade.tree.bind("<<TreeviewSelect>>", lambda e: self._mostrar_itens())
        ttk.Button(barra, text="Lançar comissão", command=self.lancar).pack(side="left")
        ttk.Button(barra, text="Pagar a garota escolhida", style="Ok.TButton", command=self.pagar).pack(side="left", padx=6)
        ttk.Button(barra, text="Cancelar lançamento", style="Perigo.TButton", command=self.cancelar).pack(side="left")
        ttk.Button(barra, text="Atualizar (F5)", command=self.atualizar).pack(side="left", padx=6)
        ttk.Button(barra, text="Fechar (Esc)", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<F5>", lambda e: self.atualizar())
        self.atualizar()
        tema.centralizar(self, master.winfo_toplevel())
        self.transient(master.winfo_toplevel())
        self.grade.tree.focus_set()

    # ------------------------------------------------------------------ lista
    def atualizar(self) -> None:
        atual = self.grade.selecionado()
        pend = self.ctx.comissoes.pendentes_por_garota()
        self.grade.preencher([[p["garota"], p["nome"], p["lancamentos"], fmt.fmt_num(p["total_cent"])] for p in pend],
                             [p["garota"] for p in pend])
        total = sum(p["total_cent"] for p in pend)
        self.lbl.configure(text=f"Total a pagar às garotas: {fmt.fmt_brl(total)}" if pend else "Nenhuma comissão a pagar.",
                           foreground=tema.COR["titulo"] if pend else tema.COR["suave"])
        if pend:
            self.grade.selecionar(atual if atual and self.grade.tree.exists(atual) else pend[0]["garota"])
        self._mostrar_itens()

    def _garota(self, avisar: bool = True) -> int | None:
        escolhida = self.grade.selecionado()
        if escolhida is None and avisar:
            tema.aviso(self, "Escolha uma garota da lista.")
        return int(escolhida) if escolhida is not None else None

    def _mostrar_itens(self) -> None:
        n = self._garota(avisar=False)
        itens = self.ctx.comissoes.lancamentos(n) if n is not None else []
        self.itens.preencher([[i["id"], fmt.fmt_datahora(i["criado_em"])[:16], fmt.fmt_num(i["valor_cent"]),
                               i["operador"] or "", i["observacao"] or ""] for i in itens], [i["id"] for i in itens])

    # ------------------------------------------------------------------ ações
    def lancar(self) -> None:
        sugerida = str(self._garota(avisar=False) or "")
        lancar(self, self.ctx, sugerida, ao_lancar=lambda texto: self.status.configure(text=texto))
        self.atualizar()
        self.ao_mudar()

    def pagar(self) -> None:
        n = self._garota()
        if n is None:
            return
        pag = pagar_garota(self, self.ctx, n)
        if pag is None:
            self.atualizar()                       # nada a pagar (ou já pago em outro lugar): a lista se corrige
            return
        self.status.configure(text=f"{'Acerto' if pag['shows'] else 'Comissão'} de {fmt.fmt_brl(pag['total_cent'])} pago à garota {n}."
                              if pag["shows"] else f"Comissão de {fmt.fmt_brl(pag['total_cent'])} paga à garota {n}.")
        self.atualizar()
        self.ao_mudar()

    def cancelar(self) -> None:
        escolhido = self.itens.selecionado()
        if escolhido is None:
            tema.aviso(self, "Escolha, na lista da direita, o lançamento que será cancelado.")
            return
        valores = self.itens.valores(escolhido)
        if cancelar_lancamento(self, self.ctx, int(escolhido), f"o lançamento {valores[0]} de R$ {valores[2]}"):
            self.status.configure(text=f"Lançamento {valores[0]} cancelado.")
            self.atualizar()
            self.ao_mudar()
