"""Diagnóstico de equipamentos (Tk): impressora, gaveta, balança e leitor.

Abrir: `abrir(master, ctx)` devolve a janela (ou levanta ErroPermissao antes de criá-la). Abrir não aciona nada; os
testes físicos pedem confirmação (padrão: Não), revalidam `cfg_maquinas` depois do diálogo e separam "comando enviado"
de "resultado confirmado pelo operador". O teste do leitor só consulta o cadastro: não vende nem mexe em estoque.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.controllers.diagnostico_controller import DISPOSITIVOS, DiagnosticoController
from src.core.erros import ErroNegocio
from src.ui import tema
from src.ui.menu_widgets import ConteudoRolavel

LARGURA_MINIMA, ALTURA_MINIMA = 560, 420
COR_ESTADO = {"erro": "perigo", "nao_confirmado": "perigo", "indisponivel": "aviso", "confirmado": "ok"}


class JanelaDiagnostico(tk.Toplevel):
    def __init__(self, master, ctx):
        self.ctx = ctx
        self.diag = DiagnosticoController(ctx)
        self.diag.exigir()                       # sem permissão, nem cria a janela
        super().__init__(master)
        self.title("Diagnóstico de equipamentos")
        self.configure(bg=tema.COR["fundo"])
        self.status: dict[str, ttk.Label] = {}
        self.resultados = {}
        self._rotulos: list[ttk.Label] = []
        ttk.Label(self, text="Diagnóstico de equipamentos", font=tema.FONTE_G).pack(anchor="w", padx=12, pady=(10, 2))
        self._rotulo(self, "Abrir esta tela não aciona nenhum equipamento. Os testes físicos pedem confirmação e só "
                           "contam como funcionando quando você confirmar o que viu. Nada aqui lança venda, estoque "
                           "ou movimento de caixa.").pack(fill="x", padx=12)
        barra = ttk.Frame(self, padding=(12, 6))
        barra.pack(side="bottom", fill="x")
        self.btn_atualizar = ttk.Button(barra, text="Atualizar (F5)", command=self.atualizar)
        self.btn_atualizar.pack(side="left")
        ttk.Button(barra, text="Fechar (Esc)", command=self.destroy).pack(side="right")
        self.mensagem = self._rotulo(self, "")
        self.mensagem.pack(side="bottom", fill="x", padx=12)
        self.rolavel = ConteudoRolavel(self)
        self.rolavel.pack(fill="both", expand=True, padx=4, pady=4)
        corpo = self.rolavel.corpo
        corpo.configure(padx=8, pady=8)
        grupo = self._grupo(corpo, "impressora")
        self.btn_verificar = ttk.Button(grupo, text="Verificar impressora (sem imprimir)", command=self.verificar_impressora)
        self.btn_impressora = ttk.Button(grupo, text="Imprimir página de teste…", command=self.testar_impressora)
        self._botoes(grupo, self.btn_verificar, self.btn_impressora)
        grupo = self._grupo(corpo, "gaveta")
        self.btn_gaveta = ttk.Button(grupo, text="Abrir gaveta para teste…", command=self.testar_gaveta)
        self._botoes(grupo, self.btn_gaveta)
        grupo = self._grupo(corpo, "balanca")
        self.btn_balanca = ttk.Button(grupo, text="Ler peso agora…", command=self.ler_balanca)
        self._botoes(grupo, self.btn_balanca)
        grupo = self._grupo(corpo, "leitor")
        self.campo_leitor = ttk.Entry(grupo)
        self.campo_leitor.bind("<Return>", lambda e: (self.conferir_leitura(), "break")[1])
        self.campo_leitor.bind("<KP_Enter>", lambda e: (self.conferir_leitura(), "break")[1])
        self.btn_leitor = ttk.Button(grupo, text="Conferir código", command=self.conferir_leitura)
        self._botoes(grupo, (self.campo_leitor, self.btn_leitor))
        self._acoes = (self.btn_verificar, self.btn_impressora, self.btn_gaveta, self.btn_balanca,
                       self.btn_leitor, self.campo_leitor, self.btn_atualizar)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<F5>", lambda e: self.atualizar())
        self.bind("<Configure>", self._ao_redimensionar, add="+")
        self.rolavel.ligar_rolagem()
        self._dimensionar()
        self.atualizar()
        self.transient(master.winfo_toplevel())
        self.campo_leitor.focus_set()

    def _rotulo(self, pai, conteudo: str) -> ttk.Label:
        rotulo = ttk.Label(pai, text=conteudo, wraplength=LARGURA_MINIMA - 60, justify="left")
        self._rotulos.append(rotulo)
        return rotulo

    def _grupo(self, corpo, chave: str) -> ttk.LabelFrame:
        grupo = ttk.LabelFrame(corpo, text=DISPOSITIVOS[chave], padding=8)
        grupo.pack(fill="x", pady=(0, 8))
        grupo.columnconfigure(0, weight=1)
        self.status[chave] = self._rotulo(grupo, "")
        self.status[chave].grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        return grupo

    @staticmethod
    def _botoes(grupo, *itens) -> None:
        """Um botão por linha (cabe em notebook); uma tupla fica lado a lado (campo do leitor e o botão)."""
        for linha, item in enumerate(itens, start=1):
            if isinstance(item, tuple):
                for coluna, widget in enumerate(item):
                    widget.grid(row=linha, column=coluna, sticky="ew", padx=(0, 6), pady=2)
            else:
                item.grid(row=linha, column=0, columnspan=2, sticky="ew", pady=2)

    def _dimensionar(self) -> None:
        self.minsize(LARGURA_MINIMA, ALTURA_MINIMA)
        largura = max(LARGURA_MINIMA, min(820, self.winfo_screenwidth() - 40))
        altura = max(ALTURA_MINIMA, min(640, self.winfo_screenheight() - 80))
        self.geometry(f"{largura}x{altura}")

    def _ao_redimensionar(self, evento) -> None:
        if evento.widget is not self:
            return
        quebra = max(LARGURA_MINIMA - 60, evento.width - 80)
        for rotulo in self._rotulos:
            rotulo.configure(wraplength=quebra)

    # ------------------------------------------------------------ estado
    def _mostrar(self, resultado) -> None:
        self.resultados[resultado.dispositivo] = resultado
        cor = tema.COR.get(COR_ESTADO.get(resultado.estado, "texto"), tema.COR.get("texto", ""))
        self.status[resultado.dispositivo].configure(text=f"{resultado.rotulo}\n{resultado.mensagem}", foreground=cor)

    def _avisar(self, conteudo: str) -> None:
        self.mensagem.configure(text=conteudo)

    def _liberar(self, ligado: bool) -> None:
        for widget in self._acoes:
            widget.state(["!disabled"] if ligado else ["disabled"])

    def exigir_acesso(self) -> int:
        """Revalida `cfg_maquinas`; sem acesso, desliga os testes e levanta."""
        try:
            operador_id = self.diag.exigir()
        except ErroNegocio as erro:
            self._liberar(False)
            self._avisar(str(erro))
            raise
        self._liberar(True)
        return operador_id

    def atualizar(self) -> bool:
        try:
            self.exigir_acesso()
        except ErroNegocio:
            return False
        for resultado in self.diag.resumo().values():
            self._mostrar(resultado)
        self._avisar("Configuração relida. Nenhum equipamento foi acionado.")
        return True

    def _perguntar(self, titulo: str, pergunta: str) -> bool:
        return tema.confirmar(self, pergunta, titulo, padrao_sim=False)

    # ------------------------------------------------------------ ações
    def verificar_impressora(self):
        try:
            achados = self.diag.verificar_impressora()
        except ErroNegocio as erro:
            self._avisar(str(erro))
            return None
        except Exception as erro:  # noqa: BLE001 - consulta ao Windows falhou: mostrar, não derrubar
            self._avisar(f"Não foi possível consultar o Windows: {erro}")
            return None
        linhas = [f"[{a.nivel.upper()}] {a.texto}" + (f" Solução: {a.solucao}" if a.solucao else "") for a in achados]
        self._avisar("\n".join(linhas) + "\nNada foi impresso.")
        return achados

    def _testar(self, funcao, titulo: str, aviso: str, conferencia: str):
        try:
            operador_id = self.exigir_acesso()
        except ErroNegocio:
            return None
        if not self._perguntar(titulo, aviso):
            self._avisar("Teste cancelado. Nada foi enviado.")
            return None
        try:
            resultado = funcao(operador_id)
        except ErroNegocio as erro:
            self._avisar(str(erro))
            try:
                self.exigir_acesso()
            except ErroNegocio:
                pass
            return None
        self._mostrar(resultado)
        self._avisar(resultado.mensagem)
        if resultado.aguarda_conferencia:
            ok = self._perguntar("Conferir resultado", conferencia)
            try:
                resultado = self.diag.confirmar(resultado, ok, operador_id)
            except ErroNegocio as erro:
                self._avisar(str(erro))
                return resultado
            self._mostrar(resultado)
            self._avisar(resultado.mensagem)
        return resultado

    def testar_impressora(self):
        return self._testar(
            self.diag.testar_impressora, "Confirmar teste físico",
            "Vai imprimir uma página de teste na impressora configurada. Confira papel e conexão. Continuar?",
            "O papel saiu, com acentos legíveis e corte?")

    def testar_gaveta(self):
        return self._testar(
            self.diag.testar_gaveta, "Confirmar teste físico",
            "Vai ABRIR FISICAMENTE a gaveta de dinheiro. Nenhum movimento de caixa será lançado. "
            "Confira se é seguro abrir agora. Continuar?",
            "A gaveta abriu?")

    def ler_balanca(self):
        return self._testar(
            self.diag.ler_balanca, "Confirmar leitura da balança",
            "Vai consultar a balança pela porta configurada. Coloque um peso conhecido no prato. "
            "Nenhum item será lançado. Continuar?",
            "O peso mostrado confere com o visor da balança?")

    def conferir_leitura(self):
        try:
            self.exigir_acesso()
        except ErroNegocio:
            return None
        resultado = self.diag.avaliar_leitura(self.campo_leitor.get())
        self._mostrar(resultado)
        self._avisar(resultado.mensagem)
        self.campo_leitor.selection_range(0, "end")
        self.campo_leitor.focus_set()
        return resultado


def abrir(master, ctx) -> JanelaDiagnostico:
    return JanelaDiagnostico(master, ctx)