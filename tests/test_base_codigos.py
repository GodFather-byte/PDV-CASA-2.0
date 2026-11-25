"""Produto novo no leitor: base de produtos por código de barras (vai com o programa, funciona sem internet), preço de
custo no cadastro rápido e a tela única de cadastro."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.controllers import base_codigos as base
from src.controllers.produto_controller import ProdutoController
from tests.base import BaseTeste

SKOL = "7891149103102"


class TesteBase(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.arquivo = Path(pasta.name) / "base.csv"

    def test_digito_verificador(self):
        self.assertTrue(base.digito_ok(SKOL))
        self.assertTrue(base.digito_ok("96385074"))                 # EAN-8
        self.assertTrue(base.digito_ok("036000291452"))             # UPC-12
        self.assertFalse(base.digito_ok("7891149103103"))           # último número errado
        self.assertFalse(base.digito_ok("123"))

    def test_upc_e_ean_viram_a_mesma_chave(self):
        self.assertEqual(base.normalizar("036000291452"), base.normalizar("0036000291452"))
        self.assertEqual(base.normalizar("abc"), "")

    def test_le_csv_descarta_codigo_inventado_e_sem_nome(self):
        texto = ("codigo_barras;nome;categoria;ncm\n"
                 f"{SKOL};  cerveja skol   lata 350ml ;cervejas;2203.00.00\n"
                 "7891149103103;CODIGO ERRADO;;\n"
                 "7894900011517;;;\n")
        validas, descartes = base.ler_csv(texto)
        self.assertEqual(validas, [{"codigo_barras": SKOL, "nome": "CERVEJA SKOL LATA 350ML", "categoria": "CERVEJAS",
                                    "ncm": "22030000"}])
        self.assertEqual(len(descartes), 2)

    def test_aceita_virgula_e_recusa_sem_colunas(self):
        validas, _ = base.ler_csv(f"codigo_barras,nome\n{SKOL},SKOL\n")
        self.assertEqual(len(validas), 1)
        with self.assertRaises(ValueError):
            base.ler_csv("codigo;descricao\n1;x\n")

    def test_juntar_nao_duplica_e_completa_o_que_falta(self):
        existentes = [{"codigo_barras": SKOL, "nome": "SKOL", "categoria": "", "ncm": ""}]
        novas = [{"codigo_barras": SKOL, "nome": "OUTRO NOME", "categoria": "CERVEJAS", "ncm": "22030000"},
                 {"codigo_barras": "96385074", "nome": "AGUA", "categoria": "", "ncm": ""}]
        linhas, entraram, repetidas = base.juntar(existentes, novas)
        self.assertEqual((entraram, repetidas), (1, 1))
        skol = next(l for l in linhas if l["codigo_barras"] == SKOL)
        self.assertEqual((skol["nome"], skol["categoria"], skol["ncm"]), ("SKOL", "CERVEJAS", "22030000"))

    def test_procurar_no_arquivo(self):
        self.arquivo.write_text(base.escrever_csv([{"codigo_barras": SKOL, "nome": "SKOL", "categoria": "", "ncm": ""}]),
                                encoding="utf-8")
        self.assertEqual(base.procurar(SKOL, self.arquivo)["nome"], "SKOL")
        self.assertIsNone(base.procurar("96385074", self.arquivo))
        self.assertEqual(base.quantidade(Path(self.arquivo.parent) / "nao_existe.csv"), 0)

    def test_arquivo_que_vai_no_programa_e_valido(self):
        base.esquecer_cache()
        self.addCleanup(base.esquecer_cache)
        texto = base.caminho_padrao().read_text(encoding="utf-8")
        self.assertTrue(texto.startswith("codigo_barras;nome;categoria;ncm"))
        _, descartes = base.ler_csv(texto)
        self.assertEqual(descartes, [], "a base do programa só pode ter linhas válidas")

    def test_ferramenta_junta_e_grava(self):
        from tools import base_codigos as ferramenta
        destino = Path(self.arquivo.parent) / "dados.csv"
        lista = Path(self.arquivo.parent) / "grok.csv"
        lista.write_text(f"codigo_barras;nome\n{SKOL};skol lata\n7891149103103;falso\n", encoding="utf-8")
        with mock.patch.object(base, "caminho_padrao", return_value=destino):
            self.assertEqual(ferramenta.main(["juntar", str(lista)]), 0)
            self.assertEqual(ferramenta.main(["juntar", str(lista)]), 0)    # de novo: nada duplica
        linhas, _ = base.ler_csv(destino.read_text(encoding="utf-8"))
        self.assertEqual([l["nome"] for l in linhas], ["SKOL LATA"])


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

    def test_da_base_vem_nome_e_categoria_e_o_foco_vai_no_preco(self):
        dlg = self.novo({"nome": "SKOL LATA", "categoria": "CERVEJAS", "fonte": "base"}, categoria_padrao=2)
        self.addCleanup(dlg.close)
        self.assertEqual((dlg.ent_nome.text(), dlg.cmb_categoria.currentData()), ("SKOL LATA", 1))
        self.assertIn("base de produtos", dlg.lbl_fonte.text())
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
    def test_bipar_produto_da_base_ativa_com_custo_sem_ir_a_internet(self):
        j = self.janela()
        self.ctx.banco.definir_operador_auditoria(self.ctx.operador_id)
        linha = {"codigo_barras": SKOL, "nome": "CERVEJA SKOL LATA 350ML", "categoria": "", "ncm": "22030000"}
        sub = self.banco.valor("SELECT MIN(id) FROM subgrupos")
        j.dialogos = mock.Mock()
        j.dialogos.confirmar.return_value = True
        j.dialogos.produto_novo.return_value = {"nome": "CERVEJA SKOL LATA 350ML", "subgrupo_id": sub,
                                                "preco_cent": 600, "preco_gelada_cent": 0, "custo_cent": 350,
                                                "estoque": 48.0}
        with mock.patch.object(base, "procurar", return_value=linha), \
                mock.patch.object(type(j), "_buscar_produto_na_internet") as internet:
            p = j._cadastro_rapido(SKOL)
        internet.assert_not_called()
        self.assertIn("base de produtos", j.dialogos.confirmar.call_args.args[1])
        sugestao = j.dialogos.produto_novo.call_args.args[1]
        self.assertEqual((sugestao["fonte"], sugestao["nome"]), ("base", "CERVEJA SKOL LATA 350ML"))
        self.assertTrue(j.dialogos.produto_novo.call_args.kwargs["com_custo"])
        salvo = self.banco.um("SELECT preco_cent, custo_medio_cent, ncm, qt_atual, cbarra FROM produtos WHERE id = ?",
                              (p["id"],))
        self.assertEqual(tuple(salvo), (600, 350, "22030000", 48, SKOL))

    def test_fora_da_base_procura_na_internet(self):
        j = self.janela()
        j.dialogos = mock.Mock()
        j.dialogos.confirmar.return_value = True
        j.dialogos.produto_novo.return_value = None
        with mock.patch.object(base, "procurar", return_value=None), \
                mock.patch.object(type(j), "_buscar_produto_na_internet",
                                  return_value={"nome": "AGUA X", "foto": None}) as internet:
            self.assertIsNone(j._cadastro_rapido("96385074"))
        internet.assert_called_once()
        self.assertEqual(j.dialogos.produto_novo.call_args.args[1]["fonte"], "internet")
