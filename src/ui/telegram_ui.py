"""Configurações > Telegram: liga o PDV ao celular do dono em três passos (criar o bot, colar o token, mandar o código)."""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from src.controllers import notificacoes
from src.core.erros import ErroNegocio
from src.ui import tema
from src.ui.tema import COR

FONTE_CODIGO = ("Consolas", 26, "bold")


class JanelaTelegram(tk.Toplevel):
    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx = ctx
        self.tg = ctx.telegram
        self.title("Telegram do dono — acompanhar a casa pelo celular")
        self.configure(bg=COR["fundo"])
        self.geometry(f"780x{min(720, max(600, self.winfo_screenheight() - 80))}")
        self.minsize(720, 600)
        self._tic = None
        self.protocol("WM_DELETE_WINDOW", self.fechar)
        self.bind("<Destroy>", self._ao_destruir, add="+")

        barra = tk.Frame(self, bg=COR["marinho"], padx=6, pady=5)
        barra.pack(fill="x")
        ttk.Button(barra, text="Sair", style="Barra.TButton", command=self.fechar).pack(side="right")

        corpo = ttk.Frame(self, padding=14)
        corpo.pack(fill="both", expand=True)
        topo = ttk.Frame(corpo)
        topo.pack(fill="x")
        ttk.Label(topo, text="Receba no celular o que acontece na casa", style="Titulo.TLabel").pack(side="left")
        self.var_ativo = tk.BooleanVar(value=self.tg.ligado())
        ttk.Checkbutton(topo, text="Telegram ligado", variable=self.var_ativo, command=self._alternar).pack(side="right")
        ttk.Label(corpo, wraplength=720, justify="left", foreground=COR["suave"], padding=(0, 2, 0, 6),
                  text="Caixa, cancelamentos e sangrias chegam sozinhos; os botões do bot mostram vendas, caixa e estoque na hora."
                  ).pack(anchor="w")

        # Rodapé reservado antes dos passos: a lista de celulares é o que encolhe numa janela baixa, nunca o aviso e o status.
        rodape = ttk.Frame(corpo)
        rodape.pack(side="bottom", fill="x")
        self.lbl_status = ttk.Label(rodape, text="", wraplength=700, justify="left")
        self.lbl_status.pack(anchor="w", pady=(8, 0))
        ttk.Label(rodape, wraplength=700, justify="left", foreground=COR["suave"],
                  text="O PDV precisa estar ligado e com internet para responder; sem internet os avisos esperam na fila. As "
                       "mensagens passam pelos servidores do Telegram: pareie só quem pode ver o faturamento. Escolha os avisos em "
                       "Configurações > Configurações > aba Telegram. Um bot por loja, em um único computador.").pack(anchor="w", pady=(6, 0))

        # Passo 1 e 2: o bot
        p1 = ttk.LabelFrame(corpo, text=" 1. Crie o bot (2 minutos, uma vez só) ", padding=10)
        p1.pack(fill="x", pady=4)
        ttk.Label(p1, wraplength=680, justify="left",
                  text="No Telegram, fale com @BotFather: envie /newbot, escolha um nome e um usuário terminado em \"bot\". "
                       "Copie o TOKEN que ele devolver e cole aqui:").pack(anchor="w")
        linha = ttk.Frame(p1)
        linha.pack(fill="x", pady=(6, 0))
        self.var_token = tk.StringVar(value=self.tg.token)
        self.ent_token = ttk.Entry(linha, textvariable=self.var_token, show="•")
        self.ent_token.pack(side="left", fill="x", expand=True)
        self.var_mostrar = tk.BooleanVar(value=False)
        ttk.Checkbutton(linha, text="mostrar", variable=self.var_mostrar,
                        command=lambda: self.ent_token.configure(show="" if self.var_mostrar.get() else "•")).pack(side="left", padx=6)
        self.btn_conectar = ttk.Button(linha, text="Conectar", command=self.conectar)
        self.btn_conectar.pack(side="left")
        ttk.Button(linha, text="Abrir @BotFather", command=lambda: webbrowser.open("https://t.me/BotFather")).pack(side="left", padx=(6, 0))
        self.lbl_bot = ttk.Label(p1, text="", foreground=COR["ok"])
        self.lbl_bot.pack(anchor="w", pady=(4, 0))

        # Passo 3: pareamento
        p2 = ttk.LabelFrame(corpo, text=" 2. Conecte o celular do dono ", padding=10)
        p2.pack(fill="x", pady=4)
        ttk.Label(p2, wraplength=680, justify="left",
                  text="Gere o código e envie a mensagem que aparecer ao bot, pelo celular do dono. Vale 10 minutos; só quem "
                       "digita o código fica autorizado.").pack(anchor="w")
        linha2 = ttk.Frame(p2)
        linha2.pack(fill="x", pady=(6, 0))
        self.btn_codigo = ttk.Button(linha2, text="Gerar código", command=self.gerar_codigo)
        self.btn_codigo.pack(side="left")
        self.btn_abrir_bot = ttk.Button(linha2, text="Abrir meu bot", command=self.abrir_bot)
        self.btn_abrir_bot.pack(side="left", padx=6)
        self.quadro_codigo = ttk.Frame(p2)                 # só aparece com um código gerado (senão sobraria um buraco)
        self.lbl_codigo = ttk.Label(self.quadro_codigo, text="", font=FONTE_CODIGO, foreground=COR["rotulo"])
        self.lbl_codigo.pack(anchor="w", pady=(6, 0))
        self.lbl_instrucao = ttk.Label(self.quadro_codigo, text="", wraplength=680, justify="left")
        self.lbl_instrucao.pack(anchor="w")

        # Celulares conectados
        p3 = ttk.LabelFrame(corpo, text=" 3. Celulares conectados ", padding=10)
        p3.pack(fill="both", expand=True, pady=4)
        from src.ui.tema import Grade
        botoes = ttk.Frame(p3)
        botoes.pack(fill="x", pady=(0, 6))
        ttk.Button(botoes, text="Enviar mensagem de teste", command=self.testar).pack(side="left")
        ttk.Button(botoes, text="Remover selecionado", command=self.remover).pack(side="left", padx=6)
        self.grade = Grade(p3, [("nome", "Quem", 300, "w"), ("desde", "Conectado em", 180, "w")], altura=3)
        self.grade.pack(fill="both", expand=True)
        self._atualizar()

    # ----------------------------------------------------------- ações
    def conectar(self) -> None:
        ok, bot = tema.tratar(self, self.tg.salvar_token, self.var_token.get())
        if ok:
            notificacoes.ACORDAR.set()
            self._atualizar()

    def gerar_codigo(self) -> None:
        ok, _ = tema.tratar(self, self.tg.gerar_codigo)
        if ok:
            self._atualizar()

    def abrir_bot(self) -> None:
        if self.tg.bot_usuario():
            webbrowser.open(f"https://t.me/{self.tg.bot_usuario()}")

    def testar(self) -> None:
        ok, n = tema.tratar(self, self.tg.testar)
        if ok:
            tema.mensagem(self, f"Mensagem de teste enviada para {n} celular(es).\nConfira no Telegram.", "Telegram")

    def remover(self) -> None:
        sel = self.grade.selecionado()
        if sel and tema.confirmar(self, "Remover este celular? Ele deixa de receber os avisos e de consultar o bot.", "Telegram"):
            self.tg.remover_chat(int(sel))
            self._atualizar()

    def _alternar(self) -> None:
        ligar = self.var_ativo.get()
        if ligar and not (self.tg.token and self.tg.chats()):
            self.var_ativo.set(False)
            tema.aviso(self, "Primeiro cole o token e conecte o celular do dono (passos 1 e 2).", "Telegram")
            return
        self.ctx.banco.cfg_set("telegram_ativo", "S" if ligar else "N")
        self._atualizar()

    # --------------------------------------------------------- estado
    def _atualizar(self) -> None:
        """Redesenha o estado a partir do banco; roda a cada 2 s (é assim que o 'celular conectado' aparece sozinho)."""
        try:
            if not self.winfo_exists():
                return
            if self._tic:                                   # chamada manual (depois de um botão): não empilha temporizadores
                self.after_cancel(self._tic)
            tg = self.tg
            usuario = tg.bot_usuario()
            self.lbl_bot.configure(text=f"✔ Bot reconhecido: @{usuario}" if tg.token and usuario else "")
            self.btn_codigo.state(["!disabled"] if tg.token else ["disabled"])
            self.btn_abrir_bot.state(["!disabled"] if usuario else ["disabled"])
            codigo = tg.codigo_pendente()
            if codigo:
                self.lbl_codigo.configure(text=f"/start {codigo}")
                self.lbl_instrucao.configure(text=f"No celular, abra a conversa com @{usuario} e envie exatamente a mensagem acima.")
                self.quadro_codigo.pack(anchor="w", fill="x")
            else:
                self.lbl_codigo.configure(text="")
                self.lbl_instrucao.configure(text="")
                self.quadro_codigo.pack_forget()
            selecionado = self.grade.selecionado()
            chats = tg.chats()
            self.grade.preencher([(c["nome"] or f"(chat {c['chat_id']})", c["criado_em"][:16]) for c in chats],
                                 ids=[c["chat_id"] for c in chats])
            self.grade.selecionar(selecionado)
            self.var_ativo.set(tg.ligado())
            erro = tg.ultimo_erro()
            if erro:
                self.lbl_status.configure(text=f"⚠ {erro}", foreground=COR["perigo"])
            elif tg.ligado() and chats:
                self.lbl_status.configure(text=f"● Funcionando: {len(chats)} celular(es) recebendo os avisos.", foreground=COR["ok"])
            elif chats:
                self.lbl_status.configure(text="● Desligado: marque \"Telegram ligado\" para voltar a avisar.", foreground=COR["aviso"])
            else:
                self.lbl_status.configure(text="Ainda não há celular conectado.", foreground=COR["suave"])
            self._tic = self.after(2000, self._atualizar)
        except tk.TclError:
            pass

    def _ao_destruir(self, e) -> None:
        if e.widget is self and self._tic:
            try:
                self.after_cancel(self._tic)
            except tk.TclError:
                pass
            self._tic = None

    def fechar(self) -> None:
        self.destroy()


def abrir(master, ctx) -> JanelaTelegram:
    return JanelaTelegram(master, ctx)
