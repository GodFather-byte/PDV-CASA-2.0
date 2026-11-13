"""Gerador de vídeos de tutorial: as partes que não dependem de abrir as telas (texto, música, roteiros)."""
import importlib.util
import tempfile
import unittest
import wave
from pathlib import Path

TEM = all(importlib.util.find_spec(m) for m in ("PIL", "numpy"))


@unittest.skipUnless(TEM, "precisa de Pillow e numpy")
class TestVideosTutoriais(unittest.TestCase):
    def setUp(self):
        from tools import videos_tutoriais
        self.v = videos_tutoriais

    def test_roteiros_disponiveis(self):
        self.assertEqual(set(self.v.ROTEIROS), {"produto", "operador", "venda", "fechamento"})
        nomes = [nome for nome, _ in self.v.ROTEIROS.values()]
        self.assertEqual(len(nomes), len(set(nomes)))

    def test_legenda_quebra_sem_passar_da_largura(self):
        fnt = self.v.fonte("SemiBold", 34)
        linhas = self.v.quebrar("Digite quanto o cliente entregou e tecle Enter. Exemplo: 20,00. " * 3, fnt, 600)
        self.assertGreater(len(linhas), 1)
        self.assertTrue(all(fnt.getlength(l) <= 600 for l in linhas if " " in l))

    def test_musica_tem_a_duracao_pedida(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = self.v.musica(Path(pasta) / "m.wav", 3.0, taxa=8000)
            with wave.open(str(arquivo)) as w:
                self.assertEqual(w.getnframes(), 24000)
                self.assertEqual(w.getframerate(), 8000)


if __name__ == "__main__":
    unittest.main()
