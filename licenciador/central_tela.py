"""Configuração local e execução do painel Telegram do fornecedor."""
from __future__ import annotations

import os
import queue
import sqlite3
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from licenciador.central import Central, ClientePonte, caminho_padrao
from licenciador.central_bot import servir
from src.core.erros import ErroNegocio


class JanelaCentral(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Central do fornecedor — Telegram")
        self.geometry("860x650")
        self.minsize(760, 590)
        self.fila: queue.Queue = queue.Queue()
        self.parar = threading.Event()
        self.servico: threading.Thread | None = None
        self.ocupada = False
        self.fechando = False
        self.protocol("WM_DELETE_WINDOW", self.fechar)
        quadro = ttk.Frame(self, padding=16)
        quadro.pack(fill="both", expand=True)
        ttk.Label(quadro, text="Somente no computador exclusivo do fornecedor.",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(quadro, text="Sem faturamento das lojas. Nenhuma cobrança é criada por esta central.").pack(anchor="w")
        self.campos = {}
        for chave, rotulo, valor, secreto in (
            ("banco", "Banco próprio da central", str(caminho_padrao()), False),
            ("url", "Endereço HTTPS da API", os.environ.get("WILLCENTRAL_API_URL", ""), False),
            ("token", "Token exclusivo da central", os.environ.get("PDV_CENTRAL_TOKEN", ""), True),
            ("bot", "Token do bot administrativo", os.environ.get("WILLCENTRAL_TELEGRAM_TOKEN", ""), True),
        ):
            ttk.Label(quadro, text=rotulo).pack(anchor="w", pady=(6, 0))
            variavel = tk.StringVar(value=valor)
            ttk.Entry(quadro, textvariable=variavel, show="*" if secreto else "").pack(fill="x")
            self.campos[chave] = variavel
        ttk.Label(quadro, text="Tokens usados apenas nesta sessão; não são gravados no banco ou enviados ao Telegram.",
                  wraplength=800).pack(anchor="w", pady=6)
        linha = ttk.Frame(quadro)
        linha.pack(fill="x")
        for texto, acao in (("Cadastrar loja", self.cadastrar), ("Autorizar administrador", self.administrador),
                             ("Importar histórico", self.importar), ("Backup", self.backup)):
            ttk.Button(linha, text=texto, command=acao).pack(side="left", padx=(0, 6), pady=4)
        outra = ttk.Frame(quadro)
        outra.pack(fill="x")
        for texto, acao in (("Aprovar caixa", self.aprovar), ("Revogar caixa", self.revogar),
                             ("Publicar licença", self.publicar), ("Sincronizar", self.sincronizar),
                             ("Atualizar lista", self.atualizar)):
            ttk.Button(outra, text=texto, command=acao).pack(side="left", padx=(0, 6), pady=4)
        self.lista = ttk.Treeview(quadro, columns=("chave", "nome", "ativa", "validade"), show="headings", height=6)
        for chave, rotulo in (("chave", "Loja"), ("nome", "Nome"), ("ativa", "Ativa"), ("validade", "Emitida até")):
            self.lista.heading(chave, text=rotulo)
            self.lista.column(chave, width=170)
        self.lista.pack(fill="both", expand=True, pady=8)
        controles = ttk.Frame(quadro)
        controles.pack(fill="x")
        ttk.Button(controles, text="Iniciar bot e sincronização", command=self.iniciar).pack(side="left")
        ttk.Button(controles, text="Parar", command=self.parar.set).pack(side="left", padx=8)
        self.status = tk.StringVar(value="Parada. Inicie e envie /start ao bot para ver seu ID; autorize-o localmente.")
        ttk.Label(quadro, textvariable=self.status, wraplength=800).pack(anchor="w", pady=8)
        self._after_id = self.after(200, self.receber)

    def opcoes(self) -> dict:
        return {k: v.get().strip() for k, v in self.campos.items()}

    @staticmethod
    def abrir(opcoes, rede=False):
        ponte = ClientePonte(opcoes["url"], opcoes["token"]) if rede else None
        return Central(Path(opcoes["banco"]), ponte)

    def executar(self, acao, rede=False):
        if self.ocupada:
            messagebox.showinfo("Central", "Aguarde a operação local em andamento.", parent=self)
            return
        opcoes = self.opcoes()
        self.ocupada = True
        self.status.set("Processando...")

        def trabalho():
            central = None
            try:
                central = self.abrir(opcoes, rede)
                resultado = acao(central)
                self.fila.put(("resultado", resultado or "Operação concluída."))
            except ErroNegocio as erro:
                self.fila.put(("erro", str(erro)))
            except (OSError, sqlite3.Error):
                self.fila.put(("erro", "Falha no banco ou arquivo local. Confira acesso e integridade."))
            finally:
                if central:
                    central.fechar()
                self.fila.put(("livre", None))
        threading.Thread(target=trabalho, daemon=True, name="central-operacao").start()

    def cadastrar(self):
        chave = simpledialog.askstring("Loja", "Chave da loja (a mesma do PDV):", parent=self)
        if not chave:
            return
        nome = simpledialog.askstring("Loja", "Nome da loja:", parent=self)
        if nome:
            self.executar(lambda central: (central.cadastrar(chave, nome), "Cadastro local salvo.")[1])

    def administrador(self):
        numero = simpledialog.askstring("Administrador", "ID numérico privado do Telegram:", parent=self)
        if not numero:
            return
        if not numero.isdigit() or int(numero) <= 0:
            messagebox.showerror("Central", "Informe um ID numérico positivo.", parent=self)
            return
        escolha = messagebox.askyesnocancel(
            "Autorização", "Sim = autorizar este ID.\nNão = remover este ID.\nCancelar = não alterar.", parent=self)
        if escolha is None:
            return
        remover = not escolha
        self.executar(lambda central: (central.administrador(int(numero), remover),
                                      "Autorização local atualizada.")[1])

    def importar(self):
        origem = filedialog.askopenfilename(parent=self, title="Histórico original do licenciador",
                                           filetypes=[("Histórico JSON", "*.json")])
        if origem:
            self.executar(lambda central: f"Licenças importadas: {central.importar_historico(Path(origem))}. "
                                         "Original preservado; nenhuma loja migrada automaticamente.")

    def backup(self):
        destino = filedialog.asksaveasfilename(parent=self, title="Novo arquivo de backup", defaultextension=".db")
        if destino:
            self.executar(lambda central: (central.backup(Path(destino)),
                                          "Backup verificado. Guarde a chave privada criptografada separadamente.")[1])

    def aprovar(self):
        loja = simpledialog.askstring("Aprovar caixa", "Chave da loja:", parent=self)
        if not loja:
            return
        caixa = simpledialog.askstring("Aprovar caixa", "UUID mostrado nas configurações do PDV:", parent=self)
        if caixa:
            self.executar(lambda central: ("credencial", central.provisionar(loja, caixa)), rede=True)

    def revogar(self):
        caixa = simpledialog.askstring("Revogar caixa", "UUID da credencial a revogar:", parent=self)
        if caixa and messagebox.askyesno("Confirmar", "Revogar acesso deste caixa à ponte?", parent=self):
            self.executar(lambda central: (central.revogar_caixa(caixa), "Credencial revogada.")[1], rede=True)

    def sincronizar(self):
        self.executar(lambda central: (central.sincronizar(), "Ponte sincronizada.")[1], rede=True)

    def publicar(self):
        loja = simpledialog.askstring("Publicar licença", "Chave da loja:", parent=self)
        if loja and messagebox.askyesno(
                "Migrar entrega da licença",
                "Autorizar a publicação da licença mais recente dessa loja?\n"
                "Na próxima sincronização a ponte passará a entregar códigos assinados localmente, "
                "sem emitir na nuvem.", parent=self):
            self.executar(lambda central: (central.autorizar_publicacao(loja),
                                          "Publicação autorizada. Sincronize para entregar.")[1])

    def atualizar(self):
        self.executar(lambda central: ("lojas", central.lojas()))

    def iniciar(self):
        if self.servico and self.servico.is_alive():
            return
        opcoes = self.opcoes()
        self.parar.clear()

        def trabalho():
            central = None
            try:
                central = self.abrir(opcoes, True)
                servir(central, opcoes["bot"], self.parar,
                       notificar=lambda mensagem: self.fila.put(("status", mensagem)))
            except ErroNegocio as erro:
                self.fila.put(("erro", str(erro)))
            except (OSError, sqlite3.Error):
                self.fila.put(("erro", "Serviço encerrado por falha local. Confira banco e permissões."))
            finally:
                if central:
                    central.fechar()
                self.fila.put(("status", "Serviço parado."))
        self.servico = threading.Thread(target=trabalho, daemon=True, name="central-servico")
        self.servico.start()
        self.status.set("Iniciando serviço...")

    def receber(self):
        while True:
            try:
                tipo, valor = self.fila.get_nowait()
            except queue.Empty:
                break
            if tipo == "livre":
                self.ocupada = False
            elif tipo == "erro":
                self.status.set(valor)
                messagebox.showerror("Central", valor, parent=self)
            elif tipo == "resultado" and isinstance(valor, tuple):
                if valor[0] == "lojas":
                    self.lista.delete(*self.lista.get_children())
                    for loja in valor[1]:
                        self.lista.insert("", "end", values=(loja["chave"], loja["nome"],
                                                           "Sim" if loja["ativa"] else "Não", loja["validade"] or "—"))
                    self.status.set("Cadastro local atualizado.")
                elif valor[0] == "credencial":
                    janela = tk.Toplevel(self)
                    janela.title("Credencial do caixa — configure localmente")
                    ttk.Label(janela, text="Exibida apenas nesta janela. Não enviar pelo bot.").pack(padx=12, pady=8)
                    campo = ttk.Entry(janela, width=78)
                    campo.insert(0, valor[1])
                    campo.pack(padx=12, pady=12)
                    campo.selection_range(0, "end")
                    campo.focus_set()
                    self.status.set("Caixa aprovado. Configure a credencial no PDV.")
            else:
                self.status.set(valor)
        if self.fechando and not self.ocupada and not (self.servico and self.servico.is_alive()):
            self.destroy()
            return
        self._after_id = self.after(200, self.receber)

    def fechar(self):
        self.fechando = True
        self.parar.set()
        self.status.set("Encerrando operações; aguarde a consulta de rede terminar...")

    def destroy(self):
        self.parar.set()
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        super().destroy()


def main():
    root = tk.Tk()
    root.withdraw()
    janela = JanelaCentral(root)
    janela.bind("<Destroy>", lambda evento: root.destroy() if evento.widget is janela else None)
    root.mainloop()
