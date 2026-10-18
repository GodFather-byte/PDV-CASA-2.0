"""Aviso de versão nova: comparação de versões, publicação na nuvem, consulta do PDV e o que fica guardado."""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from src import versao
from src.sync import atualizacoes
from src.sync.sincronizador import Sincronizador
from tests.base import BaseTeste
from tests.test_nuvem import TOKENS, TestClient, cabecalho, nuvem, preparar_lojas

if nuvem is not None:
    from backend import atualizacoes as publicacao


class Resposta:
    def __init__(self, status=200, corpo=None):
        self.status_code, self._corpo = status, corpo

    def json(self):
        if isinstance(self._corpo, Exception):
            raise self._corpo
        return self._corpo


class HttpFalso:
    def __init__(self, resposta):
        self.resposta, self.chamadas = resposta, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.chamadas.append({"url": url, "params": params, "headers": headers})
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return self.resposta

    def post(self, url, json=None, headers=None, timeout=None):
        return Resposta(200, {"aceitas": []})


def resposta_nuvem(*versoes, url=None):
    """O formato de /v1/atualizacoes, com as versões da mais nova para a mais antiga."""
    return {"versao_atual": "1.1.0", "disponivel": bool(versoes), "ultima": versoes[0][0] if versoes else None,
            "critica": any(c for _, c in versoes), "url_download": url,
            "versoes": [{"versao": v, "notas": f"Notas da {v}", "critica": c, "publicada_em": "2026-10-04 10:00:00"}
                        for v, c in versoes]}


class TesteVersao(unittest.TestCase):
    def test_compara_numero_a_numero(self):
        self.assertTrue(versao.mais_nova("1.10.0", "1.9.9"))
        self.assertTrue(versao.mais_nova("2", "1.99"))
        self.assertFalse(versao.mais_nova("1.1", "1.1.0"))                  # zeros à direita não contam
        self.assertFalse(versao.mais_nova("1.0.9", "1.1.0"))

    def test_formato(self):
        self.assertTrue(versao.valida(versao.VERSAO))
        for ruim in ("", "1.", "v1.2", "1.2.3.4.5", "1.a", None):
            with self.subTest(ruim), self.assertRaises(ValueError):
                versao.chave(ruim)


class TesteAvisoNoPDV(BaseTeste):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("api_url", "https://nuvem.exemplo/v1/sincronizar")
        self.banco.cfg_set("api_token", "tok")

    def guardar(self, *versoes, url=None):
        atualizacoes.gravar(self.banco, resposta_nuvem(*versoes, url=url))

    def test_endereco_fica_ao_lado_do_de_envio(self):
        self.assertEqual(atualizacoes.url_atualizacoes("https://n.exemplo/v1/sincronizar/"), "https://n.exemplo/v1/atualizacoes")
        self.assertEqual(atualizacoes.url_atualizacoes("http://10.0.0.5:8000"), "http://10.0.0.5:8000/v1/atualizacoes")

    def test_consulta_manda_a_versao_e_o_token_da_loja(self):
        http = HttpFalso(Resposta(200, resposta_nuvem(("1.2.0", False))))
        dados = atualizacoes.consultar("https://n.exemplo/v1/sincronizar", "tok", http, versao="1.1.0")
        self.assertEqual(dados["ultima"], "1.2.0")
        self.assertEqual(http.chamadas, [{"url": "https://n.exemplo/v1/atualizacoes", "params": {"versao": "1.1.0"},
                                          "headers": {"Authorization": "Bearer tok"}}])

    def test_falha_de_rede_ou_resposta_ruim_nao_apaga_o_aviso_guardado(self):
        self.guardar(("9.0.0", False))
        for ruim in (OSError("sem rede"), Resposta(500, {}), Resposta(200, ValueError("lixo")), Resposta(200, {"x": 1})):
            with self.subTest(ruim=ruim):
                atualizacoes.gravar(self.banco, atualizacoes.consultar("https://n/v1/sincronizar", "tok", HttpFalso(ruim)))
                self.assertEqual(atualizacoes.pendente(self.banco)["ultima"], "9.0.0")
        self.assertIsNone(atualizacoes.consultar("", "tok", HttpFalso(Resposta())))      # sem nuvem configurada

    def test_aviso_some_quando_o_pdv_e_atualizado(self):
        self.guardar(("1.3.0", False), ("1.2.0", True))
        aviso = atualizacoes.pendente(self.banco, versao="1.1.0")
        self.assertEqual((aviso["ultima"], aviso["critica"], [v["versao"] for v in aviso["versoes"]]),
                         ("1.3.0", True, ["1.3.0", "1.2.0"]))
        aviso = atualizacoes.pendente(self.banco, versao="1.2.0")          # a crítica já foi instalada
        self.assertEqual((aviso["ultima"], aviso["critica"]), ("1.3.0", False))
        self.assertIsNone(atualizacoes.pendente(self.banco, versao="1.3.0"))

    def test_dispensar_vale_so_para_aquela_versao_e_nunca_para_a_critica(self):
        self.guardar(("9.0.0", False))
        atualizacoes.dispensar(self.banco, atualizacoes.pendente(self.banco))
        self.assertIsNone(atualizacoes.pendente(self.banco))
        self.guardar(("9.1.0", False), ("9.0.0", False))                     # saiu outra: volta a avisar
        self.assertEqual(atualizacoes.pendente(self.banco)["ultima"], "9.1.0")
        self.guardar(("9.2.0", True))
        critica = atualizacoes.pendente(self.banco)
        atualizacoes.dispensar(self.banco, critica)
        self.assertEqual(atualizacoes.pendente(self.banco)["ultima"], "9.2.0")

    def test_lixo_guardado_nao_quebra(self):
        for lixo in ("{", "[]", json.dumps({"versoes": [{"versao": "abc"}, "x"]})):
            self.banco.cfg_set(atualizacoes.CHAVE_RESPOSTA, lixo)
            self.assertIsNone(atualizacoes.pendente(self.banco))

    def test_consulta_no_maximo_a_cada_seis_horas(self):
        http = HttpFalso(Resposta(200, resposta_nuvem(("9.0.0", False))))
        self.assertEqual(atualizacoes.verificar(self.banco, http)["ultima"], "9.0.0")
        self.avancar(hours=5)
        atualizacoes.verificar(self.banco, http)
        self.assertEqual(len(http.chamadas), 1)
        self.avancar(hours=1)
        atualizacoes.verificar(self.banco, http)
        self.assertEqual(len(http.chamadas), 2)

    def test_a_sincronizacao_aproveita_a_rodada_para_consultar(self):
        http = HttpFalso(Resposta(200, resposta_nuvem(("9.0.0", True))))
        self.banco.cfg_set("chave_loja", "LOJA-1")
        Sincronizador(self.banco, http).iniciar_loop(rodadas=1, dormir=lambda s: None)
        self.assertEqual(atualizacoes.pendente(self.banco)["ultima"], "9.0.0")


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TestePublicacaoNaNuvem(unittest.TestCase):
    def setUp(self):
        preparar_lojas()
        self.db = nuvem.SessionLocal()
        self.addCleanup(self.db.close)
        self.db.query(nuvem.Versao).delete()
        self.db.commit()
        self.http = TestClient(nuvem.app)

    def consultar(self, versao_pdv="1.1.0", headers=None):
        return self.http.get("/v1/atualizacoes", params={"versao": versao_pdv},
                             headers=cabecalho() if headers is None else headers)

    def test_so_traz_as_versoes_mais_novas_da_mais_nova_para_a_mais_antiga(self):
        publicacao.publicar(self.db, "1.0.5", "Antiga")
        publicacao.publicar(self.db, "1.10.0", "Bem nova", url="https://exemplo/pdv-1.10.zip")
        publicacao.publicar(self.db, "1.2.0", "Corrige o troco", critica=True)
        r = self.consultar().json()
        self.assertEqual([v["versao"] for v in r["versoes"]], ["1.10.0", "1.2.0"])
        self.assertEqual((r["disponivel"], r["ultima"], r["critica"], r["url_download"]),
                         (True, "1.10.0", True, "https://exemplo/pdv-1.10.zip"))
        r = self.consultar("1.10.0").json()
        self.assertEqual((r["disponivel"], r["ultima"], r["versoes"]), (False, None, []))

    def test_exige_token_e_versao_valida(self):
        self.assertEqual(self.consultar(headers={}).status_code, 401)
        self.assertEqual(self.consultar("v1.x").status_code, 422)
        self.assertEqual(self.consultar(headers={"Authorization": "Bearer token-de-teste"}).status_code, 200)   # administrador

    def test_o_pdv_entende_a_resposta_da_nuvem(self):
        publicacao.publicar(self.db, "9.0.0", "Nova")
        http = mock.Mock()
        http.get = lambda url, **kw: self.http.get(url.replace("https://nuvem", ""), **kw)
        dados = atualizacoes.consultar("https://nuvem/v1/sincronizar", TOKENS["LOJA-1"], http)
        self.assertEqual(dados["ultima"], "9.0.0")

    def test_validacoes_da_publicacao(self):
        publicacao.publicar(self.db, "2.0.0", "Notas")
        for args in (("2.0.0", "Repetida"), ("2.x", "Notas"), ("2.0.1", "  "), ("2.0.2", "Notas", "ftp://x")):
            with self.subTest(args=args), self.assertRaises(publicacao.ErroVersao):
                publicacao.publicar(self.db, *args)
        with self.assertRaises(publicacao.ErroVersao):
            publicacao.remover(self.db, "8.8.8")

    def test_linha_de_comando(self):
        saida = io.StringIO()
        with mock.patch.object(publicacao, "SessionLocal", return_value=self.db), mock.patch.object(self.db, "close"), \
                redirect_stdout(saida):
            self.assertEqual(publicacao.main(["publicar", "3.0.0", "--notas", "Grande", "--critica"]), 0)
            self.assertEqual(publicacao.main(["listar"]), 0)
            self.assertEqual(publicacao.main(["remover", "3.0.0"]), 0)
        self.assertIn("CRÍTICA", saida.getvalue())
        self.assertEqual(self.db.query(nuvem.Versao).count(), 0)


if __name__ == "__main__":
    unittest.main()
