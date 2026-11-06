"""Foto real do produto: escolhida de um arquivo ou buscada na internet pelo código de barras.

A foto fica no banco (tabela `produto_fotos`), então entra no backup e acompanha a troca de computador. Toda imagem,
venha de onde vier, é tratada como dado não confiável: tamanho e pixels limitados, aberta só como PNG/JPEG/BMP/WEBP e
regravada como JPEG (sem metadados). A busca na internet usa a base pública Open Food Facts (fotos enviadas por
voluntários, licença CC BY-SA): nem todo produto brasileiro tem foto lá, e a pessoa confere antes de salvar.
"""
from __future__ import annotations

import hashlib
import io
import re
import warnings
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

LIMITE_BYTES = 8 * 1024 * 1024          # foto de celular cabe; mais que isso é engano ou arquivo estranho
LIMITE_PIXELS = 40_000_000
TAMANHO_IMAGEM = (480, 480)             # caixa e cadastro
TAMANHO_MINIATURA = (160, 160)          # cardápio online (vai embutida no envio)
FORMATOS = ("PNG", "JPEG", "BMP", "WEBP")
GTIN = re.compile(r"\d{8,14}")
URL_BUSCA = "https://world.openfoodfacts.org/api/v2/product/{gtin}.json?fields=image_front_url,image_url"
HOSTS_FOTO = ("openfoodfacts.org",)    # a foto só é baixada de lá (e de subdomínios, como images.openfoodfacts.org)
TEMPO_LIMITE = (4, 8)
ORIGEM_MAX = 300


@dataclass(frozen=True)
class FotoPreparada:
    imagem: bytes        # JPEG até 480 px
    miniatura: bytes     # JPEG até 160 px
    origem: str          # https de onde veio, ou vazio (arquivo)
    sha256: str


def _pillow():
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ErroNegocio("Instale as dependências do PDV para usar fotos de produtos (Pillow).") from None
    return Image, ImageOps


def _jpeg(imagem, tamanho, qualidade) -> bytes:
    Image, _ = _pillow()
    copia = imagem.copy()
    copia.thumbnail(tamanho, Image.Resampling.LANCZOS)
    saida = io.BytesIO()
    copia.save(saida, format="JPEG", quality=qualidade, optimize=True)
    return saida.getvalue()


def preparar(dados: bytes, origem: str = "") -> FotoPreparada:
    """Valida e normaliza a imagem. Não grava nada: a tela mostra a prévia e só salva se a pessoa confirmar."""
    if not isinstance(dados, (bytes, bytearray)) or not dados:
        raise ErroNegocio("A foto está vazia.")
    if len(dados) > LIMITE_BYTES:
        raise ErroNegocio("A foto deve ter no máximo 8 MB.")
    origem = origem.strip() if isinstance(origem, str) else ""
    if origem and (len(origem) > ORIGEM_MAX or not origem.lower().startswith("https://")):
        origem = ""
    Image, ImageOps = _pillow()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(bytes(dados)), formats=FORMATOS) as bruta:
                if bruta.width * bruta.height > LIMITE_PIXELS:
                    raise ErroNegocio("A foto é grande demais (mais de 40 milhões de pixels).")
                bruta.load()
                imagem = ImageOps.exif_transpose(bruta)
                rgba = imagem.convert("RGBA")
                fundo = Image.new("RGB", rgba.size, "white")       # transparência vira branco, não preto
                fundo.paste(rgba, mask=rgba.getchannel("A"))
    except ErroNegocio:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ErroNegocio("Não foi possível abrir a foto. Use uma imagem JPG, PNG, BMP ou WEBP válida.") from None
    imagem_jpeg = _jpeg(fundo, TAMANHO_IMAGEM, 85)
    return FotoPreparada(imagem=imagem_jpeg, miniatura=_jpeg(fundo, TAMANHO_MINIATURA, 60), origem=origem,
                         sha256=hashlib.sha256(imagem_jpeg).hexdigest())


def ler_arquivo(caminho) -> bytes:
    try:
        with open(caminho, "rb") as arquivo:
            dados = arquivo.read(LIMITE_BYTES + 1)
    except OSError:
        raise ErroNegocio("Não foi possível ler o arquivo da foto.") from None
    if len(dados) > LIMITE_BYTES:
        raise ErroNegocio("A foto deve ter no máximo 8 MB.")
    return dados


def _host_permitido(url: str) -> bool:
    try:
        partes = urlsplit(url)
    except ValueError:
        return False
    host = (partes.hostname or "").lower()
    return (partes.scheme == "https" and not partes.username and not partes.password
            and any(host == h or host.endswith("." + h) for h in HOSTS_FOTO))


def _baixar(http, url: str, limite: int) -> bytes:
    from src.versao import VERSAO
    resposta = http.get(url, timeout=TEMPO_LIMITE, stream=True, allow_redirects=False,
                        headers={"User-Agent": f"WillPDV/{VERSAO} (ponto de venda; foto de produto)"})
    try:
        if resposta.status_code != 200:
            return b""
        partes, total = [], 0
        for bloco in resposta.iter_content(64 * 1024):
            total += len(bloco)
            if total > limite:
                raise ErroNegocio("A foto encontrada é grande demais.")
            partes.append(bloco)
        return b"".join(partes)
    finally:
        fechar = getattr(resposta, "close", None)
        if fechar:
            fechar()


def buscar_na_internet(cbarra: str, http=None) -> FotoPreparada:
    """Procura a foto pelo código de barras (EAN/GTIN) na base pública Open Food Facts e devolve a prévia.
    Nada é gravado aqui. Sem internet, sem código ou sem foto na base: ErroNegocio com o que fazer."""
    gtin = re.sub(r"\D", "", cbarra or "")
    if not GTIN.fullmatch(gtin):
        raise ErroNegocio("Preencha o código de barras do produto (8 a 14 números) para buscar a foto.")
    if http is None:
        try:
            import requests as http
        except ImportError:
            raise ErroNegocio("Instale as dependências do PDV para buscar fotos na internet.") from None
    import json
    try:
        bruto = _baixar(http, URL_BUSCA.format(gtin=gtin), 512 * 1024)
        if not bruto:
            raise ErroNegocio("Não achamos foto para este código de barras. Escolha um arquivo do computador.")
        try:
            dados = json.loads(bruto.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ErroNegocio("A base de fotos respondeu algo inesperado. Tente de novo mais tarde.") from None
        produto = dados.get("product") if isinstance(dados, dict) else None
        url = ""
        if isinstance(produto, dict):
            url = next((u for u in (produto.get("image_front_url"), produto.get("image_url"))
                        if isinstance(u, str) and u.strip()), "").strip()
        if not url:
            raise ErroNegocio("Não achamos foto para este código de barras. Escolha um arquivo do computador.")
        if not _host_permitido(url):
            raise ErroNegocio("A foto indicada está num endereço não confiável e foi ignorada.")
        imagem = _baixar(http, url, LIMITE_BYTES)
        if not imagem:
            raise ErroNegocio("Não foi possível baixar a foto encontrada. Tente de novo ou escolha um arquivo.")
    except ErroNegocio:
        raise
    except Exception as erro:  # noqa: BLE001 - rede (requests.RequestException, timeout, DNS): mensagem para a pessoa
        nome = type(erro).__name__
        raise ErroNegocio("Sem conexão com a base de fotos agora. Confira a internet ou escolha um arquivo."
                          + ("" if nome in ("ConnectionError", "Timeout", "ConnectTimeout", "ReadTimeout")
                             else f" ({nome})")) from None
    return preparar(imagem, url)


class FotoProdutoController:
    def __init__(self, banco):
        self.banco = banco

    def _existe(self, produto_id: int) -> None:
        if type(produto_id) is not int or self.banco.um("SELECT 1 FROM produtos WHERE id = ?", (produto_id,)) is None:
            raise ErroNegocio("Produto não encontrado.")

    def gravar(self, produto_id: int, foto: FotoPreparada) -> None:
        self._existe(produto_id)
        if not isinstance(foto, FotoPreparada):
            raise ErroNegocio("Foto inválida.")
        with self.banco.transacao():
            self.banco.executar(
                """INSERT INTO produto_fotos(produto_id, imagem, miniatura, origem, sha256, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(produto_id) DO UPDATE SET imagem = excluded.imagem, miniatura = excluded.miniatura,
                       origem = excluded.origem, sha256 = excluded.sha256, atualizado_em = excluded.atualizado_em""",
                (produto_id, foto.imagem, foto.miniatura, foto.origem, foto.sha256, fmt.agora()))

    def remover(self, produto_id: int) -> None:
        with self.banco.transacao():
            self.banco.executar("DELETE FROM produto_fotos WHERE produto_id = ?", (produto_id,))

    def imagem(self, produto_id) -> bytes | None:
        """JPEG da foto (até 480 px) ou None. Nunca levanta: foto é enfeite e não pode travar a venda."""
        try:
            valor = self.banco.valor("SELECT imagem FROM produto_fotos WHERE produto_id = ?", (produto_id,))
        except Exception:  # noqa: BLE001
            return None
        return bytes(valor) if valor else None

    def tem_foto(self, produto_id) -> bool:
        return bool(self.banco.valor("SELECT 1 FROM produto_fotos WHERE produto_id = ?", (produto_id,), 0))

    def sem_foto_com_codigo(self, limite: int = 500) -> list[dict]:
        """Produtos ativos à venda, sem foto e com código de barras de 8 a 14 números: candidatos à busca em lote."""
        saida = []
        for r in self.banco.todos(
                """SELECT p.id, p.nome, p.cbarra FROM produtos p
                   WHERE p.ativo = 1 AND p.venda = 1 AND COALESCE(p.cbarra, '') <> ''
                     AND NOT EXISTS (SELECT 1 FROM produto_fotos f WHERE f.produto_id = p.id)
                   ORDER BY p.nome"""):
            gtin = re.sub(r"\D", "", r["cbarra"] or "")
            if GTIN.fullmatch(gtin):
                saida.append({"id": r["id"], "nome": r["nome"], "cbarra": gtin})
            if len(saida) >= limite:
                break
        return saida

    def origem(self, produto_id) -> str:
        return self.banco.valor("SELECT origem FROM produto_fotos WHERE produto_id = ?", (produto_id,), "") or ""
