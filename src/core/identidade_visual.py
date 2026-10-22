"""Importação compartilhada do logotipo; a impressão existente continua recebendo BMP."""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
import warnings
from pathlib import Path

from src.core.erros import ErroNegocio
from src.database.conexao import RAIZ

LIMITE_BYTES = 5 * 1024 * 1024
LIMITE_PIXELS = 16_000_000
DIMENSOES = (384, 192)
FORMATOS = ("PNG", "JPEG", "BMP")


def _imagem(caminho):
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ErroNegocio("Instale as dependências do PDV para configurar o logotipo (Pillow).") from None
    try:
        with open(caminho, "rb") as arquivo:
            dados = arquivo.read(LIMITE_BYTES + 1)
        if len(dados) > LIMITE_BYTES:
            raise ErroNegocio("O logotipo deve ter no máximo 5 MiB.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(dados), formats=FORMATOS) as imagem:
                if imagem.width * imagem.height > LIMITE_PIXELS:
                    raise ErroNegocio("O logotipo deve ter no máximo 16 milhões de pixels.")
                imagem.load()
                imagem = ImageOps.exif_transpose(imagem)
                imagem.thumbnail(DIMENSOES, Image.Resampling.LANCZOS)
                # Transparência sobre branco evita fundos pretos no cupom térmico.
                rgba = imagem.convert("RGBA")
                fundo = Image.new("RGB", rgba.size, "white")
                fundo.paste(rgba, mask=rgba.getchannel("A"))
                return fundo
    except ErroNegocio:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ErroNegocio("Não foi possível abrir o logotipo. Escolha uma imagem PNG, JPG/JPEG ou BMP válida.") from None


def importar_logotipo(caminho, banco) -> str:
    """Cópia normalizada e imutável junto aos dados, independente do arquivo original."""
    imagem = _imagem(caminho)
    saida = io.BytesIO()
    imagem.save(saida, format="BMP")
    dados = saida.getvalue()
    raiz = Path(banco.caminho).resolve().parent if banco.caminho != ":memory:" else RAIZ
    destino = raiz / "identidade"
    temporario = None
    try:
        destino.mkdir(parents=True, exist_ok=True)
        alvo = destino / (hashlib.sha256(dados).hexdigest() + ".bmp")
        with tempfile.NamedTemporaryFile(dir=destino, suffix=".tmp", delete=False) as arquivo:
            temporario = arquivo.name
            arquivo.write(dados)
        os.replace(temporario, alvo)
        return str(alvo)
    except OSError:
        raise ErroNegocio("Não foi possível guardar o logotipo na pasta de dados. Verifique as permissões.") from None
    finally:
        if temporario and os.path.exists(temporario):
            os.unlink(temporario)


def preview_logotipo(caminho, tamanho=(160, 72)) -> bytes | None:
    """PNG para a interface Qt; arquivo ausente, inválido ou suporte indisponível mantém a identidade textual."""
    if not caminho:
        return None
    try:
        imagem = _imagem(caminho)
        imagem.thumbnail(tamanho)
        saida = io.BytesIO()
        imagem.save(saida, format="PNG")
        return saida.getvalue()
    except ErroNegocio:
        return None
