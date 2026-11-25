"""IA nos caixas (recurso pago, ligado por loja na central do fornecedor).

- A chave da API da Anthropic fica só aqui na nuvem (variável ANTHROPIC_API_KEY); o caixa nunca a vê.
- Cada loja tem `ativa` (desligada por padrão) e uma cota de usos por mês; o custo de cada chamada é guardado para o
  fornecedor saber quanto cobrar.
- O que a IA faz hoje: ler foto de nota, lista ou prateleira e devolver produtos para cadastro; padronizar nomes de
  produtos (os da NF-e de compra chegam abreviados). Ela só sugere: o caixa mostra a prévia e o lojista confirma.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db

URL_API = "https://api.anthropic.com/v1/messages"
MODELO_PADRAO = "claude-haiku-5-5"
COTA_PADRAO = 300
LIMITE_IMAGEM = 5 * 1024 * 1024
LIMITE_NOMES = 200
TIPOS_IMAGEM = {"image/jpeg", "image/png", "image/webp", "image/gif"}
# Preço por token em nanodólares (US$ por milhão de tokens x 1000), entrada e saída.
PRECOS = {"claude-haiku-5-5": (100, 500), "claude-sonnet-5-5": (2000, 10000), "claude-opus-5-5": (4000, 20000)}


class IaLoja(Base):
    __tablename__ = "ia_lojas"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, unique=True, index=True, nullable=False)
    ativa = Column(Boolean, nullable=False, default=False)
    cota_usos = Column(Integer, nullable=False, default=COTA_PADRAO)
    mes = Column(String, nullable=False, default="")
    usos_mes = Column(Integer, nullable=False, default=0)
    custo_mes_nano = Column(Integer, nullable=False, default=0)
    atualizado_em = Column(String)


class IaUso(Base):
    __tablename__ = "ia_usos"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    quando = Column(String, nullable=False)
    acao = Column(String, nullable=False)
    modelo = Column(String, nullable=False)
    tokens_entrada = Column(Integer, nullable=False, default=0)
    tokens_saida = Column(Integer, nullable=False, default=0)
    custo_nano = Column(Integer, nullable=False, default=0)
    ok = Column(Boolean, nullable=False, default=True)


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _registro(db: Session, chave_loja: str) -> IaLoja:
    linha = db.query(IaLoja).filter_by(chave_loja=chave_loja).first()
    if linha is None:
        linha = IaLoja(chave_loja=chave_loja, ativa=False, cota_usos=COTA_PADRAO, mes="", usos_mes=0,
                       custo_mes_nano=0)
        db.add(linha)
        db.flush()
    mes = datetime.now().strftime("%Y-%m")
    if linha.mes != mes:
        linha.mes, linha.usos_mes, linha.custo_mes_nano = mes, 0, 0
    return linha


def situacao(db: Session, chave_loja: str) -> dict:
    r = _registro(db, chave_loja)
    return {"ativa": bool(r.ativa), "cota_usos": r.cota_usos, "usos_mes": r.usos_mes,
            "restantes": max(0, r.cota_usos - r.usos_mes), "custo_mes_usd": round(r.custo_mes_nano / 1e9, 4),
            "configurada": bool(os.environ.get("ANTHROPIC_API_KEY"))}


def _liberar(db: Session, chave_loja: str) -> IaLoja:
    r = _registro(db, chave_loja)
    if not r.ativa:
        raise HTTPException(status_code=403, detail="A IA não está contratada nesta loja. Fale com o fornecedor "
                                                    "do sistema para ativar.")
    if r.usos_mes >= r.cota_usos:
        raise HTTPException(status_code=429, detail="A cota de IA deste mês acabou. Fale com o fornecedor para "
                                                    "aumentar.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503, detail="A IA ainda não foi configurada na nuvem.")
    return r


def custo_nano(modelo: str, entrada: int, saida: int) -> int:
    preco_in, preco_out = PRECOS.get(modelo, PRECOS["claude-sonnet-5-5"])
    return int(entrada) * preco_in + int(saida) * preco_out


def chamar_claude(conteudo: list, ferramenta: dict, sistema: str, max_tokens: int = 4096, abrir=urlopen) -> tuple:
    """Uma chamada à API com saída forçada numa ferramenta (JSON validado pelo esquema). Devolve (dados, uso)."""
    modelo = os.environ.get("IA_MODELO") or MODELO_PADRAO
    corpo = {"model": modelo, "max_tokens": max_tokens, "system": sistema, "tools": [ferramenta],
             "tool_choice": {"type": "tool", "name": ferramenta["name"]},
             "messages": [{"role": "user", "content": conteudo}]}
    pedido = Request(URL_API, data=json.dumps(corpo).encode("utf-8"), method="POST", headers={
        "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""), "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    try:
        with abrir(pedido, timeout=90) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
    except HTTPError as e:
        raise HTTPException(status_code=502, detail=f"A IA respondeu com erro ({e.code}). Tente de novo.") from None
    except (URLError, OSError, ValueError):
        raise HTTPException(status_code=502, detail="Sem resposta da IA agora. Tente de novo.") from None
    uso = dados.get("usage") or {}
    entrada = int(uso.get("input_tokens") or 0) + int(uso.get("cache_read_input_tokens") or 0) \
        + int(uso.get("cache_creation_input_tokens") or 0)
    saida = int(uso.get("output_tokens") or 0)
    for bloco in dados.get("content") or []:
        if bloco.get("type") == "tool_use" and bloco.get("name") == ferramenta["name"]:
            return bloco.get("input") or {}, (modelo, entrada, saida)
    return {}, (modelo, entrada, saida)


def _anotar(db: Session, registro: IaLoja, acao: str, uso: tuple, ok: bool) -> None:
    modelo, entrada, saida = uso
    custo = custo_nano(modelo, entrada, saida)
    registro.usos_mes += 1
    registro.custo_mes_nano += custo
    registro.atualizado_em = _agora()
    db.add(IaUso(chave_loja=registro.chave_loja, quando=_agora(), acao=acao, modelo=modelo,
                 tokens_entrada=entrada, tokens_saida=saida, custo_nano=custo, ok=ok))
    db.commit()


# ------------------------------------------------------------ o que a IA faz
SISTEMA_CADASTRO = (
    "Você ajuda a cadastrar produtos num PDV de bar, adega e restaurante no Brasil. Leia somente o que aparece na "
    "imagem; não invente produto, preço nem código de barras. Nomes em português, claros e completos, com tipo, "
    "marca, variação e volume (ex.: 'Cerveja Heineken Long Neck 330ml', 'Vodka Smirnoff 998ml'). Preço em centavos "
    "inteiros (R$ 12,50 = 1250); se a imagem for nota de compra, o valor é custo, não preço de venda. Sem um dado, "
    "deixe o campo vazio ou zero.")

FERRAMENTA_PRODUTOS = {
    "name": "produtos",
    "description": "Produtos lidos na imagem.",
    "input_schema": {"type": "object", "properties": {
        "tipo_imagem": {"type": "string", "enum": ["nota_compra", "lista_precos", "prateleira", "outro"]},
        "produtos": {"type": "array", "maxItems": 300, "items": {"type": "object", "properties": {
            "nome": {"type": "string"},
            "preco_cent": {"type": "integer", "description": "Preço de venda em centavos (0 se não houver)."},
            "custo_cent": {"type": "integer", "description": "Custo unitário em centavos (0 se não houver)."},
            "quantidade": {"type": "number", "description": "Quantidade (0 se não houver)."},
            "codigo_barras": {"type": "string"},
            "unidade": {"type": "string", "description": "UN, CX, KG, LT, FD..."},
            "grupo": {"type": "string", "description": "Cerveja, Destilado, Vinho, Refrigerante, Água, "
                                                      "Energético, Tabacaria, Petisco, Outros..."},
        }, "required": ["nome"]}},
    }, "required": ["produtos"]},
}

SISTEMA_NOMES = (
    "Você padroniza nomes de produtos de bar e adega no Brasil, vindos de notas fiscais de compra (abreviados, em "
    "maiúsculas). Devolva, na mesma ordem e com o mesmo índice, um nome claro e completo em português com tipo, "
    "marca, variação e volume, sem inventar o que não dá para deduzir (ex.: 'CERV HEINEKEN LN 330ML CX12' -> "
    "'Cerveja Heineken Long Neck 330ml'). Sugira também o grupo.")

FERRAMENTA_NOMES = {
    "name": "nomes",
    "description": "Nomes padronizados, um por item recebido.",
    "input_schema": {"type": "object", "properties": {"itens": {"type": "array", "items": {
        "type": "object", "properties": {"indice": {"type": "integer"}, "nome": {"type": "string"},
                                         "grupo": {"type": "string"}},
        "required": ["indice", "nome"]}}}, "required": ["itens"]},
}


def _texto(v, limite: int = 120) -> str:
    return " ".join(str(v or "").split())[:limite]


def _inteiro(v) -> int:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return 0
    return n if 0 <= n <= 100_000_000 else 0


def limpar_produtos(dados: dict) -> list[dict]:
    saida = []
    for p in (dados.get("produtos") or [])[:300]:
        if not isinstance(p, dict) or not _texto(p.get("nome")):
            continue
        try:
            qtd = max(0.0, min(float(p.get("quantidade") or 0), 1_000_000.0))
        except (TypeError, ValueError):
            qtd = 0.0
        barras = "".join(c for c in str(p.get("codigo_barras") or "") if c.isdigit())
        saida.append({"nome": _texto(p.get("nome")), "preco_cent": _inteiro(p.get("preco_cent")),
                      "custo_cent": _inteiro(p.get("custo_cent")), "quantidade": round(qtd, 4),
                      "codigo_barras": barras if len(barras) in (8, 12, 13, 14) else "",
                      "unidade": _texto(p.get("unidade"), 6).upper(), "grupo": _texto(p.get("grupo"), 40)})
    return saida


def ler_foto(db: Session, chave_loja: str, dados: dict) -> dict:
    """Foto (nota de compra, lista de preços ou prateleira) -> produtos para cadastro. Usada pelo caixa e pela
    retaguarda; conta na cota da loja."""
    tipo = str(dados.get("tipo") or "")
    if tipo not in TIPOS_IMAGEM:
        raise HTTPException(status_code=422, detail="Envie uma foto JPG, PNG ou WEBP.")
    try:
        imagem = base64.b64decode(str(dados.get("imagem_b64") or ""), validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="Foto inválida.") from None
    if not imagem or len(imagem) > LIMITE_IMAGEM:
        raise HTTPException(status_code=422, detail="A foto precisa ter até 5 MB.")
    registro = _liberar(db, chave_loja)
    conteudo = [{"type": "image", "source": {"type": "base64", "media_type": tipo,
                                             "data": base64.b64encode(imagem).decode("ascii")}},
                {"type": "text", "text": "Liste os produtos desta imagem para cadastro."}]
    try:
        resultado, uso = chamar_claude(conteudo, FERRAMENTA_PRODUTOS, SISTEMA_CADASTRO, 8192)
    except HTTPException:
        db.rollback()
        raise
    produtos = limpar_produtos(resultado)
    _anotar(db, registro, "produtos_foto", uso, bool(produtos))
    return {"tipo_imagem": str(resultado.get("tipo_imagem") or "outro"), "produtos": produtos}


def padronizar_nomes(db: Session, chave_loja: str, dados: dict) -> dict:
    """Nomes abreviados (da NF-e ou do cadastro) -> nomes claros e grupo, na mesma ordem. Conta na cota da loja."""
    itens = dados.get("itens")
    if not isinstance(itens, list) or not 0 < len(itens) <= LIMITE_NOMES:
        raise HTTPException(status_code=422, detail=f"Envie de 1 a {LIMITE_NOMES} nomes.")
    linhas = [f"{i}. {_texto(it.get('nome') if isinstance(it, dict) else it, 150)}"
              for i, it in enumerate(itens)]
    registro = _liberar(db, chave_loja)
    try:
        resultado, uso = chamar_claude([{"type": "text", "text": "\n".join(linhas)}], FERRAMENTA_NOMES,
                                       SISTEMA_NOMES, 8192)
    except HTTPException:
        db.rollback()
        raise
    saida = [None] * len(itens)
    for it in resultado.get("itens") or []:
        if isinstance(it, dict) and isinstance(it.get("indice"), int) and 0 <= it["indice"] < len(itens) \
                and _texto(it.get("nome")):
            saida[it["indice"]] = {"nome": _texto(it.get("nome")), "grupo": _texto(it.get("grupo"), 40)}
    _anotar(db, registro, "produtos_nomes", uso, any(saida))
    return {"itens": saida}


def _reais(cent: int) -> str:
    return f"{cent / 100:.2f}".replace(".", ",") if cent else ""


def linhas_para_importar(produtos: list[dict]) -> list[dict]:
    """Produtos lidos pela IA -> linhas no formato da importação do caixa (as mesmas colunas da planilha)."""
    return [{"nome": p["nome"], "preco": _reais(p["preco_cent"]), "custo": _reais(p["custo_cent"]),
             "quantidade": (str(p["quantidade"]).rstrip("0").rstrip(".").replace(".", ",") if p["quantidade"] else ""),
             "grupo": p["grupo"], "unidade": p["unidade"], "codigo_barras": p["codigo_barras"]} for p in produtos]


def instalar(app: FastAPI, autenticar) -> APIRouter:
    Base.metadata.create_all(bind=engine)
    router = APIRouter()

    def loja_do_caixa(acesso=Depends(autenticar)) -> str:
        if acesso.admin:
            raise HTTPException(status_code=403, detail="Use o token da loja.")
        return acesso.loja

    @router.get("/v1/ia/situacao")
    def ver(chave_loja: str = Depends(loja_do_caixa), db: Session = Depends(get_db)):
        dados = situacao(db, chave_loja)
        db.commit()
        dados.pop("custo_mes_usd")                  # custo é assunto do fornecedor
        return dados

    @router.post("/v1/ia/produtos/foto")
    def foto(dados: dict = Body(...), chave_loja: str = Depends(loja_do_caixa), db: Session = Depends(get_db)):
        return ler_foto(db, chave_loja, dados)

    @router.post("/v1/ia/produtos/nomes")
    def nomes(dados: dict = Body(...), chave_loja: str = Depends(loja_do_caixa), db: Session = Depends(get_db)):
        return padronizar_nomes(db, chave_loja, dados)

    app.include_router(router)
    return router


def instalar_fornecedor(app: FastAPI, sessao, obter, auditar) -> APIRouter:
    """Central: liga/desliga a IA da loja, define a cota e vê uso e custo do mês."""
    router = APIRouter()

    @router.get("/v1/fornecedor/lojas/{chave}/ia")
    def ver_loja(chave: str, _=Depends(sessao), db: Session = Depends(get_db)):
        loja = obter(db, chave).chave_loja
        dados = situacao(db, loja)
        db.commit()
        return dados

    @router.post("/v1/fornecedor/lojas/{chave}/ia")
    def ajustar(chave: str, dados: dict = Body(...), _=Depends(sessao), db: Session = Depends(get_db)):
        loja = obter(db, chave).chave_loja
        r = _registro(db, loja)
        if "ativa" in dados:
            if not isinstance(dados["ativa"], bool):
                raise HTTPException(status_code=422, detail="ativa deve ser verdadeiro ou falso.")
            r.ativa = dados["ativa"]
        if "cota_usos" in dados:
            cota = dados["cota_usos"]
            if type(cota) is not int or not 0 <= cota <= 100_000:
                raise HTTPException(status_code=422, detail="Cota de 0 a 100000 usos por mês.")
            r.cota_usos = cota
        r.atualizado_em = _agora()
        auditar(db, "ia_loja", loja, f"ativa={r.ativa} cota={r.cota_usos}")
        db.commit()
        return situacao(db, loja)

    @router.get("/v1/fornecedor/ia/uso")
    def uso_geral(_=Depends(sessao), db: Session = Depends(get_db)):
        mes = datetime.now().strftime("%Y-%m")
        linhas = db.query(IaLoja).order_by(IaLoja.chave_loja).all()
        return {"mes": mes, "lojas": [{"chave_loja": l.chave_loja, "ativa": bool(l.ativa), "cota_usos": l.cota_usos,
                                       "usos_mes": l.usos_mes if l.mes == mes else 0,
                                       "custo_mes_usd": round((l.custo_mes_nano if l.mes == mes else 0) / 1e9, 4)}
                                      for l in linhas]}

    app.include_router(router)
    return router
