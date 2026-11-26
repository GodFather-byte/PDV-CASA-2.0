"""Envio ao contador: config no painel, e-mail do mês com link de 7 dias, ZIP com XMLs e notas.csv, envio automático
uma vez por mês a partir do dia 1º às 08:00."""
from __future__ import annotations

import gzip
import io
import re
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests.test_painel_dono import BaseNuvem, TestClient, nuvem

if TestClient is not None:
    from backend import contador, nfce_xmls, relatorio_diario

MES = "2026-10"
BRASILIA = timezone(timedelta(hours=-3))
NFE = (b"<nfeProc><NFe><infNFe><ide><nNF>123</nNF><dhEmi>2026-10-03T21:10:00-03:00</dhEmi></ide>"
       b"<total><ICMSTot><vNF>45.90</vNF></ICMSTot></total></infNFe></NFe></nfeProc>")


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteContador(BaseNuvem):
    def setUp(self):
        super().setUp()
        for alvo in (mock.patch.object(relatorio_diario, "disparar_em_segundo_plano", return_value=False),
                     mock.patch.object(contador, "disparar_em_segundo_plano", return_value=False)):
            alvo.start()
            self.addCleanup(alvo.stop)
        with nuvem.SessionLocal() as db:
            for modelo in (contador.ContadorEnvio, contador.ContadorLink, nfce_xmls.NfceXml):
                db.query(modelo).delete()
            db.add(nfce_xmls.NfceXml(chave_loja="ADEGA-1", nome="35261000000000000000650010000001231000001234-nfeProc.xml",
                                     tipo="nfe", chave="3" * 44, mes=MES, conteudo=gzip.compress(NFE), tamanho=len(NFE),
                                     recebido_em="2026-10-03 21:11:00"))
            db.add(nfce_xmls.NfceXml(chave_loja="ADEGA-1", nome="cancelamento-0001.xml", tipo="cancelamento",
                                     chave="4" * 44, mes=MES, conteudo=gzip.compress(b"<evento/>"), tamanho=9,
                                     recebido_em="2026-10-03 22:00:00"))
            db.commit()
        contador._envios_manuais.clear()
        self.emails = []

    def enviar(self, para, assunto, corpo):
        self.emails.append((para, assunto, corpo))

    def test_mes_do_envio(self):
        self.assertIsNone(contador.mes_do_envio(datetime(2026, 11, 1, 7, 59, tzinfo=BRASILIA)))
        self.assertEqual(contador.mes_do_envio(datetime(2026, 11, 1, 8, 0, tzinfo=BRASILIA)), "2026-10")
        self.assertEqual(contador.mes_do_envio(datetime(2026, 1, 15, 10, 0, tzinfo=BRASILIA)), "2025-12")

    def test_email_tem_resumo_e_o_link_baixa_o_zip(self):
        self.venda_fechada((self.skol, 2))
        self.subir()
        with nuvem.SessionLocal() as db:
            contador.enviar_mes(db, "ADEGA-1", MES, "contador@exemplo.com", self.enviar)
        para, assunto, corpo = self.emails[-1]
        self.assertEqual(para, "contador@exemplo.com")
        self.assertIn("outubro de 2026", assunto)
        for trecho in ("Autorizadas: 1", "Canceladas: 1", "Faturamento:", "notas.csv"):
            self.assertIn(trecho, corpo)
        token = re.search(r"/v1/contador/([A-Za-z0-9_\-]+)", corpo).group(1)
        r = self.http.get(f"/v1/contador/{token}")
        self.assertEqual(r.status_code, 200)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        nomes = z.namelist()
        self.assertIn("autorizadas/35261000000000000000650010000001231000001234-nfeProc.xml", nomes)
        self.assertIn("canceladas/cancelamento-0001.xml", nomes)
        planilha = z.read("notas.csv").decode("utf-8-sig")
        self.assertIn("autorizada;123;2026-10-03 21:10:00;45,90;", planilha)
        self.assertEqual(self.http.get("/v1/contador/nao-existe").status_code, 410)
        with nuvem.SessionLocal() as db:                         # link vencido
            db.query(contador.ContadorLink).update({"expira_em": "2000-01-01 00:00:00"})
            db.commit()
        self.assertEqual(self.http.get(f"/v1/contador/{token}").status_code, 410)

    def test_envio_automatico_uma_vez_por_mes(self):
        with nuvem.SessionLocal() as db:
            db.add(contador.ContadorEnvio(chave_loja="ADEGA-1", email="contador@exemplo.com", ativo=True,
                                          ultimo_mes="2026-09", ultimo_status="", atualizado_em=""))
            db.commit()
            self.assertEqual(contador.enviar_pendentes(db, MES, self.enviar), {"enviados": 1, "falhas": 0})
            self.assertEqual(contador.enviar_pendentes(db, MES, self.enviar), {"enviados": 0, "falhas": 0})

            def quebrar(*_):
                raise RuntimeError("sem e-mail")
            self.assertEqual(contador.enviar_pendentes(db, "2026-11", quebrar), {"enviados": 0, "falhas": 1})
            linha = db.get(contador.ContadorEnvio, "ADEGA-1")
            db.refresh(linha)
            self.assertEqual(linha.ultimo_mes, MES)               # a falha devolve a reserva
        self.assertEqual(len(self.emails), 1)

    def test_painel_configura_e_envia_agora_com_limite(self):
        sessao = self.entrar()
        self.assertEqual(self.http.post("/v1/painel/contador", json={"email": "", "ativo": True}, headers=sessao).status_code, 422)
        self.assertEqual(self.http.post("/v1/painel/contador", json={"email": "ruim", "ativo": False}, headers=sessao).status_code, 422)
        r = self.http.post("/v1/painel/contador", json={"email": "Contador@Exemplo.com", "ativo": True}, headers=sessao)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["email"], "contador@exemplo.com")
        with mock.patch("backend.cobranca_mercadopago.enviar_email", side_effect=self.enviar):
            for _ in range(3):
                self.assertEqual(self.http.post("/v1/painel/contador/enviar", json={"mes": MES}, headers=sessao).status_code, 200)
            self.assertEqual(self.http.post("/v1/painel/contador/enviar", json={"mes": MES}, headers=sessao).status_code, 429)
        self.assertEqual(self.http.post("/v1/painel/contador/enviar", json={"mes": "2026-13"}, headers=sessao).status_code, 422)
        self.assertEqual(self.http.get("/v1/painel/contador").status_code, 401)


if __name__ == "__main__":
    unittest.main()
