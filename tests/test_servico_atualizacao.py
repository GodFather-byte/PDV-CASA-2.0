"""Atualização continua ativa com envio de vendas desligado e evita disparos concorrentes."""
import tempfile
from pathlib import Path
from threading import Event
from unittest import TestCase
from unittest.mock import patch
from src.database.conexao import BancoDados
from src.core.instancia import InstanciaUnica
from src.atualizacao.cliente import rodada
from src.atualizacao.servico import ServicoAtualizacao

class TesteServico(TestCase):
    def test_verifica_com_sync_quase_tempo_real_desligado(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = str(Path(pasta) / 'loja.db')
            banco = BancoDados(caminho)
            banco.cfg_set('sync_quase_tempo_real', 'N')
            banco.fechar()
            evento = Event()
            def verificar(banco, **kwargs):
                self.assertFalse(banco.cfg_bool('sync_quase_tempo_real'))
                evento.set()
            with patch('src.atualizacao.servico.rodada', side_effect=verificar):
                servico = ServicoAtualizacao(caminho)
                try:
                    servico.iniciar()
                    self.assertTrue(evento.wait(3))
                finally:
                    servico.parar()
                self.assertFalse(servico.ativo)

    def test_atualizacao_em_andamento_nao_consulta_nem_dispara_outra(self):
        with tempfile.TemporaryDirectory() as pasta:
            banco = BancoDados(str(Path(pasta) / 'loja.db'))
            trava = InstanciaUnica(banco.caminho + '.atualizacao')
            self.assertTrue(trava.adquirir())
            try:
                with patch('requests.get') as obter:
                    self.assertEqual(rodada(banco)['acao'], 'em_andamento')
                    obter.assert_not_called()
            finally:
                trava.liberar()
                banco.fechar()
