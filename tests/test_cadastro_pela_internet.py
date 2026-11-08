"""Cadastro de produto pelo código de barras: nome e foto da base pública; no caixa do Will Adega, bipar um código
desconhecido oferece cadastrar na hora e já lança."""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.controllers import foto_produto_controller as fotos
from src.core.erros import ErroNegocio
from tests.test_foto_produto import FOTO_URL, HttpFalso, Resposta, imagem
from tests.test_qt_caixa import BaseCaixaQt, QApplication

GTIN = "7891149103102"
BUSCAR = fotos.buscar_produto          # a função real (a base dos testes do caixa a troca por "sem internet")
DADOS = fotos.URL_DADOS.format(gtin=GTIN)


def http_com(produto: dict, foto=True) -> HttpFalso:
    respostas = {DADOS: Resposta(200, json.dumps({"product": produto}).encode())}
    if foto:
        respostas[FOTO_URL] = Resposta(200, imagem(600, 600, "JPEG", "RGB"))
    return HttpFalso(respostas)


class TesteBuscarProduto(unittest.TestCase):
    def test_nome_em_portugues_com_quantidade_e_foto(self):
        r = BUSCAR(GTIN, http_com({"product_name": "Skol beer", "product_name_pt": "Cerveja Skol Pilsen",
                                                "quantity": "350 ml", "image_front_url": FOTO_URL}))
        self.assertEqual(r["nome"], "CERVEJA SKOL PILSEN 350 ML")
        self.assertEqual(r["foto"].origem, FOTO_URL)

    def test_so_o_nome_so_a_marca_limite_e_nada(self):
        r = BUSCAR(GTIN, http_com({"brands": "Heineken, Outra", "quantity": "330ml"}, foto=False))
        self.assertEqual((r["nome"], r["foto"]), ("HEINEKEN 330ML", None))
        longo = BUSCAR(GTIN, http_com({"product_name": "X" * 80}, foto=False))
        self.assertEqual(len(longo["nome"]), 50)
        com_qtd = BUSCAR(GTIN, http_com({"product_name": "Gin 750 ml", "quantity": "750 ml"}, foto=False))
        self.assertEqual(com_qtd["nome"], "GIN 750 ML")                 # a quantidade já está no nome: não repete
        with self.assertRaisesRegex(ErroNegocio, "não está na base"):
            BUSCAR(GTIN, HttpFalso({}))
        with self.assertRaisesRegex(ErroNegocio, "8 a 14"):
            BUSCAR("123", HttpFalso({}))
        estranho = http_com({"product_name": "Vodka", "image_front_url": "https://outro.site/foto.jpg"}, foto=False)
        self.assertIsNone(BUSCAR(GTIN, estranho)["foto"])  # foto fora da base pública: ignorada

    def test_sem_rede(self):
        with self.assertRaisesRegex(ErroNegocio, "Sem conexão"):
            BUSCAR(GTIN, HttpFalso({DADOS: OSError("sem rede")}))


@unittest.skipIf(QApplication is None, "PySide6 não instalado")
class TesteCadastroRapidoNoCaixa(BaseCaixaQt):
    """O cadastro rápido do caixa (código de barras desconhecido no leitor) já traz o nome e grava a foto."""

    def setUp(self):
        super().setUp()
        self.abrir_turno()
        self.http = http_com({"product_name_pt": "Cerveja Skol", "quantity": "350 ml", "image_front_url": FOTO_URL})
        p = mock.patch.object(fotos, "buscar_produto", side_effect=lambda cb, http=None: BUSCAR(cb, self.http))
        p.start()
        self.addCleanup(p.stop)
        self.subgrupo = self.banco.valor("SELECT id FROM subgrupos ORDER BY id LIMIT 1")

    def roteiro(self, j, nome):
        j.dialogos.confirmacoes = [True]
        j.dialogos.textos = [nome, "4,50", "", ""]                 # nome, preço, gelada, estoque
        j.dialogos.escolhas = [self.subgrupo]

    def test_nome_vem_preenchido_e_a_foto_fica_gravada(self):
        j = self.janela()
        perguntas = []
        original = j.dialogos.pedir_texto
        j.dialogos.pedir_texto = lambda t, r, senha=False, padrao="": perguntas.append((r, padrao)) or original(t, r)
        self.roteiro(j, "CERVEJA SKOL 350 ML")
        self.lancar(j, GTIN)
        self.assertEqual(perguntas[0], ("Nome do produto (achado na internet; confira):", "CERVEJA SKOL 350 ML"))
        produto = self.banco.um("SELECT id, nome, preco_cent FROM produtos WHERE cbarra = ?", (GTIN,))
        self.assertEqual((produto["nome"], produto["preco_cent"]), ("CERVEJA SKOL 350 ML", 450))
        self.assertTrue(fotos.FotoProdutoController(self.banco).tem_foto(produto["id"]))
        self.assertEqual([i["produto_id"] for i in self.ctx.caixa.itens(j.venda_id)], [produto["id"]])
        self.assertTrue(j.foto_item.tem_foto())                         # o caixa já mostra a foto do item

    def test_fora_da_base_segue_digitando_sem_foto(self):
        self.http = HttpFalso({})
        j = self.janela()
        self.roteiro(j, "GELO 5KG")
        self.lancar(j, GTIN)
        produto = self.banco.um("SELECT id, nome FROM produtos WHERE cbarra = ?", (GTIN,))
        self.assertEqual(produto["nome"], "GELO 5KG")
        self.assertFalse(fotos.FotoProdutoController(self.banco).tem_foto(produto["id"]))
        self.assertIn("Nome do produto:", j.dialogos.perguntas)


@unittest.skipIf(QApplication is None, "PySide6 não instalado")
class TesteBotaoNoCadastro(BaseCaixaQt):
    def test_formulario_busca_nome_e_foto(self):
        from src.ui_qt.cadastros import FormularioCadastro
        self.http = http_com({"product_name": "Vodka Smirnoff", "quantity": "998 ml", "image_front_url": FOTO_URL})
        f = FormularioCadastro(self.ctx, "produtos")
        self.addCleanup(f.deleteLater)
        f.campos["cbarra"].setText(GTIN)
        p = mock.patch.object(fotos, "buscar_produto", side_effect=lambda cb, http=None: BUSCAR(cb, self.http))
        p.start()
        self.addCleanup(p.stop)
        self.assertTrue(f.preencher_pela_internet(self.http))
        self.assertEqual(f.campos["nome"].text(), "VODKA SMIRNOFF 998 ML")
        self.assertIsNotNone(f.editor_foto.pendente)
        self.assertIn("Achamos o nome e a foto", f.mensagem.text())
        f.campos["nome"].setText("MEU NOME")
        f.preencher_pela_internet(self.http)
        self.assertEqual(f.campos["nome"].text(), "MEU NOME")             # não troca o que já foi digitado
        f.campos["cbarra"].setText("")
        self.assertFalse(f.preencher_pela_internet(self.http))
        self.assertIn("8 a 14", f.mensagem.text())
