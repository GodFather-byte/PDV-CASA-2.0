"""Produtos prontos: um catálogo com o que mais se vende numa adega em São Paulo, para cadastrar a loja em minutos.

Cada item traz o nome padronizado, o subgrupo (os mesmos do perfil Adega) e o NCM. Não traz preço, porque cada loja cobra
o seu, nem código de barras: um número errado faria o leitor puxar o produto errado no caixa. O código de barras entra
depois, passando o produto no leitor (`vincular_codigo_barras`).

O NCM é o mais comum para cada tipo de produto. Quem emite nota confere com o contador.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.controllers.cadastro_controller import CadastroController
from src.controllers.importacao_produtos import ImportacaoProdutos, Previa
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroValidacao
from src.fiscal import ncm as ncm_mod


@dataclass(frozen=True)
class ItemCatalogo:
    nome: str
    subgrupo: str
    ncm: str


# NCM por tipo de produto (TIPI). Exceções (cerveja sem álcool, ice etc.) vão no próprio item.
CERVEJA, SEM_ALCOOL, REFRI, AGUA, NAO_ALCOOLICA = "22030000", "22029100", "22021000", "22011000", "22029900"
VODKA, UISQUE, GIN, CACHACA_RUM, CONHAQUE, LICOR = "22086000", "22083020", "22085000", "22084000", "22082000", "22087000"
OUTRAS_DESTILADAS, VINHO, ESPUMANTE, VERMUTE = "22089000", "22042100", "22041090", "22051000"
GELO, CARVAO, CIGARRO, NARGUILE, SEDA, ISQUEIRO = "22019000", "44029000", "24022000", "24031100", "48131000", "96131000"
CHIPS, SALGADINHO, AMENDOIM, CHICLETE, BALA, COPO = "20052000", "19041000", "20081100", "17041000", "17049020", "39241000"

LATA269, LATA350, LATAO, LONG330, LONG355, GARRAFA600, LITRAO = (
    "LATA 269ML", "LATA 350ML", "LATAO 473ML", "LONG NECK 330ML", "LONG NECK 355ML", "600ML", "LITRAO 1L")

# marca -> embalagens (as que de fato se encontram nas distribuidoras de São Paulo)
_CERVEJAS = (
    ("SKOL", (LATA269, LATA350, LATAO, GARRAFA600, LITRAO)),
    ("BRAHMA CHOPP", (LATA269, LATA350, LATAO, GARRAFA600, LITRAO)),
    ("BRAHMA DUPLO MALTE", (LATA350, LATAO, GARRAFA600)),
    ("ANTARCTICA PILSEN", (LATA269, LATA350, LATAO, GARRAFA600, LITRAO)),
    ("ANTARCTICA ORIGINAL", (LATA269, LATA350, GARRAFA600)),
    ("ITAIPAVA", (LATA269, LATA350, LATAO, GARRAFA600)),
    ("HEINEKEN", (LATA269, LATA350, LONG330, GARRAFA600)),
    ("AMSTEL", (LATA269, LATA350, LATAO, GARRAFA600)),
    ("BUDWEISER", (LATA269, LATA350, LATAO, LONG330, GARRAFA600)),
    ("STELLA ARTOIS", (LATA269, LATA350, LONG330)),
    ("CORONA", (LATA350, LONG330)),
    ("SPATEN", (LATA350, LONG355, GARRAFA600)),
    ("EISENBAHN", (LATA350, LONG355)),
    ("DEVASSA", (LATA350, LATAO, GARRAFA600)),
    ("PETRA", (LATA350, LATAO)),
    ("CRYSTAL", (LATA350, LATAO)),
    ("IMPERIO", (LATA269, LATA350, GARRAFA600)),
    ("BOHEMIA", (LATA350, GARRAFA600)),
    ("MICHELOB ULTRA", (LATA350, LONG330)),
)

# (subgrupo, NCM padrão, itens). Um item é só o nome ou (nome, NCM) quando foge do padrão do subgrupo.
_SECOES = (
    ("CERVEJAS", SEM_ALCOOL, ("CERVEJA HEINEKEN 0.0 LATA 350ML", "CERVEJA BRAHMA 0.0 LATA 350ML",
                              "CERVEJA BUDWEISER ZERO LATA 350ML")),
    ("DESTILADOS", VODKA, ("VODKA SMIRNOFF 998ML", "VODKA SMIRNOFF 600ML", "VODKA ABSOLUT 1L", "VODKA ORLOFF 1L",
                           "VODKA ASKOV 900ML", "VODKA SKYY 980ML", "VODKA NATASHA 1L", "VODKA KETEL ONE 1L")),
    ("DESTILADOS", UISQUE, ("WHISKY JOHNNIE WALKER RED LABEL 1L", "WHISKY JOHNNIE WALKER RED LABEL 500ML",
                            "WHISKY JOHNNIE WALKER BLACK LABEL 1L", "WHISKY JACK DANIELS 1L",
                            "WHISKY JACK DANIELS HONEY 1L", "WHISKY CHIVAS REGAL 12 ANOS 1L", "WHISKY BALLANTINES 1L",
                            "WHISKY WHITE HORSE 1L", "WHISKY OLD PARR 12 ANOS 1L", "WHISKY PASSPORT 1L",
                            "WHISKY BUCHANANS 12 ANOS 1L", "WHISKY JAMESON 750ML", "WHISKY TEACHERS 1L")),
    ("DESTILADOS", GIN, ("GIN TANQUERAY 750ML", "GIN GORDONS 750ML", "GIN BEEFEATER 750ML",
                         "GIN BOMBAY SAPPHIRE 750ML", "GIN SEAGERS 980ML", "GIN ROCKS 1L")),
    ("DESTILADOS", CACHACA_RUM, ("CACHACA 51 965ML", "CACHACA YPIOCA PRATA 965ML", "CACHACA VELHO BARREIRO 910ML",
                                 "CACHACA PITU 965ML", "CACHACA SELETA 1L", "CACHACA SAGATIBA 700ML",
                                 "RUM BACARDI CARTA BLANCA 980ML", "RUM MONTILLA CARTA BRANCA 1L")),
    ("DESTILADOS", OUTRAS_DESTILADAS, ("TEQUILA JOSE CUERVO ESPECIAL OURO 750ML", "TEQUILA JOSE CUERVO PRATA 750ML",
                                       "CAMPARI 998ML", "APEROL 750ML", "CATUABA SELVAGEM 900ML",
                                       "COROTE LIMAO 500ML", "COROTE MORANGO 500ML", "COROTE BLUEBERRY 500ML",
                                       "SMIRNOFF ICE LIMAO 275ML", "SKOL BEATS SENSES LATA 269ML",
                                       "SKOL BEATS GT LATA 269ML", "XEQUE MATE LATA 355ML",
                                       ("CONHAQUE DREHER 900ML", CONHAQUE), ("CONHAQUE DOMECQ 1L", CONHAQUE),
                                       ("LICOR AMARULA 750ML", LICOR), ("LICOR JAGERMEISTER 700ML", LICOR),
                                       ("LICOR BAILEYS 750ML", LICOR), ("VERMUTE MARTINI BIANCO 750ML", VERMUTE))),
    ("VINHOS E ESPUMANTES", VINHO, ("VINHO PERGOLA TINTO SUAVE 1L", "VINHO PERGOLA TINTO SECO 1L",
                                    "VINHO SANGUE DE BOI TINTO SUAVE 1L", "VINHO QUINTA DO MORGADO TINTO SUAVE 750ML",
                                    "VINHO CASILLERO DEL DIABLO CABERNET 750ML",
                                    "VINHO CONCHA Y TORO RESERVADO CABERNET 750ML",
                                    "VINHO SANTA HELENA RESERVADO CABERNET 750ML",
                                    ("ESPUMANTE CHANDON BRUT 750ML", ESPUMANTE), ("ESPUMANTE SALTON BRUT 750ML", ESPUMANTE),
                                    ("ESPUMANTE SALTON MOSCATEL 750ML", ESPUMANTE))),
    ("REFRIGERANTES", REFRI, ("REFRIGERANTE COCA-COLA LATA 350ML", "REFRIGERANTE COCA-COLA ZERO LATA 350ML",
                              "REFRIGERANTE COCA-COLA 600ML", "REFRIGERANTE COCA-COLA 1L",
                              "REFRIGERANTE COCA-COLA 2L", "REFRIGERANTE COCA-COLA ZERO 2L",
                              "REFRIGERANTE GUARANA ANTARCTICA LATA 350ML", "REFRIGERANTE GUARANA ANTARCTICA ZERO LATA 350ML",
                              "REFRIGERANTE GUARANA ANTARCTICA 600ML", "REFRIGERANTE GUARANA ANTARCTICA 2L",
                              "REFRIGERANTE FANTA LARANJA LATA 350ML", "REFRIGERANTE FANTA LARANJA 2L",
                              "REFRIGERANTE FANTA UVA LATA 350ML", "REFRIGERANTE FANTA UVA 2L",
                              "REFRIGERANTE SPRITE LATA 350ML", "REFRIGERANTE SPRITE 2L",
                              "REFRIGERANTE PEPSI LATA 350ML", "REFRIGERANTE PEPSI 2L",
                              "REFRIGERANTE SODA ANTARCTICA LATA 350ML", "REFRIGERANTE KUAT 2L",
                              "REFRIGERANTE DOLLY GUARANA 2L", "REFRIGERANTE TUBAINA 2L",
                              "AGUA TONICA SCHWEPPES LATA 350ML", "SCHWEPPES CITRUS LATA 350ML",
                              "H2OH LIMAO 500ML")),
    ("ÁGUAS E SUCOS", AGUA, ("AGUA MINERAL SEM GAS 500ML", "AGUA MINERAL COM GAS 500ML", "AGUA MINERAL SEM GAS 1,5L",
                             "AGUA MINERAL GALAO 5L")),
    ("ÁGUAS E SUCOS", NAO_ALCOOLICA, ("SUCO DEL VALLE UVA LATA 290ML", "SUCO DEL VALLE PESSEGO LATA 290ML",
                                      "SUCO DEL VALLE MARACUJA LATA 290ML", "SUCO DEL VALLE UVA 1L",
                                      "ISOTONICO GATORADE LIMAO 500ML", "ISOTONICO GATORADE LARANJA 500ML",
                                      "ISOTONICO GATORADE MORANGO MARACUJA 500ML", "ISOTONICO POWERADE 500ML")),
    ("ENERGÉTICOS", NAO_ALCOOLICA, ("ENERGETICO RED BULL 250ML", "ENERGETICO RED BULL SUGARFREE 250ML",
                                    "ENERGETICO RED BULL TROPICAL 250ML", "ENERGETICO RED BULL 473ML",
                                    "ENERGETICO MONSTER ENERGY 473ML", "ENERGETICO MONSTER MANGO LOCO 473ML",
                                    "ENERGETICO MONSTER ULTRA 473ML", "ENERGETICO TNT LATA 269ML",
                                    "ENERGETICO TNT LATA 473ML", "ENERGETICO BALY 2L", "ENERGETICO BALY LATA 473ML",
                                    "ENERGETICO FUSION 2L", "ENERGETICO FLYING HORSE 2L")),
    ("GELO E CARVÃO", GELO, ("GELO EM CUBO 2KG", "GELO EM CUBO 5KG", "GELO EM CUBO 10KG",
                             ("CARVAO VEGETAL 2KG", CARVAO), ("CARVAO VEGETAL 3KG", CARVAO),
                             ("CARVAO VEGETAL 5KG", CARVAO))),
    ("TABACARIA", CIGARRO, ("CIGARRO MARLBORO VERMELHO BOX", "CIGARRO MARLBORO GOLD BOX", "CIGARRO LUCKY STRIKE BOX",
                            "CIGARRO DUNHILL BOX", "CIGARRO ROTHMANS BOX", "CIGARRO KENT BOX", "CIGARRO CAMEL BOX",
                            "CIGARRO WINSTON BOX", "CIGARRO DERBY BOX", "CIGARRO EIGHT BOX", "CIGARRO CHESTERFIELD BOX",
                            ("SEDA SMOKING", SEDA), ("SEDA ZOMO", SEDA), ("ISQUEIRO BIC", ISQUEIRO),
                            ("ESSENCIA NARGUILE ZIGGY 50G", NARGUILE), ("CARVAO DE COCO NARGUILE 1KG", CARVAO))),
    ("PETISCOS", AMENDOIM, ("AMENDOIM JAPONES 150G", "AMENDOIM SALGADO 150G",
                            ("BATATA RUFFLES ORIGINAL 57G", CHIPS), ("BATATA PRINGLES ORIGINAL 109G", CHIPS),
                            ("SALGADINHO DORITOS 55G", SALGADINHO), ("SALGADINHO CHEETOS 51G", SALGADINHO),
                            ("SALGADINHO FANDANGOS 59G", SALGADINHO), ("SALGADINHO TORCIDA 70G", SALGADINHO),
                            ("CHICLETE TRIDENT", CHICLETE), ("BALA HALLS", BALA))),
    ("DESCARTÁVEIS", COPO, ("COPO DESCARTAVEL 200ML 100 UNIDADES", "COPO DESCARTAVEL 300ML 100 UNIDADES",
                            "CANUDO 100 UNIDADES")),
)


def _montar() -> tuple[ItemCatalogo, ...]:
    itens = [ItemCatalogo(f"CERVEJA {marca} {emb}", "CERVEJAS", CERVEJA) for marca, embs in _CERVEJAS for emb in embs]
    for subgrupo, padrao, nomes in _SECOES:
        for item in nomes:
            nome, ncm = (item, padrao) if isinstance(item, str) else item
            itens.append(ItemCatalogo(nome, subgrupo, ncm))
    return tuple(itens)


CATALOGO_ADEGA = _montar()
# Ordem das abas/filtros na tela (a mesma do perfil Adega).
SUBGRUPOS = ("CERVEJAS", "DESTILADOS", "VINHOS E ESPUMANTES", "REFRIGERANTES", "ÁGUAS E SUCOS", "ENERGÉTICOS",
             "GELO E CARVÃO", "TABACARIA", "PETISCOS", "DESCARTÁVEIS")


class CatalogoController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id
        self.cad = CadastroController(banco)

    def itens(self, subgrupo: str | None = None, busca: str = "") -> list[dict]:
        """O catálogo com `ja_cadastrado` (mesmo nome já existe na loja), filtrado por subgrupo e por texto."""
        existentes = {r["nome"].casefold() for r in self.banco.todos("SELECT nome FROM produtos")}
        termos = [t for t in _sem_acento(busca).split() if t]
        saida = []
        for i, item in enumerate(CATALOGO_ADEGA):
            if subgrupo and item.subgrupo != subgrupo:
                continue
            if termos and not all(t in _sem_acento(item.nome) for t in termos):
                continue
            saida.append({"indice": i, "nome": item.nome, "subgrupo": item.subgrupo, "ncm": item.ncm,
                          "ja_cadastrado": item.nome.casefold() in existentes})
        return saida

    def adicionar(self, escolhidos: dict[int, int]) -> dict:
        """Cadastra os itens escolhidos ({índice do catálogo: preço em centavos}) numa transação só, pela mesma gravação
        da importação de planilha (numeração, subgrupo, validações). Item que a loja já tem não é mexido."""
        if not escolhidos:
            raise ErroNegocio("Marque pelo menos um produto.")
        tabela, ncms = [], {}
        for indice, preco in escolhidos.items():
            if not 0 <= indice < len(CATALOGO_ADEGA):
                raise ErroNegocio("Produto do catálogo inválido.")
            item = CATALOGO_ADEGA[indice]
            if type(preco) is not int or preco <= 0:
                raise ErroValidacao(f"Informe o preço de {item.nome}.", {"preco": "obrigatório"})
            tabela.append({"_linha": len(tabela) + 1, "nome": item.nome, "preco": fmt.fmt_num(preco),
                           "grupo": item.subgrupo, "unidade": "UN"})
            ncms[item.nome.casefold()] = item.ncm
        importacao = ImportacaoProdutos(self.banco, self.operador_id)
        previa = importacao.analisar(tabela, atualizar_existentes=False, usar_codigo_da_planilha=False, maiusculas=False)
        novos = [p for p in previa.importaveis if p.acao == "criar"]
        ja_tinha = len(tabela) - len(novos)
        if not novos:
            return {"criados": 0, "ja_tinha": ja_tinha}
        with self.banco.transacao():
            resultado = importacao.importar(Previa(novos))
            for p in novos:
                pid = self.banco.valor("SELECT id FROM produtos WHERE nome = ? COLLATE NOCASE", (p.nome,))
                if pid and ncms.get(p.nome.casefold()):
                    self.cad.salvar("produtos", {"ncm": ncms[p.nome.casefold()]}, pid)
            self.banco.log("catalogo_produtos", f"{resultado['criados']} produtos prontos cadastrados")
        return {"criados": resultado["criados"], "ja_tinha": ja_tinha}

    # ------------------------------------------------------------ código de barras
    def sem_codigo_barras(self, busca: str = "") -> list[dict]:
        """Produtos ativos ainda sem código de barras (os do catálogo entram assim), para vincular passando no leitor."""
        termos = [t for t in _sem_acento(busca).split() if t]
        linhas = self.banco.todos("SELECT id, codigo, nome FROM produtos WHERE ativo = 1 AND COALESCE(cbarra, '') = '' "
                                  "ORDER BY nome")
        return [dict(r) for r in linhas if all(t in _sem_acento(r["nome"]) for t in termos)]

    def vincular_codigo_barras(self, produto_id: int, codigo: str) -> None:
        codigo = re.sub(r"\D", "", codigo or "")
        if not 8 <= len(codigo) <= 14:
            raise ErroValidacao("Passe o produto no leitor: o código de barras tem de 8 a 14 números.",
                                {"cbarra": "inválido"})
        outro = self.banco.um("SELECT nome FROM produtos WHERE cbarra = ? AND id <> ?", (codigo, produto_id))
        if outro:
            raise ErroNegocio(f"Este código de barras já é de {outro['nome']}.")
        if self.banco.um("SELECT 1 FROM produtos WHERE id = ?", (produto_id,)) is None:
            raise ErroNegocio("Produto não encontrado.")
        self.cad.salvar("produtos", {"cbarra": codigo}, produto_id)


def _sem_acento(texto: str) -> str:
    import unicodedata
    base = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in base if not unicodedata.combining(c)).casefold()


def conferir_catalogo() -> list[str]:
    """Problemas do catálogo (usado nos testes): nome repetido, longo demais, NCM inválido ou subgrupo fora da lista."""
    problemas, vistos = [], set()
    for item in CATALOGO_ADEGA:
        if item.nome in vistos:
            problemas.append(f"repetido: {item.nome}")
        vistos.add(item.nome)
        if len(item.nome) > 50:
            problemas.append(f"nome com mais de 50 letras: {item.nome}")
        if item.subgrupo not in SUBGRUPOS:
            problemas.append(f"subgrupo desconhecido: {item.nome}")
        try:
            ncm_mod.validar(item.ncm)
        except ErroNegocio:
            problemas.append(f"NCM inválido: {item.nome}")
    return problemas
