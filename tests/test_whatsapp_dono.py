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

    def test_alertas_agrupam_o_dia_e_ignoram_fechamento_sem_contagem(self):
        from src.whatsapp.alertas import contagem_informada
        self.assertFalse(contagem_informada({"valor_final_cent": None, "resultado_cent": -8000}))
        self.assertFalse(contagem_informada({"valor_final_cent": 0, "resultado_cent": -8000, "formas": []}))
        self.assertTrue(contagem_informada({"valor_final_cent": 9000, "formas": [
            {"tipo": "Dinheiro", "informado_cent": 9000}]}))
        muitos = [{"turno_numero": n, "operador": "ANA", "resultado_cent": -8000,
                   "valor_final_cent": 0, "dia": "2026-10-01", "fechado_em": "2026-10-01 06:00:00"}
                  for n in range(30)]
        muitos.append({"turno_numero": 9, "operador": "ANA", "resultado_cent": -800,
                       "valor_final_cent": 9200, "dia": "2026-10-03", "fechado_em": "2026-10-03 06:00:00",
                       "formas": [{"tipo": "Dinheiro", "informado_cent": 9200, "esperado_cent": 10000}]})
        alertas = montar(
            {"vendas": {"canceladas": 2, "canceladas_cent": 8000, "desconto_cent": 1000}, "loja": {"nome": "Bar"}},
            {"loja_nome": "Bar", "sangrias": [
                {"valor_cent": 30000, "descricao": "malote", "criado_em": "2026-10-03 22:00:00", "dia": "2026-10-03"},
                {"valor_cent": 90000, "descricao": "ontem", "criado_em": "2026-10-02 22:00:00", "dia": "2026-10-02"}],
             "caixa": {"turno_numero": 1}, "momento": "2026-10-03 12:00:00",
             "comandas": [{"rotulo": "C7", "aberta_em": "2026-10-03 01:00:00"}],
             "fechamentos": muitos,
             "estoque": {"zerados": 1, "abaixo_minimo_total": 1, "abaixo_minimo": [{"nome": "GIN"}]}},
            {"cancelamento_cent": 5000, "desconto_cent": 5000, "sangria_cent": 20000, "mesa_horas": 4,
             "caixa_cent": 500, "expediente_de": "18:00", "expediente_ate": "02:00",
             "tipos": {"desconto": False}},
            dia="2026-10-03", hoje="2026-10-03")
        tipos = {a["tipo"]: a["quantidade"] for a in alertas}
        self.assertEqual(tipos["conferencia"], 1)
        self.assertEqual(alertas[[a["tipo"] for a in alertas].index("conferencia")]["itens"][0]["valor_cent"], -800)
        self.assertNotIn("desconto", tipos)
        self.assertLessEqual(len(alertas), 7)

    def test_contagem_mostra_a_perda_e_ajusta_o_saldo(self):
        self.banco.executar("UPDATE produtos SET ult_preco_cent = 300 WHERE id = ?", (self.skol,))
        estoque = EstoqueController(self.banco, self.adm)
        previa = estoque.simular_contagem([(self.skol, 90)])
        self.assertEqual(previa[0]["perda_unidades"], 10)
        self.assertGreater(previa[0]["perda_cent"], 0)
        resultado = estoque.aplicar_contagem([(self.skol, 90)])
        self.assertEqual(resultado["perda_cent"], previa[0]["perda_cent"])
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 90)
