"""Reposição pelo giro por caixa e etiquetas de produtos/preços (controllers, Tk e Qt)."""
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

try:
    import tkinter as tk
    from src.ui.estoque_ui import PainelEstoque
except ImportError:
    tk = None


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
        self.assertEqual((c1["consumo_30_dias"], c1["alvo_qtd"], c1["sugerido"], c1["terminal"]), (30, 7, 5, 1))
        self.assertEqual(self.est.reposicao_giro(2)[0]["sugerido"], 12)
        self.assertEqual(self.est.reposicao_giro()[0]["sugerido"], 19)
        self.assertEqual(self.est.reposicao_giro(3), [])
        self.assertEqual(self.est.terminais(), [1, 2])

    def test_estorno_janela_saldo_sem_controle_e_quatro_casas(self):
        pid = self.produto("A", qt=0)
        self.venda(pid, 30)
        self.venda(pid, 30, dias=-31)
        self.assertEqual(self.est.reposicao_giro(1)[0]["consumo_30_dias"], 30)
        self.venda(pid, 15, tipo="estorno_venda")
        self.assertEqual(self.est.reposicao_giro(1)[0]["sugerido"], 3.5)
        cheio = self.produto("B", qt=100)
        self.venda(cheio, 30)
        livre = self.novo_produto("C")
        self.venda(livre, 30)
        self.assertEqual([p["id"] for p in self.est.reposicao_giro(1)], [pid])
        raro = self.produto("D", qt=0)
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
        manual = self.est.pedido_por_giro(self.fornecedor, [(pid, 3)], 1)
        self.assertEqual(self.est.itens(manual)[0]["quantidade"], 3)
        with self.assertRaises(ErroNegocio):
            self.est.pedido_por_giro(self.fornecedor, None, 2)

    def test_texto_informa_escopo_e_sugestao(self):
        self.venda(self.produto(), 30, terminal=2)
        texto = self.est.texto_reposicao_giro(self.est.reposicao_giro(2), 2)
        self.assertIn("CAIXA 2", texto)
        self.assertIn("SUGESTÃO", texto)


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


@unittest.skipUnless(tk, "Tkinter indisponível")
class TesteGiroEtiquetasTk(BaseGiro):
    def setUp(self):
        super().setUp()
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("sem ambiente gráfico")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        from src.ui import tema
        tema.aplicar_tema(self.root)
        self.ctx = SimpleNamespace(
            banco=self.banco, estoque=self.est,
            cadastros=SimpleNamespace(opcoes=lambda _: [(self.fornecedor, "DISTRIBUIDORA")]))
        self.pid = self.produto("CERVEJA", qt=2)
        self.venda(self.pid, 30, terminal=2)
        self.painel = PainelEstoque(self.root, self.ctx)

    def test_giro_do_caixa_escolhido_so_cria_pedido_se_confirmar(self):
        with patch("src.ui.estoque_ui.Visualizador") as ver, patch("src.ui.tema.escolher", side_effect=[2]), \
                patch("src.ui.tema.confirmar", return_value=False):
            self.painel.reposicao_giro()
        self.assertIn("CAIXA 2", ver.call_args.args[3])
        self.assertEqual(self.est.lancamentos("pedido"), [])
        with patch("src.ui.estoque_ui.Visualizador"), patch("src.ui.tema.escolher", side_effect=[2, self.fornecedor]), \
                patch("src.ui.tema.confirmar", return_value=True), patch.object(PainelEstoque, "novo_lancamento"):
            self.painel.reposicao_giro()
        pedido = self.est.lancamentos("pedido")[0]
        self.assertEqual(self.est.itens(pedido["id"])[0]["quantidade"], 5)

    def test_giro_de_outro_caixa_sem_venda_avisa(self):
        with patch("src.ui.tema.escolher", return_value=1), patch("src.ui.tema.aviso") as aviso, \
                patch("src.ui.estoque_ui.Visualizador") as ver:
            self.painel.reposicao_giro()
        aviso.assert_called_once()
        ver.assert_not_called()

    def test_dialogo_de_etiquetas_seleciona_e_abre_previa(self):
        from src.ui.etiquetas_ui import DialogoEtiquetas
        outro = self.produto("OUTRA", qt=1)
        linhas = [dict(l) for l in self.painel.linhas]
        linhas.append({**self.painel.linhas[0], "id": outro, "nome": "OUTRA"})
        dialogo = DialogoEtiquetas(self.root, self.ctx, linhas, [self.pid, outro])
        self.addCleanup(dialogo.destroy)
        dialogo.v_copias.set("2")
        with patch("src.ui.etiquetas_ui.Visualizador") as ver:
            dialogo.previa()
        self.assertEqual(len(dialogo.itens()), 2)
        self.assertEqual(ver.call_args.args[3].count("Cód"), 4)
        self.assertIn("codigo;nome", ver.call_args.kwargs["csv"])
        dialogo.v_copias.set("0")
        with patch("src.ui.etiquetas_ui.Visualizador") as ver, patch("src.ui.tema.erro") as erro:
            dialogo.previa()
        ver.assert_not_called()
        erro.assert_called_once()

    def test_botoes_acessiveis_no_painel(self):
        self.assertEqual(self.painel.b_giro.cget("text"), "Reposição pelo giro")
        with patch("src.ui.etiquetas_ui.DialogoEtiquetas") as dialogo:
            self.painel.etiquetas()
        dialogo.assert_called_once()


try:
    from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog
    from src.ui.contexto import Contexto
    from src.ui_qt.estoque import JanelaEstoque
    from src.ui_qt.etiquetas import JanelaEtiquetas
    from src.ui_qt.tema import aplicar
    from src.ui_qt.visualizador import JanelaVisualizador
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication, "PySide6 indisponível")
class TesteGiroEtiquetasQt(BaseGiro):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.aplicacao = QApplication.instance() or QApplication([])
        aplicar(cls.aplicacao)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.pid = self.produto("CERVEJA", qt=2)
        self.venda(self.pid, 30, terminal=2)
        self.janela = JanelaEstoque(self.ctx)
        self.addCleanup(self.janela.close)

    def test_giro_por_caixa_so_gera_pedido_confirmado(self):
        with patch.object(QInputDialog, "getItem", return_value=("Caixa 2", True)), \
                patch.object(JanelaVisualizador, "exec") as ver, \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertTrue(self.janela.reposicao_giro())
        ver.assert_called_once()
        self.assertEqual(self.ctx.estoque.lancamentos("pedido"), [])
        respostas = [("Caixa 2", True), ("DISTRIBUIDORA", True)]
        with patch.object(QInputDialog, "getItem", side_effect=respostas), \
                patch.object(JanelaVisualizador, "exec"), patch.object(JanelaEstoque, "abrir_lancamentos"), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(self.janela.reposicao_giro())
        pedido = self.ctx.estoque.lancamentos("pedido")[0]
        self.assertEqual(self.ctx.estoque.itens(pedido["id"])[0]["quantidade"], 5)

    def test_giro_sem_venda_no_caixa_mostra_mensagem(self):
        with patch.object(QInputDialog, "getItem", return_value=("Caixa 1", True)):
            self.assertFalse(self.janela.reposicao_giro())
        self.assertIn("Nenhum produto", self.janela.mensagem.text())

    def test_etiquetas_selecao_previa_e_csv(self):
        self.janela.grade.selectRow(0)
        dialogo = self.janela.etiquetas()
        self.assertIsInstance(dialogo, JanelaEtiquetas)
        self.addCleanup(dialogo.close)
        dialogo.copias.setValue(3)
        self.assertEqual(dialogo.itens(), [{"produto_id": self.pid, "copias": 3, "temperatura": "natural"}])
        with patch.object(JanelaVisualizador, "exec") as ver:
            self.assertTrue(dialogo.previa())
        ver.assert_called_once()
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "etiquetas.csv")
            self.assertTrue(dialogo.exportar_csv(caminho))
            with open(caminho, encoding="utf-8-sig") as f:
                self.assertEqual(len(f.read().splitlines()), 4)
        dialogo.grade.clearSelection()
        self.assertFalse(dialogo.previa())
        self.assertIn("Selecione", dialogo.mensagem.text())


if __name__ == "__main__":
    unittest.main()