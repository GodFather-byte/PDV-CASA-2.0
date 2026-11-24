"""Retaguarda: nome e foto pelo código de barras e a foto enviada do celular. A nuvem só consulta a base pública e mostra a
miniatura; o caixa baixa a foto (ou recebe a enviada), passa pelas mesmas regras da foto do caixa e grava."""
import base64
import io
import json
import unittest
from unittest import mock

from src.controllers import foto_produto_controller as fotos
from src.controllers.retaguarda_controller import RetaguardaController
from tests.base import BaseTeste

try:
    from backend import retaguarda as nuvem_retaguarda
    from fastapi import HTTPException
except (ImportError, RuntimeError):
    nuvem_retaguarda = None


def jpeg(cor=(200, 30, 30), lado=600) -> bytes:
    from PIL import Image
    saida = io.BytesIO()
    Image.new("RGB", (lado, lado), cor).save(saida, format="JPEG")
    return saida.getvalue()


class TesteFotoNoCaixa(BaseTeste):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("retaguarda_nuvem", "S")
        self.controle = RetaguardaController(self.banco)
        self.skol = self.novo_produto("SKOL", preco=800, codigo="555", cbarra="7891149103102")

    def aplicar(self, ident, dados):
        return self.controle.aplicar({"id": ident, "tipo": "produto.foto", "dados": dados, "resumo": "t", "autor": "dono"})

    def test_foto_enviada_do_celular_e_gravada_pelo_id(self):
        r = self.aplicar(1, {"produto_id": self.skol, "origem": "arquivo",
                             "imagem_b64": base64.b64encode(jpeg()).decode()})
        self.assertEqual(r["situacao"], "aplicado", r)
        self.assertTrue(fotos.FotoProdutoController(self.banco).tem_foto(self.skol))

    def test_foto_pelo_codigo_de_barras_e_pelo_codigo_do_produto_novo(self):
        preparada = fotos.preparar(jpeg(), "https://images.openfoodfacts.org/x.jpg")
        with mock.patch.object(fotos, "buscar_na_internet", return_value=preparada) as buscar:
            r = self.aplicar(2, {"codigo": "555", "origem": "codigo_barras"})
        self.assertEqual(r["situacao"], "aplicado", r)
        buscar.assert_called_once_with("7891149103102")
        self.assertIn("openfoodfacts", fotos.FotoProdutoController(self.banco).origem(self.skol))

    def test_remover_e_recusas(self):
        self.aplicar(3, {"produto_id": self.skol, "origem": "arquivo", "imagem_b64": base64.b64encode(jpeg()).decode()})
        self.assertEqual(self.aplicar(4, {"produto_id": self.skol, "origem": "remover"})["situacao"], "aplicado")
        self.assertFalse(fotos.FotoProdutoController(self.banco).tem_foto(self.skol))
        self.assertEqual(self.aplicar(5, {"codigo": "999", "origem": "remover"})["situacao"], "recusado")
        self.assertEqual(self.aplicar(6, {"produto_id": self.skol, "origem": "arquivo", "imagem_b64": "@@"})["situacao"],
                         "recusado")
        r = self.aplicar(7, {"produto_id": self.skol, "origem": "arquivo",
                             "imagem_b64": base64.b64encode(b"nao e imagem").decode()})
        self.assertEqual(r["situacao"], "recusado")

    def test_espelho_marca_quem_tem_foto(self):
        dados = self.controle.linhas("produtos")
        self.assertIn("tem_foto", dados["campos"])
        i, ident = dados["campos"].index("tem_foto"), dados["campos"].index("id")
        self.assertFalse(next(l for l in dados["linhas"] if l[ident] == self.skol)[i])
        self.aplicar(8, {"produto_id": self.skol, "origem": "arquivo", "imagem_b64": base64.b64encode(jpeg()).decode()})
        dados = self.controle.linhas("produtos")
        self.assertTrue(next(l for l in dados["linhas"] if l[ident] == self.skol)[i])


@unittest.skipIf(nuvem_retaguarda is None, "fastapi não instalado")
class TesteConsultaNaNuvem(unittest.TestCase):
    def setUp(self):
        nuvem_retaguarda._cache_gtin.clear()

    def baixador(self, produto, imagem=b"\xff\xd8\xff\xe0mini"):
        chamadas = []

        def baixar(url, limite):
            chamadas.append(url)
            if "api/v2/product" in url:
                return json.dumps({"product": produto}).encode()
            return imagem
        return baixar, chamadas

    def test_nome_e_miniatura_da_base_publica(self):
        baixar, chamadas = self.baixador({"product_name": "Skol Pilsen", "quantity": "350 ml",
                                          "image_front_small_url": "https://images.openfoodfacts.org/s.jpg"})
        r = nuvem_retaguarda.consultar_gtin("7891149103102", baixar)
        self.assertEqual(r["nome"], "SKOL PILSEN 350 ML")
        self.assertTrue(r["miniatura"].startswith("data:image/jpeg;base64,"))
        self.assertTrue(r["tem_foto"])
        nuvem_retaguarda.consultar_gtin("7891149103102", baixar)           # 2ª vez vem do cache
        self.assertEqual(len(chamadas), 2)

    def test_foto_de_outro_site_e_ignorada(self):
        baixar, chamadas = self.baixador({"product_name": "X", "image_front_small_url": "https://maldoso.exemplo/a.jpg"})
        r = nuvem_retaguarda.consultar_gtin("78911491", baixar)
        self.assertEqual((r["miniatura"], len(chamadas)), ("", 1))

    def test_codigo_invalido_ou_fora_da_base(self):
        with self.assertRaises(HTTPException) as erro:
            nuvem_retaguarda.consultar_gtin("123", lambda u, l: b"")
        self.assertEqual(erro.exception.status_code, 422)
        with self.assertRaises(HTTPException) as erro:
            nuvem_retaguarda.consultar_gtin("7891149103102", self.baixador({})[0])
        self.assertEqual(erro.exception.status_code, 404)

    def test_base_fora_do_ar(self):
        def falha(url, limite):
            raise OSError("sem rede")
        with self.assertRaises(HTTPException) as erro:
            nuvem_retaguarda.consultar_gtin("7891149103102", falha)
        self.assertEqual(erro.exception.status_code, 502)

    def test_filtro_sem_foto_e_comando_aceito(self):
        self.assertIn("sem_foto", nuvem_retaguarda.FILTROS_PRODUTO)
        self.assertIn("produto.foto", nuvem_retaguarda.TIPOS_COMANDO)
        self.assertTrue(nuvem_retaguarda.FILTROS_PRODUTO["sem_foto"]({"tem_foto": 0}))
        self.assertFalse(nuvem_retaguarda.FILTROS_PRODUTO["sem_foto"]({}))          # caixa antigo: não filtra errado


if __name__ == "__main__":
    unittest.main()
