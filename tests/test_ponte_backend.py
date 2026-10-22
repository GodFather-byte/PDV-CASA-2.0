"""Ponte de licenças (backend/ponte.py): central publica códigos assinados no PC dela; a ponte só confere e entrega."""
from __future__ import annotations

import atexit
import logging
import os
import shutil
import tempfile
import unittest
import uuid
from datetime import date, timedelta
from pathlib import Path
from contextlib import contextmanager
from unittest import mock

_PASTA = tempfile.mkdtemp(prefix="pdv_ponte_")
os.environ.setdefault("PDV_NUVEM_DB_URL", os.environ.get("PDV_TESTE_NUVEM_DB_URL")
                      or "sqlite:///" + (Path(_PASTA) / "nuvem.db").as_posix())
os.environ.setdefault("PDV_API_TOKEN", "token-de-teste")
try:
    from fastapi.testclient import TestClient
    from backend import main as nuvem
    from backend import ponte
except (ImportError, RuntimeError):
    TestClient = nuvem = ponte = None

from src.core import ed25519
from src.core import licenca as licenca_pdv

SEMENTE = bytes(range(1, 33))                    # chave de TESTE; nunca a do fornecedor
PUBLICA = ed25519.chave_publica(SEMENTE)
OUTRA_SEMENTE = bytes(range(101, 133))
CENTRAL = "central-de-teste-" + "x" * 32
TOKENS_LOJA = {"PT-A": "token-legado-pt-a", "PT-B": "token-legado-pt-b"}


def _limpar_pasta():
    if nuvem is not None:
        nuvem.engine.dispose()
    shutil.rmtree(_PASTA, ignore_errors=True)


atexit.register(_limpar_pasta)


def codigo(loja="PT-A", dias=30, semente=SEMENTE, inicio=None):
    return licenca_pdv.gerar_licenca(semente, loja, dias, inicio or date.today())


def novo_id():
    return str(uuid.uuid4())


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class BasePonte(unittest.TestCase):
    def setUp(self):
        self._limpar()
        self.addCleanup(self._limpar)
        db = nuvem.SessionLocal()
        try:
            for chave, token in TOKENS_LOJA.items():
                db.add(nuvem.Loja(chave_loja=chave, nome=chave, token_hash=nuvem.hash_token(token), ativa=True,
                                  licenca_ate=(date.today() + timedelta(days=10)).isoformat()))
            db.commit()
        finally:
            db.close()
        ambiente = mock.patch.dict(os.environ, {"PDV_CENTRAL_TOKEN": CENTRAL, "PDV_API_TOKEN": "token-de-teste"})
        ambiente.start()
        self.addCleanup(ambiente.stop)
        chave = mock.patch.object(ponte, "chave_publica", return_value=PUBLICA)
        chave.start()
        self.addCleanup(chave.stop)
        self.http = TestClient(nuvem.app)
        self.central = bearer(CENTRAL)

    @staticmethod
    def _limpar():
        db = nuvem.SessionLocal()
        try:
            for modelo in (ponte.PonteLoja, ponte.PonteCaixa, ponte.PonteLicenca, ponte.PonteSolicitacao, nuvem.Loja):
                db.query(modelo).filter(modelo.chave_loja.like("PT-%")).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

    def caixa(self, loja="PT-A"):
        caixa_id = novo_id()
        r = self.http.post("/v1/central/caixas", json={"chave_loja": loja, "caixa_id": caixa_id}, headers=self.central)
        self.assertEqual(r.status_code, 200, r.text)
        return caixa_id, bearer(r.json()["token"])

    def publicar(self, loja="PT-A", cod=None, lic_id=None):
        return self.http.post("/v1/central/licencas", headers=self.central,
                              json={"id": lic_id or novo_id(), "chave_loja": loja, "codigo": cod or codigo(loja)})

    def estado(self):
        r = self.http.get("/v1/central/estado", headers=self.central)
        self.assertEqual(r.status_code, 200)
        return r.json()


class TesteAutenticacaoCentral(BasePonte):
    def test_sem_token_admin_loja_ou_caixa_sao_recusados(self):
        _, caixa = self.caixa()
        for cab in ({}, bearer("token-de-teste"), bearer(TOKENS_LOJA["PT-A"]), caixa, bearer("Bearer")):
            self.assertEqual(self.http.get("/v1/central/lojas", headers=cab).status_code, 401)
            self.assertEqual(self.http.post("/v1/central/licencas", headers=cab, json={}).status_code, 401)

    def test_central_nao_configurada_ou_igual_ao_admin_recusa(self):
        for valor in ("", "curto", "token-de-teste"):
            with mock.patch.dict(os.environ, {"PDV_CENTRAL_TOKEN": valor}):
                self.assertEqual(self.http.get("/v1/central/lojas", headers=bearer(valor)).status_code, 503)
        with mock.patch.dict(os.environ, {"PDV_CENTRAL_TOKEN": "a" * 40, "PDV_API_TOKEN": "a" * 40}):
            self.assertEqual(self.http.get("/v1/central/lojas", headers=bearer("a" * 40)).status_code, 503)

    def test_central_nao_entra_nas_rotas_de_loja_admin_e_caixa(self):
        self.assertEqual(self.http.get("/v1/admin/lojas", headers=self.central).status_code, 401)
        self.assertEqual(self.http.get("/v1/licenca", headers=self.central).status_code, 401)
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=self.central).status_code, 401)


class TesteLojasECaixas(BasePonte):
    def test_put_cria_loja_sem_devolver_token_e_lista(self):
        r = self.http.put("/v1/central/lojas/PT-NOVA", json={"nome": " Loja Nova ", "ativa": True}, headers=self.central)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"chave_loja": "PT-NOVA", "nome": "Loja Nova", "ativa": True, "licenca_ate": None})
        self.assertNotIn("token", r.text)
        lojas = {l["chave_loja"]: l for l in self.http.get("/v1/central/lojas", headers=self.central).json()["lojas"]}
        self.assertEqual(set(lojas["PT-A"]), {"chave_loja", "nome", "ativa", "licenca_ate"})
        self.assertIn("PT-NOVA", lojas)

    def test_put_atualiza_sem_mexer_na_credencial_legada(self):
        r = self.http.put("/v1/central/lojas/PT-A", json={"nome": "Renomeada", "ativa": True}, headers=self.central)
        self.assertEqual(r.json()["nome"], "Renomeada")
        db = nuvem.SessionLocal()
        try:
            self.assertEqual(db.query(nuvem.Loja).filter_by(chave_loja="PT-A").one().token_hash,
                             nuvem.hash_token(TOKENS_LOJA["PT-A"]))
        finally:
            db.close()
        self.assertNotEqual(self.http.get("/v1/licenca", headers=bearer(TOKENS_LOJA["PT-A"])).status_code, 401)

    def test_put_valida_corpo_e_chave(self):
        casos = [("PT-X", {"nome": "X"}), ("PT-X", {"nome": "X", "ativa": "sim"}),
                 ("PT-X", {"nome": "X", "ativa": True, "plano": "ouro"}), ("PT-X", {"nome": "", "ativa": True}),
                 ("PT X", {"nome": "X", "ativa": True}), ("PT-" + "X" * 70, {"nome": "X", "ativa": True})]
        for chave, corpo in casos:
            self.assertEqual(self.http.put(f"/v1/central/lojas/{chave}", json=corpo, headers=self.central).status_code,
                             422, (chave, corpo))

    def test_put_recusa_mesma_chave_em_outra_grafia(self):
        r = self.http.put("/v1/central/lojas/pt-a", json={"nome": "X", "ativa": True}, headers=self.central)
        self.assertEqual(r.status_code, 409)

    def test_caixa_token_aparece_uma_vez_e_so_hash_fica(self):
        caixa_id = novo_id()
        r = self.http.post("/v1/central/caixas", json={"chave_loja": "PT-A", "caixa_id": caixa_id}, headers=self.central)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {"token"})
        token = r.json()["token"]
        db = nuvem.SessionLocal()
        try:
            cx = db.query(ponte.PonteCaixa).filter_by(caixa_id=caixa_id).one()
            self.assertEqual(cx.token_hash, nuvem.hash_token(token))
        finally:
            db.close()
        self.assertNotIn(token, str(self.estado()))
        for loja in ("PT-A", "PT-B"):
            r2 = self.http.post("/v1/central/caixas", json={"chave_loja": loja, "caixa_id": caixa_id},
                                headers=self.central)
            self.assertEqual(r2.status_code, 409)
            self.assertNotIn("token", r2.json())

    def test_caixa_exige_loja_ativa_existente_e_uuid(self):
        self.http.put("/v1/central/lojas/PT-B", json={"nome": "B", "ativa": False}, headers=self.central)
        self.assertEqual(self.http.post("/v1/central/caixas", json={"chave_loja": "PT-B", "caixa_id": novo_id()},
                                        headers=self.central).status_code, 409)
        self.assertEqual(self.http.post("/v1/central/caixas", json={"chave_loja": "PT-NADA", "caixa_id": novo_id()},
                                        headers=self.central).status_code, 404)
        self.assertEqual(self.http.post("/v1/central/caixas", json={"chave_loja": "PT-A", "caixa_id": "x" * 36},
                                        headers=self.central).status_code, 422)

    def test_token_do_caixa_nao_serve_para_loja_admin_ou_painel(self):
        _, caixa = self.caixa()
        self.assertEqual(self.http.get("/v1/licenca", headers=caixa).status_code, 401)
        self.assertEqual(self.http.get("/v1/admin/lojas", headers=caixa).status_code, 401)
        self.assertEqual(self.http.post("/v1/painel/envio", json={}, headers=caixa).status_code, 401)
        self.assertEqual(self.http.get("/v1/atualizacoes?versao=1.0.0", headers=caixa).status_code, 401)

    def test_token_de_loja_e_admin_nao_servem_na_ponte(self):
        for cab in (bearer(TOKENS_LOJA["PT-A"]), bearer("token-de-teste"), {}):
            self.assertEqual(self.http.get("/v1/ponte/licenca", headers=cab).status_code, 401)

    def test_revogacao_e_idempotente_e_bloqueia(self):
        caixa_id, caixa = self.caixa()
        for _ in range(2):
            r = self.http.post(f"/v1/central/caixas/{caixa_id}/revogar", headers=self.central)
            self.assertEqual(r.json(), {"caixa_id": caixa_id, "revogado": True})
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=caixa).status_code, 403)
        self.assertEqual(self.http.post("/v1/ponte/contato", json={"versao": "1.6.0", "licenca_aplicada_id": None},
                                        headers=caixa).status_code, 403)
        self.assertEqual(self.http.post("/v1/central/caixas", json={"chave_loja": "PT-A", "caixa_id": caixa_id},
                                        headers=self.central).status_code, 409)
        self.assertEqual(self.http.post(f"/v1/central/caixas/{novo_id()}/revogar", headers=self.central).status_code,
                         404)
        self.assertTrue(self.estado()["caixas"][0]["revogado"])

    def test_loja_desativada_bloqueia_caixa(self):
        _, caixa = self.caixa()
        self.http.put("/v1/central/lojas/PT-A", json={"nome": "A", "ativa": False}, headers=self.central)
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=caixa).status_code, 403)
        self.http.put("/v1/central/lojas/PT-A", json={"nome": "A", "ativa": True}, headers=self.central)
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=caixa).status_code, 404)


class TestePublicacao(BasePonte):
    def test_publica_entrega_e_ativa_modo_ponte(self):
        _, caixa = self.caixa()
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=caixa).status_code, 404)
        lic_id, cod = novo_id(), codigo(dias=40)
        r = self.publicar(cod=cod, lic_id=lic_id)
        expira = (date.today() + timedelta(days=40)).isoformat()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"id": lic_id, "chave_loja": "PT-A", "expira_em": expira})
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=caixa).json(),
                         {"id": lic_id, "codigo": cod, "expira_em": expira})
        self.assertEqual(self.estado()["licencas"], [{"id": lic_id, "chave_loja": "PT-A", "codigo": cod,
                                                      "expira_em": expira}])
        lojas = {l["chave_loja"]: l for l in self.http.get("/v1/central/lojas", headers=self.central).json()["lojas"]}
        self.assertEqual(lojas["PT-A"]["licenca_ate"], expira)
        db = nuvem.SessionLocal()
        try:
            self.assertTrue(ponte.em_modo_ponte(db, "PT-A"))
            self.assertFalse(ponte.em_modo_ponte(db, "PT-B"))
        finally:
            db.close()

    def test_aprovar_caixa_nao_ativa_modo_ponte(self):
        self.caixa()
        db = nuvem.SessionLocal()
        try:
            self.assertFalse(ponte.em_modo_ponte(db, "PT-A"))
        finally:
            db.close()

    def test_idempotencia_por_id(self):
        lic_id, cod = novo_id(), codigo()
        primeira = self.publicar(cod=cod, lic_id=lic_id)
        self.assertEqual(self.publicar(cod=cod, lic_id=lic_id).json(), primeira.json())
        self.assertEqual(self.publicar(cod=codigo(dias=31), lic_id=lic_id).status_code, 409)
        self.assertEqual(self.publicar(loja="PT-B", cod=codigo("PT-B"), lic_id=lic_id).status_code, 409)
        self.assertEqual(self.publicar(cod=cod).status_code, 409)       # mesmo código com outro id
        self.assertEqual(len(self.estado()["licencas"]), 1)

    def test_recusa_adulterada_outra_chave_outra_loja_vencida(self):
        cod = codigo()
        prefixo, carga, assinatura = cod.split(".")
        adulterada = f"{prefixo}.{carga}.{'A' if assinatura[0] != 'A' else 'B'}{assinatura[1:]}"
        for ruim in (adulterada, codigo(semente=OUTRA_SEMENTE), codigo("PT-B"), "PDVL1.lixo.lixo",
                     codigo(dias=1, inicio=date.today() - timedelta(days=10))):
            self.assertEqual(self.publicar(cod=ruim).status_code, 422)
        self.assertEqual(self.estado()["licencas"], [])

    def test_valida_campos(self):
        for corpo in ({"id": "nao-uuid", "chave_loja": "PT-A", "codigo": codigo()},
                      {"id": novo_id(), "chave_loja": "PT-A", "codigo": "x" * 2000},
                      {"id": novo_id(), "chave_loja": "PT-A", "codigo": codigo(), "valor_cent": 9900},
                      {"id": novo_id(), "chave_loja": "PT-A"}):
            self.assertEqual(self.http.post("/v1/central/licencas", json=corpo, headers=self.central).status_code, 422)
        self.assertEqual(self.publicar(loja="PT-NADA", cod=codigo("PT-NADA")).status_code, 404)

    def test_prazo_nao_retrocede(self):
        longa = codigo(dias=60)
        self.assertEqual(self.publicar(cod=longa).status_code, 200)
        self.assertEqual(self.publicar(cod=codigo(dias=30)).status_code, 409)
        mais_longa = codigo(dias=90)
        self.assertEqual(self.publicar(cod=mais_longa).status_code, 200)
        _, caixa = self.caixa()
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=caixa).json()["codigo"], mais_longa)

    def test_loja_desativada_nao_recebe_publicacao(self):
        self.http.put("/v1/central/lojas/PT-A", json={"nome": "A", "ativa": False}, headers=self.central)
        self.assertEqual(self.publicar().status_code, 409)

    def test_isolamento_entre_lojas(self):
        _, caixa_a = self.caixa("PT-A")
        _, caixa_b = self.caixa("PT-B")
        cod_a = codigo("PT-A")
        self.publicar(cod=cod_a)
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=caixa_b).status_code, 404)
        self.assertEqual(self.http.get("/v1/ponte/licenca", headers=caixa_a).json()["codigo"], cod_a)

    def test_nao_registra_token_nem_codigo_no_log(self):
        with self.assertLogs("pdv.ponte", level="INFO") as registro:
            caixa_id = novo_id()
            token = self.http.post("/v1/central/caixas", json={"chave_loja": "PT-A", "caixa_id": caixa_id},
                                   headers=self.central).json()["token"]
            cod = codigo()
            self.publicar(cod=cod)
        texto = "\n".join(registro.output)
        for segredo in (token, cod, CENTRAL):
            self.assertNotIn(segredo, texto)


class TesteContatoESolicitacoes(BasePonte):
    def test_contato_registra_versao_e_licenca_aplicada(self):
        caixa_id, caixa = self.caixa()
        lic_id = novo_id()
        self.publicar(lic_id=lic_id)
        r = self.http.post("/v1/ponte/contato", json={"versao": "1.6.0", "licenca_aplicada_id": lic_id}, headers=caixa)
        self.assertEqual(r.status_code, 200, r.text)
        cx = self.estado()["caixas"][0]
        self.assertEqual((cx["caixa_id"], cx["chave_loja"], cx["versao"], cx["licenca_aplicada_id"], cx["revogado"]),
                         (caixa_id, "PT-A", "1.6.0", lic_id, False))
        self.assertEqual(cx["ultimo_contato"], r.json()["ultimo_contato"])
        r = self.http.post("/v1/ponte/contato", json={"versao": "1.6.1", "licenca_aplicada_id": None}, headers=caixa)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self.estado()["caixas"][0]["licenca_aplicada_id"])

    def test_contato_recusa_licenca_de_outra_loja_ou_inexistente(self):
        _, caixa = self.caixa("PT-A")
        lic_b = novo_id()
        self.publicar(loja="PT-B", cod=codigo("PT-B"), lic_id=lic_b)
        for lic in (lic_b, novo_id()):
            self.assertEqual(self.http.post("/v1/ponte/contato", json={"versao": "1.6.0", "licenca_aplicada_id": lic},
                                            headers=caixa).status_code, 422)

    def test_contato_valida_campos(self):
        _, caixa = self.caixa()
        for corpo in ({"versao": "1.6.0"}, {"versao": "abc", "licenca_aplicada_id": None},
                      {"versao": "1" * 30, "licenca_aplicada_id": None},
                      {"versao": "1.6.0", "licenca_aplicada_id": None, "faturamento_cent": 100}):
            self.assertEqual(self.http.post("/v1/ponte/contato", json=corpo, headers=caixa).status_code, 422)

    def test_solicitacao_idempotente_e_isolada(self):
        caixa_id, caixa = self.caixa()
        _, outro = self.caixa("PT-B")
        sol = novo_id()
        for _ in range(2):
            r = self.http.post("/v1/ponte/solicitacoes", json={"id": sol, "tipo": "renovacao"}, headers=caixa)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {"id": sol, "situacao": "pendente"})
        self.assertEqual(self.http.post("/v1/ponte/solicitacoes", json={"id": sol, "tipo": "renovacao"},
                                        headers=outro).status_code, 409)
        for corpo in ({"id": novo_id(), "tipo": "emitir"}, {"id": "x", "tipo": "renovacao"},
                      {"id": novo_id(), "tipo": "renovacao", "texto": "oi"}):
            self.assertEqual(self.http.post("/v1/ponte/solicitacoes", json=corpo, headers=caixa).status_code, 422)
        estado = self.estado()["solicitacoes"]
        self.assertEqual(len(estado), 1)
        self.assertEqual((estado[0]["id"], estado[0]["chave_loja"], estado[0]["caixa_id"], estado[0]["tipo"],
                          estado[0]["situacao"]), (sol, "PT-A", caixa_id, "renovacao", "pendente"))
        self.assertEqual(self.estado()["licencas"], [])        # solicitar não emite


class TesteLegado(BasePonte):
    def test_loja_migrada_recebe_codigo_publicado_sem_assinar_na_nuvem(self):
        cod = codigo(dias=45)
        self.publicar(cod=cod)
        with mock.patch.object(nuvem, "semente_licenca") as semente, \
                mock.patch.object(nuvem.licenca_pdv, "gerar_licenca") as gerar:
            r = self.http.get("/v1/licenca", headers=bearer(TOKENS_LOJA["PT-A"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"codigo": cod, "expira_em": (date.today() + timedelta(days=45)).isoformat()})
        semente.assert_not_called()
        gerar.assert_not_called()

    def test_loja_migrada_sem_chave_na_nuvem_continua_entregando(self):
        self.publicar()
        with mock.patch.object(nuvem, "semente_licenca", return_value=None):
            self.assertEqual(self.http.get("/v1/licenca", headers=bearer(TOKENS_LOJA["PT-A"])).status_code, 200)

    def test_loja_nao_migrada_mantem_caminho_antigo(self):
        self.publicar()                                    # só a PT-A migra
        with mock.patch.object(nuvem, "semente_licenca", return_value=None):
            self.assertEqual(self.http.get("/v1/licenca", headers=bearer(TOKENS_LOJA["PT-B"])).status_code, 503)
        with mock.patch.object(nuvem, "semente_licenca", return_value=SEMENTE), \
                mock.patch.object(nuvem.licenca_pdv, "CHAVE_PUBLICA_HEX", PUBLICA.hex()):
            r = self.http.get("/v1/licenca", headers=bearer(TOKENS_LOJA["PT-B"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(licenca_pdv.ler_licenca(r.json()["codigo"], PUBLICA)["loja"], "PT-B")

    def test_aprovar_caixa_sem_publicar_nao_muda_o_legado(self):
        self.caixa()
        with mock.patch.object(nuvem, "semente_licenca", return_value=None):
            self.assertEqual(self.http.get("/v1/licenca", headers=bearer(TOKENS_LOJA["PT-A"])).status_code, 503)


@contextmanager
def corrida(tabela, **valores):
    """Simula outra requisição gravando a mesma linha entre a conferência e o commit desta (antes do flush)."""
    from sqlalchemy import event
    feito = []

    def outra_requisicao(sessao, contexto, instancias):
        if not feito:
            feito.append(True)
            with nuvem.engine.begin() as con:
                con.execute(tabela.insert().values(**valores))

    event.listen(nuvem.SessionLocal, "before_flush", outra_requisicao)
    try:
        yield feito
    finally:
        event.remove(nuvem.SessionLocal, "before_flush", outra_requisicao)


class TesteSolicitacaoAtendida(BasePonte):
    def pedir(self, caixa, sol=None):
        sol = sol or novo_id()
        r = self.http.post("/v1/ponte/solicitacoes", json={"id": sol, "tipo": "renovacao"}, headers=caixa)
        self.assertEqual(r.status_code, 200, r.text)
        return sol, r.json()["situacao"]

    def contato(self, caixa, lic_id):
        r = self.http.post("/v1/ponte/contato", json={"versao": "1.6.0", "licenca_aplicada_id": lic_id}, headers=caixa)
        self.assertEqual(r.status_code, 200, r.text)

    def situacao(self, sol):
        return next(s for s in self.estado()["solicitacoes"] if s["id"] == sol)

    def test_so_aplicacao_de_licenca_publicada_depois_atende(self):
        _, caixa = self.caixa()
        _, outro_caixa = self.caixa()
        antiga = novo_id()
        self.publicar(cod=codigo(dias=20), lic_id=antiga)
        sol, situacao = self.pedir(caixa)
        self.assertEqual(situacao, "pendente")
        self.contato(caixa, antiga)                                   # licença anterior ao pedido
        self.assertEqual(self.situacao(sol)["situacao"], "pendente")
        nova = novo_id()
        self.assertEqual(self.publicar(cod=codigo(dias=50), lic_id=nova).status_code, 200)
        self.assertEqual(self.situacao(sol)["situacao"], "pendente")  # publicar não basta
        self.contato(outro_caixa, nova)                               # outro caixa aplicou, este ainda não
        self.assertEqual(self.situacao(sol)["situacao"], "pendente")
        self.contato(caixa, nova)
        atendida = self.situacao(sol)
        self.assertEqual((atendida["situacao"], atendida["licenca_id"]), ("atendida", nova))
        self.assertIsNotNone(atendida["atendida_em"])
        self.contato(caixa, nova)                                     # contato repetido não muda nada
        self.assertEqual(self.situacao(sol), atendida)
        self.assertEqual(self.pedir(caixa, sol), (sol, "atendida"))   # reenvio do mesmo id: idempotente
        self.assertEqual(len(self.estado()["solicitacoes"]), 1)

    def test_pedido_sem_licenca_anterior_e_atendido_pela_primeira(self):
        _, caixa = self.caixa()
        sol, _ = self.pedir(caixa)
        lic = novo_id()
        self.publicar(lic_id=lic)
        self.contato(caixa, None)
        self.assertEqual(self.situacao(sol)["situacao"], "pendente")
        self.contato(caixa, lic)
        self.assertEqual(self.situacao(sol)["situacao"], "atendida")

    def test_novo_pedido_depois_de_aplicar_espera_licenca_mais_nova(self):
        _, caixa = self.caixa()
        lic = novo_id()
        self.publicar(lic_id=lic)
        self.contato(caixa, lic)
        sol, _ = self.pedir(caixa)
        self.contato(caixa, lic)
        self.assertEqual(self.situacao(sol)["situacao"], "pendente")


class TesteConcorrencia(BasePonte):
    def test_loja_criada_ao_mesmo_tempo_da_409(self):
        with corrida(nuvem.Loja.__table__, chave_loja="PT-CORRIDA", nome="Outra", ativa=True,
                     token_hash=nuvem.hash_token("outra-corrida")) as feito:
            r = self.http.put("/v1/central/lojas/PT-CORRIDA", json={"nome": "X", "ativa": True}, headers=self.central)
        self.assertTrue(feito)
        self.assertEqual(r.status_code, 409)

    def test_caixa_aprovado_ao_mesmo_tempo_da_409_sem_token(self):
        caixa_id = novo_id()
        with corrida(ponte.PonteCaixa.__table__, caixa_id=caixa_id, chave_loja="PT-A", token_hash="f" * 64,
                     revogado=False, criado_em="2026-10-21 10:00:00") as feito:
            r = self.http.post("/v1/central/caixas", json={"chave_loja": "PT-A", "caixa_id": caixa_id},
                               headers=self.central)
        self.assertTrue(feito)
        self.assertEqual(r.status_code, 409)
        self.assertNotIn("token", r.json())

    def _licenca(self, lic_id, cod):
        dados = licenca_pdv.ler_licenca(cod, PUBLICA)
        return dict(id=lic_id, chave_loja="PT-A", codigo=cod, emitida_em=dados["emitida_em"].isoformat(),
                    expira_em=dados["expira_em"].isoformat(), publicada_em="2026-10-21 10:00:00")

    def test_publicacao_identica_simultanea_e_sucesso(self):
        lic_id, cod = novo_id(), codigo()
        with corrida(ponte.PonteLicenca.__table__, **self._licenca(lic_id, cod)) as feito:
            r = self.publicar(cod=cod, lic_id=lic_id)
        self.assertTrue(feito)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["id"], lic_id)
        self.assertEqual(len(self.estado()["licencas"]), 1)

    def test_publicacao_diferente_simultanea_da_409(self):
        lic_id = novo_id()
        with corrida(ponte.PonteLicenca.__table__, **self._licenca(lic_id, codigo(dias=31))) as feito:
            r = self.publicar(cod=codigo(dias=40), lic_id=lic_id)
        self.assertTrue(feito)
        self.assertEqual(r.status_code, 409)

    def test_solicitacao_simultanea_com_mesmo_id_e_idempotente(self):
        caixa_id, caixa = self.caixa()
        sol = novo_id()
        with corrida(ponte.PonteSolicitacao.__table__, id=sol, chave_loja="PT-A", caixa_id=caixa_id, tipo="renovacao",
                     situacao="pendente", criada_em="2026-10-21 10:00:00", licenca_seq_base=0) as feito:
            r = self.http.post("/v1/ponte/solicitacoes", json={"id": sol, "tipo": "renovacao"}, headers=caixa)
        self.assertTrue(feito)
        self.assertEqual(r.json(), {"id": sol, "situacao": "pendente"})
        self.assertEqual(len(self.estado()["solicitacoes"]), 1)

    def test_solicitacao_simultanea_de_outro_caixa_da_409(self):
        _, caixa = self.caixa()
        sol = novo_id()
        with corrida(ponte.PonteSolicitacao.__table__, id=sol, chave_loja="PT-B", caixa_id=novo_id(), tipo="renovacao",
                     situacao="pendente", criada_em="2026-10-21 10:00:00", licenca_seq_base=0):
            r = self.http.post("/v1/ponte/solicitacoes", json={"id": sol, "tipo": "renovacao"}, headers=caixa)
        self.assertEqual(r.status_code, 409)


if __name__ == "__main__":
    unittest.main()
