"""Contrato dos alvos reais, regras e persistência do tutorial por operador."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from tests.test_qt_app import BaseQt
from src.controllers.tutoriais import PRODUTO, Tutoriais
from src.ui_qt.cadastros import FormularioCadastro, JanelaCadastro
from src.ui_qt.tutorial import MotorTutorial

class TestTutorial(BaseQt):
    def setUp(self):
        super().setUp()
        self.admin()

    def test_menu_tutoriais_fica_antes_de_operacao_e_abre_o_guia(self):
        from src.ui_qt.app import JanelaPrincipal
        app = self.app()
        app.ctx.operador = self.ctx.operador
        principal = self.janela(JanelaPrincipal(app))
        principal._fechamento_autorizado = True
        principal.show()
        self.assertEqual(principal.menu_grupos.itemText(0), "Tutoriais")
        self.assertEqual(principal.menu_grupos.itemText(1), "Operação")
        self.assertEqual(principal.botoes["tutoriais"].text(), "Cadastrar um produto")
        principal.busca_modulos.setText("tutoriais")
        self.assertTrue(principal.botoes["tutoriais"].isVisible())
        principal.busca_modulos.clear()
        principal.botoes["tutoriais"].click()
        self.assertTrue(principal.tutorial.ativo)
        self.assertTrue(principal.janelas["produtos"].isVisible())
        principal.tutorial.encerrar()

    def test_todos_os_alvos_existem_nas_telas_reais(self):
        lista = self.janela(JanelaCadastro(self.ctx, "produtos"))
        formulario = self.janela(FormularioCadastro(self.ctx, "produtos"))
        formulario.preparar_tutorial()
        for passo in PRODUTO:
            self.assertIsNotNone({"lista": lista, "formulario": formulario}[passo.janela].findChild(QWidget, passo.widget), passo.widget)

    def test_alvos_nas_tres_edicoes(self):
        import os
        from unittest.mock import patch
        from src.core import edicao
        for chave in ("willpdv", "willadega", "willrestaurante"):
            with self.subTest(edicao=chave), patch.dict(os.environ, {"PDV_EDICAO": chave}):
                edicao.preparar(self.banco)
                self.test_todos_os_alvos_existem_nas_telas_reais()

    def test_estoque_invalido_nao_grava_nem_conclui(self):
        from src.core.erros import ErroNegocio
        regra = Tutoriais(self.banco, self.ctx.operador_id)
        with self.assertRaises(ErroNegocio):
            regra.cadastrar(self.ctx.cadastros, {}, "abc")
        self.assertFalse(regra.concluido())

    def test_voltar_e_proximo_respeitam_campo(self):
        formulario = self.janela(FormularioCadastro(self.ctx, "produtos"))
        formulario.preparar_tutorial()
        formulario.show()
        motor = MotorTutorial({"formulario": formulario}, passos=PRODUTO[2:])
        self.assertFalse(motor.proximo.isEnabled())
        formulario.campos["nome"].setText("Produto")
        motor.atualizar()
        motor.mover(1)
        self.assertEqual(motor.indice, 1)
        motor.mover(-1)
        self.assertEqual(motor.indice, 0)
        motor.encerrar()

    def test_baloes_do_formulario_em_1024x600(self):
        formulario = self.janela(FormularioCadastro(self.ctx, "produtos"))
        formulario.preparar_tutorial()
        formulario.resize(1024, 600)
        formulario.show()
        self.aplicacao.processEvents()
        motor = MotorTutorial({"formulario": formulario}, passos=PRODUTO[2:])
        for indice in range(len(PRODUTO[2:])):
            motor.indice = indice
            motor._limpar()
            motor.atualizar()
            self.aplicacao.processEvents()
            motor.atualizar()
            self.assertFalse(motor.balao.geometry().intersects(motor.sombra.recorte), indice)
            self.assertTrue(formulario.rect().contains(motor.balao.geometry()), indice)
        motor.encerrar()

    def test_condicoes(self):
        self.assertFalse(Tutoriais.permite(PRODUTO[2], "  "))
        self.assertTrue(Tutoriais.permite(PRODUTO[2], "Arroz"))
        self.assertFalse(Tutoriais.permite(PRODUTO[3], "abc"))
        self.assertTrue(Tutoriais.permite(PRODUTO[3], "12,50"))
        self.assertFalse(Tutoriais.permite(PRODUTO[-1]))
        self.assertTrue(Tutoriais.permite(PRODUTO[-1], salvo=True))

    def test_salva_produto_estoque_e_conclusao(self):
        formulario = self.janela(FormularioCadastro(self.ctx, "produtos"))
        formulario.preparar_tutorial()
        formulario.campos["codigo"].setText("9888")
        formulario.campos["nome"].setText("Produto real")
        formulario.campos["preco_cent"].setText("12,50")
        for chave in ("subgrupo_id", "unidade_id"):
            formulario.campos[chave].setCurrentIndex(1)
        formulario.estoque_tutorial.setText("3")
        formulario.salvar()
        self.assertIsNotNone(formulario.id_, formulario.mensagem.text())
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id=?", (formulario.id_,)), 1250)
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id=?", (formulario.id_,)), 3)
        self.assertTrue(Tutoriais(self.banco, self.ctx.operador_id).concluido())
        self.assertFalse(Tutoriais(self.banco, 999).concluido())

    def test_falha_no_estoque_reverte_produto(self):
        from unittest.mock import patch
        from src.core.erros import ErroNegocio
        regra = Tutoriais(self.banco, self.ctx.operador_id)
        valores = {"codigo": "9887", "nome": "Produto", "preco_cent": "1,00",
                   "subgrupo_id": self.banco.valor("SELECT id FROM subgrupos LIMIT 1"),
                   "unidade_id": self.banco.valor("SELECT id FROM unidades LIMIT 1")}
        with patch("src.controllers.estoque_controller.EstoqueController.criar_lancamento", side_effect=ErroNegocio("Sem acesso")):
            with self.assertRaises(ErroNegocio):
                regra.cadastrar(self.ctx.cadastros, valores, "2")
        self.assertFalse(self.banco.valor("SELECT COUNT(*) FROM produtos WHERE codigo='9887'"))
        self.assertFalse(regra.concluido())

    def test_alvo_ausente_encerra_com_aviso(self):
        janela = self.janela(QWidget())
        janela.show()
        avisos = []
        motor = MotorTutorial({"lista": janela}, aviso=avisos.append)
        self.assertFalse(motor.ativo)
        self.assertIn("não encontrado", avisos[0])

    def test_escape_pular_e_balao_em_1024x600(self):
        janela = self.janela(JanelaCadastro(self.ctx, "produtos"))
        janela.resize(1024, 600)
        janela.show()
        self.aplicacao.processEvents()
        motor = MotorTutorial({"lista": janela})
        self.assertFalse(motor.balao.geometry().intersects(motor.sombra.recorte))
        self.assertTrue(janela.rect().contains(motor.balao.geometry()))
        QTest.keyClick(janela, Qt.Key.Key_Escape)
        self.assertFalse(motor.ativo)
        self.assertFalse(Tutoriais(self.banco, self.ctx.operador_id).concluido())
        motor = MotorTutorial({"lista": janela})
        motor.encerrar()
        self.assertFalse(motor.ativo)
