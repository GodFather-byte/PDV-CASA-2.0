"""Importar produtos de uma planilha (CSV ou Excel): escolhe o arquivo, confere a PRÉVIA e só então grava tudo de uma vez.

Também baixa a planilha-modelo e exporta os produtos atuais (para editar preços na planilha e importar de volta).
Regras em `controllers/importacao_produtos.py`."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from src.controllers.config_controller import modulos_desligados
from src.controllers.importacao_produtos import ImportacaoNFe, ImportacaoProdutos, Previa, ler_tabela
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui import tema

TIPOS_ARQUIVO = [("Planilhas (Excel ou CSV)", "*.xlsx *.csv *.txt"), ("Todos os arquivos", "*.*")]
ROTULO_ACAO = {"criar": "Criar", "atualizar": "Atualizar", "recusar": "Recusado"}


class JanelaImportarProdutos(tk.Toplevel):
    def __init__(self, master, ctx, ao_importar=None):
        super().__init__(master)
        self.ctx, self.ao_importar = ctx, ao_importar
        self.imp = ImportacaoProdutos(ctx.banco, getattr(ctx, "operador_id", None))
        self.imp_nfe = ImportacaoNFe(ctx.banco, getattr(ctx, "operador_id", None))
        self.tabela: list[dict] | None = None
        self.previa: Previa | None = None
        self.title("Importar produtos")
        self.configure(bg=tema.COR["fundo"])
        # cabe também em notebook de 768 px (barra de tarefas e título do Windows tiram ~100 px): sem isso o botão Importar,
        # que fica embaixo, saía da tela
        tela_l, tela_a = self.winfo_screenwidth(), self.winfo_screenheight()
        self._larg, self._alt = min(1100, max(tela_l - 40, 640)), min(700, max(tela_a - 110, 460))
        self.geometry(f"{self._larg}x{self._alt}")
        self.minsize(min(820, self._larg), min(560, self._alt))
        self.v_atualizar = tk.BooleanVar(value=True)
        self.v_codigo = tk.StringVar(value="planilha")
        self.v_inicio = tk.StringVar(value=str(self.imp.numero_inicial_sugerido()))
        self.v_maiusculas = tk.BooleanVar(value=True)
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)

        barra = ttk.Frame(corpo)
        barra.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Button(barra, text="Fechar (Esc)", command=self.destroy).pack(side="right")

        topo = ttk.Frame(corpo)
        topo.pack(side="top", fill="x")
        ttk.Button(topo, text="1. Escolher a planilha...", command=self.escolher_arquivo).pack(side="left")
        ttk.Button(topo, text="Importar NF-e XML...", command=self.escolher_nfe).pack(side="left", padx=6)
        self.lbl_arquivo = ttk.Label(topo, text="Nenhuma planilha escolhida", foreground=tema.COR["suave"])
        self.lbl_arquivo.pack(side="left", padx=10)
        ttk.Button(topo, text="Baixar planilha modelo...", command=self.salvar_modelo).pack(side="right")
        ttk.Button(topo, text="Exportar produtos atuais...", command=self.exportar).pack(side="right", padx=6)
        self.btn_excluir_todos = ttk.Button(topo, text="Excluir todos os produtos...", command=self.excluir_todos)
        self.btn_excluir_todos.pack(side="right")
        if not ctx.acesso.pode(ctx.operador, "util_excluir_produtos"):       # só quem tem nível para os Utilitários de risco
            self.btn_excluir_todos.state(["disabled"])

        opcoes = ttk.LabelFrame(corpo, text="2. Como importar", padding=8)
        opcoes.pack(side="top", fill="x", pady=(10, 6))
        ttk.Checkbutton(opcoes, text="Atualizar os produtos que já existem (achados pelo código ou pelo nome)", variable=self.v_atualizar,
                        command=self.analisar).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(opcoes, text="Usar o código da planilha (os sem código recebem o próximo número livre)", value="planilha",
                        variable=self.v_codigo, command=self.analisar).grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(opcoes, text="Numerar tudo em sequência, a partir do número:", value="sequencia", variable=self.v_codigo,
                        command=self.analisar).grid(row=2, column=0, sticky="w")
        e = ttk.Entry(opcoes, textvariable=self.v_inicio, width=8)
        e.grid(row=2, column=1, sticky="w", padx=6)
        e.bind("<KeyRelease>", lambda ev: self.analisar())
        ttk.Label(opcoes, text="(pula os códigos reservados do caixa, como o da comissão das garotas)",
                  foreground=tema.COR["suave"]).grid(row=2, column=2, sticky="w")
        ttk.Checkbutton(opcoes, text="Escrever os nomes dos produtos em MAIÚSCULAS", variable=self.v_maiusculas,
                        command=self.analisar).grid(row=3, column=0, columnspan=3, sticky="w")

        passo3 = ttk.Frame(corpo)
        passo3.pack(side="top", fill="x", pady=(4, 4))
        self.b_importar = ttk.Button(passo3, text="Importar", style="Ok.TButton", command=self.importar, state="disabled")
        self.b_importar.pack(side="right", padx=(10, 0))
        self.lbl_resumo = ttk.Label(passo3, text="3. Confira a prévia abaixo e clique em Importar (botão verde, aqui ao lado).",
                                    font=tema.FONTE_B, wraplength=max(self._larg - 260, 300), justify="left")
        self.lbl_resumo.pack(side="left", fill="x", expand=True)
        self.grade = tema.Grade(corpo, [("lin", "Linha", 55, "e"), ("acao", "Ação", 90, "w"), ("cod", "Código", 65, "w"),
                                        ("nome", "Produto", 220, "w"), ("preco", "Preço", 80, "e"), ("com", "Comissão", 80, "e"),
                                        ("grupo", "Grupo", 160, "w"), ("qtd", "Estoque", 70, "e"), ("obs", "Observação", 300, "w")], altura=14)
        self.grade.pack(side="top", fill="both", expand=True)
        self.grade.tag("criar", foreground=tema.COR["ok"])
        self.grade.tag("atualizar", foreground=tema.COR["rotulo"])
        self.grade.tag("recusar", foreground=tema.COR["perigo"])
        self.bind("<Escape>", lambda e: self.destroy())
        # transient ANTES de centralizar: centralizar força o mapeamento da janela, e mapeá-la antes de ligá-la a uma janela-mãe
        # escondida deixava o Tk instável (segmentation fault no teste seguinte, no Linux).
        self.transient(master.winfo_toplevel())
        tema.centralizar(self, master.winfo_toplevel())
        self._caber_na_tela()

    def _caber_na_tela(self) -> None:
        """Garante que a janela inteira (com título e barra de tarefas) fique dentro da tela."""
        x = min(max(self.winfo_x(), 0), max(self.winfo_screenwidth() - self._larg, 0))
        y = min(max(self.winfo_y(), 0), max(self.winfo_screenheight() - self._alt - 80, 0))
        self.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------ arquivo
    def escolher_arquivo(self) -> None:
        caminho = filedialog.askopenfilename(parent=self, title="Planilha de produtos", filetypes=TIPOS_ARQUIVO)
        if caminho:
            self.carregar(caminho)

    def _exigir_acesso(self) -> None:
        if self.ctx.operador is None:
            raise ErroPermissao("Entre no sistema para importar produtos.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        entidade = self.ctx.cadastros.entidade("produtos")
        if entidade.modulo in modulos_desligados(self.ctx.banco):
            raise ErroPermissao("O cadastro de produtos está desativado.")
        self.ctx.acesso.exigir(self.ctx.operador, entidade.modulo)

    def escolher_nfe(self) -> None:
        caminho = filedialog.askopenfilename(
            parent=self, title="Importar NF-e", filetypes=[("NF-e XML", "*.xml"), ("Todos os arquivos", "*.*")])
        if not caminho:
            return
        try:
            self._exigir_acesso()
        except ErroNegocio as erro:
            tema.erro(self, str(erro))
            return
        ok, previa = tema.tratar(self, self.imp_nfe.analisar, caminho)
        if ok:
            JanelaImportarNFe(self, previa)

    def carregar(self, caminho: str) -> None:
        ok, tabela = tema.tratar(self, ler_tabela, caminho)
        if not ok:
            return
        self.tabela = tabela
        self.lbl_arquivo.configure(text=f"{Path(caminho).name}  ({len(tabela)} linhas)", foreground=tema.COR["texto"])
        self.analisar()

    def excluir_todos(self) -> None:
        """Apaga os produtos de uma vez para importar a planilha como cadastro novo (a regra e os avisos: utilitarios_ui)."""
        from src.ui import utilitarios_ui
        if not utilitarios_ui.excluir_produtos(self, self.ctx):
            return
        self.v_inicio.set(str(self.imp.numero_inicial_sugerido()))
        self.analisar()                                  # a prévia de uma planilha já escolhida muda: agora tudo é novo
        if self.ao_importar:
            self.ao_importar()

    def analisar(self) -> None:
        if self.tabela is None:
            return
        inicio = None
        if self.v_codigo.get() == "sequencia":
            try:
                inicio = max(int(self.v_inicio.get().strip() or 1), 1)
            except ValueError:
                self.lbl_resumo.configure(text="Digite só números no campo da sequência.", foreground=tema.COR["perigo"])
                return
        ok, previa = tema.tratar(self, self.imp.analisar, self.tabela, atualizar_existentes=self.v_atualizar.get(),
                                 sequencia_a_partir_de=inicio, usar_codigo_da_planilha=self.v_codigo.get() == "planilha",
                                 maiusculas=self.v_maiusculas.get())
        if not ok:
            return
        self.previa = previa
        linhas, ids, tags = [], [], []
        for n, l in enumerate(previa.linhas):
            obs = l.motivo or " ".join(l.avisos)
            linhas.append([str(l.linha), ROTULO_ACAO[l.acao], str(int(l.codigo)) if l.codigo.isdigit() else l.codigo, l.nome,
                           fmt.fmt_num(l.preco_cent) if l.acao != "recusar" or l.preco_cent else "",
                           f"{fmt.fmt_num(round(l.preco_cent * l.comissao_pct / 100))}" if l.comissao_pct else "", l.grupo,
                           fmt.fmt_qtd(l.quantidade).rstrip("0").rstrip(",") if l.quantidade is not None else "", obs])
            ids.append(str(n))
            tags.append((l.acao,))
        self.grade.preencher(linhas, ids, tags)
        # a coluna Comissão só aparece quando a planilha traz comissão
        com = any(l.comissao_pct for l in previa.linhas)
        self.grade.tree.configure(displaycolumns=[c[0] for c in self.grade.colunas if com or c[0] != "com"])
        recusados = previa.contar("recusar")
        self.lbl_resumo.configure(text=f"Prévia: {previa.resumo()}." + ("  Os recusados NÃO serão importados (veja o motivo na última coluna)."
                                                                       if recusados else ""),
                                  foreground=tema.COR["perigo"] if recusados else tema.COR["ok"])
        n = len(previa.importaveis)
        self.b_importar.configure(text=f"Importar {n} produto(s)", state="normal" if n else "disabled")

    # ------------------------------------------------------------------- ações
    def importar(self) -> None:
        if self.previa is None or not self.previa.importaveis:
            return
        n = len(self.previa.importaveis)
        if not tema.confirmar(self, f"Importar {n} produto(s) agora?\n\n{self.previa.resumo()}.\n"
                                    "Se algo der errado no meio, nada é gravado.", "Importar produtos", sim="Importar", nao="Voltar"):
            return
        ok, r = tema.tratar(self, self.imp.importar, self.previa)
        if not ok:
            return
        tema.mensagem(self, f"Pronto: {r['criados']} produto(s) criado(s), {r['atualizados']} atualizado(s)"
                            + (f" e {r['estoque']} com estoque lançado." if r["estoque"] else "."), "Importação concluída")
        if self.ao_importar:
            self.ao_importar()
        self.tabela = self.previa = None
        self.grade.limpar()
        self.lbl_arquivo.configure(text="Nenhuma planilha escolhida", foreground=tema.COR["suave"])
        self.lbl_resumo.configure(text="Importação concluída. Escolha outra planilha se precisar.", foreground=tema.COR["ok"])
        self.b_importar.configure(text="Importar", state="disabled")

    def _gravar(self, titulo: str, nome: str, texto: str) -> None:
        caminho = filedialog.asksaveasfilename(parent=self, title=titulo, initialfile=nome, defaultextension=".csv",
                                               filetypes=[("Planilha CSV (abre no Excel)", "*.csv")])
        if not caminho:
            return
        try:
            Path(caminho).write_text(texto, encoding="utf-8-sig", newline="")
        except OSError as e:
            tema.erro(self, f"Não consegui salvar o arquivo: {e}")
            return
        tema.mensagem(self, f"Arquivo salvo em:\n{caminho}", "Arquivo salvo")

    def salvar_modelo(self) -> None:
        self._gravar("Salvar planilha modelo", "modelo_produtos.csv", self.imp.modelo())

    def exportar(self) -> None:
        self._gravar("Exportar produtos", "produtos.csv", self.imp.exportar())


class JanelaImportarNFe(tk.Toplevel):
    """Conferência item a item da NF-e antes de atualizar o estoque."""

    def __init__(self, importacao, previa):
        super().__init__(importacao)
        self.importacao, self.previa = importacao, previa
        self.associacoes: dict[int, int | None] = {}
        self.precos_venda: dict[int, str] = {}
        self.title("Conferir NF-e")
        self.configure(bg=tema.COR["fundo"])
        self.geometry("1000x620")
        self.transient(importacao)

        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)
        ttk.Label(corpo, text=f"NF-e {previa.numero} • {previa.emitente}").pack(anchor="w")
        ttk.Label(corpo, text="A entrada atualiza custo e estoque, mas nunca altera o preço de venda.").pack(anchor="w", pady=(2, 8))
        filtros = ttk.Frame(corpo)
        filtros.pack(fill="x", pady=(0, 8))
        ttk.Label(filtros, text="Categoria para produtos novos:").pack(side="left")
        self.grupo = tk.StringVar(value="BAR")
        ttk.Combobox(filtros, textvariable=self.grupo, values=("BAR", "ADEGA"),
                     state="readonly", width=12).pack(side="left", padx=8)
        ttk.Label(filtros, text="Produtos sem preço ficam bloqueados para venda até o cadastro do preço.").pack(side="left")

        self.grade = ttk.Treeview(corpo, columns=("xml", "ean", "quantidade", "custo", "associacao"),
                                 show="headings", selectmode="browse", height=15)
        for coluna, titulo, largura in (
                ("xml", "Produto da nota", 300), ("ean", "EAN/GTIN", 140), ("quantidade", "Quantidade", 100),
                ("custo", "Custo unitário", 120), ("associacao", "Associação atual", 270)):
            self.grade.heading(coluna, text=titulo)
            self.grade.column(coluna, width=largura)
        self.grade.pack(fill="both", expand=True)
        self.grade.bind("<<TreeviewSelect>>", self._selecionar_item)

        associar = ttk.Frame(corpo)
        associar.pack(fill="x", pady=8)
        ttk.Label(associar, text="Associar item selecionado:").pack(side="left")
        self.opcao = tk.StringVar()
        self.combo = ttk.Combobox(associar, textvariable=self.opcao, state="readonly", width=70)
        self.combo.pack(side="left", fill="x", expand=True, padx=8)
        self.combo.bind("<<ComboboxSelected>>", self._alterar_associacao)
        self._opcoes = []
        ttk.Label(associar, text="Preço de venda opcional (R$):").pack(side="left")
        self.preco_novo = tk.StringVar()
        entrada_preco = ttk.Entry(associar, textvariable=self.preco_novo, width=12)
        entrada_preco.pack(side="left", padx=6)
        entrada_preco.bind("<KeyRelease>", self._alterar_preco)
        self.mensagem = ttk.Label(corpo, text="", foreground=tema.COR["perigo"])
        self.mensagem.pack(anchor="w")
        botoes = ttk.Frame(corpo)
        botoes.pack(fill="x", pady=(8, 0))
        ttk.Button(botoes, text="Confirmar entrada", command=self.confirmar).pack(side="right")
        ttk.Button(botoes, text="Cancelar", command=self.destroy).pack(side="right", padx=8)

        for indice, item in enumerate(previa.itens):
            associacao = self._nome_produto(item.produto_id) if item.produto_id else "Criar produto novo"
            self.grade.insert("", "end", iid=str(indice), values=(
                item.nome, item.codigo_barras or "—", fmt.fmt_qtd(item.quantidade),
                fmt.fmt_num(item.custo_unit_cent), associacao))
        if previa.itens:
            primeiro = self.grade.get_children()[0]
            self.grade.selection_set(primeiro)
            self._selecionar_item()

    def _nome_produto(self, produto_id):
        produto = self.importacao.ctx.banco.um("SELECT codigo, nome FROM produtos WHERE id = ?", (produto_id,))
        return f"{produto['codigo']} • {produto['nome']}" if produto else "Produto não encontrado"

    def _selecionar_item(self, _evento=None):
        selecionados = self.grade.selection()
        if not selecionados:
            return
        indice = int(selecionados[0])
        item = self.previa.itens[indice]
        opcoes = [(None, f"Criar novo: {item.nome}")]
        produtos = {}
        for sugestao in item.sugestoes:
            produtos[sugestao["id"]] = sugestao
        if item.produto_id:
            produto = self.importacao.ctx.banco.um(
                "SELECT id, codigo, nome FROM produtos WHERE id = ?", (item.produto_id,))
            if produto:
                produtos[produto["id"]] = dict(produto)
        opcoes.extend((p["id"], f"{p['codigo']} • {p['nome']}") for p in produtos.values())
        self._opcoes = opcoes
        self.combo.configure(values=[texto for _, texto in opcoes])
        selecionado = self.associacoes.get(item.numero, item.produto_id)
        indice_opcao = next((i for i, (pid, _) in enumerate(opcoes) if pid == selecionado), 0)
        self.combo.current(indice_opcao)
        self.preco_novo.set(self.precos_venda.get(item.numero, ""))

    def _alterar_associacao(self, _evento=None):
        selecionados = self.grade.selection()
        if not selecionados or not self._opcoes:
            return
        item = self.previa.itens[int(selecionados[0])]
        self.associacoes[item.numero] = self._opcoes[self.combo.current()][0]
        valores = list(self.grade.item(selecionados[0], "values"))
        valores[-1] = self.combo.get()
        self.grade.item(selecionados[0], values=valores)

    def _alterar_preco(self, _evento=None):
        selecionados = self.grade.selection()
        if selecionados:
            item = self.previa.itens[int(selecionados[0])]
            self.precos_venda[item.numero] = self.preco_novo.get()

    def confirmar(self):
        try:
            self.importacao._exigir_acesso()
        except ErroNegocio as erro:
            tema.erro(self, str(erro))
            return
        self._alterar_preco()
        if not tema.confirmar(self, f"Registrar {len(self.previa.itens)} item(ns) da NF-e {self.previa.numero} "
                                    "no estoque?", "Confirmar entrada", sim="Confirmar", nao="Voltar"):
            return
        precos = {}
        for item in self.previa.itens:
            associacao = self.associacoes.get(item.numero, item.produto_id)
            texto_preco = self.precos_venda.get(item.numero, "").strip()
            if associacao is None and texto_preco:
                try:
                    precos[item.numero] = fmt.para_centavos(texto_preco)
                    if precos[item.numero] < 0:
                        raise ValueError
                except ValueError:
                    tema.erro(self, f"Preço de venda inválido para '{item.nome}'.")
                    return
        ok, resultado = tema.tratar(
            self, self.importacao.imp_nfe.importar, self.previa, self.grupo.get(), self.associacoes, precos)
        if not ok:
            return
        avisos = resultado["alertas_margem"]
        mensagem = (f"Entrada concluída: {resultado['criados']} produto(s) criado(s), "
                    f"{resultado['atualizados']} atualizado(s).")
        if avisos:
            nomes = ", ".join(f"{p['nome']} ({p['margem_pct']:.1f}% < {p['minima_pct']:g}%)" for p in avisos)
            mensagem += "\nMargem mínima comprometida: " + nomes
        if self.importacao.ao_importar:
            self.importacao.ao_importar()
        tema.mensagem(self, mensagem, "Importação NF-e concluída")
        self.destroy()
