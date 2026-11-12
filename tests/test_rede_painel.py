"""Tela da rede no painel do dono: o dono entra numa loja e consegue voltar para a lista de lojas."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_grupos_rede import grupos_modelo
from tests.test_painel_dono import ADMIN, BaseNuvem, TestClient, cabecalho, nuvem, painel

WEB = Path(__file__).resolve().parent.parent / "backend" / "painel_web"
DIA = {"de": "2026-10-03", "ate": "2026-10-03"}


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteVoltaDaRede(BaseNuvem):
    def setUp(self):
        super().setUp()
        self.addCleanup(self._limpar)
        r = self.http.post("/v1/admin/grupos", json={"nome": "EA Superações", "chave": "REDE-VOLTA",
                                                     "senha": "senha-da-rede-1", "temporaria": False}, headers=ADMIN)
        self.assertEqual(r.status_code, 200, r.text)
        for chave in ("ADEGA-1", "ADEGA-2"):
            self.assertEqual(self.http.post("/v1/admin/grupos/REDE-VOLTA/lojas", json={"chave_loja": chave},
                                            headers=ADMIN).status_code, 200)
        entrada = self.http.post("/v1/painel/login", json={"loja": "REDE-VOLTA", "senha": "senha-da-rede-1"})
        self.assertEqual(entrada.status_code, 200, entrada.text)
        self.rede = {"Authorization": "Bearer " + entrada.json()["token"]}

    def _limpar(self):
        painel.tentativas.acertou("REDE-VOLTA")
        db = nuvem.SessionLocal()
        try:
            db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja.in_(["ADEGA-1", "ADEGA-2"])).update(
                {"grupo_id": None}, synchronize_session=False)
            db.query(grupos_modelo()).filter_by(chave="REDE-VOLTA").delete()
            db.commit()
        finally:
            db.close()

    def test_sessao_da_rede_continua_valendo_depois_de_abrir_e_fechar_uma_loja(self):
        """É o que a volta para a lista de lojas usa: a sessão da loja acaba, a da rede não."""
        dentro = self.http.post("/v1/painel/grupo/entrar", json={"loja": "ADEGA-1"}, headers=self.rede)
        self.assertEqual(dentro.status_code, 200, dentro.text)
        loja = {"Authorization": "Bearer " + dentro.json()["token"]}
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=loja).status_code, 200)
        self.assertEqual(self.http.get("/v1/painel/rede", params=DIA, headers=loja).status_code, 404)   # loja não é rede
        self.assertEqual(self.http.post("/v1/painel/sair", headers=loja).status_code, 200)               # "Todas as lojas"
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=loja).status_code, 401)
        self.assertEqual(self.http.get("/v1/painel/rede", params=DIA, headers=self.rede).status_code, 200)
        outra = self.http.post("/v1/painel/grupo/entrar", json={"loja": "ADEGA-2"}, headers=self.rede)
        self.assertEqual(outra.status_code, 200, outra.text)
        self.assertEqual(outra.json()["loja"]["chave"], "ADEGA-2")

    def test_cada_loja_da_rede_traz_vendas_e_situacao_do_envio(self):
        venda = {"status": "fechada", "dia": "2026-10-03", "desconto_cent": 0, "modalidade": "balcao"}
        for uuid, total, status in (("volta-1", 2400, "fechada"), ("volta-2", 600, "fechada"), ("volta-3", 900, "cancelada")):
            self.http.post("/v1/painel/envio", json={"vendas": [{
                **venda, "uuid": uuid, "status": status, "total_cent": total,
                "pagamentos": [{"tipo": "Pix", "valor_cent": total, "troco_cent": 0}],
                "itens": [{"nome": "SKOL", "quantidade": 1, "total_cent": total, "cancelado": 0, "custo_linha_cent": 100}],
            }]}, headers=cabecalho("ADEGA-1"))
        dados = self.http.get("/v1/painel/rede", params=DIA, headers=self.rede).json()
        por_loja = {l["chave"]: l for l in dados["por_loja"]}
        self.assertEqual(sorted(por_loja), ["ADEGA-1", "ADEGA-2"])
        for loja in por_loja.values():
            self.assertIn("atualizado_em", loja)
            self.assertIn("atraso_min", loja)
            self.assertEqual(type(loja["vendas"]), int)
        self.assertEqual(sum(l["faturamento_cent"] for l in por_loja.values()), dados["faturamento_cent"])
        self.assertEqual((por_loja["ADEGA-1"]["vendas"], por_loja["ADEGA-2"]["vendas"]), (2, 0))      # cancelada não conta
        self.assertEqual(por_loja["ADEGA-1"]["faturamento_cent"], 3000)
        vazio = self.http.get("/v1/painel/rede", params={"de": "2020-01-01", "ate": "2020-01-01"}, headers=self.rede).json()
        self.assertEqual([l["vendas"] for l in vazio["por_loja"]], [0, 0])


class TestePaginaDaRede(unittest.TestCase):
    """A página guarda a sessão da rede num lugar que sobrevive a abrir loja, recarregar e fechar o app."""

    def setUp(self):
        self.js = (WEB / "app.js").read_text(encoding="utf-8")
        self.html = (WEB / "index.html").read_text(encoding="utf-8")

    def test_volta_para_as_lojas_fica_no_topo_da_loja_em_qualquer_aba(self):
        faixa, cabecalho, abas = (self.html.index(t) for t in ('id="faixa-rede"', '<header class="cabecalho">\n      <div class="cabecalho-titulo">', 'data-aba='))
        self.assertLess(self.html.index('id="tela-app"'), faixa)
        self.assertLess(faixa, cabecalho)
        self.assertLess(cabecalho, abas)
        self.assertIn('id="botao-voltar-rede"', self.html)
        self.assertIn("Todas as lojas", self.html)

    def test_sessao_da_rede_nao_fica_no_prefixo_que_a_troca_de_loja_apaga(self):
        prefixo = re.search(r'const PREFIXO = "([^"]+)"', self.js).group(1)
        for nome in ("REDE_TOKEN", "REDE_GRUPO", "REDE_EXPIRA"):
            valor = re.search(rf'const {nome} = "([^"]+)"', self.js).group(1)
            self.assertFalse(valor.startswith(prefixo), nome)
        self.assertNotIn("sessionStorage.setItem", self.js)                # sessionStorage some ao fechar o app
        self.assertNotIn('gravarArmazenamento(PREFIXO + "grupo"', self.js)   # era o que quebrava ao recarregar dentro da loja

    def test_sair_esquece_a_rede_e_login_direto_na_loja_tambem(self):
        self.assertGreaterEqual(self.js.count("esquecerRede();"), 2)
        self.assertIn("function voltarParaRede()", self.js)


if __name__ == "__main__":
    unittest.main()
