"""Bandeira 2: preço da noite que o dono liga e desliga (pelo painel, que manda ao caixa, ou no próprio caixa).

Ligada, o produto que entra nela sai pelo preço próprio da bandeira 2 ou, sem ele, com o acréscimo padrão; promoções e
atacado ficam suspensos nesse produto. Itens já lançados não mudam."""
from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.controllers.caixa_controller import CaixaController
from src.controllers.produto_controller import ProdutoController
from src.controllers.retaguarda_controller import CHAVE_LIGADA, RetaguardaController
from src.controllers.turno_controller import TurnoController
from src.core.erros import ErroValidacao
from tests.base import BaseTeste


class BaseBandeira(BaseTeste):
    agora = datetime(2026, 11, 23, 23, 30, 0)

    def setUp(self):
        super().setUp()
        self.op = self.operador_adm()
        self.produtos = ProdutoController(self.banco)
        self.skol = self.novo_produto("SKOL LATA", 500, preco_gelada_cent="6,00")
        self.cigarro = self.novo_produto("CIGARRO", 1200, bandeira2="N")
        self.whisky = self.novo_produto("WHISKY DOSE", 2000, preco_bandeira2_cent="25,00")

    def ligar(self, pct="20"):
        self.banco.cfg_set("bandeira2_ativa", "S")
        self.banco.cfg_set("bandeira2_pct", pct)

    def p(self, pid):
        return self.produtos.por_id(pid)


class TestePreco(BaseBandeira):
    def test_desligada_nada_muda(self):
        self.assertEqual((self.produtos.preco_vigente(self.p(self.skol)), self.produtos.preco_vigente(self.p(self.whisky))),
                         (500, 2000))

    def test_ligada_usa_o_preco_proprio_ou_o_acrescimo_padrao(self):
        self.ligar("20")
        self.assertEqual(self.produtos.preco_vigente(self.p(self.skol)), 600)          # 5,00 + 20%
        self.assertEqual(self.produtos.preco_gelada_vigente(self.p(self.skol)), 720)   # 6,00 + 20%
        self.assertEqual(self.produtos.preco_vigente(self.p(self.whisky)), 2500)       # preço próprio vale mais
        self.assertEqual(self.produtos.preco_vigente(self.p(self.cigarro)), 1200)      # fora da bandeira 2

    def test_acrescimo_arredonda_em_centavos(self):
        quebrado = self.novo_produto("AGUA", 333)
        self.ligar("15")
        self.assertEqual(self.produtos.preco_vigente(self.p(quebrado)), 383)          # 3,8295 -> 3,83

    def test_suspende_as_promocoes_do_produto_que_muda(self):
        self.banco.executar("UPDATE produtos SET hora_ini = '22:00', hora_fim = '23:59', hora_preco_cent = 400 "
                            "WHERE id IN (?, ?)", (self.skol, self.cigarro))
        self.assertEqual(self.produtos.preco_vigente(self.p(self.skol)), 400)          # happy hour sem a bandeira
        self.ligar("20")
        regra = self.produtos.regra_preco_vigente(self.p(self.skol), bandeira=self.produtos.bandeira2())
        self.assertEqual((regra["tipo"], regra["preco_cent"]), ("bandeira2", 600))
        self.banco.executar("UPDATE produtos SET hora_preco_cent = 1000 WHERE id = ?", (self.cigarro,))
        self.assertEqual(self.produtos.preco_vigente(self.p(self.cigarro)), 1000)      # fora da bandeira: promoção vale

    def test_sem_acrescimo_e_sem_preco_proprio_o_produto_segue_normal(self):
        self.banco.executar("UPDATE produtos SET hora_ini = '22:00', hora_fim = '23:59', hora_preco_cent = 400 "
                            "WHERE id = ?", (self.skol,))
        self.ligar("0")
        self.assertEqual(self.produtos.preco_vigente(self.p(self.skol)), 400)
        self.assertEqual(self.produtos.preco_vigente(self.p(self.whisky)), 2500)

    def test_cadastro_recusa_preco_negativo_e_gelada_sem_preco_gelado(self):
        from src.controllers.cadastro_controller import CadastroController
        with self.assertRaises(ErroValidacao):
            CadastroController(self.banco).salvar("produtos", {"preco_gelada_bandeira2_cent": "7,00"}, self.cigarro)
        with self.assertRaises(ErroValidacao):
            CadastroController(self.banco).salvar("produtos", {"preco_bandeira2_cent": "-1,00"}, self.cigarro)

    def test_configuracao_do_percentual(self):
        from src.controllers.config_controller import ConfigController
        ConfigController(self.banco).salvar_config({"bandeira2_ativa": "S", "bandeira2_pct": "12,5"})
        self.assertEqual(self.produtos.preco_vigente(self.p(self.skol)), 563)          # 5,625 -> 5,63
        with self.assertRaises(ErroValidacao):
            ConfigController(self.banco).salvar_config({"bandeira2_pct": "150"})


class TesteCaixa(BaseBandeira):
    def setUp(self):
        super().setUp()
        TurnoController(self.banco).abrir(self.op, 1, 0)
        self.caixa = CaixaController(self.banco, self.op)

    def item(self, item_id):
        return self.banco.um("SELECT * FROM itens_venda WHERE id = ?", (item_id,))

    def test_lanca_pelo_preco_da_noite_e_o_ja_lancado_nao_muda(self):
        venda = self.caixa.abrir_balcao()
        antes = self.caixa.adicionar_item(venda, self.skol, 1)
        self.ligar("20")
        depois = self.caixa.adicionar_item(venda, self.skol, 1, temperatura="gelada")
        self.assertEqual((self.item(antes)["preco_unit_cent"], self.item(depois)["preco_unit_cent"]), (500, 720))
        self.banco.cfg_set("bandeira2_ativa", "N")
        self.caixa.adicionar_item(venda, self.cigarro, 1)                  # reprecificar não desfaz a bandeira já lançada
        self.assertEqual(self.item(depois)["preco_unit_cent"], 720)
        explicacao = ProdutoController.explicacao_preco_adega(dict(self.item(depois)), "balcao")
        self.assertIn("Bandeira 2", explicacao["rotulo"])
        self.assertIn("promoções e atacado suspensos", explicacao["detalhe"])

    def test_atacado_fica_suspenso_na_bandeira(self):
        self.banco.executar("UPDATE produtos SET atacado_qtd = 6, preco_atacado_cent = 400 WHERE id = ?", (self.skol,))
        self.ligar("20")
        venda = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(venda, self.skol, 6)
        self.assertEqual(self.banco.valor("SELECT total_cent FROM vendas WHERE id = ?", (venda,)), 3600)   # 6 x 6,00

    def test_sem_bandeira_o_atacado_continua(self):
        self.banco.executar("UPDATE produtos SET atacado_qtd = 6, preco_atacado_cent = 400 WHERE id = ?", (self.skol,))
        venda = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(venda, self.skol, 6)
        self.assertEqual(self.banco.valor("SELECT total_cent FROM vendas WHERE id = ?", (venda,)), 2400)


class TestePainelECardapio(BaseBandeira):
    def test_dono_liga_pelo_painel_e_escolhe_produto(self):
        self.banco.cfg_set(CHAVE_LIGADA, "S")
        retaguarda = RetaguardaController(self.banco, self.op)
        chaves = {c["chave"] for c in retaguarda.esquema()["config"]["campos"]}
        self.assertTrue({"bandeira2_ativa", "bandeira2_pct"} <= chaves)
        produtos = next(e for e in retaguarda.esquema()["entidades"] if e["chave"] == "produtos")
        self.assertTrue({"bandeira2", "preco_bandeira2_cent", "preco_gelada_bandeira2_cent"}
                        <= {c["nome"] for c in produtos["campos"]})
        r = retaguarda.aplicar({"id": 1, "tipo": "config.salvar",
                                "dados": {"valores": {"bandeira2_ativa": "S", "bandeira2_pct": "10"}}})
        self.assertEqual(r["situacao"], "aplicado", r)
        r = retaguarda.aplicar({"id": 2, "tipo": "cadastro.salvar", "dados": {
            "entidade": "produtos", "id": self.skol, "valores": {"preco_bandeira2_cent": 700}}})
        self.assertEqual(r["situacao"], "aplicado", r)
        self.assertEqual(self.produtos.preco_vigente(self.p(self.skol)), 700)
        self.assertEqual(self.produtos.preco_vigente(self.p(self.cigarro)), 1200)
        retaguarda.aplicar({"id": 3, "tipo": "config.salvar", "dados": {"valores": {"bandeira2_ativa": "N"}}})
        self.assertEqual(self.produtos.preco_vigente(self.p(self.skol)), 500)

    def test_cardapio_online_sobe_o_preco_da_noite_sem_promocao(self):
        from src.sync import cardapio_envio
        self.banco.executar("UPDATE produtos SET hora_ini = '22:00', hora_fim = '23:59', hora_preco_cent = 400 "
                            "WHERE id = ?", (self.skol,))
        normal = next(p for p in cardapio_envio.coletar(self.banco)["produtos"] if p["nome"] == "SKOL LATA")
        self.assertEqual((normal["preco_cent"], normal["hora_preco_cent"]), (500, 400))
        self.ligar("20")
        noite = next(p for p in cardapio_envio.coletar(self.banco)["produtos"] if p["nome"] == "SKOL LATA")
        self.assertEqual((noite["preco_cent"], noite["hora_preco_cent"], noite["preco_gelada_cent"]), (600, 0, 720))
        cigarro = next(p for p in cardapio_envio.coletar(self.banco)["produtos"] if p["nome"] == "CIGARRO")
        self.assertEqual(cigarro["preco_cent"], 1200)


from tests.test_qt_caixa import BaseCaixaQt  # noqa: E402


class TesteAvisoNoCaixa(BaseCaixaQt):
    def test_aviso_bandeira_2_aparece_e_some_sem_reabrir_o_caixa(self):
        self.abrir_turno()
        janela = self.janela()
        self.assertTrue(janela.lbl_bandeira2.isHidden())
        self.banco.cfg_set("bandeira2_ativa", "S")
        janela.atualizar_bandeira2()                       # o relógio de 5 s chama sozinho
        self.assertFalse(janela.lbl_bandeira2.isHidden())
        self.banco.cfg_set("bandeira2_ativa", "N")
        janela.atualizar_bandeira2()
        self.assertTrue(janela.lbl_bandeira2.isHidden())
