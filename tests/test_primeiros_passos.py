"""Primeiros passos da instalação: regra (controller) e assistente Qt."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from src.controllers.contexto import Contexto
from src.controllers.primeiros_passos import CHAVE_PERFIL_ESCOLHIDO, PrimeirosPassos
from src.ui_qt.app import JanelaPrincipal
from src.ui_qt.primeiros_passos import DialogoPerfil, JanelaPrimeirosPassos
from tests.base import BaseTeste
from tests.test_qt_app import BaseQt


class TestePrimeirosPassos(BaseTeste):
    def passos(self):
        return {p["chave"]: p for p in PrimeirosPassos(self.banco).passos()}

    def test_loja_nova_tem_o_essencial_pendente_e_a_licenca_fora_do_caminho(self):
        passos = self.passos()
        self.assertEqual(list(passos), ["licenca", "loja", "perfil", "impressora", "produtos", "nuvem", "backup"])
        self.assertTrue(passos["licenca"]["feito"])                     # código-fonte: licença não exigida
        for chave in ("loja", "perfil", "impressora", "produtos", "nuvem", "backup"):
            self.assertFalse(passos[chave]["feito"], chave)
        resumo = PrimeirosPassos(self.banco).resumo()
        self.assertEqual((resumo["feitos"], resumo["total"], resumo["concluido"]), (1, 7, False))
        self.assertEqual(resumo["essenciais_pendentes"], ["loja"])

    def test_cada_passo_fecha_quando_a_loja_configura(self):
        from src.controllers.config_controller import ConfigController
        config = ConfigController(self.banco)
        config.cadastrar_loja({"nome_fantasia": "Boate Centro"})
        self.novo_produto("SKOL")
        config.salvar_maquina({"modo_impressao": "termica"})
        self.banco.cfg_set("backup_externo_pasta", "D:/copias")
        self.banco.cfg_set("api_url", "https://nuvem.exemplo/v1/sincronizar")
        self.banco.cfg_set("api_token", "token")
        passos = self.passos()
        self.assertEqual(passos["loja"]["detalhe"], config.nome_loja())
        for chave in ("loja", "impressora", "produtos", "backup"):
            self.assertTrue(passos[chave]["feito"], chave)
        self.assertFalse(passos["nuvem"]["feito"])                      # conectada, mas sem o painel do dono
        self.assertIn("painel do dono está desligado", passos["nuvem"]["detalhe"])
        self.banco.cfg_set("painel_dono", "S")
        self.assertTrue(self.passos()["nuvem"]["feito"])

    def test_escolher_o_tipo_aplica_o_perfil_e_marca_o_passo(self):
        mudancas = PrimeirosPassos(self.banco, self.operador_adm()).escolher_perfil("restaurante")
        self.assertIn("usar_cozinha_bar", [m["chave"] for m in mudancas])
        self.assertEqual(self.banco.cfg("usar_garotas"), "N")
        self.assertEqual(self.banco.cfg("perfil_operacao"), "restaurante")
        self.assertEqual(self.banco.cfg(CHAVE_PERFIL_ESCOLHIDO), "S")
        passo = self.passos()["perfil"]
        self.assertTrue(passo["feito"])
        self.assertEqual(passo["detalhe"], "Restaurante.")

    def test_edicao_com_perfil_fixo_nao_pergunta_o_tipo_de_negocio(self):
        from unittest.mock import patch
        from src.core import edicao
        with patch.dict(os.environ, {edicao.VARIAVEL: "willadega"}):
            self.assertNotIn("perfil", self.passos())


class TestePrimeirosPassosQt(BaseQt):
    def principal(self):
        app = self.app()
        app.ctx.operador = app.ctx.acesso.autenticar("ADM", "ADM")
        app.principal = JanelaPrincipal(app)
        self.janelas.append(app.principal)
        return app.principal

    def test_menu_abre_a_lista_e_o_primeiro_uso_aponta_para_ela(self):
        principal = self.principal()
        self.assertIn("primeiros_passos", principal.botoes)
        janela = principal.abrir_primeiros_passos()
        self.assertIsInstance(janela, JanelaPrimeirosPassos)
        self.assertIs(principal.abrir_primeiros_passos(), janela)          # uma janela só
        self.assertEqual((janela.progresso.value(), janela.progresso.maximum()), (1, 7))
        self.assertEqual(set(janela.botoes), {"loja", "perfil", "impressora", "produtos", "nuvem", "backup"})
        self.assertTrue(all(b.isEnabled() for b in janela.botoes.values()))

    def test_passo_abre_a_tela_certa_e_a_lista_se_atualiza(self):
        from src.ui_qt.configuracoes import SECOES, JanelaCadastroLoja, JanelaConfiguracoes
        principal = self.principal()
        janela = principal.abrir_primeiros_passos()
        cadastro = janela.abrir("loja")
        self.assertIsInstance(cadastro, JanelaCadastroLoja)
        cadastro.close()
        nuvem = janela.abrir("nuvem")
        self.assertIsInstance(nuvem, JanelaConfiguracoes)
        self.assertEqual(nuvem.abas.currentIndex(), SECOES.index("nuvem"))
        principal.ctx.config.cadastrar_loja({"nome_fantasia": "Casa"})
        janela.atualizar()
        self.assertEqual(janela.progresso.value(), 2)
        self.assertEqual(janela.botoes["loja"].text(), "Rever")

    def test_dialogo_do_tipo_mostra_o_que_muda_e_aplica(self):
        principal = self.principal()
        dialogo = DialogoPerfil(principal.ctx)
        self.janelas.append(dialogo)
        self.assertIn("Nada muda", dialogo.mudancas.text())                # a boate é o padrão de fábrica
        dialogo.escolha.setCurrentIndex(dialogo.escolha.findData("comercio"))
        self.assertIn("Mesas e comandas no caixa", dialogo.mudancas.text())
        dialogo.aplicar()
        self.assertEqual(principal.ctx.banco.cfg("usar_mesas"), "N")
        self.assertEqual(principal.ctx.banco.cfg(CHAVE_PERFIL_ESCOLHIDO), "S")

    def test_sem_acesso_o_passo_fica_desabilitado(self):
        principal = self.principal()
        ident = principal.ctx.cadastros.salvar("operadores", {"nome": "CAIXA", "senha": "segredo1", "nivel": "1", "ativo": "S"})
        principal.ctx.operador = principal.ctx.acesso.operador(ident)
        janela = JanelaPrimeirosPassos(principal.ctx, principal)
        self.janelas.append(janela)
        self.assertFalse(janela.botoes["perfil"].isEnabled())
        self.assertFalse(janela.botoes["backup"].isEnabled())
