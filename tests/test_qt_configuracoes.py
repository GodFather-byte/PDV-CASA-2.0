"""Configurações Qt isoladas: controladores reais e banco apenas em memória."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit

from src.core.erros import ErroNegocio, ErroPermissao
from src.ui.contexto import Contexto
from src.ui_qt.configuracoes import (
    SECOES, CHAVES_LOJA, CHAVES_PREFERENCIAS, JanelaConfiguracoes,
)
from src.ui_qt.tema import aplicar
from tests.base import BaseTeste


class TestConfiguracoesQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)
        aplicar(cls.aplicacao)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.janelas = []
        self.addCleanup(self._fechar)

    def _fechar(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        janela = JanelaConfiguracoes(self.ctx)
        self.janelas.append(janela)
        return janela

    def operador(self, nivel=3):
        id_ = self.ctx.cadastros.salvar("operadores", {
            "nome": "GERENTE", "senha": "segredo1", "nivel": str(nivel), "ativo": "S",
        })
        self.ctx.operador = self.ctx.acesso.operador(id_)
        return id_

    def definir(self, janela, secao, chave, valor):
        editor = janela.campos[secao][chave]
        if isinstance(editor, QCheckBox):
            editor.setChecked(valor)
        elif isinstance(editor, QComboBox):
            editor.setCurrentIndex(editor.findData(valor))
        else:
            editor.setText(valor)

    def test_carrega_identificacao_contatos_e_padroes_reais_sem_gravar(self):
        self.ctx.config.salvar_loja({
            "nome_fantasia": "Casa de teste", "uf": "SP", "telefone": "1234", "email": "loja@exemplo",
        })
        esperados = self.ctx.config.todas()
        with patch.object(self.ctx.config, "salvar_loja") as loja, \
                patch.object(self.ctx.config, "salvar_config") as config:
            janela = self.janela()
            loja.assert_not_called()
            config.assert_not_called()
        self.assertEqual(janela.campos["loja"]["nome_fantasia"].text(), "Casa de teste")
        self.assertEqual(janela.campos["loja"]["telefone"].text(), "1234")
        self.assertEqual(janela.campos["loja"]["email"].text(), "loja@exemplo")
        self.assertEqual(janela.campos["preferencias"]["posicao_padrao"].currentData(),
                         esperados["posicao_padrao"])
        self.assertEqual(janela.campos["preferencias"]["tempo_inatividade_min"].text(),
                         esperados["tempo_inatividade_min"])
        for chave in ("painel_mesas_fixo", "painel_mostra_garotas", "pergunta_pessoas"):
            self.assertEqual(janela.campos["preferencias"][chave].isChecked(),
                             esperados[chave] == "S")

    def test_escopo_explicito_nao_expoe_nem_regrava_segredos_e_parametros_criticos(self):
        self.ctx.config.salvar_config({
            "api_token": "SEGREDO_NAO_EXIBIR", "api_url": "https://exemplo.invalid",
            "servico_pct": "12,5", "usar_delivery": "N",
        })
        antes = self.ctx.config.todas()
        janela = self.janela()
        self.assertEqual(set(janela.campos["loja"]), set(CHAVES_LOJA))
        self.assertEqual(set(janela.campos["preferencias"]), set(CHAVES_PREFERENCIAS))
        self.assertNotIn("SEGREDO_NAO_EXIBIR", repr(janela._originais))
        for editor in janela.findChildren(QLineEdit):
            self.assertNotIn("SEGREDO_NAO_EXIBIR", editor.text())
        self.assertFalse(janela.findChildren(QLineEdit, "api_token"))
        self.definir(janela, "loja", "nome_fantasia", "Outra casa")
        self.assertTrue(janela.salvar())
        janela.abas.setCurrentIndex(1)
        self.definir(janela, "preferencias", "pergunta_pessoas", True)
        self.assertTrue(janela.salvar())
        depois = self.ctx.config.todas()
        for chave in set(antes) - set(CHAVES_PREFERENCIAS):
            self.assertEqual(antes[chave], depois[chave], chave)

    def test_salva_loja_por_api_com_normalizacao_sem_salvar_outra_aba(self):
        janela = self.janela()
        self.definir(janela, "loja", "nome_fantasia", "  Minha casa  ")
        self.definir(janela, "loja", "uf", "RJ")
        self.definir(janela, "preferencias", "tempo_inatividade_min", "71")
        with patch.object(self.ctx.config, "salvar_loja", wraps=self.ctx.config.salvar_loja) as salvar, \
                patch.object(self.ctx.config, "salvar_config") as config:
            janela.btn_salvar.click()
            salvar.assert_called_once_with({"nome_fantasia": "  Minha casa  ", "uf": "RJ"})
            config.assert_not_called()
        self.assertEqual(self.ctx.config.loja()["nome_fantasia"], "Minha casa")
        self.assertEqual(janela.campos["loja"]["nome_fantasia"].text(), "Minha casa")
        self.assertNotEqual(self.ctx.config.todas()["tempo_inatividade_min"], "71")
        self.assertIn("salvas", janela.mensagem.text())

    def test_salva_preferencias_com_tipos_e_opcoes_do_controller(self):
        janela = self.janela()
        janela.abas.setCurrentIndex(1)
        for chave, valor in (("posicao_padrao", "mesa"), ("tempo_inatividade_min", "15"),
                             ("pergunta_pessoas", True), ("painel_mesas_fixo", False),
                             ("painel_mostra_garotas", False)):
            self.definir(janela, "preferencias", chave, valor)
        with patch.object(self.ctx.config, "salvar_config", wraps=self.ctx.config.salvar_config) as salvar:
            janela.btn_salvar.click()
            salvar.assert_called_once_with({
                "posicao_padrao": "mesa", "tempo_inatividade_min": "15",
                "pergunta_pessoas": "S", "painel_mesas_fixo": "N", "painel_mostra_garotas": "N",
            })
        dados = self.ctx.config.todas()
        self.assertEqual([dados[k] for k in CHAVES_PREFERENCIAS], ["mesa", "15", "S", "N", "N"])

    def test_nao_grava_se_nao_ha_alteracao(self):
        janela = self.janela()
        with patch.object(self.ctx.config, "salvar_loja") as loja, \
                patch.object(self.ctx.config, "salvar_config") as config:
            self.assertTrue(janela.salvar())
            janela.abas.setCurrentIndex(1)
            self.assertTrue(janela.salvar())
            loja.assert_not_called()
            config.assert_not_called()

    def test_salva_so_alterados_preservando_edicao_externa_de_outros_campos(self):
        janela = self.janela()
        self.ctx.config.salvar_loja({"telefone": "novo telefone externo", "logotipo": "logo.bmp"})
        self.definir(janela, "loja", "nome_fantasia", "Casa")
        self.assertTrue(janela.salvar())
        self.assertEqual(self.ctx.config.loja()["telefone"], "novo telefone externo")
        self.assertEqual(self.ctx.config.loja()["logotipo"], "logo.bmp")
        janela.abas.setCurrentIndex(1)
        self.ctx.config.salvar_config({"tempo_inatividade_min": "42"})
        self.definir(janela, "preferencias", "pergunta_pessoas", True)
        self.assertTrue(janela.salvar())
        self.assertEqual(self.ctx.config.todas()["tempo_inatividade_min"], "42")

    def test_opcao_invalida_nao_e_substituida_silenciosamente_por_padrao(self):
        dados = self.ctx.config.todas()
        dados["posicao_padrao"] = "desconhecida"
        with patch.object(self.ctx.config, "todas", return_value=dados):
            janela = self.janela()
        janela.abas.setCurrentIndex(1)
        self.assertEqual(janela.campos["preferencias"]["posicao_padrao"].currentIndex(), -1)
        self.definir(janela, "preferencias", "tempo_inatividade_min", "16")
        with patch.object(self.ctx.config, "salvar_config", wraps=self.ctx.config.salvar_config) as salvar:
            self.assertTrue(janela.salvar())
            salvar.assert_called_once_with({"tempo_inatividade_min": "16"})
        janela.campos["preferencias"]["posicao_padrao"].setCurrentIndex(-1)
        self.assertFalse(janela.salvar())
        self.assertIn("Escolha uma das opções", janela.mensagem.text())

    def test_descartar_recarrega_apenas_aba_atual_pela_api(self):
        janela = self.janela()
        self.definir(janela, "loja", "telefone", "não salvo")
        self.definir(janela, "preferencias", "tempo_inatividade_min", "99")
        self.ctx.config.salvar_loja({"telefone": "9876"})
        janela.btn_recarregar.click()
        self.assertEqual(janela.campos["loja"]["telefone"].text(), "9876")
        self.assertEqual(janela.campos["preferencias"]["tempo_inatividade_min"].text(), "99")

    def test_uf_invalida_nao_grava_e_mantem_edicao_para_corrigir(self):
        janela = self.janela()
        antes = self.ctx.config.loja()
        self.definir(janela, "loja", "nome_fantasia", "Não gravar")
        self.definir(janela, "loja", "uf", "ABC")
        self.assertFalse(janela.salvar())
        self.assertEqual(self.ctx.config.loja(), antes)
        self.assertEqual(janela.campos["loja"]["uf"].text(), "ABC")
        self.assertIn("UF", janela.mensagem.text())

    def test_inteiro_invalido_faz_rollback_das_preferencias(self):
        janela = self.janela()
        janela.abas.setCurrentIndex(1)
        antes = self.ctx.config.todas()
        self.definir(janela, "preferencias", "posicao_padrao", "mesa")
        for invalido in ("abc", "-1"):
            with self.subTest(invalido=invalido):
                self.definir(janela, "preferencias", "tempo_inatividade_min", invalido)
                self.assertFalse(janela.salvar())
                self.assertEqual(self.ctx.config.todas(), antes)
                self.assertNotIn("salvas", janela.mensagem.text())
        self.definir(janela, "preferencias", "tempo_inatividade_min", "0")
        self.assertTrue(janela.salvar())
        self.assertEqual(self.ctx.config.todas()["tempo_inatividade_min"], "0")

    def test_sem_sessao_ou_sem_nivel_nao_consulta_configuracoes(self):
        for nivel in (None, 0, 2):
            with self.subTest(nivel=nivel):
                if nivel is None:
                    self.ctx.operador = None
                else:
                    if self.ctx.operador is None:
                        self.operador(nivel)
                    else:
                        self.ctx.cadastros.salvar("operadores", {"nivel": str(nivel)}, self.ctx.operador_id)
                with patch.object(self.ctx.config, "loja") as loja, \
                        patch.object(self.ctx.config, "todas") as todas:
                    with self.assertRaises(ErroPermissao):
                        self.janela()
                    loja.assert_not_called()
                    todas.assert_not_called()

    def test_nivel_tres_acessa_so_loja_sem_ler_preferencias(self):
        self.operador(3)
        with patch.object(self.ctx.config, "todas") as todas:
            janela = self.janela()
            todas.assert_not_called()
        self.definir(janela, "loja", "telefone", "123")
        self.assertTrue(janela.salvar())
        janela.abas.setCurrentIndex(1)
        self.assertFalse(janela.btn_salvar.isEnabled())
        with patch.object(self.ctx.config, "salvar_config") as salvar:
            self.assertFalse(janela.salvar())
            self.assertFalse(janela.recarregar())
            salvar.assert_not_called()
        self.assertEqual(janela._originais["preferencias"], {})

    def test_permissao_por_modulo_independente_da_permissao_de_loja(self):
        self.operador(2)
        self.ctx.acesso.alterar_nivel_modulo("cfg_configuracoes", 2)
        with patch.object(self.ctx.config, "loja") as loja:
            janela = self.janela()
            loja.assert_not_called()
        self.assertEqual(janela.abas.currentIndex(), 1)
        self.definir(janela, "preferencias", "tempo_inatividade_min", "18")
        self.assertTrue(janela.salvar())
        janela.abas.setCurrentIndex(0)
        self.assertFalse(janela.salvar())
        self.assertEqual(janela._originais["loja"], {})

    def test_revalida_nivel_atual_no_banco_antes_de_salvar_e_limpa_dados(self):
        id_ = self.operador(4)
        janela = self.janela()
        self.definir(janela, "loja", "telefone", "não gravar")
        self.ctx.cadastros.salvar("operadores", {"nivel": "1"}, id_)
        self.assertEqual(self.ctx.operador.nivel, 4)  # Sessão antiga não concede acesso.
        with patch.object(self.ctx.config, "salvar_loja") as salvar:
            self.assertFalse(janela.salvar())
            salvar.assert_not_called()
        self.assertEqual(janela.campos["loja"]["telefone"].text(), "")
        self.assertEqual(janela._originais, {secao: {} for secao in SECOES})
        self.assertFalse(janela.btn_salvar.isEnabled())

    def test_inativacao_ou_logout_com_janela_aberta_bloqueia_recarga_e_gravacao(self):
        id_ = self.operador(4)
        janela = self.janela()
        self.ctx.cadastros.salvar("operadores", {"ativo": "N"}, id_)
        with patch.object(self.ctx.config, "loja") as carregar, \
                patch.object(self.ctx.config, "salvar_loja") as salvar:
            self.assertFalse(janela.recarregar())
            self.assertFalse(janela.salvar())
            carregar.assert_not_called()
            salvar.assert_not_called()
        self.assertIn("inativo", janela.mensagem.text())
        self.ctx.operador = None
        self.assertFalse(janela.salvar())
        self.assertIn("Entre novamente", janela.mensagem.text())

    def test_revalida_alteracao_do_acesso_e_recarrega_apos_recuperar_permissao(self):
        self.operador(3)
        self.ctx.acesso.alterar_nivel_modulo("cfg_configuracoes", 3)
        janela = self.janela()
        janela.abas.setCurrentIndex(1)
        self.ctx.acesso.alterar_nivel_modulo("cfg_configuracoes", 4)
        self.assertFalse(janela.recarregar())
        self.assertEqual(janela._originais["preferencias"], {})
        self.ctx.acesso.alterar_nivel_modulo("cfg_configuracoes", 3)
        self.assertTrue(janela.recarregar())
        self.assertEqual(janela.campos["preferencias"]["tempo_inatividade_min"].text(),
                         self.ctx.config.todas()["tempo_inatividade_min"])

    def test_falha_do_controller_nao_informa_sucesso(self):
        janela = self.janela()
        self.definir(janela, "loja", "telefone", "123")
        with patch.object(self.ctx.config, "salvar_loja", side_effect=ErroNegocio("Falha ao gravar.")):
            self.assertFalse(janela.salvar())
        self.assertEqual(janela.mensagem.text(), "Falha ao gravar.")
        self.assertEqual(janela.campos["loja"]["telefone"].text(), "123")

    def test_reabrir_janela_revalida_permissao(self):
        id_ = self.operador(4)
        janela = self.janela()
        janela.show()
        self.aplicacao.processEvents()
        janela.close()
        self.ctx.cadastros.salvar("operadores", {"nivel": "1"}, id_)
        janela.show()
        self.aplicacao.processEvents()
        self.assertFalse(janela.btn_salvar.isEnabled())
        self.assertEqual(janela._originais, {secao: {} for secao in SECOES})

    def test_falha_de_recarga_apos_salvar_informa_que_gravacao_ocorreu(self):
        janela = self.janela()
        self.definir(janela, "loja", "telefone", "123")
        with patch.object(self.ctx.config, "loja", side_effect=ErroNegocio("Falha ao reler.")):
            self.assertTrue(janela.salvar())
        self.assertEqual(self.ctx.config.loja()["telefone"], "123")
        self.assertIn("Aba salva", janela.mensagem.text())
        with patch.object(self.ctx.config, "salvar_loja") as salvar:
            self.assertTrue(janela.salvar())
            salvar.assert_not_called()

    def test_campos_completos_do_controller_sem_duplicar_telegram(self):
        from src.controllers.config_controller import CAMPOS_CONFIG, CAMPOS_LOJA
        janela = self.janela()
        reais = {chave for secao in SECOES if secao != "loja"
                 for chave in janela.campos[secao]}
        self.assertEqual(reais, {c[0] for c in CAMPOS_CONFIG if c[3] != "Telegram"})
        self.assertEqual(set(janela.campos["loja"]), {c[0] for c in CAMPOS_LOJA})

    def test_parametros_modulos_financeiro_e_validacao_atomica(self):
        janela = self.janela()
        janela.abas.setCurrentIndex(SECOES.index("parametros"))
        self.definir(janela, "parametros", "usar_contas", True)
        self.definir(janela, "parametros", "servico_pct", "12,5")
        self.definir(janela, "parametros", "num_mesas", "0")
        antes = self.ctx.config.todas()
        self.assertFalse(janela.salvar())
        self.assertEqual(self.ctx.config.todas(), antes)
        self.definir(janela, "parametros", "num_mesas", "30")
        self.assertTrue(janela.salvar())
        self.assertTrue(self.banco.cfg_bool("usar_contas"))
        self.assertEqual(self.banco.cfg("servico_pct"), "12.5")
        self.assertEqual(self.banco.cfg_int("num_mesas"), 30)

    def test_token_oculto_so_substituido_ou_apagado_explicitamente(self):
        self.ctx.config.salvar_config({"api_token": "token-anterior"})
        janela = self.janela()
        token = janela.campos["nuvem"]["api_token"]
        self.assertEqual(token.echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(token.text(), "")
        self.assertNotIn("token-anterior", repr(janela._originais))
        janela.abas.setCurrentIndex(SECOES.index("nuvem"))
        self.definir(janela, "nuvem", "api_url", "https://exemplo.invalid")
        self.assertTrue(janela.salvar())
        self.assertEqual(self.banco.cfg("api_token"), "token-anterior")
        token.setText("token-substituto")
        self.assertTrue(janela.salvar())
        self.assertEqual(self.banco.cfg("api_token"), "token-substituto")
        self.assertEqual(token.text(), "")
        janela.apagar_token.setChecked(True)
        self.assertTrue(janela.salvar())
        self.assertEqual(self.banco.cfg("api_token"), "")

    def test_revogacao_limpa_token_digitado_e_impede_salvar(self):
        id_ = self.operador(4)
        janela = self.janela()
        janela.abas.setCurrentIndex(SECOES.index("nuvem"))
        janela.campos["nuvem"]["api_token"].setText("nao-gravar")
        self.ctx.cadastros.salvar("operadores", {"nivel": "1"}, id_)
        self.assertFalse(janela.salvar())
        self.assertEqual(janela.campos["nuvem"]["api_token"].text(), "")
        self.assertEqual(self.banco.cfg("api_token"), "")

    def test_tema_claro_e_escuro_aplicados_sem_trocar_regras(self):
        from src.ui_qt import tema
        janela = self.janela()
        janela.abas.setCurrentIndex(SECOES.index("parametros"))
        self.definir(janela, "parametros", "tema_visual", "claro")
        self.assertTrue(janela.salvar())
        self.assertIn("#f3f6fa", self.aplicacao.styleSheet())
        self.assertNotIn("#101827", self.aplicacao.styleSheet())
        tema.aplicar(self.aplicacao, "escuro")
        self.assertEqual(self.aplicacao.styleSheet(), tema.ESTILO)

    def test_primeiro_cadastro_exige_nome_sem_bloquear_adiamento(self):
        from src.ui_qt.configuracoes import JanelaCadastroLoja
        from PySide6.QtWidgets import QDialog
        janela = JanelaCadastroLoja(self.ctx)
        self.janelas.append(janela)
        self.assertFalse(janela.salvar())
        self.assertIn("nome", janela.mensagem.text())
        self.assertFalse(self.ctx.config.loja_cadastrada())
        self.definir(janela, "loja", "nome_fantasia", "Minha casa")
        self.assertTrue(janela.salvar())
        self.assertEqual(janela.result(), QDialog.DialogCode.Accepted)
        self.assertTrue(self.ctx.config.loja_cadastrada())

    def test_primeiro_cadastro_revoga_acesso_antes_de_gravar(self):
        from src.ui_qt.configuracoes import JanelaCadastroLoja
        id_ = self.operador(3)
        janela = JanelaCadastroLoja(self.ctx)
        self.janelas.append(janela)
        self.definir(janela, "loja", "nome_fantasia", "Nao gravar")
        self.ctx.cadastros.salvar("operadores", {"nivel": "1"}, id_)
        self.assertFalse(janela.salvar())
        self.assertFalse(self.ctx.config.loja_cadastrada())

    def test_token_nao_fica_no_retrato_se_recarga_falhar(self):
        janela = self.janela()
        janela.abas.setCurrentIndex(SECOES.index("nuvem"))
        janela.campos["nuvem"]["api_token"].setText("segredo-digitado")
        with patch.object(self.ctx.config, "todas", side_effect=ErroNegocio("Falha ao reler")):
            self.assertTrue(janela.salvar())
        self.assertNotIn("segredo-digitado", repr(janela._originais))
        self.assertEqual(janela.campos["nuvem"]["api_token"].text(), "")
        self.assertEqual(self.banco.cfg("api_token"), "segredo-digitado")

    # ------------------------------------------------ senha do painel do dono (trocada pelo PDV)
    def nuvem(self, url="https://nuvem.exemplo/v1/sincronizar", token="token-da-loja"):
        self.ctx.config.salvar_config({"api_url": url, "api_token": token})

    def na_aba_nuvem(self):
        janela = self.janela()
        janela.abas.setCurrentIndex(SECOES.index("nuvem"))
        return janela

    def esperar_a_nuvem(self):
        from PySide6.QtCore import QThreadPool
        self.assertTrue(QThreadPool.globalInstance().waitForDone(3000))
        self.aplicacao.processEvents()

    def trocar_senha(self, janela, digitado, retorno=None, erro=None):
        """Aperta o botão com `digitado` nas caixas de senha; devolve (chamadas à nuvem, avisos mostrados)."""
        from src.sync import painel_envio
        with patch("src.ui_qt.configuracoes.QInputDialog.getText", side_effect=digitado) as caixas, \
                patch.object(painel_envio, "trocar_senha_na_nuvem", return_value=retorno, side_effect=erro) as nuvem, \
                patch("src.ui_qt.configuracoes.QMessageBox.information") as aviso:
            janela.btn_senha_painel.click()
            self.esperar_a_nuvem()
        return nuvem, aviso, caixas

    def eventos_da_senha(self):
        return [l["detalhe"] for l in self.banco.todos("SELECT detalhe FROM log_eventos WHERE evento = 'painel_senha_trocada'")]

    def test_botao_da_senha_do_painel_segue_a_permissao_da_aba_nuvem(self):
        janela = self.na_aba_nuvem()
        self.assertTrue(janela.btn_senha_painel.isEnabled())
        self.operador(3)                                          # nível 3: só a loja, sem a nuvem
        janela = self.janela()
        self.assertFalse(janela.btn_senha_painel.isEnabled())

    def test_troca_a_senha_escolhida_pela_nuvem_e_registra_sem_a_senha(self):
        self.nuvem()
        janela = self.na_aba_nuvem()
        nuvem, aviso, _ = self.trocar_senha(janela, [("senha-qt-1234", True), ("senha-qt-1234", True)])
        nuvem.assert_called_once_with("https://nuvem.exemplo/v1/sincronizar", "token-da-loja", "senha-qt-1234")
        aviso.assert_not_called()
        self.assertIn("Senha do painel trocada", janela.mensagem.text())
        self.assertEqual(self.eventos_da_senha(), ["senha escolhida pelo operador"])
        self.assertNotIn("senha-qt-1234", repr(self.banco.todos("SELECT detalhe FROM log_eventos")))
        self.assertTrue(janela.btn_senha_painel.isEnabled())      # liberado para uma próxima troca

    def test_em_branco_a_nuvem_gera_e_a_senha_aparece_uma_vez(self):
        self.nuvem()
        janela = self.na_aba_nuvem()
        nuvem, aviso, caixas = self.trocar_senha(janela, [("", True)], retorno="abcd-efgh-jkmn")
        nuvem.assert_called_once_with("https://nuvem.exemplo/v1/sincronizar", "token-da-loja", None)
        self.assertEqual(caixas.call_count, 1)                    # em branco não pede confirmação
        self.assertIn("abcd-efgh-jkmn", aviso.call_args.args[2])
        self.assertNotIn("abcd-efgh-jkmn", janela.mensagem.text())
        self.assertEqual(self.eventos_da_senha(), ["senha gerada pela nuvem"])

    def test_senha_curta_confirmacao_diferente_ou_cancelamento_nao_chamam_a_nuvem(self):
        self.nuvem()
        janela = self.na_aba_nuvem()
        for digitado, mensagem in ((["curta"], "pelo menos 8 caracteres"),
                                   (["senha-qt-1234", "senha-qt-9999"], "não conferem")):
            nuvem, _, _ = self.trocar_senha(janela, [(d, True) for d in digitado])
            nuvem.assert_not_called()
            self.assertIn(mensagem, janela.mensagem.text())
        for caixas in ([("", False)], [("senha-qt-1234", True), ("", False)]):
            janela.mensagem.clear()
            nuvem, _, _ = self.trocar_senha(janela, caixas)
            nuvem.assert_not_called()
            self.assertEqual(janela.mensagem.text(), "")
        self.assertEqual(self.eventos_da_senha(), [])

    def test_exige_a_aba_salva_e_a_nuvem_configurada(self):
        janela = self.na_aba_nuvem()                              # nada configurado ainda
        nuvem, _, caixas = self.trocar_senha(janela, [])
        self.assertIn("Preencha o endereço da nuvem", janela.mensagem.text())
        caixas.assert_not_called()
        self.nuvem()
        janela = self.na_aba_nuvem()
        self.definir(janela, "nuvem", "api_url", "https://outro.exemplo")       # editado e ainda não salvo
        nuvem, _, caixas = self.trocar_senha(janela, [])
        self.assertIn("Salve as alterações desta aba", janela.mensagem.text())
        caixas.assert_not_called()
        self.assertTrue(janela.salvar())
        nuvem, _, _ = self.trocar_senha(janela, [("senha-qt-1234", True), ("senha-qt-1234", True)])
        nuvem.assert_called_once_with("https://outro.exemplo", "token-da-loja", "senha-qt-1234")

    def test_erro_da_nuvem_aparece_na_janela_e_nao_deixa_registro(self):
        self.nuvem()
        janela = self.na_aba_nuvem()
        digitado = [("senha-qt-1234", True), ("senha-qt-1234", True)]
        self.trocar_senha(janela, digitado, erro=ErroNegocio("A nuvem não reconheceu o token. A senha NÃO foi trocada."))
        self.assertIn("NÃO foi trocada", janela.mensagem.text())
        self.assertTrue(janela.btn_senha_painel.isEnabled())
        self.trocar_senha(janela, digitado, erro=RuntimeError("falha qualquer"))
        self.assertIn("Erro inesperado", janela.mensagem.text())
        self.assertNotIn("falha qualquer", janela.mensagem.text())
        self.assertEqual(self.eventos_da_senha(), [])

    def test_nao_fecha_nem_repete_enquanto_a_nuvem_nao_respondeu(self):
        import threading
        from src.sync import painel_envio
        self.nuvem()
        janela = self.na_aba_nuvem()
        liberar = threading.Event()

        def devagar(url, token, senha):
            liberar.wait(3)
            return None
        with patch("src.ui_qt.configuracoes.QInputDialog.getText", side_effect=[("senha-qt-1234", True)] * 2), \
                patch.object(painel_envio, "trocar_senha_na_nuvem", side_effect=devagar) as nuvem:
            janela.show()
            self.assertTrue(janela.trocar_senha_painel())
            self.assertFalse(janela.btn_senha_painel.isEnabled())
            self.assertFalse(janela.trocar_senha_painel())            # um clique repetido não dispara outra troca
            janela.mensagem.clear()
            janela.reject()                                           # Esc
            self.assertTrue(janela.isVisible())
            self.assertIn("Aguarde", janela.mensagem.text())
            janela.mensagem.clear()
            self.assertFalse(janela.close())                          # botão de fechar da janela
            self.assertTrue(janela.isVisible())
            self.assertIn("Aguarde", janela.mensagem.text())
            liberar.set()
            self.esperar_a_nuvem()
        nuvem.assert_called_once()
        self.assertTrue(janela.btn_senha_painel.isEnabled())
        self.assertTrue(janela.close())

    def test_permissao_perdida_durante_a_troca_nao_reabilita_o_botao(self):
        import threading
        from src.sync import painel_envio
        self.nuvem()
        janela = self.na_aba_nuvem()
        liberar = threading.Event()
        with patch("src.ui_qt.configuracoes.QInputDialog.getText", side_effect=[("senha-qt-1234", True)] * 2), \
                patch.object(painel_envio, "trocar_senha_na_nuvem", side_effect=lambda *a: liberar.wait(3) and None):
            janela.trocar_senha_painel()
            self.ctx.operador = None                                  # saiu da sessão com a nuvem ainda pensando
            liberar.set()
            self.esperar_a_nuvem()
        self.assertFalse(janela.btn_senha_painel.isEnabled())
