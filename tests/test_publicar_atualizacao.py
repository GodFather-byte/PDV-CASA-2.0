"""Publicação só termina com sucesso depois de validar e registrar o pacote."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import publicar_atualizacao as publicar
from src.atualizacao.manifesto import conferir
from src.core.ed25519 import chave_publica
from tests.test_atualizacao_automatica import SEMENTE, pacote, PUBLICA

class TestePublicacao(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.arquivo = Path(pasta.name) / 'instalador.exe'
        self.arquivo.write_bytes(b'instalador')
        self.saida = Path(pasta.name) / 'manifesto.json'
        self.args = [str(self.arquivo), '--edicao', 'willrestaurante', '--notas', 'Correção',
                     '--url', 'https://arquivos.exemplo/setup.exe', '--saida', str(self.saida)]
        ambiente = patch.dict(os.environ, {'PDV_ATUALIZACAO_CHAVE': SEMENTE.hex(),
                     'PDV_NUVEM_URL': 'https://nuvem.exemplo', 'PDV_API_TOKEN': 'teste'})
        ambiente.start()
        self.addCleanup(ambiente.stop)
        verifica = patch.object(publicar, 'conferir', side_effect=lambda p: conferir(p, PUBLICA))
        verifica.start()
        self.addCleanup(verifica.stop)

    def test_sem_chave_nao_e_sucesso(self):
        with patch.dict(os.environ, {'PDV_ATUALIZACAO_CHAVE': ''}), patch.object(publicar.urllib.request, 'urlopen') as abrir:
            self.assertEqual(publicar.main(self.args), 1)
            abrir.assert_not_called()

    def test_sem_token_nao_e_sucesso(self):
        with patch.dict(os.environ, {'PDV_API_TOKEN': ''}), patch.object(publicar.urllib.request, 'urlopen') as abrir:
            self.assertEqual(publicar.main(self.args), 1)
            abrir.assert_not_called()

    def test_arquivo_publico_errado_nao_anuncia(self):
        with patch.object(publicar.urllib.request, 'urlopen', return_value=io.BytesIO(b'outro')) as abrir:
            self.assertEqual(publicar.main(self.args), 1)
            self.assertEqual(abrir.call_count, 1)

    def test_confere_download_assina_json_e_publica_restaurante(self):
        with patch.object(publicar.urllib.request, 'urlopen', side_effect=[io.BytesIO(b'instalador'), io.BytesIO(b'{}')]) as abrir:
            self.assertEqual(publicar.main(self.args), 0)
            self.assertEqual(abrir.call_count, 2)
            dados = json.loads(abrir.call_args.args[0].data)
            self.assertTrue(conferir(dados, PUBLICA))
            self.assertEqual(dados['edicao'], 'willrestaurante')
            self.assertEqual(json.loads(self.saida.read_text()), dados)

    def test_minima_nao_invalida_assinatura_da_resposta(self):
        from backend.atualizacao_remota import resposta_publica
        from types import SimpleNamespace
        original = pacote(minima='2.0.0')
        resposta = resposta_publica(SimpleNamespace(**original), '1.0.0')
        self.assertTrue(conferir(resposta['pacote'], PUBLICA))
        self.assertEqual(resposta['pacote']['obrigatoria'], 0)
