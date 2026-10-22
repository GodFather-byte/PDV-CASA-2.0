"""Tela do WillPDV Licenças: emitir (mensal, permanente, teste), acompanhar as lojas, conferir códigos e cuidar da chave."""
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, ttk

from licenciador import nucleo
from licenciador.nucleo import Configuracao, ErroLicenciador, Historico
from src.core import backup_seguro
from src.core import formatacao as fmt
from licenciador import icone, tema
from licenciador.tema import COR, Grade

BR = "%d/%m/%Y"


def _br(iso: str) -> str:
    return date.fromisoformat(iso).strftime(BR)


class Janela(tk.Tk):
    def __init__(self, arquivo_chave: Path | None = None, historico: Historico | None = None,
                 configuracao: Configuracao | None = None):
        super().__init__()
        self.arquivo_chave = arquivo_chave
        self.historico = historico or Historico()
        self.config = configuracao or Configuracao(self.historico.arquivo.with_name("config.json"))
        self.emitida: nucleo.Emitida | None = None
        self.title(f"WillPDV Licenças {nucleo.VERSAO}")
        self.geometry("860x640")
        self.minsize(780, 580)
        tema.aplicar_tema(self)
        icone.aplicar(self, "willlicencas.ico")

        barra = tk.Frame(self, bg=COR["marinho"], padx=14, pady=10)
        barra.pack(fill="x")
        tk.Label(barra, text="WillPDV Licenças", bg=COR["marinho"], fg="white", font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(barra, text="emissão de licenças mensais e permanentes", bg=COR["marinho"], fg="#9fb3e8").pack(side="left", padx=12)

        self.aviso_chave = tk.Label(self, text="", anchor="w", justify="left", wraplength=800, padx=14, pady=6)
        self.aviso_chave.pack(fill="x")
        self.aviso_venc = tk.Label(self, text="", anchor="w", justify="left", wraplength=800, padx=14, pady=6, cursor="hand2")
        self.aviso_venc.bind("<Button-1>", lambda _e: self.abas.select(self.aba_lojas))
        self.abas = ttk.Notebook(self)
        self.abas.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._aba_emitir()
        self._aba_lojas()
        self._aba_conferir()
        self._aba_chave()
        self._aba_backup()
        ttk.Button(barra, text="Central Telegram", command=self.abrir_central).pack(side="right")
        self.janela_central = None
        self.atualizar_chave()
        self.atualizar_lojas()
        self.atualizar_backup()
        self.atualizar_validade()

    def abrir_central(self):
        from licenciador.central_tela import JanelaCentral
        if self.janela_central is None or not self.janela_central.winfo_exists():
            self.janela_central = JanelaCentral(self)
        self.janela_central.lift()

    # --------------------------------------------------------------- emitir
    def _aba_emitir(self) -> None:
        f = ttk.Frame(self.abas, padding=16)
        self.abas.add(f, text="  Emitir licença  ")
        ttk.Label(f, text="Loja (a mesma chave de loja do PDV)", style="Rotulo.TLabel").grid(row=0, column=0, sticky="w")
        self.var_loja = tk.StringVar()
        self.ent_loja = ttk.Combobox(f, textvariable=self.var_loja, values=self.historico.lojas(), width=42)
        self.ent_loja.grid(row=1, column=0, columnspan=3, sticky="we", pady=(2, 12))

        ttk.Label(f, text="Tipo de licença", style="Rotulo.TLabel").grid(row=2, column=0, sticky="w")
        self.var_tipo = tk.StringVar(value="mensal")
        quadro = ttk.Frame(f)
        quadro.grid(row=3, column=0, columnspan=3, sticky="w", pady=(2, 8))
        for valor in nucleo.TIPOS:
            ttk.Radiobutton(quadro, text=nucleo.ROTULO[valor], value=valor, variable=self.var_tipo,
                            command=self.atualizar_validade).pack(side="left", padx=(0, 18))

        self.lbl_qtd = ttk.Label(f, text="Quantos meses", style="Rotulo.TLabel")
        self.lbl_qtd.grid(row=4, column=0, sticky="w")
        self.var_qtd = tk.StringVar(value="1")
        self.spin = ttk.Spinbox(f, from_=1, to=nucleo.MAX_MESES, textvariable=self.var_qtd, width=6, command=self.atualizar_validade)
        self.spin.grid(row=5, column=0, sticky="w", pady=(2, 4))
        self.var_qtd.trace_add("write", lambda *_: self.atualizar_validade())
        self.lbl_validade = ttk.Label(f, text="", font=tema.FONTE_B, foreground=COR["marinho2"])
        self.lbl_validade.grid(row=5, column=1, sticky="w", padx=14)

        self.btn_gerar = ttk.Button(f, text="Gerar licença", style="Ok.TButton", command=self.gerar)
        self.btn_gerar.grid(row=6, column=0, sticky="w", pady=(14, 8))

        ttk.Label(f, text="Código para mandar ao cliente", style="Rotulo.TLabel").grid(row=7, column=0, sticky="w", pady=(8, 0))
        self.txt_codigo = tk.Text(f, height=6, wrap="char", font=tema.FONTE_MONO, bg="white", relief="solid", bd=1)
        self.txt_codigo.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(2, 6))
        self.txt_codigo.configure(state="disabled")
        botoes = ttk.Frame(f)
        botoes.grid(row=9, column=0, columnspan=3, sticky="w")
        self.btn_copiar = ttk.Button(botoes, text="Copiar código", command=lambda: self.copiar(lambda e: e.codigo, "Código copiado."))
        self.btn_copiar.pack(side="left")
        self.btn_msg = ttk.Button(botoes, text="Copiar mensagem pronta para o cliente",
                                  command=lambda: self.copiar(nucleo.mensagem_para_o_cliente, "Mensagem copiada."))
        self.btn_msg.pack(side="left", padx=8)
        self.btn_salvar = ttk.Button(botoes, text="Salvar em arquivo...", command=self.salvar_arquivo)
        self.btn_salvar.pack(side="left")
        self.lbl_status = ttk.Label(f, text="", foreground=COR["ok"])
        self.lbl_status.grid(row=10, column=0, columnspan=3, sticky="w", pady=(8, 0))
        f.columnconfigure(2, weight=1)
        f.rowconfigure(8, weight=1)
        self._botoes_codigo(False)

    def _botoes_codigo(self, ligado: bool) -> None:
        for b in (self.btn_copiar, self.btn_msg, self.btn_salvar):
            b.state(["!disabled"] if ligado else ["disabled"])

    def quantidade(self) -> int:
        try:
            return int(self.var_qtd.get())
        except ValueError:
            return 0

    def atualizar_validade(self) -> None:
        tipo = self.var_tipo.get()
        self.lbl_qtd.configure(text="Quantos meses" if tipo == "mensal" else "Quantos dias" if tipo == "teste" else "Sem vencimento")
        self.spin.configure(to=nucleo.MAX_MESES if tipo == "mensal" else nucleo.MAX_DIAS_TESTE)
        self.spin.state(["disabled"] if tipo == "permanente" else ["!disabled"])
        try:
            expira = nucleo.validade(tipo, self.quantidade())
            self.lbl_validade.configure(text="Sem vencimento (100 anos)" if tipo == "permanente"
                                        else f"Válida até {expira.strftime(BR)}", foreground=COR["marinho2"])
        except ErroLicenciador as e:
            self.lbl_validade.configure(text=str(e), foreground=COR["perigo"])

    def gerar(self) -> None:
        ok, e = tema.tratar(self, self._emitir)
        if not ok:
            return
        self.emitida = e
        self.txt_codigo.configure(state="normal")
        self.txt_codigo.delete("1.0", "end")
        self.txt_codigo.insert("1.0", e.codigo)
        self.txt_codigo.configure(state="disabled")
        self._botoes_codigo(True)
        vence = "sem vencimento" if e.tipo == "permanente" else f"válida até {e.expira_em.strftime(BR)}"
        self.lbl_status.configure(text=f"Licença {e.descricao.lower()} de {e.loja}, {vence}. Guardada no histórico.")
        self.ent_loja.configure(values=self.historico.lojas())
        self.atualizar_lojas()
        self._backup_automatico()

    def _emitir(self) -> nucleo.Emitida:
        e = nucleo.emitir(self.var_loja.get(), self.var_tipo.get(), self.quantidade(), self.arquivo_chave)
        self.historico.adicionar(e)
        return e

    def copiar(self, montar, aviso: str) -> None:
        if self.emitida is None:
            return
        self.clipboard_clear()
        self.clipboard_append(montar(self.emitida))
        self.lbl_status.configure(text=aviso)

    def salvar_arquivo(self) -> None:
        if self.emitida is None:
            return
        nome = f"licenca-{self.emitida.loja}-{self.emitida.expira_em.isoformat()}.txt".replace(" ", "_")
        destino = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", initialfile=nome,
                                               filetypes=[("Texto", "*.txt")])
        if destino:
            Path(destino).write_text(nucleo.mensagem_para_o_cliente(self.emitida) + "\n", encoding="utf-8")
            self.lbl_status.configure(text=f"Salvo em {destino}")

    # ---------------------------------------------------------------- lojas
    def _aba_lojas(self) -> None:
        f = ttk.Frame(self.abas, padding=16)
        self.aba_lojas = f
        self.abas.add(f, text="  Lojas e vencimentos  ")
        ttk.Label(f, text="Cada loja aparece uma vez, com a licença mais nova. Quem vence primeiro fica no alto.",
                  foreground=COR["suave"]).pack(anchor="w")
        self.grade = Grade(f, [("loja", "Loja", 230, "w"), ("tipo", "Tipo", 130, "w"), ("emitida", "Emitida em", 100, "center"),
                               ("vence", "Vence em", 100, "center"), ("situacao", "Situação", 150, "w")], altura=12)
        self.grade.pack(fill="both", expand=True, pady=8)
        self.grade.tag("vencida", foreground=COR["perigo"])
        self.grade.tag("vence", foreground="#b07700")
        botoes = ttk.Frame(f)
        botoes.pack(anchor="w")
        ttk.Button(botoes, text="Renovar a selecionada", command=self.renovar).pack(side="left")
        ttk.Button(botoes, text="Copiar o código dela", command=self.copiar_da_lista).pack(side="left", padx=8)
        ttk.Button(botoes, text="Remover do histórico", command=self.remover).pack(side="left")

    def atualizar_lojas(self) -> None:
        self._linhas = {d["codigo"]: d for d in self.historico.situacao_das_lojas()}
        self.grade.limpar()
        for codigo, d in self._linhas.items():
            tag = ("vencida",) if d["situacao"] == "Vencida" else ("vence",) if d["situacao"].startswith("Vence") else ()
            self.grade.adicionar([d["loja"], nucleo.ROTULO.get(d["tipo"], d["tipo"]), _br(d["emitida_em"]),
                                  "—" if d["permanente"] else _br(d["expira_em"]), d["situacao"]], iid=codigo, tags=tag)
        self.atualizar_aviso_vencimentos()

    def atualizar_aviso_vencimentos(self) -> None:
        resumo = nucleo.resumo_vencimentos(self.historico)
        texto = nucleo.texto_do_aviso(resumo)
        if not texto:
            self.aviso_venc.pack_forget()
            return
        vencida = bool(resumo["vencidas"])
        self.aviso_venc.configure(text=texto, bg="#fde2e2" if vencida else "#fff1d6", fg="#8a1c1c" if vencida else "#7a4b00")
        self.aviso_venc.pack(fill="x", before=self.abas)

    def _selecionada(self) -> dict | None:
        iid = self.grade.selecionado()
        return self._linhas.get(iid) if iid else None

    def renovar(self) -> None:
        d = self._selecionada()
        if d is None:
            tema.aviso(self, "Escolha uma loja na lista.", "Renovar")
            return
        self.var_loja.set(d["loja"])
        self.var_tipo.set(d["tipo"])
        self.var_qtd.set(str(d["quantidade"] or 1))
        self.atualizar_validade()
        self.abas.select(0)

    def copiar_da_lista(self) -> None:
        d = self._selecionada()
        if d is None:
            tema.aviso(self, "Escolha uma loja na lista.", "Copiar")
            return
        self.clipboard_clear()
        self.clipboard_append(d["codigo"])
        tema.mensagem(self, "Código copiado.", "Copiar")

    def remover(self) -> None:
        d = self._selecionada()
        if d is not None and tema.confirmar(self, f"Tirar {d['loja']} do histórico?\nIsso não cancela a licença já entregue.", "Remover"):
            self.historico.remover(d["codigo"])
            self.atualizar_lojas()
            self._backup_automatico()

    # -------------------------------------------------------------- conferir
    def _aba_conferir(self) -> None:
        f = ttk.Frame(self.abas, padding=16)
        self.abas.add(f, text="  Conferir um código  ")
        ttk.Label(f, text="Cole um código (PDVL1....) para ver de quem é e até quando vale", style="Rotulo.TLabel").pack(anchor="w")
        self.txt_conferir = tk.Text(f, height=6, wrap="char", font=tema.FONTE_MONO, bg="white", relief="solid", bd=1)
        self.txt_conferir.pack(fill="x", pady=(2, 8))
        ttk.Button(f, text="Conferir", command=self.conferir).pack(anchor="w")
        self.lbl_conferido = ttk.Label(f, text="", justify="left", wraplength=760, font=tema.FONTE_B)
        self.lbl_conferido.pack(anchor="w", pady=12)

    def conferir(self) -> None:
        try:
            r = nucleo.conferir(self.txt_conferir.get("1.0", "end"))
        except ErroLicenciador as e:
            self.lbl_conferido.configure(text=str(e), foreground=COR["perigo"])
            return
        cor = COR["perigo"] if r["situacao"] == "Vencida" else COR["ok"]
        validade = "sem vencimento" if r["permanente"] else f"vence em {r['expira_em'].strftime(BR)}"
        self.lbl_conferido.configure(
            text=f"Assinatura conferida.\nLoja: {r['loja']}\nEmitida em {r['emitida_em'].strftime(BR)}, {validade}\n{r['situacao']}", foreground=cor)

    # ----------------------------------------------------------------- chave
    def _aba_chave(self) -> None:
        f = ttk.Frame(self.abas, padding=16)
        self.abas.add(f, text="  Chave de segurança  ")
        ttk.Label(f, wraplength=780, justify="left",
                  text="A chave de segurança é o que prova que a licença é sua. Ela fica só neste computador, nunca no GitHub nem no PC do "
                       "cliente. Se você perder a chave, não emite mais licenças: guarde uma cópia (pendrive).").pack(anchor="w")
        self.lbl_arquivo = ttk.Label(f, text="", foreground=COR["suave"])
        self.lbl_arquivo.pack(anchor="w", pady=(10, 2))
        self.lbl_estado_chave = ttk.Label(f, text="", font=tema.FONTE_B, wraplength=780, justify="left")
        self.lbl_estado_chave.pack(anchor="w", pady=2)
        ttk.Label(f, text="Chave pública (a que vai dentro do PDV)", style="Rotulo.TLabel").pack(anchor="w", pady=(10, 0))
        self.var_publica = tk.StringVar()
        ttk.Entry(f, textvariable=self.var_publica, state="readonly", font=tema.FONTE_MONO).pack(fill="x", pady=2)
        botoes = ttk.Frame(f)
        botoes.pack(anchor="w", pady=14)
        ttk.Button(botoes, text="Importar chave...", command=self.importar_chave).pack(side="left")
        ttk.Button(botoes, text="Fazer cópia de segurança...", command=self.backup_chave).pack(side="left", padx=8)
        self.btn_criar = ttk.Button(botoes, text="Criar chave nova", command=self.criar_chave)
        self.btn_criar.pack(side="left")
        ttk.Button(botoes, text="Abrir a pasta da chave", command=self.abrir_pasta).pack(side="left", padx=8)

    def _arquivo(self) -> Path:
        return self.arquivo_chave or nucleo.arquivo_chave()

    def atualizar_chave(self) -> None:
        e = nucleo.estado_chave(self.arquivo_chave)
        self.lbl_arquivo.configure(text=f"Arquivo: {self._arquivo()}")
        self.lbl_estado_chave.configure(text=e.mensagem, foreground=COR["ok"] if e.pronta else COR["perigo"])
        self.var_publica.set(e.publica_hex)
        self.btn_criar.state(["disabled"] if e.existe else ["!disabled"])
        if e.pronta:
            self.aviso_chave.configure(text="", bg=COR["fundo"])
            self.aviso_chave.pack_forget()
        else:
            self.aviso_chave.configure(text="⚠ " + e.mensagem, bg="#fff1d6", fg="#7a4b00")
            self.aviso_chave.pack(fill="x", before=self.abas)
        self.btn_gerar.state(["!disabled"] if e.pronta else ["disabled"])

    def importar_chave(self) -> None:
        origem = filedialog.askopenfilename(parent=self, title="Escolha o arquivo da chave privada (licenca_privada.key)")
        if not origem:
            return
        substituir = False
        if self._arquivo().exists():
            if not tema.confirmar(self, "Já existe uma chave neste computador. Substituir pela escolhida?\n"
                                        "A atual fica guardada como .bak.", "Importar chave", padrao_sim=False):
                return
            substituir = True
        ok, _ = tema.tratar(self, nucleo.importar_chave, Path(origem), self._arquivo(), substituir)
        self.atualizar_chave()
        if ok:
            tema.mensagem(self, "Chave importada.", "Chave de segurança")

    def backup_chave(self) -> None:
        destino = filedialog.askdirectory(parent=self, title="Em que pasta (ou pendrive) guardar a cópia da chave?")
        if not destino:
            return
        ok, caminho = tema.tratar(self, nucleo.backup_chave, Path(destino), self._arquivo())
        if ok:
            tema.mensagem(self, f"Cópia guardada em:\n{caminho}\n\nGuarde em lugar seguro: quem tem este arquivo emite licenças.", "Cópia da chave")

    def criar_chave(self) -> None:
        if not tema.confirmar(self, "Criar uma chave NOVA?\n\nSó faça isso na primeira vez. Uma chave nova só vale se a chave pública dela for "
                                    "colocada no PDV (src/core/licenca.py) e o PDV for gerado de novo: os caixas que já existem passam a "
                                    "recusar licenças.", "Criar chave", padrao_sim=False):
            return
        ok, publica = tema.tratar(self, nucleo.criar_chave, self._arquivo())
        self.atualizar_chave()
        if ok:
            tema.mensagem(self, f"Chave criada. Faça já uma cópia de segurança.\n\nChave pública:\n{publica}", "Chave de segurança")

    def abrir_pasta(self) -> None:
        pasta = self._arquivo().parent
        pasta.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(pasta)                                         # noqa: S606 - abre a pasta no Explorer
            else:
                subprocess.Popen(["xdg-open", str(pasta)])
        except OSError:
            tema.aviso(self, f"A pasta é:\n{pasta}", "Chave")

    # ---------------------------------------------------------------- backup
    def _aba_backup(self) -> None:
        f = ttk.Frame(self.abas, padding=16)
        self.abas.add(f, text="  Backup  ")
        ttk.Label(f, wraplength=780, justify="left",
                  text="Guarde cópia do histórico (quem vence quando) e da chave fora deste computador. Para usar o Google Drive: instale o "
                       "\"Google Drive para computador\", escolha abaixo uma pasta dentro do Meu Drive e pronto, ele sincroniza sozinho. "
                       "O programa não entra na sua conta Google nem guarda senha dela.").pack(anchor="w")
        self.lbl_pasta = ttk.Label(f, text="", font=tema.FONTE_B, wraplength=780, justify="left")
        self.lbl_pasta.pack(anchor="w", pady=(12, 2))
        linha = ttk.Frame(f)
        linha.pack(anchor="w", pady=4)
        ttk.Button(linha, text="Escolher pasta do backup...", command=self.escolher_pasta_backup).pack(side="left")
        self.btn_drive = ttk.Button(linha, text="Usar o Google Drive deste computador", command=self.usar_google_drive)
        self.btn_drive.pack(side="left", padx=8)
        self.var_auto = tk.BooleanVar(value=self.config.backup_automatico)
        ttk.Checkbutton(f, text="Guardar o histórico sozinho a cada licença emitida ou removida", variable=self.var_auto,
                        command=self.mudar_automatico).pack(anchor="w", pady=(8, 2))
        acoes = ttk.Frame(f)
        acoes.pack(anchor="w", pady=12)
        self.btn_backup_agora = ttk.Button(acoes, text="Fazer backup agora (histórico e chave)", style="Ok.TButton",
                                           command=self.backup_agora)
        self.btn_backup_agora.pack(side="left")
        ttk.Button(acoes, text="Restaurar histórico...", command=self.restaurar_historico).pack(side="left", padx=8)
        ttk.Button(acoes, text="Restaurar chave...", command=self.restaurar_chave).pack(side="left")
        self.lbl_backup = ttk.Label(f, text="", wraplength=780, justify="left")
        self.lbl_backup.pack(anchor="w", pady=6)
        ttk.Label(f, wraplength=780, justify="left", foreground=COR["suave"],
                  text="A chave só vai para a nuvem criptografada com uma senha sua (mínimo 12 caracteres). Anote a senha em lugar seguro: "
                       "sem ela o backup da chave não abre. O histórico não tem a chave, mas tem os códigos de licença emitidos.").pack(anchor="w", pady=(10, 0))

    def atualizar_backup(self) -> None:
        pasta = self.config.pasta_backup
        self.lbl_pasta.configure(text=f"Pasta do backup: {pasta}" if pasta else "Pasta do backup: ainda não escolhida")
        self.btn_drive.state(["!disabled"] if nucleo.pastas_do_google_drive() else ["disabled"])
        self.btn_backup_agora.state(["!disabled"] if pasta else ["disabled"])
        ultimo = self.config.ultimo_backup
        if ultimo and not self.lbl_backup.cget("text"):
            self.lbl_backup.configure(text=f"Último backup do histórico: {ultimo}", foreground=COR["ok"])

    def escolher_pasta_backup(self) -> None:
        drives = nucleo.pastas_do_google_drive()
        inicial = str(self.config.pasta_backup or (drives[0] if drives else Path.home()))
        pasta = filedialog.askdirectory(parent=self, title="Em que pasta guardar o backup? (por exemplo, dentro do Meu Drive)",
                                        initialdir=inicial)
        if pasta:
            self._definir_pasta(Path(pasta))

    def usar_google_drive(self) -> None:
        drives = nucleo.pastas_do_google_drive()
        if drives:
            self._definir_pasta(drives[0])

    def _definir_pasta(self, pasta: Path) -> None:
        self.config.definir(pasta_backup=pasta)
        self.lbl_backup.configure(text="")
        self.atualizar_backup()
        self._backup_automatico()

    def mudar_automatico(self) -> None:
        self.config.definir(backup_automatico=bool(self.var_auto.get()))

    def _backup_automatico(self) -> None:
        """Depois de emitir ou remover: copia o histórico se a pasta estiver escolhida. Nunca atrapalha a emissão."""
        pasta = self.config.pasta_backup
        if pasta is None or not self.config.backup_automatico:
            return
        try:
            arquivo = nucleo.backup_historico(pasta, self.historico)
        except ErroLicenciador as e:
            self.lbl_backup.configure(text=f"Não consegui guardar o backup do histórico: {e}", foreground=COR["perigo"])
            return
        agora = fmt.agora()
        self.config.definir(ultimo_backup=agora)
        self.lbl_backup.configure(text=f"Histórico guardado em {arquivo} ({agora}).", foreground=COR["ok"])

    def backup_agora(self) -> None:
        pasta = self.config.pasta_backup
        if pasta is None:
            tema.aviso(self, "Escolha antes a pasta do backup.", "Backup")
            return
        ok, arquivo = tema.tratar(self, nucleo.backup_historico, pasta, self.historico)
        if not ok:
            return
        self.config.definir(ultimo_backup=fmt.agora())
        texto = f"Histórico guardado em:\n{arquivo}"
        if self.arquivo_chave is not None or nucleo.arquivo_chave().exists():
            senha = tema.pedir_texto(self, "Backup da chave", "Senha para proteger a chave na nuvem (12 caracteres ou mais)",
                                     senha=True, validar=backup_seguro.validar_senha)
            if senha is not None:
                repetida = tema.pedir_texto(self, "Backup da chave", "Digite a senha de novo", senha=True)
                if repetida != senha:
                    tema.erro(self, "As senhas não são iguais. A chave não foi guardada.", "Backup da chave")
                else:
                    ok, chave = tema.tratar(self, nucleo.backup_chave_protegido, pasta, senha, self.arquivo_chave)
                    texto += f"\n\nChave (criptografada) guardada em:\n{chave}" if ok else ""
            else:
                texto += "\n\nA chave não foi guardada (você não digitou senha)."
        self.lbl_backup.configure(text=texto, foreground=COR["ok"])
        tema.mensagem(self, texto, "Backup")

    def restaurar_historico(self) -> None:
        origem = filedialog.askopenfilename(parent=self, title="Escolha o backup do histórico (historico-AAAA-MM-DD.json)",
                                            initialdir=str(self.config.pasta_backup or Path.home()),
                                            filetypes=[("Histórico", "*.json")])
        if not origem:
            return
        if not tema.confirmar(self, "Trocar o histórico deste computador pelo backup escolhido?\nO atual fica guardado como .json.bak.",
                              "Restaurar histórico", padrao_sim=False):
            return
        ok, quantas = tema.tratar(self, nucleo.restaurar_historico, Path(origem), self.historico)
        self.atualizar_lojas()
        self.ent_loja.configure(values=self.historico.lojas())
        if ok:
            tema.mensagem(self, f"{quantas} licença(s) restaurada(s).", "Restaurar histórico")

    def restaurar_chave(self) -> None:
        origem = filedialog.askopenfilename(parent=self, title="Escolha o backup da chave (licenca_privada.key.pdvbkp)",
                                            initialdir=str(self.config.pasta_backup or Path.home()),
                                            filetypes=[("Backup da chave", "*.pdvbkp")])
        if not origem:
            return
        senha = tema.pedir_texto(self, "Restaurar chave", "Senha do backup", senha=True)
        if senha is None:
            return
        substituir = False
        if self._arquivo().exists():
            if not tema.confirmar(self, "Já existe uma chave neste computador. Substituir pela do backup?\nA atual fica guardada como .bak.",
                                  "Restaurar chave", padrao_sim=False):
                return
            substituir = True
        ok, _ = tema.tratar(self, nucleo.restaurar_chave_protegida, Path(origem), senha, self._arquivo(), substituir)
        self.atualizar_chave()
        if ok:
            tema.mensagem(self, "Chave restaurada.", "Restaurar chave")


def main() -> None:
    Janela().mainloop()
