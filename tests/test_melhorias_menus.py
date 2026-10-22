"""Novos painéis entram nos dois menus sem contornar a sessão."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from tests.test_qt_app import BaseQt


class TesteMenusMelhoriasQt(BaseQt):
    def principal(self):
        from src.ui_qt.app import JanelaPrincipal
        app = self.app()
        self.ctx = app.ctx
        self.admin()
        janela = self.janela(JanelaPrincipal(app))
        app.principal = janela
        return janela

    def test_busca_modulos_ignora_acentos_sem_alterar_permissoes(self):
        janela = self.principal()
        estados = {chave: botao.isEnabled() for chave, botao in janela.botoes.items()}
        janela.busca_modulos.setText("promocoes")
        self.assertFalse(janela.botoes["promocoes"].isHidden())
        self.assertTrue(janela.botoes["estoque"].isHidden())
        janela.busca_modulos.clear()
        self.assertTrue(all(not botao.isHidden() for botao in janela.botoes.values()))
        self.assertEqual(estados, {chave: botao.isEnabled() for chave, botao in janela.botoes.items()})

    def test_notebook_tem_rolagem_e_busca_por_teclado(self):
        janela = self.principal()
        janela.resize(1024, 680)
        janela.show()
        self.aplicacao.processEvents()
        self.assertIsNotNone(janela.conteudo_scroll.widget())
        self.assertTrue(janela.conteudo_scroll.widgetResizable())
        self.assertTrue(janela.lateral_scroll.widgetResizable())
        janela.busca_modulos.setText("estoque")
        janela.focar_busca()
        self.assertEqual(janela.busca_modulos.selectedText(), "estoque")
        self.assertLessEqual(janela.minimumWidth(), 1024)
        self.assertLessEqual(janela.minimumHeight(), 680)

    def test_inicio_mostra_envio_interrompido_sem_automaticamente_reenviar(self):
        janela = self.principal()
        item_id = self.ctx.impressao.fila.enfileirar("caixa", "teste", b"x")
        self.banco.executar("UPDATE fila_impressao SET status = 'incerto' WHERE id = ?", (item_id,))
        janela.atualizar()
        self.assertIn("interrompido", janela.indicadores["impressao"].text())
        self.assertEqual(self.banco.valor("SELECT status FROM fila_impressao WHERE id = ?", (item_id,)), "incerto")

    def test_novos_paineis_reutilizados_e_fechados_com_sessao(self):
        janela = self.principal()
        for nome in ("retornaveis", "promocoes", "alertas", "devolucoes", "diagnostico", "verificar_backup"):
            abrir = getattr(janela, "abrir_" + nome)
            painel = abrir()
            self.assertIsNotNone(painel, janela.mensagem.text())
            self.assertIs(painel, abrir())
            self.assertIs(painel, janela.janelas[nome])
        self.assertTrue(janela.fechar_filhos())

    def test_reabrir_paineis_revalida_operador_inativo(self):
        janela = self.principal()
        for nome in ("retornaveis", "promocoes", "alertas", "devolucoes", "diagnostico", "verificar_backup"):
            self.assertIsNotNone(getattr(janela, "abrir_" + nome)())
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.ctx.operador_id,))
        for nome in ("retornaveis", "promocoes", "alertas", "devolucoes", "diagnostico", "verificar_backup"):
            self.assertIsNone(getattr(janela, "abrir_" + nome)())
            self.assertTrue(janela.mensagem.text())

    def test_recursos_gerais_disponiveis_em_todos_os_perfis(self):
        from src.controllers.perfil_controller import PERFIS
        janela = self.principal()
        for perfil in PERFIS:
            with self.subTest(perfil=perfil):
                self.ctx.perfil.aplicar(perfil)
                janela.atualizar()
                for nome in ("retornaveis", "promocoes", "alertas", "devolucoes", "diagnostico", "verificar_backup"):
                    self.assertTrue(janela.botoes[nome].isEnabled())
                    self.assertIsNotNone(getattr(janela, "abrir_" + nome)())

    def test_cozinha_e_setores_respeitam_modulo_opcional(self):
        janela = self.principal()
        self.assertFalse(janela.botoes["cozinha"].isEnabled())
        self.assertNotIn("setores_impressao", dict(janela._cadastros_disponiveis()))
        self.banco.cfg_set("usar_cozinha_bar", "S")
        janela.atualizar()
        self.assertTrue(janela.botoes["cozinha"].isEnabled())
        self.assertIn("setores_impressao", dict(janela._cadastros_disponiveis()))
        cozinha = janela.abrir_cozinha()
        self.assertIsNotNone(cozinha, janela.mensagem.text())
        self.assertIs(cozinha, janela.abrir_cozinha())
        self.banco.cfg_set("usar_cozinha_bar", "N")
        self.assertIsNone(janela.abrir_cozinha())


