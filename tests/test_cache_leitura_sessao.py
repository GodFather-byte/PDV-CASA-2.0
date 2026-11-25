"""O cache de leitura do painel separa quem lê: cada sessão (cookie do navegador ou Bearer) tem a sua chave, e sem
sessão nenhuma a leitura do painel não usa o cache (vai ao banco e recebe 401). Antes, com o painel em cookie, todos
dividiam a mesma chave: um dono via o resumo de outra loja por 45 s, e até sem login."""
import unittest

from tests.test_painel_dono import BaseNuvem, TestClient, nuvem, painel

LEITURA = {"X-PDV-Leitura": "1", "X-PDV-Painel": "1"}


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteCachePorSessao(BaseNuvem):
    def setUp(self):
        super().setUp()
        from backend.cache_leitura import limpar
        limpar()
        self.addCleanup(limpar)

    def navegador(self, loja, senha):
        """Um navegador de verdade: entra com a senha e fica só com o cookie (sem Bearer)."""
        db = nuvem.SessionLocal()
        try:
            painel.definir_senha(db, loja, senha)
        finally:
            db.close()
        cliente = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(cliente.close)
        r = cliente.post("/v1/painel/login", json={"loja": loja, "senha": senha}, headers={"X-PDV-Painel": "1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(cliente.cookies.get("willpdv_painel"))
        return cliente

    def loja_do_resumo(self, cliente):
        r = cliente.get("/v1/painel/resumo", headers=LEITURA)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["loja"]["chave"]

    def test_dois_donos_em_seguida_cada_um_ve_a_sua_loja(self):
        um = self.navegador("ADEGA-1", "senha-forte-1")
        dois = self.navegador("ADEGA-2", "senha-forte-2")
        self.assertEqual(self.loja_do_resumo(um), "ADEGA-1")
        self.assertEqual(self.loja_do_resumo(dois), "ADEGA-2")         # dentro dos 45 s do cache
        self.assertEqual(self.loja_do_resumo(um), "ADEGA-1")

    def test_sem_login_nao_recebe_o_que_esta_no_cache(self):
        um = self.navegador("ADEGA-1", "senha-forte-1")
        self.loja_do_resumo(um)
        anonimo = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(anonimo.close)
        for caminho in ("/v1/painel/resumo", "/v1/painel/historico?dias=30", "/v1/painel/produtos?periodo=hoje"):
            self.assertEqual(anonimo.get(caminho, headers=LEITURA).status_code, 401, caminho)

    def test_cookie_de_outra_sessao_nao_aproveita_o_cache(self):
        um = self.navegador("ADEGA-1", "senha-forte-1")
        self.loja_do_resumo(um)
        falso = TestClient(nuvem.app, base_url="https://testserver", cookies={"willpdv_painel": "token-inventado"})
        self.addCleanup(falso.close)
        self.assertEqual(falso.get("/v1/painel/resumo", headers=LEITURA).status_code, 401)

    def test_a_mesma_sessao_continua_usando_o_cache(self):
        from backend import cache_leitura
        um = self.navegador("ADEGA-1", "senha-forte-1")
        self.loja_do_resumo(um)
        self.assertTrue(any(chave[0] == "/v1/painel/resumo" and chave[1] for chave in cache_leitura._itens))
        self.assertNotIn(um.cookies.get("willpdv_painel"), repr(list(cache_leitura._itens)))   # token não fica guardado


if __name__ == "__main__":
    unittest.main()
