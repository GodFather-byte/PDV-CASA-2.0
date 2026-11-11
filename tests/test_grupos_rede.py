"""Rede de lojas: um login, uma mensalidade, cada caixa separado."""
from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from tests.test_painel_dono import ADMIN, BaseNuvem, TestClient, cabecalho, nuvem, painel


def _pedido_rede(chave):
    return {
        "valor_cent": 10000, "dia_vencimento": 10, "email": "financeiro@exemplo.com",
        "whatsapp": "+55 11 98888-7777", "nome": "Maria Silva", "documento": "529.982.247-25",
        "cep": "01310-100", "logradouro": "Avenida Paulista", "numero": "1000",
        "bairro": "Bela Vista", "cidade": "São Paulo", "uf": "SP", "chave_loja": chave,
    }


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteRede(BaseNuvem):
    def setUp(self):
        super().setUp()
        from backend import grupos
        self.grupos = grupos
        self.addCleanup(self._limpar)

    def _limpar(self):
        painel.tentativas.acertou("REDE-TESTE")
        painel.tentativas.acertou("REDE-BLOQUEIO")
        db = nuvem.SessionLocal()
        try:
            from backend import cobranca_mercadopago as cobranca
            for modelo in (cobranca.Pagamento, cobranca.Evento, cobranca.Cobranca, cobranca.Plano):
                db.query(modelo).delete()
            db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja.in_(["ADEGA-1", "ADEGA-2", "LOJA-FORA"])).update(
                {"grupo_id": None}, synchronize_session=False)
            db.query(nuvem.Loja).filter_by(chave_loja="LOJA-FORA").delete()
            db.query(grupos_modelo()).delete()
            db.commit()
        finally:
            db.close()

    def _criar(self, chave="REDE-TESTE", senha="temporaria-1"):
        r = self.http.post("/v1/admin/grupos", json={
            "nome": "Rede teste", "chave": chave, "senha": senha, "temporaria": True,
        }, headers=ADMIN)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["link"], f"/painel/?grupo={chave}")
        self.assertTrue(r.json()["deve_trocar_senha"])
        return r.json()

    def _entrar(self, chave="REDE-TESTE", senha="temporaria-1"):
        r = self.http.post("/v1/painel/login", json={"loja": chave, "senha": senha})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json(), {"Authorization": "Bearer " + r.json()["token"]}

    def test_login_de_loja_continua_e_a_rede_nao_ve_loja_de_fora(self):
        self._criar()
        r = self.http.post("/v1/admin/grupos/REDE-TESTE/lojas", json={"chave_loja": "ADEGA-1"}, headers=ADMIN)
        self.assertEqual(r.status_code, 200, r.text)
        self.http.post("/v1/painel/envio", json={"vendas": [{
            "uuid": "rede-dentro", "status": "fechada", "dia": "2026-10-03", "total_cent": 2400,
            "desconto_cent": 0, "modalidade": "balcao",
            "pagamentos": [{"tipo": "Pix", "valor_cent": 2400, "troco_cent": 0}],
            "itens": [{"nome": "SKOL", "quantidade": 2, "total_cent": 2400, "cancelado": 0,
                       "custo_linha_cent": 1000}],
        }]}, headers=cabecalho("ADEGA-1"))
        self.http.post("/v1/painel/envio", json={"vendas": [{
            "uuid": "rede-fora", "status": "fechada", "dia": "2026-10-03", "total_cent": 5000,
            "desconto_cent": 0, "modalidade": "balcao",
            "pagamentos": [{"tipo": "Dinheiro", "valor_cent": 5000, "troco_cent": 0}],
            "itens": [{"nome": "GELO", "quantidade": 1, "total_cent": 5000, "cancelado": 0,
                       "custo_linha_cent": 2000}],
        }]}, headers=cabecalho("ADEGA-2"))
        corpo, sessao = self._entrar()
        self.assertTrue(corpo["deve_trocar_senha"])
        self.assertEqual(self.http.get("/v1/painel/rede", params={"de": "2026-10-03", "ate": "2026-10-03"},
                                       headers=sessao).status_code, 403)
        troca = self.http.post("/v1/painel/grupo/senha", json={
            "senha_atual": "temporaria-1", "senha_nova": "senha-da-rede-1"}, headers=sessao)
        self.assertEqual(troca.status_code, 200, troca.text)
        rede = self.http.get("/v1/painel/rede", params={"de": "2026-10-03", "ate": "2026-10-03"}, headers=sessao)
        self.assertEqual(rede.status_code, 200, rede.text)
        self.assertEqual(rede.json()["faturamento_cent"], 2400)
        self.assertEqual(rede.json()["lucro_cent"], 1400)
        self.assertEqual([loja["chave"] for loja in rede.json()["lojas"]], ["ADEGA-1"])
        self.assertEqual(self.http.post("/v1/painel/grupo/entrar", json={"loja": "ADEGA-2"},
                                       headers=sessao).status_code, 404)
        dentro = self.http.post("/v1/painel/grupo/entrar", json={"loja": "ADEGA-1"}, headers=sessao)
        self.assertEqual(dentro.status_code, 200, dentro.text)
        loja = {"Authorization": "Bearer " + dentro.json()["token"]}
        self.assertEqual(self.http.get("/v1/painel/resumo", headers=loja).status_code, 200)
        self.assertEqual(self.http.post("/v1/painel/login", json={
            "loja": "ADEGA-1", "senha": "senha-forte-1"}).status_code, 401)
        painel.definir_senha(nuvem.SessionLocal(), "ADEGA-1", "senha-forte-1")
        self.assertEqual(self.http.post("/v1/painel/login", json={
            "loja": "ADEGA-1", "senha": "senha-forte-1"}).status_code, 200)
        self.http.post("/v1/admin/grupos/REDE-TESTE/lojas", json={"chave_loja": "ADEGA-2"}, headers=ADMIN)
        soma = self.http.get("/v1/painel/rede", params={"de": "2026-10-03", "ate": "2026-10-03"}, headers=sessao)
        self.assertEqual(soma.json()["faturamento_cent"], 7400)
        self.assertEqual(sorted(loja["chave"] for loja in soma.json()["por_loja"]), ["ADEGA-1", "ADEGA-2"])
        self.assertEqual(self.http.post("/v1/painel/login", json={"loja": str(corpo["grupo"]["id"]),
                                                                 "senha": "senha-da-rede-1"}).status_code, 200)

    def test_muitas_tentativas_bloqueiam_o_login_da_rede(self):
        self._criar("REDE-BLOQUEIO", "temporaria-9")
        for _ in range(painel.TENTATIVAS_LOGIN):
            self.assertEqual(self.http.post("/v1/painel/login", json={
                "loja": "REDE-BLOQUEIO", "senha": "errada"}).status_code, 401)
        self.assertEqual(self.http.post("/v1/painel/login", json={
            "loja": "REDE-BLOQUEIO", "senha": "temporaria-9"}).status_code, 429)

    def test_pagamento_da_rede_renova_todas_as_lojas_e_a_loja_fora_fica(self):
        from backend import cobranca_mercadopago as cobranca
        self._criar()
        self.http.post("/v1/admin/grupos/REDE-TESTE/lojas", json={"chave_loja": "ADEGA-1"}, headers=ADMIN)
        self.http.post("/v1/admin/grupos/REDE-TESTE/lojas", json={"chave_loja": "ADEGA-2"}, headers=ADMIN)
        db = nuvem.SessionLocal()
        db.add(nuvem.Loja(chave_loja="LOJA-FORA", nome="Fora", token_hash=nuvem.hash_token("token-fora"), ativa=True))
        db.commit()
        pedido = _pedido_rede("REDE-TESTE")
        r = self.http.post("/v1/admin/grupos/REDE-TESTE/assinatura", json=pedido, headers=ADMIN)
        self.assertEqual(r.status_code, 200, r.text)
        plano = db.query(cobranca.Plano).filter_by(chave_loja="REDE-TESTE").one()
        self.assertEqual(plano.grupo_id, db.query(self.grupos.Grupo).filter_by(chave="REDE-TESTE").one().id)
        db.add(cobranca.Cobranca(
            id="cob-rede", plano=plano.id, chave_loja="REDE-TESTE", chave_vencimento="REDE-TESTE:2026-10-10",
            valor_cent=10000, vencimento="2026-10-10", status="pendente", criada_em=cobranca.agora(),
            consultada_em=cobranca.agora()))
        db.add(cobranca.Pagamento(
            id="pag-rede", cobranca="cob-rede", status="approved", valor_cent=10000,
            licenca_ate="2026-11-10", consultado_em=cobranca.agora()))
        db.commit()
        cobranca.recalcular(db, plano)
        db.commit()
        datas = {loja.chave_loja: loja.licenca_ate for loja in db.query(nuvem.Loja).all()}
        self.assertEqual(datas["ADEGA-1"], "2026-11-10")
        self.assertEqual(datas["ADEGA-2"], "2026-11-10")
        self.assertIsNone(datas["LOJA-FORA"])
        proprio = cobranca.definir_assinatura_de_pedido(db, _pedido_rede("ADEGA-1"))
        self.assertEqual(proprio, "criada")
        chamadas = []
        with mock.patch.object(cobranca, "requisitar", side_effect=lambda *a, **k: chamadas.append(a)):
            self.assertEqual(cobranca.gerar_recorrencias(db, date(2026, 10, 5), "ADEGA-1"), 0)
        self.assertEqual(chamadas, [])
        db.close()


def grupos_modelo():
    from backend.grupos import Grupo
    return Grupo
