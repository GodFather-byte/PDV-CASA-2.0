"""Insta-BDelivery pela central: o fornecedor cadastra, o caixa recebe sozinho e a vitrine pergunta se a IA está liberada."""
import hashlib
import unittest

from src.sync import insta_bdelivery
from tests.test_painel_dono import BaseNuvem, TestClient, nuvem

try:
    from backend import central_fornecedor as central, ia, insta
except (ImportError, RuntimeError):
    insta = None

TOKEN = "ibd_" + "ab" * 32
URL = "https://delivery.exemplo/api/pdv"
H = hashlib.sha256(TOKEN.encode()).hexdigest()


@unittest.skipIf(TestClient is None or insta is None, "fastapi/httpx não instalados")
class TesteInstaCentral(BaseNuvem):
    def setUp(self):
        super().setUp()
        with nuvem.SessionLocal() as db:
            for modelo in (insta.InstaLoja, ia.IaLoja, central.SessaoFornecedor):
                db.query(modelo).delete()
            db.commit()
        with central._trava:
            central._tentativas.clear()
        self.central = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(self.central.close)
        r = self.central.post("/v1/fornecedor/login", json={"credencial": "token-de-teste"},
                              headers={"X-Central-Login": "1"})
        self.csrf = {"X-Central-CSRF": r.json()["csrf"]}

    def cadastrar(self, **dados):
        return self.central.post("/v1/fornecedor/lojas/ADEGA-1/insta", json={"url": URL, "token": TOKEN, **dados},
                                 headers=self.csrf)

    def test_central_entrega_ao_caixa_e_esquece_a_chave(self):
        r = self.cadastrar()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["aguardando_caixa"])
        self.assertNotIn("token", r.json())
        self.venda_fechada((self.skol, 1))
        self.subir()                                     # recebe a configuração
        self.assertEqual(insta_bdelivery.acesso(self.banco), (URL, TOKEN))
        self.venda_fechada((self.skol, 1))
        self.subir()                                     # confirma pelo hash: a chave em texto sai da nuvem
        with nuvem.SessionLocal() as db:
            linha = db.query(insta.InstaLoja).filter_by(chave_loja="ADEGA-1").one()
            self.assertIsNone(linha.token_pendente)
            self.assertIsNotNone(linha.entregue_em)
        sit = self.central.get("/v1/fornecedor/lojas/ADEGA-1/insta").json()
        self.assertFalse(sit["aguardando_caixa"])

    def test_chave_ou_endereco_invalidos(self):
        self.assertEqual(self.cadastrar(token="qualquer").status_code, 422)
        self.assertEqual(self.cadastrar(url="http://sem-https.exemplo").status_code, 422)

    def test_vitrine_pergunta_pela_ia(self):
        self.assertEqual(self.http.get("/v1/parceiro/insta/ia", params={"h": H}).json(), {"liberada": False})
        self.cadastrar()
        self.assertEqual(self.http.get("/v1/parceiro/insta/ia", params={"h": H}).json(), {"liberada": False})
        self.central.post("/v1/fornecedor/lojas/ADEGA-1/ia", json={"ativa": True}, headers=self.csrf)
        self.assertEqual(self.http.get("/v1/parceiro/insta/ia", params={"h": H}).json(), {"liberada": True})
        self.assertEqual(self.http.get("/v1/parceiro/insta/ia", params={"h": "x"}).status_code, 422)

    def test_remover(self):
        self.cadastrar()
        r = self.central.post("/v1/fornecedor/lojas/ADEGA-1/insta", json={"remover": True}, headers=self.csrf)
        self.assertFalse(r.json()["configurado"])
        self.assertEqual(self.http.get("/v1/parceiro/insta/ia", params={"h": H}).json(), {"liberada": False})

    def test_caixa_ignora_resposta_estranha(self):
        self.assertFalse(insta_bdelivery.anotar_resposta(self.banco, {"insta": {"url": "http://x", "token": TOKEN}}))
        self.assertFalse(insta_bdelivery.anotar_resposta(self.banco, {"insta": "x"}))
        self.assertEqual(insta_bdelivery.acesso(self.banco), ("", ""))
