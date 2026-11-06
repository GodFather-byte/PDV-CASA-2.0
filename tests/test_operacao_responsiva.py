"""Venda sem saldo, quartos para caixas e painéis que cabem sem rolagem geral."""
import json
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QScrollArea, QPushButton

from src.controllers.cadastro_controller import CadastroController
from src.controllers.contexto import Contexto
from src.core.erros import ErroNegocio
from src.ui_qt import tema
from src.ui_qt.app import JanelaPrincipal
from src.ui_qt.caixa import JanelaCaixa
from src.ui_qt.quartos import JanelaQuartos
from tests.test_caixa import BaseCaixa
from tests.test_qt_app import BaseQt


class TestVendaSemSaldo(BaseCaixa):
    def test_vende_com_saldo_zero_e_estorna_exatamente(self):
        self.banco.executar('UPDATE produtos SET qt_atual=0 WHERE id=?', (self.skol,))
        venda = self.vender((self.skol, 2))
        self.pagar(venda, 'Dinheiro', 1600)
        self.caixa.fechar(venda)
        self.assertEqual(self.caixa.obter(venda)['status'], 'fechada')
        self.assertEqual(self.prod.por_id(self.skol)['qt_atual'], -2)
        evento = self.banco.um("SELECT depois FROM auditoria_eventos WHERE acao='venda_sem_estoque'")
        self.assertEqual(json.loads(evento['depois'])['resultado'], 'permitida')
        with self.assertRaises(ErroNegocio):
            self.caixa.fechar(venda)
        self.assertEqual(self.prod.por_id(self.skol)['qt_atual'], -2)
        self.caixa.cancelar_venda(venda, 'Teste de estorno sem saldo')
        self.assertEqual(self.prod.por_id(self.skol)['qt_atual'], 0)

    def test_composicao_baixa_insumo_fracionado_sem_saldo(self):
        insumo = self.novo_produto('GARRAFA', 10000, estoque=True)
        dose = self.novo_produto('DOSE', 1000)
        self.prod.incluir_composicao(dose, insumo, 0.05)
        venda = self.vender((dose, 3))
        self.pagar(venda, 'Dinheiro', 3000)
        self.caixa.fechar(venda)
        self.assertEqual(self.prod.por_id(insumo)['qt_atual'], -0.15)
        self.caixa.cancelar_venda(venda, 'Teste de composição')
        self.assertEqual(self.prod.por_id(insumo)['qt_atual'], 0)

    def test_bloqueio_configuravel_e_saidas_manuais_permanecem_controladas(self):
        self.banco.cfg_set('permitir_venda_sem_estoque', 'N')
        self.banco.executar('UPDATE produtos SET qt_atual=0 WHERE id=?', (self.skol,))
        venda = self.vender((self.skol, 1))
        self.pagar(venda, 'Dinheiro', 800)
        with self.assertRaises(ErroNegocio):
            self.caixa.fechar(venda)
        self.assertEqual(self.caixa.obter(venda)['status'], 'aberta')
        self.banco.cfg_set('permitir_venda_sem_estoque', 'S')
        with self.assertRaises(ErroNegocio):
            self.caixa.estoque._mover(self.skol, -1, 'saida')


class TestPaineisResponsivos(BaseQt):
    def setUp(self):
        super().setUp()
        self.admin()
        anterior = self.aplicacao.styleSheet()
        self.addCleanup(self.aplicacao.setStyleSheet, anterior)
        tema.aplicar(self.aplicacao)
        self.banco.cfg_set('usar_quartos', 'S')
        self.banco.cfg_set('usar_cozinha_bar', 'S')

    def acomodar(self, janela):
        janela.resize(1280, 680)
        janela.show()
        for _ in range(3):
            self.aplicacao.processEvents()
        self.assertLessEqual(janela.width(), 1280)
        self.assertLessEqual(janela.height(), 680)
        for area in janela.findChildren(QScrollArea):
            if area.isVisible():
                self.assertEqual(area.verticalScrollBar().maximum(), 0, type(janela).__name__)
                self.assertEqual(area.horizontalScrollBar().maximum(), 0, type(janela).__name__)

    def test_caixa_busca_pagamento_e_quartos_sem_rolagem_geral(self):
        self.ctx.turnos.abrir(self.ctx.operador_id, 1, 0)
        from tests.base import BaseTeste
        BaseTeste.novo_produto(self, 'COCA LATA', 500, codigo='20')
        BaseTeste.novo_produto(self, 'COCA GARRAFA', 1000, codigo='21')
        j = self.janela(JanelaCaixa(self.ctx))
        from tests.test_qt_caixa import DialogosFalsos
        j.dialogos = DialogosFalsos()
        j.dialogos.confirmacoes = [True] * 4
        self.acomodar(j)
        tamanho = j.size()
        j.ent_codigo.setText('COCA')
        j.lancar_item()
        self.aplicacao.processEvents()
        self.assertTrue(j.lista_produtos.isVisible())
        self.assertEqual(j.size(), tamanho)
        j.lancar_item()
        self.acomodar(j)
        for botao in (j.btn_receber, j.btn_fechar_venda, j.btn_trocar_turno, j.btn_lancar):
            p = botao.mapTo(j, QPoint(0, 0))
            self.assertTrue(j.rect().contains(p))
            self.assertTrue(j.rect().contains(p + QPoint(botao.width()-1, botao.height()-1)))
        self.assertGreater(j.tabela.height(), 68)

    def test_menu_todas_categorias_e_status_sem_rolagem(self):
        app = self.app()
        app.ctx.operador = self.ctx.operador
        j = self.janela(JanelaPrincipal(app))
        j._fechamento_autorizado = True
        for categoria in range(j.menu_grupos.count()):
            for aba in range(j.abas_status.count()):
                j.menu_grupos.setCurrentIndex(categoria)
                j.abas_status.setCurrentIndex(aba)
                self.acomodar(j)
        j.busca_modulos.setText('impressora')
        self.aplicacao.processEvents()
        self.assertTrue(j.botoes['impressora'].isVisible())

    def test_principais_paineis_cabem_na_tela(self):
        from src.ui_qt.cadastros import JanelaCadastro
        from src.ui_qt.estoque import JanelaEstoque
        from src.ui_qt.contas import JanelaContas
        from src.ui_qt.relatorio_vendas import JanelaRelatorioVendas
        from src.ui_qt.cozinha import JanelaCozinha
        for cls in (JanelaEstoque, JanelaContas, JanelaRelatorioVendas, JanelaCozinha, JanelaQuartos):
            with self.subTest(painel=cls.__name__):
                j = self.janela(cls(self.ctx))
                self.acomodar(j)
                j.hide()
        self.acomodar(self.janela(JanelaCadastro(self.ctx, 'produtos')))

    def test_relatorios_todos_filtros_sem_rolagem(self):
        from src.ui_qt.relatorios import JanelaRelatorios, SPECS
        j = self.janela(JanelaRelatorios(self.ctx))
        for chave in SPECS:
            with self.subTest(relatorio=chave):
                j.selecao.setCurrentIndex(j.selecao.findData(chave))
                self.acomodar(j)

    def test_quartos_paginados_sem_perder_avisos_ou_atalhos(self):
        self.banco.cfg_set('quartos_qtd', '50')
        self.ctx.turnos.abrir(self.ctx.operador_id, 1, 0)
        j = self.janela(JanelaCaixa(self.ctx))
        self.acomodar(j)
        for _ in range(6):
            j.painel_quartos.proxima.click()
        grade = j.painel_quartos.grade
        self.assertEqual(grade.pagina, 6)
        x, y, w, h = grade.celula(49)
        self.assertEqual(grade.indice_em(QPoint(int(x+w/2), int(y+h/2))), 49)
        j.painel_quartos.itens[50]['estado'] = 'livre'
        with patch.object(j.painel_quartos, 'pedir') as pedir:
            j.painel_quartos.acionar(50)
            self.assertEqual(pedir.call_args.args[1], 50)
        painel = self.janela(JanelaQuartos(self.ctx))
        self.acomodar(painel)
        for _ in range(6):
            painel.proxima.click()
        self.assertFalse(painel.cartoes[50].isHidden())
        self.assertTrue(painel.cartoes[1].isHidden())
        self.acomodar(painel)

    def test_quartos_todos_niveis_sem_liberar_configuracoes(self):
        self.ctx.acesso.alterar_nivel_modulo('util_quartos', 4)
        for nivel in range(5):
            with self.subTest(nivel=nivel):
                oid = CadastroController(self.banco).salvar('operadores',
                    {'nome': f'CAIXA{nivel}', 'senha': '1234', 'nivel': str(nivel)})
                ctx = Contexto(self.banco, self.ctx.acesso.operador(oid))
                self.assertTrue(ctx.pode('util_quartos'))
                painel = self.janela(JanelaQuartos(ctx))
                painel.exigir_acesso()
                painel.hide()
                if nivel < 4:
                    self.assertFalse(ctx.pode('cfg_acessos'))
                self.banco.executar('UPDATE operadores SET ativo=0 WHERE id=?', (oid,))
                self.assertFalse(ctx.pode('util_quartos'))
        self.banco.cfg_set('usar_quartos', 'N')
        self.assertFalse(self.ctx.pode('util_quartos'))

    def test_caixa_nivel_zero_e_um_mostram_quartos_do_turno(self):
        self.ctx.turnos.abrir(self.ctx.operador_id, 1, 0)
        for nivel in (0, 1):
            with self.subTest(nivel=nivel):
                oid = CadastroController(self.banco).salvar('operadores',
                    {'nome': f'TURNO{nivel}', 'senha': '1234', 'nivel': str(nivel)})
                ctx = Contexto(self.banco, self.ctx.acesso.operador(oid))
                j = self.janela(JanelaCaixa(ctx))
                self.acomodar(j)
                self.assertTrue(j.painel_quartos.isVisible())
                j.painel_quartos.abrir_painel()
                painel = j.painel_quartos._painel
                self.janelas.append(painel)
                painel.exigir_acesso()
                painel.hide()
                j.hide()

    def test_caixa_com_comissao_e_shows_cabe_sem_cortar_pagamento(self):
        self.ctx.turnos.abrir(self.ctx.operador_id, 1, 0)
        self.banco.cfg_set('num_comandas', '300')
        CadastroController(self.banco).salvar('garotas', {'numero':'180', 'nome':'MARIA APARECIDA DE SOUZA TESTE'})
        self.ctx.comissoes.lancar(180, 2500, self.ctx.turnos.atual()['id'], self.ctx.operador_id)
        self.ctx.quartos.iniciar(1, 2, codigo_profissional='180')
        j = self.janela(JanelaCaixa(self.ctx))
        j.ent_pos.setText('180')
        j.chamar_posicao()
        self.acomodar(j)
        self.assertTrue(j.btn_pagar_garota.isVisible())
        self.assertTrue(j.lbl_aviso_venda.isVisible())
