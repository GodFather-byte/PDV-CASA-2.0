"""Pix do Mercado Pago (API de pagamentos, https://www.mercadopago.com.br/developers).

Cria: `POST /v1/payments` com `payment_method_id = "pix"`, o valor em reais, o e-mail do pagador (obrigatório) e a
chave de idempotência no cabeçalho `X-Idempotency-Key`; a resposta traz o "copia e cola" e a imagem do QR Code em
`point_of_interaction.transaction_data`. Consulta: `GET /v1/payments/ID`. Cancela: `PUT /v1/payments/ID` com
`{"status": "cancelled"}`. Autenticação: `Authorization: Bearer <Access Token da loja>`.

O dinheiro cai direto na conta Mercado Pago da loja; o PDV só gera a cobrança e confere se foi paga.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

BASE = "https://api.mercadopago.com/v1/payments"

# status do Mercado Pago -> situação da cobrança no PDV
SITUACOES = {"approved": "aprovado", "authorized": "aprovado", "pending": "pendente", "in_process": "pendente",
             "in_mediation": "pendente", "cancelled": "cancelado", "rejected": "cancelado", "refunded": "cancelado",
             "charged_back": "cancelado"}


@dataclass
class Cobranca:
    """Resposta já traduzida. `situacao` None = não deu para saber (sem internet, Mercado Pago fora)."""
    situacao: str | None
    mensagem: str = ""
    provedor_id: str = ""
    copia_cola: str = ""
    imagem_base64: str = ""
    dados: dict = field(default_factory=dict)


class MercadoPagoPix:
    def __init__(self, token: str, http=None):
        if not (token or "").strip():
            raise ValueError("Falta o Access Token do Mercado Pago (Configurações > Integrações).")
        self.cabecalho = {"Authorization": f"Bearer {token.strip()}"}
        if http is None:
            import requests as http
        self.http = http

    def _chamar(self, metodo: str, url: str, cabecalho: dict | None = None, **kw) -> Cobranca:
        try:
            r = getattr(self.http, metodo)(url, headers={**self.cabecalho, **(cabecalho or {})}, timeout=(8, 20), **kw)
        except (OSError, ValueError) as erro:
            return Cobranca(None, f"Sem conexão com o Mercado Pago ({type(erro).__name__}).")
        try:
            dados = r.json()
        except (ValueError, AttributeError):
            dados = {}
        dados = dados if isinstance(dados, dict) else {}
        codigo = int(getattr(r, "status_code", 0) or 0)
        if codigo >= 500 or codigo in (0, 429):
            return Cobranca(None, f"Mercado Pago indisponível agora (HTTP {codigo}).", dados=dados)
        if codigo in (401, 403):
            return Cobranca("erro", "O Mercado Pago recusou o Access Token. Confira em Configurações > Integrações.",
                            dados=dados)
        if codigo >= 400:
            motivo = dados.get("message") or dados.get("error") or f"HTTP {codigo}"
            return Cobranca("erro", f"O Mercado Pago recusou a cobrança: {motivo}"[:300], dados=dados)
        status = str(dados.get("status") or "")
        situacao = SITUACOES.get(status, "pendente")
        if status == "cancelled" and dados.get("status_detail") == "expired":
            situacao = "expirado"
        transacao = (dados.get("point_of_interaction") or {}).get("transaction_data") or {}
        return Cobranca(situacao, str(dados.get("status_detail") or status), str(dados.get("id") or ""),
                        str(transacao.get("qr_code") or ""), str(transacao.get("qr_code_base64") or ""), dados)

    def criar(self, valor_cent: int, descricao: str, referencia: str, email: str, expira_min: int = 15,
              agora: datetime | None = None) -> Cobranca:
        vence = (agora or datetime.now()).astimezone() + timedelta(minutes=max(int(expira_min or 15), 1))
        corpo = {
            "transaction_amount": round(valor_cent / 100, 2),
            "description": descricao[:200],
            "payment_method_id": "pix",
            "payer": {"email": email},
            "external_reference": referencia,
            "date_of_expiration": vence.isoformat(timespec="milliseconds"),
        }
        return self._chamar("post", BASE, {"X-Idempotency-Key": referencia}, json=corpo)

    def consultar(self, provedor_id: str) -> Cobranca:
        return self._chamar("get", f"{BASE}/{provedor_id}")

    def cancelar(self, provedor_id: str) -> Cobranca:
        return self._chamar("put", f"{BASE}/{provedor_id}", json={"status": "cancelled"})
