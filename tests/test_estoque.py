"""Produtos (busca, preço vigente, composição) e lançamentos de estoque."""
from __future__ import annotations

from datetime import datetime

from src.controllers.estoque_controller import EstoqueController
from src.controllers.produto_controller import ProdutoController
from src.core.erros import ErroNegocio
from tests.base import BaseTeste


class TesteProdutos(BaseTeste):
    def setUp(self):
        super().setUp()
        self.prod = ProdutoController(self.banco)

    def test_busca_por_codigo_barras_atalho_e_nome(self):
        a = self.novo_produto("COCA COLA", 350, codigo="7", cbarra="7894900011517", atalho="cc")
        self.novo_produto("COCA ZERO", 400)
        self.assertEqual(self.prod.buscar_codigo("7")["id"], a)              # sem zeros
        self.assertEqual(self.prod.buscar_codigo("0000000000007")["id"], a)
        self.assertEqual(self.prod.buscar_codigo("7894900011517")["id"], a)  # leitor óptico
        self.assertEqual(self.prod.buscar_codigo("CC")["id"], a)             # atalho
        self.assertIsNone(self.prod.buscar_codigo("999"))
        nomes = [p["nome"] for p in self.prod.pesquisar("coca")]
        self.assertEqual(nomes, ["COCA COLA", "COCA ZERO"])

    def test_produto_fora_de_venda_nao_e_encontrado_no_caixa(self):
        pid = self.novo_produto("SAZONAL", 500, venda="N")
        self.assertIsNone(self.prod.buscar_codigo(self.prod.por_id(pid)["codigo"]))
        self.assertIsNotNone(self.prod.buscar_codigo(self.prod.por_id(pid)["codigo"], apenas_venda=False))

    def test_preco_promocional_por_horario_virando_a_meia_noite(self):
        pid = self.novo_produto("CERVEJA", 1000, hora_ini="22:00", hora_fim="02:00", hora_preco_cent="7,00")
        p = self.prod.por_id(pid)
        self.assertEqual(self.prod.preco_vigente(p, datetime(2026, 10, 3, 23, 0)), 700)
        self.assertEqual(self.prod.preco_vigente(p, datetime(2026, 10, 4, 1, 30)), 700)
        self.assertEqual(self.prod.preco_vigente(p, datetime(2026, 10, 3, 15, 0)), 1000)

    def test_preco_promocional_por_dia_da_semana_e_periodo(self):
        # sexta(6) a domingo(1) -> faixa que dá a volta na semana
        pid = self.novo_produto("DOSE", 1500, sem_inicial="6", sem_final="1", sem_preco_cent="12,00")
        p = self.prod.por_id(pid)
        self.assertEqual(self.prod.preco_vigente(p, datetime(2026, 10, 3, 20)), 1200)  # sábado
        self.assertEqual(self.prod.preco_vigente(p, datetime(2026, 10, 5, 20)), 1500)  # segunda
        pid2 = self.novo_produto("AGUA", 500, promo_de="01/10/2026", promo_ate="05/10/2026", promo_preco_cent="3,50")
        p2 = self.prod.por_id(pid2)
        self.assertEqual(self.prod.preco_vigente(p2, datetime(2026, 10, 5, 23, 59)), 350)
        self.assertEqual(self.prod.preco_vigente(p2, datetime(2026, 10, 6, 0, 1)), 500)

    def test_situacao_de_estoque_cores(self):
        base = {"qt_atual": 10, "estoque_minimo": 5}
        self.assertEqual(self.prod.situacao_estoque(base), "normal")
        self.assertEqual(self.prod.situacao_estoque({**base, "qt_atual": 5}), "ponto")
        self.assertEqual(self.prod.situacao_estoque({**base, "qt_atual": 0}), "sem")
        self.assertEqual(self.prod.situacao_estoque({**base, "qt_atual": -2}), "sem")

    def test_composicao_valida_estoque_e_ciclos(self):
        cafe = self.novo_produto("CAFE EXPRESSO", 450)
        grao = self.novo_produto("GRAO DE CAFE", 0, estoque=True)
        sem_estoque = self.novo_produto("COPO", 0)
        self.prod.incluir_composicao(cafe, grao, 0.01)
        with self.assertRaises(ErroNegocio):
            self.prod.incluir_composicao(cafe, sem_estoque, 1)       # insumo precisa estar no estoque
        with self.assertRaises(ErroNegocio):
            self.prod.incluir_composicao(cafe, cafe, 1)
        with self.assertRaises(ErroNegocio):
            self.prod.incluir_composicao(grao, cafe, 1)              # ciclo
        with self.assertRaises(ErroNegocio):
            self.prod.incluir_composicao(cafe, grao, 0.02)           # duplicado

    def test_custo_pela_composicao(self):
        cafe = self.novo_produto("CAFE", 450)
        grao = self.novo_produto("GRAO", 0, estoque=True)
        leite = self.novo_produto("LEITE", 0, estoque=True)
        self.banco.executar("UPDATE produtos SET ult_preco_cent = 8000 WHERE id = ?", (grao,))   # R$ 80/kg
        self.banco.executar("UPDATE produtos SET ult_preco_cent = 500 WHERE id = ?", (leite,))   # R$ 5/L
        self.prod.incluir_composicao(cafe, grao, 0.01)    # 10 g
        self.prod.incluir_composicao(cafe, leite, 0.1)    # 100 ml
        self.assertEqual(self.prod.custo(cafe), 80 + 50)


class TesteEstoque(BaseTeste):
    def setUp(self):
        super().setUp()
        self.est = EstoqueController(self.banco, self.operador_adm())
        self.prod = ProdutoController(self.banco)
        self.forn = self.banco.inserir("fornecedores", {"nome": "AMBEV"})

    def qt(self, pid):
        return self.prod.por_id(pid)["qt_atual"]

    def lancar(self, tipo, itens, **kw):
        lid = self.est.criar_lancamento(tipo, fornecedor_id=self.forn if tipo in ("compra", "pedido") else None, **kw)
        ids = [self.est.adicionar_item(lid, *i) for i in itens]
        return lid, ids

    def test_compra_soma_estoque_e_atualiza_ultimo_preco(self):
        pid = self.novo_produto("SKOL", 800, estoque=True)
        self.lancar("compra", [(pid, 24, 4800)])           # 24 un por R$ 48,00
        p = self.prod.por_id(pid)
        self.assertEqual(p["qt_atual"], 24)
        self.assertEqual(p["ult_preco_cent"], 200)         # R$ 2,00 cada
        self.assertEqual(p["ult_atualizacao"], "2026-10-03 21:00:00")

    def test_compra_com_desconto_no_item(self):
        pid = self.novo_produto("SKOL", 800, estoque=True)
        self.lancar("compra", [(pid, 10, 2000, 500)])      # R$ 20,00 - R$ 5,00 de desconto
        self.assertEqual(self.prod.por_id(pid)["ult_preco_cent"], 150)

    def test_entrada_saida_e_descarte(self):
        pid = self.novo_produto("GELO", 100, estoque=True)
        self.lancar("entrada", [(pid, 50)])
        self.lancar("saida", [(pid, 5)])
        self.lancar("descarte", [(pid, 2)])
        self.assertEqual(self.qt(pid), 43)

    def test_produto_sem_controle_de_estoque_e_recusado(self):
        pid = self.novo_produto("SERVICO", 100)
        lid = self.est.criar_lancamento("entrada")
        with self.assertRaises(ErroNegocio):
            self.est.adicionar_item(lid, pid, 1)

    def test_ligar_controle_permite_lancar_quantidade_de_produto_novo(self):
        pid = self.novo_produto("SKOL", 800)                       # cadastrado sem "Controla estoque"
        lid = self.est.criar_lancamento("entrada")
        self.est.adicionar_item(lid, pid, 150, ligar_controle=True)
        p = self.prod.por_id(pid)
        self.assertEqual((p["controla_estoque"], p["qt_atual"]), (1, 150))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'estoque_controle_ligado'"), 1)
        lid = self.est.criar_lancamento("saida")                   # saída nunca liga o controle sozinha
        outro = self.novo_produto("SERVICO", 100)
        with self.assertRaises(ErroNegocio):
            self.est.adicionar_item(lid, outro, 1, ligar_controle=True)

    def test_remover_item_desfaz_o_efeito_e_o_custo(self):
        pid = self.novo_produto("SKOL", 800, estoque=True)
        self.lancar("compra", [(pid, 10, 1000)])                  # R$ 1,00
        _, (item2,) = self.lancar("compra", [(pid, 10, 3000)])    # R$ 3,00
        self.assertEqual(self.prod.por_id(pid)["ult_preco_cent"], 300)
        self.est.remover_item(item2)
        self.assertEqual(self.qt(pid), 10)
        self.assertEqual(self.prod.por_id(pid)["ult_preco_cent"], 100)   # volta ao custo anterior

    def test_excluir_lancamento_inteiro(self):
        pid = self.novo_produto("SKOL", 800, estoque=True)
        lid, _ = self.lancar("entrada", [(pid, 7)])
        self.est.excluir_lancamento(lid)
        self.assertEqual(self.qt(pid), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 0)

    def test_contagem_define_o_estoque_fisico_e_registra_diferenca(self):
        pid = self.novo_produto("SKOL", 800, estoque=True, qt=30)
        _, (item,) = self.lancar("contagem", [(pid, 28)])
        self.assertEqual(self.qt(pid), 28)
        linha = self.est.itens(self.banco.valor("SELECT MAX(id) FROM lancamentos_estoque"))[0]
        self.assertEqual(linha["diferenca"], -2)
        self.assertEqual(linha["qt_anterior"], 30)

    def test_inicial_habilita_controle_e_define_minimo(self):
        pid = self.novo_produto("RED LABEL", 1500)
        lid = self.est.criar_lancamento("inicial")
        self.est.adicionar_item(lid, pid, 12, estoque_minimo=5)
        p = self.prod.por_id(pid)
        self.assertEqual((p["controla_estoque"], p["qt_atual"], p["qt_inicial"], p["estoque_minimo"]), (1, 12, 12, 5))

    def test_pedido_nao_mexe_no_estoque_ate_confirmar_entrega(self):
        pid = self.novo_produto("RED LABEL", 1500, estoque=True)
        lid, (item,) = self.lancar("pedido", [(pid, 50)])
        self.assertEqual(self.qt(pid), 0)
        self.est.confirmar_pedido(lid, {item: 50 * 6000})
        self.assertEqual(self.qt(pid), 50)
        self.assertEqual(self.est.lancamento(lid)["tipo"], "compra")
        self.assertEqual(self.prod.por_id(pid)["ult_preco_cent"], 6000)
        with self.assertRaises(ErroNegocio):
            self.est.confirmar_pedido(lid)       # já confirmado

    def test_pedido_confirmado_desconta_o_desconto_do_preco_unitario(self):
        pid = self.novo_produto("RED LABEL", 1500, estoque=True)
        lid, (item,) = self.lancar("pedido", [(pid, 10, 1000, 200)])     # R$ 10,00 com R$ 2,00 de desconto
        self.est.confirmar_pedido(lid)
        self.assertEqual(self.est.itens(lid)[0]["preco_unit_cent"], 80)  # igual ao último preço do produto
        self.assertEqual(self.prod.por_id(pid)["ult_preco_cent"], 80)

    def test_pedido_exige_fornecedor(self):
        with self.assertRaises(ErroNegocio):
            self.est.criar_lancamento("pedido")

    def test_baixa_de_venda_pela_composicao_e_estorno(self):
        cafe = self.novo_produto("CAFE EXPRESSO", 450)
        grao = self.novo_produto("GRAO DE CAFE", 0, estoque=True, qt=1.0)
        self.prod.incluir_composicao(cafe, grao, 0.01)
        venda = self.banco.inserir("vendas", {"uuid": "u1", "aberta_em": "2026-10-03 21:00:00"})
        self.banco.inserir("itens_venda", {
            "venda_id": venda, "produto_id": cafe, "quantidade": 3, "preco_unit_cent": 450,
            "total_cent": 1350, "criado_em": "2026-10-03 21:00:00"})
        self.est.baixar_venda(venda)
        self.assertAlmostEqual(self.qt(grao), 0.97)
        self.est.estornar_venda(venda)
        self.assertAlmostEqual(self.qt(grao), 1.0)

    def test_baixa_e_estorno_sao_idempotentes(self):
        """Repetir a chamada (retry) não pode duplicar os movimentos."""
        cafe = self.novo_produto("CAFE EXPRESSO", 450)
        grao = self.novo_produto("GRAO DE CAFE", 0, estoque=True, qt=10.0)
        skol = self.novo_produto("SKOL", 800, estoque=True, qt=10)
        self.prod.incluir_composicao(cafe, grao, 1)
        venda = self.banco.inserir("vendas", {"uuid": "u2", "aberta_em": "2026-10-03 21:00:00"})
        for pid, qtd in ((cafe, 2), (skol, 3)):
            self.banco.inserir("itens_venda", {
                "venda_id": venda, "produto_id": pid, "quantidade": qtd, "preco_unit_cent": 100,
                "total_cent": 100 * qtd, "criado_em": "2026-10-03 21:00:00"})
        self.est.baixar_venda(venda)
        self.est.baixar_venda(venda)
        self.assertEqual((self.qt(grao), self.qt(skol)), (8.0, 7))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_estoque WHERE tipo = 'venda'"), 2)
        self.est.estornar_venda(venda)
        self.est.estornar_venda(venda)
        self.assertEqual((self.qt(grao), self.qt(skol)), (10.0, 10))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_estoque WHERE tipo = 'estorno_venda'"), 2)

    def test_descarte_de_produto_acabado_baixa_os_insumos(self):
        cafe = self.novo_produto("CAFE EXPRESSO", 450)
        grao = self.novo_produto("GRAO DE CAFE", 0, estoque=True, qt=1.0)
        self.prod.incluir_composicao(cafe, grao, 0.01)
        self.lancar("desc_acabados", [(cafe, 2)])
        self.assertAlmostEqual(self.qt(grao), 0.98)
        sem_ficha = self.novo_produto("PAO", 100)
        lid = self.est.criar_lancamento("desc_acabados")
        with self.assertRaises(ErroNegocio):
            self.est.adicionar_item(lid, sem_ficha, 1)

    def test_historico_de_movimentos_registra_saldo_apos(self):
        pid = self.novo_produto("SKOL", 800, estoque=True)
        self.lancar("entrada", [(pid, 10)])
        self.lancar("saida", [(pid, 4)])
        movs = self.banco.todos("SELECT tipo, quantidade, qt_apos FROM movimentos_estoque WHERE produto_id = ? ORDER BY id", (pid,))
        self.assertEqual([(m["tipo"], m["quantidade"], m["qt_apos"]) for m in movs], [("entrada", 10, 10), ("saida", -4, 6)])


class TestePainelDeEstoque(BaseTeste):
    """Visão geral do estoque: situação, valor parado, movimento rápido, pedido sugerido e histórico."""

    def setUp(self):
        super().setUp()
        self.est = EstoqueController(self.banco)
        self.sem = self.novo_produto("SKOL", 800, estoque=True)
        self.ponto = self.novo_produto("BRAHMA", 800, estoque=True, qt=4)
        self.normal = self.novo_produto("COCA", 500, estoque=True, qt=30)
        self.novo_produto("AGUA", 300)                                      # não controla estoque: fica fora do painel
        for pid, minimo, preco in ((self.sem, 10, 200), (self.ponto, 5, 300), (self.normal, 6, 100)):
            self.banco.executar("UPDATE produtos SET estoque_minimo = ?, ult_preco_cent = ? WHERE id = ?", (minimo, preco, pid))

    def test_painel_resumo_filtros_e_valor_parado(self):
        r = self.est.resumo()
        self.assertEqual((r["total"], r["sem"], r["ponto"], r["normal"]), (3, 1, 1, 1))
        self.assertEqual(r["valor_cent"], 4 * 300 + 30 * 100)                # o zerado não conta
        self.assertEqual([p["nome"] for p in self.est.painel("ponto")], ["BRAHMA"])
        self.assertEqual([p["nome"] for p in self.est.painel(texto="co")], ["COCA"])
        self.assertEqual([p["nome"] for p in self.est.painel(texto="brahma")], ["BRAHMA"])
        grupo = self.est.painel()[0]["grupo"]
        self.assertEqual(len(self.est.painel(grupo=grupo)), 3)
        self.assertEqual(self.est.painel(grupo="NÃO EXISTE"), [])

    def test_sugestao_repoe_ate_o_dobro_do_minimo(self):
        por_nome = {p["nome"]: p for p in self.est.painel()}
        self.assertEqual(por_nome["SKOL"]["repor"], 20)                      # 10*2 - 0
        self.assertEqual(por_nome["BRAHMA"]["repor"], 6)                     # 5*2 - 4
        self.assertEqual(por_nome["COCA"]["repor"], 0)
        self.banco.executar("UPDATE produtos SET estoque_minimo = 0 WHERE id = ?", (self.sem,))
        self.assertEqual({p["nome"]: p["repor"] for p in self.est.painel()}["SKOL"], 0)   # sem mínimo, não sugere
        self.assertEqual([p["nome"] for p in self.est.lista_de_compras()], ["BRAHMA"])

    def test_movimento_rapido_atualiza_estoque_e_historico(self):
        self.est.registrar_rapido(self.sem, "entrada", 24)
        self.est.registrar_rapido(self.sem, "descarte", 4)
        self.est.registrar_rapido(self.sem, "saida", 2)
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.sem,)), 18)
        self.est.registrar_rapido(self.sem, "contagem", 15)                  # contei 15 na prateleira
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.sem,)), 15)
        hist = self.est.historico(self.sem)
        self.assertEqual([h["rotulo"] for h in hist], ["Contagem", "Saída", "Descarte", "Entrada"])
        self.assertEqual((hist[0]["quantidade"], hist[0]["qt_apos"]), (-3, 15))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 4)

    def test_movimento_rapido_recusa_o_que_nao_faz_sentido(self):
        with self.assertRaises(ErroNegocio):
            self.est.registrar_rapido(self.ponto, "saida", 5)                # só há 4
        with self.assertRaises(ErroNegocio):
            self.est.registrar_rapido(self.ponto, "entrada", 0)
        with self.assertRaises(ErroNegocio):
            self.est.registrar_rapido(self.ponto, "compra", 1)               # compra precisa de fornecedor/nota: lançamento completo
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.ponto,)), 4)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 0)    # nada ficou pela metade

    def test_pedido_sugerido_nao_mexe_no_estoque_ate_confirmar(self):
        forn = self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        lanc = self.est.pedido_sugerido(forn)
        self.assertEqual(self.est.lancamento(lanc)["tipo"], "pedido")
        self.assertEqual({i["nome"]: i["quantidade"] for i in self.est.itens(lanc)}, {"SKOL": 20, "BRAHMA": 6})
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.ponto,)), 4)
        self.est.confirmar_pedido(lanc)
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.ponto,)), 10)

    def test_pedido_sugerido_sem_nada_a_repor(self):
        forn = self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        self.banco.executar("UPDATE produtos SET estoque_minimo = 0")
        with self.assertRaises(ErroNegocio):
            self.est.pedido_sugerido(forn)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 0)

    def test_produto_sem_controle_aparece_na_busca_e_comeca_a_controlar_com_uma_contagem(self):
        redbull = self.novo_produto("REDBULL", 1500)                         # cadastrado sem 'Controla estoque'
        self.assertNotIn("REDBULL", [p["nome"] for p in self.est.painel()])                     # a lista padrão só tem os controlados
        achados = self.est.painel(texto="red")
        self.assertEqual([(p["nome"], p["situacao"]) for p in achados], [("REDBULL", "livre")])
        self.assertEqual([p["nome"] for p in self.est.painel("livre")], ["AGUA", "REDBULL"])
        self.assertEqual(self.est.resumo()["livre"], 2)
        self.assertEqual(self.est.resumo()["total"], 3)                       # os cartões continuam só com os controlados
        self.assertEqual(achados[0]["repor"], 0)
        self.est.registrar_rapido(redbull, "contagem", 48)
        p = self.banco.um("SELECT controla_estoque, qt_atual FROM produtos WHERE id = ?", (redbull,))
        self.assertEqual((p["controla_estoque"], p["qt_atual"]), (1, 48))
        self.assertIn("REDBULL", [x["nome"] for x in self.est.painel()])
        self.assertEqual(self.est.resumo()["livre"], 1)

    def test_entrada_tambem_liga_o_controle_mas_saida_nao(self):
        agua = self.banco.valor("SELECT id FROM produtos WHERE nome = 'AGUA'")
        with self.assertRaises(ErroNegocio):
            self.est.registrar_rapido(agua, "saida", 1)
        self.assertEqual(self.banco.valor("SELECT controla_estoque FROM produtos WHERE id = ?", (agua,)), 0)
        self.est.registrar_rapido(agua, "entrada", 12)
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (agua,)), 12)
