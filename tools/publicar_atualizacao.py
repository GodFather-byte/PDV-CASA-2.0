"""Assina o instalador e registra na nuvem.

    python -m tools.publicar_atualizacao instalador.exe --edicao willpdv --notas "Corrige o troco." \\
        --url https://atualizacoes.exemplo/willpdv/1.10.1/WillPDV-Instalador.exe

A semente fica em PDV_ATUALIZACAO_CHAVE (64 hex). Se PDV_NUVEM_URL e PDV_API_TOKEN existirem,
o manifesto é enviado a POST /v1/admin/atualizacao. Sem a semente ou os dados de publicação, falha explicitamente.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request

from src.atualizacao.manifesto import assinar, conferir, EDICOES
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
    parser.add_argument("--edicao", required=True, choices=EDICOES)
    parser.add_argument("--canal", default="estavel")
    parser.add_argument("--versao", default=VERSAO)
    parser.add_argument("--notas", required=True)
    parser.add_argument("--url", default="")
    parser.add_argument("--obrigatoria", action="store_true")
    parser.add_argument("--minima", default="")
    parser.add_argument("--saida", help="Salvar também o manifesto JSON assinado para a central")
    args = parser.parse_args(argv)
    sha, tamanho = sha256_arquivo(args.arquivo)
    semente = (os.environ.get("PDV_ATUALIZACAO_CHAVE") or "").strip()
    print(f"edicao={args.edicao} versao={args.versao} tamanho={tamanho}")
    print(f"sha256={sha}")
    if len(semente) != 64:
        print("PDV_ATUALIZACAO_CHAVE ausente: manifesto não assinado. Guarde a semente e rode de novo.")
        return 1
    pacote = {
        "edicao": args.edicao, "canal": args.canal, "versao": args.versao, "sha256": sha, "tamanho": tamanho,
        "url": args.url, "notas": args.notas, "obrigatoria": 1 if args.obrigatoria else 0, "minima": args.minima,
    }
    try:
        pacote["assinatura"] = assinar(bytes.fromhex(semente), pacote)
    except ValueError:
        print("Chave de atualização inválida.")
        return 1
    if not conferir(pacote):
        print("A chave não corresponde à chave pública reconhecida pelos caixas. Nada foi publicado.")
        return 1
    destino = os.environ.get("PDV_NUVEM_URL", "").rstrip("/")
    token = os.environ.get("PDV_API_TOKEN", "").strip()
    if not destino or not token or not args.url:
        print(json.dumps(pacote, ensure_ascii=False, indent=2))
        print("Sem PDV_NUVEM_URL, PDV_API_TOKEN ou --url: nada foi publicado.")
        return 1
    # Confere o arquivo público antes de anunciar um pacote que a loja não consegue baixar.
    try:
        with urllib.request.urlopen(args.url, timeout=60) as arquivo:
            digest = hashlib.sha256()
            recebido = 0
            while bloco := arquivo.read(1024 * 1024):
                digest.update(bloco)
                recebido += len(bloco)
        if recebido != tamanho or digest.hexdigest() != sha:
            print("O instalador público difere do arquivo assinado. Nada foi publicado.")
            return 1
    except OSError:
        print("Não foi possível baixar o instalador público. Nada foi publicado.")
        return 1
    if args.saida:
        from pathlib import Path
        Path(args.saida).write_text(json.dumps(pacote, ensure_ascii=False, indent=2), encoding="utf-8")
    pedido = urllib.request.Request(
        destino + "/v1/admin/atualizacao", data=json.dumps(pacote).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(pedido, timeout=30) as resposta:
        print(resposta.read().decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
