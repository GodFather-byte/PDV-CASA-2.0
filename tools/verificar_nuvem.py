"""Confere o commit realmente servido pela nuvem após o deploy. Somente consultas públicas."""
import argparse
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def aguardar(url: str, commit: str, timeout: int = 300, intervalo: int = 5,
             abrir=urllib.request.urlopen, dormir=time.sleep, relogio=time.monotonic) -> bool:
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
            if isinstance(dados, dict) and dados.get("commit") == commit:
                return True
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
    try:
        ok = aguardar(args.url, args.commit, args.timeout)
    except ValueError as erro:
        parser.error(str(erro))
    print("Publicação confirmada: a nuvem serve o commit esperado." if ok else
          "Publicação não confirmada. Confira o deploy automático no Render ou configure o Deploy Hook no GitHub.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
