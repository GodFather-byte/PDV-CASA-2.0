"""Combos pela retaguarda: o caixa manda a lista de combos (com itens e o preço separado) e cria o combo pedido pelo
dono com as mesmas regras do "Criar combo" do caixa."""
import unittest
from pathlib import Path

from src.controllers.retaguarda_controller import RetaguardaController
from tests.base import BaseTeste

try:
    from backend import retaguarda as nuvem_retaguarda
except (ImportError, RuntimeError):
    nuvem_retaguarda = None

RAIZ = Path(__file__).resolve().parents[1]


class TesteCombosNoCaixa(BaseTeste):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("retaguarda_nuvem", "S")
        self.controle = RetaguardaController(self.banco)
        self.skol = self.novo_produto("SKOL", preco=500, codigo="10", estoque=True)
        self.gelo = self.novo_produto("GELO", preco=800, codigo="11", estoque=True)

    def aplicar(self, ident, dados):
        return self.controle.aplicar({"id": ident, "tipo": "produto.combo", "dados": dados, "resumo": "t", "autor": "dono"})

    def test_cria_combo_e_ele_aparece_na_lista_com_a_economia(self):
        r = self.aplicar(1, {"nome": "BALDE 6 SKOL + GELO", "preco_cent": 3200, "cbarra": "",
                             "itens": [{"produto_id": self.skol, "quantidade": 6}, {"produto_id": self.gelo, "quantidade": 1}]})
        self.assertEqual(r["situacao"], "aplicado", r)
        combos = self.controle.combos()
        self.assertEqual(len(combos), 1)
        c = combos[0]
        self.assertEqual((c["nome"], c["preco_cent"], c["avulso_cent"], c["fardo"]), ("BALDE 6 SKOL + GELO", 3200, 3800, False))
        self.assertEqual(sorted((i["nome"], i["quantidade"]) for i in c["itens"]), [("GELO", 1), ("SKOL", 6)])
        self.assertIn("combos", self.controle.espelho())

    def test_mesmas_regras_do_caixa(self):
        base = {"nome": "X", "preco_cent": 1000}
        casos = [
            {**base, "itens": []},
            {**base, "itens": [{"produto_id": self.skol, "quantidade": 1}]},              # 1 unidade só
            {**base, "preco_cent": 0, "itens": [{"produto_id": self.skol, "quantidade": 2}]},
            {**base, "preco_cent": "10", "itens": [{"produto_id": self.skol, "quantidade": 2}]},
            {**base, "itens": [{"produto_id": 9999, "quantidade": 2}]},
            {**base, "itens": [{"produto_id": self.skol, "quantidade": "abc"}]},
        ]
        for i, dados in enumerate(casos, start=10):
            self.assertEqual(self.aplicar(i, dados)["situacao"], "recusado", dados)
        self.assertEqual(self.controle.combos(), [])


@unittest.skipIf(nuvem_retaguarda is None, "fastapi não instalado")
class TesteNuvemETela(unittest.TestCase):
    def test_comando_aceito_e_rota_dos_combos(self):
        self.assertIn("produto.combo", nuvem_retaguarda.TIPOS_COMANDO)
        tela = (RAIZ / "backend" / "retaguarda_web" / "app.js").read_text(encoding="utf-8")
        for trecho in ('botao("combos", "Combos")', "async function telaCombos()", '"produto.combo"', "combo-salvar"):
            self.assertIn(trecho, tela)


if __name__ == "__main__":
    unittest.main()
