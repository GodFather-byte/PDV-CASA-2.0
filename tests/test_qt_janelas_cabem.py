"""Janelas dentro da tela: ajuste automático de tamanho e Configurações sem campo cortado."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QLabel, QScrollArea, QVBoxLayout

from src.controllers.contexto import Contexto
from src.ui_qt import tema
from src.ui_qt.configuracoes import SECOES, JanelaConfiguracoes
from tests.base import BaseTeste


class BaseJanelas(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)
        tema.aplicar(cls.aplicacao)

    def setUp(self):
        super().setUp()
        self.janelas = []
        self.addCleanup(self._fechar)
        self.area = self.aplicacao.primaryScreen().availableGeometry()

    def _fechar(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def nova(self, janela):
        self.janelas.append(janela)
        return janela

    def assertCabe(self, janela):
        self.assertLessEqual(janela.width(), self.area.width() - tema.RESERVA_LARGURA)
        self.assertLessEqual(janela.height(), self.area.height() - tema.RESERVA_ALTURA)
        self.assertGreaterEqual(janela.x(), self.area.left())
        self.assertGreaterEqual(janela.y(), self.area.top())
        self.assertLessEqual(janela.x() + janela.width(), self.area.right() + 1)
        self.assertLessEqual(janela.y() + janela.height(), self.area.bottom() + 1)


class TesteAjusteDeJanelas(BaseJanelas):
    def test_janela_maior_que_a_tela_e_reduzida_e_fica_inteira_dentro_dela(self):
        janela = self.nova(QDialog())
        QVBoxLayout(janela).addWidget(QLabel("conteúdo"))
        janela.resize(self.area.width() + 600, self.area.height() + 400)
        tema.ajustar_janela(janela)
        self.assertCabe(janela)
        self.assertIsNone(getattr(janela, "_will_rolagem", None))        # conteúdo pequeno não precisa de rolagem

    def test_janela_pequena_mantem_o_tamanho(self):
        janela = self.nova(QDialog())
        janela.resize(420, 300)
        tema.ajustar_janela(janela)
        self.assertEqual((janela.width(), janela.height()), (420, 300))
        self.assertCabe(janela)

    def test_conteudo_que_nao_cabe_ganha_rolagem_em_vez_de_ser_cortado(self):
        class Alta(QDialog):
            pass
        Alta.__module__ = "src.ui_qt.exemplo"                           # só as telas do sistema são embrulhadas
        janela = self.nova(Alta())
        campo = QLabel("campo alto")
        campo.setMinimumSize(300, self.area.height() + 500)
        QVBoxLayout(janela).addWidget(campo)
        tema.ajustar_janela(janela)
        self.assertCabe(janela)
        self.assertIsInstance(janela._will_rolagem, QScrollArea)
        self.assertIs(campo.window(), janela)                            # o campo continua na mesma janela
        tema.ajustar_janela(janela)                                      # repetir não embrulha de novo
        self.assertEqual(len(janela.findChildren(QScrollArea)), 1)

    def test_filtro_ajusta_na_primeira_exibicao_e_respeita_o_tamanho_que_o_usuario_escolher_depois(self):
        filtro = tema._AjusteDeJanelas()
        filtro.ativo = True
        janela = self.nova(QDialog())
        janela.resize(self.area.width() + 300, 400)
        filtro.eventFilter(janela, QEvent(QEvent.Type.Show))
        self.assertCabe(janela)
        janela.resize(500, 350)
        janela.move(self.area.left(), self.area.top())
        filtro.eventFilter(janela, QEvent(QEvent.Type.Show))
        self.assertEqual((janela.x(), janela.y()), (self.area.left(), self.area.top()))

    def test_ajuste_automatico_fica_desligado_na_tela_ficticia_e_liga_quando_pedido(self):
        tema.instalar_ajuste_de_janelas(self.aplicacao)
        self.addCleanup(tema.instalar_ajuste_de_janelas, self.aplicacao)
        self.assertFalse(self.aplicacao._will_ajuste_janelas.ativo)
        tema.instalar_ajuste_de_janelas(self.aplicacao, forcar=True)
        self.assertTrue(self.aplicacao._will_ajuste_janelas.ativo)


class TesteConfiguracoesCabem(BaseJanelas):
    def janela(self):
        ctx = Contexto(self.banco)
        ctx.operador = ctx.acesso.operador(self.operador_adm())
        return self.nova(JanelaConfiguracoes(ctx))

    def test_nenhuma_aba_rola_para_o_lado_nem_deixa_campo_fora_da_janela(self):
        janela = self.janela()
        janela.resize(700, 520)                                          # menor que um notebook de 1024x600
        janela.show()
        for indice, secao in enumerate(SECOES):
            janela.abas.setCurrentIndex(indice)
            self.aplicacao.processEvents()
            rolagem = janela.abas.widget(indice)
            self.assertEqual(rolagem.horizontalScrollBar().maximum(), 0, secao)
            pagina = rolagem.widget()
            self.assertLessEqual(pagina.width(), rolagem.viewport().width(), secao)
            for editor in janela.campos[secao].values():
                self.assertLessEqual(editor.mapTo(pagina, editor.rect().topRight()).x(), pagina.width(), secao)

    def test_modulos_vem_primeiro_e_a_busca_esconde_o_que_nao_combina(self):
        janela = self.janela()
        janela.abas.setCurrentIndex(SECOES.index("parametros"))
        janela.show()
        self.aplicacao.processEvents()
        primeiro = next(iter(janela.campos["parametros"]))
        self.assertTrue(primeiro.startswith("usar_"), primeiro)
        janela.busca.setText("rodízio")
        self.aplicacao.processEvents()
        self.assertTrue(janela.campos["parametros"]["usar_rodizio"].isVisible())
        self.assertFalse(janela.campos["parametros"]["usar_delivery"].isVisible())
        janela.busca.clear()
        self.aplicacao.processEvents()
        self.assertTrue(janela.campos["parametros"]["usar_delivery"].isVisible())

    def test_clicar_no_texto_marca_a_opcao(self):
        from src.ui_qt.configuracoes import _Rotulo
        janela = self.janela()
        caixa = janela.campos["parametros"]["usar_delivery"]
        self.assertIsInstance(caixa, QCheckBox)
        rotulo = next(r for r in janela.findChildren(_Rotulo) if r.editor is caixa)
        marcado = caixa.isChecked()
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        QTest.mouseClick(rotulo, Qt.MouseButton.LeftButton)
        self.assertNotEqual(caixa.isChecked(), marcado)
