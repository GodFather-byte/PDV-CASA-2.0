"""Integração central (licenciador/central.py) -> ponte (backend/ponte.py) com transporte TestClient e chave de TESTE."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest import mock

from tests.test_ponte_backend import CENTRAL, PUBLICA, SEMENTE, BasePonte, TestClient, bearer
from src.core import licenca

try:
    from licenciador.central import Central, ClientePonte, ErroCentral
except ImportError:                          # a central ainda não existe nesta cópia
    Central = None

ADMIN_CHAT = 424242


@unittest.skipIf(TestClient is None or Central is None, "fastapi/httpx ou central indisponíveis")
class TesteCentralPonte(BasePonte):
    def setUp(self):
        super().setUp()
        chave = mock.patch.object(licenca, "CHAVE_PUBLICA_HEX", PUBLICA.hex())
        chave.start()
        self.addCleanup(chave.stop)
        self.pasta = Path(tempfile.mkdtemp(prefix="pdv_central_"))
        self.addCleanup(shutil.rmtree, self.pasta, True)
        self.arquivo_chave = self.pasta / "chave_teste.key"
        self.arquivo_chave.write_text(SEMENTE.hex(), encoding="ascii")
        self.chamadas = []
        cliente = ClientePonte("http://localhost", CENTRAL, transporte=self.transporte)
        self.central = Central(self.pasta / "central.db", cliente, self.arquivo_chave)
        self.addCleanup(self.central.fechar)

    def transporte(self, metodo, rota, dados):
        self.chamadas.append((metodo, rota))
        r = self.http.request(metodo, rota, json=dados, headers=bearer(CENTRAL))
        if r.status_code >= 400:
            raise ErroCentral(f"A ponte recusou a operação (HTTP {r.status_code}).")
        return r.json()

    def emitir(self, loja="PT-INT", meses=1):
        return self.central.confirmar_emissao(ADMIN_CHAT, self.central.preparar_emissao(ADMIN_CHAT, loja, meses))

    def test_fluxo_completo_cadastro_provisiona_emite_publica_contato_estado(self):
        self.assertEqual(self.central.cadastrar("PT-INT", "Loja Integração"), "PT-INT")
        self.central.administrador(ADMIN_CHAT)
        caixa_id = str(uuid.uuid4())
        token = self.central.provisionar("PT-INT", caixa_id)
        caixa = bearer(token)
        lojas = {l["chave_loja"]: l for l in self.http.get("/v1/central/lojas", headers=self.http_central()).json()["lojas"]}
        self.assertEqual((lojas["PT-INT"]["nome"], lojas["PT-INT"]["ativa"]), ("Loja Integração", True))
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=caixa).status_code, 404)

        sol = str(uuid.uuid4())
        self.assertEqual(self.http.post("/v1/ponte/solicitacoes", json={"id": sol, "tipo": "renovacao"},
                                        headers=caixa).json(), {"id": sol, "situacao": "pendente"})

        lic_id = self.emitir()
        estado = self.central.sincronizar()
        publicada = [l for l in estado["licencas"] if l["id"] == lic_id]
        self.assertEqual(len(publicada), 1)
        self.assertEqual(estado["solicitacoes"][0]["situacao"], "pendente")   # publicar não atende

        entregue = self.http.get("/v1/ponte/licenca", headers=caixa).json()
        self.assertEqual(entregue["id"], lic_id)
        lida = licenca.ler_licenca(entregue["codigo"])
        self.assertEqual((lida["loja"], lida["expira_em"].isoformat()), ("PT-INT", entregue["expira_em"]))

        r = self.http.post("/v1/ponte/contato", json={"versao": "1.6.0", "licenca_aplicada_id": lic_id}, headers=caixa)
        self.assertEqual(r.status_code, 200, r.text)
        estado = self.central.sincronizar()
        cx = next(c for c in estado["caixas"] if c["caixa_id"] == caixa_id)
        self.assertEqual((cx["chave_loja"], cx["versao"], cx["licenca_aplicada_id"], cx["revogado"]),
                         ("PT-INT", "1.6.0", lic_id, False))
        self.assertEqual((estado["solicitacoes"][0]["situacao"], estado["solicitacoes"][0]["licenca_id"]),
                         ("atendida", lic_id))
        self.assertEqual(self.central.retrato("caixas"), estado["caixas"])
        self.assertNotIn(token, str(estado))

    def http_central(self):
        return bearer(CENTRAL)

    def test_sincronizar_de_novo_nao_duplica_e_republicar_e_idempotente(self):
        self.central.cadastrar("PT-INT", "Loja")
        self.central.administrador(ADMIN_CHAT)
        lic_id = self.emitir()
        self.central.sincronizar()
        self.central.sincronizar()
        publicacoes = [c for c in self.chamadas if c == ("POST", "/v1/central/licencas")]
        self.assertEqual(len(publicacoes), 1)
        with closing(sqlite3.connect(self.pasta / "central.db")) as db:      # queda depois de publicar, antes de marcar
            with db:
                db.execute("UPDATE licencas SET publicada=0 WHERE id=?", (lic_id,))
        estado = self.central.sincronizar()
        self.assertEqual([l["id"] for l in estado["licencas"] if l["chave_loja"] == "PT-INT"], [lic_id])

    def test_renovacao_publica_prazo_maior_e_caixa_recebe_a_nova(self):
        self.central.cadastrar("PT-INT", "Loja")
        self.central.administrador(ADMIN_CHAT)
        token = self.central.provisionar("PT-INT", str(uuid.uuid4()))
        primeira = self.emitir()
        self.central.sincronizar()
        segunda = self.emitir(meses=2)
        self.central.sincronizar()
        self.assertNotEqual(primeira, segunda)
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=bearer(token)).json()["id"], segunda)

    def test_provisionar_de_novo_o_mesmo_caixa_nao_reemite_credencial(self):
        self.central.cadastrar("PT-INT", "Loja")
        caixa_id = str(uuid.uuid4())
        self.central.provisionar("PT-INT", caixa_id)
        with self.assertRaises(ErroCentral):
            self.central.provisionar("PT-INT", caixa_id)

    def test_revogar_pela_central_bloqueia_o_caixa(self):
        self.central.cadastrar("PT-INT", "Loja")
        caixa_id = str(uuid.uuid4())
        token = self.central.provisionar("PT-INT", caixa_id)
        self.central.revogar_caixa(caixa_id)
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=bearer(token)).status_code, 403)

    def test_loja_desativada_na_central_e_desativada_na_ponte(self):
        self.central.cadastrar("PT-INT", "Loja")
        token = self.central.provisionar("PT-INT", str(uuid.uuid4()))
        self.central.cadastrar("PT-INT", "Loja", ativa=False)
        self.central.sincronizar()
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=bearer(token)).status_code, 403)


    def test_loja_preexistente_com_grafia_mista_resolve_chave_original(self):
        from backend import main as nuvem
        from backend import ponte
        chave, legado = "Boate-Centro", "token-legado-boate-centro"

        def limpar():
            db = nuvem.SessionLocal()
            try:
                for modelo in (ponte.PonteLoja, ponte.PonteCaixa, ponte.PonteLicenca, ponte.PonteSolicitacao,
                               nuvem.Loja):
                    db.query(modelo).filter(modelo.chave_loja == chave).delete(synchronize_session=False)
                db.commit()
            finally:
                db.close()

        limpar()
        self.addCleanup(limpar)
        db = nuvem.SessionLocal()
        try:
            db.add(nuvem.Loja(chave_loja=chave, nome="Boate Centro", token_hash=nuvem.hash_token(legado), ativa=True))
            db.commit()
        finally:
            db.close()
        self.central.cadastrar(chave, "Boate Centro")
        caixa_id = str(uuid.uuid4())
        token = self.central.provisionar("boate-centro", caixa_id)

        estado = self.http.get("/v1/central/estado", headers=bearer(CENTRAL)).json()
        cx = next(c for c in estado["caixas"] if c["caixa_id"] == caixa_id)
        self.assertEqual(cx["chave_loja"], chave)
        lojas = [l["chave_loja"] for l in self.http.get("/v1/central/lojas", headers=bearer(CENTRAL)).json()["lojas"]]
        self.assertEqual([l for l in lojas if l.casefold() == chave.casefold()], [chave])
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=bearer(token)).status_code, 404)
        db = nuvem.SessionLocal()
        try:
            loja = db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja == chave).one()
            self.assertEqual(loja.token_hash, nuvem.hash_token(legado))      # credencial legada intacta
            self.assertFalse(ponte.em_modo_ponte(db, chave))                  # provisionar não migra a loja
        finally:
            db.close()
        self.assertNotEqual(self.http.get("/v1/licenca", headers=bearer(legado)).status_code, 401)
        self.assertEqual(self.http.get("/v1/licenca", headers=bearer(token)).status_code, 401)

    def test_pdv_real_aplica_licenca_publicada_e_central_ve_aplicada(self):
        from urllib.parse import urlsplit
        from src.database.conexao import BancoDados
        from src.sync import ponte as ponte_pdv

        http_teste, enviados = self.http, []

        class HttpTestClient:
            """Cara do `requests` usada por src.sync.ponte, entregando ao TestClient da API real."""

            def get(self, url, headers=None, timeout=None):
                enviados.append(("GET", urlsplit(url).path, None, dict(headers or {})))
                return http_teste.get(urlsplit(url).path, headers=headers)

            def post(self, url, json=None, headers=None, timeout=None):
                enviados.append(("POST", urlsplit(url).path, json, dict(headers or {})))
                return http_teste.post(urlsplit(url).path, json=json, headers=headers)

        self.central.cadastrar("PT-INT", "Loja PDV")
        self.central.administrador(ADMIN_CHAT)
        banco = BancoDados(":memory:")
        self.addCleanup(banco.fechar)
        caixa_id = ponte_pdv.garantir_caixa_id(banco)
        token = self.central.provisionar("PT-INT", caixa_id)
        for chave, valor in (("chave_loja", "PT-INT"), ("licenca_exigir", "S"),
                             ("api_url", "http://localhost/v1/sincronizar"), ("api_token", ""),
                             (ponte_pdv.CHAVE_TOKEN, token), (ponte_pdv.CHAVE_ATIVA, "S")):
            banco.cfg_set(chave, valor)
        cliente = HttpTestClient()

        sol = ponte_pdv.solicitar_renovacao(banco, cliente)
        self.assertEqual(banco.cfg(ponte_pdv.CHAVE_SOLICITACAO_ESTADO), "enviada")
        self.assertEqual(ponte_pdv.rodada(banco, cliente, forcar=True), ponte_pdv.Resultado(True, "sem_licenca"))

        lic_id = self.emitir()
        self.central.sincronizar()
        self.assertEqual(ponte_pdv.rodada(banco, cliente, forcar=True), ponte_pdv.Resultado(True, "aplicada"))
        self.assertEqual(banco.cfg(ponte_pdv.CHAVE_LICENCA_APLICADA), lic_id)
        estado_local = licenca.estado(banco)
        self.assertEqual(estado_local.situacao, "ok")
        publicada = self.http.get("/v1/ponte/licenca", headers=bearer(token)).json()
        self.assertEqual(estado_local.expira_em.isoformat(), publicada["expira_em"])
        self.assertEqual(banco.cfg(ponte_pdv.CHAVE_SOLICITACAO_ESTADO), "atendida")

        estado = self.central.sincronizar()
        cx = next(c for c in estado["caixas"] if c["caixa_id"] == caixa_id)
        self.assertEqual((cx["licenca_aplicada_id"], cx["revogado"]), (lic_id, False))
        self.assertIsNotNone(cx["ultimo_contato"])
        pedido = next(s for s in estado["solicitacoes"] if s["id"] == sol)
        self.assertEqual((pedido["situacao"], pedido["licenca_id"]), ("atendida", lic_id))

        antes = len(enviados)                                    # segundo ciclo: nada a aplicar, só contato
        self.assertEqual(ponte_pdv.rodada(banco, cliente, forcar=True), ponte_pdv.Resultado(True, "ja_aplicada"))
        self.assertEqual([(m, r) for m, r, _, _ in enviados[antes:]],
                         [("GET", "/v1/ponte/licenca"), ("POST", "/v1/ponte/contato")])
        self.assertEqual(len(self.central.sincronizar()["solicitacoes"]), 1)

        permitidos = {"/v1/ponte/licenca": None, "/v1/ponte/contato": {"versao", "licenca_aplicada_id"},
                      "/v1/ponte/solicitacoes": {"id", "tipo"}}
        for metodo, rota, corpo, cab in enviados:
            self.assertIn(rota, permitidos)
            self.assertEqual(cab["Authorization"], f"Bearer {token}")    # nunca o token da loja ou da central
            if corpo is not None:
                self.assertEqual(set(corpo), permitidos[rota])

if __name__ == "__main__":
    unittest.main()
