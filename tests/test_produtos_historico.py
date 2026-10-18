"""Exclusão física do catálogo sem perder cupons, estoque ou identidade de vendas."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from src.controllers.cadastro_controller import CadastroController
from src.controllers.estoque_controller import EstoqueController
from src.controllers.impressao_controller import ImpressaoController
from src.controllers.relatorio_controller import RelatorioController
from src.core.erros import ErroNegocio
from src.database import esquema
from src.database.conexao import BancoDados
from tests.test_excluir_produtos import BaseExcluir


class TesteHistoricoProdutos(BaseExcluir):
    def setUp(self):
        super().setUp()
        self.cad = CadastroController(self.banco)

    def test_amarula_excluida_e_red_bull_no_codigo_8_nao_mudam_vendas_antigas(self):
        antigo = self.novo_produto("AMARULA", 1500, codigo="8")
        venda = self.vender_e_fechar(antigo)
        cupom = ImpressaoController(self.banco).cupom(venda)
        rel = RelatorioController(self.banco)
        linhas = rel.vendas_periodo({}).linhas
        self.cad.excluir("produtos", antigo)
        novo = self.novo_produto("RED BULL", 2000, codigo="8")
        self.assertIsNone(self.prod.por_id(antigo))
        self.assertNotEqual(novo, antigo)
        self.assertEqual(self.prod.buscar_codigo("8")["id"], novo)
        self.assertEqual(ImpressaoController(self.banco).cupom(venda), cupom)
        self.assertEqual(rel.vendas_periodo({}).linhas, linhas)
        self.assertEqual(rel.cupom_detalhe(venda)["itens"][0]["nome"], "AMARULA")
        self.assertEqual(self.banco.todos("PRAGMA foreign_key_check"), [])

    def test_cancelamento_antigo_nao_estorna_estoque_do_novo_codigo(self):
        venda = self.vender_e_fechar(self.skol)
        codigo = self.prod.por_id(self.skol)["codigo"]
        self.cad.excluir("produtos", self.skol)
        novo = self.novo_produto("NOVA BEBIDA", 400, codigo=codigo, estoque=17)
        estoque = self.prod.por_id(novo)["qt_atual"]
        self.caixa.cancelar_venda(venda, "Teste de estorno após exclusão do cadastro")
        self.assertEqual(self.caixa.obter(venda)["status"], "cancelada")
        self.assertEqual(self.prod.por_id(novo)["qt_atual"], estoque)
        self.assertEqual(self.banco.todos("PRAGMA foreign_key_check"), [])
        self.assertTrue(self.banco.um("SELECT 1 FROM movimentos_estoque WHERE produto_id = ? AND tipo = 'estorno_venda'",
                                     (self.skol,)))

    def test_exclusao_recusa_parte_de_item_aberto(self):
        venda = self.caixa.abrir_balcao()
        item = self.caixa.adicionar_item(venda, self.skol, 1)
        self.banco.inserir("itens_venda_partes", {"item_id": item, "produto_id": self.agua, "fracao": 1})
        with self.assertRaises(ErroNegocio):
            self.cad.excluir("produtos", self.agua)
        self.assertIsNotNone(self.prod.por_id(self.agua))

    def test_parte_excluida_de_venda_fechada_continua_com_nome_antigo(self):
        venda = self.vender_e_fechar(self.skol)
        item = self.banco.valor("SELECT id FROM itens_venda WHERE venda_id = ?", (venda,))
        self.banco.inserir("itens_venda_partes", {"item_id": item, "produto_id": self.agua, "fracao": 1})
        codigo = self.prod.por_id(self.agua)["codigo"]
        self.cad.excluir("produtos", self.agua)
        self.novo_produto("OUTRA AGUA", 500, codigo=codigo)
        self.assertEqual(self.caixa.itens(venda)[0]["partes_nomes"], ["AGUA"])
        self.assertEqual(self.banco.todos("PRAGMA foreign_key_check"), [])

    def test_insumo_de_composicao_nao_e_removido_silenciosamente(self):
        self.banco.inserir("composicoes", {"produto_id": self.skol, "insumo_id": self.agua, "quantidade": 1})
        with self.assertRaisesRegex(ErroNegocio, "composição"):
            self.cad.excluir("produtos", self.agua)
        self.assertEqual(len(self.prod.composicao(self.skol)), 1)

    def test_custo_composto_preservado_apos_exclusao(self):
        self.banco.executar("UPDATE produtos SET ult_preco_cent = 250 WHERE id = ?", (self.agua,))
        self.banco.inserir("composicoes", {"produto_id": self.skol, "insumo_id": self.agua, "quantidade": 2})
        self.cad.excluir("produtos", self.skol)
        self.assertEqual(self.prod.custo(self.skol), 500)

    def test_novo_cadastro_que_falha_nao_apaga_inativo_que_cederia_codigo(self):
        self.banco.executar("UPDATE produtos SET ativo = 0 WHERE id = ?", (self.skol,))
        produto = self.prod.por_id(self.skol)
        with self.assertRaises(ErroNegocio):
            self.cad.salvar("produtos", {"codigo": produto["codigo"], "nome": "NOVA",
                                         "unidade_id": 99999, "subgrupo_id": produto["subgrupo_id"],
                                         "preco_cent": "5,00"})
        self.assertEqual(self.prod.por_id(self.skol), produto)

    def test_pedido_pendente_recusa_exclusao_individual_e_total(self):
        fornecedor = self.banco.inserir("fornecedores", {"nome": "DISTRIBUIDORA"})
        estoque = EstoqueController(self.banco)
        pedido = estoque.criar_lancamento("pedido", fornecedor_id=fornecedor)
        estoque.adicionar_item(pedido, self.skol, 1)
        for acao in (lambda: self.cad.excluir("produtos", self.skol), self.util.excluir_todos_produtos):
            with self.assertRaisesRegex(ErroNegocio, "pedido"):
                acao()
        self.assertIsNotNone(self.prod.por_id(self.skol))


class TesteMigracaoHistorico(unittest.TestCase):
    def test_v16_preserva_dados_relacoes_partes_e_sequencias(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "v16.db"
            with closing(sqlite3.connect(caminho)) as con:
                con.execute("PRAGMA foreign_keys = ON")
                for ddl in esquema.TABELAS:
                    if "CREATE TRIGGER" in ddl or ddl == esquema.PRODUTOS_HISTORICO_DDL:
                        continue
                    con.execute(ddl.replace("REFERENCES produtos_historico(id)", "REFERENCES produtos(id)"))
                con.execute("INSERT INTO grupos(id,nome) VALUES (1,'BEBIDAS')")
                con.execute("INSERT INTO subgrupos(id,nome,grupo_id) VALUES (1,'BEBIDAS',1)")
                con.execute("INSERT INTO unidades(id,nome,abreviatura) VALUES (1,'UNIDADE','UN')")
                con.execute("INSERT INTO produtos(id,codigo,nome,subgrupo_id,unidade_id) VALUES (8,'0000000000008','AMARULA',1,1)")
                con.execute("""INSERT INTO produtos(id,codigo,nome,subgrupo_id,unidade_id,ativo)
                               VALUES (9,'0000000000009~9','ANTIGO (excluído 9)',1,1,0)""")
                con.execute("INSERT INTO vendas(id,uuid,status,aberta_em) VALUES (1,'venda-teste','fechada','2026-10-16 12:00:00')")
                con.execute("""INSERT INTO itens_venda(id,venda_id,produto_id,quantidade,preco_unit_cent,total_cent,criado_em)
                               VALUES (42,1,8,1,1500,1500,'2026-10-16 12:00:00')""")
                con.execute("INSERT INTO itens_venda_partes(id,item_id,produto_id,fracao) VALUES (55,42,8,1)")
                con.execute("""INSERT INTO movimentos_estoque(id,produto_id,tipo,quantidade,qt_apos,criado_em)
                               VALUES (7,8,'venda',-1,9,'2026-10-16 12:00:00')""")
                con.execute("INSERT INTO lancamentos_estoque(id,tipo,data,criado_em) VALUES (1,'inicial','2026-10-16','2026-10-16 12:00:00')")
                con.execute("INSERT INTO itens_estoque(id,lancamento_id,produto_id,quantidade) VALUES (10,1,8,10)")
                con.execute("UPDATE sqlite_sequence SET seq = 100 WHERE name = 'itens_venda'")
                con.execute("PRAGMA user_version = 16")
                con.commit()
            passos = esquema.MIGRACOES[17] + ["SELECT * FROM falha_de_migracao_simulada"]
            with mock.patch.dict(esquema.MIGRACOES, {17: passos}):
                with self.assertRaises(sqlite3.OperationalError):
                    BancoDados(str(caminho))
            with closing(sqlite3.connect(caminho)) as con:
                self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 16)
                self.assertEqual(con.execute("SELECT id FROM itens_venda").fetchone()[0], 42)
                self.assertEqual(con.execute("SELECT id FROM itens_venda_partes").fetchone()[0], 55)
                self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
            banco = BancoDados(str(caminho))
            try:
                self.assertEqual(banco.valor("PRAGMA user_version"), esquema.VERSAO_ESQUEMA)
                self.assertEqual(banco.valor("SELECT id FROM itens_venda"), 42)
                self.assertEqual(banco.valor("SELECT id FROM itens_venda_partes"), 55)
                self.assertEqual(banco.valor("SELECT id FROM itens_estoque"), 10)
                self.assertEqual(banco.valor("SELECT seq FROM sqlite_sequence WHERE name='itens_venda'"), 100)
                self.assertEqual(banco.valor("SELECT nome FROM produtos_historico WHERE id=8"), "AMARULA")
                self.assertIsNone(banco.um("SELECT 1 FROM produtos WHERE id=9"))
                self.assertEqual(banco.valor("SELECT nome FROM produtos_historico WHERE id=9"), "ANTIGO")
                self.assertEqual(banco.valor("SELECT codigo FROM produtos_historico WHERE id=9"), "0000000000009")
                CadastroController(banco).excluir("produtos", 8)
                self.assertEqual(banco.valor("SELECT COUNT(*) FROM produtos"), 0)
                self.assertEqual(banco.valor("SELECT COUNT(*) FROM itens_venda"), 1)
                self.assertEqual(banco.valor("SELECT COUNT(*) FROM movimentos_estoque"), 1)
                self.assertEqual(banco.todos("PRAGMA foreign_key_check"), [])
            finally:
                banco.fechar()
            banco = BancoDados(str(caminho))
            try:
                self.assertEqual(banco.valor("SELECT COUNT(*) FROM produtos_historico"), 2)
                self.assertEqual(banco.todos("PRAGMA foreign_key_check"), [])
            finally:
                banco.fechar()
