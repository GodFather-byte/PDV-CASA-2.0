"""Troca de turno no modelo clássico (Qt): conferência da maquininha, resumo com sobra/falta e botões do resumo."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from tests.test_qt_caixa import BaseCaixaQt

try:
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QLabel
    from src.ui_qt.fechamento_turno import DialogoMaquininha, PainelFechamento, rotulo_do_resultado
except ImportError:                                   # pragma: no cover - sem PySide6 o painel Qt não roda
    PainelFechamento = None


class TesteFechamentoDoTurnoQt(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.skol = self.novo_produto("SKOL", 800, codigo="10", estoque=True, qt=10)
        self.turno = self.abrir_turno(10000)
        self.vender_em("Dinheiro")
        self.vender_em("Pix")

    def vender_em(self, forma):
        vid = self.ctx.caixa.abrir_balcao()
        self.ctx.caixa.adicionar_item(vid, self.skol, 1)
        self.ctx.caixa.adicionar_pagamento(vid, self.tipo(forma), 800)
        self.ctx.caixa.fechar(vid)

    def fechar(self, valor_gaveta):
        declarados = {r["tipo_id"]: valor_gaveta if r["dinheiro"] else 0
                      for r in self.ctx.turnos.formas_conferencia(self.turno, self.ctx.operador_id)}
        return self.ctx.turnos.fechar(self.turno, self.ctx.operador_id, valor_gaveta, informados_por_forma=declarados,
                                      justificativa="conferido")

    def test_dialogo_da_maquininha_lista_cada_forma_e_o_total_sem_o_dinheiro(self):
        maq = self.ctx.turnos.maquininha(self.turno)
        dlg = DialogoMaquininha(maq, self.ctx.turnos.maquininha_lancamentos(self.turno))
        self.addCleanup(dlg.deleteLater)
        rotulos = [w.text() for w in dlg.findChildren(QLabel)]
        self.assertIn("Pix", rotulos)
        self.assertNotIn("Dinheiro", rotulos)                 # o dinheiro esperado não aparece
        self.assertIn("8,00", rotulos)

    def test_resumo_mostra_sobra_em_verde_e_falta_em_vermelho(self):
        res = self.fechar(10800)                              # fundo 100 + venda em dinheiro 8: confere
        painel = PainelFechamento(self.ctx, res, vias_impressas=2)
        self.addCleanup(painel.deleteLater)
        self.assertIn("CAIXA CONFERIDO", painel.faixa.text())
        self.assertIn("#17805a", painel.faixa.styleSheet())
        self.assertIn("2 vias", painel.lbl_impresso.text())
        self.assertEqual((rotulo_do_resultado(500), rotulo_do_resultado(-500), rotulo_do_resultado(0)),
                         ("SOBRA", "FALTA", "CAIXA CONFERIDO"))

    def test_resumo_com_falta_fica_vermelho(self):
        res = self.fechar(10000)                              # faltam os R$ 8,00 da venda em dinheiro
        painel = PainelFechamento(self.ctx, res)
        self.addCleanup(painel.deleteLater)
        self.assertIn("FALTA", painel.faixa.text())
        self.assertIn("#b83a45", painel.faixa.styleSheet())
        self.assertEqual(painel.lbl_impresso.text(), "")

    def test_botoes_imprimir_conferencia_e_arquivo_texto(self):
        res = self.fechar(10800)
        chamadas = {"emitir": [], "mostrar": [], "avisar": []}
        painel = PainelFechamento(
            self.ctx, res, emitir=lambda *a, **k: chamadas["emitir"].append((a, k)),
            mostrar=lambda *a: chamadas["mostrar"].append(a), avisar=lambda *a: chamadas["avisar"].append(a))
        self.addCleanup(painel.deleteLater)
        painel.btn_imprimir.click()
        self.assertEqual(chamadas["emitir"][0][0][0], "Fechamento de turno")
        self.assertEqual(chamadas["emitir"][0][1], {"tipo": "fechamento"})
        painel.btn_conferencia.click()
        self.assertEqual(chamadas["mostrar"][0][0], "Conferência do turno")
        with tempfile.TemporaryDirectory() as pasta, patch.object(
                type(self.ctx.impressao), "enviar", return_value=os.path.join(pasta, "fechamento.txt")):
            painel.btn_texto.click()
        self.assertIn("Arquivo gerado", chamadas["avisar"][0][1])

    def test_lancamentos_da_maquininha_listam_cada_pagamento_fora_da_gaveta(self):
        lanc = self.ctx.turnos.maquininha_lancamentos(self.turno)
        self.assertEqual([(l["tipo"], l["valor"], l["local"]) for l in lanc], [("Pix", 800, "Balcão")])
        self.assertTrue(lanc[0]["cupom"])

    def test_fecha_so_com_a_gaveta_e_cartoes_conferidos_sem_pedir_cada_forma(self):
        j = self.janela()
        self.vender_em("Cartão Débito")
        j.dialogos.textos = ["108,00"]                        # só o valor da gaveta: 100 de fundo + 8 em dinheiro
        j.dialogos.confirmacoes = [True]
        with patch("src.ui_qt.fechamento.coletar") as coleta, patch(
                "src.controllers.utilitario_controller.UtilitarioController.backup_automatico", return_value="ok"):
            j.ir_para_fechamento()
        coleta.assert_not_called()                            # nada de digitar forma por forma
        self.assertIsNone(self.ctx.turnos.atual())
        res, _ = j.dialogos.paineis[0]
        conf = res["conferencia_fechamento"]
        self.assertTrue(conf["por_forma_informada"])
        self.assertFalse(conf["tem_diferenca"])
        self.assertEqual({l["tipo"]: l["informado_cent"] for l in conf["linhas"] if not l["na_gaveta"]},
                         {"Cartão Débito": 800, "Cartão Crédito": 0, "Pix": 800})
        self.assertEqual(len(j.dialogos.maquininhas[0][1]), 2)    # a tela da maquininha recebeu Pix e Débito

    def test_credito_com_taxa_nao_cria_diferenca_falsa_no_fechamento(self):
        j = self.janela()
        vid = self.ctx.caixa.abrir_balcao()
        self.ctx.caixa.adicionar_item(vid, self.skol, 1)
        tipo = self.tipo("Cartão Crédito")
        self.ctx.caixa.adicionar_pagamento(vid, tipo, 800 + self.ctx.caixa.acrescimo_da_forma(vid, tipo))
        self.ctx.caixa.fechar(vid)
        j.dialogos.textos = ["108,00"]
        j.dialogos.confirmacoes = [True]
        with patch("src.controllers.utilitario_controller.UtilitarioController.backup_automatico", return_value="ok"):
            j.ir_para_fechamento()
        self.assertIsNone(self.ctx.turnos.atual())
        self.assertEqual(j.dialogos.textos, [])               # não pediu motivo: sem diferença
        self.assertFalse(j.dialogos.paineis[0][0]["conferencia_fechamento"]["tem_diferenca"])

    def test_painel_do_resumo_mostra_o_total_a_conferir_na_maquininha(self):
        res = self.fechar(10800)
        painel = PainelFechamento(self.ctx, res)
        self.addCleanup(painel.deleteLater)
        textos = [w.text() for w in painel.findChildren(QLabel)]
        self.assertIn("Pix  (1)", textos)
        self.assertIn("TOTAL  (1)", textos)
        self.assertIn("R$ 8,00", textos)

    def test_resumo_renderiza_nos_dois_modos(self):
        res = self.fechar(10800)
        painel = PainelFechamento(self.ctx, res)
        self.addCleanup(painel.deleteLater)
        painel.show()
        imagem = QPixmap(painel.size())
        painel.render(imagem)
        self.assertFalse(imagem.isNull())

    def test_valor_invalido_da_gaveta_pergunta_de_novo_e_cancelar_preserva_o_turno(self):
        j = self.janela()
        j.dialogos.textos = ["abc", "108,00"]
        self.assertEqual(j._pedir_valor_da_gaveta(), 10800)
        self.assertIn("inválido", j.dialogos.avisos[-1].lower())
        j.dialogos.textos = [None]
        j.btn_trocar_turno.click()
        self.assertIsNotNone(self.ctx.turnos.atual())
        j.dialogos.maquininha_ok = False
        j.btn_trocar_turno.click()                            # desistir na maquininha também não fecha nada
        self.assertIsNotNone(self.ctx.turnos.atual())


if __name__ == "__main__":
    unittest.main()
