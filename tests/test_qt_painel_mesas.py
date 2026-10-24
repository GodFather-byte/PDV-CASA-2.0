"""Painel de cartões das mesas e comandas (Qt): modelo, filtros, clique, teclado e desenho nos dois modos."""
from __future__ import annotations

import unittest

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from src.ui_qt.painel_mesas import ALTURA, LARGURA, PainelMesas, detalhes
except ImportError:                                   # pragma: no cover - sem PySide6 o painel Qt não roda
    PainelMesas = None

from src.controllers.mesas_modelo import idade, montar_tiles


def mesa(rotulo, total=1000, comanda=True, status="aberta", inativa=False, minutos=3, **extra):
    return {"id": hash(rotulo) % 10_000, "rotulo": rotulo, "comanda": comanda, "status": status, "inativa": inativa,
            "total_cent": total, "minutos_parada": minutos, "n_itens": 1, **extra}


class TesteModeloDosCartoes(unittest.TestCase):
    def test_estados_por_situacao(self):
        tiles = montar_tiles([
            mesa("C1"), mesa("C2", status="conta_enviada"), mesa("C3", inativa=True, minutos=45),
            mesa("C4", recebido_cent=400), mesa("C5", recebido_cent=1000)])
        self.assertEqual([t["estado"] for t in tiles[1:]], ["consumindo", "conta", "parada", "parcial", "acerto"])
        self.assertEqual(tiles[4]["falta"], "6,00")

    def test_prepago_mostra_saldo_e_nao_falta(self):
        t = montar_tiles([mesa("C9", total=300, recebido_cent=1000, prepago=True)])[1]
        self.assertEqual((t["estado"], t["saldo"]), ("consumindo", "7,00"))
        self.assertNotIn("falta", t)

    def test_garota_com_consumo_vira_selo_e_sem_consumo_vira_cartao(self):
        garotas = [{"rotulo": "C7", "total_cent": 5000, "nome": "Bia", "marcacoes": 2}]
        com = montar_tiles([mesa("C7")], garotas=garotas)
        self.assertEqual((len(com), com[1]["tipo"], com[1]["garota"]), (2, "comanda", "50,00"))
        vazia = montar_tiles([mesa("C7", total=0, n_itens=0)], garotas=garotas)
        self.assertEqual((vazia[1]["tipo"], vazia[1]["estado"], vazia[1]["nome"]), ("garota", "garota", "Bia"))
        so_garota = montar_tiles([], garotas=garotas)
        self.assertEqual([t["tipo"] for t in so_garota], ["balcao", "garota"])

    def test_idade(self):
        self.assertEqual((idade(0), idade(42), idade(112)), ("agora", "42 min", "1h52"))


@unittest.skipIf(PainelMesas is None, "PySide6 indisponível")
class TestePainelQt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.painel = PainelMesas(colunas=2)
        self.addCleanup(self.painel.deleteLater)
        self.painel.resize(400, 600)
        self.painel.show()
        self.eventos = []
        self.painel.escolhida.connect(lambda c: self.eventos.append(("escolhida", c)))
        self.painel.transferir.connect(lambda c: self.eventos.append(("transferir", c)))
        self.painel.voltar.connect(lambda: self.eventos.append(("voltar", None)))
        self.painel.digitou.connect(lambda c: self.eventos.append(("digitou", c)))
        self.painel.atualizar([mesa("C1"), mesa("C2", status="conta_enviada"), mesa("M5", comanda=False, apelido="Carlos"),
                               mesa("C4", recebido_cent=400)], None, "C1")
        self.app.processEvents()

    def test_abas_e_busca_so_filtram_a_vista(self):
        chaves = lambda: [t["chave"] for t in self.painel.tiles()]
        self.assertEqual(chaves(), ["0", "C1", "C2", "M5", "C4"])
        self.painel._escolher_aba("Aguardando acerto")
        self.assertEqual(chaves(), ["C2"])
        self.painel._escolher_aba("Pago em parte")
        self.assertEqual(chaves(), ["C4"])
        self.painel._escolher_aba("Todas")
        self.painel.busca.setText("carl")                      # acha pelo nome da comanda
        self.assertEqual(chaves(), ["M5"])
        self.assertIn("Posições: 4", self.painel.lbl_resumo.text())

    def test_clique_no_cartao_escolhe_a_posicao(self):
        chaves = [t["chave"] for t in self.painel.tiles()]
        x, y, w, h = self.painel.grade.celula(chaves.index("C2"))
        QTest.mouseClick(self.painel.grade, Qt.LeftButton, Qt.NoModifier, QPoint(x + w // 2, y + h // 2))
        self.assertEqual(self.eventos, [("escolhida", "C2")])

    def test_teclado_navega_escolhe_transfere_e_digita(self):
        grade = self.painel.grade
        self.painel.focar("C1")
        QTest.keyClick(grade, Qt.Key_Right)
        self.assertEqual(self.painel.cursor(), "C2")
        QTest.keyClick(grade, Qt.Key_Return)
        QTest.keyClick(grade, Qt.Key_T)
        QTest.keyClick(grade, Qt.Key_7)
        QTest.keyClick(grade, Qt.Key_Escape)
        self.assertEqual(self.eventos, [("escolhida", "C2"), ("transferir", "C2"), ("digitou", "7"), ("voltar", None)])
        self.painel.focar("0")
        QTest.keyClick(grade, Qt.Key_T)                        # o balcão não é destino de transferência
        self.assertNotIn(("transferir", "0"), self.eventos)

    def test_vizinha_respeita_o_filtro_e_nao_da_a_volta(self):
        self.assertEqual(self.painel.vizinha("C1", 1), "C2")
        self.assertEqual(self.painel.vizinha("C4", 1), "C4")
        self.assertEqual(self.painel.vizinha(None, 1), "0")
        self.assertEqual(self.painel.vizinha(None, -1), "C4")

    def test_desenha_nos_dois_modos_sem_erro(self):
        for modo in ("escuro", "claro"):
            self.painel.definir_modo(modo)
            imagem = QPixmap(self.painel.size())
            self.painel.render(imagem)
            self.assertFalse(imagem.isNull())

    def test_detalhes_do_cartao(self):
        self.assertEqual(detalhes({"tipo": "comanda", "estado": "parcial", "nome": "Ana", "falta": "6,00", "minutos": 1}),
                         ("Ana", "Falta R$ 6,00", "ambar"))
        self.assertEqual(detalhes({"tipo": "mesa", "estado": "parada", "minutos": 45, "pessoas": 4}),
                         ("4 pessoas", "45 min sem lançar", "vermelho"))
        self.assertEqual(LARGURA * 2 + PainelMesas.RESERVA, self.painel.width())
        self.assertGreater(ALTURA, 0)


try:
    from tests.test_qt_caixa import BaseCaixaQt
except ImportError:                                   # pragma: no cover
    BaseCaixaQt = None


@unittest.skipIf(BaseCaixaQt is None, "PySide6 indisponível")
class TesteCartoesNoCaixa(BaseCaixaQt if BaseCaixaQt else object):
    def test_mesa_aberta_vira_cartao_e_seta_para_baixo_leva_o_foco_aos_cartoes(self):
        skol = self.novo_produto("SKOL", 800, codigo="10", estoque=True, qt=10)
        self.abrir_turno()
        vid, _ = self.ctx.caixa.abrir_mesa(5, comanda=False)
        self.ctx.caixa.adicionar_item(vid, skol, 1)
        j = self.janela()
        self.assertEqual([t["chave"] for t in j.cartoes.tiles()], ["0", "M5"])
        j.ent_pos.setFocus()
        QTest.keyClick(j.ent_pos, Qt.Key_Down)
        self.assertEqual(j.cartoes.cursor(), "0")
        j.cartoes.escolhida.emit("M5")                        # clicar no cartão chama a mesa
        self.assertEqual(j.venda_id, vid)
        self.assertEqual(j._chave_atual(), "M5")


@unittest.skipIf(BaseCaixaQt is None, "PySide6 indisponível")
class TesteEscVoltaAoMarcarComanda(BaseCaixaQt if BaseCaixaQt else object):
    def setUp(self):
        super().setUp()
        self.skol = self.novo_produto("SKOL", 800, codigo="10", estoque=True, qt=10)
        self.abrir_turno()
        self.j = self.janela()
        self.j.ent_codigo.setFocus()

    def esc(self):
        self.j.esc_caixa()
        self.aplicacao.processEvents()

    def test_esc_sem_nada_pendente_volta_ao_campo_da_posicao_com_os_cartoes_atualizados(self):
        vid, _ = self.ctx.caixa.abrir_mesa(5, comanda=False)
        self.ctx.caixa.adicionar_item(vid, self.skol, 1)
        self.esc()
        self.assertIs(self.j.focusWidget(), self.j.ent_pos)
        self.assertEqual([t["chave"] for t in self.j.cartoes.tiles()], ["0", "M5"])      # cartões recarregados

    def test_esc_primeiro_limpa_o_digitado_e_so_o_segundo_volta_a_posicao(self):
        self.j.ent_codigo.setText("10")
        self.esc()
        self.assertEqual(self.j.ent_codigo.text(), "")
        self.assertIs(self.j.focusWidget(), self.j.ent_codigo)
        self.esc()
        self.assertIs(self.j.focusWidget(), self.j.ent_pos)

    def test_esc_no_campo_da_posicao_volta_ao_balcao_e_a_mesa_continua_aberta(self):
        self.j.ent_pos.setText("M5")
        self.j.btn_chamar.click()
        self.j.ent_codigo.setText("10")
        self.j.btn_lancar.click()
        mesa_id = self.j.venda_id
        self.esc()                                   # nada pendente: vai marcar comanda
        self.assertIs(self.j.focusWidget(), self.j.ent_pos)
        self.esc()                                   # no campo da posição: balcão
        self.assertIsNone(self.j.venda_id)
        self.assertEqual(self.ctx.caixa.obter(mesa_id)["status"], "aberta")
        self.assertIn("continua aberta", self.j.lbl_status.text())

    def test_esc_nos_cartoes_volta_ao_campo_da_posicao(self):
        self.j.cartoes.focar("0")
        self.assertIs(self.j.focusWidget(), self.j.cartoes.grade)
        self.esc()
        self.assertIs(self.j.focusWidget(), self.j.ent_pos)

    def test_esc_continua_descartando_a_comissao_digitada(self):
        self.j.modo_comissao = True
        self.esc()
        self.assertFalse(self.j.modo_comissao)

    def test_tecla_esc_de_verdade_passa_pelo_atalho_da_janela(self):
        self.j.activateWindow()
        self.j.ent_codigo.setFocus()
        self.aplicacao.processEvents()
        QTest.keyClick(self.j.ent_codigo, Qt.Key_Escape)
        self.aplicacao.processEvents()
        self.assertIs(self.j.focusWidget(), self.j.ent_pos)

    def test_f4_faz_o_mesmo_que_esc_sem_pendencia(self):
        self.j.foco_posicao()
        self.assertIs(self.j.focusWidget(), self.j.ent_pos)


@unittest.skipIf(BaseCaixaQt is None, "PySide6 indisponível")
class TesteTrocaDeComandaPelasSetas(BaseCaixaQt if BaseCaixaQt else object):
    def setUp(self):
        super().setUp()
        skol = self.novo_produto("SKOL", 800, codigo="10", estoque=True, qt=20)
        self.abrir_turno()
        for pos, comanda in ((5, False), (12, True), (13, True)):
            vid, _ = self.ctx.caixa.abrir_mesa(pos, comanda=comanda)
            self.ctx.caixa.adicionar_item(vid, skol, 1)
        self.j = self.janela()
        self.j.activateWindow()
        self.j.ent_codigo.setFocus()
        self.aplicacao.processEvents()                   # os atalhos da janela só valem com ela ativa

    def tecla(self, widget, tecla):
        QTest.keyClick(widget, tecla)
        self.aplicacao.processEvents()

    def test_setas_no_codigo_vazio_andam_pela_lista_dos_cartoes_e_esc_volta(self):
        self.assertEqual(self.j._chave_atual(), "0")
        self.tecla(self.j.ent_codigo, Qt.Key_Right)
        self.assertEqual(self.j._chave_atual(), "M5")
        self.tecla(self.j.ent_codigo, Qt.Key_Right)
        self.tecla(self.j.ent_codigo, Qt.Key_Right)
        self.assertEqual(self.j._chave_atual(), "13")
        self.assertIs(self.j.focusWidget(), self.j.ent_codigo)               # o foco fica pronto para lançar
        self.tecla(self.j.ent_codigo, Qt.Key_Right)                          # na ponta não dá a volta
        self.assertEqual(self.j._chave_atual(), "13")
        self.assertIn("última", self.j.lbl_status.text())
        self.tecla(self.j.ent_codigo, Qt.Key_Left)
        self.assertEqual(self.j._chave_atual(), "12")
        self.j.esc_caixa()                                                   # Esc volta ao marcar comanda
        self.assertIs(self.j.focusWidget(), self.j.ent_pos)

    def test_seta_com_texto_digitado_continua_movendo_o_cursor(self):
        self.j.ent_codigo.setText("ab")
        self.tecla(self.j.ent_codigo, Qt.Key_Left)
        self.assertEqual(self.j._chave_atual(), "0")                         # não trocou de comanda
        self.assertEqual(self.j.ent_codigo.text(), "ab")

    def test_botoes_e_pgup_pgdn_fazem_o_mesmo(self):
        self.j.btn_proxima.click()
        self.assertEqual(self.j._chave_atual(), "M5")
        self.tecla(self.j.ent_codigo, Qt.Key_PageDown)
        self.assertEqual(self.j._chave_atual(), "12")
        self.tecla(self.j.ent_codigo, Qt.Key_PageUp)
        self.j.btn_anterior.click()
        self.assertEqual(self.j._chave_atual(), "0")

    def test_navegacao_respeita_a_aba_escolhida(self):
        self.j.cartoes._escolher_aba("Abertas")                              # sem o balcão
        self.j.navegar_comanda(1)
        self.assertEqual(self.j._chave_atual(), "M5")


@unittest.skipIf(BaseCaixaQt is None, "PySide6 indisponível")
class TesteVisualNoiteDaBoate(BaseCaixaQt if BaseCaixaQt else object):
    def test_caixa_usa_o_estilo_noturno_no_modo_escuro_e_o_claro_no_claro(self):
        j = self.janela()
        self.assertIn("#0a1029", j.styleSheet())
        self.banco.cfg_set("tema_visual", "claro")
        j.carregar_mesas()
        self.assertNotIn("#0a1029", j.styleSheet())
        self.banco.cfg_set("tema_visual", "escuro")
        j.carregar_mesas()
        self.assertIn("#0a1029", j.styleSheet())

    def test_comissao_marcada_tem_cor_de_fundo_e_de_texto_por_modo(self):
        from src.ui_qt.caixa import LINHAS_COMISSAO
        for modo, (a_pagar, paga, texto) in LINHAS_COMISSAO.items():
            self.assertTrue(all(c.startswith("#") and len(c) == 7 for c in (a_pagar, paga, texto)), modo)

    def test_cliente_alterna_claro_e_escuro_no_menu_e_o_caixa_aberto_acompanha(self):
        from src.ui_qt.app import App, JanelaPrincipal
        app = App(self.banco, self.aplicacao)
        app.ctx = self.ctx
        menu = JanelaPrincipal(app)
        self.addCleanup(menu.deleteLater)
        caixa = self.janela()
        menu.janelas["caixa"] = caixa
        self.assertIn("claro", menu.btn_tema.text())            # em uso: escuro; o botão oferece o claro
        menu.btn_tema.click()
        self.assertEqual(self.banco.cfg("tema_visual"), "claro")
        self.assertIn("escuro", menu.btn_tema.text())
        self.assertNotIn("#0a1029", caixa.styleSheet())
        menu.btn_tema.click()
        self.assertEqual(self.banco.cfg("tema_visual"), "escuro")
        self.assertIn("#0a1029", caixa.styleSheet())

    def test_menu_mostra_os_numeros_da_noite(self):
        from src.ui_qt.app import App, JanelaPrincipal
        skol = self.novo_produto("SKOL", 800, codigo="10", estoque=True, qt=10)
        self.abrir_turno()
        for pos, comanda in ((5, False), (12, True)):
            vid, _ = self.ctx.caixa.abrir_mesa(pos, comanda=comanda)
            self.ctx.caixa.adicionar_item(vid, skol, 1)
        self.ctx.caixa.enviar_conta(self.ctx.caixa.abrir_mesa(12, comanda=True)[0])
        app = App(self.banco, self.aplicacao)
        app.ctx = self.ctx
        menu = JanelaPrincipal(app)
        self.addCleanup(menu.deleteLater)
        menu._atualizar_noite()
        self.assertEqual(menu.kpis["abertas"][1].text(), "2")
        self.assertEqual(menu.kpis["acertos"][1].text(), "1")
        self.assertEqual(menu.kpis["aberto"][1].text(), "R$ 17,60")
        self.banco.cfg_set("usar_mesas", "N")
        menu._atualizar_noite()
        self.assertTrue(menu.faixa_noite.isHidden())


if __name__ == "__main__":
    unittest.main()
