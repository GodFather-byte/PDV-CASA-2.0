"""Login do dono por e-mail: convite pela central, senha criada pelo dono, código no aparelho novo, esqueci a senha
e acesso à rede inteira. O login antigo (código da loja + senha) continua."""
import re
import unittest
from unittest.mock import patch

from tests.test_nuvem import TestClient, nuvem, preparar_lojas, TOKENS

try:
    from backend import central_fornecedor as central, painel_usuarios as pu, grupos
except (ImportError, RuntimeError):
    pu = None


@unittest.skipIf(TestClient is None or pu is None, "Dependências da nuvem ausentes")
class TesteLoginEmail(unittest.TestCase):
    def setUp(self):
        preparar_lojas()
        with nuvem.SessionLocal() as db:
            for modelo in (pu.PainelUsuario, pu.PainelUsuarioToken, pu.PainelAparelho, central.SessaoFornecedor,
                           central.AuditoriaFornecedor):
                db.query(modelo).delete()
            db.commit()
        with central._trava:
            central._tentativas.clear()
        pu.tentativas_email._falhas.clear()
        self.emails = []
        correio = patch("backend.cobranca_mercadopago.enviar_email", side_effect=lambda *a: self.emails.append(a))
        correio.start()
        self.addCleanup(correio.stop)
        self.central = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(self.central.close)
        r = self.central.post("/v1/fornecedor/login", json={"credencial": "token-de-teste"}, headers={"X-Central-Login": "1"})
        self.csrf = {"X-Central-CSRF": r.json()["csrf"]}
        self.loja = sorted(TOKENS)[0]
        self.dono = TestClient(nuvem.app, base_url="https://testserver")   # o celular do dono (cookies próprios)
        self.addCleanup(self.dono.close)

    def _link(self) -> str:
        return re.search(r"/painel/\?senha=([A-Za-z0-9_\-]+)", self.emails[-1][2]).group(1)

    def _codigo(self) -> str:
        return re.search(r"\b(\d{6})\b", self.emails[-1][1]).group(1)

    def convidar(self, email="Dono@Exemplo.com", rede=False):
        r = self.central.post(f"/v1/fornecedor/lojas/{self.loja}/acessos-email", headers=self.csrf,
                              json={"email": email, "nome": "Seu Zé", "rede": rede})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["convite"])
        return r.json()

    def test_convite_senha_codigo_e_aparelho_lembrado(self):
        self.convidar()
        self.assertEqual(self.emails[-1][0], "dono@exemplo.com")
        token = self._link()
        self.assertEqual(self.dono.get("/v1/painel/senha/link", params={"token": token}).json()["tipo"], "convite")
        self.assertEqual(self.dono.post("/v1/painel/senha/definir", json={"token": token, "senha": "curta"}).status_code, 422)
        r = self.dono.post("/v1/painel/senha/definir", json={"token": token, "senha": "senha-boa-123"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["loja"]["chave"], self.loja)
        self.assertIn("token", r.json())
        self.assertEqual(self.dono.post("/v1/painel/senha/definir", json={"token": token, "senha": "outra-senha-1"}).status_code,
                         422)                                   # o link vale uma vez só
        # O aparelho que criou a senha já é conhecido: entra direto.
        r = self.dono.post("/v1/painel/login-email", json={"email": "dono@exemplo.com", "senha": "senha-boa-123"})
        self.assertEqual(r.json()["loja"]["chave"], self.loja)
        # Aparelho novo: pede código.
        outro = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(outro.close)
        self.assertEqual(outro.post("/v1/painel/login-email", json={"email": "dono@exemplo.com", "senha": "errada-123"}).status_code,
                         401)
        r = outro.post("/v1/painel/login-email", json={"email": "dono@exemplo.com", "senha": "senha-boa-123"})
        self.assertTrue(r.json()["precisa_codigo"])
        self.assertEqual(r.json()["email"], "d***@exemplo.com")
        desafio, codigo = r.json()["desafio"], self._codigo()
        errado = "000000" if codigo != "000000" else "111111"
        r = outro.post("/v1/painel/login-email/codigo", json={"desafio": desafio, "codigo": errado})
        self.assertEqual(r.status_code, 401)
        self.assertIn("Restam 4", r.json()["detail"])
        r = outro.post("/v1/painel/login-email/codigo", json={"desafio": desafio, "codigo": codigo})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["loja"]["chave"], self.loja)
        self.assertIn(pu.COOKIE_APARELHO, outro.cookies)
        self.assertEqual(outro.post("/v1/painel/login-email/codigo", json={"desafio": desafio, "codigo": codigo}).status_code,
                         401)                                   # código usado não vale de novo

    def test_codigo_trava_depois_de_5_erros(self):
        self.convidar()
        self.dono.post("/v1/painel/senha/definir", json={"token": self._link(), "senha": "senha-boa-123"})
        outro = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(outro.close)
        desafio = outro.post("/v1/painel/login-email", json={"email": "dono@exemplo.com", "senha": "senha-boa-123"}).json()["desafio"]
        codigo = self._codigo()
        errado = "000000" if codigo != "000000" else "111111"
        for _ in range(5):
            outro.post("/v1/painel/login-email/codigo", json={"desafio": desafio, "codigo": errado})
        r = outro.post("/v1/painel/login-email/codigo", json={"desafio": desafio, "codigo": codigo})
        self.assertEqual(r.status_code, 401)

    def test_esqueci_a_senha_nao_revela_e_troca_a_senha(self):
        self.convidar()
        self.dono.post("/v1/painel/senha/definir", json={"token": self._link(), "senha": "senha-boa-123"})
        antes = len(self.emails)
        r = self.dono.post("/v1/painel/senha/esqueci", json={"email": "ninguem@exemplo.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.emails), antes)               # e-mail que não existe: nada sai, resposta igual
        r2 = self.dono.post("/v1/painel/senha/esqueci", json={"email": "dono@exemplo.com"})
        self.assertEqual(r.json(), r2.json())
        self.assertEqual(len(self.emails), antes + 1)
        primeiro = self._link()
        self.dono.post("/v1/painel/senha/esqueci", json={"email": "dono@exemplo.com"})
        segundo = self._link()
        self.assertEqual(self.dono.get("/v1/painel/senha/link", params={"token": primeiro}).status_code, 410)
        self.assertEqual(self.dono.post("/v1/painel/senha/definir", json={"token": segundo, "senha": "senha-nova-456"}).status_code,
                         200)
        r = self.dono.post("/v1/painel/login-email", json={"email": "dono@exemplo.com", "senha": "senha-boa-123"})
        self.assertEqual(r.status_code, 401)

    def test_acesso_da_rede_abre_a_sessao_da_rede(self):
        with nuvem.SessionLocal() as db:
            for g in db.query(grupos.Grupo).all():
                db.delete(g)
            db.commit()
            grupo, _ = grupos.criar(db, "Rede Teste", "REDE-TESTE", "senha-da-rede-1")
            grupos.adicionar_loja(db, grupo, self.loja)
            db.commit()
        self.convidar(email="rede@exemplo.com", rede=True)
        r = self.dono.post("/v1/painel/senha/definir", json={"token": self._link(), "senha": "senha-boa-123"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["grupo"]["chave"], "REDE-TESTE")
        self.assertIn(self.loja, [l["chave"] for l in r.json()["grupo"]["lojas"]])
        lista = self.central.get(f"/v1/fornecedor/lojas/{self.loja}/acessos-email").json()
        self.assertEqual(lista["rede"][0]["email"], "rede@exemplo.com")
        self.assertTrue(lista["rede"][0]["senha_criada"])

    def test_central_remove_e_bloqueia_entrada(self):
        self.convidar()
        self.dono.post("/v1/painel/senha/definir", json={"token": self._link(), "senha": "senha-boa-123"})
        uid = self.central.get(f"/v1/fornecedor/lojas/{self.loja}/acessos-email").json()["loja"][0]["id"]
        self.assertEqual(self.central.post(f"/v1/fornecedor/lojas/{self.loja}/acessos-email/{uid}/remover", json={},
                                           headers=self.csrf).status_code, 200)
        r = self.dono.post("/v1/painel/login-email", json={"email": "dono@exemplo.com", "senha": "senha-boa-123"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.central.post(f"/v1/fornecedor/lojas/{self.loja}/acessos-email", headers=self.csrf,
                                           json={"email": "nao-e-email"}).status_code, 422)

    def test_telas_existem(self):
        from pathlib import Path
        raiz = Path(__file__).resolve().parents[1] / "backend"
        painel_js = (raiz / "painel_web" / "app.js").read_text(encoding="utf-8")
        for trecho in ('"/login-email"', '"/login-email/codigo"', '"/senha/esqueci"', '"/senha/definir"', "abrirLinkDeSenha"):
            self.assertIn(trecho, painel_js)
        html = (raiz / "painel_web" / "index.html").read_text(encoding="utf-8")
        for ident in ("form-codigo", "form-esqueci", "form-definir", "botao-esqueci"):
            self.assertIn(f'id="{ident}"', html)
        self.assertIn("acessos-email", (raiz / "central_web" / "app.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
