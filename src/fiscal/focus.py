"""Transmissor de NFC-e pelo Focus NFe (https://doc.focusnfe.com.br).

Autenticação: HTTP Basic com o token da empresa como usuário e senha vazia. Emissão síncrona:
`POST /v2/nfce?ref=REF` responde já autorizada, rejeitada ou em processamento. Consulta: `GET /v2/nfce/REF`.
Cancelamento: `DELETE /v2/nfce/REF` com `justificativa` (15 a 255 caracteres), até 30 minutos depois da emissão.

O certificado digital e o CSC ficam cadastrados na conta da loja no Focus, não no caixa.
Trocar de provedor é escrever outro arquivo com a mesma interface (`emitir`, `consultar`, `cancelar` → `Resposta`).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field

BASES = {"homologacao": "https://homologacao.focusnfe.com.br", "producao": "https://api.focusnfe.com.br"}

# status do Focus -> situação da nota no PDV
SITUACOES = {"autorizado": "autorizada", "cancelado": "cancelada", "erro_autorizacao": "rejeitada",
             "denegado": "rejeitada", "processando_autorizacao": "processando"}


@dataclass
class Resposta:
    """O que o provedor respondeu, já traduzido. `situacao` None = não deu para saber (rede, servidor fora)."""
    situacao: str | None
    mensagem: str = ""
    http: int = 0
    dados: dict = field(default_factory=dict)
    referencia_em_uso: bool = False


class Focus:
    def __init__(self, token: str, ambiente: str, http=None):
        if ambiente not in BASES:
            raise ValueError("Ambiente da NFC-e inválido.")
        if not (token or "").strip():
            raise ValueError("Falta o token do Focus NFe deste ambiente (Configurações > Integrações).")
        self.base = BASES[ambiente] + "/v2/nfce"
        self.cabecalho = {"Authorization": "Basic " + base64.b64encode(f"{token.strip()}:".encode()).decode()}
        if http is None:
            import requests as http
        self.http = http

    def _chamar(self, metodo: str, url: str, **kw) -> Resposta:
        try:
            r = getattr(self.http, metodo)(url, headers=self.cabecalho, timeout=(10, 40), **kw)
        except (OSError, ValueError) as erro:
            return Resposta(None, f"Sem conexão com o provedor fiscal ({type(erro).__name__}).")
        try:
            dados = r.json()
        except (ValueError, AttributeError):
            dados = {}
        dados = dados if isinstance(dados, dict) else {}
        codigo = int(getattr(r, "status_code", 0) or 0)
        mensagem = str(dados.get("mensagem_sefaz") or dados.get("mensagem") or "")[:300]
        if codigo >= 500 or codigo in (0, 429):
            return Resposta(None, mensagem or f"Provedor fiscal indisponível (HTTP {codigo}).", codigo, dados)
        status = str(dados.get("status") or "")
        if status in SITUACOES:
            return Resposta(SITUACOES[status], mensagem, codigo, dados)
        texto = (mensagem + " " + str(dados.get("codigo") or "")).lower()
        em_uso = codigo == 422 and ("já utilizada" in texto or "ja utilizada" in texto or "em processamento" in texto
                                    or "already" in texto)
        if codigo == 404:
            return Resposta(None, "Nota não encontrada no provedor.", codigo, dados)
        return Resposta("erro", mensagem or f"O provedor recusou o pedido (HTTP {codigo}).", codigo, dados,
                        referencia_em_uso=em_uso)

    def emitir(self, ref: str, dados: dict) -> Resposta:
        return self._chamar("post", self.base, params={"ref": ref, "completa": 0}, json=dados)

    def consultar(self, ref: str) -> Resposta:
        return self._chamar("get", f"{self.base}/{ref}", params={"completa": 0})

    def cancelar(self, ref: str, justificativa: str) -> Resposta:
        return self._chamar("delete", f"{self.base}/{ref}", json={"justificativa": justificativa})
