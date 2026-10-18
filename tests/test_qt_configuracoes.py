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
