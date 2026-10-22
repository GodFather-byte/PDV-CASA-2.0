"""Utilitários (manual ADM seção 7): limpeza do movimento, programa de comunicação e backup."""
from __future__ import annotations

import os
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui import tema


def executar(master, ctx, chave: str):
    """Executa a ação do menu Utilitários. Em "verificar_backup" devolve a janela aberta (ou None)."""
    if chave == "backup":
        ok, caminho = tema.tratar(master, ctx.utilitarios.backup)
        if ok:
            _, situacao = ctx.utilitarios.situacao_backup()
            tema.mensagem(master, f"Backup local gerado:\n{caminho}\n\n{situacao}", "Backup de dados")
    elif chave == "backup_externo":
        backup_externo(master, ctx)
    elif chave == "restaurar":
        restaurar(master, ctx)
    elif chave == "verificar_backup":
        return verificar_backup(master, ctx)
    elif chave == "suporte":
        ok, caminho = tema.tratar(master, ctx.utilitarios.pacote_suporte)
        if ok:
            tema.mensagem(master, f"Pacote de suporte gerado:\n{caminho}\n\nEnvie este arquivo ao fornecedor. Ele leva só os "
                                  "registros de erro (log), nunca as vendas.", "Pacote de suporte")
    elif chave == "comunicacao":
        tema.tratar(master, ctx.utilitarios.abrir_programa_comunicacao)
    elif chave == "limpeza":
        limpeza(master, ctx)
    elif chave == "excluir_produtos":
        excluir_produtos(master, ctx)
    elif chave == "fila_impressao":
        from src.ui.fila_impressao_ui import JanelaFilaImpressao
        JanelaFilaImpressao(master, ctx)
    elif chave == "cozinha":
        from src.ui.cozinha_ui import JanelaCozinha
        JanelaCozinha(master, ctx)


def limpeza(master, ctx) -> None:
    padrao = fmt.fmt_data(fmt.hoje()[:8] + "01")
    texto = tema.pedir_texto(
        master, "Limpeza do movimento",
        "Apaga as vendas e movimentos ANTERIORES à data informada.\n"
        "ATENÇÃO: o período apagado termina no dia anterior à data lançada.\n"
        "Recomenda-se manter o último mês (faça os relatórios antes). Um backup é feito automaticamente.\n\n"
        "Apagar tudo anterior a (dd/mm/aaaa):", padrao, largura=16)
    if texto is None:
        return
    try:
        data = fmt.para_data_iso(texto)
    except ValueError as e:
        tema.aviso(master, str(e))
        return
    if data is None:
        return
    conf = tema.pedir_texto(master, "Confirmar limpeza",
                            f"Serão apagadas as vendas anteriores a {fmt.fmt_data(data)}.\nEsta operação não pode ser desfeita "
                            "(exceto restaurando o backup).\n\nDigite APAGAR para confirmar:", largura=16)
    if (conf or "").strip().upper() != "APAGAR":
        return
    ok, res = tema.tratar(master, ctx.utilitarios.limpar_movimento, data)
    if ok:
        tema.mensagem(master, f"Limpeza concluída.\n\nVendas apagadas: {res['vendas']}\nTurnos apagados: {res['turnos']}\n"
                              f"Movimentos de estoque: {res['movimentos_estoque']}\nComissões pagas ou canceladas: {res.get('comissoes', 0)}\n"
                              f"Backup anterior à limpeza:\n{res['backup']}",
                      "Limpeza do movimento")


def excluir_produtos(master, ctx) -> bool:
    """Exclui todos os produtos de uma vez (para importar a tabela de novo). Mostra o que vai acontecer, pede para digitar
    APAGAR e só então executa, com backup antes. Devolve True se excluiu."""
    r = ctx.utilitarios.resumo_exclusao_produtos()
    if not r["total"]:
        tema.aviso(master, "Não há produtos cadastrados.")
        return False
    if r["vendas_abertas"]:
        tema.aviso(master, f"Há {r['vendas_abertas']} venda(s), mesa(s) ou comanda(s) abertas com itens.\n"
                           "Feche ou cancele antes de excluir os produtos.", "Excluir todos os produtos")
        return False
    texto = (f"Isto exclui TODOS os produtos de uma vez, para você cadastrar a tabela de novo\n"
             f"(Cadastros > Produtos > Importar planilha).\n\nProdutos cadastrados: {r['total']}\n"
             f"Serão excluídos: {r['excluidos']}\n")
    texto += ("O cadastro será removido e os códigos ficarão livres. Cupons, relatórios e movimentos antigos "
              "continuam no histórico, sem ligação com os novos produtos.\n")
    texto += ("\nUm backup é feito antes. Não dá para desfazer, a não ser restaurando o backup.\n\n"
              "Digite APAGAR para confirmar:")
    conf = tema.pedir_texto(master, "Excluir todos os produtos", texto, largura=16)
    if (conf or "").strip().upper() != "APAGAR":
        return False
    ok, res = tema.tratar(master, ctx.utilitarios.excluir_todos_produtos)
    if not ok:
        return False
    msg = f"Produtos excluídos: {res['excluidos']}\n"
    msg += "Histórico de vendas e estoque preservado.\n"
    tema.mensagem(master, msg + f"\nBackup anterior à exclusão:\n{res['backup']}\n\nAgora é só importar a planilha.",
                  "Excluir todos os produtos")
    return True


def restaurar(master, ctx) -> None:
    backups = ctx.utilitarios.listar_backups()
    if not backups:
        tema.aviso(master, "Não há backups nas pastas configuradas.")
        return
    itens = [(str(p), (p.name.removeprefix("loja_offline-").removesuffix(".db"), str(p.parent))) for p in backups[:60]]
    escolhido = tema.escolher(master, "Restaurar backup", itens, "Escolha o backup (mais novos primeiro):", largura=620,
                              colunas=[("data", "Data e hora", 170, "w"), ("pasta", "Pasta", 420, "w")], altura=12)
    if escolhido is None:
        return
    if not tema.confirmar(master, "O sistema volta ao estado deste backup: tudo o que foi lançado DEPOIS dele se perde.\n"
                                  "Uma cópia do estado de agora é guardada antes.\n\nA restauração acontece quando o programa "
                                  "for aberto de novo.\nMarcar a restauração?", "Restaurar backup", padrao_sim=False):
        return
    ok, _ = tema.tratar(master, ctx.utilitarios.pedir_restauracao, escolhido)
    if ok:
        tema.mensagem(master, "Restauração marcada. FECHE o programa e abra de novo para concluir.", "Restaurar backup")


def verificar_backup(master, ctx):
    """Abre o teste de restauração isolado; sem acesso `util_backup`, mostra o motivo e não abre."""
    ok, janela = tema.tratar(master, JanelaVerificarBackup, master, ctx)
    return janela if ok else None


def backup_externo(master, ctx) -> None:
    acoes = [("configurar", "Configurar pasta e senha de recuperação"),
             ("gerar", "Gerar cópia criptografada agora"),
             ("verificar", "Testar recuperação de um arquivo (restauração isolada)"),
             ("recuperar", "Restaurar arquivo criptografado"),
             ("desativar", "Desativar cópias externas automáticas")]
    acao = tema.escolher(master, "Backup externo criptografado", acoes,
                         "A pasta será sincronizada pelo OneDrive/Google Drive do computador.\n"
                         "O PDV verifica o arquivo, mas não confirma o envio à nuvem.", largura=650)
    if acao == "configurar":
        sugestao = os.environ.get("OneDriveCommercial") or os.environ.get("OneDrive") or str(Path.home())
        pasta = filedialog.askdirectory(parent=master, title="Escolha uma pasta sincronizada",
                                        initialdir=ctx.banco.cfg("backup_externo_pasta") or sugestao)
        if not pasta:
            return
        senha = tema.pedir_texto(master, "Senha de recuperação",
                                 "Crie uma senha de pelo menos 12 caracteres e guarde FORA deste computador.\n"
                                 "Sem ela, outra máquina não recupera os arquivos. O fornecedor não consegue redefini-la.\n"
                                 "No Windows ela é guardada protegida para as cópias automáticas.", senha=True)
        if senha is None:
            return
        repetida = tema.pedir_texto(master, "Confirme a senha", "Digite a senha de recuperação novamente:", senha=True)
        if repetida is None:
            return
        if senha != repetida:
            tema.aviso(master, "As senhas são diferentes. A configuração não foi alterada.")
            return
        ok, _ = tema.tratar(master, ctx.utilitarios.configurar_backup_externo, pasta, senha)
        if ok:
            tema.mensagem(master, "Configuração gravada. Gere a primeira cópia e teste a recuperação.\n"
                                  "Confira também no OneDrive/Google Drive se o arquivo foi enviado.", "Backup externo")
    elif acao == "gerar":
        ok, caminho = tema.tratar(master, ctx.utilitarios.backup_externo)
        if ok:
            tema.mensagem(master, f"Cópia criptografada gerada e recuperação verificada:\n{caminho}\n\n"
                                  "O envio à nuvem depende do sincronizador da pasta.", "Backup externo")
    elif acao in ("verificar", "recuperar"):
        arquivo = filedialog.askopenfilename(parent=master, title="Escolha o backup criptografado",
                                             filetypes=[("Backup seguro WillPDV", "*.pdvbkp")])
        if not arquivo:
            return
        senha = tema.pedir_texto(master, "Recuperação de backup", "Informe a senha usada neste arquivo:", senha=True)
        if senha is None:
            return
        if acao == "verificar":
            ok, resultado = tema.tratar(master, ctx.utilitarios.testar_recuperacao, arquivo, senha)
            if ok:
                tema.mensagem(master, ctx.utilitarios.texto_teste_restauracao(resultado),
                              "Recuperação REPROVADA" if not resultado["ok"] else
                              "Recuperação verificada COM AVISOS" if resultado.get("avisos") else
                              "Recuperação verificada",
                              "info" if resultado["ok"] and not resultado.get("avisos") else "aviso")
        elif tema.confirmar(master, "Tudo lançado depois do backup será perdido.\n"
                                    "Uma cópia local do estado atual será guardada antes.\n"
                                    "Marcar a restauração para a próxima abertura?", "Restaurar", padrao_sim=False):
            ok, _ = tema.tratar(master, ctx.utilitarios.pedir_restauracao_externa, arquivo, senha)
            if ok:
                tema.mensagem(master, "Restauração marcada. Feche e abra o programa para aplicar.", "Restaurar backup")
    elif acao == "desativar" and tema.confirmar(
            master, "Desativar as próximas cópias externas? Os arquivos já gerados não serão apagados.",
            "Backup externo", padrao_sim=False):
        tema.tratar(master, ctx.utilitarios.desativar_backup_externo)


class JanelaVerificarBackup(tk.Toplevel):
    """Teste de restauração ISOLADO (Tk). ``exigir_acesso()`` revalida sessão, operador ativo e ``util_backup``
    na abertura e antes de cada ação; não troca nem marca restauração; senha de ``.pdvbkp`` só em memória."""

    def __init__(self, master, ctx):
        self.ctx = ctx
        self.exigir_acesso()
        super().__init__(master)
        self.title("Verificar backup (teste de restauração)")
        self.geometry("920x660")
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both", expand=True)
        ttk.Label(corpo, wraplength=880, text=(
            "O backup escolhido é copiado para uma pasta temporária, restaurado ali e conferido (integridade, "
            "esquema e contagens). O banco em uso NÃO é alterado e nenhuma restauração é marcada.")).pack(fill="x")
        self.ultima = ttk.Label(corpo, text="", wraplength=880)
        self.ultima.pack(fill="x", pady=(8, 4))
        quadro = ttk.Frame(corpo)
        quadro.pack(fill="both", expand=True)
        self.grade = ttk.Treeview(quadro, columns=("arquivo", "pasta"), show="headings", height=8,
                                  selectmode="browse")
        self.grade.heading("arquivo", text="Backup local")
        self.grade.heading("pasta", text="Pasta")
        self.grade.column("arquivo", width=300)
        self.grade.column("pasta", width=560)
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=self.grade.yview)
        self.grade.configure(yscrollcommand=rolagem.set)
        self.grade.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")
        self.resultado = tk.Text(corpo, height=12, wrap="word")
        self.resultado.pack(fill="both", expand=True, pady=6)
        self.resultado.configure(state="disabled")
        self.mensagem = ttk.Label(corpo, text="", wraplength=880)
        self.mensagem.pack(fill="x")
        acoes = ttk.Frame(corpo)
        acoes.pack(fill="x", pady=(6, 0))
        self.btn_recente = ttk.Button(acoes, text="Verificar o mais recente", command=self.verificar)
        self.btn_recente.pack(side="left")
        ttk.Button(acoes, text="Verificar selecionado", command=self.verificar_selecionado).pack(side="left", padx=6)
        ttk.Button(acoes, text="Verificar arquivo criptografado…",
                   command=self.verificar_externo).pack(side="left")
        ttk.Button(acoes, text="Atualizar lista", command=self.carregar).pack(side="left", padx=6)
        ttk.Button(acoes, text="Fechar", command=self.destroy).pack(side="right")
        self.caminhos: dict[str, str] = {}
        self.carregar()

    def exigir_acesso(self):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre no sistema para verificar backups.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        self.ctx.acesso.exigir(self.ctx.operador, "util_backup")
        return True

    def _controlador(self):
        self.exigir_acesso()
        return self.ctx.utilitarios

    def _texto(self, conteudo: str) -> None:
        self.resultado.configure(state="normal")
        self.resultado.delete("1.0", "end")
        self.resultado.insert("1.0", conteudo)
        self.resultado.configure(state="disabled")

    def texto_resultado(self) -> str:
        return self.resultado.get("1.0", "end-1c")

    def carregar(self) -> bool:
        try:
            controlador = self._controlador()
            atual = None if self.ctx.banco.caminho == ":memory:" else Path(self.ctx.banco.caminho).resolve()
            backups = [p for p in controlador.listar_backups() if p.resolve() != atual][:60]
        except (ErroNegocio, OSError, ValueError, sqlite3.Error) as erro:
            self.mensagem.configure(text=str(erro))
            return False
        self.grade.delete(*self.grade.get_children())
        self.caminhos = {}
        for caminho in backups:
            iid = self.grade.insert("", "end", values=(caminho.name, str(caminho.parent)))
            self.caminhos[iid] = str(caminho)
        self.btn_recente.state(["!disabled"] if backups else ["disabled"])
        self.ultima.configure(text=self.ctx.utilitarios.situacao_teste_restauracao()[1])
        self.mensagem.configure(text="" if backups else "Não há backups locais nas pastas configuradas.")
        return True

    def verificar(self, caminho: str | None = None, senha: str | None = None) -> bool:
        """Executa o ensaio; True só quando aprovado. O diagnóstico aparece na caixa de resultado."""
        self.mensagem.configure(text="")
        try:
            resultado = self._controlador().testar_recuperacao(caminho, senha)
        except (ErroNegocio, OSError, ValueError, sqlite3.Error) as erro:
            self.mensagem.configure(text=str(erro))
            return False
        self._texto(self.ctx.utilitarios.texto_teste_restauracao(resultado))
        self.ultima.configure(text=self.ctx.utilitarios.situacao_teste_restauracao()[1])
        if not resultado["ok"]:
            self.mensagem.configure(
                text="Backup REPROVADO no teste de restauração. Gere um novo backup e confira o disco.")
        elif resultado.get("avisos"):
            self.mensagem.configure(text="Backup APROVADO COM AVISOS: restaura, mas há registros sem vínculo. "
                                         "Confira os avisos e chame o suporte antes de depender dele.")
        return resultado["ok"]

    def verificar_selecionado(self) -> bool:
        selecao = self.grade.selection()
        if not selecao:
            self.mensagem.configure(text="Selecione um backup da lista.")
            return False
        return self.verificar(self.caminhos[selecao[0]])

    def verificar_externo(self) -> bool:
        try:
            self._controlador()
        except ErroNegocio as erro:
            self.mensagem.configure(text=str(erro))
            return False
        arquivo = filedialog.askopenfilename(parent=self, title="Escolha o backup criptografado",
                                             initialdir=self.ctx.banco.cfg("backup_externo_pasta") or None,
                                             filetypes=[("Backup seguro WillPDV", "*.pdvbkp")])
        if not arquivo:
            return False
        senha = tema.pedir_texto(self, "Senha de recuperação", "Informe a senha usada neste arquivo:", senha=True)
        if senha is None:
            return False
        return self.verificar(arquivo, senha)