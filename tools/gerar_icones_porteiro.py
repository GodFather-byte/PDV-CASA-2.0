"""Ícones da página do porteiro (PWA): PNG de 192 e 512 px, só com a biblioteca padrão.

    python -m tools.gerar_icones_porteiro

Desenho: quadrado azul-noite de cantos arredondados e uma porta clara. Os arquivos vão para
src/porteiro/web/icones/ e o caixa os entrega na rede local. Rode de novo só se mudar o desenho.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

DESTINO = Path(__file__).resolve().parents[1] / "src" / "porteiro" / "web" / "icones"
FUNDO = (11, 18, 32)
PORTA = (248, 250, 252)
MACANETA = (94, 226, 187)


def _png(largura: int, altura: int, pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)

    linhas = b"".join(b"\x00" + bytes(c for px in linha for c in px) for linha in pixels)
    cabecalho = struct.pack(">IIBBBBB", largura, altura, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", cabecalho) + bloco(b"IDAT", zlib.compress(linhas, 9)) + bloco(b"IEND", b"")


def _dentro_arredondado(x: float, y: float, lado: float, raio: float) -> bool:
    cx = min(max(x, raio), lado - raio)
    cy = min(max(y, raio), lado - raio)
    return (x - cx) ** 2 + (y - cy) ** 2 <= raio ** 2


def icone(lado: int, com_margem: bool = False) -> bytes:
    pixels = []
    margem = lado * 0.12 if com_margem else 0
    util = lado - 2 * margem
    for j in range(lado):
        linha = []
        for i in range(lado):
            x, y = i + 0.5, j + 0.5
            if com_margem:
                cor = FUNDO + (255,)
            elif _dentro_arredondado(x, y, lado, lado * 0.22):
                cor = FUNDO + (255,)
            else:
                cor = (0, 0, 0, 0)
            gx, gy = (x - margem) / util, (y - margem) / util
            na_porta = 0.30 <= gx <= 0.70 and 0.18 <= gy <= 0.86
            if na_porta and cor[3]:
                cor = PORTA + (255,)
                if (gx - 0.58) ** 2 + (gy - 0.55) ** 2 <= 0.012:
                    cor = MACANETA + (255,)
            linha.append(cor)
        pixels.append(linha)
    return _png(lado, lado, pixels)


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    for lado in (192, 512):
        (DESTINO / f"icone-{lado}.png").write_bytes(icone(lado))
        (DESTINO / f"icone-maskable-{lado}.png").write_bytes(icone(lado, com_margem=True))
    print(f"Ícones gravados em {DESTINO}")


if __name__ == "__main__":
    main()
