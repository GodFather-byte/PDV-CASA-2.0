"""Campos de preparação e consulta de pendências na interface Tk."""
from unittest.mock import patch

from src.ui.config_ui import abrir, mostrar_integracoes
from tests.test_ui import BaseUI


class TesteIntegracoesTk(BaseUI):
    def test_formulario_expoe_preparacao_sem_ativacao(self):
        janela = abrir(self.root, self.ctx, "configuracoes")
        valores = janela._coletar()
        self.assertEqual(valores["integracao_ifood_estado"], "desativado")
        self.assertEqual(valores["integracao_nfce_estado"], "desativado")
        self.assertEqual(valores["nfce_regime_tributario"], "nao_definido")

    def test_pendencias_usam_configuracao_salva_sem_gravar(self):
        with patch("src.ui.config_ui.tema.mensagem") as mensagem, \
                patch.object(self.ctx.config, "salvar_config") as salvar:
            mostrar_integracoes(self.root, self.ctx)
        salvar.assert_not_called()
        self.assertIn("não emite notas fiscais", mensagem.call_args.args[1])
        self.assertIn("Boate está fora", mensagem.call_args.args[1])
