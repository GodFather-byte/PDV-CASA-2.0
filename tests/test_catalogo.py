"""Produtos prontos (catálogo de adega): conteúdo, cadastro em lote e vínculo do código de barras."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.controllers.catalogo import CATALOGO_ADEGA, SUBGRUPOS, CatalogoController, conferir_catalogo
from src.controllers.contexto import Contexto
from src.core.erros import ErroNegocio, ErroValidacao
from src.fiscal import ncm
from tests.base import BaseTeste


def indice(nome):
    return next(i for i, item in enumerate(CATALOGO_ADEGA) if item.nome == nome)


class TestCatalogo(BaseTeste):
    def setUp(self):
        super().setUp()
        self.cat = CatalogoController(self.banco, self.operador_adm())

    def produto(self, nome):
        return self.banco.um("SELECT p.*, s.nome AS subgrupo FROM produtos p JOIN subgrupos s ON s.id = p.subgrupo_id "
                             "WHERE p.nome = ?", (nome,))

    def test_catalogo_sem_problemas_e_com_todos_os_subgrupos(self):
        self.assertEqual(conferir_catalogo(), [])
        self.assertGreaterEqual(len(CATALOGO_ADEGA), 200)
        self.assertEqual({i.subgrupo for i in CATALOGO_ADEGA}, set(SUBGRUPOS))

    def test_ncm_do_catalogo_bate_com_a_sugestao_pelo_nome(self):
        """O catálogo e a sugestão do cadastro manual não podem discordar (o dono veria dois NCM para o mesmo produto)."""
        divergentes = [i.nome for i in CATALOGO_ADEGA if (ncm.sugerir(i.nome) or ("",))[0] != i.ncm]
        self.assertEqual(divergentes, [])

    def test_adiciona_com_preco_subgrupo_ncm_e_sem_codigo_de_barras(self):
        skol, red_label = indice("CERVEJA SKOL LATA 350ML"), indice("WHISKY JOHNNIE WALKER RED LABEL 1L")
        resultado = self.cat.adicionar({skol: 450, red_label: 15990})
        self.assertEqual(resultado, {"criados": 2, "ja_tinha": 0})
        cerveja = self.produto("CERVEJA SKOL LATA 350ML")
        self.assertEqual((cerveja["preco_cent"], cerveja["subgrupo"], cerveja["ncm"]), (450, "CERVEJAS", "22030000"))
        self.assertFalse(cerveja["cbarra"])
        self.assertEqual(self.produto("WHISKY JOHNNIE WALKER RED LABEL 1L")["ncm"], "22083020")

    def test_nao_mexe_no_que_a_loja_ja_tem(self):
        self.novo_produto(nome="CERVEJA SKOL LATA 350ML", preco=500)
        skol, coca = indice("CERVEJA SKOL LATA 350ML"), indice("REFRIGERANTE COCA-COLA LATA 350ML")
        self.assertTrue(next(i for i in self.cat.itens(busca="skol lata 350") if i["indice"] == skol)["ja_cadastrado"])
        resultado = self.cat.adicionar({skol: 999, coca: 600})
        self.assertEqual(resultado, {"criados": 1, "ja_tinha": 1})
        self.assertEqual(self.produto("CERVEJA SKOL LATA 350ML")["preco_cent"], 500)
        self.assertEqual(self.cat.adicionar({coca: 700}), {"criados": 0, "ja_tinha": 1})

    def test_exige_preco_e_item_valido(self):
        with self.assertRaises(ErroNegocio):
            self.cat.adicionar({})
        with self.assertRaises(ErroValidacao):
            self.cat.adicionar({indice("GELO EM CUBO 5KG"): 0})
        with self.assertRaises(ErroNegocio):
            self.cat.adicionar({len(CATALOGO_ADEGA): 100})
        self.assertIsNone(self.produto("GELO EM CUBO 5KG"))

    def test_busca_sem_acento_e_por_subgrupo(self):
        self.assertTrue(all(i["subgrupo"] == "ENERGÉTICOS" for i in self.cat.itens("ENERGÉTICOS")))
        nomes = [i["nome"] for i in self.cat.itens(busca="cachaça 51")]
        self.assertEqual(nomes, ["CACHACA 51 965ML"])

    def test_vincula_codigo_de_barras(self):
        self.cat.adicionar({indice("CERVEJA SKOL LATA 350ML"): 450, indice("ENERGETICO RED BULL 250ML"): 1200})
        skol = self.produto("CERVEJA SKOL LATA 350ML")["id"]
        red_bull = self.produto("ENERGETICO RED BULL 250ML")["id"]
        with self.assertRaises(ErroValidacao):
            self.cat.vincular_codigo_barras(skol, "123")
        self.cat.vincular_codigo_barras(skol, " 7891149 103003 ")
        self.assertEqual(self.produto("CERVEJA SKOL LATA 350ML")["cbarra"], "7891149103003")
        with self.assertRaises(ErroNegocio):
            self.cat.vincular_codigo_barras(red_bull, "7891149103003")
        nomes = [p["nome"] for p in self.cat.sem_codigo_barras()]
        self.assertIn("ENERGETICO RED BULL 250ML", nomes)
        self.assertNotIn("CERVEJA SKOL LATA 350ML", nomes)


class TestCatalogoQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())

    def test_digitar_preco_marca_e_adicionar_cadastra(self):
        from src.ui_qt.catalogo import JanelaCatalogo
        chamado = []
        janela = JanelaCatalogo(self.ctx, ao_adicionar=lambda: chamado.append(True))
        self.addCleanup(janela.close)
        janela.ent_busca.setText("cerveja skol lata 269")
        self.assertEqual(janela.tabela.rowCount(), 1)
        janela.tabela.item(0, janela.COL_PRECO).setText("3,5")
        self.assertEqual(janela.tabela.item(0, janela.COL_PRECO).text(), "3,50")
        self.assertTrue(janela.btn_adicionar.isEnabled())
        janela.ent_busca.setText("")                    # trocar o filtro não perde o preço digitado
        self.assertEqual(len(janela.escolhidos), 1)
        self.assertTrue(janela.adicionar())
        self.assertEqual(chamado, [True])
        produto = self.banco.um("SELECT preco_cent FROM produtos WHERE nome = 'CERVEJA SKOL LATA 269ML'")
        self.assertEqual(produto["preco_cent"], 350)
        janela.ent_busca.setText("cerveja skol lata 269")
        self.assertIn("já cadastrado", janela.tabela.item(0, janela.COL_PRODUTO).text())
        self.assertFalse(janela.tabela.item(0, janela.COL_PRECO).flags() & Qt.ItemIsEditable)

    def test_preco_invalido_nao_marca(self):
        from src.ui_qt.catalogo import JanelaCatalogo
        janela = JanelaCatalogo(self.ctx)
        self.addCleanup(janela.close)
        janela.tabela.item(0, janela.COL_PRECO).setText("abc")
        self.assertEqual(janela.escolhidos, {})
        self.assertIn("Preço inválido", janela.mensagem.text())
        self.assertFalse(janela.btn_adicionar.isEnabled())

    def test_gravar_codigo_pelo_leitor(self):
        from src.ui_qt.catalogo import JanelaCodigosBarras
        CatalogoController(self.banco, self.ctx.operador_id).adicionar({indice("GELO EM CUBO 5KG"): 1500})
        janela = JanelaCodigosBarras(self.ctx)
        self.addCleanup(janela.close)
        janela.ent_busca.setText("gelo")
        self.assertEqual(janela.lista.count(), 1)
        janela.ent_codigo.setText("7898000000017")
        self.assertTrue(janela.gravar())
        self.assertEqual(janela.lista.count(), 0)
        self.assertEqual(self.banco.valor("SELECT cbarra FROM produtos WHERE nome = 'GELO EM CUBO 5KG'"), "7898000000017")

    def test_tela_de_importacao_abre_o_catalogo(self):
        from src.ui_qt.importar_produtos import JanelaImportarProdutos
        janela = JanelaImportarProdutos(self.ctx)
        self.addCleanup(janela.close)
        catalogo = janela.abrir_catalogo()
        self.addCleanup(catalogo.close)
        self.assertEqual(catalogo.windowTitle(), "Produtos prontos")
