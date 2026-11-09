"""Custo médio, lucro da nota e relatórios. Dinheiro em centavos."""
from __future__ import annotations

import unittest

from src.controllers.estoque_controller import EstoqueController
from src.controllers.relatorio_controller import RelatorioController
from src.core import custo_lucro
from src.core.erros import ErroPermissao
from src.core.relatorio import Coluna, Relatorio, para_pdf
from tests.test_caixa import BaseCaixa


class TesteContas(unittest.TestCase):
    def test_media_margem_e_preco_sugerido_sem_float(self):
        self.assertEqual(custo_lucro.custo_medio_ponderado(10, 500, 10, 10000), 750)
        self.assertEqual(custo_lucro.custo_medio_ponderado(0, 0, 4, 2000), 500)
        self.assertEqual(custo_lucro.preco_pela_margem(600, 40), 1000)
        self.assertEqual(custo_lucro.lucro_cent(120000, 50000), 70000)
        self.assertEqual(custo_lucro.margem_texto(120000, 50000), "58,33%")
        self.assertIsInstance(custo_lucro.preco_pela_margem(14990, 30), int)

    def test_fifo_atribui_a_primeira_nota(self):
        compras = [{"id": 1, "qtd": 10, "custo_cent": 5000}, {"id": 2, "qtd": 10, "custo_cent": 8000}]
        vendas = [{"qtd": 4, "receita_cent": 6000}, {"qtd": 8, "receita_cent": 16000}]
        alocado = custo_lucro.alocar_fifo(compras, vendas)
        self.assertEqual(alocado[1]["qtd_vendida"], 10)
        self.assertEqual(alocado[2]["qtd_vendida"], 2)
        self.assertEqual(alocado[1]["custo_cent"], 5000)
        self.assertGreater(alocado[1]["lucro_cent"], 0)


class TesteNotaERelatorio(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.definir_operador_auditoria(self.adm)
        self.est = EstoqueController(self.banco, self.adm)
        self.banco.executar("UPDATE produtos SET preco_cent = 1200, custo_medio_cent = 500, ult_preco_cent = 500 "
                            "WHERE id = ?", (self.skol,))

    def test_compra_atualiza_media_e_a_nota_mostra_previsto_e_realizado(self):
        self.banco.executar("UPDATE produtos SET qt_atual = 0, custo_medio_cent = 0 WHERE id = ?", (self.skol,))
        nota = self.est.criar_lancamento("compra", fornecedor_id=self._fornecedor(), nota_fiscal="NF-1")
        self.est.adicionar_item(nota, self.skol, 10, 5000)
        self.assertEqual(self.banco.valor("SELECT custo_medio_cent FROM produtos WHERE id = ?", (self.skol,)), 500)
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 10)
        self.assertGreater(self.banco.valor("SELECT COUNT(*) FROM custo_historico WHERE produto_id = ?", (self.skol,)), 0)
        venda = self.vender((self.skol, 4))
        self.pagar(venda, "Dinheiro", 4800)
        self.caixa.fechar(venda)
        resumo = RelatorioController(self.banco).resumo_nota(nota)
        self.assertEqual(resumo["custo_cent"], 5000)
        self.assertEqual(resumo["venda_prevista_cent"], 12000)
        self.assertEqual(resumo["lucro_previsto_cent"], 7000)
        self.assertEqual(resumo["qtd_vendida"], 4)
        self.assertEqual(resumo["lucro_realizado_cent"], 4800 - 2000)

    def test_operador_de_caixa_nao_grava_custo(self):
        caixa = self.banco.inserir("operadores", {"nome": "CAIXA", "senha": "x", "nivel": 1, "cargo_id": 1, "ativo": 1})
        self.banco.definir_operador_auditoria(caixa)
        from src.controllers.cadastro_controller import CadastroController
        with self.assertRaises(ErroPermissao):
            CadastroController(self.banco).salvar("produtos", {
                "nome": self.banco.valor("SELECT nome FROM produtos WHERE id = ?", (self.skol,)),
                "preco_cent": "12,00", "custo_medio_cent": "1,00"}, self.skol)
        with self.assertRaises(ErroPermissao):
            RelatorioController(self.banco).lucro_periodo({})

    def test_relatorio_de_lucro_e_pdf(self):
        venda = self.vender((self.skol, 2))
        self.pagar(venda, "Dinheiro", 2400)
        self.caixa.fechar(venda)
        rel = RelatorioController(self.banco).lucro_periodo({})
        texto = " ".join(" ".join(l) for l in rel.linhas)
        self.assertIn("14,00", texto)
        self.assertIn("10,00", texto)
        pdf = para_pdf(rel)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(b"%%EOF", pdf)
        mes = RelatorioController(self.banco).lucro_calendario({"agrupar": "mês"})
        self.assertIn("14,00", " ".join(" ".join(l) for l in mes.linhas))
        giro = RelatorioController(self.banco).giro_estoque({})
        self.assertEqual(giro.rodape[0][0], "Estoque a custo")
        self.assertEqual(giro.rodape[1][0], "Estoque a preço de venda")

    def _fornecedor(self) -> int:
        return self.banco.inserir("fornecedores", {"nome": "Bebidas SA", "ativo": 1})


class TestePdfMinimo(unittest.TestCase):
    def test_pdf_de_relatorio_vazio(self):
        rel = Relatorio("Vazio", [Coluna("A", 8)])
        rel.add("ok")
        self.assertTrue(para_pdf(rel).startswith(b"%PDF"))
