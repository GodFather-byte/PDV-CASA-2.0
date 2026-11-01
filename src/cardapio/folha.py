"""Folha A4 com os QR do cardápio, um cartão por mesa. Só monta o HTML; quem imprime é o caixa."""
from __future__ import annotations

import base64
import io
from html import escape
from urllib.parse import quote

from src.core.erros import ErroNegocio

POR_PAGINA = 8
MAXIMO_MESAS = 200
TETO_MESA = 999


def base_da_nuvem(api_url: str) -> str:
    """O endereço configurado é o de envio (.../v1/sincronizar). O cardápio fica na raiz."""
    base = (api_url or "").strip().rstrip("/")
    if base.endswith("/v1/sincronizar"):
        base = base[: -len("/v1/sincronizar")]
    return base


def url_cardapio(api_url: str, chave: str, mesa: int | None = None) -> str:
    chave = (chave or "").strip()
    if not base_da_nuvem(api_url) or not chave:
        raise ErroNegocio("Preencha o endereço da nuvem e a chave da loja em Configurações > Nuvem.")
    consulta = "loja=" + quote(chave, safe="")
    if mesa is not None:
        consulta += f"&mesa={int(mesa)}"
    return f"{base_da_nuvem(api_url)}/cardapio/?{consulta}"


def intervalo_mesas(inicio: int, fim: int) -> list[int]:
    try:
        inicio, fim = int(inicio), int(fim)
    except (TypeError, ValueError):
        raise ErroNegocio("Informe o intervalo de mesas com números.") from None
    if inicio < 1 or fim > TETO_MESA or inicio > fim:
        raise ErroNegocio(f"O intervalo vai de 1 a {TETO_MESA}, com a primeira mesa menor ou igual à última.")
    if fim - inicio + 1 > MAXIMO_MESAS:
        raise ErroNegocio(f"Imprima no máximo {MAXIMO_MESAS} mesas por vez.")
    return list(range(inicio, fim + 1))


def cartoes(api_url: str, chave: str, inicio: int | None = None, fim: int | None = None) -> list[dict]:
    """Um cartão por mesa, ou um único cartão do cardápio quando a casa não numera mesa."""
    if inicio is None and fim is None:
        return [{"rotulo": "Cardápio", "mesa": None, "url": url_cardapio(api_url, chave)}]
    return [{"rotulo": f"Mesa {n}", "mesa": n, "url": url_cardapio(api_url, chave, n)}
            for n in intervalo_mesas(inicio if inicio is not None else 1, fim if fim is not None else inicio or 1)]


def png_qr(texto: str) -> bytes:
    import segno
    buf = io.BytesIO()
    segno.make(texto, error="m").save(buf, kind="png", scale=6, border=2, dark="#14532d", light="#ffffff")
    return buf.getvalue()


def paginas(itens: list[dict], por_pagina: int = POR_PAGINA) -> list[list[dict]]:
    return [itens[i:i + por_pagina] for i in range(0, len(itens), por_pagina)] or [[]]


def folha_html(loja: str, itens: list[dict]) -> str:
    """HTML para o navegador imprimir em A4: vários cartões por folha, cada um com o QR da mesa."""
    loja = escape((loja or "Cardápio").strip() or "Cardápio")
    blocos = []
    for folha in paginas(itens):
        cartas = []
        for item in folha:
            png = base64.b64encode(png_qr(item["url"])).decode("ascii")
            cartas.append(
                "<article class=\"cartao\">"
                f"<p class=\"loja\">{loja}</p>"
                f"<h2>{escape(item['rotulo'])}</h2>"
                f"<img alt=\"QR {escape(item['rotulo'])}\" title=\"{escape(item['url'])}\" "
                f"src=\"data:image/png;base64,{png}\">"
                "<p class=\"dica\">Aponte a câmera para ver o cardápio. Só consulta.</p>"
                "</article>"
            )
        blocos.append("<section class=\"pagina\">" + "".join(cartas) + "</section>")
    miolo = "\n".join(blocos)
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>QR do cardápio — {loja}</title>
<style>
  @page {{ size: A4; margin: 10mm; }}
  body {{ margin: 0; font-family: "Segoe UI", sans-serif; color: #142018; }}
  .pagina {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8mm; break-after: page; }}
  .pagina:last-child {{ break-after: auto; }}
  .cartao {{ border: 1px solid #c5d0c8; border-radius: 8px; text-align: center; padding: 6mm 4mm; }}
  .loja {{ margin: 0; font-size: 12pt; letter-spacing: .04em; text-transform: uppercase; color: #14532d; }}
  h2 {{ margin: 2mm 0 3mm; font-size: 22pt; }}
  img {{ width: 42mm; height: 42mm; }}
  .dica {{ margin: 3mm 0 0; font-size: 9pt; color: #4b5563; }}
  @media screen {{
    body {{ background: #eef2ef; }}
    .pagina {{ width: 190mm; margin: 8mm auto; background: #fff; padding: 8mm; box-shadow: 0 1px 4px #0002; }}
  }}
</style>
</head>
<body>
{miolo}
</body>
</html>
"""
