"""IA no caixa: pede à nuvem (que guarda a chave da API e confere se a loja contratou) e devolve sugestões.

Nada aqui grava no banco: o resultado vai para as prévias de cadastro, onde o lojista confere e confirma.
"""
from __future__ import annotations

import base64
from pathlib import Path

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

TIPOS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
LIMITE_FOTO = 5 * 1024 * 1024
LIMITE_NOMES = 200


def configurado(banco) -> bool:
    return bool((banco.cfg("api_url") or "").strip()) and bool((banco.cfg("api_token") or "").strip())


def _chamar(banco, metodo: str, rota: str, corpo: dict | None = None, http=None, timeout=(5, 120)) -> dict:
    if not configurado(banco):
        raise ErroNegocio("A IA precisa da nuvem configurada neste caixa (endereço e token da loja).")
    from src.sync.painel_envio import _base_nuvem
    if http is None:
        import requests as http
    url = f"{_base_nuvem(banco.cfg('api_url'))}{rota}"
    from src.core.endereco_nuvem import autorizar
    cabecalho = autorizar(url, banco.cfg("api_token"))
    if cabecalho is None:
        raise ErroNegocio("O endereço da nuvem precisa ser HTTPS para usar a IA.")
    try:
        if metodo == "GET":
            r = http.get(url, headers=cabecalho, timeout=timeout)
        else:
            r = http.post(url, json=corpo, headers=cabecalho, timeout=timeout)
    except OSError as e:
        raise ErroNegocio("Sem conexão com a nuvem para usar a IA.") from e
    if r.status_code == 404:
        raise ErroNegocio("A nuvem ainda não tem a IA. Atualize e tente de novo mais tarde.")
    try:
        dados = r.json()
    except ValueError:
        dados = {}
    if r.status_code != 200:
        detalhe = dados.get("detail") if isinstance(dados, dict) and isinstance(dados.get("detail"), str) else ""
        raise ErroNegocio(detalhe or f"A IA não respondeu (HTTP {r.status_code}).")
    if not isinstance(dados, dict):
        raise ErroNegocio("Resposta inválida da IA.")
    return dados


def situacao(banco, http=None) -> dict:
    """{ativa, cota_usos, usos_mes, restantes}. Sem nuvem: desligada."""
    if not configurado(banco):
        return {"ativa": False, "restantes": 0}
    return _chamar(banco, "GET", "/v1/ia/situacao", http=http, timeout=(5, 15))


def produtos_da_foto(banco, caminho, http=None) -> list[dict]:
    caminho = Path(caminho)
    tipo = TIPOS.get(caminho.suffix.lower())
    if tipo is None:
        raise ErroNegocio("Escolha uma foto JPG, PNG ou WEBP.")
    try:
        dados = caminho.read_bytes()
    except OSError as e:
        raise ErroNegocio(f"Não consegui ler a foto: {e}") from e
    if not dados or len(dados) > LIMITE_FOTO:
        raise ErroNegocio("A foto precisa ter até 5 MB.")
    r = _chamar(banco, "POST", "/v1/ia/produtos/foto",
                {"imagem_b64": base64.b64encode(dados).decode("ascii"), "tipo": tipo}, http)
    produtos = [p for p in r.get("produtos") or [] if isinstance(p, dict) and p.get("nome")]
    if not produtos:
        raise ErroNegocio("A IA não achou produtos nesta foto. Tente uma foto mais nítida e de frente.")
    return produtos


def para_tabela(produtos: list[dict]) -> list[dict]:
    """Produtos da IA no formato da planilha de importação (vai para a mesma prévia, onde o preço se corrige)."""
    tabela = []
    for n, p in enumerate(produtos, start=1):
        linha = {"_linha": n, "nome": str(p["nome"])[:50],
                 "preco": fmt.fmt_num(int(p.get("preco_cent") or 0))}
        if p.get("custo_cent"):
            linha["custo"] = fmt.fmt_num(int(p["custo_cent"]))
        if p.get("quantidade"):
            linha["quantidade"] = str(p["quantidade"]).replace(".", ",")
        for chave in ("codigo_barras", "unidade", "grupo"):
            if p.get(chave):
                linha[chave] = str(p[chave])
        tabela.append(linha)
    return tabela


def padronizar_nomes(banco, nomes: list[str], http=None) -> list[dict | None]:
    """Um resultado por nome, na mesma ordem ({nome, grupo} ou None quando a IA não soube)."""
    saida: list[dict | None] = []
    for i in range(0, len(nomes), LIMITE_NOMES):
        parte = nomes[i:i + LIMITE_NOMES]
        r = _chamar(banco, "POST", "/v1/ia/produtos/nomes", {"itens": [{"nome": n} for n in parte]}, http)
        itens = r.get("itens") if isinstance(r.get("itens"), list) else []
        for j in range(len(parte)):
            it = itens[j] if j < len(itens) else None
            saida.append({"nome": str(it["nome"])[:50], "grupo": str(it.get("grupo") or "")}
                         if isinstance(it, dict) and it.get("nome") else None)
    return saida
