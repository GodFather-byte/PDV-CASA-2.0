"""Utilitários (manual ADM seção 7): limpeza do movimento, programa de comunicação e backup."""
from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog

from src.core import formatacao as fmt
from src.ui import tema


def executar(master, ctx, chave: str) -> None:
    if chave == "backup":
        ok, caminho = tema.tratar(master, ctx.utilitarios.backup)
        if ok:
            _, situacao = ctx.utilitarios.situacao_backup()
            tema.mensagem(master, f"Backup local gerado:\n{caminho}\n\n{situacao}", "Backup de dados")
    elif chave == "backup_externo":
        backup_externo(master, ctx)
    elif chave == "restaurar":
        restaurar(master, ctx)
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


def backup_externo(master, ctx) -> None:
    acoes = [("configurar", "Configurar pasta e senha de recuperação"),
             ("gerar", "Gerar cópia criptografada agora"),
             ("verificar", "Testar recuperação de um arquivo"),
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
            ok, _ = tema.tratar(master, ctx.utilitarios.verificar_backup_externo, arquivo, senha)
            if ok:
                tema.mensagem(master, "Senha e integridade conferidas. O banco atual não foi alterado.", "Recuperação verificada")
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
