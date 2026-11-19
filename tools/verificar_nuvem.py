"""Confere o commit realmente servido pela nuvem após o deploy. Somente consultas públicas."""
import argparse
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def aguardar(url: str, commit: str, timeout: int = 300, intervalo: int = 5,
             abrir=urllib.request.urlopen, dormir=time.sleep, relogio=time.monotonic, vistos: list | None = None) -> bool:
    """`vistos`, quando passado, recebe os commits que a nuvem respondeu enquanto se esperava (sem repetir)."""
    partes = urlsplit(url)
    if partes.scheme != "https" or not partes.hostname or partes.username or partes.password or partes.query or partes.fragment:
        raise ValueError("Informe a URL HTTPS pública da nuvem, sem credenciais ou parâmetros.")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or timeout <= 0 or intervalo <= 0:
        raise ValueError("Commit ou limites de espera inválidos.")
    limite = relogio() + timeout
    while relogio() < limite:
        try:
            pedido = urllib.request.Request(url.rstrip("/") + "/v1/versao", headers={"Cache-Control": "no-cache"})
            with abrir(pedido, timeout=max(1, min(10, limite - relogio()))) as resposta:
                dados = json.load(resposta)
            servido = dados.get("commit") if isinstance(dados, dict) else None
            if servido == commit:
                return True
            if vistos is not None and isinstance(servido, str) and re.fullmatch(r"[0-9a-f]{7,40}", servido) \
                    and servido not in vistos:
                vistos.append(servido)
        except (OSError, ValueError, urllib.error.URLError):
            pass  # serviço pode estar acordando, reiniciando ou ainda na versão anterior
        dormir(max(0, min(intervalo, limite - relogio())))
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    vistos: list = []
    try:
        ok = aguardar(args.url, args.commit, args.timeout, vistos=vistos)
    except ValueError as erro:
        parser.error(str(erro))
    print(relato(ok, args.commit, vistos))
    return 0 if ok else 1


def relato(ok: bool, commit: str, vistos: list) -> str:
    """O que dizer ao fim da espera. Quando não confirma, diz o que a nuvem está servindo: é o que separa
    "o deploy ainda não terminou" de "o Render publicou outro commit" (repositório ligado errado ou desatualizado)."""
    if ok:
        return "Publicação confirmada: a nuvem serve o commit esperado."
    if not vistos:
        return ("Publicação não confirmada: a nuvem não respondeu em /v1/versao. "
                "Confira no Render se o serviço está no ar e se o deploy terminou.")
    return (f"Publicação não confirmada: a nuvem continua servindo o commit {vistos[-1][:7]}, e o esperado é "
            f"{commit[:7]}. Se o último deploy do Render terminou e o commit não mudou, o serviço está ligado a "
            "outro repositório ou a uma cópia desatualizada: em Render > serviço > Settings > Build & Deploy, "
            "confira o repositório e o ramo (GitHub, main).")


if __name__ == "__main__":
    raise SystemExit(main())
