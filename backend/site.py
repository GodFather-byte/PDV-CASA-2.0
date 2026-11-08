"""Site público de vendas do WillPDV, na mesma API (sem serviço extra).

Páginas: `/`, `/site` e `/site/`. O CSS fica em `/site/estilo.css`. Não monta arquivo
estático na raiz, para não encobrir `/v1`, `/porteiro`, `/cardapio`, `/painel` e `/central`.
"""
from __future__ import annotations

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


def url_instalador(edicao: str, arquivo: str) -> str:
    return f"{precos.R2_BASE.rstrip('/')}/{edicao}/{VERSAO}/{arquivo}"


def _trocas() -> dict[str, str]:
    adega = fmt_brl(precos.ADEGA_MENSAL_CENT)
    boate = fmt_brl(precos.BOATE_MENSAL_CENT)
    instalacao = fmt_brl(precos.INSTALACAO_CENT)
    adega_ano = fmt_brl(precos.anual_cent(precos.ADEGA_MENSAL_CENT))
    boate_ano = fmt_brl(precos.anual_cent(precos.BOATE_MENSAL_CENT))
    return {
        "{{adega_mensal}}": adega,
        "{{adega_anual}}": adega_ano,
        "{{boate_mensal}}": boate,
        "{{boate_anual}}": boate_ano,
        "{{instalacao}}": instalacao,
        "{{dias_teste}}": str(precos.DIAS_TESTE),
        "{{meses_gratis}}": str(precos.MESES_GRATIS_NO_ANUAL),
        "{{meses_cobrados}}": str(precos.meses_cobrados()),
        "{{versao}}": VERSAO,
        "{{telefone}}": telefone_visivel(),
        "{{download_willpdv}}": url_instalador("willpdv", f"WillPDV-Setup-{VERSAO}.exe"),
        "{{download_willadega}}": url_instalador("willadega", f"WillAdega-Setup-{VERSAO}.exe"),
        "{{zap_contato}}": link_whatsapp("Olá, quero conhecer o WillPDV."),
        "{{zap_adega}}": link_whatsapp(f"Olá, quero assinar o Will Adega por {adega} por mês."),
        "{{zap_boate}}": link_whatsapp(f"Olá, quero assinar o WillPDV para boate ou bar por {boate} por mês."),
        "{{zap_instalacao}}": link_whatsapp(f"Olá, quero a instalação do WillPDV ({instalacao}, uma vez)."),
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
