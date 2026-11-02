"""Lista os erros do caixa que já subiram para a nuvem.

Não imprime token, senha nem o endereço com credencial. O texto já chega sem esses dados;
mesmo assim a saída passa de novo pelo filtro.

Uso, na raiz do repositório:

    python scripts/ver_erros_caixa.py --loja BOATE-CENTRO --desde 2026-11-01 --limit 20

Pela API (não coloca o token na linha de comando; leia de variável):

    PDV_API_URL=https://nuvem.exemplo PDV_API_TOKEN=... python scripts/ver_erros_caixa.py

Pelo banco, se o agente tiver a URL só no ambiente:

    PDV_NUVEM_DB_URL=postgresql://... python scripts/ver_erros_caixa.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.core.erros_caixa import limpar_texto  # noqa: E402


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Erros do caixa na nuvem, sem segredos.")
    p.add_argument("--loja", default="")
    p.add_argument("--desde", default="")
    p.add_argument("--nivel", default="")
    p.add_argument("--limit", type=int, default=50)
    return p.parse_args()


def _pela_api(args) -> list[dict] | None:
    url = (os.environ.get("PDV_API_URL") or "").strip().rstrip("/")
    token = os.environ.get("PDV_API_TOKEN") or ""
    if not url or not token:
        return None
    import requests
    resposta = requests.get(
        url + "/v1/admin/erros-caixa",
        params={"loja": args.loja, "desde": args.desde, "nivel": args.nivel, "limite": args.limit},
        headers={"Authorization": "Bearer " + token}, timeout=(5, 20))
    if resposta.status_code != 200:
        raise SystemExit(f"A nuvem respondeu HTTP {resposta.status_code}.")
    return list(resposta.json().get("erros") or [])


def _pelo_banco(args) -> list[dict]:
    from sqlalchemy import create_engine, text
    from backend.database import argumentos_engine, normalizar_url
    bruto = os.environ.get("PDV_NUVEM_DB_URL") or os.environ.get("DATABASE_URL") or ""
    if not bruto:
        raise SystemExit("Defina PDV_API_URL e PDV_API_TOKEN, ou PDV_NUVEM_DB_URL. Não cole a senha no comando.")
    url = normalizar_url(bruto)
    motor = create_engine(url, **argumentos_engine(url))
    where = ["1=1"]
    params = {"limite": max(1, min(args.limit, 200))}
    if args.loja:
        where.append("chave_loja = :loja")
        params["loja"] = args.loja
    if args.desde:
        where.append("atualizado_em >= :desde")
        params["desde"] = args.desde[:19]
    if args.nivel:
        where.append("nivel = :nivel")
        params["nivel"] = args.nivel[:20]
    sql = ("SELECT chave_loja, nivel, modulo, mensagem, traceback, contexto, vezes, criado_em, atualizado_em "
           "FROM erros_caixa WHERE " + " AND ".join(where) + " ORDER BY atualizado_em DESC LIMIT :limite")
    try:
        with motor.connect() as con:
            return [dict(r) for r in con.execute(text(sql), params).mappings()]
    except Exception:
        raise SystemExit("Não consegui ler o banco. Confira a variável no ambiente; não cole a senha no comando.") from None


def _mostrar(erros: list[dict]) -> None:
    if not erros:
        print("Nenhum erro do caixa nesse recorte.")
        return
    for erro in erros:
        print("---")
        print(f"{erro.get('atualizado_em') or erro.get('criado_em')}  {erro.get('loja')}  "
              f"{erro.get('nivel')}  x{erro.get('vezes')}  {erro.get('modulo')}")
        print(limpar_texto(str(erro.get("mensagem") or "")))
        trilha = limpar_texto(str(erro.get("traceback") or ""))
        if trilha:
            print(trilha)
        contexto = limpar_texto(str(erro.get("contexto") or ""))
        if contexto:
            print(contexto)


def main() -> None:
    args = _argumentos()
    pela_api = _pela_api(args)
    _mostrar(pela_api if pela_api is not None else _pelo_banco(args))


if __name__ == "__main__":
    main()
