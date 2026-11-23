"""Site público de vendas do WillPDV, na mesma API (sem serviço extra).

Páginas: `/`, `/site` e `/site/`. O CSS fica em `/site/estilo.css`. Não monta arquivo
estático na raiz, para não encobrir `/v1`, `/porteiro`, `/cardapio`, `/painel` e `/central`.
"""
from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

from backend import site_precos as precos
from src.core.formatacao import fmt_brl
from src.versao import VERSAO

PASTA = Path(__file__).resolve().parent / "site_web"
VAR_WHATSAPP = "PDV_SITE_WHATSAPP"
_TEL = re.compile(r"\d{12,13}")


def numero_whatsapp() -> str:
    """DDI+DDD+número. Sem variável, ou com valor vazio/inválido, usa o padrão do arquivo de preços."""
    bruto = os.environ.get(VAR_WHATSAPP)
    if bruto is None or not str(bruto).strip():
        return precos.WHATSAPP_PADRAO
    digitos = re.sub(r"\D", "", str(bruto))
    if len(digitos) in (10, 11):
        digitos = "55" + digitos
    if _TEL.fullmatch(digitos):
        return digitos
    return precos.WHATSAPP_PADRAO


def link_whatsapp(texto: str) -> str:
    return f"https://wa.me/{numero_whatsapp()}?text={quote(texto)}"


def telefone_visivel(numero: str | None = None) -> str:
    """5511915168336 → (11) 91516-8336. Número curto demais volta só com os dígitos."""
    digitos = numero or numero_whatsapp()
    nacional = digitos[2:] if digitos.startswith("55") and len(digitos) > 11 else digitos
    if len(nacional) == 11:
        return f"({nacional[:2]}) {nacional[2:7]}-{nacional[7:]}"
    if len(nacional) == 10:
        return f"({nacional[:2]}) {nacional[2:6]}-{nacional[6:]}"
    return digitos


def telefone_internacional(numero: str | None = None) -> str:
    """5511915168336 → +55 11 91516-8336."""
    digitos = numero or numero_whatsapp()
    nacional = digitos[2:] if digitos.startswith("55") and len(digitos) > 11 else digitos
    if digitos.startswith("55") and len(nacional) == 11:
        return f"+55 {nacional[:2]} {nacional[2:7]}-{nacional[7:]}"
    if digitos.startswith("55") and len(nacional) == 10:
        return f"+55 {nacional[:2]} {nacional[2:6]}-{nacional[6:]}"
    return f"+{digitos}"


def preco_schema(cent: int) -> str:
    """Centavos para o price do schema.org (ponto decimal, duas casas)."""
    cent = int(cent)
    return f"{cent // 100}.{cent % 100:02d}"


MENSAGEM_CONTATO = "Oi Willyan, vi o site do WillPDV e quero saber mais"
TITULO = "WillPDV — sistema de caixa (PDV) em Osasco e região"


def meta_descricao() -> str:
    return (
        "WillPDV, sistema de caixa (PDV) em Osasco e região para adega, restaurante, "
        f"variedades, boate e bar. Planos a partir de {fmt_brl(precos.ADEGA_MENSAL_CENT)} por mês, "
        "anual com 2 meses grátis e instalação grátis."
    )


def _preco_html(cent: int, prefixo: str, periodo: str) -> str:
    valor = html.escape(fmt_brl(cent))
    miudo = f'<small class="prefixo">{html.escape(prefixo)}</small> ' if prefixo else ""
    sufixo = f"<small>/{html.escape(periodo)}</small>" if periodo else ""
    return f"{miudo}{valor}{sufixo}"


def grade_servicos() -> str:
    blocos = []
    for chave, nome, cent, prefixo, periodo in precos.SERVICOS:
        link = html.escape(link_whatsapp(f"{MENSAGEM_CONTATO} sobre {nome}."), quote=True)
        blocos.append(
            "<li>"
            f"<strong>{html.escape(nome)}</strong>"
            f"<span>{html.escape(precos.DESCRICAO_SERVICO[chave])}</span>"
            f'<p class="preco">{_preco_html(cent, prefixo, periodo)}</p>'
            f'<a class="zap" href="{link}">Chamar no WhatsApp</a>'
            "</li>"
        )
    return "\n".join(blocos)


def _oferta(nome: str, cent: int, descricao: str) -> dict:
    return {"@type": "Offer", "name": nome, "price": preco_schema(cent), "priceCurrency": "BRL",
            "description": descricao}


def json_ld() -> str:
    base = precos.URL_PUBLICA.rstrip("/")
    negocio = f"{base}/#negocio"
    cidades = [{"@type": "City", "name": cidade} for cidade in precos.CIDADES]
    planos = (
        ("Will Adega", precos.ADEGA_MENSAL_CENT),
        ("Will Restaurante", precos.RESTAURANTE_MENSAL_CENT),
        ("Will Variedades", precos.VARIEDADES_MENSAL_CENT),
        ("WillPDV Boate e Bar", precos.BOATE_MENSAL_CENT),
    )
    grafo = [{
        "@type": "LocalBusiness",
        "@id": negocio,
        "name": "WillPDV",
        "description": meta_descricao(),
        "url": base + "/",
        "telephone": telefone_internacional(),
        "image": f"{base}/site/balcao.webp",
        "address": {"@type": "PostalAddress", "addressLocality": "Osasco", "addressRegion": "SP",
                    "addressCountry": "BR"},
        "areaServed": cidades,
        "makesOffer": [_oferta("Instalação na loja", 0, "Instalação grátis")],
    }]
    for nome, mensal in planos:
        grafo.append({
            "@type": "SoftwareApplication",
            "name": nome,
            "applicationCategory": "BusinessApplication",
            "operatingSystem": "Windows",
            "offers": [
                _oferta(f"{nome} — mensal", mensal, "Plano mensal"),
                _oferta(f"{nome} — anual", precos.anual_cent(mensal), "Plano anual, 2 meses grátis"),
            ],
            "provider": {"@id": negocio},
        })
    for _chave, nome, cent, prefixo, periodo in precos.SERVICOS:
        if periodo:
            descricao = "Por mês"
        elif prefixo:
            descricao = "A partir de"
        else:
            descricao = "Preço único"
        grafo.append({"@type": "Service", "name": nome, "provider": {"@id": negocio},
                      "offers": _oferta(nome, cent, descricao)})
    texto = json.dumps({"@context": "https://schema.org", "@graph": grafo}, ensure_ascii=False)
    return texto.replace("<", "\\u003c")


def url_instalador(edicao: str, arquivo: str) -> str:
    return f"{precos.R2_BASE.rstrip('/')}/{edicao}/{VERSAO}/{arquivo}"


def _trocas() -> dict[str, str]:
    adega = fmt_brl(precos.ADEGA_MENSAL_CENT)
    boate = fmt_brl(precos.BOATE_MENSAL_CENT)
    restaurante = fmt_brl(precos.RESTAURANTE_MENSAL_CENT)
    variedades = fmt_brl(precos.VARIEDADES_MENSAL_CENT)
    adega_ano = fmt_brl(precos.anual_cent(precos.ADEGA_MENSAL_CENT))
    boate_ano = fmt_brl(precos.anual_cent(precos.BOATE_MENSAL_CENT))
    restaurante_ano = fmt_brl(precos.anual_cent(precos.RESTAURANTE_MENSAL_CENT))
    variedades_ano = fmt_brl(precos.anual_cent(precos.VARIEDADES_MENSAL_CENT))
    from backend.central_fornecedor import link_instalador
    return {
        "{{titulo}}": html.escape(TITULO, quote=True),
        "{{meta_descricao}}": html.escape(meta_descricao(), quote=True),
        "{{url_publica}}": html.escape(precos.URL_PUBLICA.rstrip("/"), quote=True),
        "{{json_ld}}": json_ld(),
        "{{grade_servicos}}": grade_servicos(),
        "{{adega_mensal}}": adega,
        "{{adega_anual}}": adega_ano,
        "{{boate_mensal}}": boate,
        "{{boate_anual}}": boate_ano,
        "{{restaurante_mensal}}": restaurante,
        "{{restaurante_anual}}": restaurante_ano,
        "{{variedades_mensal}}": variedades,
        "{{variedades_anual}}": variedades_ano,
        "{{download_willrestaurante}}": link_instalador("willrestaurante"),
        "{{zap_restaurante}}": link_whatsapp(
            f"{MENSAGEM_CONTATO}. Quero assinar o Will Restaurante por {restaurante} por mês."),
        "{{zap_variedades}}": link_whatsapp(
            f"{MENSAGEM_CONTATO}. Quero assinar o Will Variedades por {variedades} por mês."),
        "{{dias_teste}}": str(precos.DIAS_TESTE),
        "{{meses_gratis}}": str(precos.MESES_GRATIS_NO_ANUAL),
        "{{meses_cobrados}}": str(precos.meses_cobrados()),
        "{{versao}}": VERSAO,
        "{{telefone}}": telefone_visivel(),
        "{{download_willpdv}}": url_instalador("willpdv", f"WillPDV-Setup-{VERSAO}.exe"),
        "{{download_willadega}}": url_instalador("willadega", f"WillAdega-Setup-{VERSAO}.exe"),
        "{{zap_contato}}": link_whatsapp(MENSAGEM_CONTATO),
        "{{zap_adega}}": link_whatsapp(f"{MENSAGEM_CONTATO}. Quero assinar o Will Adega por {adega} por mês."),
        "{{zap_boate}}": link_whatsapp(
            f"{MENSAGEM_CONTATO}. Quero assinar o WillPDV para boate ou bar por {boate} por mês."),
        "{{zap_instalacao}}": link_whatsapp(f"{MENSAGEM_CONTATO}. Quero a instalação grátis do caixa."),
    }


def pagina() -> str:
    html = (PASTA / "index.html").read_text(encoding="utf-8")
    for chave, valor in _trocas().items():
        html = html.replace(chave, valor)
    return html


def instalar(app: FastAPI) -> None:
    cabecalho_html = {"Cache-Control": "no-cache"}
    cabecalho_css = {"Cache-Control": "public, max-age=3600"}

    @app.get("/", include_in_schema=False)
    @app.get("/site", include_in_schema=False)
    @app.get("/site/", include_in_schema=False)
    def site_index():
        return HTMLResponse(pagina(), headers=cabecalho_html)

    @app.get("/site/estilo.css", include_in_schema=False)
    def site_css():
        return FileResponse(PASTA / "estilo.css", media_type="text/css", headers=cabecalho_css)

    @app.get("/site/balcao.webp", include_in_schema=False)
    def site_foto():
        return FileResponse(PASTA / "balcao.webp", media_type="image/webp", headers=cabecalho_css)

    @app.get("/site/teste.js", include_in_schema=False)
    def site_js():
        return FileResponse(PASTA / "teste.js", media_type="text/javascript", headers=cabecalho_html)

    from backend import site_teste
    site_teste.instalar(app)
