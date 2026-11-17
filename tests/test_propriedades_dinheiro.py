"""Testes de propriedade do dinheiro e do estoque: regras que valem para QUALQUER venda, conferidas com vendas sorteadas.

Sem biblioteca nova: um sorteio com semente fixa (repetível). Para sortear mais casos numa investigação:
    WILLPDV_CASOS=500 python -m unittest tests.test_propriedades_dinheiro
Se um caso falhar, a mensagem traz a semente; rode de novo com WILLPDV_SEMENTE=<semente> para reproduzir.
"""
from __future__ import annotations

import os
import random

from src.core import formatacao as fmt
from tests.test_caixa import BaseCaixa
from tests.base import BaseTeste

CASOS = int(os.environ.get("WILLPDV_CASOS", "40"))
SEMENTE = int(os.environ.get("WILLPDV_SEMENTE", "20261117"))


class TesteFormatacao(BaseTeste):
    def test_centavos_vao_e_voltam_do_texto_sem_perder_um_centavo(self):
        rng = random.Random(SEMENTE)
        valores = [0, 1, -1, 99, 100, 101, 123456789, -123456789] + [rng.randint(-10**10, 10**10) for _ in range(2000)]
        for cent in valores:
            self.assertEqual(fmt.para_centavos(fmt.fmt_num(cent)), cent, cent)
            self.assertEqual(fmt.para_centavos(fmt.fmt_brl(cent).replace("-R$ ", "-")), cent, cent)

    def test_preco_vezes_quantidade_e_divisao_sao_inteiros_e_coerentes(self):
        rng = random.Random(SEMENTE + 1)
        for _ in range(2000):
            preco = rng.randint(1, 500_000)
            qtd = round(rng.uniform(0.001, 50), rng.choice((0, 1, 3)))
            if not qtd:
                continue
            total = fmt.mult_cent(preco, qtd)
            self.assertIsInstance(total, int)
            self.assertLessEqual(abs(total - preco * qtd), 0.5 + 1e-9, (preco, qtd))
            self.assertLessEqual(abs(fmt.dividir_cent(total, qtd) - preco), 1 / qtd + 1, (preco, qtd))


class TesteVendaSorteada(BaseCaixa):
    """Qualquer venda: o que entra no caixa (pago - troco) é o total, e o estoque baixa exatamente o vendido."""

    def setUp(self):
        super().setUp()
        self.produtos = [self.skol, self.agua,
                         self.novo_produto("RED BULL", 1250, estoque=True, qt=500),
                         self.novo_produto("SEDA", 350, estoque=True, qt=500),
                         self.novo_produto("PORCAO", 3990)]

    def estoque(self) -> dict[int, float]:
        return {r["id"]: r["qt_atual"] for r in self.banco.todos("SELECT id, qt_atual FROM produtos")}

    def controla(self, pid) -> bool:
        return bool(self.banco.valor("SELECT controla_estoque FROM produtos WHERE id = ?", (pid,)))

    def test_pago_menos_troco_e_o_total_e_o_estoque_fecha(self):
        for caso in range(CASOS):
            semente = SEMENTE * 1000 + caso
            rng = random.Random(semente)
            with self.subTest(semente=semente):
                antes = self.estoque()
                vid = self.caixa.abrir_balcao()
                vendido: dict[int, float] = {}
                itens = []
                for _ in range(rng.randint(1, 6)):
                    pid, qtd = rng.choice(self.produtos), rng.randint(1, 5)
                    itens.append((self.caixa.adicionar_item(vid, pid, qtd), pid, qtd))
                    vendido[pid] = vendido.get(pid, 0) + qtd
                if len(itens) > 1 and rng.random() < 0.4:        # cancela um item inteiro no meio
                    item_id, pid, qtd = itens.pop(rng.randrange(len(itens)))
                    self.caixa.cancelar_item(item_id, "teste")
                    vendido[pid] -= qtd
                v = self.caixa.obter(vid)
                for campo in ("total_cent", "desconto_cent", "servico_cent"):
                    self.assertIsInstance(v[campo], int, campo)
                total = v["total_cent"]
                self.assertEqual(total, self.caixa.liquidar(vid)["falta"])
                restante = total
                while restante > 0:                               # paga em partes, a última com sobra (troco)
                    parte = rng.randint(1, restante) if rng.random() < 0.5 else restante + rng.choice((0, 0, 50, 1000))
                    self.pagar(vid, "Dinheiro", parte)
                    restante -= parte
                self.caixa.fechar(vid)
                pags = self.caixa.pagamentos(vid)
                self.assertEqual(sum(p["valor_cent"] - p["troco_cent"] for p in pags), total)
                self.assertTrue(all(p["troco_cent"] >= 0 for p in pags))
                depois = self.estoque()
                for pid, qtd in vendido.items():
                    esperado = antes[pid] - qtd if self.controla(pid) else antes[pid]
                    self.assertAlmostEqual(depois[pid], esperado, places=4, msg=f"produto {pid}")

    def test_cancelar_a_venda_devolve_o_estoque_inteiro(self):
        for caso in range(max(CASOS // 4, 5)):
            semente = SEMENTE * 1000 + 500 + caso
            rng = random.Random(semente)
            with self.subTest(semente=semente):
                antes = self.estoque()
                vid = self.caixa.abrir_balcao()
                for _ in range(rng.randint(1, 5)):
                    self.caixa.adicionar_item(vid, rng.choice(self.produtos), rng.randint(1, 4))
                self.caixa.cancelar_venda(vid, "teste de propriedade")
                for pid, qt in self.estoque().items():
                    self.assertAlmostEqual(qt, antes[pid], places=4, msg=f"produto {pid}")

    def test_dividir_o_restante_soma_exatamente_o_que_falta(self):
        for caso in range(CASOS):
            semente = SEMENTE * 1000 + 900 + caso
            rng = random.Random(semente)
            with self.subTest(semente=semente):
                vid = self.caixa.abrir_balcao()
                for _ in range(rng.randint(1, 4)):
                    self.caixa.adicionar_item(vid, rng.choice(self.produtos), rng.randint(1, 7))
                partes = rng.randint(2, 7)
                valores = self.caixa.dividir_restante(vid, partes)
                self.assertEqual(sum(valores), self.caixa.liquidar(vid)["falta"])
                self.assertLessEqual(max(valores) - min(valores), 1)
                self.caixa.cancelar_venda(vid, "fim do caso")
