"""Limite de consumo da comanda do cliente (R$ 200,00): ao chegar nele não lança mais; só comanda, na faixa configurada."""
from __future__ import annotations

from src.core.erros import ErroNegocio
from tests.test_regras_caixa import BaseRegras


class TesteLimiteComanda(BaseRegras):
    def setUp(self):
        super().setUp()
        self.item = self.novo_produto("DOSE", 5000)          # R$ 50,00

    def test_padrao_e_200_reais(self):
        self.assertEqual(self.banco.cfg_int("limite_comanda", 200), 200)

    def test_trava_ao_chegar_em_200(self):
        v, _ = self.caixa.abrir_mesa(7, comanda=True)
        self.caixa.adicionar_item(v, self.item, 3)           # R$ 150
        self.caixa.adicionar_item(v, self.item, 1)           # R$ 200: chegou
        with self.assertRaises(ErroNegocio) as e:
            self.caixa.adicionar_item(v, self.item, 1)
        self.assertIn("acertar a comanda", str(e.exception))
        self.assertEqual(self.caixa.obter(v)["subtotal_cent"], 20000)

    def test_cancelar_item_libera_de_novo(self):
        v, _ = self.caixa.abrir_mesa(7, comanda=True)
        i = self.caixa.adicionar_item(v, self.item, 4)
        self.caixa.cancelar_item(i, "teste")
        self.caixa.adicionar_item(v, self.item, 1)

    def test_mesa_nao_tem_limite(self):
        v, _ = self.caixa.abrir_mesa(7)
        self.caixa.adicionar_item(v, self.item, 5)
        self.caixa.adicionar_item(v, self.item, 1)

    def test_configuravel_e_zero_desliga(self):
        self.banco.cfg_set("limite_comanda", "100")
        v, _ = self.caixa.abrir_mesa(7, comanda=True)
        self.caixa.adicionar_item(v, self.item, 2)
        with self.assertRaises(ErroNegocio):
            self.caixa.adicionar_item(v, self.item, 1)
        self.banco.cfg_set("limite_comanda", "0")
        self.caixa.adicionar_item(v, self.item, 1)

    def test_fora_da_faixa_nao_trava(self):
        self.banco.cfg_set("consumacao_minima_ate", "50")    # comandas das garotas: acima de 50
        v, _ = self.caixa.abrir_mesa(60, comanda=True)
        self.caixa.adicionar_item(v, self.item, 5)
        self.caixa.adicionar_item(v, self.item, 1)
