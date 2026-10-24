"""Pontos de integração: não fechar sem conferência nem anunciar backup reprovado como sucesso."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from tests.test_qt_caixa import BaseCaixaQt
from tests.test_qt_app import BaseQt


class TesteIntegracaoFechamentoQt(BaseCaixaQt):
    def fechamento(self, valor="100,00", *textos):
        self.abrir_turno()
        janela = self.janela()
        janela.dialogos.textos = [valor, *textos]
        janela.dialogos.confirmacoes = [True]
        return janela

    def test_nao_conferir_a_maquininha_preserva_turno_e_nao_faz_backup(self):
        janela = self.fechamento()
        janela.dialogos.maquininha_ok = False
        with patch.object(self.ctx.utilitarios, "backup_automatico") as backup:
            janela.ir_para_fechamento()
        backup.assert_not_called()
        self.assertIsNotNone(self.ctx.turnos.atual())

    def test_diferenca_na_gaveta_pede_o_motivo_e_ele_chega_a_fita(self):
        janela = self.fechamento("90,00", "Falta constatada na contagem física")
        with patch.object(self.ctx.utilitarios, "backup_automatico", return_value="backup-falso"), \
                patch.object(janela, "_documento_fechamento") as documento:
            janela.ir_para_fechamento()
        self.assertIsNone(self.ctx.turnos.atual())
        resumo = documento.call_args.args[0]
        fita = self.ctx.impressao.fechamento(resumo)
        self.assertIn("Falta constatada na contagem física", fita)
        self.assertIn("FALTOU R$ 10,00", fita)
        self.assertIn("FALTA de R$ 10,00", janela.dialogos.perguntas[-1])      # a diferença só aparece depois de declarar

    def test_cancelar_o_motivo_da_diferenca_nao_fecha_o_turno(self):
        janela = self.fechamento("90,00", None)
        with patch.object(self.ctx.utilitarios, "backup_automatico") as backup:
            janela.ir_para_fechamento()
        backup.assert_not_called()
        self.assertIsNotNone(self.ctx.turnos.atual())

    def test_gaveta_certa_fecha_sem_pedir_motivo(self):
        janela = self.fechamento("100,00")
        with patch.object(self.ctx.utilitarios, "backup_automatico", return_value="ok"):
            janela.ir_para_fechamento()
        self.assertIsNone(self.ctx.turnos.atual())
        self.assertEqual(len(janela.dialogos.paineis), 1)
        self.assertEqual(self.banco.valor("SELECT resultado_cent FROM turnos"), 0)


class TesteIntegracaoBackupQt(BaseQt):
    def test_backup_corrompido_nao_exibe_sucesso_na_janela_externa(self):
        from src.ui_qt.app import JanelaBackupExterno
        self.admin()
        janela = self.janela(JanelaBackupExterno(self.ctx))
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "corrompido.db"
            arquivo.write_bytes(b"NAO E SQLITE")
            with patch("src.ui_qt.app.QFileDialog.getOpenFileName", return_value=(str(arquivo), "")), \
                    patch.object(janela, "_senha", return_value="senha-ficticia-para-teste"):
                janela.verificar()
        self.assertIn("REPROVADO", janela.mensagem.text())
        self.assertNotIn("Cópia verificada", janela.mensagem.text())
        nivel, texto = self.ctx.utilitarios.situacao_teste_restauracao()
        self.assertEqual(nivel, "aviso")
        self.assertIn(texto, janela.situacao.text())
