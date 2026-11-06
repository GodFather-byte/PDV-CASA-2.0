"""Promoção também no preço da gelada: mesmas janelas da natural, cada uma com o seu preço."""
from __future__ import annotations

from datetime import datetime

from src.controllers.cadastro_controller import CadastroController
from src.controllers.etiqueta_controller import EtiquetaController
from src.controllers.perfil_controller import PerfilController
from src.controllers.produto_controller import ProdutoController
from src.core.erros import ErroNegocio
from tests.test_caixa import BaseCaixa


class TestePromocaoGelada(BaseCaixa):
    def setUp(self):
        super().setUp()
        PerfilController(self.banco, self.adm).aplicar("adega")
        self.banco.executar(
            """UPDATE produtos SET preco_gelada_cent = 1000, promo_de = '2026-10-01', promo_ate = '2026-10-31',
               promo_preco_cent = 700, promo_gelada_cent = 900 WHERE id = ?""", (self.skol,))
        self.vid = self.caixa.abrir_balcao()

    def item(self, item_id):
        return dict(self.banco.um("SELECT * FROM itens_venda WHERE id = ?", (item_id,)))

    def test_caixa_cobra_a_gelada_em_promocao_dentro_do_periodo(self):
        gelada = self.item(self.caixa.adicionar_item(self.vid, self.skol, 1, temperatura="gelada"))
        natural = self.item(self.caixa.adicionar_item(self.vid, self.skol, 1))
        self.assertEqual((gelada["preco_unit_cent"], natural["preco_unit_cent"]), (900, 700))
        explicacao = ProdutoController.explicacao_preco_adega(gelada, "balcao")
        self.assertIn("Promoção", explicacao["rotulo"])
        self.assertIn("Gelada", explicacao["rotulo"])

    def test_fora_do_periodo_volta_ao_preco_gelado_normal(self):
        p = self.prod.por_id(self.skol)
        self.assertEqual(self.prod.preco_gelada_vigente(p, datetime(2026, 11, 2, 12)), 1000)
        self.assertEqual(self.prod.preco_gelada_vigente(p, datetime(2026, 10, 15, 12)), 900)

    def test_horario_e_dia_escolhem_a_menor_e_nunca_acima_da_normal(self):
        self.banco.executar(
            """UPDATE produtos SET hora_ini = '18:00', hora_fim = '20:00', hora_preco_cent = 650,
               hora_gelada_cent = 850 WHERE id = ?""", (self.skol,))
        p = self.prod.por_id(self.skol)
        regra = self.prod.regra_preco_gelada(p, datetime(2026, 10, 3, 19))
        self.assertEqual((regra["preco_cent"], regra["criterio"]), (850, "horário"))
        self.assertEqual(self.prod.preco_gelada_vigente(p, datetime(2026, 10, 3, 21)), 900)
        sem_gelada = {**p, "preco_gelada_cent": 0}
        self.assertEqual(self.prod.regra_preco_gelada(sem_gelada)["tipo"], "gelada")

    def test_atacado_da_gelada_vale_se_for_menor_que_a_promocao(self):
        self.banco.executar("UPDATE produtos SET atacado_gelada_qtd = 6, preco_atacado_gelada_cent = 850 WHERE id = ?",
                            (self.skol,))
        item = self.item(self.caixa.adicionar_item(self.vid, self.skol, 6, temperatura="gelada"))
        self.assertEqual(item["preco_unit_cent"], 850)

    def test_etiqueta_mostra_a_gelada_em_promocao(self):
        etiquetas = EtiquetaController(self.banco).etiquetas([{"produto_id": self.skol, "temperatura": "ambas"}])
        self.assertEqual([(e["temperatura"], e["preco_cent"]) for e in etiquetas], [("natural", 700), ("gelada", 900)])

    def test_cadastro_valida_a_promocao_da_gelada(self):
        cad = CadastroController(self.banco)
        valores = cad.exibir("produtos", cad.obter("produtos", self.skol))
        valores = {k: v for k, v in valores.items() if k not in ("qt_atual", "qt_inicial", "ult_preco_cent",
                                                                   "ult_atualizacao")}
        valores.update(subgrupo_id=self.banco.valor("SELECT subgrupo_id FROM produtos WHERE id = ?", (self.skol,)),
                       unidade_id=self.banco.valor("SELECT unidade_id FROM produtos WHERE id = ?", (self.skol,)))
        for campo, valor, trecho in (("promo_gelada_cent", "11,00", "superar"),
                                     ("hora_gelada_cent", "8,00", "início e fim")):
            with self.assertRaisesRegex(ErroNegocio, trecho):
                cad.salvar("produtos", {**valores, campo: valor}, self.skol)
        with self.assertRaisesRegex(ErroNegocio, "preço gelada"):
            cad.salvar("produtos", {**valores, "preco_gelada_cent": "0,00", "promo_gelada_cent": "5,00"}, self.skol)
        cad.salvar("produtos", {**valores, "promo_gelada_cent": "9,50"}, self.skol)
        self.assertEqual(self.banco.valor("SELECT promo_gelada_cent FROM produtos WHERE id = ?", (self.skol,)), 950)
