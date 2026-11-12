"""Instalação pendente não pode fechar o caixa repetidamente nem confirmar versão antiga."""
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from src.atualizacao import cliente
from src.core import formatacao as fmt
from src.database.conexao import BancoDados

class TesteRetomada(TestCase):
    def setUp(self):
        self.banco = BancoDados(':memory:')
        self.addCleanup(self.banco.fechar)
        self.banco.cfg_set('api_url', 'https://nuvem.exemplo')
        self.banco.cfg_set(cliente.CHAVE_CONSULTA, fmt.agora())
        self.pendente = {'versao': '99.0.0', 'arquivo': '/pacote.exe'}
        cliente._gravar_estado(self.banco, self.pendente)

    def test_consumir_pendente_antes_de_fechar_impede_repeticao(self):
        chamadas = []
        def instalar(arquivo):
            self.assertEqual(cliente.estado(self.banco), {})
            chamadas.append(arquivo)
        self.assertEqual(cliente.rodada(self.banco, instalar=instalar)['acao'], 'instalar')
        self.assertEqual(cliente.rodada(self.banco, instalar=instalar)['acao'], 'requer_conferencia')
        self.assertEqual(len(chamadas), 1)

    def test_falha_ao_disparar_preserva_pendente_mas_nao_repete(self):
        def instalar(arquivo):
            raise OSError('sem permissão')
        with self.assertRaises(OSError):
            cliente.rodada(self.banco, instalar=instalar)
        self.assertEqual(cliente.estado(self.banco), self.pendente)
        self.assertEqual(cliente.rodada(self.banco, instalar=instalar)['acao'], 'requer_conferencia')

    def test_nao_dispara_instalador_inexistente(self):
        with self.assertRaisesRegex(RuntimeError, 'não encontrado'):
            cliente.disparar_instalacao(Path('/instalador-ausente.exe'))

    def test_versao_errada_nao_cria_comprovante(self):
        with tempfile.TemporaryDirectory() as pasta:
            prova = Path(pasta) / 'confirmacao.txt'
            self.assertEqual(cliente.confirmar_atualizacao('99.0.0', prova), 1)
            self.assertFalse(prova.exists())

    def test_confirma_versao_correta_com_comprovante(self):
        with tempfile.TemporaryDirectory() as pasta:
            banco = BancoDados(Path(pasta) / 'loja.db')
            prova = Path(pasta) / 'confirmacao.txt'
            with patch('src.database.conexao.BancoDados', return_value=banco):
                self.assertEqual(cliente.confirmar_atualizacao(cliente.VERSAO, prova), 0)
            self.assertEqual(prova.read_text(encoding='utf-8').strip(), cliente.VERSAO)
