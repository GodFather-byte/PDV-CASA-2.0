"""Consulta o indicador de operação do Asaas e sai com 1 se algo precisa de atenção.

Pensado para o agendador do GitHub Actions: o GitHub avisa por e-mail quando o job falha.
Usa só a biblioteca padrão. Lê PDV_API_URL e PDV_API_TOKEN (o token administrativo) do ambiente
e nunca imprime o token.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

CAMINHO = "/v1/admin/cobrancas/operacao"
# O worker agendado no GitHub roda a cada ~5 min e o cron do GitHub costuma atrasar;
# o servidor alerta com 5 min sem batida, aqui só consideramos falha depois disso.
TOLERANCIA_BATIDA = 30 * 60
FORMATO = "%Y-%m-%d %H:%M:%S"


def _segundos_desde(batida: str | None, agora: str) -> float | None:
    if not batida:
        return None
    try:
        return (datetime.strptime(agora, FORMATO) - datetime.strptime(batida, FORMATO)).total_seconds()
    except (TypeError, ValueError):
        return None


def avaliar(estado: dict, tolerancia_batida: int = TOLERANCIA_BATIDA) -> list[str]:
    """Problemas que merecem aviso; lista vazia quando está tudo certo."""
    problemas = []
    for alerta in estado.get("alertas", []):
        if alerta != "worker_sem_batida":
            problemas.append(alerta)
    parada = _segundos_desde(estado.get("worker_batida_em"), estado.get("consultado_em", ""))
    if estado.get("worker_batida_em") is None:
        problemas.append("worker_nunca_rodou")
    elif parada is None or parada > tolerancia_batida:
        problemas.append("worker_sem_batida")
    return problemas


def consultar(url: str, token: str, tentativas: int = 3, espera: int = 20) -> dict:
    """GET com novas tentativas: o serviço pode demorar a responder logo após um deploy."""
    pedido = urllib.request.Request(
        url.rstrip("/") + CAMINHO, headers={"Authorization": f"Bearer {token}"})
    ultimo_erro: Exception | None = None
    for numero in range(tentativas):
        try:
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                return json.loads(resposta.read().decode("utf-8"))
        except urllib.error.HTTPError as erro:
            if erro.code in (401, 403):
                raise SystemExit(f"Acesso recusado ({erro.code}): confira PDV_API_TOKEN.")
            ultimo_erro = erro
        except (urllib.error.URLError, TimeoutError, ValueError) as erro:
            ultimo_erro = erro
        if numero + 1 < tentativas:
            time.sleep(espera)
    raise SystemExit(f"API indisponível após {tentativas} tentativas: {type(ultimo_erro).__name__}.")


def main() -> int:
    url = os.environ.get("PDV_API_URL", "").strip()
    token = os.environ.get("PDV_API_TOKEN", "").strip()
    if not url or not token:
        print("Configure PDV_API_URL e PDV_API_TOKEN.", file=sys.stderr)
        return 2
    estado = consultar(url, token)
    problemas = avaliar(estado)
    print(f"pronto={estado.get('pronto')} batida={estado.get('worker_batida_em')} "
          f"pendentes={estado.get('eventos_pendentes')} erros={estado.get('tarefas_com_erro')}")
    if problemas:
        print("ATENÇÃO: " + ", ".join(problemas))
        return 1
    print("Operação Asaas em ordem.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
