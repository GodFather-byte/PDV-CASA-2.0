"""Contrato dos alvos reais, regras e persistência do tutorial por operador."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from tests.test_qt_app import BaseQt
from src.controllers.tutoriais import PRODUTO, ROTEIROS, Tutoriais
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
        self.assertEqual(principal.menu_grupos.currentIndex(), 1)
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


class TestOutrosTutoriais(BaseQt):
    """Grupo, subgrupo, operador, cliente, forma de pagamento e fornecedor: o mesmo motor em outros cadastros."""

    def setUp(self):
        super().setUp()
        self.admin()
        self.banco.cfg_set("usar_caderneta", "S")        # clientes só existem com caderneta ou delivery

    def principal(self):
        from src.ui_qt.app import JanelaPrincipal
        app = self.app()
        app.ctx.operador = self.ctx.operador
        principal = self.janela(JanelaPrincipal(app))
        principal._fechamento_autorizado = True
        principal.show()
        return principal

    def test_todos_os_alvos_existem_nas_tres_edicoes(self):
        import os
        from unittest.mock import patch
        from src.core import edicao
        for chave in ("willpdv", "willadega", "willrestaurante"):
            with patch.dict(os.environ, {"PDV_EDICAO": chave}):
                edicao.preparar(self.banco)
                for roteiro in (r for r in ROTEIROS.values() if r.tipo == "cadastro"):
                    lista = self.janela(JanelaCadastro(self.ctx, roteiro.cadastro))
                    formulario = self.janela(FormularioCadastro(self.ctx, roteiro.cadastro))
                    if roteiro.chave == "produto":
                        formulario.preparar_tutorial()
                    for passo in roteiro.passos:
                        alvo = {"lista": lista, "formulario": formulario}[passo.janela].findChild(QWidget, passo.widget)
                        self.assertIsNotNone(alvo, f"{chave}/{roteiro.chave}/{passo.widget}")

    def test_baloes_cabem_em_1024x600_com_a_letra_grande(self):
        for roteiro in (r for r in ROTEIROS.values() if r.tipo == "cadastro"):
            formulario = self.janela(FormularioCadastro(self.ctx, roteiro.cadastro))
            if roteiro.chave == "produto":
                formulario.preparar_tutorial()
            formulario.resize(1024, 600)
            formulario.show()
            self.aplicacao.processEvents()
            passos = tuple(p for p in roteiro.passos if p.janela == "formulario")
            motor = MotorTutorial({"formulario": formulario}, passos=passos)
            for indice in range(len(passos)):
                motor.indice = indice
                motor._limpar()
                motor.atualizar()
                self.aplicacao.processEvents()
                motor.atualizar()
                onde = f"{roteiro.chave}/{indice}"
                self.assertFalse(motor.balao.geometry().intersects(motor.sombra.recorte), onde)
                self.assertTrue(formulario.rect().contains(motor.balao.geometry()), onde)
            motor.encerrar()
            formulario.hide()

    def test_menu_tem_um_botao_por_tutorial_e_marca_o_concluido(self):
        principal = self.principal()
        self.assertEqual(principal.botoes["tutorial_cliente"].text(), "Cadastrar um cliente")
        principal.busca_modulos.setText("tutoriais")
        for roteiro in ROTEIROS.values():
            chave = "tutoriais" if roteiro.chave == "produto" else f"tutorial_{roteiro.chave}"
            self.assertTrue(principal.botoes[chave].isVisible(), chave)
        principal.busca_modulos.clear()
        Tutoriais(self.banco, self.ctx.operador_id).concluir("cliente")
        principal.marcar_tutoriais()
        self.assertEqual(principal.botoes["tutorial_cliente"].text(), "✓ Cadastrar um cliente")
        self.assertEqual(principal.botoes["tutorial_grupo"].text(), "Criar um grupo")

    def test_subgrupo_do_comeco_ao_fim(self):
        """Clica em Novo, o Próximo só acende com o nome e o grupo, e salvar conclui e marca no menu."""
        from unittest.mock import patch
        principal = self.principal()
        vistos = {}

        def usar(formulario):
            motor = principal.tutorial
            formulario.show()
            self.aplicacao.processEvents()
            motor.atualizar()
            self.assertEqual(motor.passos[motor.indice].widget, "produto_nome")
            self.assertFalse(motor.proximo.isEnabled())
            self.assertIn("Escreva", motor.dica.text())
            formulario.campos["nome"].setText("Cervejas especiais")
            motor.atualizar()
            self.assertTrue(motor.proximo.isEnabled())
            motor.mover(1)
            motor.atualizar()
            self.assertEqual(motor.passos[motor.indice].widget, "produto_grupo_id")
            self.assertFalse(motor.proximo.isEnabled())           # ainda em "Selecione…"
            formulario.campos["grupo_id"].setCurrentIndex(1)
            motor.atualizar()
            self.assertTrue(motor.proximo.isEnabled())
            motor.mover(1)
            formulario.salvar()
            vistos["id"] = formulario.id_
            return formulario.result()

        with patch.object(FormularioCadastro, "exec", usar):
            principal.botoes["tutorial_subgrupo"].click()
            self.assertTrue(principal.tutorial.ativo)
            principal.janelas["subgrupos"].novo()
        self.assertEqual(self.banco.valor("SELECT nome FROM subgrupos WHERE id = ?", (vistos["id"],)), "Cervejas especiais")
        self.assertFalse(principal.tutorial.ativo)
        self.assertTrue(Tutoriais(self.banco, self.ctx.operador_id).concluido("subgrupo"))
        self.assertFalse(Tutoriais(self.banco, self.ctx.operador_id).concluido("grupo"))
        self.assertEqual(principal.botoes["tutorial_subgrupo"].text(), "✓ Criar um subgrupo")
        self.assertIn("Subgrupo criado", principal.mensagem.text())

    def test_salvar_fora_do_tutorial_nao_conclui(self):
        formulario = self.janela(FormularioCadastro(self.ctx, "grupos"))
        formulario.campos["nome"].setText("Limpeza")
        formulario.salvar()
        self.assertIsNotNone(formulario.id_)
        self.assertFalse(Tutoriais(self.banco, self.ctx.operador_id).concluido("grupo"))

    def test_cadastro_desligado_esconde_o_tutorial(self):
        self.banco.cfg_set("usar_caderneta", "N")
        self.banco.cfg_set("usar_delivery", "N")
        principal = self.principal()
        principal.menu_grupos.setCurrentIndex(0)
        principal.atualizar()
        self.assertFalse(principal.botoes["tutorial_cliente"].isVisible())
        self.assertTrue(principal.botoes["tutorial_grupo"].isVisible())

    def test_sem_acesso_o_botao_fica_apagado(self):
        self.banco.executar("UPDATE operadores SET nivel = 1 WHERE id = ?", (self.ctx.operador_id,))
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        principal = self.principal()
        principal.atualizar()
        self.assertFalse(principal.botoes["tutorial_operador"].isEnabled())


class TestVendaDeTreino(BaseQt):
    """Tutorial "Fazer uma venda": caixa de verdade num banco só na memória, guiado no teclado."""

    def setUp(self):
        super().setUp()
        self.admin()

    def principal(self):
        from src.ui_qt.app import JanelaPrincipal
        app = self.app()
        app.ctx.operador = self.ctx.operador
        principal = self.janela(JanelaPrincipal(app))
        principal._fechamento_autorizado = True
        principal.show()
        return principal

    def enter(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.aplicacao.processEvents()
        QTest.keyClick(self.aplicacao.focusWidget(), Qt.Key.Key_Return)
        self.aplicacao.processEvents()

    def passo(self, motor):
        motor.atualizar()
        self.aplicacao.processEvents()
        return motor.passos[motor.indice].widget if motor.ativo else None

    def test_banco_de_treino_isola_a_loja(self):
        from src.controllers import treino
        self.banco.cfg_set("pix_integrado", "S")
        self.banco.cfg_set("nfce_emissao", "producao")
        banco, operador = treino.criar_banco(self.banco)
        self.addCleanup(banco.fechar)
        self.assertEqual(banco.caminho, ":memory:")
        self.assertEqual((banco.cfg("pix_integrado"), banco.cfg("nfce_emissao"), banco.cfg("imprimir_cupom")),
                         ("N", "desligada", "N"))
        self.assertEqual(operador.nome, "TREINO")
        self.assertIsNotNone(banco.um("SELECT id FROM turnos WHERE fechado_em IS NULL"))
        self.assertEqual(banco.valor("SELECT preco_cent FROM produtos WHERE CAST(codigo AS INTEGER) = 1"), 300)

    def test_venda_guiada_do_comeco_ao_fim_nas_tres_edicoes(self):
        import os
        from unittest.mock import patch
        from src.core import edicao
        for chave in ("willpdv", "willadega", "willrestaurante"):
            with self.subTest(edicao=chave), patch.dict(os.environ, {"PDV_EDICAO": chave}):
                edicao.preparar(self.banco)
                vendas_loja = self.banco.valor("SELECT COUNT(*) FROM vendas")
                principal = self.principal()
                principal.botoes["tutorial_venda"].click()
                motor = principal.tutorial
                caixa = principal.janelas["treino"]
                caixa.activateWindow()
                self.assertTrue(motor.ativo)
                if caixa.com_mesas:
                    self.assertEqual(self.passo(motor), "ent_pos")
                    caixa.ent_pos.setFocus()
                    caixa.ent_pos.setText("1")
                    self.enter()
                self.assertEqual(self.passo(motor), "ent_codigo")
                self.assertIn("treino", motor.passos[motor.indice].texto.lower() + motor.passos[0].texto.lower())
                caixa.ent_codigo.setFocus()
                caixa.ent_codigo.setText("1")
                self.enter()
                self.assertEqual(self.passo(motor), "ent_qtd")
                self.enter()
                self.assertEqual(self.passo(motor), "ent_codigo")        # "aperte Enter com o campo vazio"
                self.enter()
                self.assertEqual(self.passo(motor), "cmb_forma")
                self.enter()
                self.assertEqual(self.passo(motor), "ent_valor")
                self.enter()
                self.assertEqual(self.passo(motor), "btn_fechar_venda")
                self.enter()
                self.assertEqual(self.passo(motor), "lbl_troco")
                self.assertEqual(motor.proximo.text(), "Concluir")
                self.assertEqual(caixa.treino_banco.valor("SELECT COUNT(*) FROM vendas WHERE status = 'fechada'"), 1)
                motor.mover(1)
                self.assertFalse(motor.ativo)
                self.assertTrue(Tutoriais(self.banco, self.ctx.operador_id).concluido("venda"))
                self.assertEqual(principal.botoes["tutorial_venda"].text(), "✓ Fazer uma venda (treino)")
                # nada chegou ao banco da loja
                self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas"), vendas_loja)
                self.assertIsNone(self.banco.um("SELECT id FROM turnos WHERE fechado_em IS NULL"))
                self.banco.cfg_set(Tutoriais(self.banco, self.ctx.operador_id)._chave("venda"), "N")
                caixa.close()
                principal.close()

    def test_fechar_o_caixa_de_treino_encerra_o_tutorial(self):
        principal = self.principal()
        principal.abrir_tutoriais("venda")
        motor = principal.tutorial
        principal.janelas["treino"].close()
        self.aplicacao.processEvents()
        motor.atualizar()
        self.assertFalse(motor.ativo)
        self.assertFalse(Tutoriais(self.banco, self.ctx.operador_id).concluido("venda"))
