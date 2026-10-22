"""Excluir todos os produtos de uma vez, para cadastrar a tabela de novo (Importar produtos).

O cadastro é removido, o histórico fica separado e a operação faz backup antes e recusa com venda aberta."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from src.controllers.estoque_controller import EstoqueController
from src.controllers.impressao_controller import ImpressaoController
from src.controllers.importacao_produtos import ImportacaoProdutos
from src.controllers.utilitario_controller import UtilitarioController
from src.core.erros import ErroNegocio
from tests.test_caixa import BaseCaixa


class BaseExcluir(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.pasta = tempfile.TemporaryDirectory()             # o backup dos testes não vai para a pasta do projeto
        self.addCleanup(self.pasta.cleanup)
        self.banco.cfg_set("pasta_backup", self.pasta.name)
        self.util = UtilitarioController(self.banco, self.adm)

    def produtos(self):
        return self.banco.valor("SELECT COUNT(*) FROM produtos")

    def vender_e_fechar(self, produto):
        vid = self.vender((produto, 1))
        self.pagar(vid, "Dinheiro", self.caixa.obter(vid)["total_cent"])
        self.caixa.fechar(vid)
        return vid


class TesteExcluirTodosOsProdutos(BaseExcluir):
    def test_resumo_antes_de_excluir(self):
        self.assertEqual(self.util.resumo_exclusao_produtos(),
                         {"total": 2, "excluidos": 2, "guardados": 0, "vendas_abertas": 0})

    def test_exclui_tudo_faz_backup_e_deixa_grupos_e_unidades(self):
        grupos = self.banco.valor("SELECT COUNT(*) FROM subgrupos")
        res = self.util.excluir_todos_produtos()
        self.assertEqual((res["excluidos"], res["guardados"]), (2, 0))
        self.assertEqual(self.produtos(), 0)
        self.assertTrue(Path(res["backup"]).exists())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM subgrupos"), grupos)
        self.assertTrue(self.banco.valor("SELECT COUNT(*) FROM unidades") > 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'excluir_todos_produtos'"), 1)

    def test_o_backup_guarda_os_produtos_de_antes(self):
        import sqlite3
        res = self.util.excluir_todos_produtos()
        con = sqlite3.connect(res["backup"])
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM produtos").fetchone()[0], 2)
        finally:
            con.close()

    def test_sem_produtos_avisa(self):
        self.util.excluir_todos_produtos()
        with self.assertRaises(ErroNegocio) as e:
            self.util.excluir_todos_produtos()
        self.assertIn("Não há produtos", str(e.exception))

    def test_produto_ja_vendido_sai_do_cadastro_e_o_historico_continua(self):
        vid = self.vender_e_fechar(self.skol)
        res = self.util.excluir_todos_produtos()
        self.assertEqual((res["excluidos"], res["guardados"]), (2, 0))
        self.assertEqual(self.produtos(), 0)
        self.assertEqual(self.banco.valor("SELECT nome FROM produtos_historico WHERE id = ?", (self.skol,)), "SKOL")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda"), 1)
        self.assertIn("SKOL", ImpressaoController(self.banco).cupom(vid))                      # a reimpressão do cupom segue valendo
        self.assertEqual(self.util.resumo_exclusao_produtos()["guardados"], 0)

    def test_produto_inativo_nao_vende_no_caixa(self):
        self.vender_e_fechar(self.skol)
        self.util.excluir_todos_produtos()
        vid = self.caixa.abrir_balcao()
        with self.assertRaises(ErroNegocio):
            self.caixa.adicionar_item(vid, self.skol, 1)

    def test_recusa_com_venda_aberta_e_nao_apaga_nada(self):
        self.vender((self.skol, 1), mesa=5)
        with self.assertRaises(ErroNegocio) as e:
            self.util.excluir_todos_produtos()
        self.assertIn("abertas", str(e.exception))
        self.assertEqual(self.produtos(), 2)
        self.assertEqual(os.listdir(self.pasta.name), [])                                      # nem backup: nada foi feito

    def test_composicoes_saem_e_historico_de_estoque_continua(self):
        lanc = EstoqueController(self.banco, self.adm).criar_lancamento("inicial", descricao="teste")
        EstoqueController(self.banco, self.adm).adicionar_item(lanc, self.skol, 10)             # gera item e movimento de estoque
        self.assertTrue(self.banco.valor("SELECT COUNT(*) FROM movimentos_estoque") > 0)
        self.banco.executar("INSERT INTO composicoes(produto_id, insumo_id, quantidade) VALUES (?, ?, 1)", (self.agua, self.skol))
        self.util.excluir_todos_produtos()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM composicoes"), 0)
        for tabela in ("movimentos_estoque", "itens_estoque", "lancamentos_estoque"):
            self.assertGreater(self.banco.valor(f"SELECT COUNT(*) FROM {tabela}"), 0, tabela)

    def test_composicao_do_guardado_com_insumo_excluido_sai(self):
        self.vender_e_fechar(self.skol)                                                        # a SKOL fica guardada
        self.banco.executar("INSERT INTO composicoes(produto_id, insumo_id, quantidade) VALUES (?, ?, 1)", (self.skol, self.agua))
        self.util.excluir_todos_produtos()                                                     # a AGUA (insumo) é excluída
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM composicoes"), 0)

    def test_estoque_do_guardado_continua(self):
        self.vender_e_fechar(self.skol)
        antes = self.banco.valor("SELECT COUNT(*) FROM movimentos_estoque WHERE produto_id = ?", (self.skol,))
        self.util.excluir_todos_produtos()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_estoque WHERE produto_id = ?", (self.skol,)), antes)


class TesteCadastrarDeNovoDepoisDeExcluir(BaseExcluir):
    def tabela(self, *linhas):
        return [{"_linha": n, "codigo": c, "nome": nome, "preco": preco} for n, (c, nome, preco) in enumerate(linhas, start=2)]

    def importar(self, tabela):
        imp = ImportacaoProdutos(self.banco, self.adm)
        previa = imp.analisar(tabela)
        return previa, imp.importar(previa)

    def test_os_mesmos_codigos_ficam_livres_para_a_planilha(self):
        codigo = self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (self.agua,))
        self.util.excluir_todos_produtos()
        previa, res = self.importar(self.tabela((str(int(codigo)), "AGUA NOVA", "4,00"), ("", "SUCO", "6,00")))
        self.assertEqual((res["criados"], res["atualizados"]), (2, 0))
        self.assertEqual(self.banco.valor("SELECT nome FROM produtos WHERE codigo = ?", (codigo,)), "AGUA NOVA")

    def test_produto_excluido_vira_novo_cadastro_quando_planilha_traz_o_mesmo_codigo(self):
        self.vender_e_fechar(self.skol)
        codigo = self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (self.skol,))
        self.util.excluir_todos_produtos()
        previa, res = self.importar(self.tabela((str(int(codigo)), "SKOL", "9,00")))
        linha = previa.linhas[0]
        self.assertEqual(linha.acao, "criar")
        self.assertEqual((res["criados"], res["atualizados"]), (1, 0))
        novo = self.banco.valor("SELECT id FROM produtos WHERE codigo = ?", (codigo,))
        self.assertNotEqual(novo, self.skol)
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (novo,)), 900)
        vid = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(vid, novo, 1)

    def test_importar_um_produto_ativo_nao_muda_nada_alem_do_que_a_planilha_traz(self):
        previa, res = self.importar(self.tabela((str(int(self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (self.agua,)))),
                                                 "AGUA", "5,00")))
        self.assertEqual(res["atualizados"], 1)
        self.assertEqual(self.banco.valor("SELECT ativo FROM produtos WHERE id = ?", (self.agua,)), 1)
        self.assertFalse(any("inativo" in a for a in previa.linhas[0].avisos))


class TesteCodigosExatosDaPlanilha(BaseExcluir):
    """A planilha manda nos códigos: entram exatamente como estão, mesmo depois de uma exclusão total com produtos guardados."""

    def importar(self, *linhas):
        imp = ImportacaoProdutos(self.banco, self.adm)
        previa = imp.analisar([{"_linha": n, "codigo": c, "nome": nome, "preco": "9,00"} for n, (c, nome) in enumerate(linhas, 2)])
        return previa, imp.importar(previa)

    def codigo(self, produto_id):
        return int(self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (produto_id,)))

    def test_tabela_da_casa_entra_com_os_codigos_da_folha(self):
        from src.controllers.importacao_produtos import ler_tabela
        arquivo = Path(__file__).resolve().parent.parent / "docs" / "produtos_da_casa.csv"
        self.util.excluir_todos_produtos()
        imp = ImportacaoProdutos(self.banco, self.adm)
        previa = imp.analisar(ler_tabela(arquivo))                      # o modo padrão: usar o código da planilha
        self.assertEqual(previa.resumo(), "31 para criar, 0 para atualizar, 0 recusados")
        imp.importar(previa)
        codigos = {r["nome"]: int(r["codigo"]) for r in self.banco.todos("SELECT codigo, nome FROM produtos")}
        for nome, esperado in (("ÁGUA", 36), ("REFRIGERANTE", 1), ("CERVEJA", 2), ("CONHAQUE", 5), ("SUCO", 3), ("CATUABA", 6),
                               ("CAMPARI", 15), ("WHISK NASC.", 25), ("MALIBU", 26), ("SINUCA", 32), ("COMBO WHISK", 58),
                               ("COMBO 10 LATAS", 23), ("COMBO GIN", 16)):
            self.assertEqual(codigos[nome], esperado, nome)
        self.assertEqual(len(set(codigos.values())), 31)                 # nenhum código repetido
        self.assertEqual(codigos["MUSICA"], 9)                           # sem código na folha: o primeiro número livre
        preco = lambda n: self.banco.valor("SELECT preco_cent FROM produtos WHERE nome = ?", (n,))
        self.assertEqual((preco("CAMPARI"), preco("COMBO 10 LATAS"), preco("MUSICA")), (4500, 12000, 100))
        self.assertAlmostEqual(self.banco.valor("SELECT comissao_pct FROM produtos WHERE nome = 'CAMPARI'"), 33.3333, places=3)

    def test_excluido_cede_o_codigo_sem_mudar_o_historico(self):
        self.vender_e_fechar(self.skol)                                  # a SKOL (código 1) fica guardada
        self.util.excluir_todos_produtos()
        previa, res = self.importar(("1", "FOGO PAULISTA"))
        linha = previa.linhas[0]
        self.assertEqual((linha.acao, linha.liberar_id), ("criar", None))
        self.assertEqual(res["criados"], 1)
        novo = self.banco.valor("SELECT id FROM produtos WHERE nome = 'FOGO PAULISTA'")
        self.assertEqual(self.codigo(novo), 1)                           # o código da planilha, exato
        antigo = self.banco.um("SELECT nome, ativo, codigo FROM produtos_historico WHERE id = ?", (self.skol,))
        self.assertEqual((antigo["nome"], antigo["ativo"]), ("SKOL", 0))  # o histórico continua com o nome de antes
        self.assertEqual(int(antigo["codigo"]), 1)
        self.assertIsNone(self.banco.um("SELECT 1 FROM produtos WHERE id = ?", (self.skol,)))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda WHERE produto_id = ?", (self.skol,)), 1)

    def test_excluido_que_planilha_traz_com_outro_codigo_cria_nova_identidade(self):
        self.vender_e_fechar(self.skol)
        self.util.excluir_todos_produtos()
        previa, res = self.importar(("5", "SKOL"))
        self.assertEqual((previa.linhas[0].acao, previa.linhas[0].produto_id), ("criar", None))
        self.assertEqual((res["criados"], res["atualizados"]), (1, 0))
        self.assertEqual(int(self.banco.valor("SELECT codigo FROM produtos WHERE nome = 'SKOL'")), 5)
        self.assertEqual(int(self.banco.valor("SELECT codigo FROM produtos_historico WHERE id = ?", (self.skol,))), 1)

    def test_dois_guardados_trocando_de_codigo_ao_mesmo_tempo(self):
        self.vender_e_fechar(self.skol)                                  # SKOL = código 1
        self.vender_e_fechar(self.agua)                                  # AGUA = código 2
        self.util.excluir_todos_produtos()
        previa, res = self.importar(("1", "AGUA"), ("2", "SKOL"))        # a planilha troca os dois
        self.assertEqual([l.acao for l in previa.linhas], ["criar", "criar"])
        self.assertEqual((res["criados"], res["atualizados"]), (2, 0))
        self.assertEqual(int(self.banco.valor("SELECT codigo FROM produtos WHERE nome = 'AGUA'")), 1)
        self.assertEqual(int(self.banco.valor("SELECT codigo FROM produtos WHERE nome = 'SKOL'")), 2)

    def test_produto_ativo_nao_cede_o_codigo(self):
        previa, _ = self.importar(("1", "OUTRO NOME"))                   # o 1 é da SKOL, que está ativa: só o nome muda
        self.assertEqual((previa.linhas[0].acao, previa.linhas[0].produto_id), ("atualizar", self.skol))
        self.assertTrue(any("nome vai mudar" in a for a in previa.linhas[0].avisos))
        self.assertIsNone(previa.linhas[0].liberar_id)

    def test_sem_codigo_na_planilha_o_guardado_nao_e_mexido(self):
        self.vender_e_fechar(self.skol)
        self.util.excluir_todos_produtos()
        previa, res = self.importar(("", "OUTRO"))
        self.assertIsNone(previa.linhas[0].liberar_id)
        self.assertEqual(int(self.banco.valor("SELECT codigo FROM produtos_historico WHERE id = ?", (self.skol,))), 1)
        novo = self.banco.valor("SELECT id FROM produtos WHERE nome = 'OUTRO'")
        self.assertNotEqual(novo, self.skol)


if __name__ == "__main__":
    import unittest
    unittest.main()
