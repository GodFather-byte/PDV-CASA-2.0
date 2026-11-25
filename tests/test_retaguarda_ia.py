"""IA na retaguarda: a mesma cota da loja lê a foto, arruma os nomes e manda os produtos conferidos ao caixa."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_ia_nuvem import FOTO, TOKENS, TestClient, ia, nuvem, preparar_lojas, resposta_foto

try:
    from backend import central_fornecedor as central, retaguarda
except (ImportError, RuntimeError):
    retaguarda = None

RAIZ = Path(__file__).resolve().parents[1]


@unittest.skipIf(TestClient is None or ia is None or retaguarda is None, "Dependências da nuvem ausentes")
class TesteRetaguardaIa(unittest.TestCase):
    def setUp(self):
        preparar_lojas()
        with nuvem.SessionLocal() as db:
            for modelo in (ia.IaLoja, ia.IaUso, central.SessaoFornecedor, central.AuditoriaFornecedor,
                           retaguarda.RetaguardaComando):
                db.query(modelo).delete()
            db.commit()
        with central._trava:
            central._tentativas.clear()
        for alvo in (patch.dict(os.environ, {"ANTHROPIC_API_KEY": "chave-de-teste"}),
                     patch.object(retaguarda, "secao", return_value=({"entidades": []}, "2026-11-25 10:00:00"))):
            alvo.start()
            self.addCleanup(alvo.stop)
        self.http = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(self.http.close)
        self.loja = sorted(TOKENS)[0]
        r = self.http.post("/v1/fornecedor/login", json={"credencial": "token-de-teste"}, headers={"X-Central-Login": "1"})
        self.csrf = {"X-Central-CSRF": r.json()["csrf"]}
        self.base = f"/v1/fornecedor/lojas/{self.loja}/retaguarda"

    def ligar(self):
        r = self.http.post(f"/v1/fornecedor/lojas/{self.loja}/ia", json={"ativa": True}, headers=self.csrf)
        self.assertEqual(r.status_code, 200, r.text)

    def test_desligada_nao_chama_a_ia(self):
        self.assertFalse(self.http.get(self.base + "/ia", headers=self.csrf).json()["ativa"])
        with patch.object(ia, "chamar_claude") as chamar:
            r = self.http.post(self.base + "/ia/foto", json={"imagem_b64": FOTO, "tipo": "image/jpeg"}, headers=self.csrf)
        self.assertEqual(r.status_code, 403)
        chamar.assert_not_called()

    def test_foto_vira_linhas_da_importacao_e_conta_na_cota(self):
        self.ligar()
        with patch.object(ia, "chamar_claude", side_effect=resposta_foto):
            r = self.http.post(self.base + "/ia/foto", json={"imagem_b64": FOTO, "tipo": "image/jpeg"}, headers=self.csrf)
        self.assertEqual(r.status_code, 200, r.text)
        linhas = r.json()["linhas"]
        self.assertEqual(linhas[0]["nome"], "Cerveja Heineken Long Neck 330ml")
        self.assertEqual((linhas[0]["preco"], linhas[0]["quantidade"], linhas[0]["codigo_barras"]),
                         ("12,00", "12", "7891234567895"))
        self.assertEqual(linhas[1]["preco"], "")                   # sem preço: o dono completa na tela
        self.assertEqual(self.http.get(self.base + "/ia", headers=self.csrf).json()["usos_mes"], 1)

    def test_nomes_e_envio_viram_comando_de_importacao(self):
        self.ligar()
        resposta = ({"itens": [{"indice": 0, "nome": "Cerveja Skol Lata 350ml", "grupo": "Cerveja"}]},
                    ("claude-haiku-5-5", 100, 20))
        with patch.object(ia, "chamar_claude", return_value=resposta):
            r = self.http.post(self.base + "/ia/nomes", json={"itens": [{"nome": "CERV SKOL LT 350"}]}, headers=self.csrf)
        self.assertEqual(r.json()["itens"][0]["nome"], "Cerveja Skol Lata 350ml")
        r = self.http.post(self.base + "/ia/enviar", headers=self.csrf, json={
            "modo_quantidade": "somar", "linhas": [{"nome": "Cerveja Skol Lata 350ml", "preco": "5,00", "quantidade": "12"},
                                                   {"nome": "  ", "preco": "1,00"}]})
        self.assertEqual(r.status_code, 200, r.text)
        with nuvem.SessionLocal() as db:
            comando = db.query(retaguarda.RetaguardaComando).one()
        dados = json.loads(comando.dados)
        self.assertEqual((comando.tipo, dados["modo_quantidade"], len(dados["linhas"])), ("produtos.importar", "somar", 1))
        self.assertIn("Cadastro com IA", comando.resumo)

    def test_dono_tem_as_mesmas_rotas_e_a_tela_existe(self):
        fonte = (RAIZ / "backend" / "retaguarda.py").read_text(encoding="utf-8")
        self.assertIn('_rotas_de_leitura_e_escrita(router, "/v1/painel/retaguarda", loja_do_dono, "dono")', fonte)
        for fim in ('"/ia"', '"/ia/foto"', '"/ia/nomes"', '"/ia/enviar"'):
            self.assertIn("prefixo + " + fim, fonte)        # dentro das rotas que o dono e a central dividem
        tela = (RAIZ / "backend" / "retaguarda_web" / "app.js").read_text(encoding="utf-8")
        for trecho in ('botao("ia", "Cadastro com IA")', "async function telaIa()", "/ia/enviar", "fotoReduzida"):
            self.assertIn(trecho, tela)


if __name__ == "__main__":
    unittest.main()
