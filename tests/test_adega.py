"""Adega / depósito de bebidas: o perfil (venda só no balcão, delivery, fiado e as categorias de bebidas), o caixa sem mesas
nem comandas, o cadastro do produto na hora pelo código de barras, a quantidade antes do código ("6*") e o fardo/caixa fechada
que baixa as unidades na venda e entra como unidades na compra."""
from __future__ import annotations

import unittest
from unittest import mock

from src.controllers.cadastro_controller import CadastroController
from src.controllers.config_controller import modulos_desligados
from src.controllers.estoque_controller import EstoqueController
from src.controllers.perfil_controller import PerfilController
from src.controllers.produto_controller import ProdutoController
from src.core.erros import ErroNegocio, ErroValidacao
from tests.test_caixa import BaseCaixa

EAN = "7891234567895"


class BaseAdega(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.prod = ProdutoController(self.banco)
        self.sub = self.banco.valor("SELECT id FROM subgrupos LIMIT 1")

    def vender_no_balcao(self, produto_id, qtd):
        vid = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(vid, produto_id, qtd)
        self.pagar(vid, "Dinheiro", self.caixa.obter(vid)["total_cent"])
        return self.caixa.fechar(vid)


class TestePerfilAdega(BaseAdega):
    def test_vende_so_no_balcao_com_delivery_e_fiado(self):
        PerfilController(self.banco, self.adm).aplicar("adega")
        for chave, valor in (("usar_mesas", "N"), ("usar_delivery", "S"), ("usar_caderneta", "S"), ("usar_garotas", "N"),
                             ("usar_portaria", "N"), ("cobra_servico_mesa", "N"), ("cobra_servico_comanda", "N"),
                             ("usar_desconto", "S")):
            self.assertEqual(self.banco.cfg(chave), valor, chave)
        with self.assertRaisesRegex(ErroNegocio, "só no balcão"):
            self.caixa.abrir_mesa(5)
        v = self.vender_no_balcao(self.skol, 2)
        self.assertEqual((v["status"], v["total_cent"]), ("fechada", 1600))
        self.assertTrue({"rel_comandas", "rel_garcons", "cad_garotas"} <= modulos_desligados(self.banco))

    def test_cria_as_categorias_de_bebidas_sem_duplicar(self):
        self.banco.executar("INSERT INTO grupos(nome) VALUES ('BEBIDAS')")
        grupo = self.banco.valor("SELECT id FROM grupos WHERE nome = 'BEBIDAS'")
        self.banco.executar("INSERT INTO subgrupos(nome, grupo_id) VALUES ('CERVEJAS', ?)", (grupo,))   # a casa já tinha
        perfil = PerfilController(self.banco, self.adm)
        self.assertNotIn("CERVEJAS", perfil.categorias_faltando("adega")["BEBIDAS"])
        perfil.aplicar("adega")
        perfil.aplicar("adega")
        contar = "SELECT COUNT(*) FROM subgrupos s JOIN grupos g ON g.id = s.grupo_id WHERE g.nome = ?"
        self.assertEqual((self.banco.valor(contar, ("BEBIDAS",)), self.banco.valor(contar, ("CONVENIÊNCIA",))), (6, 4))
        self.assertEqual(perfil.categorias_faltando("adega"), {})

    def test_comercio_tambem_vende_so_no_balcao(self):
        PerfilController(self.banco, self.adm).aplicar("comercio")
        self.assertEqual(self.banco.cfg("usar_mesas"), "N")


class TesteCadastroRapido(BaseAdega):
    def test_proximo_codigo_pula_o_codigo_da_comissao(self):
        self.novo_produto("COISA", codigo="49")
        self.assertEqual(self.prod.proximo_codigo(), "51")                    # o 50 é o código da comissão das garotas
        self.assertEqual(CadastroController(self.banco).proximo_codigo_produto(), "51".zfill(13))
        self.banco.cfg_set("usar_garotas", "N")
        self.assertEqual(self.prod.proximo_codigo(), "50")                    # sem garotas, o 50 fica livre

    def test_codigo_de_barras_usado_como_codigo_nao_estoura_a_numeracao(self):
        self.novo_produto("COM EAN NO CODIGO", codigo=EAN)
        self.assertLess(int(self.prod.proximo_codigo()), 1_000_000)

    def test_cadastra_com_estoque_pelo_codigo_de_barras(self):
        p = self.prod.cadastrar_rapido(EAN, "CERVEJA X LATA 350ML", 450, self.sub, estoque=24, operador_id=self.adm)
        self.assertEqual((p["cbarra"], p["nome"], p["preco_cent"], p["controla_estoque"], p["qt_atual"]),
                         (EAN, "CERVEJA X LATA 350ML", 450, 1, 24))
        self.assertEqual(self.prod.buscar_codigo(EAN)["id"], p["id"])         # o leitor já acha
        self.assertEqual(self.vender_no_balcao(p["id"], 2)["total_cent"], 900)
        self.assertEqual(self.prod.por_id(p["id"])["qt_atual"], 22)

    def test_sem_estoque_informado_nao_controla_estoque(self):
        p = self.prod.cadastrar_rapido(EAN, "GELO 5KG", 1200, self.sub)
        self.assertEqual((p["controla_estoque"], p["preco_gelada_cent"]), (0, 0))

    def test_cadastro_rapido_com_preco_gelada(self):
        p = self.prod.cadastrar_rapido(EAN, "BRAHMA LATA", 450, self.sub, preco_gelada_cent=550)
        self.assertEqual((p["preco_cent"], p["preco_gelada_cent"]), (450, 550))
        vid = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(vid, p["id"], 2, temperatura="gelada")
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 1100)
        with self.assertRaisesRegex(ErroNegocio, "gelada"):
            self.prod.cadastrar_rapido("7890000000031", "OUTRA", 450, self.sub, preco_gelada_cent=-1)

    def test_recusa_codigo_repetido_preco_zero_e_nome_vazio(self):
        self.prod.cadastrar_rapido(EAN, "CERVEJA X", 450, self.sub)
        with self.assertRaisesRegex(ErroNegocio, "já é do produto 'CERVEJA X'"):
            self.prod.cadastrar_rapido(EAN, "OUTRA", 500, self.sub)
        with self.assertRaisesRegex(ErroNegocio, "preço"):
            self.prod.cadastrar_rapido("7890000000017", "SEM PRECO", 0, self.sub)
        with self.assertRaises(ErroValidacao):
            self.prod.cadastrar_rapido("7890000000024", "", 500, self.sub)


class TesteFardo(BaseAdega):
    def test_vender_o_fardo_baixa_as_unidades(self):
        lata = self.novo_produto("SKOL LATA 350ML", 400, estoque=True, qt=48)
        fardo = self.prod.criar_embalagem(lata, 12, "SKOL LATA 350ML - FARDO 12", 4200, "17891234567892", self.adm)
        f = self.prod.por_id(fardo)
        un = self.banco.valor("SELECT abreviatura FROM unidades WHERE id = ?", (f["unidade_id"],))
        self.assertEqual((f["preco_cent"], f["cbarra"], f["controla_estoque"], un), (4200, "17891234567892", 0, "FD"))
        self.assertEqual([(c["insumo_id"], c["quantidade"]) for c in self.prod.composicao(fardo)], [(lata, 12)])
        self.assertEqual(self.prod.buscar_codigo("17891234567892")["id"], fardo)
        self.assertEqual(self.vender_no_balcao(fardo, 2)["total_cent"], 8400)
        self.assertEqual(self.prod.por_id(lata)["qt_atual"], 48 - 24)

    def test_unidade_que_nao_controlava_estoque_passa_a_controlar(self):
        lata = self.novo_produto("BRAHMA LATA", 400)
        self.prod.criar_embalagem(lata, 12, "BRAHMA FARDO", 4200)
        self.assertEqual(self.prod.por_id(lata)["controla_estoque"], 1)

    def test_recusa_quantidade_invalida_e_preco_zero(self):
        lata = self.novo_produto("SKOL LATA", 400, estoque=True)
        for qtd in (1, 12.5, 1000):
            with self.assertRaises(ErroNegocio, msg=qtd):
                self.prod.criar_embalagem(lata, qtd, "FARDO", 4200)
        with self.assertRaisesRegex(ErroNegocio, "preço"):
            self.prod.criar_embalagem(lata, 12, "FARDO", 0)
        self.assertEqual(self.prod.composicao(lata), [])


class TesteFardoNoEstoque(BaseAdega):
    """O fardo não tem estoque próprio: compra, entrada, saída e perda de fardos vão para as unidades."""

    def setUp(self):
        super().setUp()
        self.est = EstoqueController(self.banco, self.adm)
        self.lata = self.novo_produto("SKOL LATA", 400, estoque=True, qt=30)
        self.fardo = self.prod.criar_embalagem(self.lata, 12, "SKOL LATA - FARDO", 4200)

    def qt(self, pid):
        return self.prod.por_id(pid)["qt_atual"]

    def test_reconhece_o_fardo(self):
        self.assertEqual(self.prod.embalagem(self.fardo),
                         {"unitario_id": self.lata, "unitario": "SKOL LATA", "unidade": "UN", "quantidade": 12})
        self.assertIsNone(self.prod.embalagem(self.lata))
        whisky = self.novo_produto("WHISKY GARRAFA", 9000, estoque=True)
        dose = self.novo_produto("DOSE WHISKY", 1500)
        self.prod.incluir_composicao(dose, whisky, 0.05)
        self.assertIsNone(self.prod.embalagem(dose))                          # dose não é fardo: segue a regra de sempre

    def test_compra_de_fardos_entra_nas_unidades(self):
        forn = self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        lanc = self.est.criar_lancamento("compra", fornecedor_id=forn, valor_cent=36000)
        self.est.adicionar_item(lanc, self.fardo, 10, 36000, ligar_controle=True)
        self.assertEqual((self.qt(self.lata), self.prod.por_id(self.lata)["ult_preco_cent"]), (150, 300))   # R$ 360 / 120 latas
        self.assertEqual((self.prod.por_id(self.fardo)["controla_estoque"], self.qt(self.fardo)), (0, 0))
        itens = self.est.itens(lanc)
        self.assertEqual([(i["nome"], i["quantidade"], i["valor_cent"]) for i in itens], [("SKOL LATA", 120, 36000)])
        self.est.remover_item(itens[0]["id"])
        self.assertEqual(self.qt(self.lata), 30)

    def test_entrada_perda_e_saida_rapidas_de_fardo(self):
        self.est.registrar_rapido(self.fardo, "entrada", 2)
        self.assertEqual(self.qt(self.lata), 54)
        self.est.registrar_rapido(self.fardo, "descarte", 1)
        self.assertEqual(self.qt(self.lata), 42)
        with self.assertRaisesRegex(ErroNegocio, "Só há 42,000 de 'SKOL LATA'.*48,000"):
            self.est.registrar_rapido(self.fardo, "saida", 4)
        self.assertEqual(self.prod.por_id(self.fardo)["controla_estoque"], 0)

    def test_contagem_e_inicial_de_fardo_sao_recusadas(self):
        with self.assertRaisesRegex(ErroNegocio, "conte as unidades no produto 'SKOL LATA'"):
            self.est.registrar_rapido(self.fardo, "contagem", 5)
        lanc = self.est.criar_lancamento("inicial")
        with self.assertRaisesRegex(ErroNegocio, "não tem estoque próprio"):
            self.est.adicionar_item(lanc, self.fardo, 5)
        self.assertEqual((self.qt(self.lata), self.prod.por_id(self.fardo)["controla_estoque"]), (30, 0))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque WHERE tipo = 'contagem'"), 0)


if __name__ == "__main__":
    unittest.main()
