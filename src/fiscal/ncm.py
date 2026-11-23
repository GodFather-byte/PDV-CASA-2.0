"""NCM do produto: limpeza, validação e sugestão pelo nome.

A sugestão cobre o que mais aparece em empório, adega, boate e loja de variedades (eletrônicos e utilidades). É só sugestão: quem cadastra confere, e na dúvida
o contador decide (o NCM define o imposto da nota).
"""
from __future__ import annotations

import re
import unicodedata

from src.core.erros import ErroNegocio

# (palavras ou marcas, NCM, descrição). A ordem importa: o primeiro que bater ganha, então o mais específico vem antes.
SUGESTOES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("agua de coco", "leite de coco"), "", ""),           # parecido com outra coisa: melhor não sugerir
    # Loja de variedades. Vem antes das bebidas porque usa frases inteiras ("copo termico", "carregador portatil").
    (("power bank", "carregador portatil"), "85076000", "carregador portátil (power bank)"),
    (("carregador",), "85044010", "carregador"),
    (("adaptador de tomada", "benjamim"), "85366990", "adaptador de tomada"),
    (("fone de ouvido", "headset", "headphone"), "85183000", "fone de ouvido"),
    (("microfone",), "85181090", "microfone"),
    (("caixa de som",), "85182100", "caixa de som"),
    (("cabo usb", "cabo tipo c", "cabo hdmi", "cabo auxiliar", "cabo de rede", "cabo de forca", "extensao eletrica",
      "filtro de linha"), "85444200", "cabo com conector"),
    (("pelicula",), "70071900", "película de vidro"),
    (("capinha", "suporte de celular", "bastao de selfie", "tripe para celular", "chaveiro"), "39269090",
     "acessório de plástico"),
    (("mouse pad",), "", ""),                              # borracha, tecido ou plástico: depende do material
    (("leitor de cartao",), "", ""),
    (("cartao de memoria",), "85235110", "cartão de memória"),
    (("pen drive", "pendrive"), "85235190", "pen drive"),
    (("mouse",), "84716053", "mouse"),
    (("teclado",), "84716052", "teclado"),
    (("calculadora",), "84701000", "calculadora"),
    (("lanterna",), "85131010", "lanterna"),
    (("lampada led",), "85395200", "lâmpada LED"),
    (("bateria de litio", "cr2032", "cr2025"), "85065010", "bateria de lítio"),
    (("garrafa termica", "copo termico"), "96170010", "garrafa ou copo térmico"),
    (("caneca",), "69120000", "caneca de cerâmica"),
    (("copo de vidro", "copos de vidro"), "70133700", "copo de vidro"),
    (("panela de inox", "panelas de inox"), "73239300", "panela de inox"),
    (("panela", "panelas", "cacarola", "frigideira", "leiteira"), "76151000", "panela de alumínio"),
    (("panelinhas",), "95030099", "brinquedo"),
    (("talheres",), "82159910", "talheres de inox"),
    (("faca de cozinha", "facas de cozinha"), "82119210", "faca de cozinha"),
    (("abridor",), "82055100", "abridor"),
    (("copo personalizado", "squeeze", "pote plastico", "potes plasticos", "tabua de corte", "escorredor",
      "jarra plastica", "prato plastico", "espatula"), "39241000", "utensílio de mesa e cozinha de plástico"),
    (("balde", "bacia", "cesto organizador", "caixa organizadora", "cabide", "prendedor de roupa", "lixeira",
      "saboneteira", "porta escova"), "39249000", "utilidade doméstica de plástico"),
    (("esponja de aco",), "73231000", "esponja de aço"),
    (("pano de prato",), "63029100", "pano de prato"),
    (("pano de chao", "flanela"), "63071000", "pano de limpeza"),
    (("escova de cabelo",), "96032900", "escova de cabelo"),
    (("vassoura", "rodo", "escova de limpeza"), "96039000", "vassoura, rodo ou escova"),
    (("sombrinha",), "66019110", "sombrinha dobrável"),
    (("guarda chuva",), "66019900", "guarda-chuva"),
    (("chave de fenda", "chave philips", "chaves de fenda"), "82054000", "chave de fenda"),
    (("alicate",), "82032010", "alicate"),
    (("martelo",), "82052000", "martelo"),
    (("trena",), "90178010", "trena"),
    (("cadeado",), "83011000", "cadeado"),
    (("cola instantanea", "super bonder"), "35061010", "cola instantânea"),
    (("cola branca", "cola bastao"), "35061090", "cola"),
    (("meia", "meias"), "61159500", "meias"),
    (("cueca", "cuecas"), "61071100", "cueca"),
    (("calcinha", "calcinhas"), "61082100", "calcinha"),
    (("camiseta",), "61091000", "camiseta"),
    (("chinelo",), "64022000", "chinelo de borracha"),
    (("oculos de sol",), "90041000", "óculos de sol"),
    (("carteira",), "42023200", "carteira"),
    (("mochila", "estojo escolar"), "42029200", "mochila ou estojo"),
    (("pente",), "96151100", "pente"),
    (("cortador de unha", "kit manicure"), "82142000", "cortador de unha e manicure"),
    (("espelho",), "70099200", "espelho"),
    (("elastico de cabelo", "presilha", "tiara", "piranha de cabelo"), "96159000", "acessório de cabelo"),
    (("esmalte",), "33043000", "esmalte"),
    (("batom",), "33041000", "batom"),
    (("secador de cabelo",), "85163100", "secador de cabelo"),
    (("chapinha",), "85163200", "chapinha"),
    (("maquina de cortar cabelo",), "85102000", "máquina de cortar cabelo"),
    (("aparelho de barbear",), "82121020", "aparelho de barbear"),
    (("boneca",), "95030022", "boneca"),
    (("quebra cabeca",), "95030060", "quebra-cabeça"),
    (("bola de futebol", "bola de volei"), "95066200", "bola"),
    (("baralho", "domino"), "95044000", "baralho e jogos de mesa"),
    (("massinha",), "34070010", "massa de modelar"),
    (("brinquedo", "carrinho", "blocos de montar", "ioio", "slime"), "95030099", "brinquedo"),
    (("caderno",), "48202000", "caderno"),
    (("canetinha", "marca texto", "pincel atomico"), "96082000", "canetinha e marcador"),
    (("caneta", "canetas"), "96081000", "caneta esferográfica"),
    (("apontador",), "82141000", "apontador"),
    (("lapis",), "96091000", "lápis"),
    (("borracha escolar",), "40169200", "borracha de apagar"),
    (("tesoura",), "82130000", "tesoura"),
    (("regua",), "90172000", "régua"),
    (("sulfite",), "48025610", "papel sulfite"),
    (("envelope",), "48171000", "envelope"),
    (("sacola de papel",), "48194000", "sacola de papel"),
    (("porta retrato", "enfeite"), "39264000", "objeto de decoração de plástico"),
    (("vela decorativa", "vela aromatica"), "34060000", "vela"),
    (("flor artificial", "flores artificiais"), "67021000", "flor artificial"),
    (("relogio de parede",), "91052100", "relógio de parede"),
    (("almofada",), "94049000", "almofada"),
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
    (("carvao de coco", "carvao narguile"), "44029000", "carvão para narguilé"),
    (("papel aluminio", "aluminio"), "76071990", "papel alumínio"),
    (("fumo para enrolar", "tabaco para enrolar"), "24031990", "fumo para enrolar"),
    (("essencia", "narguile", "fumo"), "24031100", "tabaco para narguilé"),
    (("piteira",), "48139000", "piteira de papel"),
    (("seda", "papel de enrolar"), "48131000", "papel para cigarro (seda)"),
    (("clipper", "isqueiro recarregavel"), "96132000", "isqueiro recarregável"),
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
