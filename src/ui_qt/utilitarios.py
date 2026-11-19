"""Utilitários locais Qt; integração: ``JanelaUtilitarios(ctx, parent).exec()``."""
import sqlite3

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from src.core import formatacao as fmt
from src.core import suporte_remoto
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui_qt.tema import texto


class JanelaUtilitarios(QDialog):
    """Usa o Contexto da sessão; ações devolvem True só quando concluídas.

    Não abre restauração, fila nem configuração de backup externo; `verificar_backup`
    abre `JanelaVerificarBackup` (ensaio isolado, sem tocar o banco em uso). Erros das
    ações aparecem em ``mensagem``; resultados e caminhos ficam em ``status``.
    A construção exige sessão ativa; cada ação exige sua permissão.
    """

    ACOES = (
        ("backup", "Backup local manual", "util_backup"),
        ("suporte", "Pacote de suporte (log de erros)", "util_backup"),
        ("rustdesk", "Suporte remoto (RustDesk)", "util_comunicacao"),
        ("limpeza", "Limpeza do movimento…", "util_limpeza"),
        ("excluir_produtos", "Excluir todos os produtos…", "util_excluir_produtos"),
        ("comunicacao", "Programa de comunicação", "util_comunicacao"),
        ("verificar_backup", "Verificar backup (teste de restauração)…", "util_backup"),
        ("recuperar_nuvem", "Recuperar a loja pelo backup da nuvem…", "util_backup"),
        ("senha_seguranca", "Senha de segurança do dono…", "util_vendas_teste"),
        ("vendas_teste", "Apagar vendas de teste…", "util_vendas_teste"),
    )

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._operador()
        self.setWindowTitle("Utilitários")
        self.resize(850, 490)
        layout = QVBoxLayout(self)
        layout.addWidget(texto("Utilitários locais", "titulo"))
        self.botoes = {}
        for chave, titulo, permissao in self.ACOES:
            botao = QPushButton(titulo)
            botao.setEnabled(ctx.acesso.pode(ctx.operador, permissao))
            botao.clicked.connect(getattr(self, chave))
            self.botoes[chave] = botao
        grade = QGridLayout()
        for indice, (titulo, chaves) in enumerate((
            ("Backup e recuperação", ("backup", "verificar_backup", "recuperar_nuvem")),
            ("Suporte e comunicação", ("suporte", "rustdesk", "comunicacao")),
            ("Manutenção de dados", ("limpeza", "excluir_produtos", "vendas_teste")),
            ("Acesso do dono", ("senha_seguranca",)),
        )):
            grupo = QGroupBox(titulo)
            coluna = QVBoxLayout(grupo)
            for chave in chaves:
                botao = self.botoes[chave]
                if chave in ("limpeza", "excluir_produtos", "vendas_teste"):
                    botao.setObjectName("perigo")
                coluna.addWidget(botao)
            coluna.addStretch()
            grade.addWidget(grupo, indice // 2, indice % 2)
        layout.addLayout(grade)
        self.status = texto("Nenhuma operação executada nesta janela.", "suave")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.mensagem = texto("", "aviso")
        self.mensagem.setWordWrap(True)
        layout.addWidget(self.mensagem)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        rodape = QHBoxLayout()
        rodape.addStretch()
        rodape.addWidget(fechar)
        layout.addLayout(rodape)

    def _operador(self):
        if self.ctx.operador is None:
            raise ErroPermissao("Entre no sistema para usar os utilitários.")
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            raise ErroPermissao("Operador inativo. Encerre a sessão.")
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)

    def _controlador(self, permissao):
        self._operador()
        self.ctx.acesso.exigir(self.ctx.operador, permissao)
        return self.ctx.utilitarios

    def exigir_acesso(self):
        self._operador()
        permitido = False
        for chave, _, modulo in self.ACOES:
            pode = self.ctx.pode(modulo)
            self.botoes[chave].setEnabled(pode)
            permitido = permitido or pode
        if not permitido:
            self.status.clear()
            raise ErroPermissao("Seu acesso não permite os utilitários.")
        return True

    def _executar(self, acao):
        self.mensagem.clear()
        try:
            return acao()
        except (ErroNegocio, OSError, ValueError, sqlite3.Error) as erro:
            self.mensagem.setText(str(erro))
            return False

    def _pedir(self, permissao, titulo, mensagem, padrao=""):
        self._controlador(permissao)
        resposta = QInputDialog.getText(
            self, titulo, mensagem, QLineEdit.EchoMode.Normal, padrao)
        self._controlador(permissao)
        return resposta

    def backup(self):
        def acao():
            caminho = self._controlador("util_backup").backup()
            _, situacao = self._controlador("util_backup").situacao_backup()
            self.status.setText(f"Backup local gerado:\n{caminho}\n\n{situacao}")
            return True
        return self._executar(acao)

    def verificar_backup(self):
        def acao():
            self._controlador("util_backup")
            from src.ui_qt.restaurar_backup import JanelaVerificarBackup
            self.janela_verificacao = JanelaVerificarBackup(self.ctx, self)
            self.janela_verificacao.open()
            self.status.setText(self.ctx.utilitarios.situacao_teste_restauracao()[1])
            return True
        return self._executar(acao)

    def recuperar_nuvem(self):
        def acao():
            self._controlador("util_backup")
            from src.ui_qt.backup_nuvem import JanelaBackupNuvem
            self.janela_backup_nuvem = JanelaBackupNuvem(self.ctx, self)
            self.janela_backup_nuvem.open()
            return True
        return self._executar(acao)

    def suporte(self):
        def acao():
            caminho = self._controlador("util_backup").pacote_suporte()
            self.status.setText(
                f"Pacote de suporte gerado:\n{caminho}\n\nEnvie este arquivo ao fornecedor. "
                "Ele leva só os registros de erro (log), nunca as vendas.")
            return True
        return self._executar(acao)

    def rustdesk(self):
        """Abre o RustDesk e mostra o ID deste computador (já copiado). Sem o programa, oferece a página de download."""
        def acao():
            ctrl = self._controlador("util_comunicacao")
            if not ctrl.rustdesk_instalado():
                resposta = QMessageBox.question(
                    self, "Suporte remoto",
                    "O RustDesk não está instalado neste computador.\n\n"
                    "É o programa que deixa o suporte ver esta tela, sempre com a sua liberação.\n"
                    "Abrir a página rustdesk.com para baixar?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
                if resposta == QMessageBox.StandardButton.Yes:
                    QDesktopServices.openUrl(QUrl(suporte_remoto.SITE))
                    self.status.setText("Página do RustDesk aberta no navegador. Baixe, instale e clique aqui de novo.")
                    return False
            ctrl.abrir_rustdesk()
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                id_atual = ctrl.obter_id_rustdesk()
            finally:
                QApplication.restoreOverrideCursor()
            if id_atual:
                QApplication.clipboard().setText(id_atual)
                self.status.setText(
                    f"RustDesk aberto.\n\nID deste computador: {suporte_remoto.formatar_id(id_atual)}\n"
                    "(já copiado: é só colar na conversa com o suporte)\n\n"
                    "Passe também a senha de uso único que aparece na janela do RustDesk, ou aceite a conexão "
                    "quando ela chegar. Sem a sua liberação ninguém entra.")
            else:
                self.status.setText(
                    "RustDesk aberto.\n\nPasse ao suporte o ID e a senha de uso único que aparecem na janela dele. "
                    "Sem a sua liberação ninguém entra.")
            return True
        return self._executar(acao)

    def comunicacao(self):
        def acao():
            self._controlador("util_comunicacao").abrir_programa_comunicacao()
            self.status.setText("Programa de comunicação aberto.")
            return True
        return self._executar(acao)

    def limpeza(self):
        def acao():
            permissao = "util_limpeza"
            data_texto, aceito = self._pedir(
                permissao, "Limpeza do movimento",
                "Apaga as vendas e movimentos ANTERIORES à data informada.\n"
                "ATENÇÃO: o período apagado termina no dia anterior à data lançada.\n"
                "Recomenda-se manter o último mês (faça os relatórios antes).\n"
                "Um backup é feito automaticamente.\n\n"
                "Apagar tudo anterior a (dd/mm/aaaa):",
                fmt.fmt_data(fmt.hoje()[:8] + "01"))
            if not aceito:
                return False
            data = fmt.para_data_iso(data_texto)
            if data is None:
                raise ErroNegocio("Informe a data limite para a limpeza.")
            confirmacao, aceito = self._pedir(
                permissao, "Confirmar limpeza",
                f"Serão apagadas as vendas anteriores a {fmt.fmt_data(data)}.\n"
                "Esta operação não pode ser desfeita (exceto restaurando o backup).\n\n"
                "Digite APAGAR para confirmar:")
            if not aceito or confirmacao.strip().upper() != "APAGAR":
                return False
            resultado = self._controlador(permissao).limpar_movimento(data)
            self.status.setText(
                f"Limpeza concluída.\n\nVendas apagadas: {resultado['vendas']}\n"
                f"Turnos apagados: {resultado['turnos']}\n"
                f"Movimentos de estoque: {resultado['movimentos_estoque']}\n"
                f"Comissões pagas ou canceladas: {resultado.get('comissoes', 0)}\n"
                f"Backup anterior à limpeza:\n{resultado['backup']}")
            return True
        return self._executar(acao)


    def senha_seguranca(self):
        def acao():
            self._controlador("util_vendas_teste")
            from src.ui_qt.vendas_teste import JanelaSenhaSeguranca
            if JanelaSenhaSeguranca(self.ctx, self).exec():
                self.status.setText("Senha de segurança do dono gravada. Ela sobe para o painel na próxima "
                                    "sincronização.")
                return True
            return False
        return self._executar(acao)

    def vendas_teste(self):
        def acao():
            self._controlador("util_vendas_teste")
            from src.ui_qt.vendas_teste import JanelaApagarVendasTeste
            self.janela_vendas_teste = JanelaApagarVendasTeste(self.ctx, self)
            self.janela_vendas_teste.open()
            return True
        return self._executar(acao)

    def excluir_produtos(self):
        def acao():
            permissao = "util_excluir_produtos"
            resumo = self._controlador(permissao).resumo_exclusao_produtos()
            if not resumo["total"]:
                raise ErroNegocio("Não há produtos cadastrados.")
            if resumo["vendas_abertas"]:
                raise ErroNegocio(
                    f"Há {resumo['vendas_abertas']} venda(s), mesa(s) ou comanda(s) abertas com itens.\n"
                    "Feche ou cancele antes de excluir os produtos.")
            confirmacao, aceito = self._pedir(
                permissao, "Excluir todos os produtos",
                "Isto exclui TODOS os produtos de uma vez, para você cadastrar a tabela de novo\n"
                "(Cadastros > Produtos > Importar planilha).\n\n"
                f"Produtos cadastrados: {resumo['total']}\n"
                f"Serão excluídos: {resumo['excluidos']}\n"
                "O cadastro será removido e os códigos ficarão livres. Cupons, relatórios e movimentos "
                "antigos continuam no histórico, sem ligação com os novos produtos.\n\n"
                "Um backup é feito antes. Não dá para desfazer, a não ser restaurando o backup.\n\n"
                "Digite APAGAR para confirmar:")
            if not aceito or confirmacao.strip().upper() != "APAGAR":
                return False
            resultado = self._controlador(permissao).excluir_todos_produtos()
            self.status.setText(
                f"Produtos excluídos: {resultado['excluidos']}\n"
                "Histórico de vendas e estoque preservado.\n"
                f"\nBackup anterior à exclusão:\n{resultado['backup']}\n\n"
                "Agora é só importar a planilha.")
            return True
        return self._executar(acao)


MODULOS_UTILITARIOS = tuple(dict.fromkeys(acao[2] for acao in JanelaUtilitarios.ACOES))
