"""Importação, persistência e fallback do logotipo, sem dados reais da loja."""
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.controllers.config_controller import ConfigController
from src.controllers.impressao_controller import ImpressaoController
from src.core.erros import ErroNegocio
from src.core.identidade_visual import LIMITE_BYTES, preview_logotipo
from src.database.conexao import BancoDados
from src.hardware.imagem_escpos import ler_bmp
from tests.base import BaseTeste


class TesteIdentidadeVisual(BaseTeste):
    def setUp(self):
        super().setUp()
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.pasta = Path(pasta.name)
        raiz = patch("src.core.identidade_visual.RAIZ", self.pasta)
        raiz.start()
        self.addCleanup(raiz.stop)
        self.config = ConfigController(self.banco)

    def imagem(self, formato="PNG", tamanho=(800, 200), cor="black"):
        caminho = self.pasta / ("origem." + formato.lower())
        Image.new("RGB", tamanho, cor).save(caminho, format=formato)
        return caminho

    def test_importa_formatos_e_reduz_preservando_proporcao(self):
        for formato in ("PNG", "JPEG", "BMP"):
            with self.subTest(formato=formato):
                origem = self.imagem(formato)
                self.config.salvar_loja({"logotipo": origem})
                alvo = Path(self.config.loja()["logotipo"])
                self.assertNotEqual(alvo, origem)
                self.assertEqual(alvo.parent, self.pasta / "identidade")
                self.assertEqual(ler_bmp(str(alvo))[:2], (384, 96))
                origem.unlink()
                self.assertIsNotNone(preview_logotipo(alvo))

    def test_nao_amplia_imagem_pequena_e_limita_altura(self):
        for tamanho, esperado in (((20, 10), (20, 10)), ((200, 800), (48, 192))):
            self.config.salvar_loja({"logotipo": self.imagem(tamanho=tamanho)})
            self.assertEqual(ler_bmp(self.config.loja()["logotipo"])[:2], esperado)

    def test_transparencia_e_removida_sobre_branco(self):
        origem = self.pasta / "transparente.png"
        Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(origem)
        self.config.salvar_loja({"logotipo": origem})
        self.assertEqual(ler_bmp(self.config.loja()["logotipo"])[2][0][0], 255)

    def test_orientacao_exif_e_aplicada(self):
        origem = self.pasta / "orientada.jpg"
        imagem = Image.new("RGB", (100, 50))
        exif = imagem.getexif()
        exif[274] = 6
        imagem.save(origem, exif=exif)
        self.config.salvar_loja({"logotipo": origem})
        self.assertEqual(ler_bmp(self.config.loja()["logotipo"])[:2], (50, 100))

    def test_invalidos_nao_alteram_configuracao_anterior(self):
        self.config.salvar_loja({"logotipo": self.imagem()})
        anterior = self.config.loja()["logotipo"]
        invalido = self.pasta / "invalido.png"
        for dados in (b"lixo", b"", b"a" * (LIMITE_BYTES + 1)):
            invalido.write_bytes(dados)
            with self.assertRaises(ErroNegocio):
                self.config.salvar_loja({"logotipo": invalido, "nome_fantasia": "Nao salvar"})
            self.assertEqual(self.config.loja()["logotipo"], anterior)
            self.assertNotEqual(self.config.nome_loja(), "Nao salvar")
        self.assertEqual(len(list((self.pasta / "identidade").iterdir())), 1)

    def test_formato_nao_suportado_mesmo_renomeado_e_recusado(self):
        origem = self.pasta / "falso.png"
        Image.new("RGB", (10, 10)).save(origem, format="GIF")
        with self.assertRaisesRegex(ErroNegocio, "válida"):
            self.config.salvar_loja({"logotipo": origem})

    def test_imagem_truncada_e_recusada(self):
        origem = self.imagem("JPEG")
        origem.write_bytes(origem.read_bytes()[:100])
        with self.assertRaises(ErroNegocio):
            self.config.salvar_loja({"logotipo": origem})

    def test_limite_de_pixels_antes_da_decodificacao(self):
        origem = self.imagem(tamanho=(100, 100))
        with patch("src.core.identidade_visual.LIMITE_PIXELS", 9999), \
                self.assertRaisesRegex(ErroNegocio, "pixels"):
            self.config.salvar_loja({"logotipo": origem})
        self.assertFalse((self.pasta / "identidade").exists())

    def test_preview_ausente_corrompido_ou_sem_pillow_tem_fallback(self):
        self.assertIsNone(preview_logotipo(None))
        self.assertIsNone(preview_logotipo(self.pasta / "ausente"))
        origem = self.imagem()
        with patch.dict("sys.modules", {"PIL": None}):
            self.assertIsNone(preview_logotipo(origem))
            with self.assertRaisesRegex(ErroNegocio, "Pillow"):
                self.config.salvar_loja({"logotipo": origem})
        origem.write_bytes(b"corrompida")
        self.assertIsNone(preview_logotipo(origem))

    def test_preview_png_limitado(self):
        dados = preview_logotipo(self.imagem())
        with Image.open(io.BytesIO(dados)) as imagem:
            self.assertEqual(imagem.format, "PNG")
            self.assertEqual(imagem.size, (160, 40))

    def test_regravar_mesmo_logo_nao_recopia_e_remover_preserva_original(self):
        origem = self.imagem()
        self.config.salvar_loja({"logotipo": origem})
        salvo = self.config.loja()["logotipo"]
        with patch("src.core.identidade_visual.importar_logotipo") as importar:
            self.config.salvar_loja({"logotipo": salvo, "telefone": "1234"})
            importar.assert_not_called()
        self.config.salvar_loja({"logotipo": ""})
        self.assertFalse(self.config.loja()["logotipo"])
        self.assertTrue(origem.exists())
        self.assertIsNone(ImpressaoController(self.banco)._logotipo("cupom"))

    def test_falha_de_gravacao_preserva_configuracao_e_limpa_temporario(self):
        origem = self.imagem()
        with patch("src.core.identidade_visual.os.replace", side_effect=OSError), \
                self.assertRaisesRegex(ErroNegocio, "permissões"):
            self.config.salvar_loja({"logotipo": origem})
        self.assertFalse(self.config.loja()["logotipo"])
        self.assertEqual(list((self.pasta / "identidade").iterdir()), [])

    def test_banco_em_disco_mantem_logo_apos_reiniciar_sem_original(self):
        banco = BancoDados(str(self.pasta / "dados" / "loja.db"))
        try:
            config = ConfigController(banco)
            origem = self.imagem()
            config.salvar_loja({"logotipo": origem})
            salvo = config.loja()["logotipo"]
        finally:
            banco.fechar()
        origem.unlink()
        banco = BancoDados(str(self.pasta / "dados" / "loja.db"))
        try:
            self.assertEqual(ConfigController(banco).loja()["logotipo"], salvo)
            self.assertEqual(Path(salvo).resolve().parent, (self.pasta / "dados" / "identidade").resolve())
            self.assertIsNotNone(preview_logotipo(salvo))
        finally:
            banco.fechar()

    def test_logo_importado_no_cupom_e_fallback_quando_perdido(self):
        self.config.salvar_loja({"logotipo": self.imagem()})
        self.config.salvar_maquina({"impressora_termica_logotipo": "S"})
        impressao = ImpressaoController(self.banco)
        self.assertIn(b"\x1dv0", impressao._logotipo("cupom"))
        self.assertIsNone(impressao._logotipo("comprovante"))
        Path(self.config.loja()["logotipo"]).unlink()
        self.assertIsNone(impressao._logotipo("cupom"))
        self.config.salvar_loja({"nome_fantasia": "Adega"})
        self.assertEqual(self.config.nome_loja(), "Adega")
