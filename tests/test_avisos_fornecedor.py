"""Resumo diário de licenças vencendo, para o fornecedor."""
from __future__ import annotations

import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4

from tests.test_nuvem import TestClient, nuvem, preparar_lojas

if TestClient is not None:
    from backend import avisos_fornecedor as avisos, ponte
    from tests.test_central_fornecedor import TesteCentralFornecedor
else:                                                  # pragma: no cover - sem dependências da nuvem
    TesteCentralFornecedor = unittest.TestCase

HOJE = date(2026, 11, 6)


@unittest.skipIf(TestClient is None, "Dependências da nuvem ausentes")
class TesteVencimentos(unittest.TestCase):
    def setUp(self):
        preparar_lojas()
        with nuvem.SessionLocal() as db:
            for modelo in (avisos.AvisoFornecedor, ponte.PonteLicenca, ponte.PonteLoja):
                db.query(modelo).delete()
            db.commit()
        avisos._ultimo_dia_verificado = None
        self.enviados = []

    def validade(self, chave, dias, ativa=True):
        with nuvem.SessionLocal() as db:
            db.query(nuvem.Loja).filter_by(chave_loja=chave).update(
                {"licenca_ate": (HOJE + timedelta(days=dias)).isoformat(), "ativa": ativa})
            db.commit()

    def enviar(self, para, assunto, corpo):
        self.enviados.append((para, assunto, corpo))

    def test_so_ativas_dentro_da_janela_e_ponte_pelo_codigo_publicado(self):
        self.validade("LOJA-1", 3)
        self.validade("LOJA-2", 40)
        with nuvem.SessionLocal() as db:
            self.assertEqual([(l["chave"], l["dias"]) for l in avisos.vencimentos(db, HOJE)], [("LOJA-1", 3)])
            db.add(ponte.PonteLoja(chave_loja="LOJA-2", modo_ponte=True, ativado_em="2026-11-01 10:00:00"))
            db.add(ponte.PonteLicenca(id=str(uuid4()), chave_loja="LOJA-2", codigo="x" * 20, emitida_em="2026-10-01",
                                     expira_em=(HOJE - timedelta(days=2)).isoformat(), publicada_em="2026-10-01 10:00:00"))
            db.commit()
            self.assertEqual([(l["chave"], l["dias"]) for l in avisos.vencimentos(db, HOJE)],
                             [("LOJA-2", -2), ("LOJA-1", 3)])
        self.validade("LOJA-1", 3, ativa=False)
        with nuvem.SessionLocal() as db:
            self.assertEqual([l["chave"] for l in avisos.vencimentos(db, HOJE)], ["LOJA-2"])

    def test_um_envio_por_dia_e_forcar_reenvia(self):
        self.validade("LOJA-1", 0)
        with patch.dict(os.environ, {"PDV_AVISOS_EMAIL": "eu@exemplo.com"}), nuvem.SessionLocal() as db:
            self.assertTrue(avisos.enviar_se_preciso(db, HOJE, enviar=self.enviar)["enviado"])
            self.assertFalse(avisos.enviar_se_preciso(db, HOJE, enviar=self.enviar)["enviado"])
            self.assertTrue(avisos.enviar_se_preciso(db, HOJE, forcar=True, enviar=self.enviar)["enviado"])
            self.assertTrue(avisos.enviar_se_preciso(db, HOJE + timedelta(days=1), enviar=self.enviar)["enviado"])
        self.assertEqual(len(self.enviados), 3)
        para, assunto, corpo = self.enviados[0]
        self.assertEqual(para, "eu@exemplo.com")
        self.assertIn("1 licença(s)", assunto)
        self.assertIn("LOJA-1", corpo)
        self.assertIn("vence HOJE", corpo)

    def test_sem_destino_sem_lojas_ou_erro_de_email_nao_marca_o_dia(self):
        with nuvem.SessionLocal() as db, patch.dict(os.environ, {"PDV_AVISOS_EMAIL": "", "EMAIL_FROM": ""}):
            self.assertEqual(avisos.enviar_se_preciso(db, HOJE, enviar=self.enviar)["motivo"], "Nenhuma loja vencendo.")
            self.validade("LOJA-1", 2)
            self.assertIn("PDV_AVISOS_EMAIL", avisos.enviar_se_preciso(db, HOJE, enviar=self.enviar)["motivo"])

            def falha(*_):
                raise RuntimeError("Brevo fora do ar")
            with patch.dict(os.environ, {"EMAIL_FROM": "loja@exemplo.com"}):
                r = avisos.enviar_se_preciso(db, HOJE, enviar=falha)
                self.assertFalse(r["enviado"])
                self.assertIsNone(db.get(avisos.AvisoFornecedor, HOJE.isoformat()))
                self.assertTrue(avisos.enviar_se_preciso(db, HOJE, enviar=self.enviar)["enviado"])
        self.assertEqual(self.enviados[0][0], "loja@exemplo.com")

    def test_gatilho_do_caixa_nao_faz_nada_sem_destino(self):
        with patch.dict(os.environ, {"PDV_AVISOS_EMAIL": "", "EMAIL_FROM": ""}), \
                patch("threading.Thread") as thread:
            avisos.disparar_em_segundo_plano()
        thread.assert_not_called()


@unittest.skipIf(TestClient is None, "Dependências da nuvem ausentes")
class TesteVencimentosNaCentral(TesteCentralFornecedor):
    def test_lista_mostra_os_vencimentos_e_botao_envia(self):
        with nuvem.SessionLocal() as db:
            db.query(avisos.AvisoFornecedor).delete()
            db.query(nuvem.Loja).filter_by(chave_loja="LOJA-1").update(
                {"licenca_ate": (date.today() + timedelta(days=2)).isoformat()})
            db.commit()
        with patch.dict(os.environ, {"PDV_AVISOS_EMAIL": ""}), patch("threading.Thread"):
            r = self.http.get("/v1/fornecedor/lojas").json()
        self.assertEqual([v["chave"] for v in r["vencimentos"]], ["LOJA-1"])
        enviados = []
        with patch.dict(os.environ, {"PDV_AVISOS_EMAIL": "eu@exemplo.com"}), \
                patch("backend.cobranca_mercadopago.enviar_email", side_effect=lambda *a: enviados.append(a)):
            r = self.post("/avisos/enviar", {})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["enviado"])
        self.assertEqual(enviados[0][0], "eu@exemplo.com")
        self.assertEqual(self.http.get("/v1/fornecedor/auditoria").json()["eventos"][0]["acao"],
                         "enviar_resumo_vencimentos")


if TestClient is not None:
    for _nome in [n for n in dir(TesteCentralFornecedor) if n.startswith("test_")]:
        if _nome not in TesteVencimentosNaCentral.__dict__:
            setattr(TesteVencimentosNaCentral, _nome, None)
