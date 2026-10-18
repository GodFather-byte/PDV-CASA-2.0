"""Logotipo da loja no cupom térmico: lê um BMP e gera o raster ESC/POS (comando GS v 0).

O manual pede logotipo em bitmap de 180x121 (256 cores). Para não depender do Pillow, este módulo
lê BMP sem compressão de 1, 4, 8, 24 e 32 bits em Python puro, converte para preto e branco por
limiar de luminância e reduz a imagem se ela for mais larga que a impressora (384 pontos em 58 mm,
576 pontos em 80 mm).
"""
from __future__ import annotations

import os
import struct
from functools import lru_cache

from src.hardware.impressora_termica import ALINHAR_CENTRO, ALINHAR_ESQ, ErroImpressao

PONTOS_POR_COLUNA = 12          # fonte A das térmicas ESC/POS: 12 pontos por coluna (48 col = 576 pontos)
LINHAS_POR_BLOCO = 200          # algumas impressoras limitam a altura de um único GS v 0


def ler_bmp(caminho: str) -> tuple[int, int, list[list[int]]]:
    """Devolve (largura, altura, linhas) com cada pixel como luminância 0..255 (0 = preto), de cima para baixo."""
    try:
        with open(caminho, "rb") as f:
            dados = f.read()
    except OSError as e:
        raise ErroImpressao(f"Não foi possível abrir o logotipo '{caminho}' ({e}).") from e
    if len(dados) < 54 or dados[:2] != b"BM":
        raise ErroImpressao("O logotipo não é um arquivo BMP válido (salve a imagem como Bitmap).")
    offset = struct.unpack_from("<I", dados, 10)[0]
    tam_cab = struct.unpack_from("<I", dados, 14)[0]
    if tam_cab < 40:
        raise ErroImpressao("Formato de BMP antigo não suportado. Salve o logotipo como Bitmap de 24 bits ou 256 cores.")
    largura, altura, _planos, bpp, compressao = struct.unpack_from("<iiHHI", dados, 18)
    n_cores = struct.unpack_from("<I", dados, 46)[0]
    de_cima_para_baixo = altura < 0
    altura = abs(altura)
    if largura <= 0 or altura <= 0 or largura > 4000 or altura > 4000:
        raise ErroImpressao("Dimensões do logotipo inválidas.")
    if bpp not in (1, 4, 8, 24, 32):
        raise ErroImpressao(f"BMP de {bpp} bits não suportado. Use 24 bits ou 256 cores.")
    if compressao not in (0, 3) or (compressao == 3 and bpp != 32):
        raise ErroImpressao("BMP compactado não suportado. Salve sem compressão.")

    paleta: list[int] = []
    if bpp <= 8:
        pos = 14 + tam_cab
        total = n_cores or (1 << bpp)
        for i in range(total):
            if pos + 4 * i + 4 > len(dados):
                break
            b, g, r, _ = dados[pos + 4 * i: pos + 4 * i + 4]
            paleta.append((299 * r + 587 * g + 114 * b) // 1000)
        paleta += [0] * ((1 << bpp) - len(paleta))

    tam_linha = ((largura * bpp + 31) // 32) * 4
    if offset + tam_linha * altura > len(dados):
        raise ErroImpressao("O arquivo BMP está incompleto ou corrompido.")
    linhas = []
    for y in range(altura):
        origem = y if de_cima_para_baixo else altura - 1 - y
        base = offset + origem * tam_linha
        linha = dados[base: base + tam_linha]
        pix: list[int] = []
        if bpp == 24:
            for x in range(largura):
                b, g, r = linha[3 * x], linha[3 * x + 1], linha[3 * x + 2]
                pix.append((299 * r + 587 * g + 114 * b) // 1000)
        elif bpp == 32:
            for x in range(largura):
                b, g, r = linha[4 * x], linha[4 * x + 1], linha[4 * x + 2]
                pix.append((299 * r + 587 * g + 114 * b) // 1000)
        elif bpp == 8:
            pix = [paleta[linha[x]] for x in range(largura)]
        elif bpp == 4:
            for x in range(largura):
                byte = linha[x // 2]
                pix.append(paleta[(byte >> 4) if x % 2 == 0 else (byte & 0x0F)])
        else:  # 1 bit
            for x in range(largura):
                pix.append(paleta[(linha[x // 8] >> (7 - x % 8)) & 1])
        linhas.append(pix)
    return largura, altura, linhas


def _reduzir(linhas: list[list[int]], largura: int, altura: int, max_largura: int) -> tuple[int, int, list[list[int]]]:
    """Vizinho mais próximo, mantendo a proporção. Só reduz; nunca amplia."""
    if largura <= max_largura:
        return largura, altura, linhas
    nova_l = max_largura
    nova_a = max(1, round(altura * max_largura / largura))
    saida = []
    for y in range(nova_a):
        fonte = linhas[min(altura - 1, y * altura // nova_a)]
        saida.append([fonte[min(largura - 1, x * largura // nova_l)] for x in range(nova_l)])
    return nova_l, nova_a, saida


def para_raster(largura: int, altura: int, linhas: list[list[int]], max_largura: int = 576, limiar: int = 128) -> bytes:
    """Bytes ESC/POS (GS v 0) que imprimem a imagem em preto e branco. Bit 1 = ponto preto."""
    largura, altura, linhas = _reduzir(linhas, largura, altura, max_largura)
    bytes_linha = (largura + 7) // 8
    saida = bytearray()
    for inicio in range(0, altura, LINHAS_POR_BLOCO):
        bloco = linhas[inicio: inicio + LINHAS_POR_BLOCO]
        corpo = bytearray()
        for pix in bloco:
            for bx in range(bytes_linha):
                b = 0
                for bit in range(8):
                    x = bx * 8 + bit
                    if x < largura and pix[x] < limiar:
                        b |= 0x80 >> bit
                corpo.append(b)
        saida += b"\x1dv0\x00" + struct.pack("<HH", bytes_linha, len(bloco)) + bytes(corpo)
    return bytes(saida)


@lru_cache(maxsize=8)
def _carregar(caminho: str, mtime: float, max_largura: int) -> bytes:
    largura, altura, linhas = ler_bmp(caminho)
    return ALINHAR_CENTRO + para_raster(largura, altura, linhas, max_largura) + b"\n" + ALINHAR_ESQ


def logotipo_escpos(caminho: str, colunas: int = 48) -> bytes:
    """Logotipo centralizado pronto para ir no começo do cupom. O resultado fica em cache enquanto
    o arquivo não mudar. Levanta ErroImpressao se o arquivo não existir ou não for um BMP suportado."""
    caminho = (caminho or "").strip()
    if not caminho:
        raise ErroImpressao("Nenhum logotipo informado (Configurações > Loja).")
    try:
        mtime = os.path.getmtime(caminho)
    except OSError as e:
        raise ErroImpressao(f"Logotipo não encontrado: '{caminho}' ({e}).") from e
    return _carregar(caminho, mtime, max(32, int(colunas)) * PONTOS_POR_COLUNA)
