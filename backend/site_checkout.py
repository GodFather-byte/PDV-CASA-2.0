"""Checkout Pro do site público: o preço sai daqui, o Mercado Pago só cobra.

O navegador manda o id do plano e os dados de quem compra. O valor em centavos
é o de `site_precos` — o que vier no corpo (valor, preço, parcelas) é ignorado.
Sem `MP_ACCESS_TOKEN` a rota responde 503 e os botões do site abrem o WhatsApp.

O webhook `/v1/pagamentos/webhook` não acredita no corpo: exige o `x-signature`
(`MP_WEBHOOK_SECRET`, o mesmo da mensalidade) e só então busca o pagamento na
API. A mesma notificação, reenviada, não duplica o registro.

Isto não emite licença nem mexe na cobrança das lojas já existentes. O pedido
fica nas tabelas `site_pedidos` e `site_pagamentos` para o acompanhamento.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import Body, FastAPI, HTTPException, Request
from sqlalchemy import Column, Integer, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import cobranca_mercadopago as cobranca
from backend import site_precos as precos
from backend.database import Base, SessionLocal, engine

log = logging.getLogger("pdv.site_checkout")

VAR_TOKEN = "MP_ACCESS_TOKEN"
VAR_BASE = "PUBLIC_BASE_URL"
PARCELAS_ANUAL = 10
ROTA_CHECKOUT = "/v1/pagamentos/checkout"
ROTA_WEBHOOK = "/v1/pagamentos/webhook"
MSG_INDISPONIVEL = "Pagamento online indisponível. Chame no WhatsApp."
MSG_FALHA = "Não foi possível abrir o pagamento. Chame no WhatsApp."
_ID_PEDIDO = re.compile(r"[a-f0-9]{32}")
_EMAIL = cobranca.EMAIL

# Família do cartão (o período entra no id: adega-mensal, adega-anual).
FAMILIAS = (
    ("adega", "Will Adega"),
    ("restaurante", "Will Restaurante"),
    ("variedades", "Will Variedades"),
    ("hotel", "Will Hotel"),
    ("boate", "WillPDV Boate e Bar"),
)
_MENSAL = {
    "adega": precos.ADEGA_MENSAL_CENT,
    "restaurante": precos.RESTAURANTE_MENSAL_CENT,
    "variedades": precos.VARIEDADES_MENSAL_CENT,
    "hotel": precos.HOTEL_MENSAL_CENT,
    "boate": precos.BOATE_MENSAL_CENT,
}
# Pix (bank_transfer) e cartão ficam. Boleto e caixa eletrônico saem.
_EXCLUIDOS = ({"id": "ticket"}, {"id": "atm"})
_STATUS = {
    "approved": "aprovado",
    "authorized": "pendente",
    "pending": "pendente",
    "in_process": "pendente",
    "in_mediation": "pendente",
    "rejected": "recusado",
    "cancelled": "cancelado",
    "refunded": "estornado",
    "charged_back": "estornado",
}


@dataclass(frozen=True)
class Plano:
    id: str
    familia: str
    nome: str
    periodo: str
    valor_cent: int
    parcelas: int


def _montar_planos() -> dict[str, Plano]:
    planos: dict[str, Plano] = {}
    for chave, nome in FAMILIAS:
        mensal = _MENSAL[chave]
        planos[f"{chave}-mensal"] = Plano(f"{chave}-mensal", chave, nome, "mensal", mensal, 1)
        anual = precos.anual_cent(mensal)
        planos[f"{chave}-anual"] = Plano(
            f"{chave}-anual", chave, nome, "anual", anual, PARCELAS_ANUAL)
    return planos


PLANOS = _montar_planos()


class Pedido(Base):
    """Um checkout do site. O valor é o do plano no momento em que a pessoa pediu."""

    __tablename__ = "site_pedidos"
    id = Column(String, primary_key=True)
    plano = Column(String, nullable=False)
    periodo = Column(String, nullable=False)
    nome = Column(String, nullable=False)
    email = Column(String, nullable=False)
    whatsapp = Column(String, nullable=False)
    loja = Column(String, nullable=False)
    valor_cent = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    preference_id = Column(String, nullable=True)
    checkout_url = Column(String, nullable=True)
    payment_id = Column(String, nullable=True, index=True)
    mp_status = Column(String, nullable=True)
    valor_pago_cent = Column(Integer, nullable=True)
    moeda = Column(String, nullable=True)
    criado_em = Column(String, nullable=False)
    atualizado_em = Column(String, nullable=False)
    pago_em = Column(String, nullable=True)


class PagamentoSite(Base):
    """Uma linha por id de pagamento. Reenvio do webhook cai na mesma linha."""

    __tablename__ = "site_pagamentos"
    payment_id = Column(String, primary_key=True)
    pedido_id = Column(String, index=True, nullable=False)
    mp_status = Column(String, nullable=False)
    valor_cent = Column(Integer, nullable=True)
    moeda = Column(String, nullable=False)
    registrado_em = Column(String, nullable=False)
    atualizado_em = Column(String, nullable=False)


def agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def checkout_disponivel() -> bool:
    return bool(os.environ.get(VAR_TOKEN, "").strip())


def _base_ok(base: str) -> bool:
    """Origem https, sem usuário, caminho, consulta ou espaço. O caminho a gente acrescenta."""
    if not base.startswith("https://") or any(c in base for c in " \t\r\n\\"):
        return False
    resto = base[len("https://"):]
    if not resto or any(c in resto for c in "@/?#"):
        return False
    return True


def base_publica() -> str:
    """Origem https do site, dos retornos e do notification_url do checkout.

    PUBLIC_BASE_URL, quando é uma origem https sem caminho. Sem ela, o endereço
    publicado em site_precos (https://willpdv.com.br).

    RENDER_EXTERNAL_URL não entra: no Render ele é o host *.onrender.com dos
    caixas e do painel. O checkout público não pode apontar para lá.
    """
    base = os.environ.get(VAR_BASE, "").strip().rstrip("/")
    if _base_ok(base):
        return base
    return precos.URL_PUBLICA.rstrip("/")


def _texto(valor: object, minimo: int, maximo: int, rotulo: str) -> str:
    texto = re.sub(r"\s+", " ", str(valor or "")).replace("\x00", "").strip()
    if not minimo <= len(texto) <= maximo:
        raise HTTPException(status_code=422, detail=f"Preencha {rotulo} ({minimo} a {maximo} letras).")
    return texto


def whatsapp_normalizado(bruto: object) -> str:
    """Celular brasileiro em 55 + DDD + número. WhatsApp é celular (9 depois do DDD)."""
    digitos = re.sub(r"\D", "", str(bruto or ""))
    if digitos.startswith("55") and len(digitos) in (12, 13):
        nacional = digitos[2:]
    elif len(digitos) in (10, 11):
        nacional = digitos
    else:
        raise HTTPException(status_code=422, detail="Informe o WhatsApp com DDD (ex.: 11 91234-5678).")
    if not 11 <= int(nacional[:2]) <= 99 or len(nacional) != 11 or nacional[2] != "9":
        raise HTTPException(status_code=422, detail="Informe o WhatsApp do celular com DDD (ex.: 11 91234-5678).")
    return "55" + nacional


def _email(valor: object) -> str:
    texto = str(valor or "").strip()
    if not _EMAIL.fullmatch(texto) or len(texto) > 120:
        raise HTTPException(status_code=422, detail="Informe um e-mail válido.")
    return texto


def plano_por_id(valor: object) -> Plano:
    if not isinstance(valor, str):
        raise HTTPException(status_code=422, detail="Escolha um plano.")
    plano = PLANOS.get(valor.strip())
    if plano is None:
        raise HTTPException(status_code=422, detail="Escolha um plano.")
    return plano


def _partir_nome(nome: str) -> tuple[str, str]:
    partes = nome.split()
    if len(partes) == 1:
        return partes[0][:40], partes[0][:40]
    return partes[0][:40], " ".join(partes[1:])[:60]


def _https(valor: object) -> str | None:
    if isinstance(valor, str) and valor.startswith("https://") and len(valor) <= 2000 and " " not in valor:
        return valor
    return None


def _link_checkout(resposta: dict) -> str:
    """Token de teste (TEST-) usa o sandbox. O campo que devolvemos ao site chama-se init_point."""
    campo = "sandbox_init_point" if cobranca.modo_teste() else "init_point"
    link = _https(resposta.get(campo))
    if link is None and campo != "init_point":
        link = _https(resposta.get("init_point"))
    if not link:
        raise cobranca.ErroCobranca("Mercado Pago não devolveu o link do checkout.")
    return link


def _corpo_preferencia(pedido: Pedido, plano: Plano) -> dict:
    base = base_publica()
    primeiro, resto = _partir_nome(pedido.nome)
    nacional = pedido.whatsapp[2:]
    return {
        "items": [{
            "id": plano.id,
            "title": f"{plano.nome} — plano {plano.periodo}"[:120],
            "description": "Assinatura do caixa WillPDV. Instalação grátis.",
            "quantity": 1,
            "currency_id": "BRL",
            "unit_price": cobranca.reais(plano.valor_cent),
        }],
        "payer": {
            "name": primeiro,
            "surname": resto,
            "email": pedido.email,
            "phone": {"area_code": nacional[:2], "number": nacional[2:]},
        },
        "back_urls": {
            "success": base + "/site/obrigado",
            "pending": base + "/site/pagamento-pendente",
            "failure": base + "/site/pagamento-falhou",
        },
        "auto_return": "approved",
        "external_reference": pedido.id,
        "notification_url": base + ROTA_WEBHOOK,
        "metadata": {"plano": plano.id, "pedido": pedido.id},
        "payment_methods": {
            "excluded_payment_types": [dict(item) for item in _EXCLUIDOS],
            "installments": plano.parcelas,
            "default_installments": 1,
        },
    }


def criar_checkout(db: Session, dados: dict) -> dict:
    if not isinstance(dados, dict):
        raise HTTPException(status_code=422, detail="Dados inválidos.")
    if not checkout_disponivel():
        raise HTTPException(status_code=503, detail=MSG_INDISPONIVEL)
    plano = plano_por_id(dados.get("plano"))
    nome = _texto(dados.get("nome"), 3, 80, "o seu nome")
    email = _email(dados.get("email"))
    whatsapp = whatsapp_normalizado(dados.get("whatsapp"))
    loja = _texto(dados.get("loja") or dados.get("nome_loja"), 3, 80, "o nome da loja")
    momento = agora()
    pedido = Pedido(
        id=uuid.uuid4().hex, plano=plano.id, periodo=plano.periodo, nome=nome, email=email,
        whatsapp=whatsapp, loja=loja, valor_cent=plano.valor_cent, status="criando",
        criado_em=momento, atualizado_em=momento)
    db.add(pedido)
    db.commit()
    try:
        resposta = cobranca.requisitar(
            "POST", "/checkout/preferences", _corpo_preferencia(pedido, plano), idempotencia=pedido.id)
        link = _link_checkout(resposta)
        pref = resposta.get("id")
        if not isinstance(pref, str) or not pref or len(pref) > 200:
            raise cobranca.ErroCobranca("Mercado Pago não devolveu a preferência.")
    except (cobranca.ErroCobranca, cobranca.MercadoPagoIndisponivel):
        pedido.status = "erro"
        pedido.atualizado_em = agora()
        db.commit()
        log.error("Checkout do site não abriu (plano %s).", plano.id)
        raise HTTPException(status_code=503, detail=MSG_FALHA) from None
    pedido.preference_id = pref
    pedido.checkout_url = link
    pedido.status = "aguardando"
    pedido.atualizado_em = agora()
    db.commit()
    return {"init_point": link, "pedido": pedido.id, "plano": plano.id, "valor_cent": plano.valor_cent}


def _valor_api(dados: dict) -> int | None:
    try:
        return cobranca.centavos(dados.get("transaction_amount"))
    except cobranca.ErroCobranca:
        return None


def _carregar(db: Session, pedido_id: str) -> Pedido | None:
    consulta = db.query(Pedido).filter(Pedido.id == pedido_id)
    if db.get_bind().dialect.name == "postgresql":
        consulta = consulta.with_for_update()
    return consulta.one_or_none()


def registrar_pagamento(db: Session, dados: dict, pagamento_id: str, repetir: bool = True) -> str:
    """Grava o que a API do Mercado Pago devolveu. Repetir a mesma notificação não altera o pedido."""
    if str(dados.get("id")) != pagamento_id:
        return "ignorado"
    referencia = str(dados.get("external_reference") or "").strip().lower()
    if not _ID_PEDIDO.fullmatch(referencia):
        return "ignorado"
    pedido = _carregar(db, referencia)
    if pedido is None:
        return "ignorado"
    mp_status = str(dados.get("status") or "")
    moeda = str(dados.get("currency_id") or "")
    valor = _valor_api(dados)
    momento = agora()
    linha = db.get(PagamentoSite, pagamento_id)
    if (linha is not None and linha.pedido_id == referencia and linha.mp_status == mp_status
            and linha.moeda == moeda and linha.valor_cent == valor):
        return "idempotente"
    if linha is None:
        linha = PagamentoSite(
            payment_id=pagamento_id, pedido_id=referencia, mp_status=mp_status, valor_cent=valor,
            moeda=moeda, registrado_em=momento, atualizado_em=momento)
        db.add(linha)
    else:
        linha.pedido_id = referencia
        linha.mp_status = mp_status
        linha.valor_cent = valor
        linha.moeda = moeda
        linha.atualizado_em = momento
    nosso = _STATUS.get(mp_status, "pendente")
    confere = moeda == "BRL" and valor == pedido.valor_cent
    if mp_status == "approved" and not confere:
        nosso = "divergente"
    if pedido.status == "aprovado" and pedido.payment_id and pedido.payment_id != pagamento_id and nosso != "aprovado":
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return "idempotente"
        return "ja_aprovado"
    pedido.payment_id = pagamento_id
    pedido.mp_status = mp_status
    pedido.valor_pago_cent = valor
    pedido.moeda = moeda
    pedido.status = nosso
    pedido.atualizado_em = momento
    if nosso == "aprovado" and not pedido.pago_em:
        pedido.pago_em = momento
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if repetir:
            return registrar_pagamento(db, dados, pagamento_id, repetir=False)
        return "idempotente"
    return "processado"


def _ids_na_ordem(dados: dict) -> list[str]:
    lista = dados.get("payments")
    if not isinstance(lista, list):
        return []
    ids: list[str] = []
    for item in lista:
        bruto = item.get("id") if isinstance(item, dict) else item
        texto = str(bruto) if bruto is not None else ""
        if cobranca.ID_PAGAMENTO.fullmatch(texto) and texto not in ids:
            ids.append(texto)
    return ids[:20]


def processar_webhook(db: Session, request: Request) -> dict:
    try:
        pagamento_id, _evento = cobranca.validar_assinatura(
            request.headers.get("x-signature"),
            request.headers.get("x-request-id"),
            request.query_params.get("data.id"))
    except cobranca.WebhookNaoConfigurado:
        raise HTTPException(status_code=503, detail="Webhook Mercado Pago não configurado.") from None
    except cobranca.AssinaturaInvalida:
        raise HTTPException(status_code=401, detail="Assinatura do webhook inválida.") from None
    if not checkout_disponivel():
        raise HTTPException(status_code=503, detail=MSG_INDISPONIVEL)
    if not cobranca.ID_PAGAMENTO.fullmatch(pagamento_id or ""):
        return {"situacao": "ignorado"}
    tipo = (request.query_params.get("type") or request.query_params.get("topic") or "").strip().lower()
    if not tipo:
        tipo = "payment"
    if tipo == "merchant_order":
        ordem = cobranca.requisitar("GET", f"/merchant_orders/{pagamento_id}")
        situacao = "ignorado"
        for pid in _ids_na_ordem(ordem):
            situacao = registrar_pagamento(db, cobranca.obter_pagamento(pid), pid)
        return {"situacao": situacao}
    if tipo != "payment":
        return {"situacao": "ignorado"}
    return {"situacao": registrar_pagamento(db, cobranca.obter_pagamento(pagamento_id), pagamento_id)}


def instalar(app: FastAPI) -> None:
    Base.metadata.create_all(bind=engine)

    @app.post(ROTA_CHECKOUT, include_in_schema=False)
    def abrir_checkout(dados: dict = Body(...)):
        with SessionLocal() as db:
            return criar_checkout(db, dados)

    @app.api_route(ROTA_WEBHOOK, methods=["GET", "POST"], include_in_schema=False)
    def webhook(request: Request):
        with SessionLocal() as db:
            try:
                return processar_webhook(db, request)
            except HTTPException:
                raise
            except cobranca.MercadoPagoIndisponivel:
                db.rollback()
                log.error("Mercado Pago indisponível ao confirmar pagamento do site.")
                raise HTTPException(
                    status_code=503, detail="Mercado Pago indisponível; a notificação será reenviada.") from None
            except Exception:
                db.rollback()
                log.error("Falha ao processar webhook de pagamento do site.")
                raise HTTPException(
                    status_code=503, detail="Não foi possível processar a notificação.") from None
