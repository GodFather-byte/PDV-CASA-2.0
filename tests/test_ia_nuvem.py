"""IA nos caixas: liga/desliga e cota pela central, chave só na nuvem, foto e nomes com a API simulada."""
import base64
import os
import unittest
from unittest.mock import patch

from tests.test_nuvem import TestClient, nuvem, preparar_lojas, cabecalho, TOKENS

try:
    from backend import ia, central_fornecedor as central
except (ImportError, RuntimeError):
    ia = None

FOTO = base64.b64encode(b"\xff\xd8\xff" + b"0" * 200).decode()


def resposta_foto(conteudo, ferramenta, sistema, max_tokens=4096):
    return ({"tipo_imagem": "lista_precos", "produtos": [
        {"nome": "Cerveja Heineken Long Neck 330ml", "preco_cent": 1200.4, "codigo_barras": "7891234567895",
         "quantidade": 12, "unidade": "un", "grupo": "Cerveja"},
        {"nome": "", "preco_cent": 100},                                     # sem nome: descartado
        {"nome": "Gelo 5kg", "preco_cent": "abc", "codigo_barras": "123"}]},  # preço e barras inválidos zerados
        ("claude-haiku-5-5", 1500, 300))


@unittest.skipIf(TestClient is None or ia is None, "Dependências da nuvem ausentes")
class TesteIaNuvem(unittest.TestCase):
    def setUp(self):
        preparar_lojas()
        with nuvem.SessionLocal() as db:
            for modelo in (ia.IaLoja, ia.IaUso, central.SessaoFornecedor, central.AuditoriaFornecedor):
                db.query(modelo).delete()
            db.commit()
        with central._trava:
            central._tentativas.clear()
        chave = patch.dict(os.environ, {"ANTHROPIC_API_KEY": "chave-de-teste"})
        chave.start()
        self.addCleanup(chave.stop)
        self.http = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(self.http.close)
        self.loja = sorted(TOKENS)[0]

    def central(self):
        r = self.http.post("/v1/fornecedor/login", json={"credencial": "token-de-teste"},
                           headers={"X-Central-Login": "1"})
        self.assertEqual(r.status_code, 200, r.text)
        return {"X-Central-CSRF": r.json()["csrf"]}

    def ligar(self, **dados):
        csrf = self.central()
        r = self.http.post(f"/v1/fornecedor/lojas/{self.loja}/ia", json={"ativa": True, **dados}, headers=csrf)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def foto(self):
        return self.http.post("/v1/ia/produtos/foto", json={"imagem_b64": FOTO, "tipo": "image/jpeg"},
                              headers=cabecalho(self.loja))

    def test_desligada_por_padrao(self):
        sit = self.http.get("/v1/ia/situacao", headers=cabecalho(self.loja)).json()
        self.assertFalse(sit["ativa"])
        self.assertNotIn("custo_mes_usd", sit)
        with patch.object(ia, "chamar_claude") as chamar:
            self.assertEqual(self.foto().status_code, 403)
            chamar.assert_not_called()

    def test_ligada_le_foto_limpa_e_conta_custo(self):
        self.ligar()
        with patch.object(ia, "chamar_claude", side_effect=resposta_foto):
            r = self.foto()
        self.assertEqual(r.status_code, 200, r.text)
        produtos = r.json()["produtos"]
        self.assertEqual([p["nome"] for p in produtos], ["Cerveja Heineken Long Neck 330ml", "Gelo 5kg"])
        self.assertEqual((produtos[0]["preco_cent"], produtos[0]["unidade"]), (1200, "UN"))
        self.assertEqual((produtos[1]["preco_cent"], produtos[1]["codigo_barras"]), (0, ""))
        uso = self.http.get(f"/v1/fornecedor/lojas/{self.loja}/ia", headers=self.central()).json()
        self.assertEqual(uso["usos_mes"], 1)
        self.assertAlmostEqual(uso["custo_mes_usd"], (1500 * 100 + 300 * 500) / 1e9)

    def test_cota_acaba(self):
        self.ligar(cota_usos=1)
        with patch.object(ia, "chamar_claude", side_effect=resposta_foto):
            self.assertEqual(self.foto().status_code, 200)
            self.assertEqual(self.foto().status_code, 429)

    def test_desligar_pela_central_bloqueia(self):
        self.ligar()
        r = self.http.post(f"/v1/fornecedor/lojas/{self.loja}/ia", json={"ativa": False}, headers=self.central())
        self.assertFalse(r.json()["ativa"])
        with patch.object(ia, "chamar_claude", side_effect=resposta_foto):
            self.assertEqual(self.foto().status_code, 403)
        with nuvem.SessionLocal() as db:
            self.assertTrue(db.query(central.AuditoriaFornecedor).filter_by(acao="ia_loja").count() >= 2)

    def test_sem_chave_na_nuvem(self):
        self.ligar()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertEqual(self.foto().status_code, 503)

    def test_nomes_na_mesma_ordem(self):
        self.ligar()
        def resposta(conteudo, ferramenta, sistema, max_tokens=4096):
            self.assertIn("0. CERV HEINEKEN LN 330ML", conteudo[0]["text"])
            return ({"itens": [{"indice": 1, "nome": "Vodka Smirnoff 998ml", "grupo": "Destilado"},
                               {"indice": 0, "nome": "Cerveja Heineken Long Neck 330ml", "grupo": "Cerveja"},
                               {"indice": 9, "nome": "fora da lista"}]}, ("claude-haiku-5-5", 100, 50))
        with patch.object(ia, "chamar_claude", side_effect=resposta):
            r = self.http.post("/v1/ia/produtos/nomes", json={"itens": [
                {"nome": "CERV HEINEKEN LN 330ML"}, {"nome": "VODKA SMIRNOFF 998"}, {"nome": "XPTO"}]},
                headers=cabecalho(self.loja))
        itens = r.json()["itens"]
        self.assertEqual([i and i["nome"] for i in itens],
                         ["Cerveja Heineken Long Neck 330ml", "Vodka Smirnoff 998ml", None])

    def test_foto_invalida_nao_gasta(self):
        self.ligar()
        r = self.http.post("/v1/ia/produtos/foto", json={"imagem_b64": "@@", "tipo": "image/jpeg"},
                           headers=cabecalho(self.loja))
        self.assertEqual(r.status_code, 422)
        r = self.http.post("/v1/ia/produtos/foto", json={"imagem_b64": FOTO, "tipo": "application/pdf"},
                           headers=cabecalho(self.loja))
        self.assertEqual(r.status_code, 422)

    def test_chamada_real_monta_pedido_sem_vazar_chave_na_resposta(self):
        capturado = {}

        class Resp:
            def __init__(self, corpo):
                self.corpo = corpo
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                return self.corpo

        def abrir(pedido, timeout=None):
            capturado["headers"] = dict(pedido.header_items())
            capturado["corpo"] = pedido.data
            import json
            return Resp(json.dumps({"content": [{"type": "tool_use", "name": "nomes", "input": {"itens": []}}],
                                    "usage": {"input_tokens": 10, "output_tokens": 5}}).encode())
        dados, uso = ia.chamar_claude([{"type": "text", "text": "x"}], ia.FERRAMENTA_NOMES, "s", abrir=abrir)
        self.assertEqual((dados, uso), ({"itens": []}, ("claude-haiku-5-5", 10, 5)))
        self.assertEqual(capturado["headers"]["X-api-key"], "chave-de-teste")
        self.assertIn(b'"tool_choice"', capturado["corpo"])
