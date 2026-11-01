"""Painel do dono para bar, boate e adega: perfil, mês até agora e relatório por período."""
from __future__ import annotations

import unittest
from datetime import date

from backend import painel
from src.sync import painel_envio
from tests.test_painel_dono import BaseNuvem, BasePainel, TestClient, cabecalho


class TestePerfilEMes(unittest.TestCase):
    def test_marco_longo_compara_com_o_fim_de_fevereiro(self):
        inicio, ate, ant_ini, ant_fim = painel.faixa_mes_ate(date(2026, 3, 31))
        self.assertEqual((inicio, ate, ant_ini, ant_fim),
                         (date(2026, 3, 1), date(2026, 3, 31), date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(painel.faixa_mes_ate(date(2026, 3, 15))[2:], (date(2026, 2, 1), date(2026, 2, 15)))

    def test_garota_e_portaria_somem_quando_a_casa_nao_usa(self):
        bar = {"usar_mesas": True, "usar_garotas": False, "usar_portaria": False}
        perfil = painel.perfil_do_painel(bar, [{"garota": True}], {"linhas": [{"garota": 1}]})
        self.assertFalse(perfil["mostrar_garotas"])
        self.assertFalse(perfil["mostrar_portaria"])
        self.assertTrue(perfil["mostrar_salao"])
        adega = {"usar_mesas": False, "usar_garotas": False, "usar_portaria": False}
        self.assertFalse(painel.perfil_do_painel(adega, [], None)["mostrar_salao"])
        antigo_vazio = painel.perfil_do_painel(None, [], {"linhas": []})
        self.assertFalse(antigo_vazio["mostrar_garotas"])
        self.assertTrue(painel.perfil_do_painel(None, [{"garota": True}], {"linhas": []})["mostrar_garotas"])

    def test_servico_nao_entra_no_consumo_e_o_custo_vira_cmv(self):
        vendas = [{"status": "fechada", "modalidade": "mesa", "total_cent": 1100, "subtotal_cent": 1000,
                   "desconto_cent": 0, "servico_cent": 100, "pessoas": 2, "garcom": "ANA",
                   "aberta_em": "2026-10-03 20:00:00", "fechada_em": "2026-10-03 21:00:00",
                   "itens": [{"nome": "SKOL", "quantidade": 2, "total_cent": 1000, "cancelado": 0,
                              "grupo": "Bebidas", "setor": "Bar", "custo_unit_cent": 300, "comissao_cent": 0}]}]
        bar = painel.indicadores_bar(vendas, 10)
        self.assertEqual((bar["servico_cent"], bar["consumo_cent"], bar["cmv_cent"], bar["margem_cent"]),
                         (100, 1000, 600, 400))
        self.assertEqual(bar["mesas"]["ticket_pessoa_cent"], 550)
        self.assertEqual(bar["mesas"]["permanencia_min"], 60)
        self.assertEqual(bar["garcons"][0]["comissao_cent"], 100)
        self.assertEqual(bar["setores"][0]["nome"], "Bar")
        self.assertEqual(bar["grupos"][0]["nome"], "Bebidas")


class TesteEnvioDoBar(BasePainel):
    def test_retrato_leva_mesa_garcom_e_modulos_sem_estoque_no_item(self):
        self.banco.cfg_set("usar_mesas", "S")
        self.banco.cfg_set("usar_garotas", "N")
        self.banco.cfg_set("usar_portaria", "N")
        self.banco.cfg_set("servico_pct", "10")
        self.banco.executar("UPDATE produtos_historico SET custo_cent = 300 WHERE id = ?", (self.skol,))
        vid, _ = self.caixa.abrir_mesa(4)
        self.banco.executar("UPDATE vendas SET garcom_id = ? WHERE id = ?", (self.adm, vid))
        self.caixa.adicionar_item(vid, self.skol, 1)
        r = painel_envio.retrato(self.banco)
        self.assertEqual(r["modulos"]["usar_garotas"], False)
        self.assertEqual(r["modulos"]["servico_pct"], 10)
        mesa = next(c for c in r["comandas"] if c["numero"] == 4 and c["comanda"] is False)
        self.assertEqual(mesa["garcom"], "ADM")
        self.assertTrue(mesa["itens"])
        self.assertNotIn("custo_unit_cent", mesa["itens"][0])
        venda = self.venda_fechada((self.skol, 2))
        item = painel_envio.coletar_vendas(self.banco)[0]["itens"][0]
        self.assertEqual((item["custo_unit_cent"], item["grupo"]), (300, item["grupo"]))
        self.assertNotIn("qt_atual", item)
        self.assertIn("garcom", painel_envio.coletar_vendas(self.banco)[0])
        self.assertTrue(venda["uuid"])


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TestePeriodoNaNuvem(BaseNuvem):
    def test_mes_ate_agora_e_relatorio_de_intervalo(self):
        def venda(uuid, dia, total, servico, forma):
            return {"uuid": uuid, "status": "fechada", "dia": dia, "total_cent": total, "desconto_cent": 0,
                    "servico_cent": servico, "modalidade": "balcao",
                    "pagamentos": [{"tipo": forma, "valor_cent": total, "troco_cent": 0}],
                    "itens": [{"nome": "X", "quantidade": 1, "total_cent": total - servico, "cancelado": 0}]}
        r = self.http.post("/v1/painel/envio", json={
            "vendas": [venda("m1", "2026-10-03", 1100, 100, "Pix"), venda("m2", "2026-10-02", 500, 0, "Dinheiro"),
                       venda("m3", "2026-09-10", 800, 80, "Pix")],
            "retrato": {"terminal_id": "cx", "dia_operacional": "2026-10-03", "momento": "2026-10-03 21:00:00",
                        "modulos": {"usar_mesas": True, "usar_garotas": False, "usar_portaria": False,
                                    "usar_cozinha_bar": False, "servico_pct": 10, "comissao_garcom_pct": 0},
                        "comandas": []},
        }, headers=cabecalho())
        self.assertEqual(r.status_code, 200, r.text)
        sessao = self.entrar()
        resumo = self.http.get("/v1/painel/resumo", headers=sessao).json()
        self.assertEqual(resumo["mes"]["de"], "2026-10-01")
        self.assertEqual(resumo["mes"]["ate"], "2026-10-03")
        self.assertEqual(resumo["mes"]["faturamento_cent"], 1600)
        self.assertEqual(resumo["mes"]["anterior"]["faturamento_cent"], 0)
        self.assertEqual(resumo["mes"]["variacao_cent"], 1600)
        self.assertFalse(resumo["perfil"]["mostrar_garotas"])
        self.assertFalse(resumo["perfil"]["mostrar_portaria"])
        per = self.http.get("/v1/painel/periodo", params={"de": "2026-09-01", "ate": "2026-10-03"}, headers=sessao).json()
        self.assertEqual((per["faturamento_cent"], per["quantidade"], per["ticket_medio_cent"], per["servico_cent"]),
                         (2400, 3, 800, 180))
        self.assertEqual(per["meses"], [
            {"mes": "2026-09", "faturamento_cent": 800, "quantidade": 1, "servico_cent": 80},
            {"mes": "2026-10", "faturamento_cent": 1600, "quantidade": 2, "servico_cent": 100},
        ])
        self.assertEqual(next(f["valor_cent"] for f in per["formas"] if f["tipo"] == "Pix"), 1900)
        self.assertEqual(next(d for d in per["dias"] if d["dia"] == "2026-09-10")["faturamento_cent"], 800)
        self.assertEqual(next(d for d in per["dias"] if d["dia"] == "2026-09-01")["faturamento_cent"], 0)
        self.assertEqual(self.http.get("/v1/painel/periodo", params={"de": "2026-10-03", "ate": "2026-10-01"},
                                       headers=sessao).status_code, 422)
        outra = self.entrar("ADEGA-2", "senha-da-outra")
        self.assertEqual(self.http.get("/v1/painel/periodo", params={"de": "2026-09-01", "ate": "2026-10-03"},
                                       headers=outra).json()["quantidade"], 0)


if __name__ == "__main__":
    unittest.main()
