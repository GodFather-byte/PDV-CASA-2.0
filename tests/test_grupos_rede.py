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

    # ----------------------------------------------------------- app da rede (PWA) e mensalidade pela central
    def test_app_da_rede_tem_o_nome_dela_e_abre_no_login_da_rede(self):
        self._criar()
        r = self.http.get("/painel/rede.webmanifest", params={"grupo": "rede-teste"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("manifest+json", r.headers["content-type"])
        m = r.json()
        self.assertEqual((m["name"], m["start_url"], m["scope"], m["display"]),
                         ("Rede teste", "/painel/?grupo=REDE-TESTE", "/painel/", "standalone"))
        self.assertTrue(all(i["src"].startswith("/painel/icones/") for i in m["icons"]))
        # rede que não existe recebe o manifesto comum (não revela quais redes existem)
        comum = self.http.get("/painel/rede.webmanifest", params={"grupo": "NAO-EXISTE"}).json()
        self.assertEqual(comum["start_url"], "/painel/")
        self.assertEqual(self.http.get("/painel/rede.webmanifest").json()["start_url"], "/painel/")

    def test_central_cadastra_a_mensalidade_unica_da_rede(self):
        from backend import central_fornecedor as central
        from backend import cobranca_mercadopago as cobranca
        self._criar()
        for loja in ("ADEGA-1", "ADEGA-2"):
            self.http.post("/v1/admin/grupos/REDE-TESTE/lojas", json={"chave_loja": loja}, headers=ADMIN)
        with central._trava:
            central._tentativas.clear()
        fornecedor = TestClient(nuvem.app, base_url="https://testserver")
        self.addCleanup(fornecedor.close)

        def limpar_central():
            with nuvem.SessionLocal() as db:
                db.query(central.SessaoFornecedor).delete()
                db.query(central.AuditoriaFornecedor).delete()
                db.commit()
        self.addCleanup(limpar_central)
        login = fornecedor.post("/v1/fornecedor/login", json={"credencial": "token-de-teste"},
                                headers={"X-Central-Login": "1"})
        self.assertEqual(login.status_code, 200, login.text)
        csrf = {"X-Central-CSRF": login.json()["csrf"]}
        pedido = _pedido_rede("REDE-TESTE")
        pedido.pop("chave_loja")
        pedido["valor_cent"] = 39900
        sem_motivo = fornecedor.post("/v1/fornecedor/grupos/REDE-TESTE/plano", json={"plano": pedido}, headers=csrf)
        self.assertEqual(sem_motivo.status_code, 422)
        with mock.patch.object(cobranca, "gerar_recorrencias", return_value=0):
            r = fornecedor.post("/v1/fornecedor/grupos/REDE-TESTE/plano",
                                json={"plano": pedido, "motivo": "Contrato das 4 lojas"}, headers=csrf)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["situacao"], "criada")
        self.assertEqual(r.json()["plano"]["valor_cent"], 39900)
        self.assertEqual(r.json()["plano"]["dia_vencimento"], 10)
        lista = fornecedor.get("/v1/fornecedor/grupos").json()["grupos"]
        self.assertEqual(lista[0]["plano"]["valor_cent"], 39900)
        db = nuvem.SessionLocal()
        try:
            plano = db.query(cobranca.Plano).filter_by(chave_loja="REDE-TESTE").one()
            self.assertIsNotNone(plano.grupo_id)
            acoes = [a.acao for a in db.query(central.AuditoriaFornecedor).all()]
            self.assertIn("rede_plano", acoes)
        finally:
            db.close()
        # dado errado volta como erro de campo, sem gravar nada
        pedido["uf"] = "SAO"
        with mock.patch.object(cobranca, "gerar_recorrencias", return_value=0):
            r = fornecedor.post("/v1/fornecedor/grupos/REDE-TESTE/plano",
                                json={"plano": pedido, "motivo": "Teste"}, headers=csrf)
        self.assertEqual(r.status_code, 422)
        self.assertIn("UF", r.json()["detail"])


def grupos_modelo():
    from backend.grupos import Grupo
    return Grupo
