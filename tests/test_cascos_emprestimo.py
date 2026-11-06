"""Cascos levados sem trazer, pelo cliente identificado: anotados como empréstimo ao fechar a venda."""
from __future__ import annotations

from src.controllers.perfil_controller import PerfilController
from src.controllers.retornaveis_controller import RetornaveisController
from src.core.erros import ErroNegocio
from tests.test_caixa import BaseCaixa


class TesteCascosEmprestados(BaseCaixa):
    def setUp(self):
        super().setUp()
        PerfilController(self.banco, self.adm).aplicar("adega")
        self.casco = self.novo_produto("CASCO 600ML", 300)
        self.banco.executar("UPDATE produtos SET casco_produto_id = ? WHERE id = ?", (self.casco, self.skol))
        self.joao = self.cliente("JOAO", limite=100000)
        self.retornaveis = RetornaveisController(self.banco, self.adm)

    def saldo(self):
        return self.retornaveis.saldo(self.joao, self.casco)

    def venda_do_joao(self, qtd=6, cobrados=2, emprestados=3):
        vid = self.caixa.abrir_caderneta(self.joao)
        item = self.caixa.adicionar_item(vid, self.skol, qtd, quantidade_cascos=cobrados, cascos_emprestados=emprestados)
        return vid, item

    def test_fechar_anota_o_emprestimo_e_cancelar_o_cupom_desfaz(self):
        vid, _ = self.venda_do_joao()
        self.assertEqual(self.saldo(), 0)                                # lançar não anota: só o fechamento
        self.caixa.fechar(vid)
        self.assertEqual(self.saldo(), 3)
        movimento = self.retornaveis.historico(self.joao, self.casco)[0]
        self.assertIn("levou sem trazer o casco", movimento["motivo"])
        self.assertEqual(movimento["tipo"], "emprestimo")
        self.caixa.cancelar_venda(vid, "lançada errado")
        self.assertEqual(self.saldo(), 0)

    def test_venda_aberta_cancelada_nao_anota_nada(self):
        vid, _ = self.venda_do_joao()
        self.caixa.cancelar_venda(vid, "desistiu")
        self.assertEqual(self.saldo(), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM retornaveis_movimentos"), 0)

    def test_cancelamento_parcial_limita_ao_que_foi_levado(self):
        vid, item = self.venda_do_joao(qtd=6, cobrados=0, emprestados=5)
        self.caixa.cancelar_item(item, "quebrou 4", quantidade=4)
        self.caixa.fechar(vid)
        self.assertEqual(self.saldo(), 2)

    def test_validacoes(self):
        vid = self.caixa.abrir_caderneta(self.joao)
        with self.assertRaisesRegex(ErroNegocio, "não podem passar"):
            self.caixa.adicionar_item(vid, self.skol, 6, quantidade_cascos=2, cascos_emprestados=5)
        with self.assertRaisesRegex(ErroNegocio, "retornável"):
            self.caixa.adicionar_item(vid, self.agua, 2, cascos_emprestados=1)
        for invalido in (-1, 1.5, True):
            with self.assertRaises(ErroNegocio):
                self.caixa.adicionar_item(vid, self.skol, 2, cascos_emprestados=invalido)
        balcao = self.caixa.abrir_balcao()
        with self.assertRaisesRegex(ErroNegocio, "precisa ter o cliente"):
            self.caixa.adicionar_item(balcao, self.skol, 2, cascos_emprestados=1)

    def test_devolucao_pela_tela_de_retornaveis_e_lista_de_quem_deve(self):
        vid, _ = self.venda_do_joao(emprestados=2)
        self.caixa.fechar(vid)
        devedores = self.retornaveis.devedores()
        self.assertEqual([(d["cliente"], d["produto"], d["saldo"]) for d in devedores], [("JOAO", "CASCO 600ML", 2)])
        self.retornaveis.registrar(self.joao, self.casco, "devolucao", 2, "trouxe os cascos")
        self.assertEqual(self.retornaveis.devedores(), [])

    def test_duas_leituras_agrupadas_somam_os_emprestados(self):
        self.banco.cfg_set("agrupar_itens_balcao", "S")
        vid = self.caixa.abrir_caderneta(self.joao)
        self.caixa.adicionar_item(vid, self.skol, 2, cascos_emprestados=1)
        self.caixa.adicionar_item(vid, self.skol, 2, cascos_emprestados=2)
        self.caixa.fechar(vid)
        self.assertEqual(self.saldo(), 3)


def _descartar(janela):
    """Fecha e destrói a janela agora (sobra para o fim do Python derruba o processo no Qt)."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    janela.close()
    janela.deleteLater()
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


try:
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from src.controllers.contexto import Contexto
    from src.ui_qt.retornaveis import JanelaRetornaveis
except ImportError:                                   # pragma: no cover - sem PySide6
    JanelaRetornaveis = None

if JanelaRetornaveis is not None:
    class TesteQuemDeveNaTela(TesteCascosEmprestados):
        def test_texto_de_quem_deve(self):
            self.app = QApplication.instance() or QApplication([])
            ctx = Contexto(self.banco)
            ctx.operador = ctx.acesso.autenticar("ADM", "ADM")
            janela = JanelaRetornaveis(ctx)
            self.addCleanup(_descartar, janela)
            self.assertIn("Nenhum cliente", janela.texto_devedores())
            vid, _ = self.venda_do_joao(emprestados=3)
            self.caixa.fechar(vid)
            texto = janela.texto_devedores()
            self.assertIn("JOAO", texto)
            self.assertIn("CASCO 600ML", texto)

    for _nome in [n for n in dir(TesteCascosEmprestados) if n.startswith("test_")]:
        setattr(TesteQuemDeveNaTela, _nome, None)
