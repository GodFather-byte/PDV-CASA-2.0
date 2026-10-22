"""Janela principal: login, os sete botões do menu (manual ADM seção 1) e o painel de resumo."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from src.controllers.acesso_controller import GRUPOS_MENU
from src.controllers.config_controller import modulos_desligados
from src.controllers.fila_impressao_controller import ServicoFilaImpressao
from src.controllers.telegram_controller import ServicoTelegram
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.sync.ponte import ServicoPonte
from src.ui import icone as icone_janela
from src.ui import caixa_tema, paleta, tema
from src.ui.contexto import Contexto
from src.ui.login import JanelaLogin
from src.ui.menu_widgets import PAL, FONTE, Atalho, Aviso, BarraProporcao, Cartao, ConteudoRolavel, ItemNav
from src.versao import VERSAO

CADASTROS = [("unidades", "Unidades"), ("grupos", "Grupos"), ("subgrupos", "Subgrupos"), ("produtos", "Produtos"),
             ("observacoes", "Observações"), ("composicao", "Composição"), ("cargos", "Cargos"),
             ("operadores", "Operadores"), ("fornecedores", "Fornecedores"), ("clientes", "Clientes"), ("garotas", "Garotas"),
             ("bairros", "Bairros e taxas de entrega"), ("tipos_pagamento", "Tipos de Pagamento"),
             ("planos_contas", "Plano de Contas"), ("subplanos", "Sub Planos"), ("aliquotas", "Alíquotas"),
             ("setores_impressao", "Setores de Impressão")]
MODULO_CADASTRO = {"planos_contas": "cad_plano_contas"}   # os demais seguem o padrão cad_<chave>

LANCAMENTOS = [("contas", "Contas", "lanc_contas"), ("estoque", "Estoque", "lanc_estoque")]

RELATORIOS = [
    ("Vendas", [("vendas_periodo", "Venda no período", "rel_vendas"), ("vendas_grupo", "Venda por grupo", "rel_vendas_grupo"),
                ("mais_vendidos", "Produtos mais vendidos", "rel_vendas_grupo"),
                ("informativo", "Informativo por dia", "rel_informativos"), ("horas", "Vendas por hora", "rel_informativos"),
                ("cancelados", "Cancelamentos", "rel_informativos")]),
    ("Caixa", [("caixa_mov", "Entradas e saídas financeiras", "rel_caixa"), ("fechamentos", "Fechamentos do caixa", "rel_caixa"),
               ("comandas", "Comandas", "rel_comandas"), ("garcons", "Garçons", "rel_garcons"),
               ("auditoria_operadores", "Auditoria por operador", "rel_auditoria"),
               ("auditoria_eventos", "Alterações e auditoria detalhada", "rel_auditoria"),
               ("comissao_garotas", "Comissão das garotas", "rel_comissao_garotas")]),
    ("Gestão", [("cmv", "C.M.V. (custo da mercadoria vendida)", "rel_cmv"),
                ("comissao_produto", "Comissão por produto", "rel_comissoes"), ("comissao_venda", "Comissão por venda", "rel_comissoes"),
                ("comissao_cliente", "Vendas por cliente", "rel_comissoes")]),
    ("Clientes", [("clientes_inativos", "Clientes inativos", "rel_clientes"), ("clientes_resumo", "Entrega e caderneta por cliente", "rel_clientes")]),
    ("Financeiro", [("resultado_financeiro", "Resultado financeiro", "rel_financeiro"), ("extrato_contas", "Extrato de contas", "rel_financeiro")]),
    ("Estoque", [("estoque_atual", "Estoque atual", "rel_estoque"), ("mov_estoque", "Movimento de estoque", "rel_estoque"),
                 ("posicao_estoque", "Posição por período", "rel_estoque"), ("custo_medio", "Preço médio de compra", "rel_informativos"),
                 ("form_contagem", "Formulário de contagem", "rel_estoque"), ("form_pedidos", "Formulário de pedidos", "rel_estoque")]),
]

UTILITARIOS = [("limpeza", "Limpeza do movimento", "util_limpeza"),
               ("excluir_produtos", "Excluir todos os produtos", "util_excluir_produtos"),
               ("comunicacao", "Programa de comunicação", "util_comunicacao"),
               ("backup", "Backup de dados", "util_backup"), ("restaurar", "Restaurar backup", "util_backup"),
               ("backup_externo", "Backup externo criptografado", "util_backup"),
               ("suporte", "Pacote de suporte (log de erros)", "util_backup"),
               ("fila_impressao", "Fila de impressão", "util_fila_impressao"),
               ("cozinha", "Painel da Cozinha/Bar", "util_cozinha")]
CONFIGURACOES = [("acessos", "Acessos", "cfg_acessos"), ("loja", "Loja", "cfg_loja"),
                 ("configuracoes", "Configurações", "cfg_configuracoes"), ("maquinas", "Máquinas", "cfg_maquinas"),
                 ("telegram", "Telegram (celular do dono)", "cfg_telegram")]

BOTOES = [("Cadastros", "Cadastros", "m"), ("Caixa", "Caixa", "c"), ("Lançamentos", "Lançamentos", "l"),
          ("Relatórios", "Relatórios", "r"), ("Utilitários", "Utilitários", "u"), ("Configurações", "Configurações", "o"),
          ("Encerrar sessão", "Saída", "s")]
def icones() -> dict:
    """A letra e a cor de cada botão do menu (as cores acompanham o modo claro/escuro em uso)."""
    return {"Cadastros": ("C", PAL["azul"]), "Caixa": ("$", PAL["verde"]), "Lançamentos": ("+", PAL["ambar"]),
            "Relatórios": ("R", PAL["violeta"]), "Utilitários": ("U", PAL["turquesa"]), "Configurações": ("O", PAL["ardosia"]),
            "Saída": ("S", PAL["vermelho"])}
DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


class App:
    def __init__(self, banco: BancoDados | None = None):
        self.banco = banco or BancoDados()
        self.root = tk.Tk()
        self.root.withdraw()
        paleta.aplicar_da_configuracao(self.banco)               # modo claro ou escuro (Configurações > Aparência)
        tema.aplicar_tema(self.root)
        icone_janela.aplicar(self.root)
        self.ctx = Contexto(self.banco)
        self.ctx.ao_mudar_tema = self.aplicar_visual
        self.janelas: dict[str, tk.Toplevel] = {}
        self.servico_impressao: ServicoFilaImpressao | None = None
        self.servico_telegram: ServicoTelegram | None = None
        self.servico_ponte: ServicoPonte | None = None
        self.menu: tk.Frame | None = None
        self.root.protocol("WM_DELETE_WINDOW", self.sair)
        self.root.report_callback_exception = self._erro_na_tela      # erro dentro de uma tela: registra e avisa, não derruba
        self._ultimo_erro = (0.0, "")
        self._relogio_id = None
        self._tic_id = None
        self._teclas: list[str] = []
        self._permitidos: set[str] = set()
        self._consulta_versao: dict | None = None      # {"pronta": bool, "dados": ...}: a thread da rede escreve aqui

    # ---------------------------------------------------------------- fluxo
    def aplicar_visual(self, modo: str) -> None:
        """Troca o modo claro/escuro em uso: novas cores, estilos refeitos, menu refeito e telas abertas fechadas (cada uma guarda as
        cores de quando foi aberta; fechar evita uma tela meio clara e meio escura)."""
        paleta.aplicar(modo)
        tema.aplicar_tema(self.root)
        caixa_tema.aplicar(self.root)
        for j in list(self.janelas.values()):
            try:
                j.destroy()
            except tk.TclError:
                pass
        self.janelas.clear()
        self.root.configure(bg=PAL["fundo"])
        if self.menu is not None:
            self.mostrar_menu()
        self.banco.log("tema_visual", modo, self.ctx.operador_id)

    def _erro_na_tela(self, tipo, valor, tb) -> None:
        """Exceção que escapou de um evento da tela (clique, tecla, temporizador). Fica no log com o traceback completo; o
        operador vê uma mensagem clara (a mesma falha repetida em sequência só avisa uma vez)."""
        import time
        from src.core import registro
        registro.registrar_excecao(tipo, valor, tb, "tela")
        agora, anterior = time.monotonic(), self._ultimo_erro
        chave = f"{tipo.__name__}:{valor}"
        self._ultimo_erro = (agora, chave)
        if chave == anterior[1] and agora - anterior[0] < 10:
            return
        try:
            tema.erro(self.root, "Ocorreu um erro inesperado nesta tela.\nO que já estava gravado foi preservado.\n"
                                 "Se repetir, gere o pacote de suporte em Utilitários e envie ao fornecedor.", "Erro")
        except tk.TclError:
            pass

    def run(self) -> None:
        self._iniciar_fila_impressao()
        self._iniciar_telegram()
        self._iniciar_ponte()
        idade = self.ctx.utilitarios.idade_backup_horas()
        if idade is None or idade >= 12:                 # abriu o caixa e a última cópia é antiga: faz uma agora
            self.ctx.utilitarios.backup_automatico("início")
        self.root.after(80, self.entrar)
        self.root.mainloop()
        self.ctx.utilitarios.backup_automatico("saída", minimo_min=60)
        if self.servico_impressao is not None:
            self.servico_impressao.parar()
        if self.servico_telegram is not None:
            self.servico_telegram.parar()
        if self.servico_ponte is not None:
            self.servico_ponte.parar()
        self.banco.fechar()

    def _iniciar_ponte(self) -> None:
        if self.banco.caminho == ":memory:":
            return
        self.servico_ponte = ServicoPonte(self.banco.caminho)
        self.servico_ponte.iniciar()

    def _iniciar_fila_impressao(self) -> None:
        """Thread que esvazia a fila da impressora térmica/cozinha. Precisa de banco em arquivo (conexão própria)."""
        try:
            self.servico_impressao = ServicoFilaImpressao(self.banco.caminho)
            self.servico_impressao.iniciar()
        except ErroNegocio:
            self.servico_impressao = None

    def _iniciar_telegram(self) -> None:
        """Threads do Telegram do dono (avisos e botões). Ficam paradas, sem rede, enquanto não houver token configurado."""
        try:
            self.servico_telegram = ServicoTelegram(self.banco.caminho)
            self.servico_telegram.iniciar()
        except ErroNegocio:
            self.servico_telegram = None

    def entrar(self) -> None:
        self._destruir_menu()
        self.root.withdraw()
        dlg = JanelaLogin(self.root, self.ctx, self.ctx.config.nome_loja())
        self.root.wait_window(dlg)
        if dlg.operador is None:
            self.root.destroy()
            return
        self.ctx.operador = dlg.operador
        self.banco.log("login", dlg.operador.nome, dlg.operador.id)
        if dlg.operador.so_caixa:
            self.abrir_caixa()
            self.root.after(50, self.entrar)
        else:
            self.mostrar_menu()

    def sair(self) -> None:
        if self.ctx.operador is None:
            self.root.destroy()
            return
        if tema.confirmar(self.root, "Encerrar a sessão e voltar à tela de entrada?", "Saída"):
            for j in list(self.janelas.values()):
                try:
                    j.destroy()
                except tk.TclError:
                    pass
            self.janelas.clear()
            self.banco.log("logout", self.ctx.operador.nome, self.ctx.operador.id)
            self.ctx.operador = None
            self.root.after(50, self.entrar)

    # ----------------------------------------------------------------- menu
    def _parar_temporizadores(self, evento=None) -> None:
        """Cancela o relógio e a atualização periódica do painel (também quando a janela é destruída por fora)."""
        if evento is not None and evento.widget is not self.menu:
            return
        for nome in ("_relogio_id", "_tic_id"):
            id_ = getattr(self, nome)
            if id_:
                try:
                    self.root.after_cancel(id_)
                except tk.TclError:
                    pass
                setattr(self, nome, None)

    def _destruir_menu(self) -> None:
        self._parar_temporizadores()
        if self.menu is not None:
            self.menu.destroy()
            self.menu = None

    def mostrar_menu(self) -> None:
        self._destruir_menu()
        r, ctx = self.root, self.ctx
        r.title(f"PDV - {ctx.config.nome_loja()}")
        r.geometry(f"{min(1280, max(1000, r.winfo_screenwidth() - 80))}x{min(800, max(600, r.winfo_screenheight() - 90))}")
        r.minsize(1000, 600)
        self._permitidos = ({m["modulo"] for g in GRUPOS_MENU for m in ctx.acesso.modulos_permitidos(ctx.operador, g)}
                            - modulos_desligados(self.banco))
        self.menu = tk.Frame(r, bg=PAL["fundo"])
        self.menu.pack(fill="both", expand=True)
        self.menu.bind("<Destroy>", self._parar_temporizadores)
        self._montar_cabecalho(self.menu)
        corpo = tk.Frame(self.menu, bg=PAL["fundo"])
        corpo.pack(fill="both", expand=True)
        self._montar_lateral(corpo)
        self._montar_conteudo(corpo)
        self._ligar_teclas()
        r.deiconify()
        r.lift()
        r.focus_force()
        self._tic()
        self.atualizar_painel()
        self.consultar_atualizacoes()
        if not ctx.config.loja_cadastrada() and ctx.acesso.pode(ctx.operador, "cfg_loja"):
            r.after(150, self.cadastrar_loja)

    def cadastrar_loja(self) -> None:
        """Primeiro uso: pede o nome da casa (ele sai nos comprovantes). 'Depois' adia para a próxima entrada."""
        from src.ui import cadastro_loja_ui
        if self.menu is not None and cadastro_loja_ui.pedir(self.root, self.ctx):
            self.mostrar_menu()                       # o nome novo aparece no cabeçalho da tela

    def _montar_cabecalho(self, pai) -> None:
        ctx, op = self.ctx, self.ctx.operador
        nome = ctx.config.nome_loja()
        cab = tk.Frame(pai, bg=PAL["cabecalho"], height=72)
        cab.pack(fill="x")
        cab.pack_propagate(False)
        tk.Label(cab, text=(nome[:1] or "P").upper(), font=(FONTE, 18, "bold"), fg=PAL["sobre"], bg=PAL["azul"], width=3
                 ).pack(side="left", padx=(20, 14), pady=14, fill="y")
        textos = tk.Frame(cab, bg=PAL["cabecalho"], width=320)
        textos.pack(side="left", fill="y", pady=12)
        textos.pack_propagate(False)
        tk.Label(textos, text=f"WILLPDV  /  {VERSAO}", font=(FONTE, 8, "bold"), fg=PAL["suave"],
                 bg=PAL["cabecalho"]).pack(anchor="w")
        nome_lbl = tk.Label(textos, text=nome, font=(FONTE, 16, "bold"), fg=PAL["texto"], bg=PAL["cabecalho"], anchor="w")
        nome_lbl.pack(fill="x")
        textos.bind("<Configure>", lambda e: nome_lbl.configure(wraplength=max(100, e.width)))

        chip = tk.Frame(cab, bg=PAL["cabecalho"])
        chip.pack(side="right", fill="y", padx=(10, 22), pady=14)
        tk.Label(chip, text=(op.nome[:1] or "?").upper(), font=(FONTE, 13, "bold"), fg=PAL["sobre"], bg=PAL["violeta"], width=3
                 ).pack(side="left", fill="y")
        quem = tk.Frame(chip, bg=PAL["cabecalho"])
        quem.pack(side="left", padx=(10, 0), fill="y")
        self.lbl_operador = tk.Label(quem, text=f"Operador: {op.nome}", font=(FONTE, 10, "bold"), fg=PAL["texto"],
                                     bg=PAL["cabecalho"], anchor="w")
        self.lbl_operador.pack(anchor="w")
        tk.Label(quem, text=f"Nível de acesso: {op.nivel}", font=(FONTE, 9), fg=PAL["suave"], bg=PAL["cabecalho"],
                 anchor="w").pack(anchor="w")
        tk.Frame(cab, width=1, bg=PAL["borda"]).pack(side="right", fill="y", pady=16)
        relogio = tk.Frame(cab, bg=PAL["cabecalho"])
        relogio.pack(side="right", padx=22, fill="y", pady=12)
        self.lbl_hora = tk.Label(relogio, text="", font=(FONTE, 18, "bold"), fg=PAL["texto"], bg=PAL["cabecalho"])
        self.lbl_hora.pack(anchor="e")
        self.lbl_data = tk.Label(relogio, text="", font=(FONTE, 9), fg=PAL["suave"], bg=PAL["cabecalho"])
        self.lbl_data.pack(anchor="e")
        tk.Frame(pai, height=1, bg=PAL["borda"]).pack(fill="x")

    def _tic(self) -> None:
        """Relógio do cabeçalho (1 por segundo)."""
        if self.menu is None:
            return
        agora = fmt.agora_dt()
        self.lbl_hora.configure(text=agora.strftime("%H:%M:%S"))
        self.lbl_data.configure(text=f"{DIAS_SEMANA[agora.weekday()]}, {agora.strftime('%d/%m/%Y')}")
        self._tic_id = self.root.after(1000, self._tic)

    def _montar_lateral(self, pai) -> None:
        visiveis = self.ctx.acesso.grupos_visiveis(self.ctx.operador) + ["Saída"]
        lat = tk.Frame(pai, bg=PAL["lateral"], width=250)
        lat.pack(side="left", fill="y")
        lat.pack_propagate(False)
        tk.Frame(pai, width=1, bg=PAL["borda"]).pack(side="left", fill="y")
        self.botoes: dict[str, ItemNav] = {}
        self._ordem_nav: list[str] = []
        self._nav_sel = -1

        def item(rotulo, grupo, letra):
            icone, cor = icones()[grupo]
            b = ItemNav(lat, rotulo, icone, cor, letra, lambda g=grupo: self.acionar(g), destaque=grupo == "Caixa")
            self.botoes[grupo] = b
            self._ordem_nav.append(grupo)
            return b

        tk.Label(lat, text="Setas: navegar  |  Enter: abrir", font=(FONTE, 9), fg=PAL["suave"], bg=PAL["lateral"]).pack(side="bottom", pady=(0, 16))
        saida = [x for x in BOTOES if x[1] == "Saída"][0]
        saida_item = item(*saida)
        saida_item.pack(side="bottom", fill="x", padx=12, pady=(3, 8))
        tk.Frame(lat, height=1, bg=PAL["borda"]).pack(side="bottom", fill="x", padx=18, pady=(8, 8))
        tk.Label(lat, text="NAVEGAÇÃO", font=(FONTE, 9, "bold"), fg=PAL["suave"], bg=PAL["lateral"]).pack(anchor="w", padx=22, pady=(22, 10))
        for rotulo, grupo, letra in BOTOES:
            if grupo in visiveis and grupo != "Saída":
                item(rotulo, grupo, letra).pack(fill="x", padx=12, pady=3)
        self._ordem_nav.remove("Saída")
        self._ordem_nav.append("Saída")                 # a Saída é a última na ordem das setas

    def _montar_conteudo(self, pai) -> None:
        self.painel_rolavel = ConteudoRolavel(pai)
        self.painel_rolavel.pack(side="left", fill="both", expand=True)
        cont = self.painel_rolavel.corpo
        self.cartoes: dict[str, Cartao] = {}
        self.valores: dict[str, tk.Label] = {}
        op = self.ctx.operador

        # saudação + botão de atualizar
        topo = tk.Frame(cont, bg=PAL["fundo"])
        topo.pack(fill="x")
        h = fmt.agora_dt().hour
        saudacao = "Bom dia" if h < 12 else "Boa tarde" if h < 18 else "Boa noite"
        textos = tk.Frame(topo, bg=PAL["fundo"])
        textos.pack(side="left")
        tk.Label(textos, text=f"{saudacao}, {op.nome.title()}", font=(FONTE, 20, "bold"), fg=PAL["texto"], bg=PAL["fundo"]).pack(anchor="w")
        self.lbl_atualiz = tk.Label(textos, text="", font=(FONTE, 9), fg=PAL["suave"], bg=PAL["fundo"])
        self.lbl_atualiz.pack(anchor="w")
        Atalho(topo, "Atualizar  (F5)", PAL["azul"], self.atualizar_painel).pack(side="right", anchor="n")

        # A ação principal fica visível antes dos indicadores e tarefas administrativas.
        self.atalho_caixa = Atalho(cont, "Abrir caixa", PAL["verde"], self.abrir_caixa,
                                   "Inicie o atendimento, lance consumos e receba pagamentos.  |  Tecla C", destaque=True)
        self.atalho_caixa.pack(fill="x", pady=(18, 0))

        # avisos (backup e versão nova)
        avisos = tk.Frame(cont, bg=PAL["fundo"])
        avisos.pack(fill="x", pady=(10, 0))
        self.aviso_backup = Aviso(avisos, wraplength=600)
        self.aviso_backup.pack(anchor="w")
        self.lbl_backup = self.aviso_backup.texto
        self.aviso_licenca = Aviso(avisos, wraplength=600)
        self.aviso_licenca.pack(anchor="w")
        self.aviso_versao = Aviso(avisos, clique=self.abrir_aviso_versao, wraplength=500)
        self.lbl_versao = self.aviso_versao.texto

        # atalhos
        atalhos = self._atalhos()[1:]       # o caixa já tem seu próprio destaque acima
        self.atalhos_rapidos = {}
        if atalhos:
            self._secao(cont, "ACESSO RÁPIDO")
            linha = self._grade(cont, 2)
            detalhes = {"Lançar estoque": "Entradas, saídas e ajustes de produtos",
                        "Produtos": "Preços, códigos e cadastro de itens",
                        "Vendas do período": "Consulte o movimento e os resultados",
                        "Backup agora": "Salve uma cópia dos dados da loja"}
            for i, (texto, cor, acao) in enumerate(atalhos):
                b = Atalho(linha, texto, cor, acao, detalhe=detalhes[texto])
                b.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0, 12 if i % 2 == 0 else 0), pady=(0, 8))
                self.atalhos_rapidos[texto] = b

        # indicadores
        self._secao(cont, "VENDAS DE HOJE")
        g = self._grade(cont, 3)
        self._cartao(g, 0, "vendas_dia", "Vendas no dia", PAL["azul"], "cupons fechados na noite", self._acesso("rel_vendas", "vendas_periodo", self.abrir_relatorio))
        self._cartao(g, 1, "vendas_total", "Faturamento do dia", PAL["verde"], "soma dos cupons", self._acesso("rel_vendas", "vendas_periodo", self.abrir_relatorio))
        self._cartao(g, 2, "venda_media", "Venda média por cupom", PAL["violeta"], "faturamento ÷ vendas", self._acesso("rel_vendas", "vendas_periodo", self.abrir_relatorio))
        if self.banco.cfg_bool("usar_contas", False):
            self._secao(cont, "CONTAS")
            g = self._grade(cont, 2)
            abrir = self._acesso("lanc_contas", "contas", self.abrir_lancamento)
            self._cartao(g, 0, "contas_anteriores", "Contas anteriores não quitadas", PAL["vermelho"], "de dias anteriores", abrir)
            self._cartao(g, 1, "contas_hoje", "Contas de hoje não quitadas", PAL["ambar"], "abertas hoje", abrir)
        self._secao(cont, "ESTOQUE")
        g = self._grade(cont, 2)
        self._cartao(g, 0, "estoque_total", "Produtos em estoque", PAL["azul"], "controlados e ativos", self._acesso_estoque("todos"))
        self._cartao(g, 1, "estoque_sem", "Sem estoque", PAL["vermelho"], "", self._acesso_estoque("sem"))
        self._cartao(g, 2, "estoque_ponto", "Em ponto de pedido", PAL["ambar"], "", self._acesso_estoque("ponto"))
        self._cartao(g, 3, "estoque_normal", "Estoque normal", PAL["verde"], "", self._acesso_estoque("normal"))
        self.barra_estoque = BarraProporcao(cont, [PAL["vermelho"], PAL["ambar"], PAL["verde"]])
        self.barra_estoque.pack(fill="x", pady=(12, 0))
        self.lbl_barra = tk.Label(cont, text="", font=(FONTE, 9), fg=PAL["suave"], bg=PAL["fundo"], anchor="w")
        self.lbl_barra.pack(fill="x", pady=(4, 0))
        tel = self.ctx.config.loja().get("telefone") or ""
        if tel:
            tk.Label(cont, text=tel, font=(FONTE, 9), fg=PAL["mudo"], bg=PAL["fundo"]).pack(side="bottom", anchor="e")
        self.painel_rolavel.ligar_rolagem()

    def _secao(self, pai, texto: str) -> None:
        tk.Label(pai, text=texto, font=(FONTE, 9, "bold"), fg=PAL["suave"], bg=PAL["fundo"], anchor="w").pack(fill="x", pady=(20, 8))

    @staticmethod
    def _grade(pai, colunas: int) -> tk.Frame:
        g = tk.Frame(pai, bg=PAL["fundo"])
        g.pack(fill="x")
        g.columnconfigure(tuple(range(colunas)), weight=1, uniform="cartao")
        g._colunas = colunas
        return g

    def _cartao(self, grade, coluna: int, chave: str, titulo: str, cor: str, detalhe: str, clique=None) -> None:
        c = Cartao(grade, titulo, cor, detalhe, clique)
        c.grid(row=coluna // grade._colunas, column=coluna % grade._colunas, sticky="nsew",
               padx=(0, 0 if coluna % grade._colunas == grade._colunas - 1 else 12), pady=(0, 8))
        self.cartoes[chave] = c
        self.valores[chave] = c.valor

    def _acesso(self, modulo: str, chave: str, abrir):
        """Ação de clique de um cartão: só existe quando o operador pode abrir a tela (e a casa não desligou o módulo)."""
        return (lambda: abrir(chave)) if modulo in self._permitidos else None

    def _acesso_estoque(self, filtro: str):
        """Cartões de estoque: abrem o painel já filtrado; quem só tem o relatório vai para ele; sem nenhum dos dois, só informa."""
        if "lanc_estoque" in self._permitidos:
            return lambda: self.abrir_estoque(filtro)
        return self._acesso("rel_estoque", "estoque_atual", self.abrir_relatorio)

    def _atalhos(self) -> list[tuple]:
        """Ações rápidas do dia a dia; só aparecem as que o nível do operador permite."""
        p = self._permitidos
        todos = [("Abrir caixa", PAL["verde"], self.abrir_caixa, None),
                 ("Lançar estoque", PAL["ambar"], lambda: self.abrir_lancamento("estoque"), "lanc_estoque"),
                 ("Produtos", PAL["azul"], lambda: self.abrir_cadastro("produtos"), "cad_produtos"),
                 ("Vendas do período", PAL["violeta"], lambda: self.abrir_relatorio("vendas_periodo"), "rel_vendas"),
                 ("Backup agora", PAL["turquesa"], lambda: self.utilitario("backup"), "util_backup")]
        return [(t, c, a) for t, c, a, mod in todos if mod is None or mod in p]

    def _ligar_teclas(self) -> None:
        """Atalhos de teclado: a letra sublinhada abre o grupo; setas + Enter navegam; F5 atualiza."""
        r = self.root
        for seq in self._teclas:
            r.unbind(seq)
        self._teclas = []

        def ligar(seq, fn):
            r.bind(seq, fn)
            self._teclas.append(seq)

        for rotulo, grupo, letra in BOTOES:
            if grupo in self.botoes:
                for l in (letra, letra.upper()):
                    ligar(f"<KeyPress-{l}>", lambda e, g=grupo: self.acionar(g))
        ligar("<Down>", lambda e: self._mover_nav(1))
        ligar("<Up>", lambda e: self._mover_nav(-1))
        ligar("<Return>", lambda e: self._abrir_nav())
        ligar("<F5>", lambda e: self.atualizar_painel())

    def _foco_em_campo(self) -> bool:
        try:
            return isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry))
        except KeyError:   # foco em lista suspensa de combobox
            return True

    def _marcar_nav(self, grupo: str | None) -> None:
        for g, b in self.botoes.items():
            b.marcar(g == grupo)
        self._nav_sel = self._ordem_nav.index(grupo) if grupo in self._ordem_nav else -1

    def _mover_nav(self, passo: int) -> None:
        if self._foco_em_campo() or not self._ordem_nav:
            return
        i = (self._nav_sel + passo) % len(self._ordem_nav) if self._nav_sel >= 0 else (0 if passo > 0 else len(self._ordem_nav) - 1)
        self._marcar_nav(self._ordem_nav[i])

    def _abrir_nav(self) -> None:
        if 0 <= self._nav_sel < len(self._ordem_nav):
            self.acionar(self._ordem_nav[self._nav_sel])

    def atualizar_painel(self) -> None:
        if self.menu is None:
            return
        if self._relogio_id:                             # chamada manual (F5, voltar do caixa): não empilha temporizadores
            self.root.after_cancel(self._relogio_id)
        p = self.ctx.relatorios.painel()
        dinheiro = {"vendas_total", "venda_media"}
        total = p["estoque_total"]
        for chave, cartao in self.cartoes.items():
            valor = p[chave]
            detalhe = None
            if chave in ("estoque_sem", "estoque_ponto", "estoque_normal"):
                detalhe = f"{round(valor * 100 / total)}% dos produtos" if total else "nenhum produto controlado"
            cartao.definir(fmt.fmt_brl(valor) if chave in dinheiro else str(valor), detalhe)
        self.barra_estoque.definir([p["estoque_sem"], p["estoque_ponto"], p["estoque_normal"]])
        if total:
            pct = lambda n: round(n * 100 / total)      # noqa: E731
            self.lbl_barra.configure(text=f"Saúde do estoque:  {pct(p['estoque_normal'])}% normal   ·   "
                                          f"{pct(p['estoque_ponto'])}% no ponto de pedido   ·   {pct(p['estoque_sem'])}% sem estoque")
        else:
            self.lbl_barra.configure(text="Nenhum produto com controle de estoque ligado.")
        self.lbl_atualiz.configure(text=f"Última atualização:  {fmt.fmt_datahora(p['atualizado_em'])}")
        nivel, texto = self.ctx.utilitarios.situacao_backup()
        self.aviso_backup.definir(texto, PAL["verde"] if nivel == "ok" else PAL["vermelho"])
        self.mostrar_situacao_licenca()
        self.mostrar_aviso_versao()
        self._relogio_id = self.root.after(30_000, self.atualizar_painel)

    # --------------------------------------------------------- atualizações
    def mostrar_situacao_licenca(self) -> None:
        from src.core import licenca
        estado = licenca.estado(self.banco)
        if estado.situacao == "desativada":
            self.aviso_licenca.pack_forget()
            return
        texto = (f"Licença válida até {fmt.fmt_data(estado.expira_em.isoformat())}."
                 if estado.expira_em else estado.mensagem)
        if estado.mensagem and estado.expira_em:
            texto = estado.mensagem
        from src.sync import ponte
        estado_ponte = ponte.estado(self.banco)
        sucesso = (estado_ponte["ultimo_sucesso"] if estado_ponte["ativa"] else
                   self.banco.cfg("licenca_nuvem_sucesso_em"))
        texto += (f" Última consulta bem-sucedida: {fmt.fmt_datahora(sucesso)}."
                  if sucesso else " Sem consulta bem-sucedida registrada nesta instalação.")
        falha = estado_ponte["erro"] if estado_ponte["ativa"] else self.banco.cfg("licenca_nuvem_erro")
        if falha:
            texto += " Ponte: consulte Configurações ou Suporte no Telegram." if estado_ponte["ativa"] else f" Nuvem: {falha}"
        cor = PAL["vermelho"] if estado.bloqueia else PAL["ambar"] if estado.avisa or falha else PAL["verde"]
        self.aviso_licenca.definir(texto, cor)
        self.aviso_licenca.pack(anchor="w")

    def mostrar_aviso_versao(self) -> None:
        """Aviso no topo da tela quando há versão nova (vermelho se for crítica). Clicar abre as notas."""
        from src.sync import atualizacoes
        from src.ui import atualizacao_ui
        aviso = atualizacoes.pendente(self.banco)
        if aviso is None:
            self.aviso_versao.pack_forget()
            return
        self.aviso_versao.definir(atualizacao_ui.texto_faixa(aviso), PAL["vermelho"] if aviso["critica"] else PAL["ambar"])
        self.aviso_versao.pack(anchor="w", before=self.aviso_backup, pady=(0, 8))

    def abrir_aviso_versao(self) -> None:
        from src.sync import atualizacoes
        from src.ui import atualizacao_ui
        aviso = atualizacoes.pendente(self.banco)
        if aviso is not None:
            atualizacao_ui.mostrar(self.root, self.banco, aviso)
            self.mostrar_aviso_versao()

    def consultar_atualizacoes(self) -> None:
        """Pergunta à nuvem se há versão nova, numa thread (a rede não pode travar a tela). O banco só é usado aqui, na
        thread da tela: a thread recebe o endereço e o token prontos e devolve a resposta em self._consulta_versao."""
        from src.sync import atualizacoes
        url, token = self.banco.cfg("api_url"), self.banco.cfg("api_token")
        if not url.strip() or not token.strip() or not atualizacoes.precisa_consultar(self.banco) or self._consulta_versao:
            return
        estado = self._consulta_versao = {"pronta": False, "dados": None}

        def rede():
            estado["dados"] = atualizacoes.consultar(url, token)
            estado["pronta"] = True
        threading.Thread(target=rede, name="consulta-atualizacoes", daemon=True).start()
        self.root.after(500, self._receber_consulta)

    def _receber_consulta(self) -> None:
        from src.sync import atualizacoes
        estado = self._consulta_versao
        if estado is None:
            return
        if not estado["pronta"]:
            self.root.after(500, self._receber_consulta)
            return
        self._consulta_versao = None
        atualizacoes.gravar(self.banco, estado["dados"])
        if self.menu is not None:
            self.mostrar_aviso_versao()

    # --------------------------------------------------------------- ações
    def acionar(self, grupo: str) -> None:
        if self._foco_em_campo() or self.menu is None or grupo not in self.botoes:
            return
        self._marcar_nav(grupo)
        if grupo == "Saída":
            return self.sair()
        if grupo == "Caixa":
            return self.abrir_caixa()
        ctx = self.ctx
        estilo = dict(tearoff=0, font=(FONTE, 11), bg=PAL["cartao"], fg=PAL["texto"], activebackground=PAL["azul"],
                      activeforeground=PAL["sobre"], bd=0, relief="flat")
        m = tk.Menu(self.root, **estilo)
        permitidos = {x["modulo"] for x in ctx.acesso.modulos_permitidos(ctx.operador, grupo)} - modulos_desligados(self.banco)
        if grupo == "Cadastros":
            for chave, rotulo in CADASTROS:
                mod = MODULO_CADASTRO.get(chave, f"cad_{chave}")
                if mod in permitidos:
                    m.add_command(label=rotulo, command=lambda c=chave: self.abrir_cadastro(c))
        elif grupo == "Lançamentos":
            for chave, rotulo, mod in LANCAMENTOS:
                if mod in permitidos:
                    m.add_command(label=rotulo, command=lambda c=chave: self.abrir_lancamento(c))
        elif grupo == "Relatórios":
            for sub, itens in RELATORIOS:
                visiveis = [i for i in itens if i[2] in permitidos
                            and (i[0] != "auditoria_eventos" or ctx.operador.nivel == 4)]
                if visiveis:
                    sm = tk.Menu(m, **estilo)
                    for chave, rotulo, _ in visiveis:
                        sm.add_command(label=rotulo, command=lambda c=chave: self.abrir_relatorio(c))
                    m.add_cascade(label=sub, menu=sm)
        elif grupo == "Utilitários":
            for chave, rotulo, mod in UTILITARIOS:
                if mod in permitidos:
                    m.add_command(label=rotulo, command=lambda c=chave: self.utilitario(c))
        elif grupo == "Configurações":
            for chave, rotulo, mod in CONFIGURACOES:
                if mod in permitidos:
                    m.add_command(label=rotulo, command=lambda c=chave: self.abrir_config(c))
        b = self.botoes[grupo]
        try:
            m.tk_popup(b.winfo_rootx() + b.winfo_width() + 2, b.winfo_rooty())
        finally:
            m.grab_release()

    def _unica(self, chave: str, criar):
        j = self.janelas.get(chave)
        if j is not None and j.winfo_exists():
            j.deiconify()
            j.lift()
            j.focus_force()
            return j
        j = criar()
        self.janelas[chave] = j
        return j

    def abrir_caixa(self) -> None:
        from src.ui.caixa_ui import JanelaCaixa
        j = JanelaCaixa(self.root, self.ctx)
        self.root.wait_window(j)
        if self.menu is not None:
            self.atualizar_painel()

    def abrir_cadastro(self, chave: str) -> None:
        if chave == "composicao":
            from src.ui.composicao_ui import JanelaComposicao
            self._unica("composicao", lambda: JanelaComposicao(self.root, self.ctx))
            return
        from src.ui.cadastros_tk import JanelaCadastro
        self._unica("cad_" + chave, lambda: JanelaCadastro(self.root, self.ctx, chave))

    def abrir_lancamento(self, chave: str) -> None:
        if chave == "estoque":
            self.abrir_estoque()
            return
        from src.ui.lancamentos_ui import JanelaContas
        self._unica("lanc_contas", lambda: JanelaContas(self.root, self.ctx))

    def abrir_estoque(self, filtro: str = "todos") -> None:
        """Painel de Estoque (visão geral). Já aberta, a janela só troca o filtro e vem para a frente."""
        from src.ui.estoque_ui import PainelEstoque

        def criar():
            j = PainelEstoque(self.root, self.ctx, filtro)
            j.bind("<Destroy>", lambda e: self.atualizar_painel() if e.widget is j and self.menu is not None else None, add="+")
            return j
        j = self._unica("lanc_estoque", criar)
        if j.filtro != filtro:
            j.filtrar(filtro)

    def abrir_relatorio(self, chave: str) -> None:
        from src.ui.relatorios_ui import abrir_relatorio
        if chave == "auditoria_eventos":
            tema.tratar(self.root, self._unica, "auditoria_eventos", lambda: abrir_relatorio(self.root, self.ctx, chave))
            return
        abrir_relatorio(self.root, self.ctx, chave)

    def abrir_config(self, chave: str) -> None:
        from src.ui import config_ui
        self._unica("cfg_" + chave, lambda: config_ui.abrir(self.root, self.ctx, chave))

    def utilitario(self, chave: str) -> None:
        from src.ui import utilitarios_ui
        utilitarios_ui.executar(self.root, self.ctx, chave)
        self.atualizar_painel()


def main() -> None:
    from src.ui import inicializacao
    trava = inicializacao.iniciar()          # instância única, restauração marcada e checagem de integridade do banco
    if trava is None:
        return
    try:
        App().run()
    finally:
        trava.liberar()


if __name__ == "__main__":
    main()
