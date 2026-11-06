"""Reposição pelo giro por caixa e etiquetas de produtos/preços (controllers e Qt)."""
import os
import tempfile
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from src.controllers.estoque_controller import EstoqueController
from src.controllers.etiqueta_controller import EtiquetaController
from src.controllers.produto_controller import ProdutoController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from tests.base import BaseTeste



class BaseGiro(BaseTeste):
    def setUp(self):
        super().setUp()
        self.est = EstoqueController(self.banco, self.operador_adm())
        self.fornecedor = self.banco.inserir("fornecedores", {"nome": "DISTRIBUIDORA"})

    def produto(self, nome="CERVEJA", qt=2, **kw):
        return self.novo_produto(nome, estoque=True, qt=qt, **kw)

    def venda(self, pid, quantidade, terminal=1, dias=0, tipo="venda"):
        vid = self.banco.inserir("vendas", {"uuid": str(uuid4()), "aberta_em": fmt.agora(), "terminal": terminal})
        self.movimento(pid, vid, quantidade, dias, tipo)
        return vid

    def movimento(self, pid, venda_id, quantidade, dias=0, tipo="venda"):
        self.banco.inserir("movimentos_estoque", {
            "produto_id": pid, "tipo": tipo, "quantidade": -abs(quantidade) if tipo == "venda" else abs(quantidade),
            "qt_apos": 0, "ref_tipo": "venda", "ref_id": venda_id,
            "criado_em": (self._hora["t"] + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")})


class TesteReposicaoGiro(BaseGiro):
    def test_recorta_por_caixa_e_calcula_sete_dias_sobre_media_de_30(self):
        pid = self.produto(qt=2)
        self.venda(pid, 30, terminal=1)
        self.venda(pid, 60, terminal=2)
        c1 = self.est.reposicao_giro(1)[0]
        self.assertEqual((c1["consumo_janela"], c1["alvo_qtd"], c1["sugerido"], c1["terminal"]), (30, 7, 5, 1))
        self.assertEqual(self.est.reposicao_giro(2)[0]["sugerido"], 12)
        self.assertEqual(self.est.reposicao_giro()[0]["sugerido"], 19)
        self.assertEqual(self.est.reposicao_giro(3), [])
        self.assertEqual(self.est.terminais(), [1, 2])

    def test_estorno_janela_saldo_sem_controle_e_quatro_casas(self):
        pid = self.produto("A", qt=0)
        self.venda(pid, 30)
        self.venda(pid, 30, dias=-31)
        self.assertEqual(self.est.reposicao_giro(1)[0]["consumo_janela"], 30)
        self.venda(pid, 15, tipo="estorno_venda")
        self.assertEqual(self.est.reposicao_giro(1)[0]["alvo_qtd"], 3.5)
        self.assertEqual(self.est.reposicao_giro(1)[0]["sugerido"], 4)          # lata não se compra pela metade
        cheio = self.produto("B", qt=100)
        self.venda(cheio, 30)
        livre = self.novo_produto("C")
        self.venda(livre, 30)
        self.assertEqual([p["id"] for p in self.est.reposicao_giro(1)], [pid])
        raro = self.produto("D", qt=0, aceita_decimal="S")
        self.venda(raro, 0.1234)
        self.assertEqual(next(p for p in self.est.reposicao_giro(1) if p["id"] == raro)["sugerido"], 0.0288)

    def test_cobertura_e_terminal_invalidos(self):
        for kw in ({"cobertura_dias": 0}, {"cobertura_dias": 7.5}, {"cobertura_dias": 366}):
            with self.assertRaises(ErroNegocio):
                self.est.reposicao_giro(1, **kw)
        for terminal in (0, "1", True):
            with self.assertRaises(ErroNegocio):
                self.est.reposicao_giro(terminal)

    def test_pedido_so_por_acao_explicita_e_sem_mexer_no_saldo(self):
        pid = self.produto(qt=2)
        outro = self.produto("OUTRO", qt=2)
        self.venda(pid, 30)
        self.assertEqual(self.est.lancamentos("pedido"), [])
        with self.assertRaises(ErroNegocio):
            self.est.pedido_por_giro(self.fornecedor, [(outro, 1)], 1)
        lanc = self.est.pedido_por_giro(self.fornecedor, None, 1)
        self.assertEqual([(i["produto_id"], i["quantidade"]) for i in self.est.itens(lanc)], [(pid, 5)])
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (pid,)), 2)
        with self.assertRaises(ErroNegocio):                                    # já está a caminho: não pede de novo
            self.est.pedido_por_giro(self.fornecedor, [(pid, 3)], 1)
        self.venda(outro, 60)
        manual = self.est.pedido_por_giro(self.fornecedor, [(outro, 3)], 1)
        self.assertEqual(self.est.itens(manual)[0]["quantidade"], 3)
        with self.assertRaises(ErroNegocio):
            self.est.pedido_por_giro(self.fornecedor, None, 2)

    def test_texto_informa_escopo_e_sugestao(self):
        self.venda(self.produto(), 30, terminal=2)
        texto = self.est.texto_reposicao_giro(self.est.reposicao_giro(2), 2)
        self.assertIn("CAIXA 2", texto)
        self.assertIn("SUGESTÃO", texto)


class TesteGiroComPrazoPedidosEFardos(BaseGiro):
    def test_janela_prazo_e_cobertura_entram_na_conta_e_na_explicacao(self):
        pid = self.produto("SKOL LATA", qt=10)
        self.venda(pid, 14, dias=-3)                       # dentro de 7 dias
        self.venda(pid, 28, dias=-10)                      # só na janela de 14 e de 30
        s7 = self.est.reposicao_giro(janela_dias=7, prazo_dias=3, cobertura_dias=7)[0]
        self.assertEqual((s7["consumo_janela"], s7["media_diaria"], s7["alvo_qtd"], s7["sugerido"]), (14, 2, 20, 10))
        self.assertIn("2,00/dia × 10 dias (prazo 3 + cobertura 7) = 20 − tem 10 → comprar 10", s7["explicacao"])
        s14 = self.est.reposicao_giro(janela_dias=14, prazo_dias=0, cobertura_dias=7)[0]
        self.assertEqual((s14["consumo_janela"], s14["alvo_qtd"], s14["sugerido"]), (42, 21, 11))

    def test_pedido_a_caminho_desconta_e_pedido_velho_nao(self):
        pid = self.produto("BRAHMA", qt=0)
        self.venda(pid, 30)                                # 1/dia x 7 = 7
        lanc = self.est.criar_lancamento("pedido", fornecedor_id=self.fornecedor)
        self.est.adicionar_item(lanc, pid, 4)
        s = self.est.reposicao_giro()[0]
        self.assertEqual((s["a_caminho"], s["sugerido"]), (4, 3))
        self.assertIn("− a caminho 4", s["explicacao"])
        self.banco.executar("UPDATE lancamentos_estoque SET data = ? WHERE id = ?",
                            ((self._hora["t"] - timedelta(days=45)).strftime("%Y-%m-%d"), lanc))
        self.assertEqual(self.est.reposicao_giro()[0]["sugerido"], 7)     # pedido esquecido não segura a compra
        self.est.confirmar_pedido(lanc)                                   # entregue: entra no saldo
        self.assertEqual(self.est.reposicao_giro()[0]["sugerido"], 3)

    def test_fardo_mostra_quantos_fardos_e_pedido_fica_em_unidades(self):
        pid = self.produto("HEINEKEN LONG NECK", qt=1)
        fardo = self.novo_produto("FARDO HEINEKEN", preco=6000)
        ProdutoController(self.banco).incluir_composicao(fardo, pid, 12)
        self.venda(pid, 60)                                # 2/dia x 7 = 14 - 1 = 13
        s = self.est.reposicao_giro()[0]
        self.assertEqual((s["sugerido"], s["fardos"], s["fardo"]["quantidade"]), (13, 2, 12))
        self.assertIn("(2 × FARDO HEINEKEN de 12)", s["explicacao"])
        lanc = self.est.pedido_por_giro(self.fornecedor)
        self.assertEqual([(i["produto_id"], i["quantidade"]) for i in self.est.itens(lanc)], [(pid, 13)])

    def test_sem_venda_na_janela_usa_o_minimo_e_avisa(self):
        pid = self.produto("VINHO", qt=1)
        self.banco.executar("UPDATE produtos SET estoque_minimo = 3 WHERE id = ?", (pid,))
        s = self.est.reposicao_giro()[0]
        self.assertEqual((s["base"], s["sugerido"], s["cobertura_dias"]), ("minimo", 5, None))
        self.assertIn("sem venda em 30 dias: dobro do mínimo 6", s["explicacao"])
        texto = self.est.texto_reposicao_giro([s])
        self.assertIn("—", texto)
        self.assertIn("pedidos não entregues", texto)

    def test_parametros_validados_e_lembrados(self):
        for kw in ({"janela_dias": 10}, {"janela_dias": "7"}, {"prazo_dias": -1}, {"prazo_dias": 61},
                   {"prazo_dias": 2.5}):
            with self.assertRaises(ErroNegocio):
                self.est.reposicao_giro(**kw)
        self.assertEqual(self.est.parametros_giro(), {"janela_dias": 30, "prazo_dias": 0, "cobertura_dias": 7})
        self.est.salvar_parametros_giro(14, 3, 10)
        self.assertEqual(self.est.parametros_giro(), {"janela_dias": 14, "prazo_dias": 3, "cobertura_dias": 10})
        with self.assertRaises(ErroNegocio):
            self.est.salvar_parametros_giro(15, 3, 10)
        self.banco.cfg_set("giro_janela_dias", "99")                     # valor estragado volta ao padrão
        self.assertEqual(self.est.parametros_giro()["janela_dias"], 30)


class TesteEtiquetas(BaseGiro):
    def setUp(self):
        super().setUp()
        self.etq = EtiquetaController(self.banco)

    def test_natural_gelada_atacado_e_fardo(self):
        pid = self.produto("SKOL LATA", preco=500)
        self.banco.executar(
            """UPDATE produtos SET preco_gelada_cent = 600, atacado_qtd = 6, preco_atacado_cent = 450,
               atacado_gelada_qtd = 12, preco_atacado_gelada_cent = 550 WHERE id = ?""", (pid,))
        fardo = self.produto("FARDO SKOL", preco=2400)
        ProdutoController(self.banco).incluir_composicao(fardo, pid, 12)
        e = self.etq.etiquetas([{"produto_id": pid, "copias": 2, "temperatura": "ambas"}])
        self.assertEqual([(x["temperatura"], x["preco_cent"], x["atacado_qtd"], x["atacado_cent"]) for x in e],
                         [("natural", 500, 6, 450)] * 2 + [("gelada", 600, 12, 550)] * 2)
        texto = self.etq.texto(e[:1])
        self.assertIn("R$ 5,00", texto)
        self.assertIn("a partir de 6 un = R$ 4,50", texto)
        self.assertEqual(self.etq.etiquetas([{"produto_id": fardo}])[0]["fardo_qtd"], 12)
        self.assertIn("Fardo com 12 un", self.etq.texto(self.etq.etiquetas([{"produto_id": fardo}])))
        linhas = self.etq.csv(e).splitlines()
        self.assertEqual(len(linhas), 5)
        self.assertIn(";5,00;6;4,50;", linhas[1])

    def test_sem_gelada_e_validacoes(self):
        pid = self.produto("AGUA", preco=300)
        self.assertEqual(len(self.etq.etiquetas([{"produto_id": pid, "temperatura": "ambas"}])), 1)
        casos = ([], [{"produto_id": pid, "temperatura": "gelada"}], [{"produto_id": pid, "copias": 0}],
                 [{"produto_id": pid, "copias": 100}], [{"produto_id": pid, "temperatura": "x"}],
                 [{"produto_id": 9999}], [{"produto_id": pid, "copias": 99}] * 6)
        for itens in casos:
            with self.assertRaises(ErroNegocio):
                self.etq.etiquetas(itens)

    def test_promocao_vigente_e_csv_sem_formula(self):
        pid = self.produto("=CMD", preco=500)
        self.banco.executar("UPDATE produtos SET promo_de = '2026-10-01', promo_ate = '2026-10-31', promo_preco_cent = 400 "
                            "WHERE id = ?", (pid,))
        e = self.etq.etiquetas([{"produto_id": pid}])
        self.assertEqual(e[0]["preco_cent"], 400)
        self.assertIn("'=CMD", self.etq.csv(e))
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (pid,)), 500)


