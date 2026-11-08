"""Pedido online pelo cardápio (só Will Adega): o cliente pede no celular, a nuvem guarda e o caixa aceita ou recusa."""
from __future__ import annotations

import os
import unittest
from datetime import datetime
from unittest import mock
from urllib.parse import unquote

from src.controllers.config_controller import ConfigController
from src.controllers.entrega_controller import EntregaController
from src.controllers.pedido_online_controller import PedidoOnlineController, detalhe, resumo
from src.controllers.perfil_controller import PerfilController
from src.core.erros import ErroEstoqueInsuficiente, ErroNegocio, ErroValidacao
from tests.test_caixa import BaseCaixa
from tests.test_painel_dono import TOKENS, TestClient, cabecalho, nuvem, preparar_lojas


class _Http:
    """O TestClient não aceita `timeout` (o requests do caixa usa)."""

    def __init__(self, http):
        self.http = http

    def post(self, url, json=None, headers=None, timeout=None):
        return self.http.post(url, json=json, headers=headers)

    def get(self, url, headers=None, timeout=None):
        return self.http.get(url, headers=headers)


class BasePedido(BaseCaixa):
    def setUp(self):
        super().setUp()
        edicao = mock.patch.dict(os.environ, {"PDV_EDICAO": "willadega"})
        edicao.start()
        self.addCleanup(edicao.stop)
        PerfilController(self.banco, self.adm).aplicar("adega")
        self.centro = self.banco.inserir("bairros", {"nome": "Centro", "taxa_cent": 500})
        self.banco.cfg_set("taxa_entrega_padrao", "8,00")
        for chave, valor in (("pedido_online", "S"), ("pedido_online_whatsapp", "(11) 98765-4321"),
                             ("cardapio_digital", "S"), ("usar_delivery", "S")):
            self.banco.cfg_set(chave, valor)
        self.cod_skol = str(int(self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (self.skol,))))
        self.cod_agua = str(int(self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (self.agua,))))
        self.ctrl = PedidoOnlineController(self.banco, self.caixa, EntregaController(self.banco, self.caixa), self.prod,
                                           self.adm)

    def pedido(self, **extra):
        base = {"numero": 7, "nome": "JOAO", "telefone": "11912345678", "retirada": False, "endereco": "Rua A, 10",
                "bairro": "Centro", "pagamento": "dinheiro", "troco_para_cent": 10000, "observacao": "bem gelada",
                "itens": [{"codigo": self.cod_skol, "nome": "SKOL", "qtd": 6}, {"codigo": self.cod_agua, "nome": "AGUA",
                                                                               "qtd": 1}], "total_cent": 5650}
        return {**base, **extra}


class TesteImportarNoCaixa(BasePedido):
    def test_vira_entrega_com_preco_do_caixa_taxa_do_bairro_troco_e_recado(self):
        r = self.ctrl.importar(self.pedido())
        v = self.caixa.obter(r["venda_id"])
        self.assertEqual((v["modalidade"], v["taxa_cent"], v["troco_para_cent"]), ("entrega", 500, 10000))
        self.assertEqual(v["mensagem"], "Pedido online #7 · Dinheiro · bem gelada")
        itens = {i["produto_id"]: i["quantidade"] for i in self.caixa.itens(r["venda_id"])}
        self.assertEqual(itens, {self.skol: 6, self.agua: 1})
        cli = self.banco.um("SELECT nome, telefone, endereco, bairro_id FROM clientes WHERE id = ?", (v["cliente_id"],))
        self.assertEqual(tuple(cli), ("JOAO", "11912345678", "Rua A, 10", self.centro))
        self.assertEqual(self.ctrl.importar(self.pedido())["venda_id"], r["venda_id"])    # de novo: a mesma entrega
        self.assertTrue(self.ctrl.importar(self.pedido())["ja_existia"])

    def test_cliente_achado_pelo_telefone_retirada_sem_taxa_e_produto_fora(self):
        joao = self.cliente("JOAO")
        self.banco.executar("UPDATE clientes SET telefone = '(11) 91234-5678' WHERE id = ?", (joao,))
        r = self.ctrl.importar(self.pedido(numero=8, retirada=True, pagamento="pix"))
        v = self.caixa.obter(r["venda_id"])
        self.assertEqual((v["cliente_id"], v["taxa_cent"], v["forma_online"]), (joao, 0, "pix"))
        self.assertIn("RETIRA NA LOJA · Pix na entrega", v["mensagem"])
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM clientes"), 1)
        self.banco.executar("UPDATE produtos SET ativo = 0 WHERE id = ?", (self.agua,))
        with self.assertRaisesRegex(ErroNegocio, "AGUA"):
            self.ctrl.importar(self.pedido(numero=9))
        self.assertIsNone(self.ctrl.ja_importado(9))

    def test_numero_1_nao_casa_com_o_10(self):
        dez = self.ctrl.importar(self.pedido(numero=10))
        self.assertIsNone(self.ctrl.ja_importado(1))
        self.assertEqual(self.ctrl.ja_importado(10), dez["venda_id"])
        um = self.ctrl.importar(self.pedido(numero=1))
        self.assertNotEqual(um["venda_id"], dez["venda_id"])
        self.assertFalse(um["ja_existia"])
        self.assertEqual(self.ctrl.ja_importado(1), um["venda_id"])

    def test_telefone_exige_o_numero_inteiro(self):
        joao = self.cliente("JOAO")
        self.banco.executar("UPDATE clientes SET telefone = '11912345678' WHERE id = ?", (joao,))
        r = self.ctrl.importar(self.pedido(numero=11, telefone="21912345678", endereco="Outra rua, 20"))
        self.assertNotEqual(self.caixa.obter(r["venda_id"])["cliente_id"], joao)
        endereco = "Rua das Flores, " + ("1234 " * 30)
        r = self.ctrl.importar(self.pedido(numero=12, telefone="21912345678", endereco=endereco))
        cli = self.banco.valor("SELECT endereco FROM clientes WHERE id = ?", (self.caixa.obter(r["venda_id"])["cliente_id"],))
        self.assertEqual(len(cli), 160)
        self.assertTrue(cli.startswith("Rua das Flores"))

    def test_reserva_estoque_recusa_sem_saldo_e_nao_baixa_duas_vezes(self):
        self.banco.executar("UPDATE produtos SET qt_atual = 2 WHERE id = ?", (self.skol,))
        item = [{"codigo": self.cod_skol, "nome": "SKOL", "qtd": 6}]
        with self.assertRaises(ErroEstoqueInsuficiente):
            self.ctrl.importar(self.pedido(numero=3, itens=item))
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 2)
        r = self.ctrl.importar(self.pedido(numero=4, itens=[{"codigo": self.cod_skol, "nome": "SKOL", "qtd": 2}]))
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 0)
        self.caixa.cancelar_venda(r["venda_id"], "cliente desistiu")
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 2)
        self.assertEqual(self.banco.valor("SELECT pedido_online_aviso FROM vendas WHERE id = ?", (r["venda_id"],)), None)
        self.banco.executar("UPDATE produtos SET qt_atual = 5 WHERE id = ?", (self.skol,))
        r = self.ctrl.importar(self.pedido(numero=5, itens=[{"codigo": self.cod_skol, "nome": "SKOL", "qtd": 2}], id=50))
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 3)
        self.pagar(r["venda_id"], "Dinheiro", self.caixa.obter(r["venda_id"])["total_cent"])
        self.caixa.fechar(r["venda_id"])
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 3)
        aviso = self.banco.um("SELECT pedido_online_aviso, pedido_online_aviso_ok FROM vendas WHERE id = ?", (r["venda_id"],))
        self.assertEqual((aviso["pedido_online_aviso"], aviso["pedido_online_aviso_ok"]), ("entregue", 0))

    def test_gelada_entra_com_o_preco_gelado(self):
        self.banco.executar("UPDATE produtos SET preco_gelada_cent = 1000 WHERE id = ?", (self.skol,))
        r = self.ctrl.importar(self.pedido(
            numero=13, itens=[{"codigo": self.cod_skol, "nome": "SKOL", "qtd": 1, "temperatura": "gelada"}]))
        item = self.caixa.itens(r["venda_id"])[0]
        self.assertEqual((item["temperatura"], item["preco_unit_cent"]), ("gelada", 1000))

    def test_sem_nada_a_venda_ou_desligado_recusa(self):
        self.banco.executar("UPDATE produtos SET ativo = 0")
        with self.assertRaisesRegex(ErroNegocio, "Não aceito"):
            self.ctrl.importar(self.pedido(numero=9))
        self.banco.cfg_set("pedido_online", "N")
        with self.assertRaisesRegex(ErroNegocio, "desligado"):
            self.ctrl.importar(self.pedido(numero=10))

    def test_textos_da_lista(self):
        self.assertEqual(resumo(self.pedido()), "#7 · JOAO · Centro · 7 itens · R$ 56,50")
        texto = detalhe(self.pedido())
        self.assertIn("6x SKOL", texto)
        self.assertIn("Dinheiro (troco para R$ 100,00)", texto)
        self.assertIn("Obs.: bem gelada", texto)


class TesteConfiguracao(BasePedido):
    def test_ligar_exige_whatsapp_delivery_e_cardapio(self):
        cfg = ConfigController(self.banco)
        with self.assertRaisesRegex(ErroValidacao, "WhatsApp"):
            cfg.salvar_config({"pedido_online_whatsapp": "123"})
        with self.assertRaisesRegex(ErroValidacao, "Delivery"):
            cfg.salvar_config({"usar_delivery": "N"})
        with self.assertRaisesRegex(ErroValidacao, "Cardápio"):
            cfg.salvar_config({"cardapio_digital": "N"})
        self.assertEqual(self.banco.cfg("usar_delivery"), "S")             # o salvamento foi desfeito
        cfg.salvar_config({"pedido_online": "N", "usar_delivery": "N"})    # desligado: tudo livre

    def test_opcoes_so_aparecem_no_will_adega(self):
        from src.core import edicao
        self.assertTrue(edicao.CHAVES_PEDIDO_ONLINE <= edicao.EDICOES["willpdv"].fora_das_configuracoes())
        self.assertFalse(edicao.CHAVES_PEDIDO_ONLINE & edicao.EDICOES["willadega"].fora_das_configuracoes())

    def test_envio_so_leva_o_pedido_no_will_adega(self):
        from src.sync.cardapio_envio import coletar
        corpo = coletar(self.banco)
        self.assertEqual(corpo["edicao"], "willadega")
        self.assertEqual(corpo["pedido"]["whatsapp"], "5511987654321")
        self.assertEqual((corpo["pedido"]["taxa_padrao_cent"], corpo["pedido"]["bairros"]),
                         (800, [{"nome": "Centro", "taxa_cent": 500}]))
        self.assertEqual({p["codigo"] for p in corpo["produtos"]}, {self.cod_skol, self.cod_agua})
        with mock.patch.dict(os.environ, {"PDV_EDICAO": "willpdv"}):
            self.assertEqual(coletar(self.banco)["pedido"], {"ligado": False})


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TesteNuvemPedido(BasePedido):
    def setUp(self):
        super().setUp()
        preparar_lojas()
        from backend.pedido_online import PedidoOnline, PedidoOnlineConfig
        db = nuvem.SessionLocal()
        try:
            db.query(PedidoOnline).delete()
            db.query(PedidoOnlineConfig).delete()
            db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja.in_(["ADEGA-1", "ADEGA-2"])).update(
                {"edicao": "willadega"}, synchronize_session=False)
            db.commit()
        finally:
            db.close()
        self.http = TestClient(nuvem.app)
        self.banco.cfg_set("api_url", "http://testserver/v1/sincronizar")
        self.banco.cfg_set("api_token", TOKENS["ADEGA-1"])
        from src.sync import cardapio_envio
        cardapio_envio.enviar(self.banco, _Http(self.http))

    def cardapio(self):
        with mock.patch("backend.cardapio.agora_local", return_value=datetime(2026, 11, 8, 15, 0)):
            return self.http.get("/v1/cardapio", params={"loja": "ADEGA-1"}).json()

    def pedir(self, **extra):
        corpo = {"loja": "ADEGA-1", "nome": "Maria", "telefone": "(11) 95555-0000", "endereco": "Rua B, 20",
                 "bairro": "centro", "pagamento": "dinheiro", "troco_para_cent": 10000,
                 "itens": [{"codigo": self.cod_skol, "qtd": 3}, {"codigo": self.cod_skol, "qtd": 3},
                           {"codigo": self.cod_agua, "qtd": 1}], **extra}
        return self.http.post("/v1/cardapio/pedido", json=corpo)

    def test_do_cardapio_ao_caixa(self):
        dados = self.cardapio()
        self.assertEqual(dados["pedido"]["bairros"], [{"nome": "Centro", "taxa_cent": 500}])
        self.assertNotIn("whatsapp", dados["pedido"])                       # o número só sai no link do pedido
        produtos = {p["nome"]: p["codigo"] for g in dados["grupos"] for s in g["subgrupos"] for p in s["produtos"]}
        self.assertEqual(produtos, {"SKOL": self.cod_skol, "AGUA": self.cod_agua})
        r = self.pedir()
        self.assertEqual(r.status_code, 200, r.text)
        corpo = r.json()
        self.assertEqual((corpo["numero"], corpo["total_cent"]), (1, 6 * 800 + 350 + 500))
        self.assertTrue(corpo["whatsapp_url"].startswith("https://wa.me/5511987654321?text="))
        texto = unquote(corpo["whatsapp_url"].split("text=", 1)[1])
        self.assertIn("*Pedido #1*", texto)
        self.assertIn("6x SKOL - R$ 48,00", texto)
        self.assertIn("Entrega: Rua B, 20 - Centro", texto)
        self.assertIn("Dinheiro (troco para R$ 100,00)", texto)
        from src.sync import pedidos_online
        novos = pedidos_online.novos(self.banco, _Http(self.http))
        self.assertEqual([(p["numero"], p["nome"], p["telefone"]) for p in novos], [(1, "Maria", "11955550000")])
        r = self.ctrl.importar(novos[0])
        pedidos_online.aceitar(self.banco, novos[0]["id"], _Http(self.http))
        pedidos_online.aceitar(self.banco, novos[0]["id"], _Http(self.http))   # repetir não quebra
        self.assertEqual(pedidos_online.novos(self.banco, _Http(self.http)), [])
        self.assertEqual(self.caixa.obter(r["venda_id"])["total_cent"], 6 * 800 + 350 + 500)
        situacao = self.http.get("/v1/cardapio/pedido", params={"loja": "ADEGA-1", "numero": 1,
                                                                  "telefone": "11955550000"}).json()
        self.assertEqual(situacao["situacao"], "aceito")
        with self.assertRaisesRegex(RuntimeError, "já foi aceito"):
            pedidos_online.recusar(self.banco, novos[0]["id"], "acabou", _Http(self.http))

    def test_recusar_com_motivo_e_cliente_ve(self):
        self.pedir()
        from src.sync import pedidos_online
        p = pedidos_online.novos(self.banco, _Http(self.http))[0]
        with self.assertRaisesRegex(RuntimeError, "motivo"):
            pedidos_online.recusar(self.banco, p["id"], "", _Http(self.http))
        pedidos_online.recusar(self.banco, p["id"], "Acabou a Skol", _Http(self.http))
        r = self.http.get("/v1/cardapio/pedido", params={"loja": "ADEGA-1", "numero": 1, "telefone": "11955550000"})
        self.assertEqual((r.json()["situacao"], r.json()["motivo"]), ("recusado", "Acabou a Skol"))
        outra = self.http.post("/v1/pedidos-online/%d/aceitar" % p["id"], headers=cabecalho("ADEGA-2"))
        self.assertEqual(outra.status_code, 404)                              # outra loja não mexe

    def test_validacoes_e_limites(self):
        for extra, trecho in (({"telefone": "123"}, "telefone"), ({"itens": []}, "vazio"),
                              ({"itens": [{"codigo": "999999", "qtd": 1}]}, "saiu do cardápio"),
                              ({"itens": [{"codigo": self.cod_skol, "qtd": 0}]}, "Quantidade"),
                              ({"pagamento": "cheque"}, "pagamento"), ({"endereco": ""}, "endereço"),
                              ({"troco_para_cent": 100}, "troco")):
            r = self.pedir(**extra)
            self.assertEqual(r.status_code, 422, extra)
            self.assertIn(trecho, r.json()["detail"])
        self.banco.cfg_set("pedido_online_minimo", "100,00")
        from src.sync import cardapio_envio
        cardapio_envio.enviar(self.banco, _Http(self.http))
        self.assertIn("mínimo", self.pedir().json()["detail"])
        self.banco.cfg_set("pedido_online_minimo", "0")
        cardapio_envio.enviar(self.banco, _Http(self.http))
        retirada = self.pedir(retirada=True, endereco="", pagamento="pix").json()
        self.assertEqual(retirada["total_cent"], 6 * 800 + 350)
        self.assertIn("Retirar na loja", unquote(retirada["whatsapp_url"]))
        self.assertEqual(self.pedir().status_code, 200)
        self.assertEqual(self.pedir().status_code, 200)
        self.assertEqual(self.pedir().status_code, 429)                      # 3 aguardando do mesmo telefone

    def test_boate_e_cadastro_de_outra_edicao_ficam_so_consulta(self):
        from src.sync import cardapio_envio
        with mock.patch.dict(os.environ, {"PDV_EDICAO": "willpdv"}):
            cardapio_envio.enviar(self.banco, _Http(self.http))
        self.assertIsNone(self.cardapio()["pedido"])
        self.assertEqual(self.pedir().status_code, 404)
        cardapio_envio.enviar(self.banco, _Http(self.http))
        self.assertIsNotNone(self.cardapio()["pedido"])
        db = nuvem.SessionLocal()
        try:
            loja = db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja == "ADEGA-1").first()
            loja.edicao = "willpdv"
            db.commit()
        finally:
            db.close()
        self.assertIsNone(self.cardapio()["pedido"])
        self.assertEqual(self.pedir().status_code, 404)
        self.assertEqual(self.http.get("/v1/pedidos-online", headers=cabecalho("ADEGA-1")).status_code, 403)
        self.assertEqual(self.http.get("/v1/pedidos-online").status_code, 401)

    def test_edicao_vazia_nao_liga_mesmo_que_o_envio_diga_adega(self):
        db = nuvem.SessionLocal()
        try:
            db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja == "ADEGA-1").update(
                {"edicao": None}, synchronize_session=False)
            db.commit()
        finally:
            db.close()
        r = self.http.post("/v1/cardapio/envio", json={
            "loja_nome": "Adega", "produtos": [], "edicao": "willadega",
            "pedido": {"ligado": True, "whatsapp": "5511987654321", "minimo_cent": 0,
                       "taxa_padrao_cent": 0, "retirada": True, "bairros": []},
        }, headers=cabecalho("ADEGA-1"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["pedido_online"])
        self.assertIsNone(self.cardapio()["pedido"])
        self.assertEqual(self.pedir().status_code, 404)

    def test_cliente_ve_saiu_entregue_e_cancelado(self):
        self.pedir()
        from src.sync import pedidos_online
        p = pedidos_online.novos(self.banco, _Http(self.http))[0]
        pedidos_online.aceitar(self.banco, p["id"], _Http(self.http))
        pedidos_online.atualizar_situacao(self.banco, p["id"], "saiu", http=_Http(self.http))
        visto = self.http.get("/v1/cardapio/pedido", params={"loja": "ADEGA-1", "numero": 1, "telefone": "11955550000"})
        self.assertEqual(visto.json()["situacao"], "saiu")
        pedidos_online.atualizar_situacao(self.banco, p["id"], "entregue", http=_Http(self.http))
        visto = self.http.get("/v1/cardapio/pedido", params={"loja": "ADEGA-1", "numero": 1, "telefone": "11955550000"})
        self.assertEqual(visto.json()["situacao"], "entregue")
        self.pedir(telefone="11955550001")
        outro = pedidos_online.novos(self.banco, _Http(self.http))[0]
        pedidos_online.aceitar(self.banco, outro["id"], _Http(self.http))
        pedidos_online.atualizar_situacao(self.banco, outro["id"], "cancelado", "cliente desistiu", _Http(self.http))
        visto = self.http.get("/v1/cardapio/pedido", params={"loja": "ADEGA-1", "numero": 2,
                                                              "telefone": "11955550001"})
        self.assertEqual((visto.json()["situacao"], visto.json()["motivo"]), ("cancelado", "cliente desistiu"))

    def test_bairro_desconhecido_avisa_e_numero_colidido_repete(self):
        r = self.pedir(bairro="Lugar Nenhum")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("Bairro não cadastrado", r.json()["aviso"])
        self.assertIn("Bairro não cadastrado", unquote(r.json()["whatsapp_url"]))
        self.banco.executar("UPDATE produtos SET preco_gelada_cent = 900, aceita_decimal = 1 WHERE id = ?", (self.skol,))
        from src.sync import cardapio_envio
        cardapio_envio.enviar(self.banco, _Http(self.http))
        gelada = self.pedir(telefone="11970000001", retirada=True, endereco="", pagamento="pix",
                            itens=[{"codigo": self.cod_skol, "qtd": 1, "temperatura": "gelada"}])
        self.assertEqual(gelada.status_code, 200, gelada.text)
        self.assertEqual(gelada.json()["total_cent"], 900)
        fracao = self.pedir(telefone="11970000002", retirada=True, endereco="", pagamento="pix",
                            itens=[{"codigo": self.cod_skol, "qtd": 1.5}])
        self.assertEqual(fracao.status_code, 200, fracao.text)
        self.assertEqual(fracao.json()["total_cent"], 1200)
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import Session
        real = Session.commit
        vezes = {"n": 0}

        def commit(sessao):
            vezes["n"] += 1
            if vezes["n"] == 1:
                raise IntegrityError("INSERT", {}, Exception("ux_pedido_online_numero"))
            return real(sessao)

        with mock.patch.object(Session, "commit", commit):
            de_novo = self.pedir(telefone="11955550009")
        self.assertEqual(de_novo.status_code, 200, de_novo.text)
        self.assertGreaterEqual(vezes["n"], 2)

    def test_loja_sem_edicao_que_ja_recebia_pedido_e_marcada_adega(self):
        import json
        from backend.pedido_online import PedidoOnlineConfig, marcar_lojas_adega
        db = nuvem.SessionLocal()
        try:
            db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja == "ADEGA-2").update(
                {"edicao": None}, synchronize_session=False)
            db.add(PedidoOnlineConfig(chave_loja="ADEGA-2",
                                      dados=json.dumps({"ligado": True, "whatsapp": "5511987654321"}),
                                      atualizado_em="2026-11-08 00:00:00"))
            db.query(nuvem.Loja).filter(nuvem.Loja.chave_loja == "ADEGA-1").update(
                {"edicao": "willpdv"}, synchronize_session=False)
            db.commit()
            marcar_lojas_adega(db)
            db.expire_all()
            self.assertEqual(db.query(nuvem.Loja).filter_by(chave_loja="ADEGA-2").one().edicao, "willadega")
            self.assertEqual(db.query(nuvem.Loja).filter_by(chave_loja="ADEGA-1").one().edicao, "willpdv")
        finally:
            db.close()
