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
    for r in banco.todos(
            """SELECT p.nome, p.preco_cent, p.texto_sugestao,
                      p.promo_de, p.promo_ate, p.promo_preco_cent,
                      p.sem_inicial, p.sem_final, p.sem_preco_cent,
                      p.hora_ini, p.hora_fim, p.hora_preco_cent,
                      g.nome AS grupo, s.nome AS subgrupo, s.figura AS foto
               FROM produtos p
               JOIN subgrupos s ON s.id = p.subgrupo_id
               JOIN grupos g ON g.id = s.grupo_id
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
        }
        descricao = " ".join((r["texto_sugestao"] or "").split())
        if descricao:
            item["descricao"] = descricao[:240]
        foto = _foto(r["foto"])
        if foto:
            item["foto"] = foto
        if item["nome"]:
            produtos.append(item)
    return {"loja_nome": config.nome_loja(), "logo": _logo(config.loja().get("logotipo")), "produtos": produtos}


def _hash(corpo: dict) -> str:
    texto = json.dumps({"loja_nome": corpo["loja_nome"], "logo": corpo["logo"], "produtos": corpo["produtos"]},
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
