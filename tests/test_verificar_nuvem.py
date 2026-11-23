"""Uma resposta de saúde ou uma versão antiga não comprovam publicação do commit novo."""
import io
import unittest
from tools.verificar_nuvem import aguardar, relato


class TesteVerificarNuvem(unittest.TestCase):
    def test_so_confirma_commit_esperado_apos_servico_acordar(self):
        hora = [0]
        respostas = [b'{"status":"ok"}', b'{"commit":"' + b'a' * 40 + b'"}']
        def abrir(pedido, timeout):
            self.assertEqual(pedido.full_url, "https://nuvem.exemplo/v1/versao")
            return io.BytesIO(respostas.pop(0))
        self.assertTrue(aguardar("https://nuvem.exemplo", "a" * 40, timeout=10, intervalo=2, abrir=abrir,
                         dormir=lambda t: hora.__setitem__(0, hora[0] + t), relogio=lambda: hora[0]))

    def test_versao_antiga_ou_falha_de_rede_expiram_sem_confirmar(self):
        for falha in (False, True):
            hora = [0]
            def abrir(*args, **kwargs):
                if falha:
                    raise OSError("offline")
                return io.BytesIO(b'{"commit":"' + b'b' * 40 + b'"}')
            self.assertFalse(aguardar("https://nuvem.exemplo", "a" * 40, timeout=5, intervalo=2, abrir=abrir,
                             dormir=lambda t: hora.__setitem__(0, hora[0] + t), relogio=lambda: hora[0]))
            self.assertEqual(hora[0], 5)

    def test_recusa_credenciais_na_url_e_commit_invalido(self):
        for url, sha in (("http://nuvem.exemplo", "a" * 40), ("https://segredo@nuvem.exemplo", "a" * 40),
                         ("https://nuvem.exemplo", "main")):
            with self.assertRaises(ValueError):
                aguardar(url, sha)

    def test_guarda_o_commit_que_a_nuvem_serviu_para_explicar_a_falha(self):
        hora = [0]
        respostas = [b'{"status":"ok"}', b'{"commit":"' + b'b' * 40 + b'"}', b'{"commit":"<script>"}']
        def abrir(*args, **kwargs):
            return io.BytesIO(respostas.pop(0) if len(respostas) > 1 else respostas[0])
        vistos = []
        self.assertFalse(aguardar("https://nuvem.exemplo", "a" * 40, timeout=20, intervalo=2, abrir=abrir, vistos=vistos,
                         dormir=lambda t: hora.__setitem__(0, hora[0] + t), relogio=lambda: hora[0]))
        self.assertEqual(vistos, ["b" * 40])                # nem resposta sem commit nem texto estranho entram

    def test_relato_diz_o_commit_servido_e_onde_conferir(self):
        self.assertIn("confirmada: a nuvem serve o commit esperado", relato(True, "a" * 40, []))
        parado = relato(False, "a" * 40, ["b" * 40])
        self.assertIn("continua servindo o commit bbbbbbb", parado)
        self.assertIn("esperado é aaaaaaa", parado)
        self.assertIn("repositório", parado)
        self.assertIn("não respondeu", relato(False, "a" * 40, []))
