"""Site público de vendas do WillPDV, na mesma API (sem serviço extra).

Páginas: `/`, `/site`, `/site/`, `/site/termos`, `/site/privacidade` e os retornos
do checkout (`/site/obrigado`, `/site/pagamento-pendente`, `/site/pagamento-falhou`).
O CSS fica em `/site/estilo.css`. Também publica `/robots.txt` e `/sitemap.xml`.
Não monta arquivo estático na raiz, para não encobrir `/v1`, `/porteiro`,
`/cardapio`, `/painel` e `/central`.

Quem abre uma página pública pelo host `*.onrender.com` recebe 301 para
https://willpdv.com.br. `/v1`, painel, webhooks, health e o resto da API ficam
no host antigo, que os caixas usam.
"""
from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

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
        f"variedades, hotel, pousada, boate e bar. Planos a partir de {fmt_brl(precos.ADEGA_MENSAL_CENT)} por mês, "
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


def url_publica() -> str:
    """Mesma origem do checkout: PUBLIC_BASE_URL válida, senão https://willpdv.com.br."""
    from backend.site_checkout import base_publica
    return base_publica()


def json_ld() -> str:
    base = url_publica().rstrip("/")
    negocio = f"{base}/#negocio"
    cidades = [{"@type": "City", "name": cidade} for cidade in precos.CIDADES]
    planos = (
        ("Will Adega", precos.ADEGA_MENSAL_CENT),
        ("Will Restaurante", precos.RESTAURANTE_MENSAL_CENT),
        ("Will Variedades", precos.VARIEDADES_MENSAL_CENT),
        ("Will Hotel", precos.HOTEL_MENSAL_CENT),
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


def botao_compra(chave: str, nome: str, zap: str) -> str:
    """Assinar agora / Comprar. Sem token do Mercado Pago, o mesmo botão abre o WhatsApp."""
    from backend.site_checkout import checkout_disponivel
    rotulo = '<span class="so-mes">Assinar agora</span><span class="so-ano">Comprar</span>'
    if not checkout_disponivel():
        return f'<a class="botao" href="{html.escape(zap, quote=True)}">{rotulo}</a>'
    return (
        '<button type="button" class="botao checkout-abrir" '
        f'data-plano="{html.escape(chave, quote=True)}" '
        f'data-nome="{html.escape(nome, quote=True)}" '
        f'data-zap="{html.escape(zap, quote=True)}">{rotulo}</button>'
    )


def _trocas() -> dict[str, str]:
    adega = fmt_brl(precos.ADEGA_MENSAL_CENT)
    boate = fmt_brl(precos.BOATE_MENSAL_CENT)
    restaurante = fmt_brl(precos.RESTAURANTE_MENSAL_CENT)
    variedades = fmt_brl(precos.VARIEDADES_MENSAL_CENT)
    hotel = fmt_brl(precos.HOTEL_MENSAL_CENT)
    adega_ano = fmt_brl(precos.anual_cent(precos.ADEGA_MENSAL_CENT))
    boate_ano = fmt_brl(precos.anual_cent(precos.BOATE_MENSAL_CENT))
    restaurante_ano = fmt_brl(precos.anual_cent(precos.RESTAURANTE_MENSAL_CENT))
    variedades_ano = fmt_brl(precos.anual_cent(precos.VARIEDADES_MENSAL_CENT))
    hotel_ano = fmt_brl(precos.anual_cent(precos.HOTEL_MENSAL_CENT))
    from backend.central_fornecedor import link_instalador
    zap_adega = link_whatsapp(
        f"{MENSAGEM_CONTATO}. Quero assinar o Will Adega por {adega} por mês.")
    zap_boate = link_whatsapp(
        f"{MENSAGEM_CONTATO}. Quero assinar o WillPDV para boate ou bar por {boate} por mês.")
    zap_restaurante = link_whatsapp(
        f"{MENSAGEM_CONTATO}. Quero assinar o Will Restaurante por {restaurante} por mês.")
    zap_variedades = link_whatsapp(
        f"{MENSAGEM_CONTATO}. Quero assinar o Will Variedades por {variedades} por mês.")
    zap_hotel = link_whatsapp(
        f"{MENSAGEM_CONTATO}. Quero assinar o Will Hotel por {hotel} por mês.")
    return {
        "{{titulo}}": html.escape(TITULO, quote=True),
        "{{meta_descricao}}": html.escape(meta_descricao(), quote=True),
        "{{url_publica}}": html.escape(url_publica().rstrip("/"), quote=True),
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
        "{{hotel_mensal}}": hotel,
        "{{hotel_anual}}": hotel_ano,
        "{{download_willrestaurante}}": link_instalador("willrestaurante"),
        "{{download_willvariedades}}": link_instalador("willvariedades"),
        "{{download_willhotel}}": link_instalador("willhotel"),
        "{{zap_restaurante}}": zap_restaurante,
        "{{zap_variedades}}": zap_variedades,
        "{{zap_hotel}}": zap_hotel,
        "{{compra_adega}}": botao_compra("adega", "Will Adega", zap_adega),
        "{{compra_restaurante}}": botao_compra("restaurante", "Will Restaurante", zap_restaurante),
        "{{compra_variedades}}": botao_compra("variedades", "Will Variedades", zap_variedades),
        "{{compra_hotel}}": botao_compra("hotel", "Will Hotel", zap_hotel),
        "{{compra_boate}}": botao_compra("boate", "WillPDV Boate e Bar", zap_boate),
        "{{dias_teste}}": str(precos.DIAS_TESTE),
        "{{meses_gratis}}": str(precos.MESES_GRATIS_NO_ANUAL),
        "{{meses_cobrados}}": str(precos.meses_cobrados()),
        "{{versao}}": VERSAO,
        "{{telefone}}": telefone_visivel(),
        "{{download_willpdv}}": link_instalador("willpdv"),
        "{{download_willadega}}": link_instalador("willadega"),
        "{{zap_contato}}": link_whatsapp(MENSAGEM_CONTATO),
        "{{zap_adega}}": zap_adega,
        "{{zap_boate}}": zap_boate,
        "{{zap_instalacao}}": link_whatsapp(f"{MENSAGEM_CONTATO}. Quero a instalação grátis do caixa."),
    }


_PAGINAS = ("index.html", "termos.html", "privacidade.html")


def pagina(nome: str = "index.html") -> str:
    if nome not in _PAGINAS:
        raise ValueError("Página do site desconhecida.")
    texto = (PASTA / nome).read_text(encoding="utf-8")
    for chave, valor in _trocas().items():
        texto = texto.replace(chave, valor)
    return texto


_RETORNOS = {
    "obrigado": (
        "Obrigado",
        "Obrigado. Se o Mercado Pago aprovou o pagamento, a gente confirma o pedido e "
        "chama você no WhatsApp para combinar a instalação, que é grátis.",
    ),
    "pendente": (
        "Pagamento pendente",
        "O pagamento ficou pendente. No Pix isso é comum: quando o Mercado Pago confirmar, "
        "a gente chama você no WhatsApp.",
    ),
    "falhou": (
        "Pagamento não concluído",
        "O pagamento não foi concluído. Você pode voltar aos planos e tentar de novo, "
        "ou chamar no WhatsApp.",
    ),
}
_ID_PAGAMENTO_URL = re.compile(r"[0-9]{1,20}")


def pagina_retorno(chave: str, request: Request) -> str:
    titulo, mensagem = _RETORNOS[chave]
    pagamento = ""
    for nome in ("payment_id", "collection_id"):
        bruto = request.query_params.get(nome) or ""
        if _ID_PAGAMENTO_URL.fullmatch(bruto):
            pagamento = bruto
            break
    extra = (f'<p class="miudo">Número do pagamento: {pagamento}. Guarde este número se precisar falar com a gente.</p>'
             if pagamento else "")
    texto = (PASTA / "retorno.html").read_text(encoding="utf-8")
    trocas = _trocas()
    trocas["{{titulo_retorno}}"] = html.escape(titulo, quote=True)
    trocas["{{mensagem_retorno}}"] = html.escape(mensagem, quote=True)
    trocas["{{extra_retorno}}"] = extra
    for marca, valor in trocas.items():
        texto = texto.replace(marca, valor)
    return texto


# Só estas páginas mudam de host. O conjunto é fechado de propósito: um prefixo
# /site pegaria no futuro uma rota que não é vitrine, e /v1 nunca entra aqui.
PAGINAS_PUBLICAS = frozenset({
    "/",
    "/site",
    "/site/",
    "/site/termos",
    "/site/termos/",
    "/site/privacidade",
    "/site/privacidade/",
    "/site/obrigado",
    "/site/obrigado/",
    "/site/pagamento-pendente",
    "/site/pagamento-pendente/",
    "/site/pagamento-falhou",
    "/site/pagamento-falhou/",
    "/robots.txt",
    "/sitemap.xml",
})
_CAMINHOS_SITEMAP = ("/", "/site/termos", "/site/privacidade")
_HOST = re.compile(r"[a-z0-9.-]+")


def _host_limpo(bruto: str) -> str:
    """Primeiro host do cabeçalho, sem porta e sem ponto final."""
    return bruto.split(",")[0].strip().split(":")[0].lower().rstrip(".")


def host_pedido(request: Request) -> str:
    """Host que o cliente pediu, sem porta."""
    return _host_limpo(request.headers.get("host") or request.url.hostname or "")


def destino_se_onrender(request: Request) -> str | None:
    """URL absoluta do 301, ou None para a API seguir normal.

    Só GET e HEAD, só página pública, só host *.onrender.com. Se o endereço
    público também for onrender, não redireciona (evita laço). Se o proxy já
    diz que o host original é o domínio público, também não redireciona.
    """
    if request.method not in ("GET", "HEAD"):
        return None
    host = host_pedido(request)
    if not _HOST.fullmatch(host) or not host.endswith(".onrender.com"):
        return None
    if request.url.path not in PAGINAS_PUBLICAS:
        return None
    base = url_publica().rstrip("/")
    destino_host = base.split("://", 1)[-1].lower().rstrip(".")
    if not destino_host or destino_host == host or destino_host.endswith(".onrender.com"):
        return None
    encaminhado = _host_limpo(request.headers.get("x-forwarded-host") or "")
    if encaminhado == destino_host:
        return None
    consulta = request.url.query
    if any(ord(c) < 32 or c in " \\" for c in consulta):
        consulta = ""
    return base + request.url.path + (("?" + consulta) if consulta else "")


def robots_txt() -> str:
    base = url_publica().rstrip("/")
    return f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n"


def sitemap_xml() -> str:
    base = url_publica().rstrip("/")
    linhas = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for caminho in _CAMINHOS_SITEMAP:
        linhas.append(f"  <url><loc>{html.escape(base + caminho)}</loc></url>")
    linhas.append("</urlset>")
    return "\n".join(linhas) + "\n"


def instalar(app: FastAPI) -> None:
    cabecalho_html = {"Cache-Control": "no-cache"}
    cabecalho_css = {"Cache-Control": "public, max-age=3600"}

    @app.middleware("http")
    async def redirecionar_site_no_onrender(request: Request, call_next):
        destino = destino_se_onrender(request)
        if destino is None:
            return await call_next(request)
        return RedirectResponse(destino, status_code=301)

    @app.get("/", include_in_schema=False)
    @app.get("/site", include_in_schema=False)
    @app.get("/site/", include_in_schema=False)
    def site_index():
        return HTMLResponse(pagina(), headers=cabecalho_html)

    @app.get("/site/termos", include_in_schema=False)
    @app.get("/site/termos/", include_in_schema=False)
    def site_termos():
        return HTMLResponse(pagina("termos.html"), headers=cabecalho_html)

    @app.get("/site/privacidade", include_in_schema=False)
    @app.get("/site/privacidade/", include_in_schema=False)
    def site_privacidade():
        return HTMLResponse(pagina("privacidade.html"), headers=cabecalho_html)

    @app.get("/robots.txt", include_in_schema=False)
    def site_robots():
        return Response(robots_txt(), media_type="text/plain; charset=utf-8", headers=cabecalho_html)

    @app.get("/sitemap.xml", include_in_schema=False)
    def site_sitemap():
        return Response(sitemap_xml(), media_type="application/xml; charset=utf-8", headers=cabecalho_html)

    @app.get("/site/estilo.css", include_in_schema=False)
    def site_css():
        return FileResponse(PASTA / "estilo.css", media_type="text/css", headers=cabecalho_css)

    @app.get("/site/balcao.webp", include_in_schema=False)
    def site_foto():
        return FileResponse(PASTA / "balcao.webp", media_type="image/webp", headers=cabecalho_css)

    @app.get("/site/teste.js", include_in_schema=False)
    def site_js():
        return FileResponse(PASTA / "teste.js", media_type="text/javascript", headers=cabecalho_html)

    @app.get("/site/checkout.js", include_in_schema=False)
    def site_checkout_js():
        return FileResponse(PASTA / "checkout.js", media_type="text/javascript", headers=cabecalho_html)

    @app.get("/site/obrigado", include_in_schema=False)
    @app.get("/site/obrigado/", include_in_schema=False)
    def site_obrigado(request: Request):
        return HTMLResponse(pagina_retorno("obrigado", request), headers=cabecalho_html)

    @app.get("/site/pagamento-pendente", include_in_schema=False)
    @app.get("/site/pagamento-pendente/", include_in_schema=False)
    def site_pendente(request: Request):
        return HTMLResponse(pagina_retorno("pendente", request), headers=cabecalho_html)

    @app.get("/site/pagamento-falhou", include_in_schema=False)
    @app.get("/site/pagamento-falhou/", include_in_schema=False)
    def site_falhou(request: Request):
        return HTMLResponse(pagina_retorno("falhou", request), headers=cabecalho_html)

    from backend import site_checkout, site_teste
    site_teste.instalar(app)
    site_checkout.instalar(app)
