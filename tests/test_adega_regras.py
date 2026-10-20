"""Preços por temperatura, atacado, leituras repetidas e cascos na adega."""
from __future__ import annotations

import tempfile
from pathlib import Path

from src.controllers.perfil_controller import PerfilController
from src.controllers.produto_controller import ProdutoController
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from tests.test_caixa import BaseCaixa


class TesteRegrasAdega(BaseCaixa):
    def setUp(self):
        super().setUp()
        PerfilController(self.banco, self.adm).aplicar("adega")
        self.banco.executar(
            """UPDATE produtos SET preco_gelada_cent = 1000, atacado_qtd = 6,
               preco_atacado_cent = 650, atacado_gelada_qtd = 6,
               preco_atacado_gelada_cent = 850 WHERE id = ?""", (self.skol,))
        self.vid = self.caixa.abrir_balcao()

    def lancar(self, qtd=1, **kw):
        return self.caixa.adicionar_item(self.vid, self.skol, qtd, **kw)

    def test_explicacao_preco_por_temperatura_e_faixa(self):
        for temperatura in ("natural", "gelada"):
            self.lancar(6, temperatura=temperatura)
        for item in self.caixa.itens(self.vid):
            explicacao = ProdutoController.explicacao_preco_adega(item, "balcao")
            self.assertEqual(explicacao["rotulo"], f"{item['temperatura'].capitalize()} · Atacado")
            self.assertIn("a partir de 6 un da mesma bebida/temperatura", explicacao["detalhe"])
            self.assertEqual(explicacao["economia_cent"], 900)
            self.assertIn("R$ 9,00", explicacao["detalhe"])

    def test_explicacao_preserva_promocao_entrega_e_item_migrado(self):
        self.lancar()
        item = self.caixa.itens(self.vid)[0]
        for alteracoes, modalidade in (({}, "balcao"), ({"preco_base_cent": None}, "balcao"),
                                      ({"preco_unit_cent": 650, "total_cent": 650}, "entrega"),
                                      ({"preco_base_cent": 600, "preco_unit_cent": 600}, "balcao")):
            with self.subTest(alteracoes=alteracoes, modalidade=modalidade):
                explicacao = ProdutoController.explicacao_preco_adega({**item, **alteracoes}, modalidade)
                self.assertEqual(explicacao, {"rotulo": "Natural", "detalhe": "", "economia_cent": 0})

    def test_explicacao_faixa_fracionada_e_arredondamento_da_linha(self):
        item = {"temperatura": "gelada", "preco_base_cent": 1000, "preco_unit_cent": 850,
                "quantidade": 1.0001, "total_cent": 850, "atacado_gelada_qtd": 1.0001}
        explicacao = ProdutoController.explicacao_preco_adega(item, "balcao")
        self.assertIn("a partir de 1,0001 un", explicacao["detalhe"])
        self.assertEqual(explicacao["economia_cent"], 150)

    def test_perfil_adega_liga_agrupamento_mas_boate_nao(self):
        self.assertTrue(self.banco.cfg_bool("agrupar_itens_balcao"))
        PerfilController(self.banco, self.adm).aplicar("boate")
        self.assertFalse(self.banco.cfg_bool("agrupar_itens_balcao"))

    def test_leituras_repetidas_sao_uma_linha(self):
        primeiro = self.lancar()
        self.assertEqual(self.lancar(2), primeiro)
        itens = self.caixa.itens(self.vid)
        self.assertEqual(len(itens), 1)
        self.assertEqual((itens[0]["quantidade"], itens[0]["total_cent"]), (3, 2400))

    def test_agrupamento_pode_ser_desligado(self):
        self.banco.cfg_set("agrupar_itens_balcao", "N")
        self.assertNotEqual(self.lancar(), self.lancar())
        self.assertEqual(len(self.caixa.itens(self.vid)), 2)

    def test_limite_por_linha_nao_impede_nova_leitura(self):
        self.banco.cfg_set("qtd_maxima_item", 2)
        self.lancar(2)
        self.lancar()
        self.assertEqual([i["quantidade"] for i in self.caixa.itens(self.vid)], [2, 1])

    def test_observacoes_diferentes_nao_se_agrupam(self):
        self.lancar(observacao="Separar")
        self.lancar(observacao="Entregar")
        self.assertEqual(len(self.caixa.itens(self.vid)), 2)

    def test_item_preparado_nao_se_agrupa(self):
        primeiro = self.lancar()
        self.banco.executar("UPDATE itens_venda SET status_preparo = 'entregue' WHERE id = ?", (primeiro,))
        self.assertNotEqual(self.lancar(), primeiro)

    def test_impressao_remota_nao_recebe_quantidade_acumulada(self):
        subgrupo = self.prod.por_id(self.skol)["subgrupo_id"]
        self.banco.executar("UPDATE subgrupos SET impressora_remota = 1 WHERE id = ?", (subgrupo,))
        self.assertNotEqual(self.lancar(), self.lancar())
        self.assertEqual([i["quantidade"] for i in self.caixa.itens(self.vid)], [1, 1])

    def test_atacado_exatamente_no_minimo_reprecifica_todas(self):
        self.lancar(5)
        self.assertEqual(self.caixa.obter(self.vid)["total_cent"], 4000)
        self.lancar()
        item = self.caixa.itens(self.vid)[0]
        self.assertEqual((item["quantidade"], item["preco_unit_cent"], item["total_cent"]), (6, 650, 3900))
        self.assertEqual(item["preco_base_cent"], 800)

    def test_atacado_soma_linhas_sem_agrupamento(self):
        self.banco.cfg_set("agrupar_itens_balcao", "N")
        self.lancar(3)
        self.lancar(3)
        self.assertEqual([i["preco_unit_cent"] for i in self.caixa.itens(self.vid)], [650, 650])

    def test_cancelar_abaixo_do_minimo_restaura_preco(self):
        self.banco.cfg_set("agrupar_itens_balcao", "N")
        self.lancar(5)
        ultimo = self.lancar()
        self.caixa.cancelar_item(ultimo)
        self.assertEqual(self.caixa.obter(self.vid)["total_cent"], 4000)
        self.assertEqual(self.caixa.itens(self.vid)[0]["preco_unit_cent"], 800)

    def test_natural_e_gelada_nao_somam_minimo(self):
        self.lancar(3)
        self.lancar(3, temperatura="gelada")
        itens = self.caixa.itens(self.vid)
        self.assertEqual([i["preco_unit_cent"] for i in itens], [800, 1000])
        self.assertEqual([i["temperatura"] for i in itens], ["natural", "gelada"])
        self.assertIn("Gelada", itens[1]["observacao"])

    def test_gelada_tem_seu_proprio_atacado(self):
        self.lancar(6, temperatura="gelada")
        self.assertEqual(self.caixa.obter(self.vid)["total_cent"], 5100)

    def test_observacao_editada_preserva_temperatura_no_cupom(self):
        item = self.lancar(temperatura="gelada")
        for texto, esperado in (("Separar", "Gelada - Separar"), ("Gelada - Separar", "Gelada - Separar"),
                                (None, "Gelada")):
            self.caixa.definir_observacao(item, texto)
            self.assertEqual(self.caixa.itens(self.vid)[0]["observacao"], esperado)

    def test_minimo_fracionado_exato_sem_somar_temperaturas(self):
        self.banco.executar(
            "UPDATE produtos SET aceita_decimal = 1, atacado_qtd = 1.0001 WHERE id = ?", (self.skol,))
        self.lancar(0.5)
        self.lancar(0.5)
        self.assertEqual(self.caixa.itens(self.vid)[0]["preco_unit_cent"], 800)
        self.lancar(0.0001)
        item = self.caixa.itens(self.vid)[0]
        self.assertEqual((item["quantidade"], item["preco_unit_cent"], item["total_cent"]), (1.0001, 650, 650))

    def test_atacado_nao_aumenta_promocao_melhor(self):
        self.banco.executar(
            "UPDATE produtos SET promo_de = '2026-01-01', promo_ate = '2026-12-31', promo_preco_cent = 600 WHERE id = ?",
            (self.skol,))
        self.lancar(6)
        self.assertEqual(self.caixa.itens(self.vid)[0]["preco_unit_cent"], 600)

    def test_mudanca_de_preco_nao_altera_base_das_leituras_anteriores(self):
        self.lancar(2)
        self.banco.executar("UPDATE produtos SET preco_cent = 900 WHERE id = ?", (self.skol,))
        self.lancar(2)
        self.assertEqual([i["preco_unit_cent"] for i in self.caixa.itens(self.vid)], [800, 900])

    def test_itens_antigos_sem_base_nao_sao_reprecificados(self):
        item = self.lancar()
        self.banco.executar("UPDATE itens_venda SET preco_base_cent = NULL WHERE id = ?", (item,))
        self.lancar(6)
        self.assertEqual([i["preco_unit_cent"] for i in self.caixa.itens(self.vid)], [800, 650])

    def test_estoque_compartilhado_e_estorno(self):
        self.lancar(2)
        self.lancar(3, temperatura="gelada")
        self.pagar(self.vid, "Dinheiro", self.caixa.obter(self.vid)["total_cent"])
        self.caixa.fechar(self.vid)
        self.assertEqual(self.prod.por_id(self.skol)["qt_atual"], 95)
        self.caixa.cancelar_venda(self.vid)
        self.assertEqual(self.prod.por_id(self.skol)["qt_atual"], 100)

    def test_casco_cobrado_apenas_para_unidades_sem_troca(self):
        casco = self.novo_produto("CASCO 600 ML", 500, estoque=True, qt=20)
        self.banco.executar("UPDATE produtos SET casco_produto_id = ? WHERE id = ?", (casco, self.skol))
        self.lancar(4, quantidade_cascos=2)
        itens = self.caixa.itens(self.vid)
        self.assertEqual([(i["produto_id"], i["quantidade"]) for i in itens], [(self.skol, 4), (casco, 2)])
        self.assertEqual(self.caixa.obter(self.vid)["total_cent"], 4200)
        self.pagar(self.vid, "Dinheiro", 4200)
        self.caixa.fechar(self.vid)
        self.assertEqual(self.prod.por_id(casco)["qt_atual"], 18)

    def test_troca_integral_nao_lanca_casco(self):
        casco = self.novo_produto("CASCO", 500)
        self.banco.executar("UPDATE produtos SET casco_produto_id = ? WHERE id = ?", (casco, self.skol))
        self.lancar(2, quantidade_cascos=0)
        self.assertEqual(len(self.caixa.itens(self.vid)), 1)

    def test_produto_com_casco_nao_vira_fardo_nem_composicao_depois(self):
        casco = self.novo_produto("CASCO", 500)
        self.banco.executar("UPDATE produtos SET casco_produto_id = ? WHERE id = ?", (casco, self.skol))
        quantidade_produtos = self.banco.valor("SELECT COUNT(*) FROM produtos")
        with self.assertRaisesRegex(ErroNegocio, "casco"):
            self.prod.criar_embalagem(self.skol, 12, "FARDO", 6000)
        for produto, insumo in ((self.skol, self.agua), (self.agua, self.skol)):
            with self.assertRaisesRegex(ErroNegocio, "casco"):
                self.prod.incluir_composicao(produto, insumo, 2)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), quantidade_produtos)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM composicoes"), 0)

    def test_casco_invalido_nao_deixa_venda_parcial(self):
        for qtd in (-1, 3, 1.5, True):
            with self.assertRaises(ErroNegocio):
                self.lancar(2, quantidade_cascos=qtd)
        with self.assertRaises(ErroNegocio):
            self.lancar(2, quantidade_cascos=1)
        self.assertEqual(self.caixa.itens(self.vid), [])

    def test_falha_no_lancamento_casco_desfaz_bebida(self):
        casco = self.novo_produto("CASCO", 500)
        self.banco.executar("UPDATE produtos SET casco_produto_id = ? WHERE id = ?", (casco, self.skol))
        from unittest.mock import patch
        original = self.prod.preco_vigente

        def preco(produto, quando=None):
            if produto["id"] == casco:
                raise ErroNegocio("Falha no casco")
            return original(produto, quando)

        with patch.object(self.caixa.produtos, "preco_vigente", side_effect=preco):
            with self.assertRaisesRegex(ErroNegocio, "Falha no casco"):
                self.lancar(2, quantidade_cascos=1)
        self.assertEqual(self.caixa.itens(self.vid), [])
        self.assertEqual(self.caixa.obter(self.vid)["total_cent"], 0)

    def test_temperatura_invalida_ou_sem_preco_nao_lanca(self):
        for pid, temperatura in ((self.skol, "fria"), (self.agua, "gelada")):
            with self.assertRaises(ErroNegocio):
                self.caixa.adicionar_item(self.vid, pid, 1, temperatura=temperatura)
        self.assertEqual(self.caixa.itens(self.vid), [])

    def test_tabela_de_precos_mostra_gelada_e_atacado(self):
        from src.controllers.impressao_controller import ImpressaoController
        texto = ImpressaoController(self.banco).tabela_precos()
        linhas = [l.strip() for l in texto.splitlines()]
        i = next(n for n, l in enumerate(linhas) if "SKOL" in l)
        self.assertTrue(linhas[i].endswith("8,00"))
        self.assertEqual(linhas[i + 1].split(), ["gelada", "10,00"])
        self.assertEqual(linhas[i + 2].split(), ["atacado", "a", "partir", "de", "6", "6,50"])
        self.assertEqual(linhas[i + 3].split(), ["atacado", "gelada", "a", "partir", "de", "6", "8,50"])
        j = next(n for n, l in enumerate(linhas) if "AGUA" in l)              # sem gelada nem atacado: uma linha só
        self.assertFalse(j + 1 < len(linhas) and "gelada" in linhas[j + 1])

    def test_mesas_preservam_itens_separados_sem_atacado(self):
        self.banco.cfg_set("usar_mesas", "S")
        vid, _ = self.caixa.abrir_mesa(1)
        self.caixa.adicionar_item(vid, self.skol, 3)
        self.caixa.adicionar_item(vid, self.skol, 3)
        self.assertEqual([i["preco_unit_cent"] for i in self.caixa.itens(vid)], [800, 800])
        self.assertEqual(len(self.caixa.itens(vid)), 2)

    def test_migracao_v21_preserva_produtos_e_precos_de_itens(self):
        self.lancar()
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "antigo.db"
            antigo = BancoDados(str(caminho))
            self.banco.conexao.backup(antigo.conexao)
            for tabela in ("produtos", "itens_venda"):
                for operacao in ("insert", "update", "delete"):
                    antigo.executar(f"DROP TRIGGER auditoria_{tabela}_{operacao}")
            for coluna in ("preco_gelada_cent", "atacado_qtd", "preco_atacado_cent",
                           "atacado_gelada_qtd", "preco_atacado_gelada_cent", "casco_produto_id"):
                antigo.executar(f"ALTER TABLE produtos DROP COLUMN {coluna}")
            for coluna in ("preco_base_cent", "temperatura"):
                antigo.executar(f"ALTER TABLE itens_venda DROP COLUMN {coluna}")
            antigo.executar("DELETE FROM config WHERE chave = 'agrupar_itens_balcao'")
            antigo.executar("PRAGMA user_version = 21")
            antigo.fechar()
            migrado = BancoDados(str(caminho))
            try:
                self.assertEqual(migrado.valor("PRAGMA user_version"), 22)
                self.assertTrue(migrado.cfg_bool("agrupar_itens_balcao"))
                item = migrado.um("SELECT * FROM itens_venda WHERE venda_id = ?", (self.vid,))
                self.assertEqual((item["preco_unit_cent"], item["preco_base_cent"], item["temperatura"]),
                                 (800, None, "natural"))
                self.assertEqual(migrado.valor("PRAGMA integrity_check"), "ok")
                self.assertEqual(migrado.todos("PRAGMA foreign_key_check"), [])
                self.assertEqual(len(list(Path(pasta).glob("*.bak"))), 1)
            finally:
                migrado.fechar()
