"""Regras existentes, simulação sem escrita e interfaces de gestão isoladas."""
import importlib.util
import os
import subprocess
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from src.controllers.acesso_controller import AcessoController
from src.controllers.cadastro_controller import CadastroController
from src.controllers.produto_controller import ProdutoController
from src.controllers.promocoes_controller import CAMPOS, PromocoesController
from src.core.erros import ErroPermissao, ErroValidacao
from tests.base import BaseTeste


class TestePromocoes(BaseTeste):
    def setUp(self):
        super().setUp()
        acesso = AcessoController(self.banco)
        self.ctx = SimpleNamespace(banco=self.banco, acesso=acesso,
                                   operador_id=self.operador_adm(),
                                   operador=acesso.operador(self.operador_adm()),
                                   cadastros=CadastroController(self.banco))
        self.ctx.pode = lambda modulo: acesso.pode(self.ctx.operador, modulo)
        self.controller = PromocoesController(self.ctx)
        self.pid = self.novo_produto("BEBIDA", 1000, estoque=True, qt=50)

    def salvar(self, **valores):
        return self.controller.salvar(self.pid, valores)

    def simular(self, **parametros):
        return self.controller.simular(self.pid, **parametros)

    def configurar(self):
        self.salvar(promo_de="03/10/2026", promo_ate="04/10/2026", promo_preco_cent="9",
                    sem_inicial="7", sem_final="1", sem_preco_cent="8",
                    hora_ini="22:00", hora_fim="04:00", hora_preco_cent="7",
                    atacado_qtd="6", preco_atacado_cent="6,50",
                    preco_gelada_cent="12", atacado_gelada_qtd="3", preco_atacado_gelada_cent="11")

    def test_sobrepostas_menor_preco_sem_acumulo(self):
        self.configurar()
        r = self.simular(quando="2026-10-03 22:00:00", quantidade="6")
        self.assertEqual((r["base_cent"], r["promocao_cent"], r["faixa_cent"], r["final_cent"]),
                         (1000, 700, 650, 650))
        self.assertEqual(r["total_cent"], 3900)
        self.assertTrue(all(regra["elegivel"] for regra in r["regras"]))
        r = self.simular(quando="2026-10-03 22:00:00", quantidade="5")
        self.assertFalse(r["faixa_atingida"])
        self.assertEqual(r["final_cent"], 700)
        self.salvar(preco_atacado_cent="7,50")
        r = self.simular(quando="2026-10-03 22:00:00", quantidade="6")
        self.assertTrue(r["faixa_atingida"])
        self.assertEqual(r["final_cent"], 700)

    def test_fronteiras_periodo_inclusivo(self):
        self.salvar(promo_de="03/10/2026", promo_ate="04/10/2026", promo_preco_cent="9")
        for quando, esperado in (
            ("2026-10-02 23:59:59", 1000), ("2026-10-03 00:00:00", 900),
            ("2026-10-04 23:59:59", 900), ("2026-10-05 00:00:00", 1000),
        ):
            with self.subTest(quando=quando):
                self.assertEqual(self.simular(quando=quando)["final_cent"], esperado)

    def test_fronteiras_horario_e_virada(self):
        self.salvar(hora_ini="22:00", hora_fim="04:00", hora_preco_cent="7")
        for hora, esperado in (("21:59:59", 1000), ("22:00:00", 700),
                                ("04:00:59", 700), ("04:01:00", 1000)):
            with self.subTest(hora=hora):
                self.assertEqual(self.simular(quando="2026-10-03 " + hora)["final_cent"], esperado)
        self.salvar(hora_ini="12:00", hora_fim="14:00")
        for hora, esperado in (("11:59:59", 1000), ("12:00:00", 700),
                                ("14:00:59", 700), ("14:01:00", 1000)):
            with self.subTest(hora=hora):
                self.assertEqual(self.simular(quando="2026-10-03 " + hora)["final_cent"], esperado)

    def test_dias_viram_semana(self):
        self.salvar(sem_inicial="6", sem_final="2", sem_preco_cent="8")
        for data, esperado in (("2026-10-02", 800), ("2026-10-03", 800), ("2026-10-04", 800),
                               ("2026-10-05", 800), ("2026-10-06", 1000), ("2026-10-01", 1000)):
            with self.subTest(data=data):
                self.assertEqual(self.simular(quando=data + " 12:00:00")["final_cent"], esperado)

    def test_natural_gelada_independentes(self):
        self.configurar()
        for temperatura, qtd, esperado in (("natural", "3", 700), ("gelada", "2", 1200), ("gelada", "3", 1100)):
            with self.subTest(temperatura=temperatura, qtd=qtd):
                r = self.simular(temperatura=temperatura, quantidade=qtd, quando="2026-10-03 22:00:00")
                self.assertEqual(r["final_cent"], esperado)
                if temperatura == "gelada":
                    self.assertIsNone(r["promocao_cent"])
                    self.assertFalse(any(regra["elegivel"] for regra in r["regras"]))

    def test_gelada_sem_preco_recusada(self):
        with self.assertRaises(ErroValidacao):
            self.simular(temperatura="gelada")
        with self.assertRaises(ErroValidacao):
            self.simular(temperatura="outra")

    def test_simulacao_rascunho_nao_grava_nada(self):
        antes = "\n".join(self.banco.conexao.iterdump())
        r = self.simular(valores={"hora_ini": "20:00", "hora_fim": "22:00", "hora_preco_cent": "5"})
        self.assertEqual(r["final_cent"], 500)
        self.assertEqual("\n".join(self.banco.conexao.iterdump()), antes)
        descricao = self.controller.descrever(r)
        for trecho in ("1000 cent", "500 cent", "20:00", "22:00", "2026-10-03", "Sem acúmulo"):
            self.assertIn(trecho, descricao)

    def test_usa_validacao_padrao_para_salvar_e_simular(self):
        casos = [
            {"promo_preco_cent": "-1"}, {"hora_preco_cent": "10,01"},
            {"promo_preco_cent": "9"}, {"sem_preco_cent": "8"}, {"hora_preco_cent": "7"},
            {"promo_de": "31/02/2026"}, {"hora_ini": "25:00"}, {"sem_inicial": "8"},
            {"promo_de": "04/10/2026", "promo_ate": "03/10/2026"},
            {"atacado_qtd": "NaN", "preco_atacado_cent": "7"},
            {"atacado_qtd": "2,12345", "preco_atacado_cent": "7"},
            {"atacado_qtd": "2", "preco_atacado_cent": "11"},
            {"atacado_gelada_qtd": "2", "preco_atacado_gelada_cent": "7"},
        ]
        for valores in casos:
            for operacao in ("salvar", "simular"):
                with self.subTest(valores=valores, operacao=operacao), self.assertRaises(ErroValidacao):
                    if operacao == "salvar":
                        self.controller.salvar(self.pid, valores)
                    else:
                        self.simular(valores=valores)

    def test_edicao_parcial_valida_periodo_completo(self):
        self.salvar(promo_de="03/10/2026", promo_ate="04/10/2026", promo_preco_cent="9")
        for valores in ({"promo_de": "05/10/2026"}, {"promo_ate": ""},
                        {"preco_cent": "8"}):
            with self.subTest(valores=valores), self.assertRaises(ErroValidacao):
                self.controller.salvar(self.pid, valores)
        self.salvar(promo_preco_cent="0", promo_de="", promo_ate="")
        self.assertEqual(self.simular()["final_cent"], 1000)

    def test_quantidade_simulada_finita_quatro_casas_unidade(self):
        for valor in ("0", "-1", "NaN", "inf", "-inf", "1e999", "0,00001", "2,12345", "abc", True, "2,5"):
            with self.subTest(valor=valor), self.assertRaises(ErroValidacao):
                self.simular(quantidade=valor)
        self.ctx.cadastros.salvar("produtos", {"aceita_decimal": "S"}, self.pid)
        self.salvar(atacado_qtd="2,1234", preco_atacado_cent="7")
        self.assertEqual(self.simular(quantidade="2,1233")["final_cent"], 1000)
        self.assertEqual(self.simular(quantidade="2,123400")["final_cent"], 700)

    def test_instante_invalido_recusado(self):
        for valor in ("2026-02-31 12:00:00", "2026-10-03 25:00:00", "03/10/2026", "", "2026-10-03 12:00:00extra"):
            with self.subTest(valor=valor), self.assertRaises(ErroValidacao):
                self.simular(quando=valor)

    def test_operador_inativo_nivel_e_modulo_reconsultados(self):
        for comando in (
            "UPDATE operadores SET ativo = 0 WHERE id = ?",
            "UPDATE operadores SET nivel = 0 WHERE id = ?",
        ):
            with self.subTest(comando=comando):
                self.banco.executar(comando, (self.ctx.operador_id,))
                for acao in (lambda: self.salvar(preco_cent="9"), self.simular, self.controller.listar,
                             self.controller.exigir_acesso):
                    with self.assertRaises(ErroPermissao):
                        acao()
                self.banco.executar("UPDATE operadores SET ativo = 1, nivel = 4 WHERE id = ?", (self.ctx.operador_id,))
        with patch("src.controllers.promocoes_controller.modulos_desligados", return_value={"cad_produtos"}):
            with self.assertRaises(ErroPermissao):
                self.salvar(preco_cent="9")

    def test_campos_fora_do_escopo_recusados(self):
        for valores in ({"qt_atual": "999"}, {"codigo": "123"}, {"aceita_decimal": "S"}):
            with self.subTest(valores=valores), self.assertRaises(ErroValidacao):
                self.controller.salvar(self.pid, valores)

    def test_preco_legado_mais_alto_nao_aumenta_base(self):
        produto = self.ctx.cadastros.obter("produtos", self.pid)
        produto.update(hora_ini="00:00", hora_fim="23:59", hora_preco_cent=1200)
        self.assertEqual(ProdutoController.regra_preco_vigente(produto, datetime(2026, 10, 3))["preco_cent"], 1000)


    def test_qt_abre_simula_salva_e_revalida(self):
        if importlib.util.find_spec("PySide6") is None:
            self.skipTest("PySide6 não instalado")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from src.ui_qt.promocoes import JanelaPromocoes
        app = QApplication.instance() or QApplication([])
        janela = JanelaPromocoes(self.ctx)
        self.addCleanup(janela.close)
        self.assertIsNotNone(app)
        self.assertEqual(set(janela.campos), {c.nome for c in CAMPOS})
        janela.simular()
        self.assertIn("FINAL UNITÁRIO: 1000 cent", janela.resultado.toPlainText())
        janela.campos["preco_cent"].setText("9")
        janela.salvar()
        self.assertEqual(self.ctx.cadastros.obter("produtos", self.pid)["preco_cent"], 900)
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.ctx.operador_id,))
        with self.assertRaises(ErroPermissao):
            janela.exigir_acesso()
