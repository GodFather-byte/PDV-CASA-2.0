"""Adicionais mantêm preço, limites e retrato ao cancelar, transferir e aceitar pedido."""
import copy
import json
from uuid import uuid4

from fastapi import HTTPException
from src.controllers.opcoes_produto_controller import OpcoesProdutoController
from src.controllers.impressao_controller import ImpressaoController
from src.core.erros import ErroNegocio
from tests.test_caixa import BaseCaixa


class TesteOpcoesProduto(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.ctrl = OpcoesProdutoController(self.banco)
        self.ponto, self.bacon, self.cheddar = [str(uuid4()) for _ in range(3)]
        self.grupos = [
            {"id": str(uuid4()), "nome": "Ponto", "minimo": 1, "maximo": 1,
             "opcoes": [{"id": self.ponto, "nome": "Ao ponto", "preco_cent": 0}]},
            {"id": str(uuid4()), "nome": "Adicionais", "minimo": 0, "maximo": 2,
             "opcoes": [{"id": self.bacon, "nome": "Bacon extra", "preco_cent": 300},
                        {"id": self.cheddar, "nome": "Cheddar", "preco_cent": 200}]}]
        self.ctrl.salvar(self.skol, self.grupos)

    def test_escolha_obrigatoria_e_opcao_desconhecida_nao_lancam_item(self):
        vid, _ = self.caixa.abrir_mesa(1)
        for ids in ([], [self.ponto, str(uuid4())], [self.ponto, self.ponto]):
            with self.assertRaises(ErroNegocio):
                self.caixa.adicionar_item(vid, self.skol, 1, opcoes_ids=ids)
        self.assertEqual(self.caixa.itens(vid), [])

    def test_preco_por_unidade_e_retrato_nao_mudam_com_cadastro(self):
        vid, _ = self.caixa.abrir_mesa(1)
        item = self.caixa.adicionar_item(vid, self.skol, 2, opcoes_ids=[self.ponto, self.bacon])
        antes = dict(self.banco.um("SELECT * FROM itens_venda WHERE id = ?", (item,)))
        self.assertEqual((antes["preco_unit_cent"], antes["adicionais_cent"], antes["total_cent"]), (1100, 300, 2200))
        novo = copy.deepcopy(self.grupos)
        novo[1]["opcoes"][0]["preco_cent"] = 700
        self.ctrl.salvar(self.skol, novo)
        self.caixa.recalcular(vid)
        self.assertEqual(self.banco.valor("SELECT total_cent FROM itens_venda WHERE id = ?", (item,)), 2200)
        self.assertIn("Bacon extra", self.caixa.itens(vid)[0]["nome"])

    def test_cancelamento_e_transferencia_parciais_preservam_escolhas(self):
        vid, _ = self.caixa.abrir_mesa(1, comanda=False)
        item = self.caixa.adicionar_item(vid, self.skol, 3, opcoes_ids=[self.ponto, self.bacon])
        self.caixa.cancelar_item(item, "Teste", quantidade=1)
        self.caixa.transferir_item(item, (False, 2), 1)
        linhas = self.banco.todos("SELECT quantidade, total_cent, opcoes_json FROM itens_venda WHERE produto_id = ?",
                                   (self.skol,))
        self.assertEqual(sum(r["total_cent"] for r in linhas), 3300)
        self.assertTrue(all([o["id"] for o in json.loads(r["opcoes_json"])] == [self.ponto, self.bacon] for r in linhas))

    def test_atacado_nao_apaga_preco_dos_adicionais(self):
        self.banco.executar("UPDATE produtos SET atacado_qtd = 2, preco_atacado_cent = 700 WHERE id = ?", (self.skol,))
        vid = self.caixa.abrir_balcao()
        item = self.caixa.adicionar_item(vid, self.skol, 2, opcoes_ids=[self.ponto, self.bacon])
        self.assertEqual(self.banco.valor("SELECT preco_unit_cent FROM itens_venda WHERE id = ?", (item,)), 1000)
        linha = self.caixa.itens(vid)[0]
        explicacao = self.prod.explicacao_preco_adega(linha, "balcao")
        self.assertEqual(explicacao["economia_cent"], 200)
        self.assertIn("adicionais", explicacao["detalhe"])

    def test_ticket_da_cozinha_leva_opcoes_e_preco(self):
        self.banco.executar("UPDATE subgrupos SET impressora_remota = 1")
        vid, _ = self.caixa.abrir_mesa(1)
        self.caixa.adicionar_item(vid, self.skol, 1, opcoes_ids=[self.ponto, self.bacon])
        texto = "\n".join(ImpressaoController(self.banco).pedido_remoto(vid).values())
        self.assertIn("Ao ponto", texto)
        self.assertIn("Bacon extra", texto)
        self.assertIn("3,00", texto)

    def test_nuvem_recalcula_preco_sem_aceitar_valor_do_navegador(self):
        from backend.pedido_online import montar_pedido
        produto = {"nome": "Hambúrguer", "preco_cent": 800, "grupos_opcoes": self.grupos}
        pedido = {"nome": "Ana", "telefone": "11999990000", "retirada": True, "pagamento": "dinheiro",
                  "itens": [{"codigo": "1", "qtd": 2, "preco_cent": 1, "opcoes_ids": [self.ponto, self.bacon]}]}
        dados = montar_pedido({"retirada": True}, {"1": produto}, pedido)
        self.assertEqual(dados["total_cent"], 2200)
        self.assertEqual(dados["itens"][0]["opcoes_ids"], sorted([self.ponto, self.bacon]))
        pedido["itens"][0]["opcoes_ids"] = []
        with self.assertRaises(HTTPException):
            montar_pedido({"retirada": True}, {"1": produto}, pedido)


class TesteMigracaoRestaurante(BaseCaixa):
    def test_migrar_47_preserva_itens_e_inicia_retratos_vazios(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from contextlib import closing
        from src.database.conexao import BancoDados
        vid = self.caixa.abrir_balcao()
        item = self.caixa.adicionar_item(vid, self.skol, 2)
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = str(Path(pasta) / "anterior.db")
            self.banco.copiar_para(arquivo)
            with closing(sqlite3.connect(arquivo)) as con, con:
                con.execute("DROP TABLE produto_opcoes")
                con.execute("DROP TABLE pedidos_mesa_importados")
                con.execute("ALTER TABLE itens_venda DROP COLUMN opcoes_json")
                con.execute("ALTER TABLE itens_venda DROP COLUMN adicionais_cent")
                con.execute("PRAGMA user_version = 47")
            migrado = BancoDados(arquivo)
            try:
                self.assertEqual(migrado.valor("PRAGMA user_version"), 49)
                linha = migrado.um("SELECT total_cent, opcoes_json, adicionais_cent FROM itens_venda WHERE id = ?", (item,))
                self.assertEqual(tuple(linha), (1600, "[]", 0))
                self.assertEqual(migrado.todos("PRAGMA foreign_key_check"), [])
                self.assertTrue(list(Path(pasta).glob("*.antes-migracao-v47-*.bak")))
            finally:
                migrado.fechar()
