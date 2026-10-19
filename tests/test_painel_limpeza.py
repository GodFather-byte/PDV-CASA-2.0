"""Limpeza automática da nuvem do painel: vendas além da retenção, sessões vencidas e caixas parados."""
from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from unittest import mock

from tests.test_painel_caixas import retrato_manual
from tests.test_painel_dono import BaseNuvem, TestClient, cabecalho, lojas, nuvem, painel


def texto(momento: datetime) -> str:
    return momento.strftime("%Y-%m-%d %H:%M:%S")


def semear_venda(db, uuid, dia, loja="ADEGA-1"):
    db.add(painel.PainelVenda(chave_loja=loja, uuid=uuid, dia=dia, status="fechada", modalidade="balcao", total_cent=1000,
                              dados=json.dumps({"uuid": uuid, "itens": [], "pagamentos": []}), recebida_em=texto(datetime.now())))


def venda_do_pdv(uuid, dia, status="fechada"):
    return {"uuid": uuid, "dia": dia, "status": status, "modalidade": "balcao", "total_cent": 1000,
            "fechada_em": f"{dia} 21:00:00", "itens": [], "pagamentos": []}


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteRetencao(BaseNuvem):
    """O "hoje" da nuvem é 2026-10-03 nos testes (BaseNuvem); com 120 dias de retenção o primeiro dia guardado é 2026-06-05."""

    def setUp(self):
        super().setUp()
        ambiente = mock.patch.dict(os.environ)
        ambiente.start()
        self.addCleanup(ambiente.stop)
        os.environ.pop("PDV_PAINEL_RETENCAO_DIAS", None)

    def com_banco(self):
        db = nuvem.SessionLocal()
        self.addCleanup(db.close)
        return db

    def dias_guardados(self, db):
        return sorted(v.dia for v in db.query(painel.PainelVenda))

    # ---- quanto tempo guardar
    def test_padrao_de_120_dias_e_o_valor_do_ambiente(self):
        self.assertEqual(painel.retencao_vendas_dias(), 120)
        os.environ["PDV_PAINEL_RETENCAO_DIAS"] = "45"
        self.assertEqual(painel.retencao_vendas_dias(), 45)
        self.assertEqual(painel._corte_das_vendas(), "2026-08-19")

    def test_valor_de_ambiente_ruim_nao_apaga_o_movimento_recente(self):
        for ruim, esperado in (("", 120), ("abc", 120), ("0", 7), ("-30", 7), ("3", 7), ("7", 7)):
            os.environ["PDV_PAINEL_RETENCAO_DIAS"] = ruim
            self.assertEqual(painel.retencao_vendas_dias(), esperado, ruim)

    def test_a_retencao_cobre_o_historico_de_90_dias_do_app(self):
        self.assertGreaterEqual(painel.RETENCAO_VENDAS_DIAS, 90)

    # ---- o que a limpeza apaga
    def test_apaga_so_as_vendas_antes_do_corte(self):
        db = self.com_banco()
        for n, dia in enumerate(("2026-06-04", "2026-06-05", "2026-06-06", "2026-10-03")):
            semear_venda(db, f"v{n}", dia)
        semear_venda(db, "outra", "2026-01-01", loja="ADEGA-2")
        db.commit()
        removidas = painel.limpar_antigos(db)
        self.assertEqual(removidas["vendas"], 2)
        self.assertEqual(self.dias_guardados(db), ["2026-06-05", "2026-06-06", "2026-10-03"])     # o dia do corte fica

    def test_apaga_sessoes_vencidas_e_deixa_as_vigentes(self):
        db = self.com_banco()
        agora = datetime.now()
        for n, expira in enumerate((agora - timedelta(days=1), agora - timedelta(seconds=1), agora + timedelta(days=5))):
            db.add(painel.PainelSessao(chave_loja="ADEGA-1", token_hash=f"hash{n}", criada_em=texto(agora),
                                       expira_em=texto(expira)))
        db.commit()
        self.assertEqual(painel.limpar_antigos(db)["sessoes"], 2)
        self.assertEqual([s.token_hash for s in db.query(painel.PainelSessao)], ["hash2"])

    def test_sessao_vigente_continua_abrindo_o_painel_depois_da_limpeza(self):
        sessao = self.entrar()
        painel.limpar_antigos(self.com_banco())
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=sessao).status_code, 200)

    def test_apaga_caixas_que_nao_mandam_retrato_ha_semanas(self):
        db = self.com_banco()
        agora = datetime.now()
        for terminal_id, parado_ha in (("velho", timedelta(days=painel.DIAS_CAIXA_PARADO, minutes=1)),
                                       ("ontem", timedelta(days=1))):
            db.add(painel.PainelCaixa(chave_loja="ADEGA-1", terminal_id=terminal_id, terminal=1, dados="{}",
                                      recebido_em=texto(agora - parado_ha)))
        db.commit()
        self.assertEqual(painel.limpar_antigos(db)["caixas"], 1)
        self.assertEqual([c.terminal_id for c in db.query(painel.PainelCaixa)], ["ontem"])

    def test_repetir_nao_apaga_mais_nada(self):
        db = self.com_banco()
        semear_venda(db, "v", "2026-01-01")
        db.commit()
        self.assertEqual(painel.limpar_antigos(db), {"vendas": 1, "sessoes": 0, "caixas": 0})
        self.assertEqual(painel.limpar_antigos(db), {"vendas": 0, "sessoes": 0, "caixas": 0})

    def test_configuracao_de_senha_e_lojas_nunca_sao_tocadas(self):
        self.entrar()
        db = self.com_banco()
        painel.limpar_antigos(db)
        self.assertEqual(db.query(painel.PainelAcesso).count(), 1)
        self.assertEqual(db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja.in_(["ADEGA-1", "ADEGA-2"])).count(), 2)

    # ---- venda velha nem entra
    def test_venda_alem_da_retencao_e_confirmada_mas_nao_guardada(self):
        corpo = {"vendas": [venda_do_pdv("antiga", "2026-05-01"), venda_do_pdv("cancelada-antiga", "2026-05-02", "cancelada"),
                            venda_do_pdv("recente", "2026-10-03")], "retrato": retrato_manual("a")}
        r = self.http.post("/v1/painel/envio", json=corpo, headers=cabecalho())
        self.assertEqual(r.json()["uuids"], ["antiga", "cancelada-antiga", "recente"])   # o PDV marca as três como enviadas
        self.assertEqual(self.dias_guardados(self.com_banco()), ["2026-10-03"])

    def test_primeiro_envio_de_um_historico_grande_nao_enche_o_banco(self):
        corpo = {"vendas": [venda_do_pdv(f"v{n}", (datetime(2026, 10, 3) - timedelta(days=n)).strftime("%Y-%m-%d"))
                            for n in range(200)], "retrato": retrato_manual("a")}
        self.http.post("/v1/painel/envio", json=corpo, headers=cabecalho())
        guardados = self.dias_guardados(self.com_banco())
        self.assertEqual(len(guardados), 121)                  # hoje e os 120 dias anteriores
        self.assertEqual(guardados[0], "2026-06-05")

    # ---- a limpeza sozinha
    def test_o_envio_dispara_a_limpeza_depois_da_resposta(self):
        painel._limpeza["ultima"] = None
        db = self.com_banco()
        semear_venda(db, "velha", "2026-01-01")
        db.commit()
        r = self.http.post("/v1/painel/envio", json={"vendas": [], "retrato": retrato_manual("a")}, headers=cabecalho())
        self.assertEqual(r.status_code, 200)
        db.expire_all()
        self.assertEqual(self.dias_guardados(db), [])

    def test_so_limpa_uma_vez_por_janela(self):
        painel._limpeza["ultima"] = None
        with mock.patch.object(painel, "limpar_antigos", return_value={"vendas": 0, "sessoes": 0, "caixas": 0}) as limpar, \
                mock.patch.object(painel.time, "monotonic") as relogio:
            relogio.return_value = 1000.0
            self.assertIsNotNone(painel.limpeza_periodica())
            relogio.return_value = 1000.0 + painel.INTERVALO_LIMPEZA_SEG - 1
            self.assertIsNone(painel.limpeza_periodica())
            relogio.return_value = 1000.0 + painel.INTERVALO_LIMPEZA_SEG
            self.assertIsNotNone(painel.limpeza_periodica())
        self.assertEqual(limpar.call_count, 2)

    def test_falha_na_limpeza_nao_derruba_o_envio(self):
        painel._limpeza["ultima"] = None
        with mock.patch.object(painel, "limpar_antigos", side_effect=RuntimeError("banco ocupado")), \
                mock.patch.object(painel.log, "exception") as registro:
            r = self.http.post("/v1/painel/envio", json={"vendas": [venda_do_pdv("v", "2026-10-03")],
                                                         "retrato": retrato_manual("a")}, headers=cabecalho())
        self.assertEqual((r.status_code, r.json()["uuids"]), (200, ["v"]))
        registro.assert_called_once()
        self.assertEqual(self.dias_guardados(self.com_banco()), ["2026-10-03"])

    # ---- na linha de comando
    def test_comando_de_linha_limpa_e_conta(self):
        db = self.com_banco()
        semear_venda(db, "v1", "2026-01-01")
        semear_venda(db, "v2", "2026-01-02")
        db.commit()
        saida = io.StringIO()
        with redirect_stdout(saida):
            self.assertEqual(lojas.main(["limpar-painel"]), 0)
        self.assertIn("2 vendas", saida.getvalue())
        self.assertIn("120 dias", saida.getvalue())
        db.expire_all()
        self.assertEqual(self.dias_guardados(db), [])


# --------------------------------------------------- a memória das tentativas de login
@unittest.skipIf(painel is None, "fastapi/httpx não instalados")
class TesteTentativasDeLogin(unittest.TestCase):
    def test_consultar_chave_desconhecida_nao_cria_entrada(self):
        t = painel._Tentativas()
        for n in range(100):
            self.assertFalse(t.bloqueada(f"loja-{n}"))
        self.assertEqual(len(t._falhas), 0)

    def test_falhas_vencidas_saem_ao_consultar(self):
        t = painel._Tentativas()
        t.falhou("A", agora=1000.0)
        self.assertFalse(t.bloqueada("A", agora=1000.0 + painel.JANELA_LOGIN_SEG + 1))
        self.assertEqual(len(t._falhas), 0)

    def test_nomes_inventados_nao_enchem_a_memoria(self):
        t = painel._Tentativas()
        with mock.patch.object(painel, "LIMITE_CHAVES_TENTATIVAS", 5):
            for n in range(5):
                t.falhou(f"inventada-{n}", agora=1000.0)
            self.assertEqual(len(t._falhas), 5)
            t.falhou("nova", agora=1000.0 + painel.JANELA_LOGIN_SEG + 1)          # as anteriores já passaram da janela
        self.assertEqual(list(t._falhas), ["nova"])

    def test_bloqueio_continua_funcionando(self):
        t = painel._Tentativas()
        for n in range(painel.TENTATIVAS_LOGIN):
            self.assertFalse(t.bloqueada("loja", agora=100.0 + n))
            t.falhou("loja", agora=100.0 + n)
        self.assertTrue(t.bloqueada("loja", agora=110.0))
        t.acertou("loja")
        self.assertFalse(t.bloqueada("loja", agora=110.0))


if __name__ == "__main__":
    unittest.main()
