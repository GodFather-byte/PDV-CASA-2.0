"""Tela de entrada: usuário e senha (manual ADM seção 1)."""
from __future__ import annotations

import tkinter as tk
import logging
import threading
from queue import Empty, Queue
from tkinter import ttk

from src.controllers.turno_controller import TurnoController
from src.core import formatacao as fmt
from src.core import licenca
from src.core.erros import ErroNegocio
from src.ui import tema
from src.ui.menu_widgets import PAL, FONTE, misturar
from src.versao import VERSAO


class JanelaLogin(tk.Toplevel):
    """Devolve o Operador em `self.operador` (None se o usuário fechar a janela)."""

    def __init__(self, master, ctx, titulo_loja: str = "PDV"):
        super().__init__(master)
        self.ctx, self.operador = ctx, None
        self._entrando = False
        self._fechada = False
        self._consulta_licenca = None
        self._consulta_after = None
        self.title("WillPDV • Entrada no sistema")
        self.configure(bg=PAL["fundo"])
        self.resizable(False, False)
        self._aplicar_estilos()
        layout = tk.Frame(self, bg=PAL["fundo"])
        layout.pack(fill="both", expand=True)
        layout.columnconfigure(0, minsize=300)
        layout.columnconfigure(1, minsize=460, weight=1)

        marca = tk.Frame(layout, bg=PAL["lateral"], padx=28, pady=30)
        marca.grid(row=0, column=0, sticky="nsew")
        tk.Label(marca, text="W", font=(FONTE, 22, "bold"), bg=PAL["verde"], fg=PAL["fundo"], width=3
                 ).pack(anchor="w")
        tk.Label(marca, text="WILLPDV", font=(FONTE, 11, "bold"), bg=PAL["lateral"], fg=PAL["verde"]
                 ).pack(anchor="w", pady=(18, 0))
        tk.Label(marca, text="Seu atendimento\ncomeça aqui.", font=(FONTE, 24, "bold"), bg=PAL["lateral"],
                 fg=PAL["texto"], justify="left").pack(anchor="w", pady=(14, 12))
        tk.Frame(marca, height=2, width=44, bg=PAL["verde"]).pack(anchor="w", pady=(8, 20))
        tk.Label(marca, text=titulo_loja, font=(FONTE, 15, "bold"), bg=PAL["lateral"], fg=PAL["texto"],
                 wraplength=240, justify="left").pack(anchor="w")
        tk.Label(marca, text="Vendas, caixa e gestão\nem um só lugar.", font=(FONTE, 11), bg=PAL["lateral"],
                 fg=PAL["suave"], justify="left").pack(anchor="w", pady=(10, 0))
        tk.Label(marca, text=f"Ponto de venda  /  Versão {VERSAO}", font=(FONTE, 9), bg=PAL["lateral"],
                 fg=PAL["mudo"]).pack(side="bottom", anchor="w")

        quadro = tk.Frame(layout, bg=PAL["fundo"], padx=36, pady=28)
        quadro.grid(row=0, column=1, sticky="nsew")
        tk.Label(quadro, text="Bem-vindo de volta", bg=PAL["fundo"], fg=PAL["texto"], font=(FONTE, 21, "bold")
                 ).pack(anchor="w")
        tk.Label(quadro, text="Entre com seu usuário para acessar o PDV.", bg=PAL["fundo"], fg=PAL["suave"],
                 font=(FONTE, 10)).pack(anchor="w", pady=(8, 24))
        tk.Label(quadro, text="Usuário", bg=PAL["fundo"], fg=PAL["texto"], font=(FONTE, 10, "bold")
                 ).pack(anchor="w")
        self.var_usuario = tk.StringVar(self)
        nomes = ctx.acesso.nomes_login()
        self.ent_usuario = ttk.Combobox(quadro, textvariable=self.var_usuario, values=nomes, width=28,
                                        font=(FONTE, 12), style="Login.TCombobox")
        self.ent_usuario.pack(fill="x", pady=(8, 6))
        if len(nomes) == 1:
            self.var_usuario.set(nomes[0])
        tk.Label(quadro, text="Selecione seu nome ou digite seu usuário.", bg=PAL["fundo"], fg=PAL["mudo"],
                 font=(FONTE, 9)).pack(anchor="w", pady=(0, 18))
        tk.Label(quadro, text="Senha", bg=PAL["fundo"], fg=PAL["texto"], font=(FONTE, 10, "bold")
                 ).pack(anchor="w")
        self.var_senha = tk.StringVar(self)
        self.ent_senha = ttk.Entry(quadro, textvariable=self.var_senha, show="*", width=28, font=(FONTE, 12),
                                   style="Login.TEntry")
        self.ent_senha.pack(fill="x", pady=(8, 8))
        self.var_mostrar_senha = tk.BooleanVar(self, value=False)
        self.chk_mostrar_senha = ttk.Checkbutton(quadro, text="Mostrar senha", variable=self.var_mostrar_senha,
                                                command=self._mostrar_senha, style="Login.TCheckbutton")
        self.chk_mostrar_senha.pack(anchor="w")
        self.lbl_msg = tk.Label(quadro, text="", bg=PAL["fundo"], fg=PAL["vermelho"], font=(FONTE, 10, "bold"),
                                wraplength=360, justify="left", anchor="w")
        self.lbl_msg.pack(fill="x", pady=(14, 12))
        self.btn_entrar = ttk.Button(quadro, text="Entrar no PDV", command=self.entrar, style="Login.TButton")
        self.btn_entrar.pack(fill="x")
        if licenca.exigida(ctx.banco):
            ttk.Button(quadro, text="Código de licença...", command=self.pedir_licenca, style="Login.Secundario.TButton"
                       ).pack(fill="x", pady=(10, 0))
        tk.Label(quadro, text="Enter: continuar  |  Esc: sair", bg=PAL["fundo"], fg=PAL["mudo"], font=(FONTE, 9)
                 ).pack(pady=(18, 0))
        self.ent_usuario.bind("<<ComboboxSelected>>", lambda e: self.ent_senha.focus_set())
        self.ent_usuario.bind("<Return>", lambda e: (self.ent_senha.focus_set(), "break")[1])
        self.ent_senha.bind("<Return>", lambda e: (self.entrar(), "break")[1])
        self.btn_entrar.bind("<Return>", lambda e: (self.entrar(), "break")[1])
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())
        tema.centralizar(self)
        self.lift()
        tema.modalizar(self)
        (self.ent_senha if self.var_usuario.get() else self.ent_usuario).focus_set()

    def _aplicar_estilos(self) -> None:
        """Estilos exclusivos do login, sem alterar os demais formulários."""
        estilo = ttk.Style(self)
        for nome in ("Login.TEntry", "Login.TCombobox"):
            estilo.configure(nome, padding=10, fieldbackground=PAL["cartao"], foreground=PAL["texto"],
                             insertcolor=PAL["texto"], bordercolor=PAL["borda"], lightcolor=PAL["borda"],
                             darkcolor=PAL["borda"], arrowcolor=PAL["texto"], background=PAL["cartao"])
            estilo.map(nome, bordercolor=[("focus", PAL["verde"])], fieldbackground=[("readonly", PAL["cartao"])])
        estilo.configure("Login.TCheckbutton", font=(FONTE, 10), background=PAL["fundo"], foreground=PAL["suave"])
        estilo.map("Login.TCheckbutton", background=[("active", PAL["fundo"])], foreground=[("active", PAL["texto"])])
        estilo.configure("Login.TButton", font=(FONTE, 12, "bold"), padding=(12, 12), background=PAL["verde"],
                         foreground=PAL["fundo"], borderwidth=0)
        estilo.map("Login.TButton", background=[("active", misturar(PAL["verde"], PAL["brilho"], 0.25)),
                                               ("pressed", misturar(PAL["verde"], PAL["fundo"], 0.2))],
                   foreground=[("active", PAL["fundo"])])
        estilo.configure("Login.Secundario.TButton", font=(FONTE, 10), padding=(12, 8), background=PAL["cartao"],
                         foreground=PAL["suave"], borderwidth=0)
        estilo.map("Login.Secundario.TButton", background=[("active", PAL["cartao_hover"])])

    def _mostrar_senha(self) -> None:
        """Alterna somente a visualização; a senha permanece no mesmo campo."""
        self.ent_senha.configure(show="" if self.var_mostrar_senha.get() else "*")

    def entrar(self) -> None:
        if self._fechada or self._entrando:
            return
        self._entrando = True
        self.btn_entrar.configure(state="disabled")
        self._executar_entrada(consultar_nuvem=True)

    def _executar_entrada(self, consultar_nuvem: bool) -> None:
        try:
            self._continuar_entrada(consultar_nuvem)
        finally:
            if self._consulta_licenca is None and not self._fechada:
                self._entrando = False
                self.btn_entrar.configure(state="normal")

    def _continuar_entrada(self, consultar_nuvem: bool) -> None:
        estado = licenca.estado(self.ctx.banco)
        turno = TurnoController(self.ctx.banco).atual()
        if estado.bloqueia and consultar_nuvem and self._renovar_pela_nuvem():
            return
        if estado.bloqueia and not licenca.turno_vale_como_isencao(self.ctx.banco, turno):
            # Com um turno recente aberto a loja continua operando (só avisa); sem ele, exige a renovação.
            self.ctx.banco.log("licenca_bloqueio", estado.mensagem)
            self.lbl_msg.configure(text=estado.mensagem)
            if not self.pedir_licenca(estado.mensagem):
                return
            estado = licenca.estado(self.ctx.banco)
        senha = self.var_senha.get()
        try:
            operador = self.ctx.acesso.autenticar(self.var_usuario.get(), senha)
        except ErroNegocio as e:
            self.lbl_msg.configure(text=str(e), fg=PAL["vermelho"])
            self.var_senha.set("")
            self.ent_senha.focus_set()
            return
        if self.ctx.acesso.precisa_trocar_senha(operador, senha) and not self.trocar_senha(operador):
            self.lbl_msg.configure(text="Troque a senha para entrar no sistema.", fg=PAL["vermelho"])
            self.var_senha.set("")
            self.ent_senha.focus_set()
            return
        self.operador = operador
        if licenca.exigida(self.ctx.banco):
            licenca.registrar_uso(self.ctx.banco)
        if estado.bloqueia:
            tema.mensagem(self, f"{estado.mensagem}\nO turno aberto pode ser trabalhado e fechado normalmente; "
                                "a próxima entrada exigirá o código de renovação.", "Licença", "aviso")
        elif estado.avisa:
            tema.mensagem(self, estado.mensagem, "Licença", "aviso")
        self.destroy()

    def trocar_senha(self, operador) -> bool:
        """Senha igual ao nome (a de fábrica é ADM/ADM): pede uma nova, duas vezes. Devolve False se o usuário desistir."""
        nova = tema.pedir_texto(
            self, "Troque a senha", f"A senha de {operador.nome} é igual ao nome e qualquer um pode adivinhá-la.\n"
            "Digite uma senha nova (até 10 letras ou números):", senha=True, largura=22,
            validar=lambda v: self.ctx.acesso.validar_nova_senha(operador, v))
        if nova is None:
            return False

        def conferir(v: str) -> str:
            if v.upper() != nova.upper():
                raise ErroNegocio("As senhas não conferem.")
            return v
        if tema.pedir_texto(self, "Troque a senha", "Digite a senha nova de novo:", senha=True, largura=22,
                            validar=conferir) is None:
            return False
        self.ctx.acesso.trocar_senha(operador, nova)
        tema.mensagem(self, "Senha trocada. Use a senha nova nas próximas entradas.", "Senha")
        return True

    def _renovar_pela_nuvem(self) -> bool:
        """Inicia só a rede fora da thread Tk; True indica que a entrada será retomada."""
        from src.sync import licenca_nuvem
        url, token = self.ctx.banco.cfg("api_url"), self.ctx.banco.cfg("api_token")
        if not url.strip() or not token.strip() or not licenca_nuvem.iniciar_consulta(self.ctx.banco, forcar=True):
            return False
        self.lbl_msg.configure(text="Verificando a licença na nuvem...", fg=PAL["texto"])
        fila = self._consulta_licenca = Queue()

        def rede():
            try:
                resultado = licenca_nuvem.consultar_resultado(url, token, timeout=(3, 5))
                fila.put((resultado, None))
            except Exception as e:
                logging.getLogger("pdv.licenca").exception("Falha na consulta de licença do login.")
                fila.put((licenca_nuvem.ResultadoConsulta(False, erro=str(e)), e))

        try:
            threading.Thread(target=rede, name="consulta-licenca-login", daemon=True).start()
            self._consulta_after = self.after(100, self._receber_licenca)
        except Exception:
            self._consulta_licenca = None
            raise
        return True

    def _receber_licenca(self) -> None:
        from src.sync import licenca_nuvem
        self._consulta_after = None
        if self._fechada or self._consulta_licenca is None:
            return
        try:
            resultado, erro = self._consulta_licenca.get_nowait()
        except Empty:
            self._consulta_after = self.after(100, self._receber_licenca)
            return
        self._consulta_licenca = None
        try:
            licenca_nuvem.registrar_resultado(self.ctx.banco, resultado)
            licenca_nuvem.aplicar(self.ctx.banco, resultado.codigo)
        except Exception as e:
            logging.getLogger("pdv.licenca").exception("Falha ao aplicar licença no login.")
            self.lbl_msg.configure(text=f"Não foi possível atualizar a licença: {e}", fg=PAL["vermelho"])
            self._entrando = False
            self.btn_entrar.configure(state="normal")
            return
        self.lbl_msg.configure(text=f"Consulta de licença falhou: {erro}" if erro else "")
        self._executar_entrada(consultar_nuvem=False)

    def destroy(self) -> None:
        self._fechada = True
        self._consulta_licenca = None
        if self._consulta_after is not None:
            try:
                self.after_cancel(self._consulta_after)
            except tk.TclError:
                pass
            self._consulta_after = None
        super().destroy()

    def pedir_licenca(self, motivo: str = "") -> bool:
        """Pede o código de licença e o ativa. Devolve True se a licença ficou liberada para entrar."""
        if self._fechada or self._consulta_licenca is not None:
            return False
        texto = (f"{motivo}\n\n" if motivo else "") + "Cole o código de licença fornecido:"
        codigo = tema.pedir_texto(self, "Código de licença", texto, largura=64)
        if not codigo:
            return False
        try:
            lic = licenca.ativar(self.ctx.banco, codigo)
        except ErroNegocio as e:
            self.lbl_msg.configure(text=str(e), fg=PAL["vermelho"])
            return False
        self.lbl_msg.configure(text=f"Licença ativada até {fmt.fmt_data(lic['expira_em'].isoformat())}.", fg=PAL["verde"])
        return not licenca.estado(self.ctx.banco).bloqueia
