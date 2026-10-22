"""Coleta real Tk/Qt: declaração explícita, motivo e revalidação sem fechar turno."""
from unittest import mock

from src.controllers.acesso_controller import Operador
from src.core.erros import ErroNegocio
from tests.test_ui import BaseUI
from tests.test_qt_caixa import BaseCaixaQt, QApplication


class CenariosColeta:
    def test_campos_vazios_sem_esperado_e_nao_aceita_sem_declarar(self):
        janela = self.dialogo()
        self.assertTrue(all(not self.ler(c) for c in janela.campos.values()))
        self.assertTrue(all(self.ler(l) == "Não revelado" for l in janela.esperados.values()))
        self.assertFalse(janela.conferir())
        self.assertIsNone(janela.resultado)
        self.assertIn("inclusive zero", self.ler(janela.mensagem))
        self.assertEqual(self.ctx.turnos.obter(self.turno)["status"], "aberto")

    def test_coleta_exata_nao_pede_motivo_nem_fecha(self):
        janela = self.dialogo()
        antes = {t: self.banco.valor(f"SELECT COUNT(*) FROM {t}") for t in ("auditoria_eventos", "log_eventos")}
        self.preencher(janela)
        self.assertTrue(janela.conferir())
        self.assertEqual(self.ler(janela.esperados[self.dinheiro]), "R$ 100,00")
        self.assertEqual(self.ler(janela.diferencas[self.dinheiro]), "R$ 0,00")
        with mock.patch.object(self.ctx.turnos, "fechar", side_effect=AssertionError("Coleta não fecha")):
            self.assertTrue(janela.aceitar())
        self.assertEqual(janela.resultado["justificativa"], "")
        self.assertEqual(janela.resultado["informados_por_forma"][self.dinheiro], 10000)
        self.assertEqual(self.ctx.turnos.obter(self.turno)["status"], "aberto")
        self.assertEqual(antes, {t: self.banco.valor(f"SELECT COUNT(*) FROM {t}")
                                for t in ("auditoria_eventos", "log_eventos")})

    def test_gaveta_com_falta_exige_motivo_e_mostra_diferenca(self):
        janela = self.dialogo(9900)
        self.preencher(janela, dinheiro="99,00")
        self.assertTrue(janela.conferir())
        self.assertIn("diferença -R$ 1,00", self.ler(janela.gaveta))
        self.assertFalse(janela.aceitar())
        self.assertIn("justificativa obrigatória", self.ler(janela.mensagem))
        self.escrever(janela.motivo, " \t ")
        self.assertFalse(janela.aceitar())
        self.escrever(janela.motivo, "  Faltou um real na contagem  ")
        self.assertTrue(janela.aceitar())
        self.assertEqual(janela.resultado["justificativa"], "Faltou um real na contagem")
        self.assertEqual(self.ctx.turnos.obter(self.turno)["status"], "aberto")

    def test_diferenca_pix_com_gaveta_exata_exige_motivo(self):
        janela = self.dialogo()
        self.preencher(janela)
        pix = self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Pix'")
        self.escrever(janela.campos[pix], "1,00")
        self.assertTrue(janela.conferir())
        self.assertEqual(self.ler(janela.diferencas[pix]), "R$ 1,00")
        self.assertFalse(janela.aceitar())
        self.escrever(janela.motivo, "Pix informado a mais no extrato")
        self.assertTrue(janela.aceitar())
        self.assertEqual(janela.resultado["informados_por_forma"][pix], 100)

    def test_valores_invalidos_e_zero_omitido_nao_passam(self):
        janela = self.dialogo()
        self.preencher(janela)
        pix = self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Pix'")
        for texto in ("", "R$", "-1,00", "abc", "1e9999"):
            with self.subTest(texto=texto):
                self.escrever(janela.campos[pix], texto)
                self.assertFalse(janela.conferir())
                self.assertIsNone(janela.resultado)
        self.escrever(janela.campos[pix], "0")
        self.assertTrue(janela.conferir())

    def test_soma_gaveta_incoerente_nao_passa(self):
        janela = self.dialogo()
        self.preencher(janela, dinheiro="90,00")
        self.assertFalse(janela.conferir())
        self.assertIn("soma das formas físicas", self.ler(janela.mensagem))

    def test_operador_inativado_antes_aceitar_nao_passa(self):
        janela = self.dialogo()
        self.preencher(janela)
        self.assertTrue(janela.conferir())
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.ctx.operador_id,))
        self.assertFalse(janela.aceitar())
        self.assertIn("operador ativo", self.ler(janela.mensagem))
        self.assertIsNone(janela.resultado)

    def test_troca_de_operador_na_janela_exige_reiniciar(self):
        janela = self.dialogo()
        self.preencher(janela)
        self.assertTrue(janela.conferir())
        self.ctx.operador = None
        self.assertFalse(janela.aceitar())
        self.assertIn("operador mudou", self.ler(janela.mensagem))
        self.assertIsNone(janela.resultado)

    def test_permissao_existente_caixa_nivel_zero_preservada(self):
        self.banco.executar("UPDATE operadores SET nivel = 0 WHERE id = ?", (self.ctx.operador_id,))
        self.ctx.operador = Operador(self.ctx.operador_id, "CAIXA", 0)
        janela = self.dialogo()
        self.preencher(janela)
        self.assertTrue(janela.conferir())
        self.assertTrue(janela.aceitar())
        self.assertIsNotNone(janela.resultado)

    def test_turno_encerrado_por_outro_fluxo_nao_aceita_coleta(self):
        janela = self.dialogo()
        self.preencher(janela)
        self.assertTrue(janela.conferir())
        self.ctx.turnos.fechar(self.turno, self.ctx.operador_id, 10000)
        self.assertFalse(janela.aceitar())
        self.assertIn("já foi fechado", self.ler(janela.mensagem))

    def test_movimento_entre_previa_e_aceite_exige_revisao(self):
        janela = self.dialogo()
        self.preencher(janela)
        self.assertTrue(janela.conferir())
        self.ctx.turnos.movimentar(self.turno, self.ctx.operador_id, "saida", 100, "Gelo")
        self.escrever(janela.motivo, "Contagem feita antes da sangria")
        self.assertFalse(janela.aceitar())
        self.assertIn("mudou", self.ler(janela.mensagem))
        self.assertIsNone(janela.resultado)
        self.assertTrue(janela.aceitar())
        self.assertEqual(janela.resultado["justificativa"], "Contagem feita antes da sangria")

    def test_editar_forma_apos_previa_exige_revisar_nova_diferenca(self):
        janela = self.dialogo()
        self.preencher(janela)
        self.assertTrue(janela.conferir())
        pix = self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Pix'")
        self.escrever(janela.campos[pix], "2,00")
        self.assertFalse(janela.aceitar())
        self.assertEqual(self.ler(janela.diferencas[pix]), "R$ 2,00")
        self.assertFalse(janela.aceitar())
        self.escrever(janela.motivo, "Valor visto no extrato")
        self.assertTrue(janela.aceitar())

    def test_operador_ausente_na_abertura_e_rejeitado(self):
        self.ctx.operador = None
        with self.assertRaises(ErroNegocio):
            self.dialogo()

    def preencher(self, janela, dinheiro="100,00"):
        for chave, campo in janela.campos.items():
            self.escrever(campo, dinheiro if chave == self.dinheiro else "0,00")


class TesteColetaTk(CenariosColeta, BaseUI):
    def setUp(self):
        super().setUp()
        self.turno = self.abrir_turno()
        self.dinheiro = self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Dinheiro'")

    def dialogo(self, valor=10000):
        from src.ui.fechamento_ui import DialogoFechamento
        janela = DialogoFechamento(self.root, self.ctx, self.turno, valor)
        self.addCleanup(lambda: janela.destroy() if janela.winfo_exists() else None)
        return janela

    @staticmethod
    def ler(campo):
        return campo.get() if hasattr(campo, "get") else campo.cget("text")

    @staticmethod
    def escrever(campo, texto):
        campo.delete(0, "end")
        campo.insert(0, texto)

    def test_coletar_cancelamento_retorna_none(self):
        from src.ui.fechamento_ui import coletar
        self.robo.quando("DialogoFechamento", lambda j: j.destroy())
        self.assertIsNone(coletar(self.root, self.ctx, self.turno, 10000))
        self.assertEqual(self.ctx.turnos.obter(self.turno)["status"], "aberto")

    def test_coletar_retorna_mapa_e_justificativa(self):
        from src.ui.fechamento_ui import coletar
        def preencher_e_aceitar(j):
            self.preencher(j)
            j.conferir()
            j.aceitar()
        self.robo.quando("DialogoFechamento", preencher_e_aceitar)
        resultado = coletar(self.root, self.ctx, self.turno, 10000)
        self.assertEqual(resultado["informados_por_forma"][self.dinheiro], 10000)
        self.assertEqual(resultado["justificativa"], "")


class TesteColetaQt(CenariosColeta, BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.turno = self.abrir_turno()
        self.dinheiro = self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Dinheiro'")

    def dialogo(self, valor=10000):
        from src.ui_qt.fechamento import DialogoFechamento
        janela = DialogoFechamento(self.ctx, self.turno, valor)
        self.addCleanup(janela.deleteLater)
        return janela

    @staticmethod
    def ler(campo):
        return campo.text()

    @staticmethod
    def escrever(campo, texto):
        campo.setText(texto)

    def test_coletar_cancelamento_retorna_none(self):
        from PySide6.QtCore import QTimer
        from src.ui_qt.fechamento import coletar
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
        self.assertIsNone(coletar(self.ctx, self.turno, 10000))
        self.assertEqual(self.ctx.turnos.obter(self.turno)["status"], "aberto")

    def test_coletar_retorna_mapa_e_justificativa(self):
        from PySide6.QtCore import QTimer
        from src.ui_qt.fechamento import coletar
        def preencher_e_aceitar():
            j = QApplication.activeModalWidget()
            self.preencher(j)
            j.conferir()
            j.aceitar()
        QTimer.singleShot(0, preencher_e_aceitar)
        resultado = coletar(self.ctx, self.turno, 10000)
        self.assertEqual(resultado["informados_por_forma"][self.dinheiro], 10000)
        self.assertEqual(resultado["justificativa"], "")
