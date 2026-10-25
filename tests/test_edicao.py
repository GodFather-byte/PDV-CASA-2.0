"""Edição do programa: WillPDV (completo) e E&A Superações (só adega) a partir do mesmo código."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core import edicao
from src.core.erros import ErroNegocio
from src.controllers.config_controller import ConfigController
from src.database import conexao
from src.database.conexao import BancoDados

ADEGA = {edicao.VARIAVEL: "ea_superacoes"}


def sem_variavel():
    """Ambiente sem PDV_EDICAO (o CI ou quem roda os testes pode tê-la)."""
    return patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != edicao.VARIAVEL}, clear=True)


class TesteEscolhaDaEdicao(unittest.TestCase):
    def test_sem_nada_e_o_willpdv(self):
        with sem_variavel():
            ed = edicao.atual()
        self.assertEqual((ed.chave, ed.nome, ed.pasta_dados), ("willpdv", "WillPDV", "WILL-PDV"))
        self.assertEqual((ed.fixas, ed.perfil, ed.menu_oculto), ({}, None, frozenset()))

    def test_variavel_escolhe_a_adega(self):
        with patch.dict(os.environ, ADEGA):
            ed = edicao.atual()
        self.assertEqual((ed.nome, ed.perfil, ed.pasta_dados), ("E&A Superações", "adega", "EA-SUPERACOES"))
        self.assertIn("usar_garotas", ed.fora_das_configuracoes())
        self.assertIn("num_mesas", ed.fora_das_configuracoes())

    def test_nome_desconhecido_e_erro_para_nao_abrir_os_dados_de_outra_edicao(self):
        with patch.dict(os.environ, {edicao.VARIAVEL: "adega"}), self.assertRaises(ValueError):
            edicao.atual()

    def test_executavel_le_o_arquivo_gravado_pelo_build(self):
        with tempfile.TemporaryDirectory() as pasta, sem_variavel():
            (Path(pasta) / edicao.ARQUIVO).write_text("ea_superacoes\n", encoding="utf-8")
            with patch.object(edicao.sys, "frozen", True, create=True), \
                    patch.object(edicao.sys, "executable", str(Path(pasta) / "programa.exe")):
                self.assertEqual(edicao.atual().chave, "ea_superacoes")

    def test_cada_edicao_tem_a_sua_pasta_de_dados_no_executavel(self):
        with tempfile.TemporaryDirectory() as pasta, patch.object(conexao.sys, "frozen", True, create=True), \
                patch.dict(os.environ, {"LOCALAPPDATA": pasta}):
            with patch.dict(os.environ, ADEGA):
                self.assertEqual(conexao._raiz_dados(), Path(pasta) / "EA-SUPERACOES")
            with patch.dict(os.environ, {edicao.VARIAVEL: "willpdv"}):
                self.assertEqual(conexao._raiz_dados(), Path(pasta) / "WILL-PDV")

    def test_icone_e_logotipo_da_adega_existem(self):
        with patch.dict(os.environ, ADEGA):
            ed = edicao.atual()
            pasta = edicao.pasta_recursos()
        self.assertTrue((pasta / ed.icone).is_file())
        self.assertTrue((pasta / ed.logotipo).is_file())

    def test_linha_de_comando_tira_a_edicao_dos_argumentos(self):
        from src.app import _tirar_edicao
        with sem_variavel():
            self.assertEqual(_tirar_edicao(["--edicao", "ea_superacoes", "--autoteste", "saida.txt"]),
                             ["--autoteste", "saida.txt"])
            self.assertEqual(os.environ[edicao.VARIAVEL], "ea_superacoes")
            self.assertEqual(_tirar_edicao(["--edicao=willpdv"]), [])
            self.assertEqual(os.environ[edicao.VARIAVEL], "willpdv")


class TestePrepararBanco(unittest.TestCase):
    def setUp(self):
        self.banco = BancoDados(":memory:")
        self.addCleanup(self.banco.fechar)

    def test_willpdv_nao_mexe_em_nada(self):
        with sem_variavel():
            self.assertEqual(edicao.preparar(self.banco), [])
        self.assertEqual(self.banco.cfg("perfil_operacao"), "boate")
        self.assertTrue(self.banco.cfg_bool("usar_mesas"))
        self.assertTrue(self.banco.cfg_bool("usar_garotas"))

    def test_adega_aplica_o_perfil_na_primeira_entrada(self):
        with patch.dict(os.environ, ADEGA):
            mudancas = edicao.preparar(self.banco)
        self.assertTrue(mudancas)
        self.assertEqual((self.banco.cfg("perfil_operacao"), self.banco.cfg("edicao")), ("adega", "ea_superacoes"))
        for chave in ("usar_mesas", "usar_garotas", "usar_portaria", "usar_rodizio", "usar_prepago"):
            self.assertFalse(self.banco.cfg_bool(chave), chave)
        self.assertTrue(self.banco.cfg_bool("usar_caderneta"))
        self.assertTrue(self.banco.cfg_bool("usar_delivery"))
        self.assertIsNotNone(self.banco.um("SELECT id FROM grupos WHERE nome = 'BEBIDAS'"))

    def test_ajuste_do_dono_fica_e_modulo_de_boate_volta_a_desligar(self):
        with patch.dict(os.environ, ADEGA):
            edicao.preparar(self.banco)
            ConfigController(self.banco).salvar_config({"usar_delivery": "N"})     # ajuste do dono: vale
            self.banco.cfg_set("usar_garotas", "S")                               # ligado por fora: não vale
            self.assertEqual(edicao.preparar(self.banco), [])                     # o perfil não é reaplicado
        self.assertFalse(self.banco.cfg_bool("usar_delivery"))
        self.assertFalse(self.banco.cfg_bool("usar_garotas"))

    def test_configuracoes_recusam_ligar_modulo_de_boate_na_adega(self):
        with patch.dict(os.environ, ADEGA):
            edicao.preparar(self.banco)
            config = ConfigController(self.banco)
            with self.assertRaises(ErroNegocio):
                config.salvar_config({"usar_garotas": "S"})
            config.salvar_config({"usar_mesas": "N", "usar_delivery": "S"})       # o mesmo valor fixo passa
        with sem_variavel():
            ConfigController(self.banco).salvar_config({"usar_garotas": "S"})       # no WillPDV continua livre
        self.assertTrue(self.banco.cfg_bool("usar_garotas"))


try:
    from tests.test_qt_app import BaseQt
    from src.ui_qt.app import App, JanelaPrincipal
    from src.ui_qt.configuracoes import JanelaConfiguracoes
    from src.ui_qt.login import JanelaLogin
except ImportError:                                   # pragma: no cover - sem PySide6 estes testes não rodam
    BaseQt = None

if BaseQt is not None:
    class TesteTelasDaAdega(BaseQt):
        def principal(self):
            app = self.app()
            app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
            return self.janela(JanelaPrincipal(app))

        def test_menu_com_a_marca_da_adega_e_sem_cozinha(self):
            with patch.dict(os.environ, ADEGA):
                edicao.preparar(self.banco)
                janela = self.principal()
            self.assertTrue(janela.windowTitle().startswith("E&A Superações • "))
            self.assertNotIn("Qt piloto", janela.windowTitle())
            self.assertFalse(janela.logo_edicao.pixmap().isNull())
            janela.show()
            janela.filtrar_modulos("")
            self.assertFalse(janela.botoes["cozinha"].isVisible())
            self.assertTrue(janela.botoes["caixa"].isVisible())
            self.assertFalse(janela.faixa_noite.isVisible())                 # sem mesas: sem a "noite ao vivo"

        def test_willpdv_continua_igual(self):
            with sem_variavel():
                janela = self.principal()
                login = self.janela(JanelaLogin(self.ctx))
            self.assertTrue(janela.windowTitle().startswith("WillPDV • "))
            self.assertTrue(janela.windowTitle().endswith(" • Qt piloto"))
            self.assertTrue(janela.logo_edicao.pixmap().isNull())
            self.assertEqual(login.windowTitle(), "WillPDV • Entrada Qt")
            janela.show()
            self.assertTrue(janela.botoes["cozinha"].isVisible())

        def test_configuracoes_da_adega_sem_mesas_nem_garotas(self):
            self.admin()
            with patch.dict(os.environ, ADEGA):
                edicao.preparar(self.banco)
                janela = self.janela(JanelaConfiguracoes(self.ctx))
                campos = {chave for secao in janela.campos.values() for chave in secao}
                for chave in ("usar_garotas", "usar_mesas", "num_mesas", "codigo_comissao", "codigo_saida"):
                    self.assertNotIn(chave, campos)
                for chave in ("usar_caderneta", "usar_delivery", "agrupar_itens_balcao", "tema_visual"):
                    self.assertIn(chave, campos)
                self.ctx.config.salvar_config(janela._valores("parametros"))     # gravar a aba não esbarra nos fixos

        def test_caixa_da_adega_so_balcao_e_sem_comissoes(self):
            from src.ui_qt.caixa import JanelaCaixa
            self.admin()
            with patch.dict(os.environ, ADEGA):
                edicao.preparar(self.banco)
                caixa = self.janela(JanelaCaixa(self.ctx))
            caixa.show()
            self.assertFalse(caixa.com_mesas)
            self.assertFalse(caixa.btn_comissoes.isVisible())

        def test_iniciar_o_programa_prepara_a_adega(self):
            with patch.dict(os.environ, ADEGA):
                app = self.app()
                app.iniciar(servicos=False)
            self.assertEqual(self.banco.cfg("perfil_operacao"), "adega")
            self.assertFalse(self.banco.cfg_bool("usar_mesas"))


if __name__ == "__main__":
    unittest.main()
