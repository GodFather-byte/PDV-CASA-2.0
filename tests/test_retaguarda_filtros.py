"""Retaguarda: filtros prontos de produto (estoque baixo, sem estoque, sem preço, abaixo do custo, sem NCM e sem código de
barras), ordenação por coluna e a lista inteira para exportar a planilha. Tela: botão Mostrar senha no painel do dono."""
import unittest
import unittest.mock
from pathlib import Path

from src.sync import retaguarda
from tests.test_notas_dono import _Ponte
from tests.test_painel_dono import BaseNuvem, TestClient, nuvem

try:
    from backend import retaguarda as nuvem_retaguarda
except (ImportError, RuntimeError):
    nuvem_retaguarda = None

RAIZ = Path(__file__).resolve().parents[1]


@unittest.skipIf(TestClient is None or nuvem_retaguarda is None, "fastapi/httpx não instalados")
class TesteFiltrosRetaguarda(BaseNuvem):
    def setUp(self):
        super().setUp()
        with nuvem.SessionLocal() as db:
            db.query(nuvem_retaguarda.RetaguardaEspelho).delete()
            db.query(nuvem_retaguarda.RetaguardaComando).delete()
            db.commit()
        self.banco.cfg_set("retaguarda_nuvem", "S")
        self.dono = self.entrar()
        self.banco.executar("UPDATE produtos SET ativo = 0")                # só os produtos deste teste contam
        baixo = self.novo_produto("AAA BAIXO", preco=500, codigo="801", estoque=True)
        zerado = self.novo_produto("BBB ZERADO", preco=900, codigo="802", estoque=True)
        self.novo_produto("CCC SEM PRECO", preco=0, codigo="803")
        caro = self.novo_produto("DDD PREJUIZO", preco=300, codigo="804")
        self.banco.executar("UPDATE produtos SET qt_atual = 2, estoque_minimo = 5 WHERE id = ?", (baixo,))
        self.banco.executar("UPDATE produtos SET qt_atual = 0, estoque_minimo = 0 WHERE id = ?", (zerado,))
        self.banco.executar("UPDATE produtos SET custo_medio_cent = 450 WHERE id = ?", (caro,))
        self.banco.executar("UPDATE produtos SET ncm = '22030000', cbarra = '789000000' || codigo WHERE ativo = 1 AND nome <> 'CCC SEM PRECO'")
        retaguarda.sincronizar(self.banco, _Ponte(self.http), forcar=True)

    def nomes(self, **params):
        r = self.http.get("/v1/painel/retaguarda/cadastro/produtos", params={"inativos": 0, **params}, headers=self.dono)
        self.assertEqual(r.status_code, 200, r.text)
        dados = r.json()
        return [dict(zip(dados["campos"], l))["nome"] for l in dados["linhas"]]

    def test_filtros_prontos(self):
        self.assertEqual(self.nomes(filtro="estoque_baixo"), ["AAA BAIXO"])
        self.assertEqual(self.nomes(filtro="sem_estoque"), ["BBB ZERADO"])
        self.assertEqual(self.nomes(filtro="sem_preco"), ["CCC SEM PRECO"])
        self.assertEqual(self.nomes(filtro="abaixo_custo"), ["DDD PREJUIZO"])
        self.assertEqual(self.nomes(filtro="sem_ncm"), ["CCC SEM PRECO"])
        self.assertEqual(self.nomes(filtro="sem_codigo_barras"), ["CCC SEM PRECO"])

    def test_filtro_invalido_ou_fora_de_produtos(self):
        r = self.http.get("/v1/painel/retaguarda/cadastro/produtos", params={"filtro": "nada"}, headers=self.dono)
        self.assertEqual(r.status_code, 422)
        r = self.http.get("/v1/painel/retaguarda/cadastro/grupos", params={"filtro": "sem_preco"}, headers=self.dono)
        self.assertEqual(r.status_code, 422)

    def test_ordena_por_preco_e_nome_com_vazio_no_fim(self):
        self.assertEqual(self.nomes(ordem="preco_cent"), ["CCC SEM PRECO", "DDD PREJUIZO", "AAA BAIXO", "BBB ZERADO"])
        self.assertEqual(self.nomes(ordem="preco_cent", desc=1)[0], "BBB ZERADO")
        self.assertEqual(self.nomes(ordem="nome", desc=1), ["DDD PREJUIZO", "CCC SEM PRECO", "BBB ZERADO", "AAA BAIXO"])
        self.assertEqual(self.nomes(ordem="campo_que_nao_existe"), self.nomes())

    def test_exportar_traz_a_lista_inteira_sem_pagina(self):
        with unittest.mock.patch.object(nuvem_retaguarda, "PAGINA", 2):
            self.assertEqual(len(self.nomes()), 2)
            self.assertEqual(len(self.nomes(todas=1)), 4)


class TesteTelas(unittest.TestCase):
    def test_painel_tem_mostrar_senha_e_retaguarda_os_botoes_novos(self):
        painel = (RAIZ / "backend" / "painel_web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function configurarMostrarSenha()", painel)
        self.assertIn("configurarMostrarSenha();", painel)
        tela = (RAIZ / "backend" / "retaguarda_web" / "app.js").read_text(encoding="utf-8")
        for seletor in ("exportar-csv", "filtro-produtos", "duplicar-produto", '"ordenar-"'):
            self.assertIn(seletor, tela)


if __name__ == "__main__":
    unittest.main()
