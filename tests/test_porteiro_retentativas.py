"""Regressões: API do porteiro desatualizada não deve causar spam de envios."""
import unittest
from unittest import mock

from src.porteiro import nuvem_envio as envio


class TesteFalhaRotaPorteiro(unittest.TestCase):
    def setUp(self):
        envio.zerar_envio()
        self.addCleanup(envio.zerar_envio)

    def test_http_404_aponta_necessidade_de_deploy(self):
        banco = mock.Mock()
        banco.cfg.side_effect = lambda chave: {"api_url": "https://exemplo.invalid/v1/sincronizar",
                                                "api_token": "token-teste"}.get(chave, "")
        http = mock.Mock()
        http.post.return_value.status_code = 404
        with self.assertRaisesRegex(RuntimeError, "confira o deploy"):
            envio._post(banco, {}, http)
        self.assertEqual(http.post.call_count, 1)

    def test_404_espera_uma_hora_sem_perder_retrato(self):
        banco = mock.Mock()
        banco.cfg_bool.return_value = False
        corpo = {"posicoes": [], "pin_hash": "hash", "url_lan": "", "posicao_padrao": "comanda"}
        with mock.patch.object(envio, "ligado", return_value=True), \
             mock.patch.object(envio, "montar", return_value=corpo), \
             mock.patch.object(envio, "_post", side_effect=[RuntimeError("Nuvem do porteiro: HTTP 404."), None]) as enviar:
            with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
                envio.enviar_se_preciso(banco, relogio=lambda: 100.0)
            self.assertTrue(envio._estado["rota_ausente"])
            self.assertEqual(envio.enviar_se_preciso(banco, relogio=lambda: 200.0), {"enviado": False})
            self.assertEqual(enviar.call_count, 1)
            self.assertTrue(envio.enviar_se_preciso(banco, relogio=lambda: 3701.0)["enviado"])
            self.assertEqual(enviar.call_count, 2)
            self.assertFalse(envio._estado["rota_ausente"])
