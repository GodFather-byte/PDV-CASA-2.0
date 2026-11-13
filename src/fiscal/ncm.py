"""NCM do produto: limpeza, validação e sugestão pelo nome.

A sugestão cobre o que mais aparece em empório, adega e boate. É só sugestão: quem cadastra confere, e na dúvida
o contador decide (o NCM define o imposto da nota).
"""
from __future__ import annotations

import re
import unicodedata

from src.core.erros import ErroNegocio

# (palavras ou marcas, NCM, descrição). A ordem importa: o primeiro que bater ganha, então o mais específico vem antes.
SUGESTOES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("agua de coco", "leite de coco"), "", ""),           # parecido com outra coisa: melhor não sugerir
    (("sem alcool", "zero alcool", "0 0", "budweiser zero"), "22029100", "cerveja sem álcool"),
    (("gelo",), "22019000", "gelo"),
    (("ice", "beats", "xeque mate"), "22089000", "bebida alcoólica mista (ice)"),
    (("energetico", "red bull", "monster", "tnt", "baly", "fusion", "burn"), "22029900", "energético"),
    (("isotonico", "gatorade", "powerade"), "22029900", "isotônico"),
    (("suco", "nectar", "del valle", "cha gelado", "mate couro", "ades", "toddynho", "achocolatado"),
     "22029900", "suco ou bebida pronta"),
    (("refrigerante", "refri", "coca", "guarana", "fanta", "sprite", "pepsi", "kuat", "soda", "schweppes",
      "tonica", "tubaina", "dolly", "h2oh"), "22021000", "refrigerante"),
    (("agua",), "22011000", "água mineral"),
    (("cerveja", "chope", "chopp", "skol", "brahma", "antarctica", "heineken", "budweiser", "itaipava", "amstel",
      "stella", "corona", "eisenbahn", "devassa", "petra", "crystal", "spaten", "bohemia", "colorado",
      "becks", "sol", "michelob", "lokal", "imperio", "puro malte", "long neck"), "22030000", "cerveja"),
    (("espumante", "champagne", "prosecco", "chandon"), "22041090", "espumante"),
    (("vinho", "cabernet", "merlot", "malbec", "carmenere", "sangue de boi", "pergola", "quinta do morgado"),
     "22042100", "vinho"),
    (("vermute", "martini", "cinzano"), "22051000", "vermute"),
    (("whisky", "uisque", "red label", "black label", "johnnie walker", "jack daniel", "chivas", "ballantine",
      "white horse", "passport", "old parr", "buchanan", "jameson", "grand old parr", "teachers"),
     "22083020", "uísque"),
    (("vodka", "smirnoff", "absolut", "orloff", "skyy", "ciroc", "belvedere", "ketel"), "22086000", "vodka"),
    (("gin", "tanqueray", "gordons", "beefeater", "bombay", "seagers", "rocks"), "22085000", "gin"),
    (("cachaca", "pinga", "ypioca", "velho barreiro", "pitu", "sagatiba", "salinas", "seleta", "51"),
     "22084000", "cachaça"),
    (("rum", "bacardi", "montilla"), "22084000", "rum"),
    (("conhaque", "brandy", "dreher", "domecq"), "22082000", "conhaque"),
    (("licor", "jagermeister", "amarula", "baileys", "cointreau", "frangelico"), "22087000", "licor"),
    (("tequila", "jose cuervo", "campari", "aperol", "steinhaeger", "catuaba", "corote"), "22089000",
     "outras bebidas destiladas"),
    (("saque",), "22060090", "saquê"),
    (("cigarro", "marlboro", "lucky strike", "dunhill", "rothmans", "kent", "camel", "winston", "derby", "eight",
      "chesterfield"), "24022000", "cigarro"),
    (("charuto", "cigarrilha"), "24021000", "charuto"),
    (("carvao de coco",), "44029000", "carvão para narguilé"),
    (("essencia", "narguile", "fumo"), "24031100", "tabaco para narguilé"),
    (("seda", "papel de enrolar"), "48131000", "papel para cigarro (seda)"),
    (("isqueiro", "bic"), "96131000", "isqueiro"),
    (("carvao",), "44029000", "carvão vegetal"),
    (("batata", "chips", "pringles", "ruffles"), "20052000", "batata frita (chips)"),
    (("salgadinho", "doritos", "cheetos", "fandangos", "torcida", "baconzitos", "elma chips"), "19041000",
     "salgadinho de milho"),
    (("amendoim", "dori", "mendorato", "japones"), "20081100", "amendoim"),
    (("chocolate", "bombom", "kitkat", "kit kat", "snickers", "twix", "lacta", "garoto", "talento"),
     "18069000", "chocolate"),
    (("chiclete", "trident", "mentos"), "17041000", "goma de mascar"),
    (("bala", "halls", "pirulito", "pacoca", "doce de leite"), "17049020", "balas e confeitos"),
    (("copo descartavel", "canudo"), "39241000", "copo e canudo descartável"),
    (("biscoito", "bolacha", "wafer", "cookie", "oreo", "trakinas", "passatempo"), "19053100", "biscoito"),
    (("leite",), "04011010", "leite UHT"),
    (("pao", "torrada"), "19059090", "pão e torrada"),
)


def _texto(valor: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode()
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", sem_acento.lower()).split()) + " "


def limpar(ncm: str | None) -> str:
    """'2203.00.00' -> '22030000'. Vazio continua vazio."""
    return "".join(c for c in str(ncm or "") if c.isdigit())


def validar(ncm: str | None) -> str:
    """Devolve o NCM só com dígitos; vazio é permitido, mas preenchido tem de ter 8 dígitos."""
    limpo = limpar(ncm)
    if str(ncm or "").strip() and len(limpo) != 8:
        raise ErroNegocio("O NCM tem 8 números (ex.: 2203.00.00 para cerveja).")
    return limpo


def formatar(ncm: str | None) -> str:
    limpo = limpar(ncm)
    return f"{limpo[:4]}.{limpo[4:6]}.{limpo[6:]}" if len(limpo) == 8 else limpo


def sugerir(nome: str | None) -> tuple[str, str] | None:
    """NCM provável pelo nome do produto: (ncm, descrição) ou None."""
    texto = _texto(nome)
    if not texto.strip():
        return None
    for palavras, ncm, descricao in SUGESTOES:
        if any(f" {_texto(p).strip()} " in texto for p in palavras):
            return (ncm, descricao) if ncm else None
    return None
