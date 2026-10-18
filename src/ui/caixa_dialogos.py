"""Diálogos do caixa: abertura/troca de turno, sangria, garçom, observação e divisão de produto."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.controllers import conferencia_turno
from src.core import formatacao as fmt
from src.hardware.impressora_termica import ErroImpressao
from src.ui import tema
from src.ui.visualizador import Visualizador, enviar_ou_mostrar


def abrir_turno(master, ctx) -> bool:
    """Abertura do turno: número do turno e valor encontrado no caixa (fundo de caixa)."""
    max_turnos = max(ctx.banco.cfg_int("num_turnos", 3), 1)
    numero = tema.pedir_numero(master, "Abertura do turno", "Turno:", ctx.turnos.numero_sugerido(), 1, max(max_turnos, 9))
    if numero is None:
        return False
    valor = tema.pedir_dinheiro(master, "Abertura do turno", "Valor inicial (+) - dinheiro encontrado no caixa:",
                                0, permitir_zero=True)
    if valor is None:
        return False
    if not tema.confirmar(master, f"Confirma valor inicial de {fmt.fmt_brl(valor)}?", "Confirm"):
        return abrir_turno(master, ctx)
    ok, _ = tema.tratar(master, ctx.turnos.abrir, ctx.operador_id, numero, valor)
    return ok


def conferir_maquininha(master, ctx, turno_id: int) -> bool:
    """Antes de contar a gaveta: o que foi lançado no turno em cartão (débito e crédito, separados) e Pix, para o operador
    comparar com o que a maquininha imprimiu. Devolve False se desistiu de fechar. Não mostra o dinheiro esperado."""
    maq = ctx.turnos.maquininha(turno_id)
    if not maq["linhas"]:
        return True                                  # a casa não tem forma fora da gaveta: nada a conferir
    dlg = tema.Dialogo(master, "Conferir maquininha")
    ttk.Label(dlg.corpo, text="Lançado neste turno no sistema", font=tema.FONTE_B).pack(anchor="w")
    ttk.Label(dlg.corpo, text="Compare cada linha com o total que a maquininha (fechamento do lote) mostra.",
              foreground=tema.COR["suave"], wraplength=420, justify="left").pack(anchor="w", pady=(0, 8))
    grade = ttk.Frame(dlg.corpo)
    grade.pack(fill="x")
    grade.columnconfigure(0, weight=1)
    for i, cab in enumerate(("Forma", "Qtd.", "Valor (R$)")):
        ttk.Label(grade, text=cab, style="Rotulo.TLabel").grid(row=0, column=i, sticky="w" if i == 0 else "e", padx=(0, 16))
    for i, r in enumerate(maq["linhas"], start=1):
        ttk.Label(grade, text=r["tipo"], font=tema.FONTE_B).grid(row=i, column=0, sticky="w", padx=(0, 16))
        ttk.Label(grade, text=str(r["qtd"])).grid(row=i, column=1, sticky="e", padx=(0, 16))
        ttk.Label(grade, text=fmt.fmt_num(r["valor"]), font=("Georgia", 15, "bold")).grid(row=i, column=2, sticky="e")
    fim = len(maq["linhas"]) + 1
    ttk.Separator(grade).grid(row=fim, column=0, columnspan=3, sticky="ew", pady=6)
    ttk.Label(grade, text="Total", font=tema.FONTE_B).grid(row=fim + 1, column=0, sticky="w")
    ttk.Label(grade, text=str(maq["qtd"])).grid(row=fim + 1, column=1, sticky="e", padx=(0, 16))
    ttk.Label(grade, text=fmt.fmt_num(maq["total"]), font=("Georgia", 15, "bold")).grid(row=fim + 1, column=2, sticky="e")
    ttk.Label(dlg.corpo, text="Se algum valor não bate, cancele e confira os pagamentos antes de fechar o turno.",
              foreground=tema.COR["suave"], wraplength=420, justify="left").pack(anchor="w", pady=(8, 0))
    b = tema._botoes(dlg, "Continuar", comando_ok=dlg.ok)
    dlg.bind("<Return>", lambda e: dlg.ok())
    return bool(dlg.mostrar(b))


def trocar_turno(master, ctx) -> bool:
    """Troca de turno: a maquininha é conferida primeiro e o operador declara o valor da gaveta ANTES de ver o esperado."""
    turno = ctx.turnos.atual()
    if turno is None:
        tema.aviso(master, "Não há turno aberto.")
        return False
    if not conferir_maquininha(master, ctx, turno["id"]):
        return False
    valor = tema.pedir_dinheiro(master, "Troca de turno", "Digite o valor encontrado na gaveta (+ cheques/tickets):",
                                0, permitir_zero=True)
    if valor is None:
        return False
    abertas = ctx.turnos.posicoes_abertas()
    aviso = ""
    if abertas:                 # mesas e comandas esquecidas abertas: o caixa avisa, o dono decide
        nomes = ", ".join(p["nome"] for p in abertas[:6]) + (", ..." if len(abertas) > 6 else "")
        aviso = (f"\n\nATENÇÃO: {len(abertas)} mesa(s)/comanda(s) aberta(s), {fmt.fmt_brl(sum(p['total_cent'] for p in abertas))}:"
                 f"\n{nomes}.\nElas continuam abertas no próximo turno.")
    a_pagar = ctx.comissoes.pendentes_por_garota()
    if a_pagar:                 # comissão paga com dinheiro da gaveta muda a contagem: melhor pagar antes de contar
        aviso += (f"\n\nComissão das garotas a pagar: {fmt.fmt_brl(sum(p['total_cent'] for p in a_pagar))} "
                  f"({len(a_pagar)} garota(s)).\nSe vai pagar com dinheiro da gaveta, responda Não, pague "
                  "(botão Comissões) e conte o caixa de novo.")
    if not tema.confirmar(master, f"Confirma {fmt.fmt_brl(valor)} como valor final?\n"
                                  "Depois de confirmar o turno é encerrado e não pode ser acertado." + aviso, "Troca de turno"):
        return False
    ok, res = tema.tratar(master, ctx.turnos.fechar, turno["id"], ctx.operador_id, valor)
    if ok:
        if ctx.utilitarios.backup_automatico("troca de turno") is None:
            tema.aviso(master, "O turno foi fechado, mas o BACKUP automático falhou.\n"
                               "Faça um backup manual em Utilitários > Backup de dados e confira a pasta/disco.")
        PainelFechamento(master, ctx, res, vias_impressas=imprimir_fechamento(master, ctx, res))
    return ok


def imprimir_fechamento(master, ctx, res: dict) -> int:
    """Ao trocar o turno o fechamento sai sozinho (sobra/falta, sangrias e a assinatura do caixa e do gerente): quem recebe
    o caixa já fica com a folha na mão. Devolve quantas vias foram para a impressora (0: desligado, modo 'tela' ou erro).

    No modo 'tela' não abre nada aqui: o painel que vem a seguir tem o botão de imprimir."""
    if not ctx.banco.cfg_bool("imprimir_fechamento_ao_trocar", True) or ctx.impressao.deve_mostrar_na_tela():
        return 0
    vias = max(1, min(ctx.banco.cfg_int("vias_fechamento", 1), 3))
    try:
        ctx.impressao.enviar(ctx.impressao.fechamento(res), f"fechamento_turno_{res['turno']['numero']}", tipo="fechamento",
                             copias=vias)
    except ErroImpressao as e:
        tema.erro(master, f"O fechamento não foi impresso: {e}\nUse o botão Imprimir Fechamento.")
        return 0
    return vias


# Linhas do fechamento de módulos opcionais: zeradas e com o módulo desligado (boate), não aparecem.
_LINHAS_OPCIONAIS = {"entregas_pendentes": "usar_delivery", "venda_caderneta": "usar_caderneta",
                     "pagtos_caderneta": "usar_caderneta"}


class PainelFechamento(tk.Toplevel):
    """Resumo do turno (sobra/zero em verde, falta em vermelho) com Imprimir e Gerar arquivo texto."""

    def __init__(self, master, ctx, res: dict, vias_impressas: int = 0):
        super().__init__(master)
        self.ctx, self.res = ctx, res
        self.title("Fechamento do turno")
        self.configure(bg=tema.COR["fundo"])
        t = res["turno"]
        M = fmt.fmt_num
        corpo = ttk.Frame(self, padding=14)
        corpo.pack(fill="both", expand=True)
        esq = ttk.LabelFrame(corpo, text="Turno", padding=10)
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        abertas = res.get("posicoes_abertas") or []
        com = res.get("comissoes") or {}
        dados = [("Turno", t["numero"]), ("Abertura", fmt.fmt_datahora(t["aberto_em"])), ("Valor inicial (+)", M(res["valor_inicial"])),
                 ("Cupom inicial", res["cupom_inicial"]), ("Fechamento", fmt.fmt_datahora(fmt.agora())),
                 ("Valor final (-)", M(res["valor_final"])), ("Cupom final", res["cupom_final"]), ("Posições", res["posicoes"]),
                 ("Entregas", res["entregas"]), ("Perc. entrega", f"{res['perc_entrega']:.2f}".replace(".", ",")),
                 ("TC (cupons)", res["tc"]), ("TM", M(res["tm"])), ("Nº de pessoas", res["pessoas"]),
                 ("Valor por pessoa", M(res["valor_por_pessoa"])),
                 ("Posições em aberto", f"{len(abertas)} ({M(sum(p['total_cent'] for p in abertas))})" if abertas else "nenhuma"),
                 ("Cupons cancelados", len(res.get("cupons_cancelados") or ())),
                 ("Itens cancelados", len(res.get("itens_cancelados") or ())),
                 ("Transferências", len(res.get("transferencias") or ())),
                 ("Comissões das garotas", M(com["total_cent"]) if com.get("quantidade") else "nenhuma"),
                 ("Shows pagos às garotas", M(res["shows"]["total_cent"]) if (res.get("shows") or {}).get("quantidade") else "nenhum"),
                 ("Saídas sem consumo (1002)", len(res.get("saidas_liberadas") or ())),
                 ("Produtos vendidos", f"{len(res.get('produtos_vendidos') or ())} (lista na conferência)")]
        if not res["entregas"] and not ctx.banco.cfg_bool("usar_delivery", False):    # casa sem delivery: linhas zeradas somem
            dados = [d for d in dados if d[0] not in ("Entregas", "Perc. entrega")]
        for i, (r, v) in enumerate(dados):
            ttk.Label(esq, text=r).grid(row=i, column=0, sticky="w")
            ttk.Label(esq, text=str(v), font=tema.FONTE_B).grid(row=i, column=1, sticky="e", padx=(20, 0))
        dir_ = ttk.LabelFrame(corpo, text="Recebimentos financeiros", padding=10)
        dir_.grid(row=0, column=1, sticky="nsew")
        i = 0
        for r in res["recebimentos"] or [{"tipo": "(nenhum)", "valor": 0}]:
            ttk.Label(dir_, text=r["tipo"]).grid(row=i, column=0, sticky="w")
            ttk.Label(dir_, text=M(r["valor"]), font=tema.FONTE_B).grid(row=i, column=1, sticky="e", padx=(30, 0))
            i += 1
        for rotulo, chave in (("Adiant. de contas abertas", "adiantamentos_abertos"),
                              ("Pago em turno anterior", "recebido_turno_anterior")):
            if res.get(chave):                  # explica por que o recebido difere do vendido; só aparece quando acontece
                ttk.Label(dir_, text=f"  {rotulo}", foreground=tema.COR["suave"]).grid(row=i, column=0, sticky="w")
                ttk.Label(dir_, text=M(res[chave]), foreground=tema.COR["suave"]).grid(row=i, column=1, sticky="e", padx=(30, 0))
                i += 1
        ttk.Separator(dir_).grid(row=i, column=0, columnspan=2, sticky="ew", pady=6)
        for rotulo, chave in (("Troco", "troco"), ("C. Vale emitido (+)", "vale_emitido"), ("Venda (+)", "venda"),
                              ("Desconto (-)", "desconto"), ("Serviço (+)", "servico"), ("Taxa (+)", "taxa"),
                              ("Taxa do crédito (+)", "acrescimo"), ("Repique", "repique"), ("Entregas pend.", "entregas_pendentes"), ("Venda caderneta", "venda_caderneta"),
                              ("Pagtos caderneta (+)", "pagtos_caderneta"), ("Entradas financ. (+)", "entradas"),
                              ("Saídas financ. (-)", "saidas"), ("Fora da gaveta (cartão/Pix)", "fora_da_gaveta"),
                              ("Valor esperado", "esperado")):
            if not res[chave] and (chave == "acrescimo" or (
                    chave in _LINHAS_OPCIONAIS and not ctx.banco.cfg_bool(_LINHAS_OPCIONAIS[chave], False))):
                continue
            i += 1
            v = res[chave] if chave == "entregas_pendentes" else M(res[chave])
            ttk.Label(dir_, text=rotulo, font=tema.FONTE_B if chave == "esperado" else tema.FONTE).grid(row=i, column=0, sticky="w")
            ttk.Label(dir_, text=str(v), font=tema.FONTE_B).grid(row=i, column=1, sticky="e", padx=(30, 0))
        resultado = res["resultado"]
        cor = tema.COR["ok_fundo"] if resultado >= 0 else tema.COR["perigo_fundo"]
        rotulo = "SOBRA" if resultado > 0 else ("FALTA" if resultado < 0 else "CAIXA CONFERIDO")
        faixa = tk.Frame(corpo, bg=cor, padx=10, pady=8)
        faixa.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 8))
        tk.Label(faixa, text=f"Resultado: {fmt.fmt_brl(resultado)}  -  {rotulo}", bg=cor, fg=tema.COR["sobre"], font=("Segoe UI", 20, "bold")).pack()
        barra = ttk.Frame(corpo)
        barra.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Button(barra, text="Imprimir Fechamento", command=self.imprimir).pack(side="left")
        ttk.Button(barra, text="Gera Arquivo Texto", command=self.gerar_texto).pack(side="left", padx=8)
        ttk.Button(barra, text="Conferência do turno", command=self.conferencia).pack(side="left")
        b = ttk.Button(barra, text="Concluir (Enter)", style="Ok.TButton", command=self.destroy)
        b.pack(side="right")
        if vias_impressas:
            self.lbl_impresso = ttk.Label(corpo, foreground=tema.COR["ok"], font=tema.FONTE_B, text=(
                f"Fechamento enviado à impressora ({vias_impressas} via{'s' if vias_impressas > 1 else ''}): "
                "o caixa responsável e o gerente assinam."))
            self.lbl_impresso.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.bind("<Return>", lambda e: self.destroy())
        self.bind("<Escape>", lambda e: self.destroy())
        tema.centralizar(self, master.winfo_toplevel())
        self.transient(master.winfo_toplevel())
        tema.modalizar(self)
        b.focus_set()
        self.wait_window(self)

    def _texto(self) -> str:
        return self.ctx.impressao.fechamento(self.res)

    def imprimir(self) -> None:
        enviar_ou_mostrar(self, self.ctx, "Fechamento de turno", self._texto(), f"fechamento_turno_{self.res['turno']['numero']}",
                          tipo="fechamento")

    def conferencia(self) -> None:
        """Posições abertas, cancelamentos e transferências do turno, na tela (sem imprimir)."""
        Visualizador(self, self.ctx, "Conferência do turno",
                     conferencia_turno.texto_conferencia(self.res, self.ctx.impressao.largura()),
                     f"conferencia_turno_{self.res['turno']['numero']}")

    def gerar_texto(self) -> None:
        """Grava o fechamento em arquivo sem imprimir a fita."""
        caminho = self.ctx.impressao.enviar(self._texto(), f"fechamento_turno_{self.res['turno']['numero']}")
        tema.mensagem(self, f"Arquivo gerado:\n{caminho}", "Gera Arquivo Texto")


def sangria(master, ctx, turno_id: int) -> bool:
    """Saída (sangria) ou entrada de dinheiro no caixa, com comprovante."""
    dlg = tema.Dialogo(master, "Entradas e saídas financeiras")
    tipo = tk.StringVar(value="saida")
    quadro = ttk.Frame(dlg.corpo)
    quadro.pack(fill="x")
    ttk.Radiobutton(quadro, text="Saída (sangria)", variable=tipo, value="saida").pack(side="left", padx=(0, 16))
    ttk.Radiobutton(quadro, text="Entrada (suprimento)", variable=tipo, value="entrada").pack(side="left")
    ttk.Label(dlg.corpo, text="Valor", style="Rotulo.TLabel").pack(anchor="w", pady=(10, 0))
    valor = tk.StringVar()
    ev = ttk.Entry(dlg.corpo, textvariable=valor, width=16)
    ev.pack(anchor="w")
    ttk.Label(dlg.corpo, text="Descrição / motivo", style="Rotulo.TLabel").pack(anchor="w", pady=(8, 0))
    desc = tk.StringVar()
    ed = ttk.Entry(dlg.corpo, textvariable=desc, width=40)
    ed.pack(fill="x")
    msg = ttk.Label(dlg.corpo, text="", foreground=tema.COR["perigo"])
    msg.pack(anchor="w")

    def gravar(_=None):
        try:
            cent = fmt.para_centavos(valor.get())
        except ValueError:
            msg.configure(text="Valor inválido.")
            return
        try:
            ctx.turnos.movimentar(turno_id, ctx.operador_id, tipo.get(), cent, desc.get())
        except Exception as e:  # noqa: BLE001
            msg.configure(text=str(e))
            return
        dlg.ok((tipo.get(), cent, desc.get()))
    tema._botoes(dlg, "Gravar", comando_ok=gravar)
    ev.bind("<Return>", lambda e: ed.focus_set())
    ed.bind("<Return>", gravar)
    r = dlg.mostrar(ev)
    if r:
        t, cent, d = r
        # a gaveta abre junto: o operador vai pôr (ou tirar) o dinheiro do movimento
        enviar_ou_mostrar(master, ctx, "Comprovante", ctx.impressao.comprovante_movimento(t, cent, d, ctx.operador.nome),
                          "sangria", tipo="comprovante", abrir_gaveta=True)
        return True
    return False


def escolher_garcom(master, ctx) -> int | None:
    garcons = [(r["id"], r["nome"]) for r in ctx.cadastros.listar("operadores", apenas_ativos=True) if r["garcom"]]
    if not garcons:
        garcons = [(r["id"], r["nome"]) for r in ctx.cadastros.listar("operadores", apenas_ativos=True)]
    return tema.escolher(master, "Garçom", garcons, "Garçom que atendeu (digite as iniciais):")


def escolher_observacao(master, ctx) -> str | None:
    obs = [(r["texto"], f"{r['codigo']} - {r['texto']}") for r in ctx.cadastros.listar("observacoes")]
    if not obs:
        livre = tema.pedir_texto(master, "Observação", "Não há observações cadastradas. Digite a observação do item:")
        return livre or None
    return tema.escolher(master, "Observações", obs, "Escolha a observação do item (ou Esc):")


def dialogo_partes(master, ctx, produto: dict) -> list[int] | None:
    """Produto dividido/combo: pergunta em quantas partes e qual produto em cada parte."""
    n_max = produto["partes"]
    n = tema.pedir_numero(master, produto["nome"], f"Dividir em quantas partes? (1 a {n_max}, 1 = sem divisão)", 2 if n_max >= 2 else 1, 1, n_max)
    if n is None:
        return None
    if n == 1:
        return []
    if produto["composto"]:
        candidatos = [r for r in ctx.cadastros.listar("produtos", apenas_ativos=True) if r["compoe"] and r["id"] != produto["id"]]
    else:
        candidatos = [r for r in ctx.cadastros.listar("produtos", apenas_ativos=True) if r["montagem"]]
    if not candidatos:
        tema.aviso(master, "Não há produtos cadastrados para montar esta divisão (marque 'Montagem' nos produtos).")
        return None
    itens = [(r["id"], r["nome"]) for r in candidatos]
    partes = []
    for i in range(1, n + 1):
        escolhido = tema.escolher(master, f"{produto['nome']} - parte {i} de {n}", itens, "Digite para filtrar:")
        if escolhido is None:
            return None
        partes.append(escolhido)
    return partes
