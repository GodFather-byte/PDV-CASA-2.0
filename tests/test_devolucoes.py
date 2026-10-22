"""Devolução parcial/total de venda fechada (docs/DEVOLUCOES.md)."""
from __future__ import annotations

import os
import sqlite3
import uuid as _uuid

from src.controllers.devolucoes_controller import DevolucoesController, ratear
from src.core.erros import ErroNegocio, ErroPermissao
from src.database import esquema
from src.database.conexao import BancoDados
from tests.test_caixa import BaseCaixa


def novo_uuid() -> str:
    return str(_uuid.uuid4())


class BaseDevolucao(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("usar_desconto", "S")
        self.dev = DevolucoesController(self.banco, self.adm, caixa=self.caixa)

    def fechada(self, *itens, desconto=None, forma="Dinheiro", mesa=None, servico=None):
        vid = self.vender(*itens, mesa=mesa)
        if desconto is not None:
            self.caixa.definir_desconto(vid, valor_cent=desconto)
        if servico is not None:
            self.caixa.definir_servico(vid, servico)
        total = self.caixa.recalcular(vid)["total"]
        tp = self.tipo(forma)
        total += self.caixa.acrescimo_da_forma(vid, tp)
        self.caixa.adicionar_pagamento(vid, tp, total)
        self.caixa.fechar(vid)
        return vid

    def item(self, vid, n=0):
        return self.caixa.itens(vid)[n]["id"]

    def devolver(self, vid, selecao, modo="dinheiro_gaveta", **kw):
        kw.setdefault("uuid", novo_uuid())
        kw.setdefault("motivo", "cliente desistiu")
        kw.setdefault("autorizado_por", self.adm)
        return self.caixa.devolver(vid, selecao, kw.pop("motivo"), kw.pop("autorizado_por"), modo, kw.pop("uuid"), **kw)

    def qt(self, pid):
        return self.prod.por_id(pid)["qt_atual"]


class TesteRateio(BaseDevolucao):
    def test_ratear_soma_exata_e_deterministica(self):
        r = ratear(100, [("a", 1), ("b", 1), ("c", 1)])
        self.assertEqual(r, {"a": 34, "b": 33, "c": 33})
        self.assertEqual(ratear(7, [("a", 0), ("b", 0)]), {"a": 4, "b": 3})
        self.assertEqual(sum(ratear(999, [(i, i * 37 % 11 + 1) for i in range(9)]).values()), 999)

    def test_parciais_com_desconto_somam_o_total_pago(self):
        vid = self.fechada((self.skol, 3), (self.agua, 1), desconto=101)   # 2400 + 350 - 101 = 2649
        total = self.caixa.obter(vid)["total_cent"]
        s, a = self.item(vid, 0), self.item(vid, 1)
        valores = [self.devolver(vid, [{"item_id": s, "quantidade": 1}])["valor_cent"] for _ in range(3)]
        valores.append(self.devolver(vid, [{"item_id": a, "quantidade": 1}])["valor_cent"])
        self.assertEqual(sum(valores), total)
        self.assertTrue(self.dev.da_venda(vid)[-1]["completa"])
        with self.assertRaisesRegex(ErroNegocio, "restam"):
            self.devolver(vid, [{"item_id": a, "quantidade": 1}])

    def test_fracao_quatro_casas(self):
        self.banco.executar("UPDATE produtos SET aceita_decimal = 1 WHERE id = ?", (self.skol,))
        vid = self.fechada((self.skol, 1.5))                               # 1200
        s = self.item(vid)
        d1 = self.devolver(vid, [{"item_id": s, "quantidade": "0,3333"}])
        d2 = self.devolver(vid, [{"item_id": s, "quantidade": 1.1667}])
        self.assertEqual(d1["valor_cent"] + d2["valor_cent"], 1200)
        with self.assertRaisesRegex(ErroNegocio, "4 casas"):
            self.dev.previa(vid, [{"item_id": s, "quantidade": "0.00001"}])
        for ruim in ("nan", "inf", "-1", "abc"):
            with self.assertRaises(ErroNegocio):
                self.dev.previa(vid, [{"item_id": s, "quantidade": ruim}])

    def test_servico_e_acrescimo_explicitos(self):
        vid = self.fechada((self.skol, 2), (self.agua, 2), mesa=3, forma="Cartão Crédito")
        v = self.caixa.obter(vid)
        self.assertEqual((v["servico_cent"], v["acrescimo_cent"]), (230, 500))
        sit = self.dev.situacao(vid)
        self.assertEqual(sit["extras_cent"], 500)
        sel = [{"item_id": i["item_id"], "quantidade": i["quantidade"]} for i in sit["itens"]]
        p = self.dev.previa(vid, sel, reembolsar_extras=False)
        self.assertEqual((p["servico_rateado_cent"], p["extras_cent"], p["valor_cent"]), (230, 0, 2530))
        p = self.dev.previa(vid, sel)
        self.assertEqual(p["valor_cent"], v["total_cent"])
        d = self.devolver(vid, sel, "externo", tipo_pagamento_id=self.tipo("Cartão Crédito"), referencia_externa="NSU 123")
        self.assertEqual((d["extras_cent"], d["valor_cent"]), (500, v["total_cent"]))
        self.assertEqual(self.caixa.obter(vid)["total_cent"], v["total_cent"])         # venda original intacta


class TesteGravacao(BaseDevolucao):
    def test_gaveta_cria_saida_e_estoque_opcional(self):
        vid = self.fechada((self.skol, 3))
        self.assertEqual(self.qt(self.skol), 97)
        s = self.item(vid)
        d = self.devolver(vid, [{"item_id": s, "quantidade": 1, "retorna_estoque": True}])
        self.assertEqual(self.qt(self.skol), 98)
        mov = self.banco.um("SELECT * FROM movimentos_caixa WHERE id = ?", (d["movimento_caixa_id"],))
        self.assertEqual((mov["tipo"], mov["valor_cent"]), ("saida", 800))
        self.devolver(vid, [{"item_id": s, "quantidade": 1, "retorna_estoque": False}])
        self.assertEqual(self.qt(self.skol), 98)
        self.assertEqual(self.turnos.resumo(self.turno)["esperado"], 10000 + 2400 - 1600)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM pagamentos_venda WHERE venda_id = ?", (vid,)), 1)

    def test_composicao_volta_insumo_limitado_a_baixa(self):
        whisky = self.novo_produto("WHISKY", 9000, estoque=True, qt=1)
        dose = self.novo_produto("DOSE", 1500)
        self.prod.incluir_composicao(dose, whisky, 0.05)
        vid = self.fechada((dose, 4))
        self.assertAlmostEqual(self.qt(whisky), 0.8)
        d = self.devolver(vid, [{"item_id": self.item(vid), "quantidade": 2, "retorna_estoque": True}])
        self.assertAlmostEqual(self.qt(whisky), 0.9)
        mov = self.banco.todos("SELECT * FROM movimentos_estoque WHERE ref_tipo = 'devolucao_venda' AND ref_id = ?",
                               (d["id"],))
        self.assertEqual([(m["produto_id"], round(m["quantidade"], 4)) for m in mov], [(whisky, 0.1)])

    def test_uuid_repetido_e_idempotente(self):
        vid = self.fechada((self.skol, 2))
        u = novo_uuid()
        d1 = self.devolver(vid, [{"item_id": self.item(vid), "quantidade": 1}], uuid=u)
        d2 = self.devolver(vid, [{"item_id": self.item(vid), "quantidade": 1}], uuid=u)
        self.assertEqual((d1["id"], d1["repetida"], d2["repetida"]), (d2["id"], False, True))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa WHERE tipo = 'saida'"), 1)
        outra = self.fechada((self.agua, 1))
        with self.assertRaisesRegex(ErroNegocio, "outro cupom"):
            self.devolver(outra, [{"item_id": self.item(outra), "quantidade": 1}], uuid=u)
        with self.assertRaisesRegex(ErroNegocio, "inválido"):
            self.devolver(vid, [{"item_id": self.item(vid), "quantidade": 1}], uuid="abc")

    def test_registro_imutavel(self):
        vid = self.fechada((self.skol, 1))
        d = self.devolver(vid, [{"item_id": self.item(vid), "quantidade": 1}])
        for sql in ("UPDATE devolucoes SET valor_cent = 0 WHERE id = ?", "DELETE FROM devolucoes WHERE id = ?",
                    "DELETE FROM devolucoes_itens WHERE devolucao_id = ?"):
            with self.assertRaises(sqlite3.DatabaseError):
                self.banco.executar(sql, (d["id"],))
        self.assertTrue(self.banco.valor(
            "SELECT COUNT(*) FROM auditoria_eventos WHERE entidade = 'devolucoes'"))

    def test_cancelar_venda_com_devolucao_e_bloqueado(self):
        vid = self.fechada((self.skol, 2))
        self.devolver(vid, [{"item_id": self.item(vid), "quantidade": 1}])
        with self.assertRaisesRegex(ErroNegocio, "devolução"):
            self.caixa.cancelar_venda(vid, "teste")
        self.assertEqual(self.caixa.obter(vid)["status"], "fechada")

    def test_venda_cancelada_ou_aberta_nao_devolve(self):
        vid = self.fechada((self.skol, 1))
        s = self.item(vid)
        self.caixa.cancelar_venda(vid, "erro")
        with self.assertRaisesRegex(ErroNegocio, "cancelado"):
            self.devolver(vid, [{"item_id": s, "quantidade": 1}])
        aberta = self.vender((self.agua, 1))
        with self.assertRaisesRegex(ErroNegocio, "FECHADA"):
            self.devolver(aberta, [{"item_id": self.item(aberta), "quantidade": 1}])

    def test_permissao_motivo_e_turno(self):
        vid = self.fechada((self.skol, 2))
        s = self.item(vid)
        caixa0 = self.banco.inserir("operadores", {"nome": "CX", "senha": "x", "nivel": 0, "ativo": 1})
        with self.assertRaises(ErroPermissao):
            self.devolver(vid, [{"item_id": s, "quantidade": 1}], autorizado_por=caixa0)
        with self.assertRaisesRegex(ErroNegocio, "motivo"):
            self.devolver(vid, [{"item_id": s, "quantidade": 1}], motivo="   ")
        sem_op = DevolucoesController(self.banco, None)
        with self.assertRaises(ErroPermissao):
            sem_op.registrar(vid, [{"item_id": s, "quantidade": 1}], "x", self.adm, "dinheiro_gaveta", novo_uuid())
        with self.assertRaises(ErroPermissao):
            sem_op.exigir_acesso()
        self.assertFalse(DevolucoesController(self.banco, caixa0).operador_autoriza())
        self.assertTrue(self.dev.operador_autoriza())
        self.turnos.fechar(self.turno, self.adm, 10000 + 1600)
        with self.assertRaisesRegex(ErroNegocio, "turno"):
            self.devolver(vid, [{"item_id": s, "quantidade": 1}])
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM devolucoes"), 0)

    def test_devolucao_em_turno_seguinte_conta_no_turno_do_reembolso(self):
        vid = self.fechada((self.skol, 2))
        self.turnos.fechar(self.turno, self.adm, 11600)
        t2 = self.turnos.abrir(self.adm, 2, 5000)
        d = self.devolver(vid, [{"item_id": self.item(vid), "quantidade": 1}])
        self.assertEqual((d["turno_id"], d["venda_turno_id"]), (t2, self.turno))
        self.assertEqual(self.dev.resumo_turno(self.turno)["quantidade"], 0)
        r = self.dev.resumo_turno(t2)
        self.assertEqual((r["valor_cent"], r["dinheiro_gaveta_cent"], r["por_modo"]["dinheiro_gaveta"]),
                         (800, 800, {"quantidade": 1, "valor_cent": 800}))
        self.assertEqual(r["movimentos_caixa_ids"], [d["movimento_caixa_id"]])
        self.assertEqual(len(self.dev.listar(de="2026-10-03", ate="2026-10-03")), 1)


class TesteReembolso(BaseDevolucao):
    def test_externo_exige_referencia_forma_da_venda_e_teto(self):
        vid = self.fechada((self.skol, 2), forma="Pix")
        s = self.item(vid)
        with self.assertRaisesRegex(ErroNegocio, "referência"):
            self.devolver(vid, [{"item_id": s, "quantidade": 1}], "externo", tipo_pagamento_id=self.tipo("Pix"))
        with self.assertRaisesRegex(ErroNegocio, "forma"):
            self.devolver(vid, [{"item_id": s, "quantidade": 1}], "externo",
                          tipo_pagamento_id=self.tipo("Cartão Débito"), referencia_externa="X")
        d = self.devolver(vid, [{"item_id": s, "quantidade": 1}], "externo", tipo_pagamento_id=self.tipo("Pix"),
                          referencia_externa="E2E123")
        self.assertIsNone(d["movimento_caixa_id"])
        r = self.dev.resumo_turno(self.turno)
        self.assertEqual((r["dinheiro_gaveta_cent"], r["externos"][0]["referencia_externa"]), (0, "E2E123"))
        self.assertEqual(r["por_forma"][0]["tipo"], "Pix")

    def test_caderneta_credita_cliente(self):
        cid = self.cliente()
        vid = self.caixa.abrir_caderneta(cid)
        self.caixa.adicionar_item(vid, self.skol, 2)
        self.caixa.fechar(vid)
        s = self.item(vid)
        with self.assertRaisesRegex(ErroNegocio, "caderneta"):
            self.devolver(vid, [{"item_id": s, "quantidade": 1}])
        d = self.devolver(vid, [{"item_id": s, "quantidade": 1}], "caderneta")
        self.assertEqual(self.banco.valor("SELECT saldo_cent FROM clientes WHERE id = ?", (cid,)), -800)
        self.assertIsNotNone(d["caderneta_id"])

    def test_concorrencia_segunda_conexao_ve_saldo_atualizado(self):
        caminho = os.path.abspath(f"_teste_dev_{os.getpid()}.db")
        for x in (caminho, caminho + "-wal", caminho + "-shm"):
            if os.path.exists(x):
                os.remove(x)
        b1 = BancoDados(caminho)
        b2 = BancoDados(caminho)
        try:
            from src.controllers.caixa_controller import CaixaController
            from src.controllers.turno_controller import TurnoController
            adm = b1.valor("SELECT id FROM operadores WHERE nome = 'ADM'")
            TurnoController(b1).abrir(adm, 1, 0)
            banco_teste, self.banco = self.banco, b1
            try:
                pid = self.novo_produto("COCA", 500)
            finally:
                self.banco = banco_teste
            c1, c2 = CaixaController(b1, adm), CaixaController(b2, adm)
            vid = c1.abrir_balcao()
            c1.adicionar_item(vid, pid, 1)
            c1.adicionar_pagamento(vid, 1, c1.recalcular(vid)["total"])
            c1.fechar(vid)
            item = c1.itens(vid)[0]["id"]
            c2.previa_devolucao(vid, [{"item_id": item, "quantidade": 1}])       # prévia antiga na conexão 2
            c1.devolver(vid, [{"item_id": item, "quantidade": 1}], "m", adm, "dinheiro_gaveta", novo_uuid())
            with self.assertRaisesRegex(ErroNegocio, "restam"):
                c2.devolver(vid, [{"item_id": item, "quantidade": 1}], "m", adm, "dinheiro_gaveta", novo_uuid())
        finally:
            b1.fechar()
            b2.fechar()
            for x in (caminho, caminho + "-wal", caminho + "-shm"):
                if os.path.exists(x):
                    os.remove(x)

    def test_troca_abre_nova_venda_idempotente(self):
        vid = self.fechada((self.skol, 1))
        d = self.devolver(vid, [{"item_id": self.item(vid), "quantidade": 1}], troca=True)
        nova = self.caixa.abrir_troca(d["id"])
        self.assertEqual(self.caixa.abrir_troca(d["id"]), nova)
        self.assertNotEqual(nova, vid)
        self.caixa.adicionar_item(nova, self.agua, 1)
        self.assertEqual(self.dev.obter(d["id"])["troca_venda_id"], nova)
        comum = self.fechada((self.agua, 1))
        d2 = self.devolver(comum, {self.item(comum): 1})
        with self.assertRaisesRegex(ErroNegocio, "troca"):
            self.caixa.abrir_troca(d2["id"])

    def test_comprovante(self):
        vid = self.fechada((self.skol, 1))
        d = self.devolver(vid, [{"item_id": self.item(vid), "quantidade": 1}])
        txt = self.dev.comprovante(d["id"], 40)
        self.assertIn("DEVOLUÇÃO", txt)
        self.assertIn(d["uuid"][:20], txt)
        self.assertTrue(all(len(l) <= 40 for l in txt.splitlines()))


class TesteMigracao29(BaseDevolucao):
    def test_banco_v28_ganha_estados_da_fila_sem_perder_linhas(self):
        caminho = os.path.abspath(f"_teste_v29_{os.getpid()}.db")
        try:
            b = BancoDados(caminho)
            ddl = b.valor("SELECT sql FROM sqlite_master WHERE name = 'fila_impressao'")
            b.fechar()
            c = sqlite3.connect(caminho)
            c.executescript("PRAGMA foreign_keys=OFF; DROP TABLE fila_impressao; "
                            + ddl.replace("'pendente','enviando','enviado','erro','incerto','cancelado'",
                                          "'pendente','enviado','erro','cancelado'") + ";")
            for i in (5, 9):
                c.execute("INSERT INTO fila_impressao (id, criado_em, nome, dados, status) VALUES (?, '2026-01-01 00:00:00',"
                          " 'x', x'00', 'pendente')", (i,))
            c.execute("PRAGMA user_version = 28")
            c.commit()
            c.close()
            b = BancoDados(caminho)
            self.assertEqual(b.valor("PRAGMA user_version"), esquema.VERSAO_ESQUEMA)
            self.assertEqual([r[0] for r in b.todos("SELECT id FROM fila_impressao ORDER BY id")], [5, 9])
            b.executar("UPDATE fila_impressao SET status = 'enviando' WHERE id = 5")
            b.executar("UPDATE fila_impressao SET status = 'incerto' WHERE id = 9")
            nid = b.inserir("fila_impressao", {"criado_em": "2026-01-01 00:00:00", "nome": "y", "dados": b"1"})
            self.assertGreater(nid, 9)
            b.fechar()
        finally:
            for x in (caminho, caminho + "-wal", caminho + "-shm"):
                if os.path.exists(x):
                    os.remove(x)