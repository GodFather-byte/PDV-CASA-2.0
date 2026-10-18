"""Configurações (manual ADM seção 8): acessos, loja, configurações operacionais e máquinas."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.controllers.config_controller import CAMPOS_CONFIG, CAMPOS_LOJA, CAMPOS_MAQUINA
from src.core.erros import ErroNegocio
from src.ui import paleta, tema
from src.ui.escolher_impressora_ui import JanelaEscolherImpressora
from src.ui.visualizador import Visualizador


def abrir(master, ctx, chave: str):
    if chave == "acessos":
        return JanelaAcessos(master, ctx)
    if chave == "loja":
        return JanelaFormulario(master, ctx, "Dados da Loja", [(c[0], c[1], c[2], "Dados", None) for c in CAMPOS_LOJA],
                                ctx.config.loja, ctx.config.salvar_loja, imprimivel=True)
    if chave == "telegram":
        from src.ui import telegram_ui
        return telegram_ui.abrir(master, ctx)
    if chave == "maquinas":
        campos = [(c[0], c[1], c[2], "Máquina", c[3] if len(c) > 3 else None) for c in CAMPOS_MAQUINA]

        def _testar(janela):
            ok, _ = tema.tratar(janela, ctx.config.salvar_maquina, janela._coletar())
            if ok:
                sucesso, _ = tema.tratar(janela, ctx.impressao.imprimir_teste)
                if sucesso:
                    tema.mensagem(janela, "Página de teste enviada à impressora térmica.", "Teste de impressão")

        def _gaveta(janela):
            ok, _ = tema.tratar(janela, ctx.config.salvar_maquina, janela._coletar())
            if ok:
                sucesso, _ = tema.tratar(janela, ctx.impressao.abrir_gaveta)
                if sucesso:
                    tema.mensagem(janela, "Pulso de abertura enviado à gaveta.", "Gaveta")

        return JanelaFormulario(master, ctx, "Máquinas", campos, ctx.config.maquina, ctx.config.salvar_maquina,
                                aviso="Atenção: as mudanças nas configurações do equipamento só valem depois de sair do programa e entrar novamente.",
                                somente_leitura=("terminal",),
                                acoes=[("Assistente de impressora (Elgin i9)", lambda j: abrir_assistente(j, ctx)),
                                       ("Escolher impressora do computador", lambda j: escolher_impressora(j, ctx, "termica")),
                                       ("Imprimir página de teste", _testar), ("Abrir gaveta", _gaveta)],
                                botoes_campo={"impressora_termica_endereco": ("Escolher da lista...", lambda j: escolher_impressora(j, ctx, "termica")),
                                              "impressora_remota_endereco": ("Escolher da lista...", lambda j: escolher_impressora(j, ctx, "remota"))})
    return JanelaFormulario(master, ctx, "Configurações", [(c[0], c[1], c[2], c[3], c[4] if len(c) > 4 else None) for c in CAMPOS_CONFIG],
                            ctx.config.todas, ctx.config.salvar_config,
                            depois_de_gravar=lambda janela: aplicar_visual(janela, ctx))


def aplicar_visual(janela, ctx) -> None:
    """Depois de gravar as configurações: se o operador trocou o modo claro/escuro, aplica na hora. A janela principal (via
    `ctx.ao_mudar_tema`) refaz o menu e fecha as telas abertas, que guardam as cores de quando abriram; sem ela (testes) só
    troca a paleta e os estilos."""
    novo = paleta.validar(ctx.banco.cfg(paleta.CHAVE, paleta.PADRAO))
    if novo == paleta.modo():
        return
    tema.mensagem(janela, f"Modo {paleta.MODOS[novo].lower()} escolhido. O visual muda agora: o menu é refeito e as telas "
                          "abertas são fechadas para adotar as cores novas.", "Aparência")
    if ctx.ao_mudar_tema is not None:
        ctx.ao_mudar_tema(novo)
    else:
        paleta.aplicar(novo)
        tema.aplicar_tema(janela.winfo_toplevel())


def abrir_assistente(janela, ctx):
    """Assistente que escolhe a impressora, grava a configuração certa e imprime o teste. Grava direto no banco, então a janela de
    Máquinas (aberta por trás) recarrega os campos quando o assistente configura, para um 'Gravar' dela não desfazer a escolha."""
    from src.ui.assistente_impressora_ui import JanelaAssistenteImpressora

    def recarregar() -> None:
        try:
            dados = ctx.config.maquina()
            for campo in ("modo_impressao", "impressora_termica_conexao", "impressora_termica_endereco", "impressora_termica_codepage",
                          "colunas_fita", "impressora_termica_cortar"):
                janela.definir(campo, dados[campo])
        except tk.TclError:
            pass            # a janela de Máquinas foi fechada com o assistente aberto
    return JanelaAssistenteImpressora(janela, ctx, recarregar)


def escolher_impressora(janela, ctx, alvo: str):
    """Abre a lista das impressoras deste computador e põe a escolha nos campos da janela de Máquinas.
    `alvo`: 'termica' (impressora do caixa) ou 'remota' (cozinha/bar)."""
    conexao, endereco = {"termica": ("impressora_termica_conexao", "impressora_termica_endereco"),
                         "remota": ("impressora_remota_conexao", "impressora_remota_endereco")}[alvo]

    def escolhida(con: str, end: str) -> None:
        try:
            janela.definir(conexao, con)
            janela.definir(endereco, end)
            if alvo == "termica" and janela.valor("modo_impressao") != "termica" and tema.confirmar(
                    janela, "O caixa ainda não está configurado para imprimir pela impressora térmica.\n"
                            "Ativar a impressão pela térmica agora?", "Impressora térmica"):
                janela.definir("modo_impressao", "termica")
            tema.mensagem(janela, f"Escolhida: {end}.\nClique em Gravar para guardar.", "Impressora")
        except tk.TclError:
            pass            # a janela de Máquinas foi fechada com a lista aberta
    return JanelaEscolherImpressora(janela, ctx, alvo, escolhida)


class JanelaFormulario(tk.Toplevel):
    """Formulário simples dirigido por lista de campos (chave, rótulo, tipo, seção, opções).
    `botoes_campo`: {chave: (texto, função(janela))} põe um botão ao lado do campo (ex.: escolher da lista)."""

    def __init__(self, master, ctx, titulo, campos, carregar, salvar, aviso: str | None = None,
                 imprimivel: bool = False, somente_leitura: tuple = (), acoes=None, botoes_campo: dict | None = None,
                 depois_de_gravar=None):
        super().__init__(master)
        self.ctx, self.campos, self.carregar, self.salvar = ctx, campos, carregar, salvar
        self.depois_de_gravar = depois_de_gravar            # função(janela) chamada depois de gravar com sucesso
        self.botoes: dict[str, ttk.Button] = {}
        self.somente_leitura = somente_leitura
        self.title(titulo)
        self.configure(bg=tema.COR["fundo"])
        self.geometry("900x660" if len({c[3] for c in campos}) > 1 else "760x560")
        barra = tk.Frame(self, bg=tema.COR["marinho"], padx=6, pady=5)
        barra.pack(fill="x")
        ttk.Button(barra, text="Gravar", style="Barra.TButton", command=self.gravar).pack(side="left", padx=2)
        ttk.Button(barra, text="Cancelar", style="Barra.TButton", command=self.recarregar).pack(side="left", padx=2)
        if imprimivel:
            ttk.Button(barra, text="Imprimir", style="Barra.TButton", command=self.imprimir).pack(side="left", padx=2)
        for rotulo, fn in (acoes or []):
            ttk.Button(barra, text=rotulo, style="Barra.TButton", command=lambda f=fn: f(self)).pack(side="left", padx=2)
        ttk.Button(barra, text="Sair", style="Barra.TButton", command=self.destroy).pack(side="right")
        if aviso:
            ttk.Label(self, text=aviso, foreground=tema.COR["aviso"], wraplength=800, padding=(12, 8, 12, 0)).pack(anchor="w")
        secoes: dict[str, list] = {}
        for c in campos:
            secoes.setdefault(c[3], []).append(c)
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)
        nb = ttk.Notebook(corpo) if len(secoes) > 1 else None
        if nb:
            nb.pack(fill="both", expand=True)
        self.vars: dict[str, tk.Variable] = {}
        self.opcoes: dict[str, dict] = {}
        for nome, lista in secoes.items():
            pagina = ttk.Frame(nb, padding=12) if nb else corpo
            if nb:
                nb.add(pagina, text=nome)
            for i, (chave, rotulo, tipo, _, opc) in enumerate(lista):
                if tipo == "sn":
                    v = tk.BooleanVar()
                    ttk.Checkbutton(pagina, text=rotulo, variable=v).grid(row=i, column=0, columnspan=2, sticky="w", pady=4)
                else:
                    v = tk.StringVar()
                    ttk.Label(pagina, text=rotulo, style="Rotulo.TLabel").grid(row=i, column=0, sticky="w", pady=4, padx=(0, 12))
                    if tipo == "escolha":
                        self.opcoes[chave] = {r: val for val, r in opc}
                        w = ttk.Combobox(pagina, textvariable=v, values=[r for _, r in opc], state="readonly", width=34)
                    else:
                        w = ttk.Entry(pagina, textvariable=v, width=46 if tipo == "texto" else 14,
                                      state="readonly" if chave in somente_leitura else "normal")
                    w.grid(row=i, column=1, sticky="w", pady=4)
                    if botoes_campo and chave in botoes_campo:
                        texto, funcao = botoes_campo[chave]
                        self.botoes[chave] = ttk.Button(pagina, text=texto, command=lambda f=funcao: f(self))
                        self.botoes[chave].grid(row=i, column=2, sticky="w", padx=8, pady=4)
                self.vars[chave] = v
        self.recarregar()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Control-s>", lambda e: self.gravar())
        tema.centralizar(self, master.winfo_toplevel())
        self.transient(master.winfo_toplevel())

    def recarregar(self) -> None:
        dados = self.carregar()
        for chave, rotulo, tipo, _, opc in self.campos:
            v = dados.get(chave)
            if tipo == "sn":
                self.vars[chave].set(str(v).upper() in ("S", "1", "TRUE"))
            elif tipo == "escolha":
                self.vars[chave].set(next((r for val, r in opc if str(val) == str(v)), ""))
            else:
                self.vars[chave].set("" if v is None else str(v))

    def definir(self, chave: str, valor) -> None:
        """Põe um valor no campo como se o operador o tivesse escolhido (em campo de opções, `valor` é o código)."""
        _, _, tipo, _, opc = next(c for c in self.campos if c[0] == chave)
        if tipo == "sn":
            self.vars[chave].set(str(valor).upper() in ("S", "1", "TRUE"))
        elif tipo == "escolha":
            self.vars[chave].set(next((r for val, r in opc if str(val) == str(valor)), ""))
        else:
            self.vars[chave].set("" if valor is None else str(valor))

    def valor(self, chave: str):
        """O que está no campo agora, no mesmo formato que será gravado (código da opção, 'S'/'N' ou o texto)."""
        return self._coletar().get(chave)

    def _coletar(self) -> dict:
        valores = {}
        for chave, _, tipo, _, opc in self.campos:
            if chave in self.somente_leitura:
                continue
            v = self.vars[chave].get()
            if tipo == "sn":
                v = "S" if v else "N"
            elif tipo == "escolha":
                v = self.opcoes[chave].get(v, v)
            valores[chave] = v
        return valores

    def gravar(self) -> None:
        ok, _ = tema.tratar(self, self.salvar, self._coletar())
        if ok:
            tema.mensagem(self, "Configurações gravadas.", "Gravar")
            if self.depois_de_gravar is not None:
                self.depois_de_gravar(self)

    def imprimir(self) -> None:
        l = self.ctx.config.loja()
        texto = "\n".join(f"{c[1]:<40} {l.get(c[0]) or ''}" for c in CAMPOS_LOJA)
        Visualizador(self, self.ctx, "Dados da loja", "DADOS DA LOJA\n" + "=" * 60 + "\n" + texto, "dados_loja")


class JanelaAcessos(tk.Toplevel):
    """Nível mínimo de cada módulo (1 a 4). O nível 0 já é o do caixa e não aparece."""

    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx = ctx
        self.title("Acessos ao sistema")
        self.configure(bg=tema.COR["fundo"])
        self.geometry("880x640")
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)
        ttk.Label(corpo, text="Cada módulo exige um nível mínimo. Os níveis são hierárquicos: o operador de nível 4 executa tudo o que "
                              "estiver restrito aos demais. O nível 0 é exclusivo da operação de caixa.",
                  wraplength=820, justify="left").pack(anchor="w", pady=(0, 8))
        self.grade = tema.Grade(corpo, [("grupo", "Grupo", 110, "w"), ("desc", "Módulo", 400, "w"), ("nivel", "Nível", 60, "center")], altura=18)
        self.grade.pack(fill="both", expand=True)
        edit = ttk.Frame(corpo)
        edit.pack(fill="x", pady=(10, 0))
        self.lbl = ttk.Label(edit, text="Selecione um módulo", font=tema.FONTE_B)
        self.lbl.pack(side="left")
        self.v_nivel = tk.StringVar(value="2")
        ttk.Button(edit, text="Gravar", style="Ok.TButton", command=self.gravar).pack(side="right")
        ttk.Combobox(edit, textvariable=self.v_nivel, values=["1", "2", "3", "4"], state="readonly", width=4).pack(side="right", padx=8)
        ttk.Label(edit, text="Novo nível:").pack(side="right")
        self.grade.tree.bind("<<TreeviewSelect>>", self._sel)
        self.bind("<Escape>", lambda e: self.destroy())
        self.carregar()
        tema.centralizar(self, master.winfo_toplevel())
        self.transient(master.winfo_toplevel())

    def carregar(self, manter: str | None = None) -> None:
        mods = self.ctx.acesso.modulos()
        self.grade.preencher([[m["grupo"], m["descricao"], m["nivel"]] for m in mods], [m["modulo"] for m in mods])
        self.grade.selecionar(manter) if manter else self.grade.selecionar_indice(0)

    def _sel(self, _=None) -> None:
        s = self.grade.selecionado()
        if s:
            v = self.grade.valores(s)
            self.lbl.configure(text=v[1])
            self.v_nivel.set(str(v[2]))

    def gravar(self) -> None:
        s = self.grade.selecionado()
        if s is None:
            return
        ok, _ = tema.tratar(self, self.ctx.acesso.alterar_nivel_modulo, s, int(self.v_nivel.get()))
        if ok:
            self.carregar(s)
