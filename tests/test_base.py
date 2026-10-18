"""Testes da base: formatação, banco, cadastros genéricos."""
from __future__ import annotations

import os
import tempfile
import unittest

from src.controllers.cadastro_controller import CadastroController
from src.core import formatacao as fmt
from src.core import seguranca
from src.core.erros import ErroNegocio, ErroValidacao
from src.database.conexao import BancoDados
from tests.base import BaseTeste


class TesteFormatacao(unittest.TestCase):
    def test_para_centavos(self):
        casos = {"3,50": 350, "8.00": 800, "1.234,56": 123456, "12,5": 1250, "R$ 7,99": 799,
                 "": 0, 8: 800, 8.5: 850, "0,005": 1, "0,004": 0}
        for entrada, esperado in casos.items():
            self.assertEqual(fmt.para_centavos(entrada), esperado, entrada)
        with self.assertRaises(ValueError):
            fmt.para_centavos("abc")

    def test_formatos(self):
        self.assertEqual(fmt.fmt_brl(123456), "R$ 1.234,56")
        self.assertEqual(fmt.fmt_brl(-274), "-R$ 2,74")
        self.assertEqual(fmt.fmt_num(5), "0,05")
        self.assertEqual(fmt.fmt_qtd(1234.5), "1.234,500")

    def test_calculos_com_arredondamento_comercial(self):
        self.assertEqual(fmt.pct_de(1001, 10), 100)    # 100,1 -> 100
        self.assertEqual(fmt.pct_de(1005, 10), 101)    # 100,5 -> 101 (meio para cima)
        self.assertEqual(fmt.mult_cent(2190, 0.315), 690)  # torta: 21,90 x 0,315 = 6,8985 -> 6,90
        self.assertEqual(fmt.mult_cent(333, 3), 999)

    def test_datas(self):
        self.assertEqual(fmt.para_data_iso("03/10/2026"), "2026-10-03")
        self.assertEqual(fmt.para_data_iso(""), None)
        self.assertEqual(fmt.somar_meses("2026-01-31", 1), "2026-02-28")
        self.assertEqual(fmt.dia_semana("2026-10-03"), 7)   # sábado
        self.assertEqual(fmt.dia_semana("2026-10-04"), 1)   # domingo
        self.assertEqual(fmt.para_hora("18"), "18:00")
        with self.assertRaises(ValueError):
            fmt.para_hora("25:00")


class TesteSeguranca(unittest.TestCase):
    def test_senha_sem_diferenciar_caixa(self):
        h = seguranca.gerar_hash("Adm")
        self.assertTrue(seguranca.conferir("ADM", h))
        self.assertTrue(seguranca.conferir("adm", h))
        self.assertFalse(seguranca.conferir("adn", h))
        self.assertFalse(seguranca.conferir("adm", None))
        self.assertNotEqual(seguranca.gerar_hash("x"), seguranca.gerar_hash("x"))  # sal


class TesteBanco(BaseTeste):
    def test_sementes_minimas(self):
        self.assertEqual(self.banco.valor("SELECT nome FROM operadores"), "ADM")
        self.assertGreaterEqual(self.banco.valor("SELECT COUNT(*) FROM acessos"), 30)
        self.assertEqual(self.banco.valor("SELECT tipo FROM tipos_pagamento ORDER BY ordem LIMIT 1"), "Dinheiro")
        self.assertEqual(self.banco.cfg("servico_pct"), "10")

    def test_transacao_aninhada_reverte_so_o_trecho_interno(self):
        with self.banco.transacao():
            self.banco.executar("INSERT INTO cargos(nome) VALUES ('A')")
            with self.assertRaises(RuntimeError):
                with self.banco.transacao():
                    self.banco.executar("INSERT INTO cargos(nome) VALUES ('B')")
                    raise RuntimeError
        nomes = [r[0] for r in self.banco.todos("SELECT nome FROM cargos WHERE nome IN ('A','B')")]
        self.assertEqual(nomes, ["A"])

    def test_banco_legado_e_preservado_em_arquivo(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "loja.db")
            con = sqlite3.connect(caminho)
            con.execute("CREATE TABLE produtos (id INTEGER PRIMARY KEY, codigo_barras TEXT, nome TEXT, preco REAL)")
            con.execute("INSERT INTO produtos(nome, preco) VALUES ('VELHO', 5)")
            con.commit(); con.close()
            b = BancoDados(caminho)
            self.assertEqual(b.valor("SELECT COUNT(*) FROM produtos"), 0)
            b.fechar()
            guardados = [f for f in os.listdir(pasta) if ".legado-" in f]
            self.assertEqual(len(guardados), 1)


class TesteCadastros(BaseTeste):
    def setUp(self):
        super().setUp()
        self.cad = CadastroController(self.banco)

    def test_crud_basico_e_unicidade(self):
        gid = self.cad.salvar("grupos", {"nome": "BEBIDAS"})
        self.assertEqual(self.cad.obter("grupos", gid)["nome"], "BEBIDAS")
        with self.assertRaises(ErroNegocio) as e:
            self.cad.salvar("grupos", {"nome": "BEBIDAS"})
        self.assertIn("Já existe", str(e.exception))
        self.cad.salvar("grupos", {"nome": "DRINKS"}, id_=gid)
        self.assertEqual(self.cad.obter("grupos", gid)["nome"], "DRINKS")
        self.cad.excluir("grupos", gid)
        self.assertIsNone(self.cad.obter("grupos", gid))

    def test_obrigatorio_e_tamanho(self):
        with self.assertRaises(ErroValidacao) as e:
            self.cad.salvar("unidades", {"nome": "", "abreviatura": ""})
        self.assertIn("nome", e.exception.campos)
        with self.assertRaises(ErroValidacao):
            self.cad.salvar("unidades", {"nome": "Caixa", "abreviatura": "ABCDEFGH"})

    def test_excluir_em_uso_da_mensagem_amigavel(self):
        self.novo_produto("COCA")
        with self.assertRaises(ErroNegocio) as e:
            self.cad.excluir("grupos", self.banco.valor("SELECT id FROM grupos WHERE nome='DIVERSOS'"))
        self.assertIn("em uso", str(e.exception))

    def test_produto_codigo_13_digitos_e_unicos(self):
        pid = self.novo_produto("COCA COLA", 350, codigo="1")
        p = self.cad.obter("produtos", pid)
        self.assertEqual(p["codigo"], "0000000000001")
        self.assertEqual(p["preco_cent"], 350)
        with self.assertRaises(ErroNegocio):
            self.novo_produto("OUTRA", codigo="0000000000001")   # código repetido
        with self.assertRaises(ErroNegocio):
            self.novo_produto("COCA COLA", codigo="2")           # nome repetido
        with self.assertRaises(ErroValidacao):
            self.novo_produto("LONGO", codigo="12345678901234")  # 14 dígitos

    def test_codigo_de_barras_unico_mas_vazio_repete(self):
        self.novo_produto("A", cbarra="7891000100103")
        self.novo_produto("B")
        self.novo_produto("C")   # vários sem código de barras
        with self.assertRaises(ErroNegocio):
            self.novo_produto("D", cbarra="7891000100103")

    def test_exibir_formata_para_o_usuario(self):
        pid = self.novo_produto("TORTA", 2190, estoque=True)
        linha = self.cad.obter("produtos", pid)
        txt = self.cad.exibir("produtos", linha)
        self.assertEqual(txt["preco_cent"], "21,90")
        self.assertEqual(txt["controla_estoque"], "S")
        self.assertEqual(txt["subgrupo_id"], "DIVERSOS - DIVERSOS")

    def test_operador_senha_hash_e_ultimo_admin(self):
        oid = self.cad.salvar("operadores", {"nome": "Maria", "senha": "abc123", "nivel": "0"})
        senha = self.cad.obter("operadores", oid)["senha"]
        self.assertTrue(senha.startswith("pbkdf2$"))
        self.cad.salvar("operadores", {"nome": "Maria", "senha": "", "nivel": "1"}, id_=oid)
        self.assertEqual(self.cad.obter("operadores", oid)["senha"], senha)   # senha mantida
        with self.assertRaises(ErroValidacao):
            self.cad.salvar("operadores", {"nome": "Joao", "senha": "senha-longa-demais!", "nivel": "0"})
        adm = self.operador_adm()
        with self.assertRaises(ErroNegocio):
            self.cad.excluir("operadores", adm)
        with self.assertRaises(ErroNegocio):
            self.cad.salvar("operadores", {"nome": "ADM", "nivel": "2"}, id_=adm)

    def test_pesquisa_com_curingas_literais(self):
        self.novo_produto("DESCONTO 10%")
        self.novo_produto("OUTRO")
        achados = self.cad.listar("produtos", texto="10%")
        self.assertEqual([p["nome"] for p in achados], ["DESCONTO 10%"])

    def test_aliquota_formato_validado(self):
        with self.assertRaises(ErroValidacao):
            self.cad.salvar("aliquotas", {"descricao": "X", "aliquota": "5", "formato": "5,00%"})
        i = self.cad.salvar("aliquotas", {"descricao": "X", "aliquota": "5", "formato": "ii"})
        self.assertEqual(self.cad.obter("aliquotas", i)["formato"], "II")


if __name__ == "__main__":
    unittest.main()
