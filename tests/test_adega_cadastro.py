"""Opções comerciais da adega nos cadastros compartilhados e fardo no Qt."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from src.controllers.cadastro_controller import CadastroController
from src.controllers.entidades import ENTIDADES, _antes_produto
from src.controllers.produto_controller import ProdutoController
from src.core.erros import ErroNegocio, ErroValidacao
from tests.base import BaseTeste


class TesteCadastroAdega(BaseTeste):
    def setUp(self):
        super().setUp()
        self.cad = CadastroController(self.banco)
        self.prod = ProdutoController(self.banco)
        self.bebida = self.novo_produto("CERVEJA", 800, estoque=True, qt=24)
        self.casco = self.novo_produto("CASCO", 500)

    def alterar(self, **dados):
        return self.cad.salvar("produtos", dados, self.bebida)

    def registro(self):
        return self.cad.obter("produtos", self.bebida)

    def test_secao_adega_compartilhada_e_opcional(self):
        campos = {c.nome for c in ENTIDADES["produtos"].campos if c.secao == "Adega"}
        self.assertEqual(campos, {
            "preco_gelada_cent", "atacado_qtd", "preco_atacado_cent",
            "atacado_gelada_qtd", "preco_atacado_gelada_cent", "casco_produto_id"})
        produto = self.registro()
        self.assertIsNone(produto["casco_produto_id"])
        for campo in campos - {"casco_produto_id"}:
            self.assertEqual(produto[campo], 0)

    def test_precos_por_temperatura_sem_novo_estoque(self):
        self.alterar(preco_gelada_cent="10,00", atacado_qtd="12", preco_atacado_cent="7,00",
                     atacado_gelada_qtd="6", preco_atacado_gelada_cent="9,00")
        produto = self.registro()
        self.assertEqual((produto["preco_cent"], produto["preco_gelada_cent"],
                          produto["preco_atacado_cent"], produto["preco_atacado_gelada_cent"]),
                         (800, 1000, 700, 900))
        self.assertEqual(produto["qt_atual"], 24)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), 2)

    def test_faixas_independentes_e_preco_igual_ao_varejo(self):
        self.alterar(atacado_qtd="12", preco_atacado_cent="8,00")
        self.alterar(preco_gelada_cent="9", atacado_gelada_qtd="3", preco_atacado_gelada_cent="9")
        self.alterar(atacado_qtd="0", preco_atacado_cent="0")
        self.assertEqual(self.registro()["atacado_qtd"], 0)
        self.assertEqual(self.registro()["atacado_gelada_qtd"], 3)

    def test_cada_faixa_exige_minimo_e_preco_juntos(self):
        for quantidade, preco in (("atacado_qtd", "preco_atacado_cent"),
                                  ("atacado_gelada_qtd", "preco_atacado_gelada_cent")):
            for dados in ({quantidade: "12"}, {preco: "5"}):
                with self.subTest(dados=dados), self.assertRaisesRegex(ErroValidacao, "ambos zero"):
                    self.alterar(**dados)

    def test_atacado_nao_supera_varejo_da_temperatura(self):
        for dados in (
            {"atacado_qtd": "12", "preco_atacado_cent": "8,01"},
            {"preco_gelada_cent": "10", "atacado_gelada_qtd": "6", "preco_atacado_gelada_cent": "10,01"},
            {"atacado_gelada_qtd": "6", "preco_atacado_gelada_cent": "7"},
        ):
            with self.subTest(dados=dados), self.assertRaisesRegex(ErroValidacao, "varejo"):
                self.alterar(**dados)

    def test_alteracoes_parciais_validam_faixa_atual(self):
        self.alterar(atacado_qtd="12", preco_atacado_cent="7")
        self.alterar(preco_atacado_cent="6,50")
        self.assertEqual(self.registro()["atacado_qtd"], 12)
        for dados in ({"preco_cent": "6"}, {"atacado_qtd": "0"}, {"preco_atacado_cent": "0"}):
            with self.subTest(dados=dados), self.assertRaises(ErroValidacao):
                self.alterar(**dados)
        self.assertEqual(self.registro()["preco_atacado_cent"], 650)

    def test_nao_desliga_gelada_com_atacado_gelada_ativo(self):
        self.alterar(preco_gelada_cent="10", atacado_gelada_qtd="6", preco_atacado_gelada_cent="9")
        with self.assertRaises(ErroValidacao):
            self.alterar(preco_gelada_cent="0")
        self.alterar(preco_gelada_cent="0", atacado_gelada_qtd="0", preco_atacado_gelada_cent="0")

    def test_quantidade_decimal_somente_se_permitida(self):
        for campo, preco in (("atacado_qtd", "preco_atacado_cent"),
                             ("atacado_gelada_qtd", "preco_atacado_gelada_cent")):
            with self.subTest(campo=campo), self.assertRaisesRegex(ErroValidacao, "inteira"):
                self.alterar(**{campo: "2,5", preco: "7", "preco_gelada_cent": "9"})
        self.alterar(aceita_decimal="S", atacado_qtd="2,1234", preco_atacado_cent="7")
        self.assertEqual(self.registro()["atacado_qtd"], 2.1234)
        with self.assertRaisesRegex(ErroValidacao, "inteira"):
            self.alterar(aceita_decimal="N")

    def test_quantidades_invalidas_nao_sao_arredondadas(self):
        self.alterar(aceita_decimal="S")
        for valor in ("nan", "inf", "-inf", "1e999", "-1", "2,12345", "0,00001", "abc", True):
            with self.subTest(valor=valor), self.assertRaises(ErroValidacao):
                self.alterar(atacado_qtd=valor, preco_atacado_cent="7")
        self.alterar(atacado_qtd="2,123400", preco_atacado_cent="7")
        self.assertEqual(self.registro()["atacado_qtd"], 2.1234)

    def test_precos_negativos_recusados(self):
        for campo in ("preco_cent", "preco_gelada_cent", "preco_atacado_cent", "preco_atacado_gelada_cent"):
            with self.subTest(campo=campo), self.assertRaises(ErroValidacao):
                self.alterar(**{campo: "-0,01"})

    def test_hook_exige_precos_inteiros_em_centavos(self):
        for campo in ("preco_gelada_cent", "preco_atacado_cent", "preco_atacado_gelada_cent"):
            for valor in (0.5, True, float("nan"), float("inf"), -1):
                with self.subTest(campo=campo, valor=valor), self.assertRaises(ErroValidacao):
                    _antes_produto(self.banco, {campo: valor}, self.bebida)

    def test_casco_separado_e_remocao_opcional(self):
        self.alterar(casco_produto_id=self.casco)
        self.assertEqual(self.registro()["casco_produto_id"], self.casco)
        self.alterar(nome="CERVEJA RETORNAVEL")
        self.assertEqual(self.registro()["casco_produto_id"], self.casco)
        self.alterar(casco_produto_id=None)
        self.assertIsNone(self.registro()["casco_produto_id"])

    def test_casco_deve_existir_ativo_e_a_venda(self):
        for casco_id in (self.bebida, 999999):
            with self.subTest(casco_id=casco_id), self.assertRaises(ErroValidacao):
                self.alterar(casco_produto_id=casco_id)
        for campo in ("ativo", "venda"):
            self.cad.salvar("produtos", {campo: "N"}, self.casco)
            with self.subTest(campo=campo), self.assertRaises(ErroValidacao):
                self.alterar(casco_produto_id=self.casco)
            self.cad.salvar("produtos", {campo: "S"}, self.casco)

    def test_casco_nao_tem_casco_proprio_nem_ciclo(self):
        terceiro = self.novo_produto("OUTRO CASCO", 300)
        self.cad.salvar("produtos", {"casco_produto_id": terceiro}, self.casco)
        with self.assertRaises(ErroValidacao):
            self.alterar(casco_produto_id=self.casco)
        with self.assertRaises(ErroValidacao):
            self.cad.salvar("produtos", {"casco_produto_id": self.casco}, terceiro)

    def test_edicao_do_casco_nao_invalida_bebida_vinculada(self):
        self.alterar(casco_produto_id=self.casco)
        for dados in ({"ativo": "N"}, {"venda": "N"}, {"casco_produto_id": self.bebida}):
            with self.subTest(dados=dados), self.assertRaises(ErroValidacao):
                self.cad.salvar("produtos", dados, self.casco)
        self.cad.salvar("produtos", {"nome": "CASCO 600ML"}, self.casco)

    def test_excluir_casco_referenciado_orienta_desvincular_bebidas(self):
        self.alterar(casco_produto_id=self.casco)
        with self.assertRaisesRegex(ErroNegocio, "Desvincule o casco no cadastro das bebidas") as erro:
            self.cad.excluir("produtos", self.casco)
        self.assertNotIn("Desmarque", str(erro.exception))
        self.assertIsNotNone(self.cad.obter("produtos", self.casco))
        self.assertEqual(self.registro()["casco_produto_id"], self.casco)
        self.alterar(casco_produto_id=None)
        self.cad.excluir("produtos", self.casco)
        self.assertIsNone(self.cad.obter("produtos", self.casco))

    def test_lookup_somente_cascos_ativos_a_venda_e_sem_casco(self):
        self.alterar(casco_produto_id=self.casco)
        inativo = self.novo_produto("INATIVO", ativo="N")
        sem_venda = self.novo_produto("INSUMO", venda="N")
        ids = dict(self.cad.opcoes("cascos"))
        self.assertIn(self.casco, ids)
        for id_ in (self.bebida, inativo, sem_venda):
            self.assertNotIn(id_, ids)

    def test_casco_incompativel_com_fracionamento_e_montagem(self):
        for dados in (
            {"aceita_decimal": "S"}, {"partes": "2"}, {"montagem": "S"}, {"para_ser_montado": "S"},
            {"manual": "S"}, {"composto": "S"}, {"balanca": "S"},
        ):
            with self.subTest(dados=dados), self.assertRaisesRegex(ErroValidacao, "fracionamento"):
                self.alterar(casco_produto_id=self.casco, **dados)
        self.alterar(casco_produto_id=self.casco)
        with self.assertRaises(ErroValidacao):
            self.alterar(aceita_decimal="S")

    def test_casco_incompativel_com_fardo_existente(self):
        fardo = self.prod.criar_embalagem(self.bebida, 12, "FARDO", 8000)
        for id_ in (self.bebida, fardo):
            with self.subTest(id_=id_), self.assertRaisesRegex(ErroValidacao, "fardo"):
                self.cad.salvar("produtos", {"casco_produto_id": self.casco}, id_)

    def test_importacao_e_cadastro_rapido_preservam_opcoes_na_edicao(self):
        self.alterar(preco_gelada_cent="10", atacado_qtd="12", preco_atacado_cent="7")
        self.alterar(nome="NOME IMPORTADO", preco_cent="9")
        self.assertEqual((self.registro()["preco_gelada_cent"], self.registro()["atacado_qtd"]), (1000, 12))
        subgrupo = self.registro()["subgrupo_id"]
        produto = self.prod.cadastrar_rapido("7891234567895", "AGUA", 300, subgrupo)
        self.assertEqual(produto["preco_gelada_cent"], 0)
        self.assertIsNone(produto["casco_produto_id"])


try:
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QTabWidget
    from src.ui.contexto import Contexto
    from src.ui_qt.cadastros import FormularioCadastro, FormularioEmbalagem, JanelaCadastro
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 não instalado")
class TesteCadastroAdegaQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.bebida = self.novo_produto("CERVEJA", 800)
        self.janelas = []
        self.addCleanup(self.fechar)

    def fechar(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self, classe=JanelaCadastro, *args):
        janela = classe(self.ctx, *args)
        self.janelas.append(janela)
        return janela

    def test_formulario_adega_salva_e_reabre(self):
        formulario = self.janela(FormularioCadastro, "produtos", self.bebida)
        abas = formulario.findChild(QTabWidget)
        self.assertIn("Adega", [abas.tabText(i) for i in range(abas.count())])
        formulario.campos["preco_gelada_cent"].setText("10")
        formulario.campos["atacado_qtd"].setText("12")
        formulario.campos["preco_atacado_cent"].setText("7")
        formulario.salvar()
        self.assertEqual(formulario.result(), QDialog.DialogCode.Accepted)
        reaberto = self.janela(FormularioCadastro, "produtos", self.bebida)
        self.assertEqual(reaberto.campos["preco_gelada_cent"].text(), "10,00")

    def test_botao_fardo_so_em_produtos_e_exige_selecao(self):
        janela = self.janela(JanelaCadastro, "produtos")
        self.assertIn("Criar fardo", [b.text() for b in janela.findChildren(QPushButton)])
        janela.criar_embalagem()
        self.assertIn("Selecione", janela.mensagem.text())
        grupos = self.janela(JanelaCadastro, "grupos")
        self.assertNotIn("Criar fardo", [b.text() for b in grupos.findChildren(QPushButton)])

    def test_fardo_usa_controlador_e_baixa_unidades(self):
        formulario = self.janela(FormularioEmbalagem, self.bebida)
        self.assertEqual(formulario.quantidade.text(), "12")
        formulario.preco.setText("84,00")
        with patch.object(self.ctx.produtos, "criar_embalagem",
                          wraps=self.ctx.produtos.criar_embalagem) as criar:
            formulario.salvar()
        criar.assert_called_once_with(self.bebida, 12.0, "CERVEJA - FARDO", 8400, None, self.ctx.operador_id)
        self.assertEqual(formulario.result(), QDialog.DialogCode.Accepted)
        embalagem = self.ctx.produtos.embalagem(formulario.id_)
        self.assertEqual((embalagem["unitario_id"], embalagem["quantidade"]), (self.bebida, 12))

    def test_fardo_invalido_permanece_aberto(self):
        formulario = self.janela(FormularioEmbalagem, self.bebida)
        formulario.preco.setText("10")
        formulario.quantidade.setText("1")
        formulario.salvar()
        self.assertIsNone(formulario.id_)
        self.assertIn("de 2 a 999", formulario.mensagem.text())
        formulario.quantidade.setText("abc")
        formulario.salvar()
        self.assertIn("inválidos", formulario.mensagem.text())

    def test_fardo_revalida_permissao_ao_salvar_e_abrir(self):
        formulario = self.janela(FormularioEmbalagem, self.bebida)
        formulario.preco.setText("84")
        with patch.object(self.ctx, "pode", return_value=False), \
             patch.object(self.ctx.produtos, "criar_embalagem") as criar:
            formulario.salvar()
            criar.assert_not_called()
            self.assertIn("acesso", formulario.mensagem.text())
            with self.assertRaises(ErroNegocio):
                FormularioEmbalagem(self.ctx, self.bebida)

    def test_botao_fardo_atualiza_somente_quando_criado(self):
        janela = self.janela(JanelaCadastro, "produtos")
        janela.grade.selectRow(0)
        with patch.object(FormularioEmbalagem, "exec", return_value=QDialog.DialogCode.Accepted), \
             patch.object(janela, "atualizar") as atualizar:
            janela.criar_embalagem()
            atualizar.assert_called_once()
        self.assertIn("baixa as unidades", janela.mensagem.text())
        with patch.object(FormularioEmbalagem, "exec", return_value=QDialog.DialogCode.Rejected), \
             patch.object(janela, "atualizar") as atualizar:
            janela.criar_embalagem()
            atualizar.assert_not_called()
