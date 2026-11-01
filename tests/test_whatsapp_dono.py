"""Resumo e alertas do WhatsApp, sem bot, e a contagem de estoque."""
from __future__ import annotations

from unittest import mock

from src.controllers.estoque_controller import EstoqueController
from src.whatsapp.alertas import montar
from src.whatsapp.caixa import enviar_no_fechamento, montar as montar_caixa
from src.whatsapp.resumo import link, numeros, texto_resumo
from tests.test_caixa import BaseCaixa


class TesteWhatsApp(BaseCaixa):
    def test_numeros_ganham_ddi_e_o_link_nao_chama_api(self):
        self.assertEqual(numeros("11 98888-7777, 5511977776666"), ["5511988887777", "5511977776666"])
        self.assertEqual(numeros("123"), [])
        url = link("5511988887777", "Olá")
        self.assertTrue(url.startswith("https://wa.me/5511988887777?text="))

    def test_resumo_do_dia_traz_os_blocos_e_o_fechamento_abre_o_whatsapp(self):
        vid = self.vender((self.skol, 2))
        self.pagar(vid, "Dinheiro", self.caixa.obter(vid)["total_cent"])
        self.caixa.fechar(vid)
        esperado = self.turnos.resumo(self.turno)["esperado"]
        self.turnos.fechar(self.turno, self.adm, esperado)
        dados = montar_caixa(self.banco)
        texto = texto_resumo(dados)
        self.assertIn("Vendas: 1", texto)
        self.assertIn("Formas de pagamento", texto)
        self.assertIn("Conferência de caixa", texto)
        self.assertIn("Sangrias", texto)
        abertos = []
        self.assertIsNone(enviar_no_fechamento(self.banco))
        self.banco.cfg_set("whatsapp_dono", "11988887777")
        with mock.patch("src.whatsapp.caixa.abrir", side_effect=lambda dest, txt, abrir_url=None: abertos.append(dest) or dest):
            texto = enviar_no_fechamento(self.banco)
        self.assertIn("5511988887777", abertos[-1])
        self.assertIn("Total do período", texto)

    def test_alertas_saem_dos_dados_que_ja_estao_no_retrato(self):
        alertas = montar(
            {"vendas": {"canceladas": 2, "canceladas_cent": 8000, "desconto_cent": 1000}, "loja": {"nome": "Bar"}},
            {"loja_nome": "Bar", "sangrias": [{"valor_cent": 30000, "descricao": "malote", "criado_em": "2026-10-03 22:00:00"}],
             "caixa": {"turno_numero": 1}, "momento": "2026-10-03 12:00:00",
             "comandas": [{"rotulo": "C7", "aberta_em": "2026-10-03 01:00:00"}],
             "fechamentos": [{"turno_numero": 1, "operador": "ANA", "resultado_cent": -500}],
             "estoque": {"zerados": 1, "abaixo_minimo_total": 1, "abaixo_minimo": [{"nome": "GIN"}]}},
            {"cancelamento_cent": 5000, "desconto_cent": 5000, "sangria_cent": 20000, "mesa_horas": 4,
             "expediente_de": "18:00", "expediente_ate": "02:00"})
        tipos = {a["tipo"] for a in alertas}
        self.assertTrue({"cancelamento", "sangria", "mesa", "expediente", "conferencia", "estoque"} <= tipos)
        self.assertNotIn("desconto", tipos)

    def test_contagem_mostra_a_perda_e_ajusta_o_saldo(self):
        self.banco.executar("UPDATE produtos SET ult_preco_cent = 300 WHERE id = ?", (self.skol,))
        estoque = EstoqueController(self.banco, self.adm)
        previa = estoque.simular_contagem([(self.skol, 90)])
        self.assertEqual(previa[0]["perda_unidades"], 10)
        self.assertGreater(previa[0]["perda_cent"], 0)
        resultado = estoque.aplicar_contagem([(self.skol, 90)])
        self.assertEqual(resultado["perda_cent"], previa[0]["perda_cent"])
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 90)
