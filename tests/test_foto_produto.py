"""Foto real do produto: normalização segura, busca pelo código de barras, gravação no banco e cardápio."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.controllers import foto_produto_controller as fotos
from src.controllers.foto_produto_controller import FotoProdutoController
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.sync import cardapio_envio
from tests.base import BaseTeste


def imagem(largura=1200, altura=900, formato="PNG", modo="RGBA", cor=(200, 30, 60, 0)) -> bytes:
    saida = io.BytesIO()
    Image.new(modo, (largura, altura), cor if modo == "RGBA" else cor[:3]).save(saida, format=formato)
    return saida.getvalue()


class Resposta:
    def __init__(self, status=200, corpo=b""):
        self.status_code, self.corpo, self.fechada = status, corpo, False

    def iter_content(self, tamanho):
        for i in range(0, len(self.corpo), tamanho):
            yield self.corpo[i:i + tamanho]

    def close(self):
        self.fechada = True


class HttpFalso:
    def __init__(self, respostas):
        self.respostas, self.pedidos = dict(respostas), []

    def get(self, url, **kw):
        self.pedidos.append((url, kw))
        resposta = self.respostas.get(url, Resposta(404))
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


API = "https://world.openfoodfacts.org/api/v2/product/7891149103102.json?fields=image_front_url,image_url"
FOTO_URL = "https://images.openfoodfacts.org/images/products/789/114/910/3102/front_pt.jpg"


class TestePreparar(unittest.TestCase):
    def test_png_transparente_vira_jpeg_branco_nos_dois_tamanhos(self):
        foto = fotos.preparar(imagem())
        with Image.open(io.BytesIO(foto.imagem)) as grande, Image.open(io.BytesIO(foto.miniatura)) as mini:
            self.assertEqual((grande.format, grande.size), ("JPEG", (480, 360)))
            self.assertEqual((mini.format, mini.size), ("JPEG", (160, 120)))
            self.assertGreater(min(grande.convert("RGB").getpixel((10, 10))), 240)      # transparente -> branco
            self.assertNotIn("exif", grande.info)
        self.assertEqual(foto.origem, "")
        self.assertEqual(len(foto.sha256), 64)

    def test_imagem_pequena_nao_e_ampliada_e_origem_so_https(self):
        foto = fotos.preparar(imagem(100, 50, "JPEG", "RGB"), "http://inseguro.com/a.jpg")
        with Image.open(io.BytesIO(foto.imagem)) as grande:
            self.assertEqual(grande.size, (100, 50))
        self.assertEqual(foto.origem, "")
        self.assertEqual(fotos.preparar(imagem(10, 10), FOTO_URL).origem, FOTO_URL)

    def test_recusa_vazio_lixo_formato_estranho_e_grande_demais(self):
        gif = io.BytesIO()
        Image.new("RGB", (10, 10)).save(gif, format="GIF")
        for dados in (b"", b"nao e imagem", imagem()[:40], gif.getvalue(), b"0" * (fotos.LIMITE_BYTES + 1)):
            with self.assertRaises(ErroNegocio):
                fotos.preparar(dados)

    def test_ler_arquivo(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "skol.png"
            caminho.write_bytes(imagem(50, 50))
            self.assertEqual(fotos.ler_arquivo(caminho), caminho.read_bytes())
            with self.assertRaises(ErroNegocio):
                fotos.ler_arquivo(Path(pasta) / "nao_existe.png")


class TesteBuscaNaInternet(unittest.TestCase):
    def http(self, produto=None, foto=None):
        corpo = json.dumps({"status": 1, "product": produto if produto is not None else {"image_front_url": FOTO_URL}})
        return HttpFalso({API: Resposta(200, corpo.encode()), FOTO_URL: foto or Resposta(200, imagem(800, 800, "JPEG", "RGB"))})

    def test_acha_pelo_codigo_de_barras_e_guarda_a_origem(self):
        http = self.http()
        foto = fotos.buscar_na_internet("789 1149-103102", http)
        self.assertEqual(foto.origem, FOTO_URL)
        self.assertEqual([url for url, _ in http.pedidos], [API, FOTO_URL])
        _, opcoes = http.pedidos[0]
        self.assertFalse(opcoes["allow_redirects"])
        self.assertTrue(opcoes["timeout"])
        self.assertIn("WillPDV/", opcoes["headers"]["User-Agent"])

    def test_sem_codigo_sem_produto_sem_foto_e_host_estranho(self):
        with self.assertRaisesRegex(ErroNegocio, "código de barras"):
            fotos.buscar_na_internet("123", self.http())
        with self.assertRaisesRegex(ErroNegocio, "Não achamos"):
            fotos.buscar_na_internet("7891149103102", HttpFalso({}))
        with self.assertRaisesRegex(ErroNegocio, "Não achamos"):
            fotos.buscar_na_internet("7891149103102", self.http(produto={}))
        for url in ("https://evil.com/x.jpg", "http://images.openfoodfacts.org/x.jpg",
                    "https://openfoodfacts.org.evil.com/x.jpg", "https://u:s@images.openfoodfacts.org/x.jpg"):
            http = self.http(produto={"image_front_url": url})
            with self.assertRaisesRegex(ErroNegocio, "não confiável"):
                fotos.buscar_na_internet("7891149103102", http)
            self.assertEqual(len(http.pedidos), 1)                     # a imagem suspeita nem é baixada

    def test_rede_fora_e_foto_grande_demais_viram_mensagem(self):
        http = HttpFalso({API: ConnectionError("sem rede")})
        with self.assertRaisesRegex(ErroNegocio, "Sem conexão"):
            fotos.buscar_na_internet("7891149103102", http)
        enorme = Resposta(200, b"x" * (fotos.LIMITE_BYTES + 10))
        with self.assertRaisesRegex(ErroNegocio, "grande demais"):
            fotos.buscar_na_internet("7891149103102", self.http(foto=enorme))
        with self.assertRaisesRegex(ErroNegocio, "Não foi possível abrir"):
            fotos.buscar_na_internet("7891149103102", self.http(foto=Resposta(200, b"<html>")))


class TesteGravacao(BaseTeste):
    def setUp(self):
        super().setUp()
        self.fotos = FotoProdutoController(self.banco)
        self.pid = self.novo_produto("SKOL LATA")

    def test_grava_troca_remove_e_apaga_junto_com_o_produto(self):
        self.assertIsNone(self.fotos.imagem(self.pid))
        primeira = fotos.preparar(imagem(300, 300))
        self.fotos.gravar(self.pid, primeira)
        self.assertEqual(self.fotos.imagem(self.pid), primeira.imagem)
        segunda = fotos.preparar(imagem(200, 100, "JPEG", "RGB"), FOTO_URL)
        self.fotos.gravar(self.pid, segunda)
        self.assertEqual((self.fotos.imagem(self.pid), self.fotos.origem(self.pid)), (segunda.imagem, FOTO_URL))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produto_fotos"), 1)
        self.fotos.remover(self.pid)
        self.assertFalse(self.fotos.tem_foto(self.pid))
        self.fotos.gravar(self.pid, primeira)
        self.banco.executar("DELETE FROM produtos WHERE id = ?", (self.pid,))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produto_fotos"), 0)

    def test_produto_inexistente_ou_foto_invalida(self):
        with self.assertRaises(ErroNegocio):
            self.fotos.gravar(9999, fotos.preparar(imagem(10, 10)))
        with self.assertRaises(ErroNegocio):
            self.fotos.gravar(self.pid, b"jpeg cru")
        self.assertIsNone(self.fotos.imagem("x"))

    def test_banco_antigo_ganha_a_tabela_na_migracao(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "antigo.db")
            BancoDados(caminho).fechar()
            con = sqlite3.connect(caminho)
            con.execute("DROP TABLE produto_fotos")
            con.execute("PRAGMA user_version = 36")
            con.commit()
            con.close()
            migrado = BancoDados(caminho)
            try:
                self.assertEqual(migrado.valor("SELECT COUNT(*) FROM produto_fotos"), 0)
                self.assertEqual(migrado.valor("PRAGMA user_version"), 37)
            finally:
                migrado.fechar()


class TesteCardapio(BaseTeste):
    def setUp(self):
        super().setUp()
        self.fotos = FotoProdutoController(self.banco)
        self.da_internet = self.novo_produto("SKOL LATA")
        self.do_arquivo = self.novo_produto("VINHO DA CASA")
        self.sem_foto = self.novo_produto("GELO")
        self.fotos.gravar(self.da_internet, fotos.preparar(imagem(300, 300), FOTO_URL))
        self.fotos.gravar(self.do_arquivo, fotos.preparar(imagem(300, 300)))

    def itens(self):
        return {p["nome"]: p.get("foto") for p in cardapio_envio.coletar(self.banco)["produtos"]}

    def test_internet_vai_pelo_endereco_e_arquivo_pela_miniatura(self):
        itens = self.itens()
        self.assertEqual(itens["SKOL LATA"], FOTO_URL)
        self.assertTrue(itens["VINHO DA CASA"].startswith("data:image/jpeg;base64,"))
        self.assertLessEqual(len(itens["VINHO DA CASA"]), cardapio_envio.FOTO_EMBUTIDA_MAX)
        self.assertIsNone(itens["GELO"])

    def test_orcamento_de_miniaturas_e_a_figura_da_categoria_como_reserva(self):
        self.banco.executar("UPDATE subgrupos SET figura = 'https://exemplo.com/categoria.jpg'")
        antigo = cardapio_envio.FOTOS_EMBUTIDAS_TOTAL
        cardapio_envio.FOTOS_EMBUTIDAS_TOTAL = 10
        try:
            itens = self.itens()
        finally:
            cardapio_envio.FOTOS_EMBUTIDAS_TOTAL = antigo
        self.assertEqual(itens["VINHO DA CASA"], "https://exemplo.com/categoria.jpg")
        self.assertEqual(itens["GELO"], "https://exemplo.com/categoria.jpg")
        self.assertEqual(itens["SKOL LATA"], FOTO_URL)

    def test_trocar_a_foto_muda_o_hash_do_envio(self):
        antes = cardapio_envio._hash(cardapio_envio.coletar(self.banco))
        self.fotos.gravar(self.do_arquivo, fotos.preparar(imagem(300, 300, cor=(0, 0, 255, 255))))
        self.assertNotEqual(antes, cardapio_envio._hash(cardapio_envio.coletar(self.banco)))


try:
    from backend import cardapio as cardapio_nuvem
except ImportError:  # pragma: no cover - sem dependências da nuvem
    cardapio_nuvem = None


@unittest.skipIf(cardapio_nuvem is None, "Dependências da nuvem ausentes")
class TesteCardapioNaNuvem(unittest.TestCase):
    def test_aceita_miniatura_jpeg_e_recusa_o_resto(self):
        valido = "data:image/jpeg;base64," + "QUJD" * 10
        base = {"nome": "VINHO", "preco_cent": 3000}
        self.assertEqual(cardapio_nuvem.produto_limpo({**base, "foto": valido})["foto"], valido)
        for ruim in ("data:image/svg+xml;base64,PHN2Zz4=", "data:text/html;base64,PGh0bWw+",
                     "data:image/jpeg;base64,<script>", "data:image/jpeg;base64," + "A" * 13000,
                     "javascript:alert(1)"):
            self.assertNotIn("foto", cardapio_nuvem.produto_limpo({**base, "foto": ruim}))
        self.assertEqual(cardapio_nuvem.produto_limpo({**base, "foto": FOTO_URL})["foto"], FOTO_URL)
