"""Will Hotel mostra só o que é de hotel: depois da entrada abre a recepção (não o caixa de PDV), o menu esconde o que é
de boate/adega e os botões falam a língua do hotel. O caixa continua para receber a conta e para o turno."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
from unittest.mock import patch

from src.core import edicao
from tests.test_qt_app import BaseQt


class TesteHotelSoHotel(BaseQt):
    def setUp(self):
        super().setUp()
        ambiente = patch.dict(os.environ, {"PDV_EDICAO": "willhotel"})
        ambiente.start()
        self.addCleanup(ambiente.stop)
        edicao.preparar(self.banco)
        consultar = patch("src.ui_qt.app.JanelaPrincipal.consultar_atualizacoes")
        consultar.start()
        self.addCleanup(consultar.stop)

    def entrar(self, operador):
        app = self.app()
        app.login = SimpleNamespace(operador=operador, deleteLater=lambda: None)
        app._autenticado()
        self.janela(app.principal)
        for janela in list(app.principal.janelas.values()):
            self.janela(janela)
        return app.principal

    def test_entrada_abre_a_recepcao_e_nao_o_caixa(self):
        principal = self.entrar(self.ctx.acesso.autenticar("ADM", "ADM"))
        self.assertIn("hotel", principal.janelas)
        self.assertNotIn("caixa", principal.janelas)

    def test_operador_so_de_caixa_tambem_comeca_na_recepcao(self):
        operador = self.ctx.acesso.autenticar("ADM", "ADM")
        with patch.object(type(operador), "so_caixa", property(lambda _: True)):
            principal = self.entrar(operador)
        self.assertIn("hotel", principal.janelas)
        self.assertNotIn("caixa", principal.janelas)

    def test_menu_so_com_o_que_e_de_hotel_e_com_rotulos_de_hotel(self):
        principal = self.entrar(self.ctx.acesso.autenticar("ADM", "ADM"))
        visiveis = {c for c, b in principal.botoes.items() if b.parent() is not None}
        for chave in ("cozinha", "promocoes", "retornaveis", "porteiro", "quartos", "composicao", "devolucoes"):
            self.assertNotIn(chave, visiveis, chave)
        self.assertEqual(principal.botoes["hotel"].text(), "Recepção do hotel")
        self.assertEqual(principal.botoes["caixa"].text(), "Caixa • receber contas e turno")
        self.assertEqual(list(principal.atalhos), ["hotel", "caixa", "produtos"])

    def test_recepcao_mostra_o_turno_do_caixa(self):
        principal = self.entrar(self.ctx.acesso.autenticar("ADM", "ADM"))
        recepcao = principal.janelas["hotel"]
        recepcao.atualizar()
        self.assertIn("turno fechado", recepcao.lbl_turno.text())


class TesteOutrasEdicoesNaoMudam(BaseQt):
    def test_willpdv_continua_com_o_menu_e_os_rotulos_de_sempre(self):
        ed = edicao.EDICOES["willpdv"]
        self.assertEqual((ed.inicio, ed.rotulos), ("", {}))
