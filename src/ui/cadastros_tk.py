"""Tela genérica de cadastros (manual ADM seção 3 e 'botões de tarefas' da seção 2).

Monta formulário, grade e a barra Incluir/Excluir/Gravar/Cancelar/Filtrar/Pesquisar/Ordenar/
Tela/Imprimir/navegação/Sair a partir da descrição em controllers/entidades.py."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.controllers.entidades import ENTIDADES
from src.core import formatacao as fmt
from src.core.erros import ErroValidacao
from src.core.relatorio import Coluna, Relatorio, para_csv, para_texto
from src.ui import tema
from src.ui.visualizador import Visualizador


class _CampoUI:
    """Liga um Campo a um widget Tk e converte de/para o texto do formulário."""

    def __init__(self, pai, campo, cad):
        self.campo, self.cad = campo, cad
        self.quadro = ttk.Frame(pai)
        self.var = tk.StringVar()
        self.bool = tk.BooleanVar()
        self.mapa: dict[str, int] = {}
        t = campo.tipo
        if t == "sn":
            self.w = ttk.Checkbutton(self.quadro, text=campo.rotulo, variable=self.bool)
            self.w.pack(anchor="w")
            return
        marca = " *" if campo.obrigatorio else ""
        ttk.Label(self.quadro, text=campo.rotulo + marca, style="Rotulo.TLabel").pack(anchor="w")
        if t == "lookup":
            rotulos = cad.opcoes(campo.lookup)
            self.mapa = {r: i for i, r in rotulos}
            valores = ([] if campo.obrigatorio else [""]) + [r for _, r in rotulos]
            self.w = ttk.Combobox(self.quadro, textvariable=self.var, values=valores, state="readonly",
                                  width=max(campo.largura, 14))
        elif t == "escolha":
            valores = [r for _, r in campo.opcoes]
            self.w = ttk.Combobox(self.quadro, textvariable=self.var, values=valores, state="readonly",
                                  width=max(campo.largura, 8))
        else:
            self.w = ttk.Entry(self.quadro, textvariable=self.var, width=max(campo.largura, 8),
                               show="*" if t == "senha" else "",
                               state="readonly" if campo.somente_leitura else "normal")
        self.w.pack(anchor="w", fill="x")

    def get(self) -> str:
        t = self.campo.tipo
        if t == "sn":
            return "S" if self.bool.get() else "N"
        if t == "lookup":
            return str(self.mapa.get(self.var.get(), ""))
        return self.var.get()

    def set(self, texto: str, linha: dict | None = None) -> None:
        t = self.campo.tipo
        if t == "sn":
            self.bool.set(texto == "S")
        else:
            self.var.set(texto)

    def recarregar_opcoes(self) -> None:
        if self.campo.tipo == "lookup":
            rotulos = self.cad.opcoes(self.campo.lookup)
            self.mapa = {r: i for i, r in rotulos}
            self.w.configure(values=([] if self.campo.obrigatorio else [""]) + [r for _, r in rotulos])


class JanelaCadastro(tk.Toplevel):
    def __init__(self, master, ctx, chave: str):
        super().__init__(master)
        self.ctx, self.cad, self.ent = ctx, ctx.cadastros, ENTIDADES[chave]
        self.chave = chave
        self.id_atual: int | None = None
        self.texto_busca = ""
        self.ordem = self.ent.ordem
        self.filtros: dict = {}
        self.apenas_ativos = False
        self.title(self.ent.titulo)
        self.configure(bg=tema.COR["fundo"])
        self.geometry("1040x700")
        self.minsize(900, 560)
        self._barra()
        self._formulario()
        self._grade()
        self.status = ttk.Label(self, text="", foreground=tema.COR["suave"], padding=(10, 3))
        self.status.pack(fill="x", side="bottom")
        self._atalhos()
        self.carregar()
        self.transient(master.winfo_toplevel())

    # ------------------------------------------------------------- layout
    def _barra(self) -> None:
        barra = tk.Frame(self, bg=tema.COR["marinho"], padx=6, pady=5)
        barra.pack(fill="x")
        botoes = [("Incluir", self.incluir), ("Excluir", self.excluir), ("Gravar", self.gravar), ("Cancelar", self.cancelar),
                  None, ("Filtrar", self.filtrar), ("Pesquisar", self.pesquisar), ("Ordenar", self.ordenar),
                  None, ("Tela", self.ver_tela), ("Imprimir", self.imprimir),
                  None, ("|<", lambda: self.ir(0)), ("<", lambda: self.ir(self.grade.indice() - 1)),
                  (">", lambda: self.ir(self.grade.indice() + 1)), (">|", lambda: self.ir(10 ** 9))]
        for b in botoes:
            if b is None:
                tk.Frame(barra, width=14, bg=tema.COR["marinho"]).pack(side="left")
                continue
            ttk.Button(barra, text=b[0], style="Barra.TButton", command=b[1], width=len(b[0]) + 2 if len(b[0]) > 2 else 4
                       ).pack(side="left", padx=1)
        ttk.Button(barra, text="Sair", style="Barra.TButton", command=self.destroy).pack(side="right")
        extras = self._botoes_extras()
        if extras:     # segunda linha, para não espremer a barra principal
            self.extras = tk.Frame(self, bg=tema.COR["marinho2"], padx=6, pady=4)
            self.extras.pack(fill="x")
            for rotulo, comando in extras:
                ttk.Button(self.extras, text=rotulo, style="Barra.TButton", command=comando).pack(side="left", padx=2)

    def _formulario(self) -> None:
        secoes: dict[str, list] = {}
        for c in self.ent.campos:
            secoes.setdefault(c.secao, []).append(c)
        self.campos: dict[str, _CampoUI] = {}
        contenedor = ttk.Frame(self, padding=(10, 8, 10, 0))
        contenedor.pack(fill="x")
        if len(secoes) > 1:
            pai_secoes = ttk.Notebook(contenedor)
            pai_secoes.pack(fill="x")
        for nome_secao, campos in secoes.items():
            if len(secoes) > 1:
                pagina = ttk.Frame(pai_secoes, padding=10)
                pai_secoes.add(pagina, text=nome_secao)
            else:
                pagina = ttk.Frame(contenedor)
                pagina.pack(fill="x")
            normais = [c for c in campos if c.tipo != "sn"]
            flags = [c for c in campos if c.tipo == "sn"]
            colunas = 3 if len(normais) > 3 else max(len(normais), 1)
            for i, c in enumerate(normais):
                cu = _CampoUI(pagina, c, self.cad)
                cu.quadro.grid(row=i // colunas, column=i % colunas, sticky="w", padx=(0, 16), pady=(0, 6))
                self.campos[c.nome] = cu
            base = (len(normais) + colunas - 1) // colunas
            for i, c in enumerate(flags):
                cu = _CampoUI(pagina, c, self.cad)
                cu.quadro.grid(row=base + i // 3, column=i % 3, sticky="w", padx=(0, 16), pady=(0, 2))
                self.campos[c.nome] = cu
        primeiro = next(iter(self.campos.values()))
        self._primeiro = primeiro.w

    def _grade(self) -> None:
        self.cols = [c for c in self.ent.campos if c.na_grade]
        colunas = [(c.nome, c.rotulo, min(max(c.largura * 7, 60), 220), "e" if c.tipo in ("dinheiro", "decimal", "int") else "w")
                   for c in self.cols]
        quadro = ttk.Frame(self, padding=10)
        quadro.pack(fill="both", expand=True)
        self.grade = tema.Grade(quadro, colunas, altura=9)
        self.grade.pack(fill="both", expand=True)
        self.grade.tag("inativo", foreground=tema.COR["inativo"])
        self.grade.tree.bind("<<TreeviewSelect>>", self._ao_selecionar)
        self.grade.tree.bind("<Delete>", lambda e: self.excluir())

    def _atalhos(self) -> None:
        self.bind("<Control-s>", lambda e: self.gravar())
        self.bind("<Control-f>", lambda e: self.pesquisar())
        self.bind("<Insert>", lambda e: self.incluir())
        self.bind("<Escape>", lambda e: self.destroy())

    # --------------------------------------------------------------- dados
    def carregar(self, selecionar: int | None = None) -> None:
        self.linhas = self.cad.listar(self.chave, self.texto_busca or None, self.ordem, self.apenas_ativos, self.filtros)
        self._por_id = {l["id"]: l for l in self.linhas}
        textos = [self.cad.exibir(self.ent, l) for l in self.linhas]
        tags = [("inativo",) if self.ent.tem_ativo and not l.get("ativo", 1) else () for l in self.linhas]
        self.grade.preencher([[t[c.nome] for c in self.cols] for t in textos], [l["id"] for l in self.linhas], tags)
        alvo = selecionar if selecionar in self._por_id else (self.linhas[0]["id"] if self.linhas else None)
        info = []
        if self.texto_busca:
            info.append(f'busca "{self.texto_busca}"')
        if self.apenas_ativos:
            info.append("somente ativos")
        if self.filtros:
            info.append("filtrado")
        self.status.configure(text=f"{len(self.linhas)} registro(s)" + (" - " + ", ".join(info) if info else ""))
        if alvo is not None:
            self.grade.selecionar(alvo)
            self._mostrar(alvo)
        else:
            self._novo_formulario()

    def _ao_selecionar(self, _=None) -> None:
        s = self.grade.selecionado()
        if s is not None and int(s) != self.id_atual:
            self._mostrar(int(s))

    def _mostrar(self, id_: int) -> None:
        linha = self._por_id.get(id_) or self.cad.obter(self.chave, id_)
        if linha is None:
            return
        self.id_atual = id_
        textos = self.cad.exibir(self.ent, linha)
        for nome, cu in self.campos.items():
            cu.recarregar_opcoes()
            cu.set(textos[nome], linha)
        self._modo_senha(editando=True)

    def _novo_formulario(self) -> None:
        self.id_atual = None
        iniciais = self.cad.valores_iniciais(self.chave)
        for nome, cu in self.campos.items():
            cu.recarregar_opcoes()
            if cu.campo.tipo == "sn":
                cu.set("S" if iniciais.get(nome) == "S" else "N")
            else:
                cu.set(iniciais.get(nome, ""))
        self._modo_senha(editando=False)
        self._primeiro.focus_set()

    def _modo_senha(self, editando: bool) -> None:
        cu = self.campos.get("senha")
        if cu is not None:
            self.status.configure(text=self.status.cget("text").split(" | ")[0] +
                                  (" | senha em branco = manter a atual" if editando else ""))

    # ------------------------------------------------------------- comandos
    def incluir(self) -> None:
        self.grade.tree.selection_remove(self.grade.tree.selection())
        self._novo_formulario()

    def gravar(self) -> None:
        valores = {n: cu.get() for n, cu in self.campos.items() if not cu.campo.somente_leitura}
        ok, novo_id = tema.tratar(self, self.cad.salvar, self.chave, valores, self.id_atual)
        if ok:
            self.id_atual = novo_id
            self.carregar(novo_id)
            self.status.configure(text=self.status.cget("text") + "  |  Gravado")

    def cancelar(self) -> None:
        if self.id_atual is not None:
            self._mostrar(self.id_atual)
        else:
            self._novo_formulario()

    def excluir(self) -> None:
        if self.id_atual is None:
            return
        nome = self.cad.exibir(self.ent, self._por_id.get(self.id_atual) or {}).get(self.cols[0].nome, "")
        if not tema.confirmar(self, f"Excluir o registro '{nome}'?", "Excluir", padrao_sim=False):
            return
        ok, aviso = tema.tratar(self, self.cad.excluir, self.chave, self.id_atual)
        if ok:
            if aviso:
                tema.mensagem(self, aviso, "Produto guardado")
            indice = self.grade.indice()
            self.id_atual = None
            self.carregar()
            self.grade.selecionar_indice(indice)
            self._ao_selecionar()

    def pesquisar(self) -> None:
        texto = tema.pedir_texto(self, "Pesquisar", "Procurar por (vazio mostra todos):", self.texto_busca)
        if texto is not None:
            self.texto_busca = texto
            self.carregar()

    def ordenar(self) -> None:
        alfabetica = self.ordem == self.ent.ordem
        self.ordem = "id" if alfabetica else self.ent.ordem
        self.carregar(self.id_atual)
        self.status.configure(text=self.status.cget("text") + ("  |  ordem de cadastramento" if alfabetica else "  |  ordem alfabética"))

    def filtrar(self) -> None:
        dlg = tema.Dialogo(self, "Filtrar")
        ttk.Label(dlg.corpo, text="Mostrar somente registros com:", style="Rotulo.TLabel").pack(anchor="w", pady=(0, 6))
        combos = {}
        for c in self.ent.campos:
            if c.tipo == "lookup":
                opc = self.cad.opcoes(c.lookup)
                ttk.Label(dlg.corpo, text=c.rotulo).pack(anchor="w")
                var = tk.StringVar()
                atual = next((r for i, r in opc if i == self.filtros.get(c.nome)), "")
                var.set(atual)
                cb = ttk.Combobox(dlg.corpo, textvariable=var, values=[""] + [r for _, r in opc], state="readonly", width=34)
                cb.pack(anchor="w", pady=(0, 6))
                combos[c.nome] = (var, {r: i for i, r in opc})
        ativos = tk.BooleanVar(value=self.apenas_ativos)
        if self.ent.tem_ativo:
            ttk.Checkbutton(dlg.corpo, text="Somente ativos", variable=ativos).pack(anchor="w")
        if not combos and not self.ent.tem_ativo:
            ttk.Label(dlg.corpo, text="Este cadastro não tem filtros. Use Pesquisar.").pack()

        def aplicar():
            self.filtros = {n: m[v.get()] for n, (v, m) in combos.items() if v.get()}
            self.apenas_ativos = ativos.get()
            dlg.ok()
        tema._botoes(dlg, "Aplicar", comando_ok=aplicar)
        if dlg.mostrar():
            self.carregar(self.id_atual)

    def ir(self, indice: int) -> None:
        self.grade.selecionar_indice(indice)
        self._ao_selecionar()

    def _relatorio(self) -> Relatorio:
        rel = Relatorio(self.ent.titulo, [Coluna(c.rotulo, c.largura, "d" if c.tipo in ("dinheiro", "decimal", "int") else "e")
                                          for c in self.cols])
        for l in self.linhas:
            t = self.cad.exibir(self.ent, l)
            rel.add(*[t[c.nome] for c in self.cols])
        rel.rodape = [("Registros", str(len(self.linhas)))]
        return rel

    def ver_tela(self) -> None:
        rel = self._relatorio()
        Visualizador(self, self.ctx, rel.titulo, para_texto(rel, 100), self.chave, csv=para_csv(rel))

    def imprimir(self) -> None:
        rel = self._relatorio()
        v = Visualizador(self, self.ctx, rel.titulo, para_texto(rel, 80), self.chave, csv=para_csv(rel), modal=False)
        v.imprimir()

    # ------------------------------------------------------------- extras
    def _botoes_extras(self):
        ch = self.chave
        if ch == "produtos":
            return [("Importar planilha", self._importar_planilha), ("Ajustar estoque", self._ajustar_estoque),
                    ("Observações", self._abrir_observacoes),
                    ("Composição", self._abrir_composicao), ("Imprimir Tabela", self._tabela_precos)]
        if ch == "clientes":
            return [("Gerar arquivos", self._gerar_clientes)]
        if ch == "planos_contas":
            return [("Sub Planos", lambda: JanelaCadastro(self, self.ctx, "subplanos"))]
        return []

    def _importar_planilha(self) -> None:
        """Cadastra/atualiza vários produtos de uma vez a partir de uma planilha (CSV ou Excel), com prévia."""
        from src.ui.importar_produtos_ui import JanelaImportarProdutos
        JanelaImportarProdutos(self, self.ctx, self.carregar)

    def _ajustar_estoque(self) -> None:
        """Informa quanto o produto tem de verdade agora (contagem). Se ainda não controlava estoque, passa a controlar.
        O 'Qt. atual' do formulário é só leitura de propósito: toda mudança de quantidade vira um movimento no histórico."""
        if self.id_atual is None:
            tema.aviso(self, "Grave o produto antes de ajustar o estoque.")
            return
        p = self.ctx.produtos.por_id(self.id_atual)
        situacao = "Ainda não controla estoque: ao confirmar, ele passa a controlar." if not p["controla_estoque"] else \
            f"Hoje o sistema tem {fmt.fmt_qtd(p['qt_atual'])}."

        def validar(texto):
            q = fmt.para_qtd(texto)
            if q < 0:
                raise ValueError("A quantidade não pode ser negativa.")
            return q
        q = tema.pedir_texto(self, "Ajustar estoque", f"{p['nome']}\n{situacao}\nQuantos existem de verdade agora?",
                             fmt.fmt_qtd(p["qt_atual"]) if p["controla_estoque"] else "", largura=16, validar=validar)
        if q is None:
            return
        ok, _ = tema.tratar(self, self.ctx.estoque.registrar_rapido, self.id_atual, "contagem", q)
        if ok:
            linha = self.cad.obter(self.chave, self.id_atual)
            textos = self.cad.exibir(self.ent, linha)
            for nome in ("controla_estoque", "qt_atual", "qt_inicial"):          # só os campos de estoque: não perde o que está sendo digitado
                self.campos[nome].set(textos[nome], linha)
            self.status.configure(text=f"Estoque ajustado para {fmt.fmt_qtd(q)}.")

    def _abrir_observacoes(self) -> None:
        JanelaCadastro(self, self.ctx, "observacoes")

    def _abrir_composicao(self) -> None:
        from src.ui.composicao_ui import JanelaComposicao
        if self.id_atual is None:
            tema.aviso(self, "Grave o produto antes de montar a composição.")
            return
        JanelaComposicao(self, self.ctx, self.id_atual)

    def _tabela_precos(self) -> None:
        Visualizador(self, self.ctx, "Tabela de preços", self.ctx.impressao.tabela_precos(), "tabela_precos")

    def _gerar_clientes(self) -> None:
        """Exporta todos os clientes em texto (separador ';') para mala direta. Cada geração substitui a anterior."""
        from src.database.conexao import RAIZ
        pasta = RAIZ / "mala_direta"
        pasta.mkdir(exist_ok=True)
        caminho = pasta / "clientes.txt"
        campos = ["numero_consulta", "nome", "endereco", "complemento", "cep", "cidade", "telefone", "rg", "cpf", "email", "obs"]
        with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
            f.write(";".join(campos) + "\r\n")
            clientes = self.cad.listar("clientes", ordem="nome")
            for l in clientes:
                f.write(";".join(str(l.get(c) or "").replace(";", ",").replace("\n", " ") for c in campos) + "\r\n")
        tema.mensagem(self, f"{len(clientes)} cliente(s) exportado(s) em:\n{caminho}", "Gerar arquivos")
