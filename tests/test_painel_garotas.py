"""Aba Garotas do painel do dono: o caixa manda os pagamentos às garotas (dinheiro, Pix, vale, consumo e shows) e a nuvem
os entrega no resumo. Caixa antigo, sem os pagamentos, aparece como não sincronizado (não como zero)."""
import unittest
from pathlib import Path

from src.controllers.comissao_controller import ComissaoController
from src.sync import painel_envio
from tests.test_painel_dono import BaseNuvem, BasePainel, TestClient


def pagar_ana(teste):
    com = ComissaoController(teste.banco)
    com.lancar(12, 5000, teste.turno, teste.adm)
    return com.pagar(12, teste.turno, teste.adm, tirar_do_caixa=True, shows=1, valor_show_cent=3000, pix_cent=2000,
                     vale_cent=1000)


class TesteEnvioGarotas(BasePainel):
    def test_retrato_leva_os_pagamentos_com_dinheiro_e_pix(self):
        self.banco.inserir("garotas", {"numero": 12, "nome": "ANA", "ativo": 1})
        pagar_ana(self)
        r = painel_envio.retrato(self.banco)["comissoes"]
        self.assertEqual(len(r["acertos"]), 1)
        a = r["acertos"][0]
        self.assertEqual((a["garota"], a["nome"], a["total_cent"], a["pix_cent"], a["vale_cent"], a["dinheiro_cent"],
                          a["shows"], a["shows_cent"]), (12, "ANA", 8000, 2000, 1000, 5000, 1, 3000))
        self.assertTrue(a["dia"])
        self.assertEqual(r["consumo_pendente_cent"], 0)


@unittest.skipIf(TestClient is None, "Dependências da nuvem ausentes")
class TesteNuvemGarotas(BaseNuvem):
    def test_resumo_entrega_os_pagamentos(self):
        self.preparar_noite()
        pagar_ana(self)
        self.subir()
        r = self.http.get("/v1/painel/resumo", headers=self.entrar()).json()["comissoes"]
        self.assertTrue(r["acertos_sincronizados"])
        self.assertEqual([(a["garota"], a["dinheiro_cent"], a["pix_cent"]) for a in r["acertos"]], [(12, 10000, 2000)])   # a noite já tinha 50,00 lançados

    def test_caixa_antigo_sem_pagamentos_fica_como_nao_sincronizado(self):
        from backend import painel
        bloco = painel._comissoes_publicas({"comissoes": {"linhas": [], "pendente_total_cent": 0}})
        self.assertIsNone(bloco["acertos"])


class TesteTelaGarotas(unittest.TestCase):
    def test_aba_garotas_no_painel_e_comissoes_fora_do_salao(self):
        html = (Path(__file__).resolve().parents[1] / "backend" / "painel_web" / "index.html").read_text(encoding="utf-8")
        aba = html[html.index('id="aba-garotas"'):html.index('id="aba-produtos"')]
        self.assertIn('id="bloco-comissoes"', aba)
        self.assertIn('id="lista-pagamentos-garotas"', aba)
        salao = html[html.index('id="aba-abertas"'):html.index('id="aba-garotas"')]
        self.assertNotIn('id="bloco-comissoes"', salao)
        self.assertIn('id="tab-garotas"', html)


if __name__ == "__main__":
    unittest.main()
