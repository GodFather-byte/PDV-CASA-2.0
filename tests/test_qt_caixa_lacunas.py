"""Caixa Qt: lacunas fechadas em relação ao Tk (leitor F3, nomear comanda, Leitura X, Redução Z, fila e sangria F7)."""
from unittest.mock import patch

from PySide6.QtGui import QShortcut

from src.core.erros import ErroPermissao
from tests.test_qt_caixa import BaseCaixaQt


class TestCaixaQtLacunas(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.abrir_turno()
        self.cerveja = self.novo_produto("CERVEJA", 800, codigo="71")
        self.j = self.janela()

    def chamar(self, pos="M1"):
        self.j.ent_pos.setText(pos)
        self.j.btn_chamar.click()
        return self.j.venda_id

    def atalho(self, tecla):
        return next(a for a in self.j.findChildren(QShortcut) if a.key().toString() == tecla)

    def test_acoes_do_menu(self):
        for chave in ("nomear", "leitor", "leitura_x", "reducao_z", "fila"):
            self.assertIn(chave, self.j.acoes)
        self.assertIn("F7", self.j.acoes["sangria"].text())
        self.assertIn("F3", self.j.acoes["leitor"].text())

    def test_f3_modo_leitor_lanca_uma_unidade(self):
        self.j.leitor = False
        self.atalho("F3").activated.emit()
        self.assertTrue(self.j.leitor)
        self.assertEqual(self.j.lbl_leitor.text(), "LEITOR ÓPTICO ATIVO")
        self.lancar(self.j, "71", "5")                          # quantidade digitada é ignorada no modo leitor
        self.assertEqual(self.ctx.caixa.itens(self.j.venda_id)[0]["quantidade"], 1)
        self.lancar(self.j, "3*71", "1")                        # n*código continua valendo
        self.assertEqual([i["quantidade"] for i in self.ctx.caixa.itens(self.j.venda_id)], [1, 3])
        self.j.acoes["leitor"].trigger()
        self.assertFalse(self.j.leitor)
        self.assertEqual(self.j.lbl_leitor.text(), "")
        self.lancar(self.j, "71", "2")
        self.assertEqual(self.ctx.caixa.itens(self.j.venda_id)[-1]["quantidade"], 2)

    def test_f7_chama_a_sangria(self):
        with patch.object(self.j, "_pode_operar", return_value=False) as pode:
            self.atalho("F7").activated.emit()
        pode.assert_called_once_with()                          # sangria() começa conferindo se pode operar

    def test_nomear_comanda(self):
        self.j.acoes["nomear"].trigger()                        # balcão: só avisa
        self.assertIn("comanda ou mesa", self.j.dialogos.avisos[-1])
        vid = self.chamar("C3")
        self.j.dialogos.textos = ["Carlos"]
        self.j.acoes["nomear"].trigger()
        self.assertEqual(self.ctx.caixa.obter(vid)["apelido"], "Carlos")
        self.j.dialogos.textos = [""]
        self.j.nomear_comanda()
        self.assertFalse(self.ctx.caixa.obter(vid)["apelido"])

    def test_leitura_x_e_reducao_z_usam_a_impressao(self):
        with patch.object(self.ctx.impressao, "leitura_x", return_value="X") as x, \
                patch.object(self.ctx.impressao, "reducao_z", return_value="Z") as z, \
                patch.object(self.j, "_emitir") as emitir:
            self.j.acoes["leitura_x"].trigger()
            self.j.acoes["reducao_z"].trigger()
        x.assert_called_once_with(self.ctx.turnos.atual()["id"])
        z.assert_called_once_with()
        self.assertEqual([c.args[:3] for c in emitir.call_args_list],
                         [("Leitura X", "X", "leitura_x"), ("Redução Z", "Z", "reducao_z")])
        self.assertEqual([c.kwargs["tipo"] for c in emitir.call_args_list], ["fechamento", "relatorio"])

    def test_fila_abre_uma_vez_e_respeita_permissao(self):
        with patch("src.ui_qt.fila_impressao.JanelaFilaImpressao._exigir_acesso",
                   side_effect=ErroPermissao("Sem permissão para a fila.")):
            self.j.acoes["fila"].trigger()
        self.assertIn("Sem permissão", self.j.dialogos.avisos[-1])
        self.assertIsNone(self.j.janela_fila)
        with patch("src.ui_qt.fila_impressao.JanelaFilaImpressao._exigir_acesso"):
            self.j.abrir_fila()
            primeira = self.j.janela_fila
            self.assertTrue(primeira.isVisible())
            self.j.abrir_fila()
            self.assertIs(self.j.janela_fila, primeira)
        primeira.close()
