"""Cardápio digital: o caixa publica o catálogo na nuvem (Configurações > Nuvem > `cardapio_digital`).

Sobe só o que o celular pode mostrar: nome, grupo, preço e as regras de promoção/happy hour.
Não sobe custo, estoque, produto inativo, fora de venda ou com "mostrar no cardápio" desmarcado.
Reenviar substitui o catálogo da loja. Se nada mudou, não chama a nuvem.
"""
from __future__ import annotations

import hashlib
import json
import logging

from src.controllers.config_controller import ConfigController
from src.core import formatacao as fmt

log = logging.getLogger("pdv.cardapio")

MAX_PRODUTOS = 2000
CHAVE_HASH = "cardapio_ultimo_hash"
CHAVE_PUBLICADO = "cardapio_publicado"
_FOTO_MAX = 300
FOTO_EMBUTIDA_MAX = 12000         # miniatura do produto (data:image/jpeg;base64,...) por item
FOTOS_EMBUTIDAS_TOTAL = 1_500_000  # soma das miniaturas num envio; o que passar segue sem foto (ou com a da categoria)


def ligado(banco) -> bool:
    return (banco.cfg_bool("cardapio_digital", False) and bool(banco.cfg("api_url").strip())
            and bool(banco.cfg("api_token").strip()))


def _base_nuvem(api_url: str) -> str:
    base = (api_url or "").strip().rstrip("/")
    if base.endswith("/v1/sincronizar"):
        base = base[: -len("/v1/sincronizar")]
    return base


def url_envio(api_url: str) -> str:
    return f"{_base_nuvem(api_url)}/v1/cardapio/envio"


def _foto(valor: str | None) -> str:
    texto = (valor or "").strip()
    if len(texto) > _FOTO_MAX or not texto.lower().startswith(("https://", "http://")):
        return ""
    return texto


def _foto_produto(origem: str | None, miniatura, orcamento: list[int]) -> str:
    """Foto do produto para o cardápio: o endereço https de onde ela veio (internet) ou a miniatura embutida (arquivo),
    dentro do orçamento total do envio. Vazio quando não há foto ou o orçamento acabou."""
    url = _foto(origem)
    if url.lower().startswith("https://"):
        return url
    if not miniatura:
        return ""
    import base64
    texto = "data:image/jpeg;base64," + base64.b64encode(bytes(miniatura)).decode("ascii")
    if len(texto) > FOTO_EMBUTIDA_MAX or len(texto) > orcamento[0]:
        return ""
    orcamento[0] -= len(texto)
    return texto


def _logo(caminho: str | None) -> str:
    """Uma miniatura do logotipo, ou vazio. Arquivo ausente ou grande demais não impede o catálogo."""
    if not (caminho or "").strip():
        return ""
    try:
        from PIL import Image
        with Image.open(caminho) as imagem:
            imagem = imagem.convert("RGB")
            imagem.thumbnail((160, 80))
            import io
            buf = io.BytesIO()
            imagem.save(buf, format="JPEG", quality=60, optimize=True)
    except (OSError, ValueError):
        return ""
    except ImportError:
        return ""
    dados = buf.getvalue()
    if len(dados) > 40000:
        return ""
    import base64
    return "data:image/jpeg;base64," + base64.b64encode(dados).decode("ascii")


def coletar(banco) -> dict:
    """O catálogo visível, já sem custo e sem estoque."""
    config = ConfigController(banco)
    produtos = []
    orcamento = [FOTOS_EMBUTIDAS_TOTAL]
    for r in banco.todos(
            """SELECT p.codigo, p.nome, p.preco_cent, p.texto_sugestao,
                      p.promo_de, p.promo_ate, p.promo_preco_cent,
                      p.sem_inicial, p.sem_final, p.sem_preco_cent,
                      p.hora_ini, p.hora_fim, p.hora_preco_cent,
                      p.preco_gelada_cent, p.promo_gelada_cent, p.sem_gelada_cent, p.hora_gelada_cent,
                      p.aceita_decimal, p.casco_produto_id,
                      g.nome AS grupo, s.nome AS subgrupo, s.figura AS foto,
                      f.origem AS foto_origem, f.miniatura AS foto_miniatura
               FROM produtos p
               JOIN subgrupos s ON s.id = p.subgrupo_id
               JOIN grupos g ON g.id = s.grupo_id
               LEFT JOIN produto_fotos f ON f.produto_id = p.id
               WHERE p.ativo = 1 AND p.venda = 1 AND p.mostrar_no_cardapio = 1
               ORDER BY g.nome, s.nome, p.nome
               LIMIT ?""", (MAX_PRODUTOS,)):
        item = {
            "nome": (r["nome"] or "").strip(),
            "grupo": (r["grupo"] or "").strip() or "Outros",
            "subgrupo": (r["subgrupo"] or "").strip() or "Geral",
            "preco_cent": int(r["preco_cent"] or 0),
            "promo_de": r["promo_de"] or "", "promo_ate": r["promo_ate"] or "",
            "promo_preco_cent": int(r["promo_preco_cent"] or 0),
            "sem_inicial": r["sem_inicial"], "sem_final": r["sem_final"],
            "sem_preco_cent": int(r["sem_preco_cent"] or 0),
            "hora_ini": r["hora_ini"] or "", "hora_fim": r["hora_fim"] or "",
            "hora_preco_cent": int(r["hora_preco_cent"] or 0),
            "preco_gelada_cent": int(r["preco_gelada_cent"] or 0),
            "promo_gelada_cent": int(r["promo_gelada_cent"] or 0),
            "sem_gelada_cent": int(r["sem_gelada_cent"] or 0),
            "hora_gelada_cent": int(r["hora_gelada_cent"] or 0),
            "fracionado": bool(r["aceita_decimal"]),
            "retornavel": bool(r["casco_produto_id"]),
        }
        codigo = (r["codigo"] or "").strip()
        if codigo.isdigit():
            item["codigo"] = str(int(codigo))              # sem os zeros da frente: é o que o pedido online devolve
        descricao = " ".join((r["texto_sugestao"] or "").split())
        if descricao:
            item["descricao"] = descricao[:240]
        foto = _foto_produto(r["foto_origem"], r["foto_miniatura"], orcamento) or _foto(r["foto"])
        if foto:
            item["foto"] = foto
        if item["nome"]:
            produtos.append(item)
    from src.core import edicao
    return {"loja_nome": config.nome_loja(), "logo": _logo(config.loja().get("logotipo")), "produtos": produtos,
            "edicao": edicao.atual().chave, "pedido": config_pedido(banco)}


def config_pedido(banco) -> dict:
    """Pedido online pelo cardápio: no Will Adega e Will Restaurante, com o pedido ligado e o WhatsApp da loja preenchido."""
    from src.core import edicao
    whatsapp = "".join(c for c in (banco.cfg("pedido_online_whatsapp", "") or "") if c.isdigit())
    if edicao.atual().chave not in {"willadega", "willrestaurante"} or not banco.cfg_bool("pedido_online", False) or not whatsapp:
        return {"ligado": False}
    if len(whatsapp) in (10, 11):
        whatsapp = "55" + whatsapp                   # DDD + número: o link do WhatsApp quer o 55 do Brasil
    try:
        minimo = fmt.para_centavos(banco.cfg("pedido_online_minimo", "0") or 0)
        padrao = fmt.para_centavos(banco.cfg("taxa_entrega_padrao", "0") or 0)
    except ValueError:
        minimo = padrao = 0
    bairros = [{"nome": r["nome"], "taxa_cent": int(r["taxa_cent"] or 0)}
               for r in banco.todos("SELECT nome, taxa_cent FROM bairros ORDER BY nome LIMIT 300")]
    return {"ligado": True, "whatsapp": whatsapp, "minimo_cent": max(0, minimo), "taxa_padrao_cent": max(0, padrao),
            "retirada": banco.cfg_bool("pedido_online_retirada", True), "bairros": bairros}


def _hash(corpo: dict) -> str:
    texto = json.dumps({"loja_nome": corpo["loja_nome"], "logo": corpo["logo"], "produtos": corpo["produtos"],
                        "pedido": corpo.get("pedido"), "edicao": corpo.get("edicao")},
                       ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def precisa_enviar(banco) -> bool:
    """Há catálogo novo (ou uma retirada) que ainda não subiu. Só olha o caixa."""
    if not banco.cfg("api_url").strip() or not banco.cfg("api_token").strip():
        return False
    if not banco.cfg_bool("cardapio_digital", False):
        return banco.cfg(CHAVE_PUBLICADO) == "S"
    if banco.cfg(CHAVE_PUBLICADO) != "S":
        return True
    return _hash(coletar(banco)) != banco.cfg(CHAVE_HASH)


def enviar(banco, http=None) -> dict | None:
    """Publica o catálogo, ou tira do ar se o cardápio foi desligado depois de publicado.
    Devolve None sem nuvem configurada. Não marca nada se a nuvem não responder 200."""
    url_api = banco.cfg("api_url").strip()
    token = banco.cfg("api_token").strip()
    if not url_api or not token:
        return None
    if http is None:
        import requests as http
    if not banco.cfg_bool("cardapio_digital", False):
        if banco.cfg(CHAVE_PUBLICADO) != "S":
            return None
        corpo = {"loja_nome": ConfigController(banco).nome_loja(), "logo": "", "produtos": [], "retirar": True}
    else:
        corpo = coletar(banco)
        digesto = _hash(corpo)
        if digesto == banco.cfg(CHAVE_HASH) and banco.cfg(CHAVE_PUBLICADO) == "S":
            return {"produtos": len(corpo["produtos"]), "enviado": False}
        corpo = {**corpo, "enviado_em": fmt.agora()}
    try:
        resposta = http.post(url_envio(url_api), json=corpo,
                             headers={"Authorization": f"Bearer {token}"}, timeout=(5, 30))
    except OSError as e:
        raise RuntimeError(f"Cardápio digital: sem conexão ({e}).") from e
    if resposta.status_code != 200:
        raise RuntimeError(f"Cardápio digital: a nuvem respondeu HTTP {resposta.status_code}.")
    if corpo.get("retirar"):
        banco.cfg_set(CHAVE_PUBLICADO, "N")
        banco.cfg_set(CHAVE_HASH, "")
        log.info("Cardápio digital retirado da nuvem.")
        return {"produtos": 0, "enviado": True, "retirado": True}
    banco.cfg_set(CHAVE_PUBLICADO, "S")
    banco.cfg_set(CHAVE_HASH, _hash(corpo))
    log.info("Cardápio digital: %d produto(s) publicado(s).", len(corpo["produtos"]))
    return {"produtos": len(corpo["produtos"]), "enviado": True}
