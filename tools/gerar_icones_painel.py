"""Ícones do painel do dono (PWA): PNG de 192 e 512 px gerados só com a biblioteca padrão (sem Pillow).

    python -m tools.gerar_icones_painel

Desenho: quadrado verde-escuro de cantos arredondados, uma garrafa clara ao centro e o rótulo em verde. Os arquivos vão para
backend/painel_web/icones/ e são servidos pela API junto com o app; só precisa rodar de novo se mudar o desenho.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

DESTINO = Path(__file__).resolve().parents[1] / "backend" / "painel_web" / "icones"
FUNDO = (20, 83, 45)          # verde-escuro
GARRAFA = (236, 253, 245)     # quase branco
ROTULO = (74, 222, 128)       # verde-claro


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
    """`com_margem` gera o ícone "maskable" (o Android recorta a borda): o desenho fica na zona segura central."""
    pixels = []
    margem = lado * 0.1 if com_margem else 0
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
            # garrafa: gargalo (estreito, em cima), ombro e corpo (largo, embaixo), tudo relativo à área útil
            gx, gy = (x - margem) / util, (y - margem) / util
            no_gargalo = 0.44 <= gx <= 0.56 and 0.14 <= gy <= 0.34
            no_corpo = 0.34 <= gx <= 0.66 and 0.40 <= gy <= 0.86
            no_ombro = 0.34 <= gx <= 0.66 and 0.34 <= gy < 0.40 and abs(gx - 0.5) <= 0.06 + (gy - 0.34) / 0.06 * 0.10
            if (no_gargalo or no_corpo or no_ombro) and cor[3]:
                cor = GARRAFA + (255,)
                if 0.36 <= gx <= 0.64 and 0.56 <= gy <= 0.72:
                    cor = ROTULO + (255,)
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
