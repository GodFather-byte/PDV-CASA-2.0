"""Gera os logotipos do WillPDV e do WillPDV Licenças (ícone .ico, logo .png e as imagens do assistente do instalador).

Ferramenta do fornecedor (não vai no instalador). Precisa do Pillow só para rodar isto:  pip install pillow

    python -m tools.gerar_logos

Grava em `instalador/`. Os arquivos gerados ficam no repositório, então o build não depende do Pillow. Para usar uma
marca própria, basta trocar `willpdv.ico` (e os .bmp) por arquivos seus com os mesmos nomes.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SAIDA = Path(__file__).resolve().parents[1] / "instalador"
FONTES = ["/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf", "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
          "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
TAM = 1024          # desenha grande e reduz: bordas lisas em qualquer tamanho

MARINHO, AZUL, AZUL_CLARO, BRANCO = (20, 35, 77), (79, 140, 255), (159, 179, 232), (255, 255, 255)
ESCURO, AMBAR = (10, 16, 34), (255, 197, 71)


def fonte(tamanho: int) -> ImageFont.FreeTypeFont:
    for caminho in FONTES:
        if Path(caminho).exists():
            return ImageFont.truetype(caminho, tamanho)
    raise SystemExit("Nenhuma fonte em negrito encontrada para desenhar o logo.")


def _degrade(tam: int, de: tuple, ate: tuple) -> Image.Image:
    """Degradê diagonal (canto de cima à esquerda -> canto de baixo à direita)."""
    img = Image.new("RGB", (tam, tam))
    px = img.load()
    for y in range(tam):
        for x in range(tam):
            t = (x + y) / (2 * (tam - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(de, ate))
    return img


def _quadrado(de: tuple, ate: tuple) -> Image.Image:
    """Fundo: quadrado arredondado com degradê, sobre transparente."""
    base = _degrade(TAM, de, ate).convert("RGBA")
    mascara = Image.new("L", (TAM, TAM), 0)
    ImageDraw.Draw(mascara).rounded_rectangle((0, 0, TAM - 1, TAM - 1), radius=int(TAM * 0.22), fill=255)
    base.putalpha(mascara)
    return base


def logo_pdv() -> Image.Image:
    """Um 'W' grande em branco, com a etiqueta PDV em azul embaixo."""
    img = _quadrado((31, 58, 138), ESCURO)
    d = ImageDraw.Draw(img)
    f = fonte(int(TAM * 0.62))
    d.text((TAM / 2, TAM * 0.43), "W", font=f, fill=BRANCO, anchor="mm")
    caixa = (int(TAM * 0.28), int(TAM * 0.70), int(TAM * 0.72), int(TAM * 0.86))
    d.rounded_rectangle(caixa, radius=int(TAM * 0.08), fill=AZUL)
    d.text(((caixa[0] + caixa[2]) / 2, (caixa[1] + caixa[3]) / 2 + 4), "PDV", font=fonte(int(TAM * 0.115)), fill=BRANCO, anchor="mm")
    return img


def logo_licencas() -> Image.Image:
    """Uma chave (a licença) em âmbar sobre o mesmo fundo, para não confundir com o PDV do cliente."""
    img = _quadrado((60, 48, 110), ESCURO)
    d = ImageDraw.Draw(img)
    cx, cy, r = int(TAM * 0.36), int(TAM * 0.40), int(TAM * 0.17)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=AMBAR, width=int(TAM * 0.07))              # cabeça da chave
    d.ellipse((cx - r * 0.38, cy - r * 0.38, cx + r * 0.38, cy + r * 0.38), fill=AMBAR)
    haste_y = cy + int(TAM * 0.02)
    d.rounded_rectangle((cx + r - 4, haste_y - int(TAM * 0.035), int(TAM * 0.84), haste_y + int(TAM * 0.035)),
                        radius=int(TAM * 0.03), fill=AMBAR)                                            # haste
    for x in (0.64, 0.76):                                                                            # dentes
        d.rounded_rectangle((int(TAM * x), haste_y, int(TAM * (x + 0.05)), haste_y + int(TAM * 0.15)), radius=int(TAM * 0.02), fill=AMBAR)
    d.text((TAM / 2, TAM * 0.80), "LICENÇAS", font=fonte(int(TAM * 0.115)), fill=BRANCO, anchor="mm")
    return img


def _em_fundo(logo: Image.Image, lado: int, fundo: tuple) -> Image.Image:
    img = Image.new("RGB", (lado, lado), fundo)
    peq = logo.resize((lado, lado), Image.LANCZOS)
    img.paste(peq, (0, 0), peq)
    return img


def imagem_grande(logo: Image.Image, nome: str, subtitulo: str, de: tuple, ate: tuple) -> Image.Image:
    """Painel da esquerda do assistente do instalador: 164 x 314 (desenhado em dobro e reduzido)."""
    w, h = 164 * 4, 314 * 4
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        cor = tuple(round(a + (b - a) * t) for a, b in zip(de, ate))
        for x in range(w):
            px[x, y] = cor
    miniatura = logo.resize((int(w * 0.72), int(w * 0.72)), Image.LANCZOS)
    img.paste(miniatura, ((w - miniatura.width) // 2, int(h * 0.09)), miniatura)
    d = ImageDraw.Draw(img)
    d.text((w / 2, h * 0.505), nome, font=fonte(int(w * 0.17)), fill=BRANCO, anchor="mm")
    d.text((w / 2, h * 0.595), subtitulo, font=fonte(int(w * 0.082)), fill=AZUL_CLARO, anchor="mm")
    d.rectangle((int(w * 0.18), int(h * 0.64), int(w * 0.82), int(h * 0.64) + 8), fill=AZUL if de != (60, 48, 110) else AMBAR)
    return img.resize((164, 314), Image.LANCZOS)


def gravar(logo: Image.Image, prefixo: str, nome: str, subtitulo: str, de: tuple, ate: tuple) -> list[Path]:
    SAIDA.mkdir(parents=True, exist_ok=True)
    escritos = []
    ico = SAIDA / f"{prefixo}.ico"
    logo.resize((256, 256), Image.LANCZOS).save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    png = SAIDA / f"{prefixo}-logo.png"
    logo.resize((512, 512), Image.LANCZOS).save(png)
    grande = SAIDA / f"{prefixo}-assistente.bmp"
    imagem_grande(logo, nome, subtitulo, de, ate).save(grande, "BMP")
    pequena = SAIDA / f"{prefixo}-assistente-pequena.bmp"
    _em_fundo(logo, 55, BRANCO).save(pequena, "BMP")
    return escritos + [ico, png, grande, pequena]


def main() -> None:
    arquivos = gravar(logo_pdv(), "willpdv", "WillPDV", "Ponto de venda", (31, 58, 138), ESCURO)
    arquivos += gravar(logo_licencas(), "willlicencas", "Licenças", "WillPDV", (60, 48, 110), ESCURO)
    for a in arquivos:
        print(f"{a.relative_to(SAIDA.parent)}  ({a.stat().st_size // 1024 or 1} KB)")


if __name__ == "__main__":
    main()
