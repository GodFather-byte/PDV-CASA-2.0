"""Produto novo no leitor: preço de custo no cadastro rápido e a tela única de cadastro."""
import os
import unittest
from unittest import mock

from src.controllers.produto_controller import ProdutoController
from tests.base import BaseTeste

SKOL = "7891149103102"


class TesteCadastroRapidoComCusto(BaseTeste):
    def setUp(self):
        super().setUp()
        self.prod = ProdutoController(self.banco)
        self.sub = self.banco.valor("SELECT MIN(id) FROM subgrupos")
        self.adm = self.operador_adm()

    def test_gerente_grava_custo_e_ncm(self):
        self.banco.definir_operador_auditoria(self.adm)
        p = self.prod.cadastrar_rapido(SKOL, "SKOL LATA", 500, self.sub, estoque=12, operador_id=self.adm,
                                       custo_cent=320, ncm="22030000")
        linha = self.banco.um("SELECT custo_medio_cent, ncm, qt_atual FROM produtos WHERE id = ?", (p["id"],))
        self.assertEqual((linha["custo_medio_cent"], linha["ncm"], linha["qt_atual"]), (320, "22030000", 12))

    def test_custo_negativo_recusa(self):
        from src.core.erros import ErroNegocio
        with self.assertRaises(ErroNegocio):
            self.prod.cadastrar_rapido(SKOL, "SKOL", 500, self.sub, custo_cent=-1)


class TesteTela(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from src.ui_qt.caixa import ler_dinheiro
        from src.ui_qt.produto_novo import DialogoProdutoNovo
        self.categorias = [(1, "CERVEJAS - BEBIDAS", "CERVEJAS"), (2, "GELO - OUTROS", "GELO")]
        self.novo = lambda sugestao, **k: DialogoProdutoNovo(None, SKOL, sugestao, self.categorias, ler_dinheiro, **k)

    def test_nome_da_internet_vem_preenchido_e_categoria_padrao(self):
        dlg = self.novo({"nome": "SKOL LATA", "fonte": "internet"}, categoria_padrao=1)
        self.addCleanup(dlg.close)
        self.assertEqual((dlg.ent_nome.text(), dlg.cmb_categoria.currentData()), ("SKOL LATA", 1))
        self.assertIn("internet", dlg.lbl_fonte.text())
        dlg.ent_preco.setText("5,00")
        dlg.ent_custo.setText("3,20")
        dlg.ent_qtd.setText("24")
        dlg.confirmar()
        self.assertEqual(dlg.resultado, {"nome": "SKOL LATA", "subgrupo_id": 1, "preco_cent": 500,
                                         "preco_gelada_cent": 0, "custo_cent": 320, "estoque": 24.0})

    def test_sem_preco_ou_sem_nome_nao_cadastra(self):
        dlg = self.novo({"fonte": ""})
        self.addCleanup(dlg.close)
        dlg.confirmar()
        self.assertIsNone(dlg.resultado)
        self.assertIn("nome", dlg.lbl_erro.text())
        dlg.ent_nome.setText("X")
        dlg.confirmar()
        self.assertIsNone(dlg.resultado)
        self.assertIn("Preço de venda", dlg.lbl_erro.text())

    def test_custo_maior_que_venda_avisa_uma_vez(self):
        dlg = self.novo({"nome": "X", "fonte": "internet"})
        self.addCleanup(dlg.close)
        dlg.ent_preco.setText("5")
        dlg.ent_custo.setText("6")
        dlg.confirmar()
        self.assertIsNone(dlg.resultado)
        dlg.confirmar()
        self.assertEqual(dlg.resultado["custo_cent"], 600)

    def test_operador_sem_nivel_nao_ve_custo_e_sem_gelada(self):
        dlg = self.novo({"nome": "X"}, com_custo=False, com_gelada=False)
        self.addCleanup(dlg.close)
        self.assertIsNone(dlg.ent_custo)
        self.assertIsNone(dlg.ent_gelada)


if __name__ == "__main__":
    unittest.main()


from tests.test_qt_caixa import BaseCaixaQt   # noqa: E402


class TesteFluxoNoCaixa(BaseCaixaQt):
    def test_bipar_produto_novo_cadastra_com_custo(self):
        j = self.janela()
        self.ctx.banco.definir_operador_auditoria(self.ctx.operador_id)
        sub = self.banco.valor("SELECT MIN(id) FROM subgrupos")
        j.dialogos = mock.Mock()
        j.dialogos.confirmar.return_value = True
        j.dialogos.produto_novo.return_value = {"nome": "CERVEJA SKOL LATA 350ML", "subgrupo_id": sub,
                                                "preco_cent": 600, "preco_gelada_cent": 0, "custo_cent": 350,
                                                "estoque": 48.0}
        with mock.patch.object(type(j), "_buscar_produto_na_internet",
                               return_value={"nome": "CERVEJA SKOL LATA 350ML", "foto": None}):
            p = j._cadastro_rapido(SKOL)
        self.assertTrue(j.dialogos.produto_novo.call_args.kwargs["com_custo"])
        salvo = self.banco.um("SELECT preco_cent, custo_medio_cent, qt_atual, cbarra FROM produtos WHERE id = ?",
                              (p["id"],))
        self.assertEqual(tuple(salvo), (600, 350, 48, SKOL))

    def test_desistir_na_tela_nao_cadastra(self):
        j = self.janela()
        j.dialogos = mock.Mock()
        j.dialogos.confirmar.return_value = True
        j.dialogos.produto_novo.return_value = None
        with mock.patch.object(type(j), "_buscar_produto_na_internet",
                               return_value={"nome": "AGUA X", "foto": None}) as internet:
            self.assertIsNone(j._cadastro_rapido("96385074"))
        internet.assert_called_once()
        self.assertEqual(j.dialogos.produto_novo.call_args.args[1]["fonte"], "internet")
        self.assertIsNone(self.ctx.produtos.buscar_codigo("96385074"))
