"""O dono troca a senha do painel pelo próprio PDV (Configurações > Nuvem): as regras e a nuvem de verdade, sem tela.
A janela do Tk tem o seu arquivo (test_painel_senha_tk.py); a do Qt, o test_qt_configuracoes.py."""
from __future__ import annotations

import unittest

from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.sync import painel_envio
from tests.base import BaseTeste
from tests.test_painel_dono import ADMIN, TOKENS, BaseNuvem, TestClient, _ClienteSemTimeout, nuvem

URL = "https://nuvem.exemplo/v1/sincronizar"


class Resposta:
    def __init__(self, status=200, corpo=None, sem_json=False):
        self.status_code, self._corpo, self._sem_json = status, corpo or {}, sem_json

    def json(self):
        if self._sem_json:
            raise ValueError("a resposta não é JSON")
        return self._corpo


class HttpDeSenha:
    """Responde o que foi combinado e guarda o que o PDV enviou."""

    def __init__(self, resposta=None, erro=None):
        self.resposta, self.erro, self.chamadas = resposta or Resposta(), erro, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.chamadas.append({"url": url, "corpo": json, "headers": headers, "timeout": timeout})
        if self.erro is not None:
            raise self.erro
        return self.resposta


# ------------------------------------------------------------- as regras, sem tela nem servidor
class TesteTrocarSenhaNoPdv(BaseTeste):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("api_url", URL)
        self.banco.cfg_set("api_token", "token-da-loja")

    def trocar(self, senha=None, http=None, **kw):
        return painel_envio.trocar_senha_na_nuvem(URL, "token-da-loja", senha, http or HttpDeSenha(), **kw)

    def test_endereco_da_senha_fica_ao_lado_do_de_envio(self):
        for url in (URL, "https://nuvem.exemplo/", "https://nuvem.exemplo"):
            self.assertEqual(painel_envio.url_senha(url), "https://nuvem.exemplo/v1/painel/senha", url)

    def test_senha_escolhida_vai_com_o_token_da_loja_e_nao_volta(self):
        http = HttpDeSenha(Resposta(200, {"loja": "ADEGA-1", "senha": None, "definida": True}))
        self.assertIsNone(self.trocar("  minha-senha-1  ", http))
        chamada = http.chamadas[0]
        self.assertEqual(chamada["url"], "https://nuvem.exemplo/v1/painel/senha")
        self.assertEqual(chamada["corpo"], {"senha": "minha-senha-1"})                  # sem as pontas em branco
        self.assertEqual(chamada["headers"], {"Authorization": "Bearer token-da-loja"})
        self.assertEqual(chamada["timeout"], (5, 30))

    def test_em_branco_a_nuvem_gera_e_a_senha_volta_uma_vez(self):
        http = HttpDeSenha(Resposta(200, {"loja": "ADEGA-1", "senha": "abcd-efgh-jkmn", "definida": True}))
        for vazio in (None, "", "   "):
            self.assertEqual(self.trocar(vazio, http), "abcd-efgh-jkmn")
        self.assertTrue(all(c["corpo"] == {} for c in http.chamadas))

    def test_gerada_que_nao_volta_pede_senha_propria(self):
        with self.assertRaisesRegex(ErroNegocio, "não devolveu a nova"):
            self.trocar(None, HttpDeSenha(Resposta(200, {"definida": True})))
        with self.assertRaisesRegex(ErroNegocio, "não devolveu a nova"):
            self.trocar(None, HttpDeSenha(Resposta(200, sem_json=True)))

    def test_senha_curta_ou_longa_demais_nem_chega_a_nuvem(self):
        http = HttpDeSenha()
        with self.assertRaisesRegex(ErroNegocio, "pelo menos 8 caracteres"):
            self.trocar("1234567", http)
        with self.assertRaisesRegex(ErroNegocio, "longa demais"):
            self.trocar("x" * 129, http)
        self.assertEqual(http.chamadas, [])
        self.trocar("x" * 128, http)                                                     # o limite exato passa
        self.trocar("12345678", http)

    def test_sem_endereco_ou_sem_token_pede_para_preencher(self):
        http = HttpDeSenha()
        for url, token in (("", "t"), ("  ", "t"), (URL, ""), (URL, "  ")):
            with self.assertRaisesRegex(ErroNegocio, "Preencha o endereço da nuvem e o token"):
                painel_envio.trocar_senha_na_nuvem(url, token, "senha-boa-1", http)
        self.assertEqual(http.chamadas, [])

    def test_erros_da_nuvem_viram_mensagem_para_o_operador(self):
        casos = [
            (Resposta(401, {"detail": "Token invalido"}), "não reconheceu o token"),
            (Resposta(403, {"detail": "Loja desativada na nuvem."}), "Loja desativada na nuvem. A senha NÃO foi trocada"),
            (Resposta(403, {"detail": "Use o token da loja (ou a rota de administrador com a chave)."}), "Use o token da loja"),
            (Resposta(403, sem_json=True), "HTTP 403"),
            (Resposta(422, {"detail": "A senha do painel precisa ter pelo menos 8 caracteres."}), "pelo menos 8 caracteres"),
            (Resposta(422, {"detail": [{"msg": "campo inválido"}]}), "HTTP 422"),          # detalhe que não é texto
            (Resposta(500, {}), "HTTP 500"),
            (Resposta(503, {"detail": "Servidor sem lojas cadastradas."}), "HTTP 503"),
        ]
        for resposta, esperado in casos:
            with self.subTest(status=resposta.status_code):
                with self.assertRaises(ErroNegocio) as contexto:
                    self.trocar("senha-boa-1", HttpDeSenha(resposta))
                self.assertIn(esperado, str(contexto.exception))
                self.assertIn("NÃO foi trocada", str(contexto.exception))

    def test_sem_conexao_diz_que_a_senha_nao_foi_trocada(self):
        for erro in (ConnectionError("rede fora"), TimeoutError("demorou"), OSError("sem rota")):
            with self.assertRaisesRegex(ErroNegocio, "Sem conexão com a nuvem: a senha NÃO foi trocada"):
                self.trocar("senha-boa-1", HttpDeSenha(erro=erro))

    def test_requests_de_verdade_tambem_cai_na_mensagem_de_conexao(self):
        import requests
        with self.assertRaisesRegex(ErroNegocio, "Sem conexão"):
            self.trocar("senha-boa-1", HttpDeSenha(erro=requests.ConnectionError("sem rede")))
        with self.assertRaisesRegex(ErroNegocio, "Sem conexão"):
            self.trocar("senha-boa-1", HttpDeSenha(erro=requests.Timeout("demorou")))

    def test_trocar_senha_usa_o_endereco_do_banco_e_registra_sem_a_senha(self):
        http = HttpDeSenha(Resposta(200, {"senha": None, "definida": True}))
        adm = self.operador_adm()
        self.assertIsNone(painel_envio.trocar_senha(self.banco, "segredo-novo-1", http, operador_id=adm))
        self.assertEqual(http.chamadas[0]["url"], "https://nuvem.exemplo/v1/painel/senha")
        linhas = self.banco.todos("SELECT operador_id, evento, detalhe FROM log_eventos WHERE evento = 'painel_senha_trocada'")
        self.assertEqual([(l["operador_id"], l["detalhe"]) for l in linhas], [(adm, "senha escolhida pelo operador")])
        self.assertNotIn("segredo-novo-1", " ".join(str(tuple(l)) for l in self.banco.todos("SELECT * FROM log_eventos")))

    def test_senha_gerada_tambem_fica_no_log_sem_aparecer(self):
        http = HttpDeSenha(Resposta(200, {"senha": "abcd-efgh-jkmn", "definida": True}))
        self.assertEqual(painel_envio.trocar_senha(self.banco, None, http), "abcd-efgh-jkmn")
        detalhes = [l["detalhe"] for l in self.banco.todos("SELECT detalhe FROM log_eventos WHERE evento = 'painel_senha_trocada'")]
        self.assertEqual(detalhes, ["senha gerada pela nuvem"])

    def test_falha_nao_deixa_registro_de_troca(self):
        with self.assertRaises(ErroNegocio):
            painel_envio.trocar_senha(self.banco, "segredo-novo-1", HttpDeSenha(Resposta(401)))
        self.assertIsNone(self.banco.um("SELECT 1 FROM log_eventos WHERE evento = 'painel_senha_trocada'"))

    def test_banco_sem_nuvem_configurada(self):
        vazio = BancoDados(":memory:")
        self.addCleanup(vazio.fechar)
        with self.assertRaisesRegex(ErroNegocio, "Preencha o endereço da nuvem"):
            painel_envio.trocar_senha(vazio, "segredo-novo-1", HttpDeSenha())


# ------------------------------------------------------- contra a API de verdade (TestClient)
@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteTrocarSenhaContraANuvem(BaseNuvem):
    def trocar(self, senha=None, token=TOKENS["ADEGA-1"]):
        return painel_envio.trocar_senha_na_nuvem("http://testserver/v1/sincronizar", token, senha, _ClienteSemTimeout(self.http))

    def pode_entrar(self, senha, loja="ADEGA-1"):
        return self.http.post("/v1/painel/login", json={"loja": loja, "senha": senha}).status_code == 200

    def test_senha_escolhida_passa_a_valer_e_derruba_o_celular(self):
        sessao = self.entrar(senha="senha-antiga-1")
        self.assertIsNone(self.trocar("senha-nova-do-dono"))
        self.assertTrue(self.pode_entrar("senha-nova-do-dono"))
        self.assertFalse(self.pode_entrar("senha-antiga-1"))
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=sessao).status_code, 401)   # o celular entra de novo

    def test_senha_gerada_pela_nuvem_volta_e_funciona(self):
        gerada = self.trocar(None)
        self.assertRegex(gerada, r"^[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}$")
        self.assertTrue(self.pode_entrar(gerada))

    def test_so_mexe_na_loja_do_token(self):
        self.entrar("ADEGA-2", "senha-da-outra-1")
        self.trocar("senha-nova-do-dono")                                            # token da ADEGA-1
        self.assertTrue(self.pode_entrar("senha-da-outra-1", "ADEGA-2"))
        self.assertFalse(self.pode_entrar("senha-nova-do-dono", "ADEGA-2"))

    def test_token_errado_de_admin_ou_de_loja_desativada(self):
        with self.assertRaisesRegex(ErroNegocio, "não reconheceu o token"):
            self.trocar("senha-nova-do-dono", token="token-que-nao-existe")
        with self.assertRaisesRegex(ErroNegocio, "Use o token da loja"):
            self.trocar("senha-nova-do-dono", token=ADMIN["Authorization"].split()[1])
        db = nuvem.SessionLocal()
        try:
            from backend import lojas
            lojas.definir_ativa(db, "ADEGA-1", False)
        finally:
            db.close()
        with self.assertRaisesRegex(ErroNegocio, "Loja desativada na nuvem"):
            self.trocar("senha-nova-do-dono")
        self.assertFalse(self.pode_entrar("senha-nova-do-dono"))

    def test_regras_de_tamanho_valem_nos_dois_lados(self):
        with self.assertRaises(ErroNegocio):
            self.trocar("curta")                                                     # barrada antes de sair do PDV
        r = self.http.post("/v1/painel/senha", json={"senha": "curta"}, headers={"Authorization": f"Bearer {TOKENS['ADEGA-1']}"})
        self.assertEqual(r.status_code, 422)                                         # e se algum PDV passar, a nuvem barra


if __name__ == "__main__":
    unittest.main()
