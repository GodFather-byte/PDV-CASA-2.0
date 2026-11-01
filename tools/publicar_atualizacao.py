"""Assina o instalador e registra na nuvem.

    python -m tools.publicar_atualizacao instalador.exe --edicao willpdv --notas "Corrige o troco." \\
        --url https://atualizacoes.exemplo/willpdv/1.10.1/WillPDV-Instalador.exe

A semente fica em PDV_ATUALIZACAO_CHAVE (64 hex). Se PDV_NUVEM_URL e PDV_API_TOKEN existirem,
o manifesto é enviado a POST /v1/admin/atualizacao. Sem a semente, só mostra o SHA-256 e sai 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request

from src.atualizacao.manifesto import assinar
from src.versao import VERSAO


def sha256_arquivo(caminho: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    tamanho = 0
    with open(caminho, "rb") as arquivo:
        while True:
            bloco = arquivo.read(1024 * 1024)
            if not bloco:
                break
            tamanho += len(bloco)
            digest.update(bloco)
    return digest.hexdigest(), tamanho


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.publicar_atualizacao")
    parser.add_argument("arquivo")
    parser.add_argument("--edicao", required=True, choices=("willpdv", "ea_superacoes", "bar"))
    parser.add_argument("--canal", default="estavel")
    parser.add_argument("--versao", default=VERSAO)
    parser.add_argument("--notas", required=True)
    parser.add_argument("--url", default="")
    parser.add_argument("--obrigatoria", action="store_true")
    parser.add_argument("--minima", default="")
    args = parser.parse_args(argv)
    sha, tamanho = sha256_arquivo(args.arquivo)
    semente = (os.environ.get("PDV_ATUALIZACAO_CHAVE") or "").strip()
    print(f"edicao={args.edicao} versao={args.versao} tamanho={tamanho}")
    print(f"sha256={sha}")
    if len(semente) != 64:
        print("PDV_ATUALIZACAO_CHAVE ausente: manifesto não assinado. Guarde a semente e rode de novo.")
        return 0
    pacote = {
        "edicao": args.edicao, "canal": args.canal, "versao": args.versao, "sha256": sha, "tamanho": tamanho,
        "url": args.url, "notas": args.notas, "obrigatoria": 1 if args.obrigatoria else 0, "minima": args.minima,
    }
    pacote["assinatura"] = assinar(bytes.fromhex(semente), pacote)
    destino = os.environ.get("PDV_NUVEM_URL", "").rstrip("/")
    token = os.environ.get("PDV_API_TOKEN", "").strip()
    if not destino or not token or not args.url:
        print(json.dumps(pacote, ensure_ascii=False, indent=2))
        print("Sem PDV_NUVEM_URL, PDV_API_TOKEN ou --url: nada foi publicado.")
        return 0
    pedido = urllib.request.Request(
        destino + "/v1/admin/atualizacao", data=json.dumps(pacote).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(pedido, timeout=30) as resposta:
        print(resposta.read().decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
