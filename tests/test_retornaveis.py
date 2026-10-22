"""Posse por cliente: banco real, auditoria, migração e rollback."""
import json
import sqlite3
from unittest.mock import patch

from src.controllers.retornaveis_controller import RetornaveisController
from src.core.erros import ErroNegocio, ErroPermissao
from src.database import esquema
from tests.base import BaseTeste


class TestRetornaveis(BaseTeste):
    def setUp(self):
        super().setUp()
        self.operador_id = self.operador_adm()
        self.controle = RetornaveisController(self.banco, self.operador_id)
        self.cliente_id = self.banco.inserir("clientes", {"numero_consulta": "10", "nome": "ANA"})
        self.produto_id = self.novo_produto("CAIXA PLÁSTICA", estoque=True, qt=15)

    def registrar(self, tipo="emprestimo", quantidade=2, motivo="Entrega combinada", **kw):
        return self.controle.registrar(
            kw.get("cliente_id", self.cliente_id), kw.get("produto_id", self.produto_id),
            tipo, quantidade, motivo)

    def test_emprestimo_devolucao_parcial_e_total_com_historico_e_auditoria(self):
        primeiro = self.registrar(quantidade="2,1234")
        self.registrar("devolucao", "0.1234", "Retorno parcial")
        self.assertEqual(self.controle.saldo(self.cliente_id, self.produto_id), 2)
        self.registrar("devolucao", 2, "Retorno total")
        self.assertEqual(self.controle.saldo(self.cliente_id, self.produto_id), 0)
        historico = self.controle.historico(self.cliente_id, self.produto_id)
        self.assertEqual([m["saldo_apos"] for m in historico], [0, 2, 2.1234])
        self.assertEqual(historico[-1]["id"], primeiro)
        self.assertEqual(historico[-1]["criado_em"], "2026-10-03 21:00:00")
        self.assertEqual(historico[-1]["operador_id"], self.operador_id)
        auditoria = self.banco.todos(
            "SELECT * FROM auditoria_eventos WHERE entidade = 'retornaveis_movimentos' ORDER BY id")
        self.assertEqual([a["acao"] for a in auditoria],
                         ["retornavel_emprestado", "retornavel_devolvido", "retornavel_devolvido"])
        self.assertEqual(auditoria[0]["operador_id"], self.operador_id)
        self.assertEqual(auditoria[0]["origem"], "operador")
        self.assertIsNone(auditoria[0]["antes"])
        retrato = json.loads(auditoria[0]["depois"])
        self.assertEqual(retrato["cliente_id"], self.cliente_id)
        self.assertNotIn("motivo", retrato)

    def test_saldos_independentes_por_cliente_e_produto(self):
        outro_cliente = self.banco.inserir("clientes", {"numero_consulta": "11", "nome": "BIA"})
        outro_produto = self.novo_produto("BALDE")
        self.registrar(quantidade=3)
        self.registrar(quantidade=7, cliente_id=outro_cliente)
        self.registrar(quantidade=5, produto_id=outro_produto)
        self.registrar("devolucao", 1)
        self.assertEqual(self.controle.saldo(self.cliente_id, self.produto_id), 2)
        self.assertEqual(self.controle.saldo(outro_cliente, self.produto_id), 7)
        self.assertEqual(self.controle.saldo(self.cliente_id, outro_produto), 5)
        self.assertEqual(len(self.controle.saldos(self.cliente_id)), 2)
        self.assertEqual(len(self.controle.historico(outro_cliente)), 1)

    def test_devolucao_excessiva_ou_sem_emprestimo_nao_grava(self):
        with self.assertRaises(ErroNegocio):
            self.registrar("devolucao", 1)
        self.registrar(quantidade=1)
        with self.assertRaises(ErroNegocio):
            self.registrar("devolucao", "1.0001")
        self.assertEqual(self.controle.saldo(self.cliente_id, self.produto_id), 1)
        self.assertEqual(len(self.controle.historico(self.cliente_id)), 1)
        self.assertEqual(self.banco.valor(
            "SELECT COUNT(*) FROM auditoria_eventos WHERE entidade = 'retornaveis_movimentos'"), 1)

    def test_quantidades_invalidas_nao_gravam(self):
        for quantidade in (0, -1, True, False, None, "", "abc", "1.00001",
                           "0.00001", "1,2,3", float("nan"), float("inf"), -float("inf"), "1e999"):
            with self.subTest(quantidade=quantidade), self.assertRaises(ErroNegocio):
                self.registrar(quantidade=quantidade)
        self.assertEqual(len(self.controle.historico(self.cliente_id)), 0)

    def test_soma_decimal_nao_cria_residuo_ou_saldo_negativo(self):
        for _ in range(3):
            self.registrar(quantidade=0.1)
        self.assertEqual(self.controle.saldo(self.cliente_id, self.produto_id), 0.3)
        self.registrar("devolucao", 0.3)
        self.assertEqual(self.controle.saldo(self.cliente_id, self.produto_id), 0)

    def test_tipo_motivo_identificadores_e_cadastros_inativos_invalidos(self):
        for campos in (
            {"tipo": "troca"}, {"tipo": []}, {"motivo": ""}, {"motivo": " \t "}, {"motivo": None},
            {"cliente_id": None}, {"cliente_id": True}, {"cliente_id": 99999},
            {"produto_id": None}, {"produto_id": True}, {"produto_id": 99999},
        ):
            with self.subTest(campos=campos), self.assertRaises(ErroNegocio):
                self.registrar(**campos)
        for tabela, identificador in (("clientes", self.cliente_id), ("produtos", self.produto_id)):
            self.banco.atualizar(tabela, identificador, {"ativo": 0})
            with self.assertRaises(ErroNegocio):
                self.registrar()
            self.banco.atualizar(tabela, identificador, {"ativo": 1})
        self.assertEqual(len(self.controle.historico(self.cliente_id)), 0)

    def test_revalida_nivel_modulo_operador_ativo_e_sessao(self):
        self.banco.executar("UPDATE acessos SET nivel = 2 WHERE modulo = 'lanc_estoque'")
        self.banco.atualizar("operadores", self.operador_id, {"nivel": 2})
        self.registrar()
        self.banco.executar("UPDATE acessos SET nivel = 3 WHERE modulo = 'lanc_estoque'")
        with self.assertRaises(ErroPermissao):
            self.registrar()
        self.banco.atualizar("operadores", self.operador_id, {"nivel": 4, "ativo": 0})
        with self.assertRaises(ErroPermissao):
            self.registrar()
        for operador_id in (None, True, 99999):
            with self.subTest(operador_id=operador_id), self.assertRaises(ErroPermissao):
                RetornaveisController(self.banco, operador_id).registrar(
                    self.cliente_id, self.produto_id, "emprestimo", 1, "Teste")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM retornaveis_movimentos"), 1)

    def test_falha_da_auditoria_reverte_movimento_e_saldo(self):
        self.registrar()
        self.banco.executar(
            "CREATE TRIGGER falha_auditoria_retornaveis BEFORE INSERT ON auditoria_eventos "
            "WHEN NEW.entidade = 'retornaveis_movimentos' BEGIN "
            "SELECT RAISE(ABORT, 'falha de teste'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.registrar("devolucao", 1)
        self.assertEqual(self.controle.saldo(self.cliente_id, self.produto_id), 2)
        self.assertEqual(len(self.controle.historico(self.cliente_id)), 1)

    def test_rollback_externo_reverte_movimentos_e_auditoria(self):
        with self.assertRaises(RuntimeError):
            with self.banco.transacao():
                self.registrar()
                self.registrar("devolucao", 1)
                raise RuntimeError("Falha posterior")
        self.assertEqual(self.controle.saldo(self.cliente_id, self.produto_id), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM retornaveis_movimentos"), 0)
        self.assertEqual(self.banco.valor(
            "SELECT COUNT(*) FROM auditoria_eventos WHERE entidade = 'retornaveis_movimentos'"), 0)

    def test_historico_nao_permite_editar_ou_apagar_e_sobrevive_exclusao_produto(self):
        self.registrar()
        for comando in ("DELETE FROM retornaveis_movimentos",
                        "UPDATE retornaveis_movimentos SET quantidade = 3"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.banco.executar(comando)
        self.banco.executar("DELETE FROM produtos WHERE id = ?", (self.produto_id,))
        self.assertEqual(self.controle.historico(self.cliente_id)[0]["produto"], "CAIXA PLÁSTICA")
        self.assertEqual(self.controle.saldos(self.cliente_id)[0]["saldo"], 2)
        with self.assertRaises(ErroNegocio):
            self.registrar("devolucao", 1)

    def test_nao_altera_outras_tabelas_inclusive_estoque_vendas_financeiro(self):
        tabelas = [r["name"] for r in self.banco.todos(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT IN ('sqlite_sequence','auditoria_eventos','retornaveis_movimentos')")]
        antes = {t: [tuple(r) for r in self.banco.todos(f'SELECT * FROM "{t}"')] for t in tabelas}
        self.registrar(quantidade=100)
        self.registrar("devolucao", 25)
        depois = {t: [tuple(r) for r in self.banco.todos(f'SELECT * FROM "{t}"')] for t in tabelas}
        self.assertEqual(antes, depois)

    def test_todos_perfis_sem_restricao_a_cascos(self):
        from src.controllers.perfil_controller import PERFIS, PerfilController
        for perfil in PERFIS:
            with self.subTest(perfil=perfil):
                PerfilController(self.banco, self.operador_id).aplicar(perfil)
                self.registrar(quantidade=1)
                self.registrar("devolucao", 1)
        self.assertEqual(self.controle.saldo(self.cliente_id, self.produto_id), 0)

    def test_migracao_v25_nao_inventa_saldo_de_cascos_e_e_idempotente(self):
        bebida = self.novo_produto("BEBIDA", casco_produto_id=self.produto_id)
        self.banco.executar("DROP TABLE retornaveis_movimentos")
        self.banco.executar("PRAGMA user_version = 25")
        self.banco._criar_esquema()
        self.assertEqual(self.banco.valor("PRAGMA user_version"), esquema.VERSAO_ESQUEMA)
        self.assertEqual(self.controle.saldo(self.cliente_id, self.produto_id), 0)
        self.assertEqual(self.banco.valor(
            "SELECT casco_produto_id FROM produtos WHERE id = ?", (bebida,)), self.produto_id)
        self.assertEqual(self.banco.valor(
            "SELECT qt_atual FROM produtos WHERE id = ?", (self.produto_id,)), 15)
        self.registrar()
        self.banco._criar_esquema()
        self.assertEqual(len(self.controle.historico(self.cliente_id)), 1)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM pragma_foreign_key_check"), 0)

    def test_migracao_v26_falha_atomicamente(self):
        self.banco.executar("DROP TABLE retornaveis_movimentos")
        self.banco.executar("PRAGMA user_version = 25")
        with patch.dict(esquema.MIGRACOES, {26: [*esquema.RETORNAVEIS_DDL, "SQL INVALIDO"]}):
            with self.assertRaises(sqlite3.OperationalError):
                self.banco._migrar(25)
        self.assertEqual(self.banco.valor("PRAGMA user_version"), 25)
        self.assertIsNone(self.banco.um(
            "SELECT name FROM sqlite_master WHERE name = 'retornaveis_movimentos'"))
        self.banco._criar_esquema()
        self.registrar()
        self.assertEqual(self.controle.saldo(self.cliente_id, self.produto_id), 2)

    def test_migracao_v27_pagamentos_itens_sem_backfill(self):
        self.registrar()
        self.banco.executar("DROP TABLE pagamentos_itens")
        self.banco.executar("PRAGMA user_version = 26")
        self.banco._migrar(26)
        self.assertEqual(self.banco.valor("PRAGMA user_version"), esquema.VERSAO_ESQUEMA)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM pagamentos_itens"), 0)
        self.assertEqual(self.controle.saldo(self.cliente_id, self.produto_id), 2)
        indices = {r["name"] for r in self.banco.todos("PRAGMA index_list(pagamentos_itens)")}
        self.assertTrue({"ix_pagamentos_itens_item", "ix_pagamentos_itens_pagamento"} <= indices)
        referencias = self.banco.todos("PRAGMA foreign_key_list(pagamentos_itens)")
        self.assertEqual({r["table"] for r in referencias}, {"pagamentos_venda", "itens_venda"})
        self.assertTrue(all(r["on_delete"] == "CASCADE" for r in referencias))
