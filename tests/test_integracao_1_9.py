"""Pontos de integração: não fechar sem conferência nem anunciar backup reprovado como sucesso."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from tests.test_qt_caixa import BaseCaixaQt
from tests.test_qt_app import BaseQt


class TesteIntegracaoFechamentoQt(BaseCaixaQt):
    def fechamento(self, valor="100,00"):
        self.abrir_turno()
        janela = self.janela()
        janela.ir_para_fechamento()
        janela.ent_gaveta.setText(valor)
        janela.dialogos.confirmacoes = [True]
        return janela

    def test_cancelar_conferencia_preserva_turno_e_nao_faz_backup(self):
        janela = self.fechamento()
        with patch("src.ui_qt.fechamento.coletar", return_value=None) as conferencia, \
                patch.object(self.ctx.utilitarios, "backup_automatico") as backup:
            janela.fechar_turno()
        conferencia.assert_called_once()
        backup.assert_not_called()
        self.assertIsNotNone(self.ctx.turnos.atual())

    def test_conferencia_e_motivo_chegam_ao_fechamento_e_fita(self):
        janela = self.fechamento("90,00")
        declarados = {r["tipo_id"]: 9000 if r["dinheiro"] else 0
                      for r in self.ctx.turnos.formas_conferencia(
                          self.ctx.turnos.atual()["id"], self.ctx.operador_id)}
        with patch("src.ui_qt.fechamento.coletar", return_value={
                "informados_por_forma": declarados,
                "justificativa": "Falta constatada na contagem física"}), \
                patch.object(self.ctx.utilitarios, "backup_automatico", return_value="backup-falso"), \
                patch.object(janela, "_documento_fechamento") as documento:
            janela.fechar_turno()
        self.assertIsNone(self.ctx.turnos.atual())
        resumo = documento.call_args.args[0]
        fita = self.ctx.impressao.fechamento(resumo)
        self.assertIn("Falta constatada na contagem física", fita)
        self.assertIn("FALTOU R$ 10,00", fita)


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
