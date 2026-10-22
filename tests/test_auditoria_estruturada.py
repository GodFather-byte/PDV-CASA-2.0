"""Auditoria transacional, identidade da sessão, privacidade e migração v18."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from src.controllers.acesso_controller import AcessoController, Operador
from src.controllers.auditoria_controller import AuditoriaController
from src.controllers.cadastro_controller import CadastroController
from src.controllers.caixa_controller import CaixaController
from src.controllers.estoque_controller import EstoqueController
from src.controllers.turno_controller import TurnoController
from src.core.erros import ErroNegocio, ErroPermissao, ErroValidacao
from src.database import esquema
from src.database.conexao import BancoDados
from src.controllers.contexto import Contexto
from tests.base import BaseTeste


class TesteAuditoriaEstruturada(BaseTeste):
    def setUp(self):
        super().setUp()
        self.acesso = AcessoController(self.banco)
        self.adm = self.acesso.operador(self.operador_adm())
        self.contexto = Contexto(self.banco, self.adm)
        self.cad = CadastroController(self.banco)

    def eventos(self, entidade=None, acao=None):
        return [e for e in self.contexto.auditoria.listar(limite=500)
                if (entidade is None or e["entidade"] == entidade)
                and (acao is None or e["acao"] == acao)]

    def test_sementes_nao_geram_ruido_nem_retroativo(self):
        self.assertEqual(self.eventos(), [])

    def test_cadastro_preco_exclusao_preservam_retratos_e_log_legado(self):
        produto = self.novo_produto(preco=800)
        self.cad.salvar("produtos", {"preco_cent": "9,50"}, produto)
        self.cad.excluir("produtos", produto)
        eventos = list(reversed(self.eventos("produtos")))
        self.assertEqual([e["acao"] for e in eventos], ["cadastro", "preco_alterado", "exclusao"])
        self.assertIsNone(eventos[0]["antes"])
        self.assertEqual(eventos[1]["antes"]["preco_cent"], 800)
        self.assertEqual(eventos[1]["depois"]["preco_cent"], 950)
        self.assertEqual(eventos[2]["antes"]["preco_cent"], 950)
        self.assertIsNone(eventos[2]["depois"])
        self.assertTrue(all(e["operador_id"] == self.adm.id for e in eventos))
        self.assertTrue(all(e["quando"] == "2026-10-03 21:00:00" for e in eventos))
        self.assertEqual(self.banco.valor(
            "SELECT COUNT(*) FROM log_eventos WHERE evento = 'produto_excluido'"), 1)

    def test_log_legado_nao_duplica_evento_estruturado(self):
        self.banco.log("produto_excluido", "detalhe legado", self.adm.id)
        self.assertEqual(self.eventos(), [])
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos"), 1)

    def test_update_sem_mudanca_nao_audita(self):
        produto = self.novo_produto(preco=800)
        quantidade = len(self.eventos())
        self.banco.executar("UPDATE produtos SET preco_cent = preco_cent WHERE id = ?", (produto,))
        self.assertEqual(len(self.eventos()), quantidade)

    def test_promocao_auditada_como_preco(self):
        produto = self.novo_produto(promo_de="03/10/2026", promo_ate="04/10/2026")
        self.cad.salvar("produtos", {"promo_preco_cent": "6,00"}, produto)
        eventos = self.eventos("produtos", "preco_alterado")
        self.assertEqual(len(eventos), 1)
        evento = eventos[0]
        self.assertEqual(evento["antes"]["promo_preco_cent"], 0)
        self.assertEqual(evento["depois"]["promo_preco_cent"], 600)
        self.assertEqual(evento["operador_id"], self.adm.id)
        cadastro = self.cad.obter("produtos", produto)
        self.assertEqual((cadastro["promo_de"], cadastro["promo_ate"]), ("2026-10-03", "2026-10-04"))

    def test_sem_operador_e_sistema_nao_herda_responsavel_do_registro(self):
        self.contexto.operador = None
        EstoqueController(self.banco, self.adm.id).criar_lancamento("entrada")
        evento = self.banco.um("SELECT * FROM auditoria_eventos ORDER BY id DESC LIMIT 1")
        self.assertEqual(evento["origem"], "sistema")
        self.assertIsNone(evento["operador_id"])

    def test_supervisor_nao_substitui_sessao(self):
        usuario = self.cad.salvar("operadores", {"nome": "CAIXA", "senha": "caixa123", "nivel": "0"})
        self.contexto.operador = self.acesso.operador(usuario)
        self.assertEqual(self.acesso.validar_supervisor("ADM", "caixa_cancelamento").id, self.adm.id)
        produto = self.novo_produto()
        evento = AuditoriaController(self.banco, self.adm).listar()[0]
        self.assertEqual(evento["entidade_id"], str(produto))
        self.assertEqual(evento["operador_id"], usuario)
        self.assertEqual(evento["origem"], "operador")

    def test_troca_sessao_e_saida_atualizam_identidade(self):
        self.novo_produto("UM")
        self.contexto.operador = None
        self.novo_produto("DOIS")
        eventos = AuditoriaController(self.banco, self.adm).listar()
        self.assertEqual([e["origem"] for e in eventos], ["sistema", "operador"])

    def test_senha_dados_pessoais_e_config_secreta_nao_sao_copiados(self):
        segredo = "Segredo88"
        usuario = self.cad.salvar("operadores", {"nome": "PESSOA PRIVADA", "senha": segredo, "nivel": "1"})
        self.acesso.trocar_senha(self.acesso.operador(usuario), "Outro99")
        self.cad.salvar("clientes", {
            "numero_consulta": "CLI", "nome": "CLIENTE PRIVADO", "cpf": "12345678900",
            "endereco": "ENDERECO PRIVADO", "telefone": "9988776655", "email": "privado@example.test"})
        self.banco.cfg_set("telegram_token", "TOKEN_PRIVADO")
        bruto = json.dumps([dict(r) for r in self.banco.todos("SELECT * FROM auditoria_eventos")])
        for valor in (segredo, "Outro99", "PESSOA PRIVADA", "CLIENTE PRIVADO", "12345678900",
                      "ENDERECO PRIVADO", "9988776655", "privado@example.test", "TOKEN_PRIVADO"):
            self.assertNotIn(valor, bruto)
        self.assertNotIn(self.banco.valor("SELECT senha FROM operadores WHERE id = ?", (usuario,)), bruto)
        self.assertEqual(len(self.eventos("operadores", "credencial_alterada")), 1)

    def test_mudanca_somente_dado_pessoal_registra_sem_valor(self):
        cliente = self.cad.salvar("clientes", {"numero_consulta": "1", "nome": "CLIENTE"})
        self.cad.salvar("clientes", {"telefone": "999999999"}, cliente)
        self.assertEqual(len(self.eventos("clientes")), 2)
        self.assertNotIn("telefone", self.eventos("clientes")[0]["depois"])

    def test_permissao_nivel_e_modulo_auditados(self):
        usuario = self.cad.salvar("operadores", {"nome": "BAR", "senha": "123", "nivel": "0"})
        self.cad.salvar("operadores", {"nivel": "2"}, usuario)
        self.acesso.alterar_nivel_modulo("cad_produtos", 4)
        self.assertEqual(len(self.eventos(acao="permissao_alterada")), 2)
        evento = self.eventos("acessos")[0]
        self.assertEqual(evento["entidade_id"], "cad_produtos")
        self.assertEqual(evento["depois"]["nivel"], 4)

    def test_estoque_nao_duplica_espelho_historico(self):
        produto = self.novo_produto(estoque=True)
        EstoqueController(self.banco, self.adm.id)._mover(produto, 2.125, "entrada")
        eventos = self.eventos(acao="estoque_alterado")
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["antes"]["qt_atual"], 0)
        self.assertEqual(eventos[0]["depois"]["qt_atual"], 2.125)

    def test_falha_no_historico_estoque_reverte_saldo_e_auditoria(self):
        produto = self.novo_produto(estoque=True)
        quantidade = len(self.eventos())
        with patch.object(self.banco, "inserir", side_effect=RuntimeError("falhou")):
            with self.assertRaises(RuntimeError):
                EstoqueController(self.banco, self.adm.id)._mover(produto, 2, "entrada")
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto,)), 0)
        self.assertEqual(len(self.eventos()), quantidade)

    def test_falha_no_log_de_senha_reverte_credencial_e_auditoria(self):
        senha = self.banco.valor("SELECT senha FROM operadores WHERE id = ?", (self.adm.id,))
        with patch.object(self.banco, "log", side_effect=RuntimeError("falhou")):
            with self.assertRaises(RuntimeError):
                self.acesso.trocar_senha(self.adm, "Nova123")
        self.assertEqual(self.banco.valor("SELECT senha FROM operadores WHERE id = ?", (self.adm.id,)), senha)
        self.assertEqual(self.eventos(), [])

    def test_estoque_de_produto_excluido_tambem_auditado(self):
        produto = self.novo_produto(estoque=True)
        self.cad.excluir("produtos", produto)
        EstoqueController(self.banco, self.adm.id)._mover(produto, 1.5, "estorno_venda")
        eventos = self.eventos("produtos_historico", "estoque_alterado")
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["depois"]["qt_atual"], 1.5)

    def test_rollback_externo_reverte_dados_auditoria_e_log(self):
        with self.assertRaisesRegex(RuntimeError, "falhou"), self.banco.transacao():
            self.novo_produto()
            self.banco.log("legado", "também transacional")
            raise RuntimeError("falhou")
        self.assertEqual(self.eventos(), [])
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos"), 0)

    def test_savepoint_reverte_so_eventos_da_camada_falha(self):
        with self.banco.transacao():
            self.novo_produto("MANTIDO")
            try:
                with self.banco.transacao():
                    self.novo_produto("REVERTIDO")
                    raise RuntimeError("falhou")
            except RuntimeError:
                pass
            self.novo_produto("OUTRO")
        self.assertEqual([e["depois"]["nome"] for e in self.eventos("produtos")], ["OUTRO", "MANTIDO"])

    def test_violacao_integridade_nao_deixa_evento(self):
        self.novo_produto("UNICO")
        quantidade = len(self.eventos())
        with self.assertRaises(ErroNegocio):
            self.novo_produto("UNICO")
        self.assertEqual(len(self.eventos()), quantidade)

    def preparar_venda(self):
        self.banco.cfg_set("usar_desconto", "S")
        produto = self.novo_produto(estoque=True, qt=10)
        TurnoController(self.banco).abrir(self.adm.id, 1, 0)
        caixa = CaixaController(self.banco, self.adm.id)
        venda = caixa.abrir_balcao()
        item = caixa.adicionar_item(venda, produto, 1)
        return caixa, venda, item

    def test_desconto_e_cancelamentos_identificam_venda_por_uuid(self):
        caixa, venda, item = self.preparar_venda()
        caixa.definir_desconto(venda, pct=10)
        eventos = self.eventos("vendas", "desconto_alterado")
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["antes"]["desconto_cent"], 0)
        self.assertEqual(eventos[0]["depois"]["desconto_cent"], 80)
        self.assertEqual(eventos[0]["entidade_id"], caixa.obter(venda)["uuid"])
        caixa.cancelar_item(item)
        caixa.cancelar_venda(venda, "MOTIVO PRIVADO")
        self.assertEqual(len(self.eventos("itens_venda", "item_cancelado")), 1)
        self.assertEqual(len(self.eventos("vendas", "venda_cancelada")), 1)
        self.assertNotIn("MOTIVO PRIVADO", json.dumps(self.eventos()))

    def test_falha_no_log_de_desconto_reverte_operacao_e_auditoria(self):
        caixa, venda, _ = self.preparar_venda()
        antes = caixa.obter(venda)
        quantidade = len(self.eventos())
        with patch.object(self.banco, "log", side_effect=RuntimeError("falha")):
            with self.assertRaises(RuntimeError):
                caixa.definir_desconto(venda, valor_cent=100)
        self.assertEqual(caixa.obter(venda)["desconto_cent"], antes["desconto_cent"])
        self.assertEqual(len(self.eventos()), quantidade)

    def test_consulta_so_admin_inclusive_revogacao_de_sessao(self):
        usuario = self.cad.salvar("operadores", {"nome": "GERENTE", "senha": "123", "nivel": "3"})
        for operador in (None, self.acesso.operador(usuario), Operador(usuario, "FORJADO", 4)):
            with self.subTest(operador=operador), self.assertRaises(ErroPermissao):
                AuditoriaController(self.banco, operador).listar()
        controller = self.contexto.auditoria
        self.cad.salvar("operadores", {"nome": "OUTRO ADM", "senha": "123", "nivel": "4"})
        self.cad.salvar("operadores", {"nivel": "3"}, self.adm.id)
        with self.assertRaises(ErroPermissao):
            controller.listar()

    def test_consulta_exige_modulo_e_nega_operador_inativo(self):
        with patch.object(AcessoController, "exigir", side_effect=ErroPermissao("negado")) as exigir:
            with self.assertRaises(ErroPermissao):
                self.contexto.auditoria.listar()
            self.assertEqual(exigir.call_args.args[1], "rel_auditoria")
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.adm.id,))
        with self.assertRaises(ErroPermissao):
            self.contexto.auditoria.listar()

    def test_consulta_paginada_e_filtrada_por_dia_acao(self):
        produto = self.novo_produto()
        self.avancar(days=1)
        self.cad.salvar("produtos", {"preco_cent": "9,00"}, produto)
        self.cad.salvar("produtos", {"preco_cent": "10,00"}, produto)
        controller = self.contexto.auditoria
        filtrados = controller.listar("2026-10-04", "2026-10-04", "preco_alterado")
        self.assertEqual(len(filtrados), 2)
        self.assertEqual(controller.listar(limite=1)[0], filtrados[0])
        self.assertEqual(controller.listar(limite=1, offset=1)[0], filtrados[1])
        self.assertEqual(controller.listar(offset=999), [])
        self.assertEqual(controller.listar(acao="' OR 1=1 --"), [])
        self.assertEqual(controller.listar(fim="2026-10-03 20:59:59"), [])

    def test_consulta_rejeita_paginacao_e_periodo_invalidos(self):
        for argumentos in ({"limite": 0}, {"limite": 501}, {"limite": True}, {"limite": "10"},
                           {"offset": -1}, {"offset": 1.5}, {"inicio": "03/10/2026"},
                           {"inicio": "2026-02-30"}, {"inicio": "2026-1-01"},
                           {"inicio": "2026-10-04", "fim": "2026-10-03"}, {"acao": ""}):
            with self.subTest(argumentos=argumentos), self.assertRaises(ErroValidacao):
                self.contexto.auditoria.listar(**argumentos)

    def test_identidade_invalida_nao_substitui_sessao(self):
        for identificador in (True, "1", -999):
            with self.subTest(identificador=identificador), self.assertRaises(ValueError):
                self.banco.definir_operador_auditoria(identificador)
        self.novo_produto()
        self.assertEqual(self.eventos()[0]["operador_id"], self.adm.id)


class TesteMigracaoAuditoria(BaseTeste):
    def banco_v17(self):
        with patch.object(esquema, "VERSAO_ESQUEMA", 17), patch.object(esquema, "AUDITORIA", []):
            banco = BancoDados(":memory:")
        self.addCleanup(banco.fechar)
        return banco

    def test_v17_para_v18_preserva_dados_log_e_sem_retroatividade(self):
        banco = self.banco_v17()
        banco.log("evento_legado", "preservado", 1)
        self.assertEqual(banco.valor("PRAGMA user_version"), 17)
        with patch.object(esquema, "VERSAO_ESQUEMA", 18):     # só o passo v17->v18 (esta classe testa só esse passo)
            banco._criar_esquema()
        self.assertEqual(banco.valor("PRAGMA user_version"), 18)
        self.assertEqual(banco.valor("SELECT COUNT(*) FROM auditoria_eventos"), 0)
        self.assertEqual(banco.valor("SELECT detalhe FROM log_eventos"), "preservado")
        self.assertEqual(banco.valor("PRAGMA integrity_check"), "ok")
        self.assertEqual(banco.todos("PRAGMA foreign_key_check"), [])
        banco.definir_operador_auditoria(1)
        banco.executar("UPDATE operadores SET nivel = 3 WHERE id = 1")
        self.assertEqual(banco.valor("SELECT acao FROM auditoria_eventos"), "permissao_alterada")
        with patch.object(esquema, "VERSAO_ESQUEMA", 18):
            banco._criar_esquema()
        banco.executar("UPDATE operadores SET nivel = 4 WHERE id = 1")
        self.assertEqual(banco.valor("SELECT COUNT(*) FROM auditoria_eventos"), 2)

    def test_migracao_falha_reverte_tabela_gatilhos_e_versao(self):
        banco = self.banco_v17()
        with patch.dict(esquema.MIGRACOES, {18: [*esquema.AUDITORIA, "COMANDO INVALIDO"]}):
            with self.assertRaises(sqlite3.OperationalError):
                banco._migrar(17)
        self.assertEqual(banco.valor("PRAGMA user_version"), 17)
        self.assertIsNone(banco.um("SELECT name FROM sqlite_master WHERE name = 'auditoria_eventos'"))
        self.assertEqual(banco.valor(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'auditoria_%'"), 0)
        with patch.object(esquema, "VERSAO_ESQUEMA", 18):      # só o passo v17->v18 (esta classe testa só esse passo)
            banco._criar_esquema()
        self.assertEqual(banco.valor("PRAGMA user_version"), 18)

    def test_arquivo_v17_backup_e_reabertura_preservam_eventos(self):
        caminho = Path.cwd() / f".auditoria-teste-{uuid4().hex}.db"

        def limpar():
            for arquivo in caminho.parent.glob(caminho.name + "*"):
                arquivo.unlink(missing_ok=True)

        self.addCleanup(limpar)
        with patch.object(esquema, "VERSAO_ESQUEMA", 17), patch.object(esquema, "AUDITORIA", []):
            banco = BancoDados(str(caminho))
        try:
            banco.log("antes_migracao", "preservado", 1)
        finally:
            banco.fechar()
        with patch.object(esquema, "VERSAO_ESQUEMA", 18):     # só o passo v17->v18 (esta classe testa só esse passo)
            banco = BancoDados(str(caminho))
        try:
            self.assertEqual(banco.valor("PRAGMA user_version"), 18)
            self.assertEqual(banco.valor("SELECT COUNT(*) FROM auditoria_eventos"), 0)
            banco.definir_operador_auditoria(1)
            AcessoController(banco).alterar_nivel_modulo("rel_auditoria", 4)
        finally:
            banco.fechar()
        backups = list(caminho.parent.glob(caminho.name + ".antes-migracao-v17-*.bak"))
        self.assertEqual(len(backups), 1)
        con = sqlite3.connect(backups[0])
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 17)
            self.assertEqual(con.execute("SELECT detalhe FROM log_eventos").fetchone()[0], "preservado")
            self.assertIsNone(con.execute(
                "SELECT name FROM sqlite_master WHERE name = 'auditoria_eventos'").fetchone())
        finally:
            con.close()
        banco = BancoDados(str(caminho))
        try:
            self.assertEqual(banco.valor("SELECT COUNT(*) FROM auditoria_eventos"), 1)
            self.assertEqual(banco.valor("SELECT operador_id FROM auditoria_eventos"), 1)
            AcessoController(banco).alterar_nivel_modulo("rel_auditoria", 3)
            ultimo = banco.um("SELECT * FROM auditoria_eventos ORDER BY id DESC LIMIT 1")
            self.assertEqual(ultimo["origem"], "sistema")
            self.assertIsNone(ultimo["operador_id"])
        finally:
            banco.fechar()
