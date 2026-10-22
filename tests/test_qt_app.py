"""Contratos reais do piloto Qt, executados sem servidor gráfico nem banco de loja."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import json
import subprocess
import sys
import time
import unittest
from threading import Event
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QMessageBox

from src.core import licenca
from src.core.erros import ErroNegocio, ErroPermissao
from src.database.conexao import BancoDados
from src.sync.licenca_nuvem import ResultadoConsulta
from src.ui.contexto import Contexto
from src.ui_qt.app import App, JanelaBackupExterno, JanelaPrincipal, autoteste, preparar_inicio
from src.ui_qt.cadastros import FormularioCadastro, JanelaCadastro
from src.ui_qt.auditoria import JanelaAuditoria
from src.ui_qt.assistente_impressora import JanelaAssistenteImpressora
from src.ui_qt.configuracoes import JanelaConfiguracoes
from src.ui_qt.composicao import JanelaComposicao
from src.ui_qt.contas import JanelaContas
from src.ui_qt.estoque import JanelaEstoque
from src.ui_qt.fila_impressao import JanelaFilaImpressao
from src.ui_qt.importar_produtos import JanelaImportarProdutos
from src.ui_qt.relatorio_vendas import JanelaRelatorioVendas
from src.ui_qt.relatorios import JanelaRelatorios
from src.ui_qt.restaurar_backup import JanelaRestaurarBackup
from src.ui_qt.login import JanelaLogin, TrocaSenha


class BaseQt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.banco = BancoDados(":memory:")
        self.ctx = Contexto(self.banco)
        self.janelas = []
        self.apps = []

    def tearDown(self):
        for app in self.apps:
            app.finalizar()
            self.aplicacao.aboutToQuit.disconnect(app.finalizar)
        for janela in reversed(self.janelas):
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.banco.fechar()

    def janela(self, janela):
        self.janelas.append(janela)
        return janela

    def admin(self):
        self.ctx.operador = self.ctx.acesso.autenticar("ADM", "ADM")
        return self.ctx.operador

    def app(self):
        app = App(self.banco, self.aplicacao)
        self.apps.append(app)
        return app

    def aguardar(self, condicao, segundos=3):
        limite = time.monotonic() + segundos
        while not condicao() and time.monotonic() < limite:
            self.aplicacao.processEvents()
            time.sleep(0.005)
        self.assertTrue(condicao(), "O evento Qt não ocorreu dentro do prazo.")


class TestLoginQt(BaseQt):
    def login(self):
        janela = self.janela(JanelaLogin(self.ctx))
        janela.usuario.setCurrentText("ADM")
        return janela

    def test_senha_incorreta_nao_autentica(self):
        janela = self.login()
        janela.senha.setText("errada")
        janela.entrar()
        self.assertIsNone(janela.operador)
        self.assertIn("Senha Incorreta", janela.mensagem.text())
        self.assertTrue(janela.btn_entrar.isEnabled())
        self.assertEqual(janela.senha.text(), "")

    def test_senha_fabrica_nao_pode_ser_cancelada_para_entrar(self):
        janela = self.login()
        janela.senha.setText("ADM")
        with patch.object(TrocaSenha, "exec", return_value=QDialog.DialogCode.Rejected):
            janela.entrar()
        self.assertIsNone(janela.operador)
        self.assertIn("fábrica", janela.mensagem.text())
        self.assertTrue(janela.btn_entrar.isEnabled())

    def test_troca_senha_valida_confirma_e_persiste(self):
        dialogo = self.janela(TrocaSenha(self.ctx, self.admin()))
        dialogo.nova.setText("ADM")
        dialogo.confirmacao.setText("ADM")
        dialogo.salvar()
        self.assertIn("não pode", dialogo.mensagem.text())
        dialogo.nova.setText("Segura123")
        dialogo.confirmacao.setText("Outra123")
        dialogo.salvar()
        self.assertIn("não conferem", dialogo.mensagem.text())
        dialogo.confirmacao.setText("Segura123")
        dialogo.salvar()
        self.assertEqual(dialogo.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.ctx.acesso.autenticar("ADM", "Segura123").id, self.ctx.operador_id)
        self.assertEqual(dialogo.nova.text(), "")

    def test_login_com_senha_trocada(self):
        operador = self.admin()
        self.ctx.acesso.trocar_senha(operador, "Segura123")
        self.ctx.operador = None
        janela = self.login()
        janela.senha.setText("Segura123")
        janela.entrar()
        self.assertEqual(janela.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(janela.operador.id, operador.id)
        self.assertFalse(janela._timer.isActive())

    def test_login_fabrica_conclui_apenas_depois_da_troca_real(self):
        janela = self.login()
        janela.senha.setText("ADM")

        def trocar(dialogo):
            dialogo.nova.setText("Segura123")
            dialogo.confirmacao.setText("Segura123")
            dialogo.salvar()
            return dialogo.result()

        with patch.object(TrocaSenha, "exec", new=trocar):
            janela.entrar()
        self.assertEqual(janela.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.ctx.acesso.autenticar("ADM", "Segura123").id, janela.operador.id)

    def test_licenca_exigida_sem_codigo_bloqueia_antes_de_autenticar(self):
        self.banco.cfg_set("licenca_exigir", "S")
        janela = self.login()
        janela.senha.setText("ADM")
        with patch.object(self.ctx.acesso, "autenticar", wraps=self.ctx.acesso.autenticar) as autenticar:
            janela.entrar()
        autenticar.assert_not_called()
        self.assertIsNone(janela.operador)
        self.assertIn("licença", janela.mensagem.text().lower())

    def test_licenca_bloqueada_preserva_isencao_de_turno(self):
        self.ctx.acesso.trocar_senha(self.admin(), "Segura123")
        janela = self.login()
        janela.senha.setText("Segura123")
        with patch("src.ui_qt.login.licenca.estado",
                   return_value=licenca.Estado("bloqueada", mensagem="Licença vencida")), \
                patch("src.ui_qt.login.licenca.turno_vale_como_isencao", return_value=True) as isencao:
            janela.entrar()
        isencao.assert_called_once_with(self.banco, self.ctx.turnos.atual())
        self.assertEqual(janela.result(), QDialog.DialogCode.Accepted)

    def test_rede_nao_bloqueia_loop_nem_usa_banco_na_thread(self):
        self.banco.cfg_set("licenca_exigir", "S")
        self.banco.cfg_set("api_url", "https://exemplo.invalid")
        self.banco.cfg_set("api_token", "token-teste")
        janela = self.login()
        liberar = Event()
        chamada = Event()
        pulso = []

        def consultar(*args, **kwargs):
            chamada.set()
            liberar.wait(2)
            return ResultadoConsulta(False, erro="Sem rede no teste")

        try:
            with patch("src.ui_qt.login.licenca_nuvem.consultar_resultado", side_effect=consultar):
                janela.entrar()
                self.assertTrue(chamada.wait(1))
                QTimer.singleShot(0, lambda: pulso.append(True))
                self.aplicacao.processEvents()
                self.assertTrue(pulso)
                self.assertFalse(janela.btn_entrar.isEnabled())
                liberar.set()
                self.aguardar(lambda: not janela._ocupada)
            self.assertIn("Sem rede no teste", self.banco.cfg("licenca_nuvem_erro"))
            self.assertIsNone(janela.operador)
        finally:
            liberar.set()
            if janela._thread:
                janela._thread.join(2)

    def test_fechar_cancela_timer_e_descarta_resposta_tardia(self):
        self.banco.cfg_set("licenca_exigir", "S")
        self.banco.cfg_set("api_url", "https://exemplo.invalid")
        self.banco.cfg_set("api_token", "token-teste")
        janela = self.login()
        liberar = Event()
        try:
            with patch("src.ui_qt.login.licenca_nuvem.consultar_resultado",
                       side_effect=lambda *a, **k: (liberar.wait(2), ResultadoConsulta(True))[1]):
                janela.entrar()
                janela.close()
                self.assertTrue(janela._cancelamento.is_set())
                self.assertFalse(janela._timer.isActive())
                liberar.set()
                janela._thread.join(2)
                janela._receber_licenca()
            self.assertEqual(self.banco.cfg("licenca_nuvem_sucesso_em"), "")
            self.assertIsNone(janela.operador)
        finally:
            liberar.set()
            if janela._thread:
                janela._thread.join(2)

    def test_ativacao_invalida_nao_muda_licenca(self):
        janela = self.login()
        with patch("src.ui_qt.login.QInputDialog.getMultiLineText", return_value=("invalida", True)):
            janela.pedir_licenca()
        self.assertEqual(self.banco.cfg("licenca_token"), "")
        self.assertIsNone(janela.operador)


class TestCadastrosQt(BaseQt):
    def setUp(self):
        super().setUp()
        self.admin()

    def test_produto_criado_e_preco_convertido_pelo_controller(self):
        formulario = self.janela(FormularioCadastro(self.ctx, "produtos"))
        formulario.campos["subgrupo_id"].setCurrentIndex(1)
        formulario.campos["unidade_id"].setCurrentIndex(1)
        formulario.campos["nome"].setText("Produto Qt")
        formulario.campos["preco_cent"].setText("12,34")
        formulario.salvar()
        self.assertEqual(formulario.result(), QDialog.DialogCode.Accepted, formulario.mensagem.text())
        produto = self.ctx.cadastros.obter("produtos", formulario.id_)
        self.assertEqual(produto["preco_cent"], 1234)
        self.assertIsInstance(produto["preco_cent"], int)
        self.assertEqual(produto["nome"], "Produto Qt")

    def test_validacao_controller_impede_preco_negativo(self):
        formulario = self.janela(FormularioCadastro(self.ctx, "produtos"))
        formulario.campos["subgrupo_id"].setCurrentIndex(1)
        formulario.campos["unidade_id"].setCurrentIndex(1)
        formulario.campos["nome"].setText("Produto Qt")
        formulario.campos["preco_cent"].setText("-1,00")
        formulario.salvar()
        self.assertNotEqual(formulario.result(), QDialog.DialogCode.Accepted)
        self.assertIn("negativo", formulario.mensagem.text())
        self.assertEqual(self.ctx.cadastros.listar("produtos"), [])

    def test_edicao_produto_preserva_id_e_valores(self):
        id_ = self.ctx.cadastros.salvar("produtos", {"codigo": "8", "nome": "Inicial", "preco_cent": "3,50",
                                                  "subgrupo_id": 1, "unidade_id": 1})
        formulario = self.janela(FormularioCadastro(self.ctx, "produtos", id_))
        self.assertEqual(formulario.campos["preco_cent"].text(), "3,50")
        formulario.campos["nome"].setText("Alterado Qt")
        formulario.salvar()
        self.assertEqual(formulario.id_, id_)
        self.assertEqual(self.ctx.cadastros.obter("produtos", id_)["nome"], "Alterado Qt")

    def test_operador_criado_com_hash_e_grade_sem_senha(self):
        formulario = self.janela(FormularioCadastro(self.ctx, "operadores"))
        formulario.campos["nome"].setText("CAIXA")
        formulario.campos["senha"].setText("Segura123")
        formulario.salvar()
        self.assertEqual(formulario.result(), QDialog.DialogCode.Accepted, formulario.mensagem.text())
        self.assertEqual(self.ctx.acesso.autenticar("CAIXA", "Segura123").nivel, 0)
        cadastro = self.janela(JanelaCadastro(self.ctx, "operadores"))
        self.assertNotIn("senha", [c.nome for c in cadastro.colunas])
        self.assertEqual(formulario.campos["senha"].text(), "")

    def test_edicao_operador_em_branco_mantem_senha(self):
        id_ = self.ctx.operador_id
        formulario = self.janela(FormularioCadastro(self.ctx, "operadores", id_))
        self.assertEqual(formulario.campos["senha"].text(), "")
        formulario.salvar()
        self.assertEqual(formulario.result(), QDialog.DialogCode.Accepted, formulario.mensagem.text())
        self.assertEqual(self.ctx.acesso.autenticar("ADM", "ADM").id, id_)

    def test_unico_administrador_nao_pode_ser_rebaixado(self):
        formulario = self.janela(FormularioCadastro(self.ctx, "operadores", self.ctx.operador_id))
        formulario.campos["nivel"].setCurrentIndex(formulario.campos["nivel"].findData(0))
        formulario.salvar()
        self.assertIn("ao menos um", formulario.mensagem.text())
        self.assertEqual(self.ctx.acesso.operador(self.ctx.operador_id).nivel, 4)

    def test_nivel_caixa_nao_abre_cadastro_por_chamada_direta(self):
        id_ = self.ctx.cadastros.salvar("operadores", {"nome": "CAIXA", "senha": "Segura123", "nivel": 0})
        self.ctx.operador = self.ctx.acesso.operador(id_)
        with self.assertRaises(ErroPermissao):
            JanelaCadastro(self.ctx, "produtos")
        with self.assertRaises(ErroPermissao):
            FormularioCadastro(self.ctx, "operadores")

    def test_revogacao_de_acesso_impede_salvar_formulario_ja_aberto(self):
        id_ = self.ctx.cadastros.salvar("operadores", {"nome": "SUP", "senha": "Segura123", "nivel": 3})
        self.ctx.operador = self.ctx.acesso.operador(id_)
        formulario = self.janela(FormularioCadastro(self.ctx, "produtos"))
        formulario.campos["nome"].setText("Produto sem acesso")
        self.ctx.cadastros.salvar("operadores", {"nivel": 0}, id_)
        formulario.salvar()
        self.assertIn("acesso", formulario.mensagem.text())
        self.assertEqual(self.ctx.cadastros.listar("produtos"), [])

    def test_cadastro_adicional_reutiliza_formulario_e_permissao_do_controller(self):
        self.banco.cfg_set("usar_caderneta", "1")
        janela = self.janela(JanelaCadastro(self.ctx, "clientes"))
        self.assertEqual(janela.chave, "clientes")
        self.assertIn("Cliente", janela.windowTitle())

    def test_todas_as_entidades_genericas_adicionais_abrem_no_qt(self):
        from src.ui_qt.app import JanelaPrincipal
        self.banco.cfg_set("usar_caderneta", "1")
        self.banco.cfg_set("usar_delivery", "1")
        self.banco.cfg_set("usar_contas", "1")
        self.banco.cfg_set("usar_cozinha_bar", "1")
        for chave, _rotulo in JanelaPrincipal.CADASTROS_QT:
            with self.subTest(cadastro=chave):
                janela = self.janela(JanelaCadastro(self.ctx, chave))
                self.assertEqual(janela.chave, chave)


class TestAppQt(BaseQt):
    def test_tema_carrega_fontes_legiveis_no_plugin_offscreen(self):
        from PySide6.QtGui import QFontDatabase
        from src.ui_qt import tema
        tema.aplicar(self.aplicacao)
        self.assertTrue(QFontDatabase.families(), "Qt precisa de fonte para mostrar textos legíveis.")

    def test_autoteste_empacotado_abre_e_fecha_janelas_reais(self):
        janelas_antes = set(self.aplicacao.topLevelWidgets())
        resultado = autoteste(Path.cwd())
        self.assertIn("Qt Widgets", resultado[0])
        self.assertIn("comissão na linha", resultado[1])
        self.assertFalse(any(j.isVisible() for j in set(self.aplicacao.topLevelWidgets()) - janelas_antes))

    def test_banco_memoria_e_qapplication_existente_sem_servicos(self):
        app = self.app()
        with patch("src.ui_qt.app.ServicoFilaImpressao") as impressao, \
                patch("src.ui_qt.app.ServicoTelegram") as telegram, \
                patch("src.ui_qt.app.ServicoPonte") as ponte, \
                patch("src.controllers.utilitario_controller.UtilitarioController.backup_automatico") as backup:
            app.iniciar()
            self.assertIs(app.aplicacao, self.aplicacao)
            self.assertTrue(app.login.isVisible())
            app.finalizar()
        impressao.assert_not_called()
        telegram.assert_not_called()
        backup.assert_not_called()
        self.assertEqual(self.banco.valor("SELECT 1"), 1)

    def test_sessao_abre_principal_e_volta_ao_login(self):
        app = self.app()
        app.iniciar(servicos=False)
        operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.ctx.acesso.trocar_senha(operador, "Segura123")
        app.login.senha.setText("Segura123")
        app.login.entrar()
        self.assertIsNotNone(app.principal)
        self.assertIsNone(app.login)
        self.assertEqual(app.ctx.operador.nome, "ADM")
        principal = app.principal
        self.assertTrue(app.encerrar_sessao())
        self.assertIsNone(app.ctx.operador)
        self.assertTrue(app.login.isVisible())
        self.assertFalse(principal._timer.isActive())

    def test_principal_exibe_status_honesto_e_limites(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        principal = app.principal
        self.assertIn("memória", principal.indicadores["backup"].text())
        self.assertIn("não configurada", principal.indicadores["sync"].text())
        self.assertIn("não executada automaticamente", principal.indicadores["sync"].text())
        principal.mostrar_limites()
        self.assertIn("--tk", principal.mensagem.text())
        self.assertIn("indisponíveis", principal.mensagem.text())

    def test_menu_admin_abre_contas_unica_e_fecha_na_sessao(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        self.assertTrue(app.principal.botoes["contas"].isEnabled())
        janela = app.principal.abrir_contas()
        self.assertIsInstance(janela, JanelaContas)
        self.assertIs(app.principal.abrir_contas(), janela)
        self.assertIs(app.principal.janelas["contas"], janela)
        self.assertTrue(app.principal.fechar_filhos())
        self.assertNotIn("contas", app.principal.janelas)

    def test_menu_contas_revalida_permissao_na_reabertura(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        janela = app.principal.abrir_contas()
        self.assertIsNotNone(janela)
        self.banco.executar("UPDATE operadores SET nivel = 2 WHERE id = ?", (app.ctx.operador_id,))
        self.ctx.acesso.alterar_nivel_modulo("lanc_contas", 3)
        self.assertIsNone(app.principal.abrir_contas())
        self.assertIn("acesso", app.principal.mensagem.text().lower())

    def test_menu_novas_configuracoes_utilitarios_e_janelas_unicas(self):
        from src.ui_qt.acessos import JanelaAcessos
        from src.ui_qt.maquinas import JanelaMaquinas
        from src.ui_qt.telegram import JanelaTelegram
        from src.ui_qt.utilitarios import JanelaUtilitarios
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        for chave, classe in (("maquinas", JanelaMaquinas), ("acessos", JanelaAcessos),
                              ("telegram", JanelaTelegram), ("utilitarios", JanelaUtilitarios)):
            with self.subTest(tela=chave):
                self.assertTrue(app.principal.botoes[chave].isEnabled())
                abrir = getattr(app.principal, f"abrir_{chave}")
                janela = abrir()
                self.assertIsInstance(janela, classe)
                self.assertIs(abrir(), janela)
                self.assertTrue(janela.isVisible())
        self.assertTrue(app.principal.fechar_filhos())
        self.assertEqual(app.principal.janelas, {})

    def test_menu_novas_telas_revalida_inativacao_ao_reabrir(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        for chave in ("maquinas", "acessos", "telegram", "utilitarios"):
            abrir = getattr(app.principal, f"abrir_{chave}")
            with self.subTest(tela=chave):
                self.banco.executar("UPDATE operadores SET ativo = 1 WHERE id = ?", (app.ctx.operador_id,))
                self.assertIsNotNone(abrir())
                self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (app.ctx.operador_id,))
                self.assertIsNone(abrir())
                self.assertIn("inativo", app.principal.mensagem.text().lower())

    def test_aplicativo_aplica_tema_claro_persistido_ao_iniciar(self):
        self.banco.cfg_set("tema_visual", "claro")
        app = self.app()
        app.iniciar(servicos=False)
        self.assertIn("#f3f6fa", self.aplicacao.styleSheet())
        from src.ui_qt import tema
        tema.aplicar(self.aplicacao)

    def test_convite_cadastro_loja_adia_sem_gravar_e_nao_reabre_ja_cadastrada(self):
        from src.ui_qt.configuracoes import JanelaCadastroLoja
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        janela = app.principal.oferecer_cadastro_loja()
        self.assertIsInstance(janela, JanelaCadastroLoja)
        janela.close()
        self.assertFalse(app.ctx.config.loja_cadastrada())
        app.ctx.config.cadastrar_loja({"nome_fantasia": "Casa"})
        self.assertIsNone(app.principal.oferecer_cadastro_loja())

    def test_atualizacoes_janela_reutilizada_e_cancelada_no_logout(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        with patch("src.ui_qt.atualizacoes.atualizacoes.consultar") as rede:
            janela = app.principal.abrir_atualizacoes()
            self.assertIs(app.principal.abrir_atualizacoes(), janela)
            app.principal.consultar_atualizacoes()
            rede.assert_not_called()
        self.assertTrue(app.principal.fechar_filhos())
        self.assertIsNone(janela._solicitacao)
        self.assertFalse(janela.isVisible())

    def test_caixa_import_local_nao_bloqueante_e_referencia_retida(self):
        import types
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        chamadas = []

        class CaixaFalso(QMainWindow):
            def __init__(self, ctx, parent=None):
                super().__init__(parent)
                chamadas.append((ctx, parent))

        modulo = types.ModuleType("src.ui_qt.caixa")
        modulo.JanelaCaixa = CaixaFalso
        with patch.dict(sys.modules, {"src.ui_qt.caixa": modulo}):
            janela = app.principal.abrir_caixa()
            self.assertTrue(janela.isVisible())
            self.assertIs(app.principal.janelas["caixa"], janela)
            self.assertIs(app.principal.abrir_caixa(), janela)
        self.assertEqual(chamadas, [(app.ctx, app.principal)])

    def test_filho_que_recusa_fechar_impede_logout(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        filho = MagicMock()
        filho.close.return_value = False
        app.principal.janelas["caixa"] = filho
        self.assertFalse(app.encerrar_sessao())
        self.assertIsNotNone(app.ctx.operador)
        filho.close.return_value = True

    def test_ciclo_arquivo_faz_backups_e_para_servicos(self):
        app = self.app()
        self.banco.caminho = "somente-teste-qt.db"
        try:
            with patch("src.ui_qt.app.ServicoFilaImpressao") as impressao, \
                    patch("src.ui_qt.app.ServicoTelegram") as telegram, \
                    patch("src.ui_qt.app.ServicoPonte") as ponte, \
                    patch("src.controllers.utilitario_controller.UtilitarioController.idade_backup_horas",
                          return_value=None), \
                    patch("src.controllers.utilitario_controller.UtilitarioController.backup_automatico") as backup:
                app.iniciar()
                impressao.return_value.iniciar.assert_called_once()
                telegram.return_value.iniciar.assert_called_once()
                ponte.return_value.iniciar.assert_called_once()
                app.finalizar()
                impressao.return_value.parar.assert_called_once()
                telegram.return_value.parar.assert_called_once()
                ponte.return_value.parar.assert_called_once()
                self.assertEqual(backup.call_count, 2)
                backup.assert_any_call("início")
                backup.assert_any_call("saída", minimo_min=60)
        finally:
            self.banco.caminho = ":memory:"

    def test_bootstrap_nao_prepara_banco_se_instancia_ja_existe(self):
        with patch("src.core.instancia.InstanciaUnica") as classe, \
                patch("src.ui_qt.app.registro.configurar_logs"), \
                patch("src.database.protecao.preparar_banco") as preparar, \
                patch.object(QMessageBox, "warning"):
            classe.return_value.adquirir.return_value = False
            self.assertIsNone(preparar_inicio())
        preparar.assert_not_called()

    def test_bootstrap_libera_trava_se_integridade_falha(self):
        with patch("src.core.instancia.InstanciaUnica") as classe, \
                patch("src.ui_qt.app.registro.configurar_logs"), \
                patch("src.database.protecao.preparar_banco", side_effect=OSError("Falha no banco")):
            with self.assertRaises(OSError):
                preparar_inicio()
        classe.return_value.liberar.assert_called_once()

    def test_import_e_janelas_qt_nao_carregam_tk(self):
        codigo = (
            "import sys; from PySide6.QtWidgets import QApplication; "
            "from src.database.conexao import BancoDados; from src.ui_qt.app import App; "
            "q=QApplication([]); q.setQuitOnLastWindowClosed(False); b=BancoDados(':memory:'); "
            "a=App(b,q); a.iniciar(servicos=False); a.finalizar(); q.processEvents(); b.fechar(); "
            "assert 'tkinter' not in sys.modules, 'Qt carregou Tk'"
        )
        resultado = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True,
                                   timeout=30, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        self.assertEqual(resultado.returncode, 0, resultado.stderr)


class TestBackupExternoQt(BaseQt):
    def setUp(self):
        super().setUp()
        self.admin()
        self.backup = self.janela(JanelaBackupExterno(self.ctx))

    def test_configuracao_exige_senha_longa_confirmada_e_so_chama_controller(self):
        senha = "Recuperacao123!"
        with patch("src.ui_qt.app.QFileDialog.getExistingDirectory", return_value="C:\\BackupTeste"), \
                patch("src.ui_qt.app.QInputDialog.getText", side_effect=[(senha, True), (senha, True)]), \
                patch("src.controllers.utilitario_controller.UtilitarioController.configurar_backup_externo") as salvar:
            self.backup.configurar()
        salvar.assert_called_once_with("C:\\BackupTeste", senha)
        self.assertIn("não prova upload", self.backup.mensagem.text())
        self.assertFalse(any(senha in str(r["valor"]) for r in self.banco.todos("SELECT valor FROM config")))

    def test_senha_curta_nao_configura_backup(self):
        with patch("src.ui_qt.app.QFileDialog.getExistingDirectory", return_value="C:\\BackupTeste"), \
                patch("src.ui_qt.app.QInputDialog.getText", return_value=("curta", True)), \
                patch("src.controllers.utilitario_controller.UtilitarioController.configurar_backup_externo") as salvar:
            self.backup.configurar()
        salvar.assert_not_called()
        self.assertIn("12 caracteres", self.backup.mensagem.text())

    def test_confirmacao_diferente_nao_exporta(self):
        with patch("src.ui_qt.app.QInputDialog.getText",
                   side_effect=[("Recuperacao123!", True), ("OutraSenha1234!", True)]), \
                patch("src.controllers.utilitario_controller.UtilitarioController.backup_externo") as exportar:
            self.backup.exportar()
        exportar.assert_not_called()
        self.assertIn("não conferem", self.backup.mensagem.text())

    def test_exportacao_manual_nao_afirma_upload(self):
        senha = "Recuperacao123!"
        with patch("src.ui_qt.app.QInputDialog.getText", side_effect=[(senha, True), (senha, True)]), \
                patch("src.controllers.utilitario_controller.UtilitarioController.backup_externo",
                      return_value="C:\\BackupTeste\\copia.pdvbkp") as exportar:
            self.backup.exportar()
        exportar.assert_called_once_with(senha=senha)
        self.assertIn("não comprova upload", self.backup.mensagem.text())

    def test_verificacao_incorreta_nao_mostra_sucesso(self):
        with patch("src.ui_qt.app.QFileDialog.getOpenFileName", return_value=("copia.pdvbkp", "")), \
                patch("src.ui_qt.app.QInputDialog.getText", return_value=("Recuperacao123!", True)), \
                patch("src.controllers.utilitario_controller.UtilitarioController.verificar_backup_externo",
                      side_effect=ErroNegocio("Senha inválida.")):
            self.backup.verificar()
        self.assertEqual(self.backup.mensagem.text(), "Senha inválida.")

    def test_restauracao_exige_confirmacao_digitada_e_delega_agendamento(self):
        with patch("src.ui_qt.app.QFileDialog.getOpenFileName", return_value=("copia.pdvbkp", "")), \
                patch("src.ui_qt.app.QInputDialog.getText",
                      side_effect=[("Recuperacao123!", True), ("RESTAURAR", True)]), \
                patch("src.controllers.utilitario_controller.UtilitarioController.pedir_restauracao_externa") as pedir:
            self.backup.restaurar()
        pedir.assert_called_once_with("copia.pdvbkp", "Recuperacao123!")
        self.assertIn("ainda não foi substituído", self.backup.mensagem.text())

    def test_restauracao_sem_confirmacao_nao_e_agendada(self):
        with patch("src.ui_qt.app.QFileDialog.getOpenFileName", return_value=("copia.pdvbkp", "")), \
                patch("src.ui_qt.app.QInputDialog.getText",
                      side_effect=[("Recuperacao123!", True), ("sim", True)]), \
                patch("src.controllers.utilitario_controller.UtilitarioController.pedir_restauracao_externa") as pedir:
            self.backup.restaurar()
        pedir.assert_not_called()
        self.assertIn("não solicitada", self.backup.mensagem.text())

    def test_permissao_e_conferida_novamente_antes_de_exportar(self):
        id_ = self.ctx.cadastros.salvar("operadores", {"nome": "CAIXA", "senha": "Segura123", "nivel": 0})
        self.ctx.operador = self.ctx.acesso.operador(id_)
        with patch("src.controllers.utilitario_controller.UtilitarioController.backup_externo") as exportar:
            self.backup.exportar()
        exportar.assert_not_called()
        self.assertIn("acesso", self.backup.mensagem.text())


class TestAuditoriaQt(BaseQt):
    def setUp(self):
        super().setUp()
        self.admin()

    def evento(self, quando="2026-10-16 12:30:00", acao="preco_alterado", antes=None, depois=None):
        return self.banco.inserir("auditoria_eventos", {
            "quando": quando, "operador_id": self.ctx.operador_id, "origem": "operador",
            "entidade": "produtos", "entidade_id": "8", "acao": acao,
            "antes": json.dumps(antes, ensure_ascii=False) if antes is not None else None,
            "depois": json.dumps(depois, ensure_ascii=False) if depois is not None else None,
        })

    def auditoria(self):
        return self.janela(JanelaAuditoria(self.ctx))

    def test_consulta_somente_leitura_mostra_retratos_reais(self):
        id_ = self.ctx.cadastros.salvar("produtos", {
            "codigo": "8", "nome": "Café", "preco_cent": "3,50", "subgrupo_id": 1, "unidade_id": 1})
        self.ctx.cadastros.salvar("produtos", {"preco_cent": "4,20"}, id_)
        antes = self.banco.conexao.total_changes
        janela = self.auditoria()
        janela.grade.selectRow(0)
        self.assertEqual(janela.eventos[0]["acao"], "preco_alterado")
        self.assertEqual(json.loads(janela.antes.toPlainText())["preco_cent"], 350)
        self.assertEqual(json.loads(janela.depois.toPlainText())["preco_cent"], 420)
        self.assertTrue(janela.antes.isReadOnly())
        self.assertTrue(janela.depois.isReadOnly())
        self.assertEqual(janela.grade.editTriggers(), janela.grade.EditTrigger.NoEditTriggers)
        self.assertEqual(self.banco.conexao.total_changes, antes)

    def test_paginacao_100_preserva_filtros_e_ordem(self):
        for numero in range(102):
            self.evento(depois={"numero": numero})
        janela = self.auditoria()
        self.assertEqual(len(janela.eventos), 100)
        self.assertEqual(janela.eventos[0]["depois"]["numero"], 101)
        self.assertFalse(janela.anterior.isEnabled())
        self.assertTrue(janela.proxima.isEnabled())
        janela.proxima_pagina()
        self.assertEqual(janela.offset, 100)
        self.assertEqual(len(janela.eventos), 2)
        self.assertEqual(janela.eventos[0]["depois"]["numero"], 1)
        self.assertFalse(janela.proxima.isEnabled())
        self.assertTrue(janela.anterior.isEnabled())
        janela.pagina_anterior()
        self.assertEqual(janela.offset, 0)
        self.assertEqual(len(janela.eventos), 100)
        janela.acao.setCurrentIndex(janela.acao.findData("exclusao"))
        janela.filtrar()
        self.assertEqual(janela.offset, 0)
        self.assertEqual(janela.eventos, [])
        self.assertIn("0 evento", janela.paginacao.text())

    def test_filtros_inclusivos_periodo_e_acao(self):
        self.evento("2026-10-15 23:59:59")
        esperado = self.evento("2026-10-16 23:59:59")
        self.evento("2026-10-17 00:00:00")
        self.evento("2026-10-16 10:00:00", acao="cadastro")
        janela = self.auditoria()
        janela.inicio.setText("2026-10-16")
        janela.fim.setText("2026-10-16")
        janela.acao.setCurrentIndex(janela.acao.findData("preco_alterado"))
        janela.filtrar()
        self.assertEqual([e["id"] for e in janela.eventos], [esperado])
        self.assertEqual(janela._filtros["acao"], "preco_alterado")

    def test_acao_digitada_e_periodo_invalido_sao_tratados(self):
        self.evento(acao="acao_futura")
        janela = self.auditoria()
        janela.acao.setEditText("acao_futura")
        janela.filtrar()
        self.assertEqual(len(janela.eventos), 1)
        janela.inicio.setText("16/10/2026")
        janela.filtrar()
        self.assertEqual(janela.eventos, [])
        self.assertIn("ISO", janela.mensagem.text())
        janela.inicio.setText("2026-10-17")
        janela.fim.setText("2026-10-16")
        janela.filtrar()
        self.assertIn("posterior", janela.mensagem.text())

    def test_sistema_sem_operador_e_retrato_nulo(self):
        self.ctx.operador = None
        id_ = self.ctx.cadastros.salvar("produtos", {
            "codigo": "8", "nome": "Sistema", "subgrupo_id": 1, "unidade_id": 1})
        self.admin()
        janela = self.auditoria()
        janela.grade.selectRow(0)
        self.assertEqual(janela.eventos[0]["origem"], "sistema")
        self.assertIsNone(janela.eventos[0]["operador_id"])
        self.assertEqual(janela.antes.toPlainText(), "Sem retrato")
        self.assertEqual(json.loads(janela.depois.toPlainText())["id"], id_)

    def test_credenciais_nao_aparecem_nos_retratos(self):
        self.ctx.cadastros.salvar("operadores", {"nome": "CAIXA", "senha": "Segura123", "nivel": 0})
        janela = self.auditoria()
        janela.grade.selectRow(0)
        retrato = janela.depois.toPlainText()
        self.assertNotIn("Segura123", retrato)
        self.assertNotIn('"senha"', retrato)

    def test_nao_admin_e_sessao_ausente_nao_abrem_consulta(self):
        id_ = self.ctx.cadastros.salvar("operadores", {"nome": "SUP", "senha": "Segura123", "nivel": 3})
        self.ctx.operador = self.ctx.acesso.operador(id_)
        with self.assertRaises(ErroPermissao):
            JanelaAuditoria(self.ctx)
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            JanelaAuditoria(self.ctx)

    def test_operador_desativado_limpa_dados_na_consulta_e_detalhes(self):
        self.evento(antes={"preco_cent": 350})
        janela = self.auditoria()
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.ctx.operador_id,))
        janela.grade.selectRow(0)
        self.assertEqual(janela.eventos, [])
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertEqual(janela.antes.toPlainText(), "")
        self.assertIn("administrador", janela.mensagem.text())
        self.assertFalse(janela.atualizar())

    def test_menu_admin_abre_janela_unica_e_fecha_na_sessao(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        self.assertTrue(app.principal.botoes["auditoria"].isEnabled())
        janela = app.principal.abrir_auditoria()
        self.assertIsInstance(janela, JanelaAuditoria)
        self.assertTrue(janela.isVisible())
        self.assertIs(app.principal.abrir_auditoria(), janela)
        self.assertTrue(app.encerrar_sessao())
        self.assertFalse(janela.isVisible())

    def test_menu_admin_abre_consulta_estoque_unica_e_fecha_na_sessao(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        self.assertTrue(app.principal.botoes["estoque"].isEnabled())
        janela = app.principal.abrir_estoque()
        self.assertIsInstance(janela, JanelaEstoque)
        self.assertTrue(janela.isVisible())
        self.assertIs(app.principal.abrir_estoque(), janela)
        self.assertTrue(app.encerrar_sessao())
        self.assertFalse(janela.isVisible())

    def test_menu_estoque_revalida_permissao_na_abertura(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        app.ctx.operador = None
        self.assertIsNone(app.principal.abrir_estoque())
        self.assertNotIn("estoque", app.principal.janelas)
        self.assertIn("operador", app.principal.mensagem.text())

    def test_menu_admin_abre_relatorio_vendas_unico_e_fecha_na_sessao(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        self.assertTrue(app.principal.botoes["relatorio_vendas"].isEnabled())
        janela = app.principal.abrir_relatorio_vendas()
        self.assertIsInstance(janela, JanelaRelatorioVendas)
        self.assertTrue(janela.isVisible())
        self.assertIs(app.principal.abrir_relatorio_vendas(), janela)
        self.assertTrue(app.encerrar_sessao())
        self.assertFalse(janela.isVisible())

    def test_menu_abre_catalogo_de_relatorios_com_permissao(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        self.assertTrue(app.principal.botoes["relatorios"].isEnabled())
        with patch("PySide6.QtWidgets.QInputDialog.getItem", return_value=("Entradas e saídas financeiras do caixa", True)):
            janela = app.principal.abrir_relatorios()
        self.assertIsInstance(janela, JanelaRelatorios)
        self.assertEqual(janela.chave, "caixa_mov")
        self.assertTrue(janela.isVisible())
        self.assertTrue(app.encerrar_sessao())
        self.assertFalse(janela.isVisible())

    def test_menu_admin_abre_configuracoes_unica_e_fecha_na_sessao(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        self.assertTrue(app.principal.botoes["configuracoes"].isEnabled())
        janela = app.principal.abrir_configuracoes()
        self.assertIsInstance(janela, JanelaConfiguracoes)
        self.assertTrue(janela.isVisible())
        self.assertIs(app.principal.abrir_configuracoes(), janela)
        self.assertTrue(app.encerrar_sessao())
        self.assertFalse(janela.isVisible())

    def test_menu_admin_abre_importacao_unica_e_fecha_na_sessao(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        self.assertTrue(app.principal.botoes["importar_produtos"].isEnabled())
        janela = app.principal.abrir_importacao_produtos()
        self.assertIsInstance(janela, JanelaImportarProdutos)
        self.assertTrue(janela.isVisible())
        self.assertIs(app.principal.abrir_importacao_produtos(), janela)
        self.assertTrue(app.encerrar_sessao())
        self.assertFalse(janela.isVisible())

    def test_menu_admin_abre_assistente_impressora_unico_e_fecha_na_sessao(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        with patch("src.ui_qt.assistente_impressora.impressoras_so.listar_impressoras", return_value=[]), \
             patch("src.ui_qt.assistente_impressora.assistente.diagnosticar", return_value=[]):
            self.assertTrue(app.principal.botoes["impressora"].isEnabled())
            janela = app.principal.abrir_assistente_impressora()
            self.assertIsInstance(janela, JanelaAssistenteImpressora)
            self.assertTrue(janela.isVisible())
            self.assertIs(app.principal.abrir_assistente_impressora(), janela)
            self.assertTrue(app.encerrar_sessao())
            self.assertFalse(janela.isVisible())

    def test_menu_restauracao_rejeita_banco_em_memoria_sem_criar_janela(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        self.assertTrue(app.principal.botoes["restaurar"].isEnabled())
        self.assertIsNone(app.principal.abrir_restaurar_backup())
        self.assertNotIn("restaurar", app.principal.janelas)
        self.assertIn("banco salvo", app.principal.mensagem.text())

    def test_menu_abre_fila_de_impressao_e_composicao(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        with patch("src.ui_qt.fila_impressao.QMessageBox.warning"), \
             patch("src.ui_qt.fila_impressao.QMessageBox.information"):
            self.assertTrue(app.principal.botoes["fila_impressao"].isEnabled())
            fila = app.principal.abrir_fila_impressao()
            self.assertIsInstance(fila, JanelaFilaImpressao)
            self.assertTrue(fila.isVisible())
        self.banco.cfg_set("usar_delivery", "1")
        self.assertTrue(app.principal.botoes["composicao"].isEnabled())
        composicao = app.principal.abrir_composicao()
        self.assertIsInstance(composicao, JanelaComposicao)
        self.assertTrue(composicao.isVisible())
        self.assertTrue(app.encerrar_sessao())
        self.assertFalse(fila.isVisible())
        self.assertFalse(composicao.isVisible())

    def test_menu_importacao_revalida_permissao_na_reabertura(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        janela = app.principal.abrir_importacao_produtos()
        self.assertIsNotNone(janela)
        app.ctx.operador = None
        self.assertIsNone(app.principal.abrir_importacao_produtos())
        self.assertIs(app.principal.janelas["importar_produtos"], janela)
        self.assertIn("Entre no sistema", app.principal.mensagem.text())

    def test_menu_abre_cadastros_adicionais_pela_entidade_existente(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        self.assertTrue(app.principal.botoes["mais_cadastros"].isEnabled())
        with patch("PySide6.QtWidgets.QInputDialog.getItem", return_value=("Unidades", True)):
            janela = app.principal.escolher_cadastro_adicional()
        self.assertIsInstance(janela, JanelaCadastro)
        self.assertEqual(janela.chave, "unidades")
        self.assertTrue(janela.isVisible())
        self.assertIs(app.principal.abrir_cadastro("unidades"), janela)
        self.assertTrue(app.encerrar_sessao())
        self.assertFalse(janela.isVisible())

    def test_menu_cadastros_adicionais_respeita_acesso_e_modulo(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.ctx.acesso.alterar_nivel_modulo("cad_unidades", 4)
        app.principal = JanelaPrincipal(app)
        self.assertIn(("unidades", "Unidades"), app.principal._cadastros_disponiveis())
        app.ctx.operador = app.ctx.acesso.operador(app.ctx.operador_id)
        self.banco.executar("UPDATE operadores SET nivel = 1 WHERE id = ?", (app.ctx.operador_id,))
        app.principal.atualizar()
        self.assertNotIn(("unidades", "Unidades"), app.principal._cadastros_disponiveis())
        with patch("PySide6.QtWidgets.QInputDialog.getItem") as escolha:
            self.assertIsNone(app.principal.escolher_cadastro_adicional())
            escolha.assert_not_called()
        self.assertIn("não permite", app.principal.mensagem.text())

    def test_menu_nao_admin_desabilita_e_chamada_direta_nao_contorna(self):
        id_ = self.ctx.cadastros.salvar("operadores", {"nome": "SUP", "senha": "Segura123", "nivel": 3})
        app = self.app()
        app.ctx.operador = app.ctx.acesso.operador(id_)
        app.principal = JanelaPrincipal(app)
        self.assertFalse(app.principal.botoes["auditoria"].isEnabled())
        self.assertIsNone(app.principal.abrir_auditoria())
        self.assertNotIn("auditoria", app.principal.janelas)
        self.assertIn("administrador", app.principal.mensagem.text())


if __name__ == "__main__":
    unittest.main()
