"""Piloto Qt opt-in; usa os controladores e a proteção de dados existentes."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
    QScrollArea,
)

from src.controllers.config_controller import modulos_desligados
from src.controllers.fila_impressao_controller import ServicoFilaImpressao
from src.controllers.telegram_controller import ServicoTelegram
from src.core import licenca, registro
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados, caminho_padrao
from src.sync.ponte import ServicoPonte
from src.ui.contexto import Contexto
from src.ui_qt import tema
from src.ui_qt.login import JanelaLogin
from src.versao import VERSAO


class JanelaBackupExterno(QDialog):
    """A interface só coleta dados; criptografia e restauração pertencem ao controlador."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.exigir_acesso()
        self.setWindowTitle("Backup externo cifrado")
        self.resize(660, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(tema.texto("Proteja uma cópia fora deste PC", "titulo"))
        layout.addWidget(tema.texto(
            "Guarde a senha de recuperação fora deste computador. Sem ela a cópia não pode ser recuperada. "
            "Pasta sincronizada não prova que houve upload; confira no serviço e teste a recuperação.", "aviso"))
        self.situacao = tema.texto("")
        layout.addWidget(self.situacao)
        for titulo, acao in (
            ("Configurar pasta e senha para backup automático", self.configurar),
            ("Exportar cópia cifrada agora", self.exportar),
            ("Verificar uma cópia com a senha de recuperação", self.verificar),
            ("Preparar restauração de cópia cifrada", self.restaurar),
            ("Desativar backup externo automático", self.desativar),
        ):
            botao = QPushButton(titulo)
            botao.clicked.connect(acao)
            layout.addWidget(botao)
        self.mensagem = tema.texto("", "aviso")
        layout.addWidget(self.mensagem)
        self.atualizar()

    def exigir_acesso(self):
        from src.core.erros import ErroPermissao
        if self.ctx.operador is not None:
            cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
            if not cadastro or not cadastro["ativo"]:
                raise ErroPermissao("Operador inativo. Encerre a sessão.")
            self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        if not self.ctx.pode("util_backup"):
            raise ErroPermissao("Seu acesso não permite backup/restauração.")

    def atualizar(self):
        banco = self.ctx.banco
        pasta = banco.cfg("backup_externo_pasta") or "Não configurada"
        ultimo = banco.cfg("backup_externo_ultimo") or "Nenhuma cópia registrada"
        verificado = banco.cfg("backup_externo_verificado_em") or "Sem verificação registrada"
        erro = banco.cfg("backup_externo_erro")
        self.situacao.setText(f"Pasta: {pasta}\nÚltima cópia: {ultimo}\nVerificação: {verificado}"
                             + (f"\nAtenção: {erro}" if erro else ""))

    def _senha(self, confirmar=False):
        senha, aceito = QInputDialog.getText(
            self, "Senha de recuperação", "Digite a senha de recuperação (mínimo 12 caracteres):",
            QLineEdit.EchoMode.Password)
        if not aceito:
            return None
        if len(senha) < 12:
            raise ErroNegocio("A senha de recuperação deve ter no mínimo 12 caracteres.")
        if confirmar:
            repetida, aceito = QInputDialog.getText(
                self, "Confirme a recuperação", "Digite novamente a senha; guarde-a fora deste PC:",
                QLineEdit.EchoMode.Password)
            if not aceito:
                return None
            if senha != repetida:
                raise ErroNegocio("As senhas de recuperação não conferem.")
        return senha

    def _executar(self, acao):
        try:
            self.exigir_acesso()
            acao()
            self.atualizar()
        except (ErroNegocio, OSError, ValueError) as erro:
            self.mensagem.setText(str(erro))

    def configurar(self):
        def acao():
            pasta = QFileDialog.getExistingDirectory(self, "Pasta externa ou sincronizada")
            if not pasta:
                return
            senha = self._senha(confirmar=True)
            if senha is None:
                return
            self.ctx.utilitarios.configurar_backup_externo(pasta, senha)
            self.mensagem.setText("Configuração salva pelo mecanismo protegido do sistema. "
                                  "Guarde a senha fora deste PC; configuração não prova upload.")
        self._executar(acao)

    def exportar(self):
        def acao():
            senha = self._senha(confirmar=True)
            if senha is None:
                return
            destino = self.ctx.utilitarios.backup_externo(senha=senha)
            self.mensagem.setText(f"Cópia cifrada criada: {destino}\nIsto não comprova upload para a nuvem.")
        self._executar(acao)

    def verificar(self):
        def acao():
            caminho, _ = QFileDialog.getOpenFileName(self, "Selecione a cópia cifrada", "", "Todos os arquivos (*)")
            if not caminho:
                return
            senha = self._senha()
            if senha is None:
                return
            self.ctx.utilitarios.verificar_backup_externo(caminho, senha)
            self.mensagem.setText("Cópia verificada com a senha informada. Upload não foi verificado.")
        self._executar(acao)

    def restaurar(self):
        def acao():
            caminho, _ = QFileDialog.getOpenFileName(self, "Cópia cifrada para restauração", "",
                                                    "Todos os arquivos (*)")
            if not caminho:
                return
            senha = self._senha()
            if senha is None:
                return
            confirmacao, aceito = QInputDialog.getText(
                self, "Confirmar restauração", "A cópia substituirá os dados no próximo início. "
                "Digite RESTAURAR para preparar:")
            if not aceito or confirmacao != "RESTAURAR":
                self.mensagem.setText("Restauração não solicitada.")
                return
            self.ctx.utilitarios.pedir_restauracao_externa(caminho, senha)
            self.mensagem.setText("Restauração preparada. Encerre o programa e abra novamente; "
                                  "a proteção inicial fará a troca. O banco aberto ainda não foi substituído.")
        self._executar(acao)

    def desativar(self):
        def acao():
            if QMessageBox.question(
                    self, "Desativar backup externo", "Desativar novas cópias automáticas externas?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            self.ctx.utilitarios.desativar_backup_externo()
            self.mensagem.setText("Backup externo automático desativado. Cópias existentes não foram apagadas.")
        self._executar(acao)


class JanelaPrincipal(QMainWindow):
    CADASTROS_QT = (
        ("unidades", "Unidades"), ("grupos", "Grupos"), ("subgrupos", "Subgrupos"),
        ("observacoes", "Observações"), ("cargos", "Cargos"), ("fornecedores", "Fornecedores"),
        ("clientes", "Clientes"), ("garotas", "Garotas"), ("bairros", "Bairros e taxas de entrega"),
        ("tipos_pagamento", "Tipos de pagamento"), ("planos_contas", "Plano de contas"),
        ("subplanos", "Subplanos"), ("aliquotas", "Alíquotas"),
        ("setores_impressao", "Setores de impressão"),
    )

    def __init__(self, app):
        super().__init__()
        self.app, self.ctx = app, app.ctx
        self.janelas = {}
        self._atualizacoes = None
        self._fechamento_autorizado = False
        self.setWindowTitle(f"WillPDV • {self.ctx.config.nome_loja()} • Qt piloto")
        self.resize(1180, 760)
        self.setMinimumSize(850, 600)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        lateral = QVBoxLayout()
        lateral.addWidget(tema.texto("WILLPDV", "marca"))
        lateral.addWidget(tema.texto(f"Versão {VERSAO}\nInterface Qt • piloto", "suave"))
        self.busca_modulos = QLineEdit()
        self.busca_modulos.setPlaceholderText("Buscar módulo…")
        self.busca_modulos.setClearButtonEnabled(True)
        self.busca_modulos.setAccessibleName("Buscar módulo do PDV")
        lateral.addWidget(self.busca_modulos)
        self.botoes = {}
        for chave, titulo, acao in (
            ("inicio", "Visão geral", self.atualizar),
            ("caixa", "Abrir caixa", self.abrir_caixa),
            ("produtos", "Produtos", lambda: self.abrir_cadastro("produtos")),
            ("estoque", "Estoque", self.abrir_estoque),
            ("retornaveis", "Retornáveis por cliente", self.abrir_retornaveis),
            ("promocoes", "Promoções e faixas", self.abrir_promocoes),
            ("alertas", "Alertas da operação", self.abrir_alertas),
            ("cozinha", "Cozinha / Bar", self.abrir_cozinha),
            ("relatorio_vendas", "Vendas • relatório", self.abrir_relatorio_vendas),
            ("relatorios", "Mais relatórios", self.abrir_relatorios),
            ("contas", "Contas a pagar / receber", self.abrir_contas),
            ("operadores", "Operadores", lambda: self.abrir_cadastro("operadores")),
            ("mais_cadastros", "Mais cadastros", self.escolher_cadastro_adicional),
            ("configuracoes", "Configurações gerais", self.abrir_configuracoes),
            ("maquinas", "Máquinas e periféricos", self.abrir_maquinas),
            ("acessos", "Níveis de acesso", self.abrir_acessos),
            ("telegram", "Telegram do dono", self.abrir_telegram),
            ("utilitarios", "Utilitários e manutenção", self.abrir_utilitarios),
            ("atualizacoes", "Atualizações do programa", self.abrir_atualizacoes),
            ("importar_produtos", "Importar produtos", self.abrir_importacao_produtos),
            ("auditoria", "Auditoria • somente leitura", self.abrir_auditoria),
            ("backup", "Backup externo cifrado", self.abrir_backup),
            ("restaurar", "Restaurar backup local", self.abrir_restaurar_backup),
            ("impressora", "Assistente de impressora", self.abrir_assistente_impressora),
            ("fila_impressao", "Fila de impressão", self.abrir_fila_impressao),
            ("composicao", "Composição / ficha técnica", self.abrir_composicao),
            ("outros", "Escopo e homologação", self.mostrar_limites),
        ):
            botao = QPushButton(titulo)
            botao.clicked.connect(acao)
            self.botoes[chave] = botao
            lateral.addWidget(botao)
        self.busca_modulos.textChanged.connect(self.filtrar_modulos)
        lateral.addStretch()
        self.sessao = tema.texto("", "suave")
        lateral.addWidget(self.sessao)
        sair = QPushButton("Encerrar sessão")
        sair.clicked.connect(lambda: self.app.encerrar_sessao(confirmar=True))
        lateral.addWidget(sair)
        lateral_widget = QWidget()
        lateral_widget.setLayout(lateral)
        self.lateral_scroll = QScrollArea()
        self.lateral_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.lateral_scroll.setWidgetResizable(True)
        self.lateral_scroll.setWidget(lateral_widget)
        layout.addWidget(self.lateral_scroll, 1)
        conteudo = QVBoxLayout()
        conteudo.setContentsMargins(24, 12, 12, 12)
        conteudo.addWidget(tema.texto("Sua operação, em foco", "titulo"))
        conteudo.addWidget(tema.texto(
            "Validação gradual: Qt e Tk compartilham as regras, não as janelas.", "suave"))
        self.indicadores = {}
        for chave, titulo in (("turno", "CAIXA"), ("licenca", "LICENÇA"),
                              ("backup", "PROTEÇÃO DOS DADOS"), ("sync", "NUVEM E SERVIÇOS")):
            cartao = QFrame()
            cartao.setObjectName("cartao")
            caixa = QVBoxLayout(cartao)
            caixa.setContentsMargins(18, 14, 18, 14)
            caixa.addWidget(tema.texto(titulo, "suave"))
            rotulo = tema.texto("")
            caixa.addWidget(rotulo)
            self.indicadores[chave] = rotulo
            conteudo.addWidget(cartao)
        conteudo.addWidget(tema.texto(
            "Interface em homologação: valide os fluxos em cópia dos dados e com periféricos reais. "
            "O caminho --tk permanece disponível durante a transição. "
            "Não abra duas instâncias sobre o mesmo banco.", "aviso"))
        self.mensagem = tema.texto("", "aviso")
        conteudo.addWidget(self.mensagem)
        self.aviso_atualizacao = tema.texto("", "aviso")
        conteudo.addWidget(self.aviso_atualizacao)
        conteudo.addStretch()
        layout.addLayout(conteudo, 3)
        self._timer = QTimer(self)
        self._timer.setInterval(15000)
        self._timer.timeout.connect(self.atualizar)
        self._timer.start()
        self._primeiro_uso_timer = QTimer(self)
        self._primeiro_uso_timer.setSingleShot(True)
        self._primeiro_uso_timer.timeout.connect(self.oferecer_cadastro_loja)
        self._atualizacoes_timer = QTimer(self)
        self._atualizacoes_timer.setInterval(60000)
        self._atualizacoes_timer.timeout.connect(self.consultar_atualizacoes)
        self.atualizar()

    def atualizar(self):
        if self.ctx.operador is None:
            return
        cadastro = self.ctx.cadastros.obter("operadores", self.ctx.operador_id)
        if cadastro is None or not cadastro["ativo"]:
            self.app.encerrar_sessao()
            return
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        operador = self.ctx.operador
        self.sessao.setText(f"{operador.nome}\nNível {operador.nivel}")
        desligados = modulos_desligados(self.ctx.banco)
        for chave in ("produtos", "operadores"):
            modulo = f"cad_{chave}"
            self.botoes[chave].setEnabled(modulo not in desligados and self.ctx.pode(modulo))
        self.botoes["mais_cadastros"].setEnabled(bool(self._cadastros_disponiveis()))
        self.botoes["estoque"].setEnabled(self.ctx.pode("lanc_estoque"))
        self.botoes["retornaveis"].setEnabled(self.ctx.pode("lanc_estoque"))
        self.botoes["promocoes"].setEnabled(
            "cad_produtos" not in desligados and self.ctx.pode("cad_produtos"))
        self.botoes["alertas"].setEnabled(
            self.ctx.pode("rel_estoque") or self.ctx.pode("rel_informativos"))
        self.botoes["cozinha"].setEnabled(
            "util_cozinha" not in desligados and self.ctx.pode("util_cozinha"))
        self.botoes["relatorio_vendas"].setEnabled(self.ctx.pode("rel_vendas"))
        self.botoes["contas"].setEnabled(self.ctx.pode("lanc_contas"))
        self.botoes["relatorios"].setEnabled(any(
            spec.modulo not in desligados and self.ctx.pode(spec.modulo)
            for spec in self._catalogo_relatorios().values()))
        self.botoes["configuracoes"].setEnabled(
            self.ctx.pode("cfg_loja") or self.ctx.pode("cfg_configuracoes"))
        for chave, modulo in (("maquinas", "cfg_maquinas"), ("acessos", "cfg_acessos"),
                              ("telegram", "cfg_telegram")):
            self.botoes[chave].setEnabled(self.ctx.pode(modulo))
        from src.ui_qt.utilitarios import MODULOS_UTILITARIOS
        self.botoes["utilitarios"].setEnabled(
            any(self.ctx.pode(modulo) for modulo in MODULOS_UTILITARIOS))
        self.botoes["importar_produtos"].setEnabled(
            "cad_produtos" not in desligados and self.ctx.pode("cad_produtos"))
        self.botoes["backup"].setEnabled(self.ctx.pode("util_backup"))
        self.botoes["restaurar"].setEnabled(self.ctx.pode("util_backup"))
        self.botoes["impressora"].setEnabled(self.ctx.pode("cfg_maquinas"))
        self.botoes["fila_impressao"].setEnabled(self.ctx.pode("util_fila_impressao"))
        self.botoes["composicao"].setEnabled(
            "cad_composicao" not in desligados and self.ctx.pode("cad_composicao"))
        self.botoes["auditoria"].setEnabled(
            operador.nivel == 4 and self.ctx.pode("rel_auditoria") and "rel_auditoria" not in desligados)
        turno = self.ctx.turnos.atual()
        self.indicadores["turno"].setText(
            f"Turno {turno['id']} aberto. Operações disponíveis em Abrir caixa."
            if turno else "Nenhum turno aberto. A abertura é feita no caixa.")
        estado = licenca.estado(self.ctx.banco)
        mensagem = estado.mensagem or f"Situação local: {estado.situacao}"
        if estado.bloqueia and licenca.turno_vale_como_isencao(self.ctx.banco, turno):
            mensagem += "\nTurno recente protegido; próxima entrada depende de renovação."
        self.indicadores["licenca"].setText(mensagem)
        if self.ctx.banco.caminho == ":memory:":
            backup = "Banco em memória: backup e serviços de arquivo não iniciados."
        else:
            _, backup = self.ctx.utilitarios.situacao_backup()
        self.indicadores["backup"].setText(backup)
        banco = self.ctx.banco
        from src.sync import ponte
        estado_ponte = ponte.estado(banco)
        configurada = bool(banco.cfg("api_url").strip() and banco.cfg("api_token").strip())
        ultima = (estado_ponte["ultimo_sucesso"] if estado_ponte["ativa"] else
                  banco.cfg("licenca_nuvem_sucesso_em") or banco.cfg("licenca_nuvem_consultada_em"))
        erro = estado_ponte["erro"] if estado_ponte["ativa"] else banco.cfg("licenca_nuvem_erro")
        nuvem = ("Ponte da central ativa (sem envio de vendas)." if estado_ponte["ativa"] else
                 "Nuvem configurada." if configurada else "Nuvem não configurada.")
        nuvem += f"\nÚltima consulta de licença concluída: {ultima}." if ultima else "\nSem consulta de licença concluída."
        if erro:
            nuvem += ("\nFalha na ponte; consulte Configurações ou Suporte no Telegram."
                      if estado_ponte["ativa"] else f"\nÚltima falha de licença: {erro}")
        nuvem += "\nSincronização de vendas: não executada automaticamente pelo piloto."
        if self.app.estado_servicos:
            nuvem += "\n" + " | ".join(self.app.estado_servicos)
        self.indicadores["sync"].setText(nuvem)

    def filtrar_modulos(self, texto):
        from src.database.conexao import normalizar
        busca = normalizar(texto.strip())
        for botao in self.botoes.values():
            botao.setVisible(not busca or busca in normalizar(botao.text()))

    def mostrar_limites(self):
        self.mensagem.setText(
            "Disponível conforme acesso: caixa, cadastros, estoque, relatórios, configurações, máquinas, acessos, "
            "Telegram, alertas, retornáveis, promoções, cozinha/bar, utilitários, importação, ficha técnica, "
            "impressão, backup e restauração. Use a busca lateral para localizar os módulos. "
            "Valide em cópia dos dados. Serviços externos e periféricos indisponíveis não são simulados. "
            "Encerre antes de usar --tk; não há fallback para Tk nem duas instâncias no mesmo banco.")

    def _unica(self, chave, criar):
        janela = self.janelas.get(chave)
        if janela is None:
            janela = criar()
            # Fechar libera formulários e seus segredos; não manter objetos Qt já destruídos.
            from PySide6.QtCore import Qt
            janela.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            janela.destroyed.connect(lambda *_: self.janelas.pop(chave, None))
            self.janelas[chave] = janela
        janela.show()
        janela.raise_()
        janela.activateWindow()
        return janela

    def abrir_caixa(self):
        if self.ctx.operador is None:
            return
        try:
            from src.ui_qt.caixa import JanelaCaixa
            return self._unica("caixa", lambda: JanelaCaixa(self.ctx, self))
        except Exception as erro:
            logging.getLogger("pdv.qt").exception("Falha ao abrir o caixa Qt.")
            self.mensagem.setText(f"Não foi possível abrir o caixa Qt: {erro}. Sem fallback; use --tk.")

    def abrir_estoque(self):
        try:
            from src.ui_qt.estoque import JanelaEstoque
            janela = self.janelas.get("estoque")
            if janela is not None and not janela.atualizar():
                return None
            return self._unica("estoque", lambda: JanelaEstoque(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def _abrir_painel_operacional(self, chave, criar):
        try:
            janela = self.janelas.get(chave)
            if janela is not None:
                janela.exigir_acesso()
            return self._unica(chave, criar)
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_retornaveis(self):
        from src.ui_qt.retornaveis import JanelaRetornaveis
        return self._abrir_painel_operacional(
            "retornaveis", lambda: JanelaRetornaveis(self.ctx, self))

    def abrir_promocoes(self):
        from src.ui_qt.promocoes import JanelaPromocoes
        return self._abrir_painel_operacional(
            "promocoes", lambda: JanelaPromocoes(self.ctx, self))

    def abrir_alertas(self):
        from src.ui_qt.alertas import JanelaAlertas
        return self._abrir_painel_operacional(
            "alertas", lambda: JanelaAlertas(self.ctx, self))

    def abrir_cozinha(self):
        from src.ui_qt.cozinha import JanelaCozinha
        return self._abrir_painel_operacional(
            "cozinha", lambda: JanelaCozinha(self.ctx, self))

    def abrir_contas(self):
        try:
            from src.ui_qt.contas import JanelaContas
            janela = self.janelas.get("contas")
            if janela is not None:
                janela._exigir_acesso()
            return self._unica("contas", lambda: JanelaContas(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_relatorio_vendas(self):
        try:
            from src.ui_qt.relatorio_vendas import JanelaRelatorioVendas
            janela = self.janelas.get("relatorio_vendas")
            if janela is not None and not janela.atualizar():
                return None
            return self._unica(
                "relatorio_vendas", lambda: JanelaRelatorioVendas(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    @staticmethod
    def _catalogo_relatorios():
        from src.ui_qt.relatorios import SPECS
        return SPECS

    def abrir_relatorios(self):
        from PySide6.QtWidgets import QInputDialog
        desligados = modulos_desligados(self.ctx.banco)
        disponiveis = [
            (chave, spec) for chave, spec in self._catalogo_relatorios().items()
            if spec.modulo not in desligados and self.ctx.pode(spec.modulo)
        ]
        if not disponiveis:
            self.mensagem.setText("Seu acesso não permite os relatórios disponíveis.")
            return None
        rotulos = [spec.titulo for _, spec in disponiveis]
        escolhido, aceito = QInputDialog.getItem(
            self, "Relatórios", "Escolha um relatório:", rotulos, 0, False)
        if not aceito:
            return None
        chave = next(chave for chave, spec in disponiveis if spec.titulo == escolhido)
        try:
            from src.ui_qt.relatorios import JanelaRelatorios
            janela = self.janelas.get("relatorios")
            if janela is not None:
                janela.selecao.setCurrentIndex(janela.selecao.findData(chave))
                if not janela.atualizar():
                    return None
                return self._unica("relatorios", lambda: janela)
            return self._unica(
                "relatorios", lambda: JanelaRelatorios(self.ctx, self, chave=chave))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_configuracoes(self):
        try:
            from src.ui_qt.configuracoes import JanelaConfiguracoes
            return self._unica(
                "configuracoes", lambda: JanelaConfiguracoes(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def oferecer_cadastro_loja(self):
        if self.ctx.config.loja_cadastrada() or self.ctx.operador is None:
            return None
        try:
            from src.ui_qt.configuracoes import JanelaCadastroLoja
            janela = self._unica(
                "cadastro_loja", lambda: JanelaCadastroLoja(self.ctx, self))
            janela.accepted.connect(lambda: self.setWindowTitle(
                f"WillPDV • {self.ctx.config.nome_loja()} • Qt piloto"))
            return janela
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_maquinas(self):
        try:
            from src.ui_qt.maquinas import JanelaMaquinas
            janela = self.janelas.get("maquinas")
            if janela is not None:
                janela.exigir_acesso()
            return self._unica("maquinas", lambda: JanelaMaquinas(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_acessos(self):
        try:
            from src.ui_qt.acessos import JanelaAcessos
            janela = self.janelas.get("acessos")
            if janela is not None:
                janela.exigir_acesso()
            return self._unica("acessos", lambda: JanelaAcessos(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_telegram(self):
        try:
            from src.ui_qt.telegram import JanelaTelegram
            janela = self.janelas.get("telegram")
            if janela is not None:
                janela.exigir_acesso()
            return self._unica("telegram", lambda: JanelaTelegram(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_utilitarios(self):
        try:
            from src.ui_qt.utilitarios import JanelaUtilitarios
            janela = self.janelas.get("utilitarios")
            if janela is not None:
                janela.exigir_acesso()
            return self._unica("utilitarios", lambda: JanelaUtilitarios(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def _janela_atualizacoes(self):
        from src.ui_qt.atualizacoes import JanelaAtualizacoes
        if self._atualizacoes is None:
            self._atualizacoes = JanelaAtualizacoes(self.ctx, self)
            self._atualizacoes.aviso_alterado.connect(self._mostrar_aviso_atualizacao)
            self._mostrar_aviso_atualizacao(self._atualizacoes.aviso)
        self._atualizacoes.exigir_acesso()
        return self._atualizacoes

    def _mostrar_aviso_atualizacao(self, aviso):
        self.aviso_atualizacao.setText(
            f"Atualização {aviso['ultima']} disponível. Consulte Atualizações do programa."
            if aviso else "")

    def abrir_atualizacoes(self):
        try:
            janela = self._janela_atualizacoes()
            janela.show()
            janela.raise_()
            janela.activateWindow()
            return janela
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def consultar_atualizacoes(self):
        if self.ctx.banco.caminho == ":memory:":
            return
        try:
            self._janela_atualizacoes().consultar_automaticamente()
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_importacao_produtos(self):
        try:
            from src.ui_qt.importar_produtos import JanelaImportarProdutos
            janela = self.janelas.get("importar_produtos")
            if janela is not None:
                janela._exigir_acesso()
            return self._unica(
                "importar_produtos",
                lambda: JanelaImportarProdutos(self.ctx, self, ao_importar=self._atualizar_produtos))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def _atualizar_produtos(self):
        janela = self.janelas.get("produtos")
        if janela is not None:
            janela.atualizar()

    def abrir_cadastro(self, chave):
        try:
            from src.ui_qt.cadastros import JanelaCadastro, exigir_acesso
            exigir_acesso(self.ctx, chave)
            return self._unica(chave, lambda: JanelaCadastro(self.ctx, chave, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def _cadastros_disponiveis(self):
        desligados = modulos_desligados(self.ctx.banco)
        disponiveis = []
        for chave, rotulo in self.CADASTROS_QT:
            entidade = self.ctx.cadastros.entidade(chave)
            if entidade.modulo not in desligados and self.ctx.pode(entidade.modulo):
                disponiveis.append((chave, rotulo))
        return disponiveis

    def escolher_cadastro_adicional(self):
        from PySide6.QtWidgets import QInputDialog
        disponiveis = self._cadastros_disponiveis()
        if not disponiveis:
            self.mensagem.setText("Seu acesso não permite outros cadastros.")
            return None
        rotulos = [rotulo for _, rotulo in disponiveis]
        escolhido, aceito = QInputDialog.getItem(
            self, "Mais cadastros", "Escolha um cadastro:", rotulos, 0, False)
        if not aceito:
            return None
        chave = next(chave for chave, rotulo in disponiveis if rotulo == escolhido)
        return self.abrir_cadastro(chave)

    def abrir_backup(self):
        try:
            return self._unica("backup", lambda: JanelaBackupExterno(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_assistente_impressora(self):
        try:
            from src.ui_qt.assistente_impressora import JanelaAssistenteImpressora
            return self._unica(
                "assistente_impressora",
                lambda: JanelaAssistenteImpressora(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_restaurar_backup(self):
        try:
            from src.ui_qt.restaurar_backup import JanelaRestaurarBackup
            janela = self.janelas.get("restaurar")
            if janela is not None and not janela.carregar():
                return None
            return self._unica(
                "restaurar", lambda: JanelaRestaurarBackup(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_fila_impressao(self):
        try:
            from src.ui_qt.fila_impressao import JanelaFilaImpressao
            return self._unica(
                "fila_impressao", lambda: JanelaFilaImpressao(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_composicao(self):
        try:
            from src.ui_qt.composicao import JanelaComposicao
            return self._unica(
                "composicao", lambda: JanelaComposicao(self.ctx, parent=self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def abrir_auditoria(self):
        try:
            from src.ui_qt.auditoria import JanelaAuditoria
            # Reabrir uma janela existente também precisa revalidar a sessão no controlador.
            janela = self.janelas.get("auditoria")
            if janela is not None and not janela.atualizar():
                return None
            return self._unica("auditoria", lambda: JanelaAuditoria(self.ctx, self))
        except ErroNegocio as erro:
            self.mensagem.setText(str(erro))

    def fechar_filhos(self):
        for janela in list(self.janelas.values()):
            if not janela.close():
                return False
        self.janelas.clear()
        if self._atualizacoes is not None:
            self._atualizacoes.cancelar_consulta()
            self._atualizacoes.close()
        return True

    def closeEvent(self, evento):
        if self._fechamento_autorizado:
            self._timer.stop()
            self._primeiro_uso_timer.stop()
            self._atualizacoes_timer.stop()
            evento.accept()
        elif self.app.encerrar(confirmar=True):
            evento.accept()
        else:
            evento.ignore()


class App:
    """Coordenação de sessão. Banco injetado pertence ao chamador e não é fechado."""

    def __init__(self, banco=None, aplicacao=None):
        self.aplicacao = aplicacao or QApplication.instance()
        if self.aplicacao is None:
            raise RuntimeError("Crie QApplication antes de construir App.")
        self.banco = banco if banco is not None else BancoDados()
        self._banco_proprio = banco is None
        self.ctx = Contexto(self.banco)
        self.login = None
        self.principal = None
        self.servicos = []
        self.estado_servicos = []
        self._iniciada = False
        self._finalizada = False
        self._servicos_habilitados = False
        self._gancho_anterior = None
        self._gancho = None
        self.aplicacao.aboutToQuit.connect(self.finalizar)

    def iniciar(self, servicos=True):
        if self._iniciada:
            return
        self._iniciada = True
        self._gancho_anterior = sys.excepthook
        self._gancho = self._erro_na_tela
        sys.excepthook = self._gancho
        self._servicos_habilitados = servicos and self.banco.caminho != ":memory:"
        tema.aplicar(self.aplicacao, self.banco.cfg("tema_visual") or "escuro")
        if self._servicos_habilitados:
            idade = self.ctx.utilitarios.idade_backup_horas()
            if idade is None or idade >= 12:
                self.ctx.utilitarios.backup_automatico("início")
            for classe, nome in ((ServicoFilaImpressao, "Impressão"), (ServicoTelegram, "Telegram"),
                                 (ServicoPonte, "Ponte de licenças")):
                servico = None
                try:
                    servico = classe(self.banco.caminho)
                    servico.iniciar()
                    self.servicos.append(servico)
                    self.estado_servicos.append(f"{nome}: serviço iniciado (não confirma entrega)")
                except Exception:
                    if servico is not None:
                        servico.parar()
                    logging.getLogger("pdv.qt").exception("Serviço %s indisponível.", nome)
                    self.estado_servicos.append(f"{nome}: indisponível; veja o log")
        else:
            self.estado_servicos = ["Serviços de arquivo não iniciados"]
        self.entrar()

    def _erro_na_tela(self, tipo, valor, traceback):
        registro.registrar_excecao(tipo, valor, traceback, "tela Qt")
        if not self._finalizada:
            QMessageBox.critical(
                self.principal or self.login, "Erro nesta tela",
                "Ocorreu um erro inesperado. O que já estava gravado foi preservado. "
                "Consulte o log; se repetir, encerre o piloto e use --tk.")

    def entrar(self):
        if self._finalizada:
            return
        self.login = JanelaLogin(self.ctx)
        self.login.accepted.connect(self._autenticado)
        self.login.rejected.connect(self.encerrar)
        self.login.show()

    def _autenticado(self):
        operador = self.login.operador
        if operador is None:
            return
        self.ctx.operador = operador
        self.banco.log("login", operador.nome, operador.id)
        self.login.deleteLater()
        self.login = None
        self.principal = JanelaPrincipal(self)
        self.principal.show()
        if not self.ctx.config.loja_cadastrada() and self.ctx.pode("cfg_loja"):
            self.principal._primeiro_uso_timer.start(150)
        self.principal._atualizacoes_timer.start()
        self.principal.consultar_atualizacoes()
        if operador.so_caixa:
            self.principal.abrir_caixa()

    def encerrar_sessao(self, confirmar=False):
        if self._finalizada or self.ctx.operador is None:
            return False
        if confirmar and QMessageBox.question(
                self.principal, "Encerrar sessão", "Voltar à tela de entrada? O turno não será fechado.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        if self.principal and not self.principal.fechar_filhos():
            return False
        self.banco.log("logout", self.ctx.operador.nome, self.ctx.operador_id)
        self.ctx.operador = None
        if self.principal:
            self.principal._fechamento_autorizado = True
            self.principal.close()
            self.principal.deleteLater()
            self.principal = None
        self.entrar()
        return True

    def encerrar(self, confirmar=False):
        if self._finalizada:
            return True
        if confirmar and QMessageBox.question(
                self.principal, "Fechar WillPDV", "Fechar o programa? O turno aberto será preservado.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        if self.principal and not self.principal.fechar_filhos():
            return False
        self.finalizar()
        self.aplicacao.quit()
        return True

    def finalizar(self):
        if self._finalizada:
            return
        self._finalizada = True
        if self._gancho is not None and sys.excepthook is self._gancho:
            sys.excepthook = self._gancho_anterior
        try:
            if self.login:
                self.login.cancelar_consulta()
                self.login.close()
                self.login.deleteLater()
                self.login = None
            if self.principal:
                self.principal._timer.stop()
                self.principal.fechar_filhos()
                self.principal._fechamento_autorizado = True
                self.principal.close()
                self.principal.deleteLater()
                self.principal = None
            if self.ctx.operador:
                self.banco.log("logout", self.ctx.operador.nome, self.ctx.operador_id)
                self.ctx.operador = None
            if self._servicos_habilitados:
                self.ctx.utilitarios.backup_automatico("saída", minimo_min=60)
        finally:
            for servico in self.servicos:
                try:
                    servico.parar()
                except Exception:
                    logging.getLogger("pdv.qt").exception("Falha ao parar serviço.")
            self.servicos.clear()
            if self._banco_proprio:
                self.banco.fechar()


def preparar_inicio(parent=None):
    """Mesmas APIs de proteção do bootstrap Tk, com perguntas exclusivamente Qt."""
    from src.core.instancia import InstanciaUnica
    from src.database import protecao

    registro.configurar_logs()
    caminho = caminho_padrao()
    trava = InstanciaUnica(caminho)
    if not trava.adquirir():
        QMessageBox.warning(parent, "WillPDV", "O WillPDV já está aberto neste computador. Use a janela existente.")
        return None
    try:
        resultado = protecao.preparar_banco(
            caminho, lambda titulo, mensagem: QMessageBox.question(
                parent, titulo, mensagem, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes)
        if resultado == "cancelado":
            trava.liberar()
            return None
        if resultado == "restaurado":
            QMessageBox.information(parent, "WillPDV", "Backup restaurado. O programa abrirá com os dados dele.")
        return trava
    except BaseException:
        trava.liberar()
        raise


def main():
    """Entrada de produção; nunca continua se a proteção inicial falhar."""
    existente = QApplication.instance()
    aplicacao = existente or QApplication(sys.argv[:1])
    aplicacao.setQuitOnLastWindowClosed(False)
    tema.aplicar(aplicacao)
    trava = None
    app = None
    ciclo_transferido = False
    try:
        trava = preparar_inicio()
        if trava is None:
            return 1
        app = App(aplicacao=aplicacao)
        app.iniciar()
        if existente is not None:
            # O hospedeiro já controla exec(); conserva o ciclo e a trava até aboutToQuit.
            aplicacao._willpdv_qt = app
            aplicacao.aboutToQuit.connect(trava.liberar)
            ciclo_transferido = True
            return 0
        return aplicacao.exec()
    except Exception:
        registro.registrar_excecao(*sys.exc_info(), "início Qt")
        QMessageBox.critical(None, "WillPDV • Falha no início",
                             "Não foi possível iniciar o piloto Qt. Nenhum fallback foi executado. "
                             "Consulte o log e, após encerrar, use --tk.")
        return 1
    finally:
        if not ciclo_transferido:
            try:
                if app is not None:
                    app.finalizar()
            finally:
                if trava is not None:
                    trava.liberar()


def autoteste(pasta: Path) -> list[str]:
    """Contrato do autoteste empacotado; banco efêmero em memória, sem rede/serviços."""
    import os
    from PySide6.QtCore import QCoreApplication, QEvent

    existente = QApplication.instance()
    if existente is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    aplicacao = existente or QApplication([])
    banco = BancoDados(":memory:")
    app = None
    try:
        app = App(banco, aplicacao)
        tema.aplicar(aplicacao)
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        app.principal.show()
        produtos = app.principal.abrir_cadastro("produtos")
        operadores = app.principal.abrir_cadastro("operadores")
        aplicacao.processEvents()
        if not all(janela is not None and janela.isVisible()
                   for janela in (app.principal, produtos, operadores)):
            raise RuntimeError("Uma das janelas Qt não abriu.")
        telas_administrativas = (
            app.principal.abrir_configuracoes, app.principal.abrir_maquinas,
            app.principal.abrir_acessos, app.principal.abrir_telegram,
            app.principal.abrir_utilitarios, app.principal.abrir_atualizacoes,
            app.principal.abrir_estoque,
            app.principal.abrir_alertas, app.principal.abrir_promocoes,
            app.principal.abrir_retornaveis,
        )
        for abrir in telas_administrativas:
            janela = abrir()
            if janela is None or not janela.isVisible():
                raise RuntimeError(f"A tela Qt {abrir.__name__} não abriu.")
        from src.ui_qt.comissao import DialogoAcerto, DialogoComissao
        for chave, valor in (("imprimir_via_comissao", "N"), ("comissao_na_linha", "S"),
                             ("comissao_em_pontos", "N"), ("comissao_pede_shows", "N"),
                             ("posicao_padrao", "comanda"), ("num_comandas", "300")):
            banco.cfg_set(chave, valor)
        # Cenário efêmero: não ativa licença nem altera a exigência do executável comercial.
        from src.core.formatacao import agora
        banco.inserir("turnos", {"numero": 1, "terminal": app.ctx.turnos.terminal,
                                "operador_id": app.ctx.operador_id, "aberto_em": agora(),
                                "valor_inicial_cent": 10000, "status": "aberto"})
        caixa = app.principal.abrir_caixa()
        if caixa is None or not caixa.isVisible():
            raise RuntimeError("O caixa Qt não abriu.")
        caixa.ent_pos.setText("180")
        caixa.btn_chamar.click()
        if caixa.venda_id is None:
            raise RuntimeError("O caixa Qt não abriu a comanda de teste.")
        caixa.ent_codigo.setText(app.ctx.comissoes.codigo())
        caixa.btn_lancar.click()
        if not caixa.modo_comissao or caixa.ent_codigo.text() != "180":
            raise RuntimeError("O código de comissão não ativou o modo na linha.")
        caixa.ent_qtd.setText("15,00")
        caixa.btn_lancar.click()
        if caixa.modo_comissao or app.ctx.comissoes.pendente(180) != 1500:
            raise RuntimeError("A comissão Qt não foi gravada corretamente.")
        painel = caixa.abrir_comissoes()
        if not painel.isVisible() or not painel.selecionar_garota(180):
            raise RuntimeError("A comissão não apareceu no painel Qt.")
        dialogo = DialogoComissao(caixa, app.ctx, "180")
        dialogo.ent_valor.setText("15,00")
        dialogo.gravar()
        if dialogo.resultado != (180, 1500):
            raise RuntimeError("O diálogo Qt de comissão não converteu o valor.")
        acerto = DialogoAcerto(caixa, app.ctx, 180, "", 1500, 1)
        acerto.ent_pix.setText("15,00")
        acerto.confirmar()
        if acerto.resultado != {"do_caixa": False, "shows": 0, "valor_show_cent": 0, "pix_cent": 1500, "vale_cent": 0}:
            raise RuntimeError("O diálogo Qt de acerto não validou o pagamento.")
        caixa.liberar_saida()
        if caixa.venda_id is not None or banco.cfg_int("ultimo_ticket_saida", 0) != 1:
            raise RuntimeError("A saída Qt não liberou a comanda.")
        if app.ctx.comissoes.pendente(180) != 1500:
            raise RuntimeError("A saída alterou indevidamente a comissão pendente.")
        return ["Qt Widgets: menu principal e cadastros de produtos/operadores abrem; "
                "banco em memória, sem rede nem serviços",
                "caixa Qt: comissão na linha, painel, diálogos de comissão/acerto e saída sem consumo conferidos",
                "configurações, máquinas, acessos, Telegram, utilitários, atualizações e estoque abrem sem rede nem hardware"]
    finally:
        if app is not None:
            app.finalizar()
            aplicacao.aboutToQuit.disconnect(app.finalizar)
        aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        banco.fechar()


if __name__ == "__main__":
    sys.exit(main())
