"""Relatório diário de vendas por e-mail (backend/relatorio_diario.py): conteúdo, configuração no painel e envio
uma vez por dia a partir das 08:00."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.test_painel_dono import BaseNuvem, TestClient, nuvem

if TestClient is not None:
    from backend import relatorio_diario as rel
    DISPARAR = rel.disparar_em_segundo_plano          # a função real (o setUp a troca para a nuvem não mandar nada)

DIA = "2026-10-03"                                   # o dia do relógio dos testes do caixa
BRASILIA = timezone(timedelta(hours=-3))


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteRelatorioDiario(BaseNuvem):
    def setUp(self):
        super().setUp()
        parar = mock.patch.object(rel, "disparar_em_segundo_plano", return_value=False)
        parar.start()
        self.addCleanup(parar.stop)
        with nuvem.SessionLocal() as db:
            db.query(rel.RelatorioDiario).delete()
            db.commit()
        rel._envios_manuais.clear()
        self.enviados = []

    def enviar(self, para, assunto, corpo):
        self.enviados.append((para, assunto, corpo))

    def ligar(self, emails="dono@exemplo.com", ativo=True, ultimo_dia=None):
        with nuvem.SessionLocal() as db:
            db.add(rel.RelatorioDiario(chave_loja="ADEGA-1", emails=emails, ativo=ativo, ultimo_dia=ultimo_dia,
                                       ultimo_status="", atualizado_em=""))
            db.commit()

    # ---- horário
    def test_so_depois_das_oito_e_sempre_o_dia_anterior(self):
        self.assertIsNone(rel.dia_do_relatorio(datetime(2026, 10, 4, 7, 59, tzinfo=BRASILIA)))
        self.assertEqual(rel.dia_do_relatorio(datetime(2026, 10, 4, 8, 0, tzinfo=BRASILIA)), DIA)
        self.assertEqual(rel.dia_do_relatorio(datetime(2026, 10, 4, 23, 30, tzinfo=BRASILIA)), DIA)

    # ---- conteúdo
    def test_relatorio_explica_vendas_pagamentos_produtos_e_caixa(self):
        self.venda_fechada((self.skol, 2))
        self.venda_fechada((self.skol, 1), forma="Pix")
        self.subir()
        with nuvem.SessionLocal() as db:
            assunto, corpo = rel.montar(db, "ADEGA-1", DIA)
        self.assertIn("Adega 1", assunto)
        self.assertIn("03/10", assunto)
        for trecho in ("1) RESUMO DO DIA", "em 2 venda(s)", "Ticket médio", "2) COMO FOI PAGO", "Dinheiro", "Pix",
                       "3) PRODUTOS QUE MAIS VENDERAM", "4) CAIXA", "5) ESTOQUE", "PONTOS DE ATENÇÃO",
                       "sábado, 03/10/2026"):
            self.assertIn(trecho, corpo)
        nome = self.banco.um("SELECT nome FROM produtos WHERE id = ?", (self.skol,))["nome"]
        self.assertIn(nome, corpo)
        self.assertNotIn("GAROTAS", corpo)          # adega sem garotas: a seção não aparece

    def test_dia_sem_vendas_avisa_para_conferir_o_caixa(self):
        with nuvem.SessionLocal() as db:
            assunto, corpo = rel.montar(db, "ADEGA-1", DIA)
        self.assertIn("R$ 0,00", assunto)
        self.assertIn("nenhuma venda chegou", corpo)

    def test_fechamento_com_falta_entra_nos_pontos_de_atencao(self):
        self.venda_fechada((self.skol, 1))
        esperado = self.turnos.resumo(self.turno)["esperado"]
        self.turnos.fechar(self.turno, self.adm, esperado - 500, justificativa="conferir")
        self.subir()
        with nuvem.SessionLocal() as db:
            _, corpo = rel.montar(db, "ADEGA-1", DIA)
        self.assertIn("FALTOU R$ 5,00", corpo)
        self.assertIn("faltou dinheiro no fechamento de caixa", corpo)

    # ---- envio automático
    def test_envia_uma_vez_por_dia_para_cada_email(self):
        self.ligar("dono@exemplo.com,gerente@exemplo.com")
        with nuvem.SessionLocal() as db:
            self.assertEqual(rel.enviar_pendentes(db, DIA, enviar=self.enviar), {"enviados": 1, "falhas": 0})
            self.assertEqual(rel.enviar_pendentes(db, DIA, enviar=self.enviar), {"enviados": 0, "falhas": 0})
            linha = db.get(rel.RelatorioDiario, "ADEGA-1")
            self.assertEqual(linha.ultimo_dia, DIA)
            self.assertIn("2 e-mail(s)", linha.ultimo_status)
        self.assertEqual([e[0] for e in self.enviados], ["dono@exemplo.com", "gerente@exemplo.com"])

    def test_desligado_nao_envia_e_falha_volta_a_ficar_pendente(self):
        self.ligar(ativo=False)
        with nuvem.SessionLocal() as db:
            self.assertEqual(rel.enviar_pendentes(db, DIA, enviar=self.enviar)["enviados"], 0)
            db.query(rel.RelatorioDiario).update({"ativo": True, "ultimo_dia": "2026-10-02"})
            db.commit()

            def quebrar(*_):
                raise RuntimeError("servidor de e-mail fora")
            self.assertEqual(rel.enviar_pendentes(db, DIA, enviar=quebrar), {"enviados": 0, "falhas": 1})
            linha = db.get(rel.RelatorioDiario, "ADEGA-1")
            db.refresh(linha)
            self.assertEqual(linha.ultimo_dia, "2026-10-02")
            self.assertIn("Falhou", linha.ultimo_status)
            self.assertEqual(rel.enviar_pendentes(db, DIA, enviar=self.enviar)["enviados"], 1)

    def test_disparo_em_segundo_plano_respeita_o_horario(self):
        import time
        self.addCleanup(lambda: setattr(rel, "_feito", None))
        with mock.patch.object(rel, "enviar_pendentes", return_value={"enviados": 0, "falhas": 0}) as envio:
            rel._feito, rel._proxima_tentativa = None, 0.0
            self.assertFalse(DISPARAR(datetime(2026, 10, 4, 7, 0, tzinfo=BRASILIA)))
            self.assertTrue(DISPARAR(datetime(2026, 10, 4, 8, 5, tzinfo=BRASILIA)))
            for _ in range(100):
                if rel._feito == DIA:
                    break
                time.sleep(0.05)
            self.assertEqual(rel._feito, DIA)
            self.assertFalse(DISPARAR(datetime(2026, 10, 4, 9, 0, tzinfo=BRASILIA)))
            envio.assert_called_once()

    # ---- painel
    def test_painel_salva_valida_e_envia_agora_com_limite(self):
        sessao = self.entrar()
        r = self.http.get("/v1/painel/relatorio-diario", headers=sessao)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["ativo"])
        for corpo in ({"emails": "nao-e-email", "ativo": True}, {"emails": "", "ativo": True},
                      {"emails": "a@x.com, b@x.com, c@x.com, d@x.com", "ativo": True}):
            self.assertEqual(self.http.post("/v1/painel/relatorio-diario", json=corpo, headers=sessao).status_code, 422)
        self.assertEqual(self.http.post("/v1/painel/relatorio-diario/enviar-agora", headers=sessao).status_code, 422)
        r = self.http.post("/v1/painel/relatorio-diario", json={"emails": "Dono@Exemplo.com; dono@exemplo.com",
                                                                "ativo": True}, headers=sessao)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["emails"], ["dono@exemplo.com"])
        self.assertTrue(r.json()["ativo"])
        with mock.patch("backend.cobranca_mercadopago.enviar_email", side_effect=self.enviar):
            for _ in range(3):
                r = self.http.post("/v1/painel/relatorio-diario/enviar-agora", headers=sessao)
                self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(self.http.post("/v1/painel/relatorio-diario/enviar-agora", headers=sessao).status_code, 429)
        self.assertEqual(len(self.enviados), 3)
        self.assertEqual(self.http.get("/v1/painel/relatorio-diario").status_code, 401)

    def test_tela_e_agendamento_existem(self):
        raiz = Path(__file__).resolve().parents[1]
        html = (raiz / "backend/painel_web/index.html").read_text(encoding="utf-8")
        js = (raiz / "backend/painel_web/app.js").read_text(encoding="utf-8")
        for ident in ("form-relatorio-diario", "relatorio-emails", "relatorio-ativo", "relatorio-agora"):
            self.assertIn(f'id="{ident}"', html)
        self.assertIn("/relatorio-diario/enviar-agora", js)
        fluxo = (raiz / ".github/workflows/relatorio-diario.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "5 11 * * *"', fluxo)       # 08:05 em Brasília


if __name__ == "__main__":
    unittest.main()
