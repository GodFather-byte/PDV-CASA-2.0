"""Excluir do cadastro e liberar identificadores, preservando os registros históricos."""
from __future__ import annotations

from src.controllers.cadastro_controller import CadastroController
from src.core.erros import ErroNegocio
from tests.test_excluir_produtos import BaseExcluir


class TesteExcluirProdutoCadastrado(BaseExcluir):
    def setUp(self):
        super().setUp()
        self.cad = CadastroController(self.banco)

    def test_sem_venda_apaga_de_verdade_e_o_codigo_volta_a_ficar_livre(self):
        codigo = self.prod.por_id(self.skol)["codigo"]
        self.assertIsNone(self.cad.excluir("produtos", self.skol))
        self.assertIsNone(self.prod.por_id(self.skol))
        self.assertIsNone(self.banco.um("SELECT 1 FROM produtos WHERE codigo = ?", (codigo,)))

    def test_ja_vendido_sai_do_cadastro_e_libera_o_codigo(self):
        antes = self.prod.por_id(self.skol)
        self.vender_e_fechar(self.skol)
        aviso = self.cad.excluir("produtos", self.skol)
        self.assertIsNone(aviso)
        self.assertIsNone(self.prod.por_id(self.skol))
        p = self.banco.um("SELECT * FROM produtos_historico WHERE id = ?", (self.skol,))
        self.assertEqual((p["codigo"], p["nome"]), (antes["codigo"], antes["nome"]))
        # o código e o nome antigos já servem para um produto novo
        novo = self.novo_produto(antes["nome"], 500, codigo=antes["codigo"])
        self.assertEqual(self.prod.por_id(novo)["codigo"], antes["codigo"])

    def test_o_historico_da_venda_continua(self):
        vid = self.vender_e_fechar(self.skol)
        self.cad.excluir("produtos", self.skol)
        self.assertEqual(len(self.caixa.itens(vid)), 1)

    def test_recusa_se_esta_numa_venda_aberta(self):
        self.vender((self.skol, 1))
        with self.assertRaises(ErroNegocio):
            self.cad.excluir("produtos", self.skol)
        self.assertEqual(self.prod.por_id(self.skol)["ativo"], 1)

    def test_preserva_os_movimentos_do_estoque_dele(self):
        antes = self.banco.valor("SELECT COUNT(*) FROM movimentos_estoque WHERE produto_id = ?", (self.skol,))
        self.cad.excluir("produtos", self.skol)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_estoque WHERE produto_id = ?", (self.skol,)), antes)


class TesteReusarCodigoDeProdutoGuardado(BaseExcluir):
    """O número que ficou preso a um produto inativo (guardado por já ter sido vendido) volta a servir no cadastro."""
    def setUp(self):
        super().setUp()
        self.cad = CadastroController(self.banco)

    def valores(self, codigo, nome):
        sub = self.banco.valor("SELECT id FROM subgrupos LIMIT 1")
        un = self.banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'")
        return {"codigo": codigo, "nome": nome, "subgrupo_id": str(sub), "unidade_id": str(un), "preco_cent": "5,00"}

    def guardar_com_excluir_todos(self):
        self.vender_e_fechar(self.skol)
        self.util.excluir_todos_produtos()
        return self.banco.um("SELECT codigo, nome FROM produtos_historico WHERE id = ?", (self.skol,))

    def test_cadastrar_com_o_codigo_do_produto_guardado(self):
        velho = self.guardar_com_excluir_todos()
        novo = self.cad.salvar("produtos", self.valores(velho["codigo"], "CERVEJA NOVA"))
        self.assertEqual(self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (novo,)), velho["codigo"])
        self.assertIsNone(self.prod.por_id(self.skol))
        self.assertEqual(self.banco.valor("SELECT codigo FROM produtos_historico WHERE id = ?", (self.skol,)), velho["codigo"])

    def test_cadastrar_com_o_nome_do_produto_guardado(self):
        velho = self.guardar_com_excluir_todos()
        novo = self.cad.salvar("produtos", self.valores("9999", velho["nome"]))
        self.assertEqual(self.banco.valor("SELECT nome FROM produtos WHERE id = ?", (novo,)), velho["nome"])

    def test_produto_ativo_continua_bloqueando_o_codigo(self):
        codigo = self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (self.skol,))
        with self.assertRaises(ErroNegocio):
            self.cad.salvar("produtos", self.valores(codigo, "OUTRO"))

    def test_excluir_e_cadastrar_de_novo_com_o_mesmo_numero(self):
        codigo = self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (self.skol,))
        self.vender_e_fechar(self.skol)
        self.cad.excluir("produtos", self.skol)
        novo = self.cad.salvar("produtos", self.valores(codigo.lstrip("0"), "SKOL"))
        self.assertEqual(self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (novo,)), codigo)
