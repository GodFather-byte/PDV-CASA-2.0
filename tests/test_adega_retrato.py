"""Retrato histórico dos preços, sem reconstrução pelo cadastro atual."""
from __future__ import annotations

import json
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from src.controllers.perfil_controller import PerfilController
from src.controllers.produto_controller import ProdutoController
from src.database.conexao import BancoDados
from tests.test_caixa import BaseCaixa


class TesteRetratoPrecoAdega(BaseCaixa):
    def setUp(self):
        super().setUp()
        PerfilController(self.banco, self.adm).aplicar("adega")
        self.banco.executar(
            """UPDATE produtos SET preco_gelada_cent = 1000, atacado_qtd = 6,
               preco_atacado_cent = 650, atacado_gelada_qtd = 6,
               preco_atacado_gelada_cent = 850 WHERE id = ?""", (self.skol,))
        self.vid = self.caixa.abrir_balcao()

    def lancar(self, quantidade=1, **kw):
        return self.caixa.adicionar_item(self.vid, self.skol, quantidade, **kw)

    def item(self, item_id=None):
        return dict(self.banco.um("SELECT * FROM itens_venda WHERE id = ?", (
            item_id or self.banco.valor("SELECT MIN(id) FROM itens_venda WHERE venda_id = ?", (self.vid,)),)))

    def retrato(self, item_id=None):
        return json.loads(self.item(item_id)["regra_preco_json"])

    def promover(self, preco=600):
        self.banco.executar(
            """UPDATE produtos SET promo_de = '2026-01-01', promo_ate = '2026-12-31',
               promo_preco_cent = ? WHERE id = ?""", (preco, self.skol))

    def test_retrato_persiste_regra_temperatura_base_faixa_e_instante(self):
        for temperatura, base, preco in (("natural", 800, 650), ("gelada", 1000, 850)):
            with self.subTest(temperatura=temperatura):
                item = self.lancar(6, temperatura=temperatura)
                regra = self.retrato(item)
                self.assertEqual((regra["versao"], regra["tipo"], regra["temperatura"]), (1, "atacado", temperatura))
                self.assertEqual((regra["minimo_qtd"], regra["preco_faixa_cent"]), (6, preco))
                self.assertEqual((regra["preco_base_cent"], regra["preco_unit_cent"]), (base, preco))
                self.assertEqual(regra["quantidade_grupo"], 6)
                self.assertEqual(regra["aplicado_em"], "2026-10-03 21:00:00")

    def test_explicacao_nao_depende_de_modalidade_ou_cadastro_mutavel(self):
        self.lancar(6, temperatura="gelada")
        antes = ProdutoController.explicacao_preco_adega(self.caixa.itens(self.vid)[0], "balcao")
        self.banco.executar(
            """UPDATE produtos SET preco_cent = 9999, preco_gelada_cent = 0,
               atacado_gelada_qtd = 99, preco_atacado_gelada_cent = 1 WHERE id = ?""", (self.skol,))
        depois = ProdutoController.explicacao_preco_adega(self.caixa.itens(self.vid)[0], "mesa")
        self.assertEqual(antes, depois)
        self.assertIn("a partir de 6 un", depois["detalhe"])
        self.assertEqual(depois["economia_cent"], 900)

    def test_promocao_melhor_que_atacado_e_base_preservada_ao_reprecificar(self):
        self.promover()
        item = self.lancar(6)
        regra = self.retrato(item)
        self.assertEqual((regra["tipo"], regra["preco_unit_cent"]), ("promocao", 600))
        self.assertTrue(regra["faixa_atingida"])
        self.assertEqual(regra["base"]["criterio"], "período")
        self.assertEqual(regra["base"]["inicio"], "2026-01-01")
        self.avancar(minutes=10)
        self.banco.executar("UPDATE produtos SET promo_preco_cent = 0, preco_atacado_cent = 550 WHERE id = ?", (self.skol,))
        self.lancar()
        regra = self.retrato(item)
        self.assertEqual((regra["tipo"], regra["preco_base_cent"], regra["preco_unit_cent"]), ("atacado", 600, 550))
        self.assertEqual(regra["base"]["avaliado_em"], "2026-10-03 21:00:00")
        self.assertEqual(regra["aplicado_em"], "2026-10-03 21:10:00")

    def test_promocao_e_atacado_empatados_preservam_tipo_da_base(self):
        self.promover(650)
        self.lancar(6)
        self.assertEqual(self.retrato()["tipo"], "promocao")
        self.assertEqual(self.retrato()["preco_unit_cent"], 650)

    def test_promocoes_semana_horario_e_periodo_mesma_selecao_do_preco(self):
        self.promover(750)
        self.banco.executar(
            """UPDATE produtos SET sem_inicial = 1, sem_final = 7, sem_preco_cent = 700,
               hora_ini = '20:00', hora_fim = '02:00', hora_preco_cent = 600 WHERE id = ?""", (self.skol,))
        self.lancar()
        self.assertEqual((self.retrato()["base"]["criterio"], self.item()["preco_unit_cent"]), ("horário", 600))
        self.avancar(hours=6)
        item = self.lancar()
        self.assertEqual((self.retrato(item)["base"]["criterio"], self.item(item)["preco_unit_cent"]),
                         ("dia da semana", 700))

    def test_preco_gelado_nao_herda_promocao_natural(self):
        self.promover()
        self.lancar(temperatura="gelada")
        self.assertEqual((self.retrato()["tipo"], self.item()["preco_unit_cent"]), ("gelada", 1000))

    def test_agrupamento_preserva_origens_distintas_com_mesmo_valor(self):
        primeiro = self.lancar()
        self.avancar(minutes=1)
        self.promover(800)
        self.assertEqual(self.lancar(2), primeiro)
        regra = self.retrato()
        self.assertEqual(self.item()["total_cent"], 2400)
        self.assertEqual([l["quantidade"] for l in regra["leituras"]], [1, 2])
        self.assertEqual([l["base"]["tipo"] for l in regra["leituras"]], ["normal", "promocao"])
        self.assertEqual([l["base"]["avaliado_em"] for l in regra["leituras"]],
                         ["2026-10-03 21:00:00", "2026-10-03 21:01:00"])
        detalhe = ProdutoController.explicacao_preco_adega(self.item(), "balcao")["detalhe"]
        self.assertIn("normal, promoção", detalhe)

    def test_agrupamento_legado_separa_origem_desconhecida_da_leitura_nova(self):
        primeiro = self.lancar()
        self.banco.executar("UPDATE itens_venda SET regra_preco_json = NULL WHERE id = ?", (primeiro,))
        self.assertEqual(self.lancar(2), primeiro)
        regra = self.retrato()
        self.assertEqual([l["base"]["tipo"] for l in regra["leituras"]], ["legado", "normal"])
        self.assertEqual([l["quantidade"] for l in regra["leituras"]], [1, 2])
        self.assertEqual(self.item()["total_cent"], 2400)

    def test_partes_preservam_apenas_criterio_e_preco_efetivamente_cobrado(self):
        self.banco.executar("UPDATE produtos SET partes = 2 WHERE id = ?", (self.skol,))
        self.banco.executar("UPDATE produtos SET montagem = 1 WHERE id IN (?, ?)", (self.skol, self.agua))
        item = self.caixa.adicionar_item(self.vid, self.skol, 1, partes=[self.skol, self.agua])
        regra = self.retrato(item)
        self.assertEqual((regra["tipo"], regra["base"]["criterio"]), ("partes", "maior"))
        self.assertNotIn("componentes", regra["base"])
        self.assertIsNone(self.item(item)["preco_base_cent"])
        self.assertEqual(self.item(item)["preco_unit_cent"], 800)

    def test_cancelamento_preserva_cancelado_e_retrata_faixa_dos_restantes(self):
        self.banco.cfg_set("agrupar_itens_balcao", "N")
        primeiro = self.lancar(5)
        ultimo = self.lancar()
        cancelado = self.item(ultimo)["regra_preco_json"]
        self.avancar(minutes=5)
        self.caixa.cancelar_item(ultimo)
        self.assertEqual(self.item(ultimo)["regra_preco_json"], cancelado)
        regra = self.retrato(primeiro)
        self.assertEqual((regra["tipo"], regra["preco_unit_cent"], regra["quantidade_grupo"]), ("normal", 800, 5))
        self.assertFalse(regra["faixa_atingida"])

    def test_faixa_muda_sem_mudar_preco_tambem_atualiza_retrato(self):
        self.lancar(6)
        self.avancar(minutes=1)
        self.banco.executar("UPDATE produtos SET atacado_qtd = 5 WHERE id = ?", (self.skol,))
        self.caixa._reprecificar_balcao(self.vid)
        self.assertEqual((self.retrato()["minimo_qtd"], self.item()["preco_unit_cent"]), (5, 650))
        antes = self.item()["regra_preco_json"]
        self.avancar(minutes=1)
        self.caixa._reprecificar_balcao(self.vid)
        self.assertEqual(self.item()["regra_preco_json"], antes)

    def test_fechamento_e_cancelamento_de_cupom_nao_reescrevem_retrato(self):
        self.lancar(6)
        antes = self.item()
        self.pagar(self.vid, "Dinheiro", 3900)
        self.caixa.fechar(self.vid)
        self.banco.executar("UPDATE produtos SET preco_atacado_cent = 1 WHERE id = ?", (self.skol,))
        self.caixa._reprecificar_balcao(self.vid)
        self.caixa.recalcular(self.vid)
        self.caixa.cancelar_venda(self.vid)
        self.caixa._reprecificar_balcao(self.vid)
        self.assertEqual(self.item()["regra_preco_json"], antes["regra_preco_json"])
        self.assertEqual(self.item()["preco_unit_cent"], antes["preco_unit_cent"])

    def test_legado_sem_retrato_nunca_deduz_faixa_do_cadastro(self):
        item = {"temperatura": "natural", "preco_base_cent": 800, "preco_unit_cent": 650,
                "total_cent": 3900, "quantidade": 6, "atacado_qtd": 123}
        for valor in (None, "{", "[]", '{"versao":99}',
                      '{"versao":1,"tipo":"normal","base":{"tipo":"normal"}}'):
            with self.subTest(valor=valor):
                explicacao = ProdutoController.explicacao_preco_adega({**item, "regra_preco_json": valor}, "balcao")
                self.assertIn("Legado", explicacao["rotulo"])
                self.assertIn("histórica indisponível", explicacao["detalhe"])
                self.assertNotIn("123", explicacao["detalhe"])
                self.assertEqual(explicacao["economia_cent"], 0)

    def test_json_v1_incompleto_ou_com_tipos_invalidos_tem_fallback_seguro(self):
        self.lancar(6)
        item = self.item()
        regra = self.retrato()
        invalidos = [{k: v for k, v in regra.items() if k != removido} for removido in regra]
        invalidos.extend({**regra, campo: valor} for campo, valor in (
            ("versao", True), ("versao", 1.0),
            ("preco_base_cent", None), ("preco_unit_cent", True), ("preco_base_cent", 800.0),
            ("temperatura", "fria"), ("tem_preco_gelada", "sim"), ("faixa_atingida", 1),
            ("minimo_qtd", "6"), ("minimo_qtd", {}), ("minimo_qtd", False),
            ("preco_faixa_cent", None), ("preco_faixa_cent", []),
            ("quantidade_grupo", float("nan")), ("quantidade_grupo", float("inf")),
            ("aplicado_em", None), ("aplicado_em", "2026-99-99"),
            ("leituras", [{}]), ("leituras", [{"base": regra["base"]}]),
        ))
        invalidos.extend({**regra, "base": {k: v for k, v in regra["base"].items() if k != removido}}
                         for removido in ("tipo", "preco_cent", "avaliado_em"))
        for numero, invalido in enumerate(invalidos):
            with self.subTest(caso=numero):
                corrompido = {**item, "regra_preco_json": json.dumps(invalido)}
                self.assertIsNone(ProdutoController.ler_regra_preco(corrompido))
                explicacao = ProdutoController.explicacao_preco_adega(corrompido, "balcao")
                self.assertEqual(explicacao["rotulo"], "Natural · Legado")
                self.assertIn("Regra histórica indisponível", explicacao["detalhe"])
                self.assertEqual(explicacao["economia_cent"], 0)
        self.assertEqual(self.item(), item)

    def test_promocao_json_v1_sem_campos_da_regra_tem_fallback_seguro(self):
        self.promover()
        self.lancar()
        item = self.item()
        regra = self.retrato()
        for campo in ("criterio", "inicio", "fim"):
            with self.subTest(campo=campo):
                base = {k: v for k, v in regra["base"].items() if k != campo}
                corrompido = {**item, "regra_preco_json": json.dumps({**regra, "base": base})}
                self.assertIsNone(ProdutoController.ler_regra_preco(corrompido))
                self.assertIn("Legado", ProdutoController.explicacao_preco_adega(corrompido, "balcao")["rotulo"])

    def test_reprecificacao_legado_registra_so_regra_nova_sem_inventar_origem_base(self):
        self.banco.cfg_set("agrupar_itens_balcao", "N")
        item = self.lancar(5)
        self.banco.executar("UPDATE itens_venda SET regra_preco_json = NULL WHERE id = ?", (item,))
        self.lancar()
        regra = self.retrato(item)
        self.assertEqual((regra["tipo"], regra["base"]["tipo"]), ("atacado", "legado"))
        self.assertEqual(regra["leituras"], [])
        self.assertIn("origem histórica", ProdutoController.explicacao_preco_adega(self.item(item), "balcao")["detalhe"])

    def test_fora_do_balcao_registra_base_sem_aplicar_atacado(self):
        self.banco.atualizar("vendas", self.vid, {"modalidade": "entrega"})
        self.lancar(6)
        self.assertEqual((self.retrato()["tipo"], self.item()["preco_unit_cent"]), ("normal", 800))
        self.assertIsNone(self.retrato()["minimo_qtd"])

    def test_consulta_historica_funciona_apos_excluir_produto(self):
        self.lancar(6)
        self.pagar(self.vid, "Dinheiro", 3900)
        self.caixa.fechar(self.vid)
        self.banco.executar("DELETE FROM produtos WHERE id = ?", (self.skol,))
        item = self.caixa.itens(self.vid)[0]
        self.assertIsNone(item["atacado_qtd"])
        explicacao = ProdutoController.explicacao_preco_adega(item, "balcao")
        self.assertIn("a partir de 6 un", explicacao["detalhe"])
        self.assertEqual(explicacao["economia_cent"], 900)

    def test_volume_reprecifica_em_lote_e_nao_regrava_retrato_estavel(self):
        """Regressão de custo: uma consulta de itens, escrita linear e segunda passagem sem escrita."""
        self.banco.cfg_set("agrupar_itens_balcao", "N")
        modelos = [self.item(self.lancar(temperatura=t)) for t in ("natural", "gelada")]
        for item in modelos:
            item.pop("id")
            for _ in range(119):
                self.banco.inserir("itens_venda", item)
        with patch.object(self.banco, "todos", wraps=self.banco.todos) as consultas, \
                patch.object(self.banco, "atualizar", wraps=self.banco.atualizar) as retratos, \
                patch.object(self.banco, "executar", wraps=self.banco.executar) as precos:
            self.caixa._reprecificar_balcao(self.vid)
            self.assertEqual(consultas.call_count, 1)
            self.assertEqual(retratos.call_count, 240)
            self.assertEqual(precos.call_count, 240)
            consultas.reset_mock()
            retratos.reset_mock()
            precos.reset_mock()
            self.avancar(minutes=1)
            self.caixa._reprecificar_balcao(self.vid)
            self.assertEqual(consultas.call_count, 1)
            self.assertEqual(retratos.call_count, 0)
            self.assertEqual(precos.call_count, 0)
        itens = self.caixa.itens(self.vid)
        self.assertEqual(len(itens), 240)
        self.assertEqual({i["preco_unit_cent"] for i in itens if i["temperatura"] == "natural"}, {650})
        self.assertEqual({i["preco_unit_cent"] for i in itens if i["temperatura"] == "gelada"}, {850})
        self.assertEqual({json.loads(i["regra_preco_json"])["quantidade_grupo"] for i in itens}, {120})
        with patch.object(self.banco, "todos", side_effect=AssertionError("Consulta indevida")), \
                patch.object(self.banco, "um", side_effect=AssertionError("Consulta indevida")):
            explicacoes = [ProdutoController.explicacao_preco_adega(i, "balcao") for i in itens]
        self.assertEqual(sum(e["economia_cent"] for e in explicacoes), 36000)

    def test_volume_agrupado_preserva_todas_as_leituras_sem_mudar_cobranca(self):
        primeiro = self.lancar()
        for _ in range(99):
            self.assertEqual(self.lancar(), primeiro)
        item = self.item()
        regra = self.retrato()
        self.assertEqual((item["quantidade"], item["preco_unit_cent"], item["total_cent"]), (100, 650, 65000))
        self.assertEqual(len(regra["leituras"]), 100)
        self.assertEqual(sum(l["quantidade"] for l in regra["leituras"]), 100)
        self.assertEqual(len(self.caixa.itens(self.vid)), 1)
        self.assertEqual(self.caixa.obter(self.vid)["total_cent"], 65000)

    def test_migracao_v23_nao_inventa_regra_e_mantem_backup_reabrivel(self):
        self.lancar(6)
        self.pagar(self.vid, "Dinheiro", 3900)
        self.caixa.fechar(self.vid)
        cancelada = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(cancelada, self.skol, 2)
        self.caixa.cancelar_venda(cancelada)
        with tempfile.TemporaryDirectory(dir=".") as pasta:
            caminho = Path(pasta) / "v23.db"
            antigo = BancoDados(str(caminho))
            self.banco.conexao.backup(antigo.conexao)
            antigo.executar("ALTER TABLE itens_venda DROP COLUMN regra_preco_json")
            antigo.executar("PRAGMA user_version = 23")
            valores = [tuple(r) for r in antigo.todos(
                "SELECT preco_unit_cent, total_cent, preco_base_cent FROM itens_venda ORDER BY id")]
            vendas = [tuple(r) for r in antigo.todos("SELECT uuid, status, total_cent FROM vendas ORDER BY id")]
            antigo.fechar()
            migrado = BancoDados(str(caminho))
            try:
                self.assertEqual(migrado.valor("PRAGMA user_version"), 24)
                self.assertEqual(migrado.valor(
                    "SELECT COUNT(*) FROM itens_venda WHERE regra_preco_json IS NOT NULL"), 0)
                self.assertEqual([tuple(r) for r in migrado.todos(
                    "SELECT preco_unit_cent, total_cent, preco_base_cent FROM itens_venda ORDER BY id")], valores)
                self.assertEqual([tuple(r) for r in migrado.todos(
                    "SELECT uuid, status, total_cent FROM vendas ORDER BY id")], vendas)
                self.assertEqual(migrado.valor("PRAGMA integrity_check"), "ok")
                self.assertEqual(migrado.todos("PRAGMA foreign_key_check"), [])
            finally:
                migrado.fechar()
            import sqlite3
            copias = list(Path(pasta).glob("*.bak"))
            self.assertEqual(len(copias), 1)
            with closing(sqlite3.connect(copias[0])) as backup:
                self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 23)
                self.assertNotIn("regra_preco_json", [r[1] for r in backup.execute("PRAGMA table_info(itens_venda)")])
            reaberto = BancoDados(str(caminho))
            reaberto.fechar()
            self.assertEqual(len(list(Path(pasta).glob("*.bak"))), 1)
