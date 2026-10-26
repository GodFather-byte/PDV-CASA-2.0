"""Caixa Qt (piloto): venda real pelo CaixaController acionada pelos widgets, num banco em memória."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
except ImportError:                                   # pragma: no cover - sem PySide6 o piloto Qt não roda
    QApplication = None

from tests.base import BaseTeste

if QApplication is not None:
    from src.controllers.cadastro_controller import CadastroController
    from src.controllers.contexto import Contexto
    from src.ui_qt.caixa import (JanelaCaixa, PAGINA_ABERTURA, PAGINA_VENDA, _fmt_qtd,
                                 ler_dinheiro)


class DialogosFalsos:
    """Respostas roteirizadas no lugar das janelas de pergunta; guarda os avisos e erros mostrados."""

    def __init__(self):
        self.confirmacoes, self.textos, self.escolhas = [], [], []
        self.avisos, self.erros, self.perguntas = [], [], []
        self.maquininhas, self.paineis = [], []
        self.maquininha_ok = True

    def aviso(self, titulo, texto):
        self.avisos.append(texto)

    def erro(self, titulo, texto):
        self.erros.append(texto)

    def confirmar(self, titulo, texto, padrao_sim=True):
        self.perguntas.append(texto)
        if not self.confirmacoes:
            raise AssertionError(f"Confirmação inesperada: {texto}")
        return self.confirmacoes.pop(0)

    def pedir_texto(self, titulo, rotulo, senha=False, padrao=""):
        self.perguntas.append(rotulo)
        if not self.textos:
            raise AssertionError(f"Pergunta inesperada: {rotulo}")
        return self.textos.pop(0)

    def escolher(self, titulo, rotulo, opcoes):
        return self.escolhas.pop(0) if self.escolhas else None

    def maquininha(self, maq, lancamentos=None):
        self.maquininhas.append((maq, lancamentos))
        return self.maquininha_ok

    def painel_fechamento(self, ctx, res, vias, **ganchos):
        self.paineis.append((res, vias))


@unittest.skipIf(QApplication is None, "PySide6 não instalado")
class BaseCaixaQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        for chave in ("imprimir_cupom", "imprimir_saida_ao_pagar", "imprimir_fechamento_ao_trocar", "pergunta_pessoas",
                      "controle_garcom"):
            self.banco.cfg_set(chave, "0")
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.autenticar("ADM", "ADM")
        self.janelas = []
        self.addCleanup(self._fechar_janelas)

    def _fechar_janelas(self):
        for j in self.janelas:
            j._ocupado = j._fechando_venda = False
            j.venda_id = None                      # não pergunta nada ao descartar no fim do teste
            j.dialogos = DialogosFalsos()
            j.dialogos.confirmacoes = [True] * 3
            j.close()
            j.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        j = JanelaCaixa(self.ctx)
        j.dialogos = DialogosFalsos()
        # A janela do acerto é modal: sem troca explícita no teste (patch.object), ela "desiste" (Esc) e anota que abriu.
        j.acertos_abertos = []
        j._dialogo_acerto = lambda *args, **kw: j.acertos_abertos.append(args) or None
        j.show()
        self.janelas.append(j)
        return j

    def abrir_turno(self, valor=10000):
        return self.ctx.turnos.abrir(self.ctx.operador_id, 1, valor)

    def operador_bar(self):
        oid = CadastroController(self.banco).salvar("operadores", {"nome": "BAR", "senha": "1234", "nivel": "0"})
        self.ctx.operador = self.ctx.acesso.operador(oid)
        return oid

    def lancar(self, j, codigo, qtd="1"):
        j.ent_codigo.setText(codigo)
        j.ent_qtd.setText(qtd)
        j.btn_lancar.click()

    def contar(self, tabela):
        return self.banco.valor(f"SELECT COUNT(*) FROM {tabela}")

    def forma(self, j, nome):
        j.cmb_forma.setCurrentIndex(j.cmb_forma.findData(self.tipo(nome)))

class TestAuxiliares(unittest.TestCase):
    @unittest.skipIf(QApplication is None, "PySide6 não instalado")
    def test_quantidade_e_dinheiro(self):
        self.assertEqual(_fmt_qtd(1), "1")
        self.assertEqual(_fmt_qtd(1.2345), "1,2345")
        self.assertEqual(_fmt_qtd(0.5), "0,5")
        self.assertEqual(ler_dinheiro("", permitir_zero=True), 0)
        self.assertEqual(ler_dinheiro("0,00", permitir_zero=True), 0)
        self.assertEqual(ler_dinheiro("1.234,56"), 123456)
        for ruim in ("abc", "-5", "1e5", "1,234"):
            with self.assertRaises(ValueError):
                ler_dinheiro(ruim, permitir_zero=True)


class TestTurnoQt(BaseCaixaQt):
    def test_abre_turno_pelos_widgets(self):
        j = self.janela()
        self.assertEqual(j.paginas.currentIndex(), PAGINA_ABERTURA)
        j.ent_fundo.setText("abc")
        j.btn_abrir_turno.click()
        self.assertIsNone(self.ctx.turnos.atual())
        self.assertTrue(j.dialogos.avisos)
        j.ent_fundo.setText("50,00")
        j.dialogos.confirmacoes = [False]
        j.btn_abrir_turno.click()
        self.assertIsNone(self.ctx.turnos.atual())
        j.dialogos.confirmacoes = [True]
        j.btn_abrir_turno.click()
        turno = self.ctx.turnos.atual()
        self.assertEqual(turno["valor_inicial_cent"], 5000)
        self.assertEqual(turno["aberto_em"], "2026-10-03 21:00:00")
        self.assertEqual(j.paginas.currentIndex(), PAGINA_VENDA)

    def test_licenca_bloqueada_impede_abrir_turno(self):
        j = self.janela()
        j.ent_fundo.setText("0")
        j.dialogos.confirmacoes = [True]
        bloqueio = SimpleNamespace(bloqueia=True, mensagem="Licença vencida.")
        with patch("src.controllers.turno_controller.licenca.estado", return_value=bloqueio):
            j.btn_abrir_turno.click()
        self.assertIsNone(self.ctx.turnos.atual())
        self.assertIn("Licença vencida", j.dialogos.erros[0])
        self.assertEqual(j.paginas.currentIndex(), PAGINA_ABERTURA)

    def test_sem_turno_nao_vende(self):
        self.novo_produto("SKOL", 800, codigo="10")
        j = self.janela()
        self.lancar(j, "10")
        self.assertEqual(self.contar("vendas"), 0)

    def test_fecha_turno_pelos_widgets(self):
        self.abrir_turno()
        self.novo_produto("SKOL", 800, codigo="10")
        j = self.janela()
        self.lancar(j, "10")
        j.btn_trocar_turno.click()                       # balcão com itens: não troca
        self.assertEqual(j.paginas.currentIndex(), PAGINA_VENDA)
        self.assertIn("venda em andamento", j.dialogos.avisos[-1])
        j.ent_valor.setText("8,00")
        j.btn_receber.click()
        j.btn_fechar_venda.click()
        j.dialogos.textos = ["108,00"]
        j.dialogos.confirmacoes = [False]
        j.btn_trocar_turno.click()                       # a maquininha é conferida antes da gaveta; "Não" na confirmação
        self.assertEqual(len(j.dialogos.maquininhas), 1)
        self.assertIsNotNone(self.ctx.turnos.atual())
        self.assertNotIn("esperado", " ".join(j.dialogos.perguntas).lower())      # o esperado não é revelado
        j.dialogos.textos = ["108,00"]
        j.dialogos.confirmacoes = [True]
        with patch("src.controllers.utilitario_controller.UtilitarioController.backup_automatico", return_value="ok"):
            j.btn_trocar_turno.click()                   # só a gaveta é digitada: nada de valor por forma
        self.assertEqual(len(j.dialogos.paineis), 1)     # o resumo do turno aparece depois de fechar
        self.assertIsNone(self.ctx.turnos.atual())
        self.assertEqual(self.banco.valor("SELECT valor_final_cent FROM turnos"), 10800)
        self.assertEqual(j.paginas.currentIndex(), PAGINA_ABERTURA)
        self.assertTrue(j.isVisible())                   # o turno fecha, a janela não


class TestVendaQt(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.abrir_turno()
        self.skol = self.novo_produto("SKOL", 800, codigo="10", estoque=True, qt=10)
        self.lata = self.novo_produto("COCA LATA", 500, codigo="20")
        self.litro = self.novo_produto("COCA 2L", 900, codigo="21")

    def test_venda_de_balcao_completa(self):
        j = self.janela()
        self.lancar(j, "10", "2")
        self.lancar(j, "coca")                           # dois produtos: abre a lista para escolher
        self.assertFalse(j.lista_produtos.isHidden())
        self.assertEqual(j.lista_produtos.count(), 2)
        linha = next(i for i in range(2) if j.lista_produtos.item(i).data(0x0100) == self.litro)
        j.lista_produtos.setCurrentRow(linha)
        j.btn_lancar.click()
        self.assertTrue(j.lista_produtos.isHidden())
        self.assertEqual(j.tabela.rowCount(), 2)
        self.assertEqual(j.tabela.item(0, 4).text(), "2")
        self.assertEqual(j.lbl_total.text(), "25,00")
        venda_id = j.venda_id
        self.assertEqual(j.ent_valor.text(), "25,00")
        self.forma(j, "Dinheiro")
        j.ent_valor.setText("30")
        j.btn_receber.click()
        j.btn_fechar_venda.click()
        v = self.ctx.caixa.obter(venda_id)
        self.assertEqual(v["status"], "fechada")
        self.assertIsNotNone(v["cupom"])
        self.assertEqual((v["total_cent"], v["pago_cent"], v["troco_cent"]), (2500, 3000, 500))
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 8)
        self.assertIsNone(j.venda_id)
        self.assertEqual(j.lbl_troco.text(), "5,00")
        self.assertIn("Troco R$ 5,00", j.lbl_status.text())
        self.assertEqual(j.tabela.rowCount(), 0)

    def test_quantidade_fracionada_com_quatro_casas(self):
        self.banco.executar("UPDATE produtos SET aceita_decimal = 1 WHERE id = ?", (self.lata,))
        j = self.janela()
        self.lancar(j, "20", "1,2345")
        self.assertEqual(self.banco.valor("SELECT quantidade FROM itens_venda"), 1.2345)
        self.assertEqual(j.tabela.item(0, 4).text(), "1,2345")

    def test_erros_nao_alteram_o_banco(self):
        j = self.janela()
        self.lancar(j, "999")
        self.assertIn("não encontrado", j.lbl_status.text())
        self.lancar(j, "10", "abc")
        self.lancar(j, "10", "0")                        # o controller recusa: o balcão aberto junto é desfeito
        self.lancar(j, "10", "1,5")                      # não aceita fração
        self.assertEqual(self.contar("vendas"), 0)
        self.assertIsNone(j.venda_id)
        self.assertEqual(len(j.dialogos.erros), 2)
        self.lancar(j, "10")
        venda_id = j.venda_id
        self.forma(j, "Pix")
        j.ent_valor.setText("100,00")
        j.btn_receber.click()                            # Pix não dá troco: desfaz o pagamento
        self.assertIn("não dá troco", j.dialogos.erros[-1])
        self.assertEqual(self.contar("pagamentos_venda"), 0)
        j.ent_valor.setText("1e5")
        j.btn_receber.click()
        self.assertEqual(self.contar("pagamentos_venda"), 0)
        j.ent_valor.setText("3,00")
        j.btn_receber.click()
        j.btn_fechar_venda.click()                       # falta pagar
        self.assertIn("Faltam", j.dialogos.erros[-1])
        v = self.ctx.caixa.obter(venda_id)
        self.assertEqual(v["status"], "aberta")
        self.assertIsNone(v["cupom"])
        j.lista_pagamentos.setCurrentRow(0)
        j.btn_remover_pag.click()
        self.assertEqual(self.contar("pagamentos_venda"), 0)

    def test_troco_alto_pede_confirmacao(self):
        j = self.janela()
        self.lancar(j, "10")
        self.forma(j, "Dinheiro")
        j.ent_valor.setText("600,00")
        j.dialogos.confirmacoes = [False]
        j.btn_receber.click()
        self.assertEqual(self.contar("pagamentos_venda"), 0)
    def test_cancelar_item_exige_supervisor(self):
        self.operador_bar()
        j = self.janela()
        self.lancar(j, "10")
        self.lancar(j, "20")
        j.tabela.selectRow(0)
        j.dialogos.textos = [None]                       # desistiu da senha: nada muda
        j.btn_cancelar_item.click()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda WHERE cancelado = 1"), 0)
        j.tabela.selectRow(0)
        j.dialogos.textos = ["errada", "1234", "ADM"]   # o próprio operador nível 0 não autoriza
        j.dialogos.confirmacoes = [True]
        j.btn_cancelar_item.click()
        self.assertEqual(sum("Senha inválida" in e for e in j.dialogos.erros), 2)
        cancelado = self.banco.um("SELECT * FROM itens_venda WHERE cancelado = 1")
        self.assertEqual(cancelado["produto_id"], self.skol)
        self.assertEqual(j.lbl_total.text(), "5,00")

    def test_tres_senhas_erradas_nao_cancelam(self):
        self.operador_bar()
        j = self.janela()
        self.lancar(j, "10")
        j.tabela.selectRow(0)
        j.dialogos.textos = ["x", "y", "z"]
        j.btn_cancelar_item.click()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda WHERE cancelado = 1"), 0)

    def test_cancelar_venda_com_autorizacao_e_motivo(self):
        self.banco.cfg_set("exigir_motivo_cancelamento", "S")
        self.operador_bar()
        j = self.janela()
        self.lancar(j, "10")
        venda_id = j.venda_id
        j.dialogos.textos = ["ADM", "", "cliente desistiu"]
        j.dialogos.confirmacoes = [True]
        j.btn_cancelar_venda.click()
        v = self.ctx.caixa.obter(venda_id)
        self.assertEqual(v["status"], "cancelada")
        self.assertEqual(v["motivo_cancelamento"], "cliente desistiu")
        self.assertIsNotNone(v["cupom"])
        self.assertIsNone(j.venda_id)

    def test_administrador_cancela_sem_senha(self):
        j = self.janela()
        self.lancar(j, "10")
        venda_id = j.venda_id
        j.dialogos.confirmacoes = [False]
        j.btn_cancelar_venda.click()
        self.assertEqual(self.ctx.caixa.obter(venda_id)["status"], "aberta")
        j.dialogos.confirmacoes = [True]
        j.btn_cancelar_venda.click()
        v = self.ctx.caixa.obter(venda_id)
        self.assertEqual((v["status"], v["motivo_cancelamento"]), ("cancelada", "cancelada no caixa"))

    def test_sair_com_venda_aberta_preserva(self):
        j = self.janela()
        self.lancar(j, "10", "3")
        venda_id = j.venda_id
        j.dialogos.confirmacoes = [False]
        j.close()
        self.assertTrue(j.isVisible())
        j.dialogos.confirmacoes = [True]
        j.close()
        self.assertFalse(j.isVisible())
        self.assertEqual(self.ctx.caixa.obter(venda_id)["status"], "aberta")
        self.assertIsNotNone(self.ctx.turnos.atual())
        nova = self.janela()
        self.assertEqual(nova.venda_id, venda_id)
        self.assertEqual(nova.tabela.rowCount(), 1)
        self.assertEqual(nova.lbl_total.text(), "24,00")

    def test_fechar_durante_gravacao_e_recusado(self):
        j = self.janela()
        j._ocupado = True
        j.close()
        self.assertTrue(j.isVisible())

    def test_mesa_e_comanda(self):
        j = self.janela()
        j.ent_pos.setText("M5")
        j.btn_chamar.click()
        mesa = self.ctx.caixa.obter(j.venda_id)
        self.assertEqual((mesa["modalidade"], mesa["posicao"], mesa["comanda"]), ("mesa", 5, 0))
        self.lancar(j, "10")
        j.ent_pos.setText("12")                         # comanda vazia: é descartada ao sair dela
        j.btn_chamar.click()
        comanda_id = j.venda_id
        self.assertEqual(self.ctx.caixa.obter(comanda_id)["comanda"], 1)
        j.ir_para_balcao()
        self.assertIsNone(j.venda_id)
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (comanda_id,)))
        self.assertEqual([t["chave"] for t in j.cartoes.tiles()], ["0", "M5"])
        self.lancar(j, "20")                             # balcão com itens não deixa chamar mesa
        balcao = j.venda_id
        j.ent_pos.setText("M5")
        j.btn_chamar.click()
        self.assertEqual(j.venda_id, balcao)
        self.assertIn("Conclua", j.dialogos.avisos[-1])
        j.dialogos.confirmacoes = [True]
        j.btn_cancelar_venda.click()
        j.cartoes.escolhida.emit("M5")
        self.assertEqual(j.venda_id, mesa["id"])
        j.btn_receber.click()                            # o valor sugerido já inclui o serviço
        j.btn_fechar_venda.click()
        v = self.ctx.caixa.obter(mesa["id"])
        self.assertEqual(v["status"], "fechada")
        self.assertEqual(v["total_cent"], 880)
        self.assertEqual([t["chave"] for t in j.cartoes.tiles()], ["0"])

    def test_mesa_com_garcom_obrigatorio(self):
        self.banco.cfg_set("controle_garcom", "S")
        j = self.janela()
        j.ent_pos.setText("M3")
        j.btn_chamar.click()
        mesa_id = j.venda_id
        self.lancar(j, "10")
        j.btn_receber.click()
        j.btn_fechar_venda.click()                       # não escolheu garçom: continua aberta
        self.assertEqual(self.ctx.caixa.obter(mesa_id)["status"], "aberta")
        j.dialogos.escolhas = [self.operador_adm()]
        j.btn_fechar_venda.click()
        v = self.ctx.caixa.obter(mesa_id)
        self.assertEqual((v["status"], v["garcom_id"]), ("fechada", self.operador_adm()))

    def test_desistir_da_montagem_nao_abre_venda(self):
        j = self.janela()
        self.banco.executar("UPDATE produtos SET partes = 2, composto = 1 WHERE id = ?", (self.skol,))
        j.dialogos.textos = [None]
        self.lancar(j, "10")
        self.assertEqual(self.contar("vendas"), 0)
        self.assertEqual(self.contar("itens_venda"), 0)

    def test_cupom_em_modo_tela_aparece_sem_bloquear(self):
        self.banco.cfg_set("imprimir_cupom", "1")
        j = self.janela()
        self.lancar(j, "10")
        with patch.object(type(self.ctx.impressao), "deve_mostrar_na_tela", return_value=True):
            j.btn_receber.click()
            j.btn_fechar_venda.click()
        self.assertEqual(len(j.documentos), 1)
        self.assertIn("SKOL", j.documentos[0].texto.toPlainText())


if __name__ == "__main__":
    unittest.main()