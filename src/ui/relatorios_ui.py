"""Relatórios (manual ADM seção 6): janela genérica com critérios de consulta, mais as telas
especiais de Venda no período (cupom a cupom) e Estoque atual (cores de situação)."""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Callable

from src.core import formatacao as fmt
from src.core.posicao import rotulo as rotulo_posicao
from src.core.relatorio import Relatorio, para_csv, para_texto
from src.ui import tema
from src.ui.visualizador import Visualizador

LIMITE_CUPONS = 1000       # a grade de cupons mostra os mais recentes; os totais abaixo valem para o período inteiro

# chave -> (rótulo, tipo)   tipos: data, hora, int, sn, lookup:<nome>, escolha:<a|b|c>, texto
FILTROS = {
    "de": ("Data inicial", "data"), "ate": ("Data final", "data"),
    "hora_ini": ("Hora inicial", "hora"), "hora_fim": ("Hora final", "hora"),
    "cupom_ini": ("Cupom inicial", "int"), "cupom_fim": ("Cupom final", "int"),
    "turno_atual": ("Somente o turno atual (aberto)", "sn"), "turno": ("Turno", "int"),
    "operador_id": ("Operador", "lookup:operadores"), "garcom_id": ("Garçom", "lookup:operadores"),
    "vendedor_id": ("Vendedor", "lookup:operadores"), "entregador_id": ("Entregador", "lookup:operadores"),
    "cliente_id": ("Cliente", "lookup:clientes"),
    "modalidade": ("Modalidade", "escolha:balcao|mesa|comanda|caderneta|entrega"),
    "tipo_caixa": ("Movimento", "escolha:entrada|saida"),
    "tipo_estoque": ("Tipo de movimento", "escolha:compra|entrada|saida|descarte|quebra|oxidacao|devolucao|contagem|inicial|pedido|desc_acabados"),
    "fornecedor_id": ("Fornecedor", "lookup:fornecedores"),
    "plano_id": ("Plano de contas", "lookup:planos_contas"), "subplano_id": ("Sub plano", "lookup:subplanos"),
    "por": ("Considerar a data de", "escolha:dt_quitacao|dt_entrada|dt_vencimento"),
    "apenas_resultado": ("Somente contas que afetam o resultado", "sn"), "apenas_debitos": ("Somente débitos", "sn"),
    "incluir_previsao": ("Incluir previsões", "sn"),
    "garota": ("Garota (número)", "int"), "situacao_comissao": ("Situação da comissão", "escolha:pendente|paga|cancelada"),
    "detalhar": ("Listar cada lançamento", "sn"),
}
VENDAS = ["de", "ate", "hora_ini", "hora_fim", "cupom_ini", "cupom_fim", "turno_atual", "turno", "operador_id", "modalidade"]
VENDAS_MAIS = ["garcom_id", "vendedor_id", "entregador_id", "cliente_id"]
PERIODO = ["de", "ate"]
PERIODO_TURNO = ["de", "ate", "turno", "operador_id"]


@dataclass
class Spec:
    titulo: str
    filtros: list
    executar: Callable            # (ctx, filtros) -> Relatorio
    padrao: str = "hoje"          # 'hoje' | 'mes' | 'vazio'
    fita: Callable | None = None  # (ctx, filtros) -> Relatorio impresso na impressora de cupom
    mais: list = field(default_factory=list)


def _mes_a_hoje():
    h = fmt.hoje()
    return h[:8] + "01", h


SPECS: dict[str, Spec] = {
    "vendas_grupo": Spec("Venda por grupo", VENDAS, lambda c, f: c.relatorios.vendas_por_grupo(f), mais=VENDAS_MAIS),
    "informativo": Spec("Informativo de vendas por dia", PERIODO + ["operador_id"], lambda c, f: c.relatorios.informativo_dias(f), "mes"),
    "horas": Spec("Vendas por hora", PERIODO + ["hora_ini", "hora_fim"], lambda c, f: c.relatorios.vendas_por_hora(f), "mes"),
    "cancelados": Spec("Cancelamentos", PERIODO + ["operador_id"], lambda c, f: c.relatorios.cancelados(f), "mes"),
    "caixa_mov": Spec("Entradas e saídas financeiras do caixa", PERIODO_TURNO + ["tipo_caixa"],
                      lambda c, f: c.relatorios.caixa_movimentos({**f, "tipo": f.get("tipo_caixa")})),
    "fechamentos": Spec("Fechamentos do caixa", PERIODO_TURNO, lambda c, f: c.relatorios.fechamentos(f), "mes"),
    "comandas": Spec("Comandas", VENDAS, lambda c, f: c.relatorios.comandas(f), mais=VENDAS_MAIS),
    "auditoria_operadores": Spec("Auditoria por operador", PERIODO, lambda c, f: c.relatorios.auditoria_operadores(f), "mes"),
    "garcons": Spec("Garçons", VENDAS, lambda c, f: c.relatorios.garcons(f), mais=VENDAS_MAIS),
    "comissao_garotas": Spec("Comissão das garotas", PERIODO + ["turno", "garota", "situacao_comissao", "detalhar"],
                             lambda c, f: c.relatorios.comissoes_garotas(f), "mes"),
    "cmv": Spec("C.M.V. - Custo da mercadoria vendida", VENDAS, lambda c, f: c.relatorios.cmv(f), mais=VENDAS_MAIS),
    "comissao_produto": Spec("Comissão por produto", PERIODO, lambda c, f: c.relatorios.comissoes_produto(f), "mes"),
    "comissao_venda": Spec("Comissão por venda", PERIODO, lambda c, f: c.relatorios.comissoes_venda(f), "mes"),
    "comissao_cliente": Spec("Vendas por cliente", PERIODO + ["cliente_id"], lambda c, f: c.relatorios.comissoes_cliente(f), "mes"),
    "clientes_inativos": Spec("Clientes inativos (sem consumo no período)", PERIODO,
                              lambda c, f: c.relatorios.clientes_inativos(f.get("de") or fmt.somar_dias(fmt.hoje(), -30), f.get("ate")), "vazio"),
    "clientes_resumo": Spec("Entrega e caderneta por cliente", PERIODO, lambda c, f: c.relatorios.clientes_resumo(f), "mes"),
    "resultado_financeiro": Spec("Resultado financeiro",
                                 PERIODO + ["por", "plano_id", "subplano_id", "apenas_resultado", "apenas_debitos", "incluir_previsao"],
                                 lambda c, f: c.relatorios.resultado_financeiro(f), "mes"),
    "extrato_contas": Spec("Extrato de contas", PERIODO, lambda c, f: c.relatorios.extrato_contas(f), "mes"),
    "mov_estoque": Spec("Movimento de estoque", PERIODO + ["tipo_estoque", "fornecedor_id"],
                        lambda c, f: c.relatorios.movimento_estoque({**f, "tipo": f.get("tipo_estoque")}), "mes"),
    "posicao_estoque": Spec("Posição do estoque por período", PERIODO, lambda c, f: c.relatorios.posicao_estoque_periodo(f), "mes"),
    "custo_medio": Spec("Preço médio de compra", PERIODO + ["fornecedor_id"], lambda c, f: c.relatorios.custo_medio(f), "mes"),
    "form_contagem": Spec("Formulário de contagem", [], lambda c, f: c.relatorios.formulario_contagem(), "vazio"),
    "form_pedidos": Spec("Formulário de pedidos", [], lambda c, f: c.relatorios.formulario_pedidos(), "vazio"),
}


class PainelFiltros(ttk.LabelFrame):
    """Monta os campos de 'critérios de consulta' e devolve um dict de filtros validado."""

    def __init__(self, master, ctx, chaves: list, mais: list | None = None, padrao: str = "hoje", colunas: int = 4):
        super().__init__(master, text="Critérios de consulta", padding=8)
        self.ctx, self.vars, self.tipos, self.mapas = ctx, {}, {}, {}
        self.colunas = colunas
        self._n = 0
        for ch in chaves:
            self._add(self, ch)
        self.extra = None
        if mais:
            self.extra = ttk.Frame(self)
            for ch in mais:
                self._add(self.extra, ch, contar=False)
            self.var_mais = tk.BooleanVar()
            ttk.Checkbutton(self, text="Mais opções (garçom, vendedor, entregador, cliente)", variable=self.var_mais,
                            command=self._alternar_mais).grid(row=99, column=0, columnspan=4, sticky="w")
        self.padrao = padrao
        self.limpar()

    def _alternar_mais(self) -> None:
        if self.var_mais.get():
            self.extra.grid(row=100, column=0, columnspan=4, sticky="w", pady=(6, 0))
        else:
            self.extra.grid_forget()

    def _add(self, pai, chave: str, contar: bool = True) -> None:
        rotulo, tipo = FILTROS[chave]
        i = self._n if contar else len(self.vars)
        q = ttk.Frame(pai)
        if pai is self:
            q.grid(row=i // self.colunas, column=i % self.colunas, sticky="w", padx=(0, 14), pady=(0, 6))
        else:
            q.pack(side="left", padx=(0, 14))
        self._n += 1 if contar else 0
        self.tipos[chave] = tipo
        if tipo == "sn":
            v = tk.BooleanVar()
            ttk.Checkbutton(q, text=rotulo, variable=v).pack(anchor="w")
        else:
            ttk.Label(q, text=rotulo, style="Rotulo.TLabel").pack(anchor="w")
            v = tk.StringVar()
            if tipo.startswith("lookup:"):
                opc = self.ctx.cadastros.opcoes(tipo.split(":")[1])
                self.mapas[chave] = {r: i for i, r in opc}
                ttk.Combobox(q, textvariable=v, values=[""] + [r for _, r in opc], state="readonly", width=22).pack(anchor="w")
            elif tipo.startswith("escolha:"):
                ttk.Combobox(q, textvariable=v, values=[""] + tipo.split(":")[1].split("|"), state="readonly", width=16).pack(anchor="w")
            else:
                ttk.Entry(q, textvariable=v, width=12 if tipo in ("data", "hora", "int") else 20).pack(anchor="w")
        self.vars[chave] = v

    def limpar(self) -> None:
        for ch, v in self.vars.items():
            v.set(False) if self.tipos[ch] == "sn" else v.set("")
        if self.padrao == "hoje":
            for ch in ("de", "ate"):
                if ch in self.vars:
                    self.vars[ch].set(fmt.fmt_data(fmt.hoje()))
        elif self.padrao == "mes":
            ini, fim = _mes_a_hoje()
            for ch, val in (("de", ini), ("ate", fim)):
                if ch in self.vars:
                    self.vars[ch].set(fmt.fmt_data(val))
        if "por" in self.vars:
            self.vars["por"].set("dt_quitacao")

    def valores(self) -> dict:
        saida = {}
        for ch, v in self.vars.items():
            tipo, bruto = self.tipos[ch], v.get()
            if tipo == "sn":
                if bruto:
                    saida[ch] = True
            elif str(bruto).strip():
                bruto = str(bruto).strip()
                if tipo == "data":
                    saida[ch] = fmt.para_data_iso(bruto)
                elif tipo == "hora":
                    saida[ch] = fmt.para_hora(bruto)
                elif tipo == "int":
                    saida[ch] = int(bruto)
                elif tipo.startswith("lookup:"):
                    saida[ch] = self.mapas[ch][bruto]
                else:
                    saida[ch] = bruto
        return saida


def abrir_relatorio(master, ctx, chave: str):
    if chave == "auditoria_eventos":
        from src.ui.auditoria_ui import JanelaAuditoria
        return JanelaAuditoria(master, ctx)
    if chave == "vendas_periodo":
        return JanelaVendasPeriodo(master, ctx)
    if chave == "estoque_atual":
        return JanelaEstoqueAtual(master, ctx)
    return JanelaRelatorio(master, ctx, chave)


class _Base(tk.Toplevel):
    def __init__(self, master, ctx, titulo: str, geometria: str = "1060x720"):
        super().__init__(master)
        self.ctx, self.rel = ctx, None
        self.title(titulo)
        self.configure(bg=tema.COR["fundo"])
        self.geometry(geometria)
        self.bind("<Escape>", lambda e: self.destroy())

    def _barra(self, botoes: list) -> ttk.Frame:
        b = ttk.Frame(self, padding=(10, 4))
        b.pack(fill="x")
        for rotulo, cmd, lado in botoes:
            ttk.Button(b, text=rotulo, command=cmd).pack(side=lado, padx=3)
        return b

    def _mostrar(self, rel: Relatorio, largura: int = 100) -> None:
        Visualizador(self, self.ctx, rel.titulo, para_texto(rel, largura), rel.titulo.lower().replace(" ", "_"), csv=para_csv(rel))

    def _imprimir(self, rel: Relatorio, largura: int = 80) -> None:
        v = Visualizador(self, self.ctx, rel.titulo, para_texto(rel, largura), rel.titulo.lower().replace(" ", "_"), csv=para_csv(rel), modal=False)
        v.imprimir()

    def _erro_filtro(self, e: Exception) -> None:
        tema.aviso(self, f"Critério inválido: {e}")


class JanelaRelatorio(_Base):
    def __init__(self, master, ctx, chave: str):
        self.spec = SPECS[chave]
        super().__init__(master, ctx, self.spec.titulo)
        self.painel = PainelFiltros(self, ctx, self.spec.filtros, self.spec.mais, self.spec.padrao)
        if self.spec.filtros:
            self.painel.pack(fill="x", padx=10, pady=(10, 0))
        self._barra([("Executa consulta", self.executar, "left"), ("Limpa consulta", self.limpar, "left"),
                     ("Tela (A4)", self.tela, "left"), ("Impressora", self.impressora, "left"), ("Saída", self.destroy, "right")])
        self.caixa = tk.Text(self, font=tema.FONTE_MONO, wrap="none", bg=tema.COR["papel"], fg=tema.COR["texto"], insertbackground=tema.COR["texto"], relief="solid", borderwidth=1, padx=8, pady=6)
        sy = ttk.Scrollbar(self, orient="vertical", command=self.caixa.yview)
        sx = ttk.Scrollbar(self, orient="horizontal", command=self.caixa.xview)
        self.caixa.configure(yscrollcommand=sy.set, xscrollcommand=sx.set, state="disabled")
        sx.pack(side="bottom", fill="x")
        sy.pack(side="right", fill="y")
        self.caixa.pack(fill="both", expand=True, padx=(10, 0), pady=(0, 0))
        self.executar()
        self.transient(master.winfo_toplevel())

    def _filtros(self) -> dict | None:
        try:
            return self.painel.valores()
        except (ValueError, KeyError) as e:
            self._erro_filtro(e)
            return None

    def executar(self) -> None:
        f = self._filtros()
        if f is None:
            return
        ok, rel = tema.tratar(self, self.spec.executar, self.ctx, f)
        if ok:
            self.rel = rel
            self.caixa.configure(state="normal")
            self.caixa.delete("1.0", "end")
            self.caixa.insert("1.0", para_texto(rel, 110) if not rel.vazio() or rel.rodape else rel.titulo + "\n\n(nada encontrado para os critérios)")
            self.caixa.configure(state="disabled")

    def limpar(self) -> None:
        self.painel.limpar()
        self.executar()

    def tela(self) -> None:
        if self.rel is not None:
            self._mostrar(self.rel)

    def impressora(self) -> None:
        if self.rel is not None:
            self._imprimir(self.rel)


class JanelaVendasPeriodo(_Base):
    """Cupom a cupom, com itens e pagamentos; totalização na fita ou em A4."""

    def __init__(self, master, ctx):
        super().__init__(master, ctx, "Venda no período", "1180x800")
        self.painel = PainelFiltros(self, ctx, VENDAS, VENDAS_MAIS, "hoje")
        self.painel.pack(fill="x", padx=10, pady=(10, 0))
        self._barra([("Executa consulta", self.executar, "left"), ("Limpa consulta", self.limpar, "left"),
                     ("Tela (A4)", self.tela, "left"), ("Impressora (fita)", self.fita, "left"),
                     ("Cancela cupom visualizado", self.cancelar_cupom, "left"), ("Saída", self.destroy, "right")])
        corpo = ttk.Frame(self, padding=(10, 0, 10, 10))
        corpo.pack(fill="both", expand=True)
        self.grade = tema.Grade(corpo, [("cup", "Cupom", 70, "w"), ("data", "Data/hora", 140, "w"), ("op", "Operador", 110, "w"),
                                        ("pos", "Posição", 60, "e"), ("mod", "Modalidade", 90, "w"), ("tur", "Turno", 50, "e"),
                                        ("atual", "Atual", 50, "center"), ("canc", "Cancelado", 70, "center"),
                                        ("total", "Total", 90, "e"), ("desc", "Desconto", 80, "e")], altura=11)
        self.grade.pack(fill="both", expand=True)
        self.grade.tag("cancelado", foreground=tema.COR["perigo"])
        baixo = ttk.Frame(corpo)
        baixo.pack(fill="x", pady=(8, 0))
        self.g_itens = tema.Grade(baixo, [("cod", "Código", 110, "w"), ("prod", "Produto", 240, "w"), ("canc", "Canc.", 45, "center"),
                                          ("qt", "Quant", 70, "e"), ("preco", "Preço", 80, "e")], altura=6)
        self.g_itens.pack(side="left", fill="x", expand=True)
        self.g_pag = tema.Grade(baixo, [("tipo", "Pagamento", 150, "w"), ("valor", "Valor", 90, "e")], altura=6)
        self.g_pag.pack(side="left", padx=(10, 0))
        self.resumo = ttk.Label(corpo, text="", font=tema.FONTE_B, foreground=tema.COR["rotulo"])
        self.resumo.pack(anchor="w", pady=(6, 0))
        self.grade.tree.bind("<<TreeviewSelect>>", self._detalhe)
        self.executar()
        self.transient(master.winfo_toplevel())

    def _filtros(self) -> dict | None:
        try:
            return self.painel.valores()
        except (ValueError, KeyError) as e:
            self._erro_filtro(e)
            return None

    def executar(self) -> None:
        f = self._filtros()
        if f is None:
            return
        self.f = f
        todos = self.ctx.relatorios.cupons(f)
        cupons = todos[-LIMITE_CUPONS:]
        self.grade.preencher([[c["cupom"], fmt.fmt_datahora(c["fechada_em"]), c["operador"] or "",
                               self.ctx.caixa.rotular_posicao(c["comanda"], c["posicao"]) if c["posicao"] else "",
                               "comanda" if c["comanda"] else c["modalidade"],
                               c["turno"] or "", "S" if c["atual"] else "N", "S" if c["cancelado"] else "N", fmt.fmt_num(c["total_cent"]),
                               fmt.fmt_num(c["desconto_cent"])] for c in cupons], [c["id"] for c in cupons],
                             [("cancelado",) if c["cancelado"] else () for c in cupons])
        if cupons:
            self.grade.selecionar_indice(10 ** 9)
        t = self.ctx.relatorios._totais(f)
        corte = (f"   |   MOSTRANDO OS {len(cupons)} ÚLTIMOS DE {len(todos)}: use os filtros para ver os demais"
                 if len(todos) > len(cupons) else "")
        self.resumo.configure(text=f"TC {t['tc']}   TM {fmt.fmt_brl(t['tm'])}   Produtos {fmt.fmt_brl(t['venda'])}   "
                                   f"Total apurado {fmt.fmt_brl(t['total'])}   ({len(cupons)} cupom(ns) listado(s)){corte}")

    def _detalhe(self, _=None) -> None:
        s = self.grade.selecionado()
        self.g_itens.limpar()
        self.g_pag.limpar()
        if s is None:
            return
        d = self.ctx.relatorios.cupom_detalhe(int(s))
        for i in d["itens"]:
            self.g_itens.adicionar([i["codigo"], i["nome"], "S" if i["cancelado"] else "N", fmt.fmt_qtd(i["quantidade"]), fmt.fmt_num(i["preco_unit_cent"])])
        for p in d["pagamentos"]:
            self.g_pag.adicionar([p["tipo"], fmt.fmt_num(p["valor_cent"])])

    def limpar(self) -> None:
        self.painel.limpar()
        self.executar()

    def tela(self) -> None:
        if self._filtros() is not None:
            self._mostrar(self.ctx.relatorios.vendas_periodo(self._filtros()))

    def fita(self) -> None:
        f = self._filtros()
        if f is not None:
            rel = self.ctx.relatorios.totalizacao_fita(f)
            Visualizador(self, self.ctx, "Venda no período (fita)", para_texto(rel, self.ctx.impressao.largura()), "venda_periodo_fita")

    def cancelar_cupom(self) -> None:
        s = self.grade.selecionado()
        if s is None:
            return
        v = self.ctx.caixa.obter(int(s))
        if v["status"] != "fechada":
            tema.aviso(self, "Este cupom já está cancelado.")
            return
        if self.ctx.acesso.precisa_senha(self.ctx.operador, "caixa_cancelamento", "exigir_senha_cancelamento"):
            if tema.pedir_senha_supervisor(self, self.ctx, "caixa_cancelamento", "Cancelar cupom exige autorização:") is None:
                return
        motivo = tema.pedir_texto(self, "Cancela cupom", f"Cancelar o cupom {v['cupom']} ({fmt.fmt_brl(v['total_cent'])}).\nMotivo:")
        if motivo is None:
            return
        ok, _ = tema.tratar(self, self.ctx.caixa.cancelar_venda, int(s), motivo)
        if ok:
            self.executar()


class JanelaEstoqueAtual(_Base):
    def __init__(self, master, ctx):
        super().__init__(master, ctx, "Estoque atual", "1100x740")
        self.dados: list = []
        f = ttk.LabelFrame(self, text="Critérios de consulta", padding=8)
        f.pack(fill="x", padx=10, pady=(10, 0))
        self.v_sit, self.v_data, self.v_vd, self.v_val, self.v_vv, self.v_un, self.v_sub = (tk.StringVar() for _ in range(7))
        self.v_sit.set("todos"); self.v_vd.set("menor"); self.v_vv.set("maior")
        sit = ttk.Frame(f)
        sit.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 18))
        ttk.Label(sit, text="Situação do estoque", style="Rotulo.TLabel").pack(anchor="w")
        for v, r in (("todos", "Todos"), ("normal", "Estoque normal"), ("ponto", "Ponto de pedido"), ("sem", "Sem estoque")):
            ttk.Radiobutton(sit, text=r, value=v, variable=self.v_sit).pack(anchor="w")
        ttk.Label(f, text="Última atualização (data)", style="Rotulo.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(f, textvariable=self.v_data, width=12).grid(row=1, column=1, sticky="w", padx=(0, 8))
        ttk.Combobox(f, textvariable=self.v_vd, values=["maior", "menor"], state="readonly", width=7).grid(row=1, column=2, sticky="w", padx=(0, 18))
        ttk.Label(f, text="Valor em estoque (R$)", style="Rotulo.TLabel").grid(row=0, column=3, sticky="w")
        ttk.Entry(f, textvariable=self.v_val, width=12).grid(row=1, column=3, sticky="w", padx=(0, 8))
        ttk.Combobox(f, textvariable=self.v_vv, values=["maior", "menor"], state="readonly", width=7).grid(row=1, column=4, sticky="w", padx=(0, 18))
        un = ctx.cadastros.opcoes("unidades"); sg = ctx.cadastros.opcoes("subgrupos")
        self.m_un = {r: i for i, r in un}; self.m_sg = {r: i for i, r in sg}
        ttk.Label(f, text="Unidade", style="Rotulo.TLabel").grid(row=0, column=5, sticky="w")
        ttk.Combobox(f, textvariable=self.v_un, values=[""] + list(self.m_un), state="readonly", width=12).grid(row=1, column=5, padx=(0, 14))
        ttk.Label(f, text="Sub grupo", style="Rotulo.TLabel").grid(row=0, column=6, sticky="w")
        ttk.Combobox(f, textvariable=self.v_sub, values=[""] + list(self.m_sg), state="readonly", width=20).grid(row=1, column=6)
        ttk.Label(f, text="'maior' = igual ou maior; 'menor' = igual ou menor. Ex.: parados há mais de 20 dias = data de 20 dias atrás, 'menor'.",
                  foreground=tema.COR["suave"]).grid(row=2, column=1, columnspan=6, sticky="w", pady=(6, 0))
        self._barra([("Executa consulta", self.executar, "left"), ("Limpa consulta", self.limpar, "left"), ("Tela (A4)", self.tela, "left"),
                     ("Impressora", self.impressora, "left"), ("Formulário de contagem", self.contagem, "left"),
                     ("Formulário de pedidos", self.pedidos, "left"), ("Saída", self.destroy, "right")])
        corpo = ttk.Frame(self, padding=(10, 0, 10, 10))
        corpo.pack(fill="both", expand=True)
        self.grade = tema.Grade(corpo, [("cod", "Código", 120, "w"), ("prod", "Produto", 330, "w"), ("min", "Mínimo", 80, "e"),
                                        ("atual", "Atual", 80, "e"), ("custo", "Custo", 80, "e"), ("total", "Total", 90, "e"),
                                        ("un", "Un", 50, "w"), ("upd", "Atualizado", 130, "w")], altura=18)
        self.grade.pack(fill="both", expand=True)
        self.grade.tag("normal", background=tema.COR["ok_linha"])
        self.grade.tag("ponto", background=tema.COR["ponto_linha"])
        self.grade.tag("sem", background=tema.COR["sem_linha"])
        self.resumo = ttk.Label(corpo, text="", font=tema.FONTE_B)
        self.resumo.pack(anchor="w", pady=(6, 0))
        self.executar()
        self.transient(master.winfo_toplevel())

    def _filtros(self) -> dict | None:
        f: dict = {}
        try:
            if self.v_sit.get() != "todos":
                f["situacao"] = self.v_sit.get()
            if self.v_data.get().strip():
                f["data"] = fmt.para_data_iso(self.v_data.get())
                f["verifica_datas"] = self.v_vd.get()
            if self.v_val.get().strip():
                f["valor"] = fmt.para_centavos(self.v_val.get())
                f["verifica_valores"] = self.v_vv.get()
        except ValueError as e:
            self._erro_filtro(e)
            return None
        if self.v_un.get():
            f["unidade_id"] = self.m_un[self.v_un.get()]
        if self.v_sub.get():
            f["subgrupo_id"] = self.m_sg[self.v_sub.get()]
        return f

    def executar(self) -> None:
        f = self._filtros()
        if f is None:
            return
        self.rel, self.dados = self.ctx.relatorios.estoque_atual(f)
        self.grade.preencher([[d["codigo"], d["nome"], fmt.fmt_qtd(d["estoque_minimo"]), fmt.fmt_qtd(d["qt_atual"]), fmt.fmt_num(d["ult_preco_cent"]),
                               fmt.fmt_num(d["total_cent"]), d["un"], fmt.fmt_datahora(d["ult_atualizacao"])] for d in self.dados],
                             [d["id"] for d in self.dados], [(d["situacao"],) for d in self.dados])
        total = sum(max(d["total_cent"], 0) for d in self.dados)
        self.resumo.configure(text=f"{len(self.dados)} produto(s)   |   Valor em estoque (custo): {fmt.fmt_brl(total)}   |   "
                                   "Verde = normal   Amarelo = ponto de pedido   Vermelho = zerado ou negativo")

    def limpar(self) -> None:
        for v in (self.v_data, self.v_val, self.v_un, self.v_sub):
            v.set("")
        self.v_sit.set("todos")
        self.executar()

    def tela(self) -> None:
        if self.rel is not None:
            self._mostrar(self.rel)

    def impressora(self) -> None:
        if self.rel is not None:
            self._imprimir(self.rel)

    def contagem(self) -> None:
        self._mostrar(self.ctx.relatorios.formulario_contagem(), 80)

    def pedidos(self) -> None:
        self._mostrar(self.ctx.relatorios.formulario_pedidos(), 80)
