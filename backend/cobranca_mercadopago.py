"""Cobrança da licença pelo Mercado Pago (Pix e Checkout Pro). Nenhum segredo vai para o PDV.

O webhook roda dentro da API: valida o cabeçalho x-signature, busca o pagamento na API oficial
e só então renova a loja. A varredura periódica também fica neste processo (sem worker pago).
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import Base

log = logging.getLogger("pdv.cobranca")
API = "https://api.mercadopago.com"
TIMEOUT = 8
TOLERANCIA_ASSINATURA_SEG = 300
INTERVALO_VARREDURA = 6 * 60 * 60
ATRASO_VARREDURA = 20
LIMITE_RESPOSTA = 1_000_000
ID_PAGAMENTO = re.compile(r"[0-9]{1,20}")
ID_EVENTO = re.compile(r"[A-Za-z0-9_-]{8,128}")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,80}\.[^@\s]{1,24}$")
CAMINHO_API = re.compile(r"/[A-Za-z0-9_./-]{1,200}")
APROVADO = "approved"
_MARCA_DECIMAL = "«dec:"
_parada = threading.Event()
_thread: threading.Thread | None = None
_trava_thread = threading.Lock()


class ErroCobranca(Exception):
    """Erro que deve ser mostrado ao administrador sem expor credenciais."""


class MercadoPagoIndisponivel(ErroCobranca):
    pass


class WebhookNaoConfigurado(ErroCobranca):
    pass


class AssinaturaInvalida(ErroCobranca):
    pass


class Plano(Base):
    """Mensalidade de uma loja. A validade anterior congela o que já estava pago antes do plano."""
    __tablename__ = "planos_mercadopago"
    id = Column(String, primary_key=True)
    chave_loja = Column(String, unique=True, nullable=False, index=True)
    valor_cent = Column(Integer, nullable=False)
    email_pagador = Column(String, nullable=False)
    validade_anterior = Column(String, nullable=True)
    criado_em = Column(String, nullable=False)


class Cobranca(Base):
    """Uma mensalidade gerada por nós: Pix (QR) e, quando o Mercado Pago aceita, link do Checkout Pro."""
    __tablename__ = "cobrancas_mercadopago"
    id = Column(String, primary_key=True)
    plano = Column(String, nullable=False, index=True)
    chave_loja = Column(String, nullable=False, index=True)
    chave_vencimento = Column(String, unique=True, nullable=False)
    valor_cent = Column(Integer, nullable=False)
    vencimento = Column(String, nullable=False)
    status = Column(String, nullable=False)
    pix_id = Column(String, nullable=True)
    preference_id = Column(String, nullable=True)
    pix_copia_cola = Column(Text, nullable=True)
    pix_qr_base64 = Column(Text, nullable=True)
    pix_url = Column(String, nullable=True)
    checkout_url = Column(String, nullable=True)
    preference_erro = Column(String, nullable=True)
    licenca_ate = Column(String, nullable=True)
    criada_em = Column(String, nullable=False)
    consultada_em = Column(String, nullable=False)


class Pagamento(Base):
    """Pagamento conferido na API (Pix e/ou Checkout Pro da mesma cobrança)."""
    __tablename__ = "pagamentos_mercadopago"
    id = Column(String, primary_key=True)
    cobranca = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)
    valor_cent = Column(Integer, nullable=False)
    meio = Column(String, nullable=True)
    licenca_ate = Column(String, nullable=True)
    consultado_em = Column(String, nullable=False)


class Evento(Base):
    """x-request-id já aplicado. Outra notificação do mesmo pagamento, com outro id, é processada de novo."""
    __tablename__ = "eventos_mercadopago"
    id = Column(String, primary_key=True)
    pagamento = Column(String, nullable=False)
    recebido_em = Column(String, nullable=False)


def agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def garantir_esquema(bind=None) -> None:
    """Cria as tabelas do Mercado Pago se faltarem.

    Não altera ``lojas.licenca_ate`` e não apaga tabelas antigas do Asaas: a data paga da loja
    continua valendo, e o histórico que já estava no banco permanece intocado.
    """
    from backend.database import engine
    alvo = bind or engine
    for modelo in (Plano, Cobranca, Pagamento, Evento):
        modelo.__table__.create(bind=alvo, checkfirst=True)


def fim_periodo(vencimento: date) -> date:
    """Um mês de calendário a partir do vencimento, inclusive; nunca a partir do recebimento do webhook."""
    ano = vencimento.year + (vencimento.month == 12)
    mes = vencimento.month % 12 + 1
    return date(ano, mes, min(vencimento.day, calendar.monthrange(ano, mes)[1]))


def centavos(valor: object) -> int:
    try:
        decimal = Decimal(str(valor))
        convertido = decimal * 100
        if not convertido.is_finite() or convertido <= 0 or convertido != convertido.to_integral_value():
            raise ValueError
        return int(convertido)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        raise ErroCobranca("Valor da cobrança deve ser positivo, com até duas casas decimais.") from None


def reais(valor_cent: int) -> Decimal:
    return (Decimal(int(valor_cent)) / Decimal(100)).quantize(Decimal("0.01"))


def para_json(dados: dict) -> bytes:
    """Serializa Decimal como número JSON exato (99.90), sem passar por float."""
    def conv(valor):
        if isinstance(valor, Decimal):
            if not valor.is_finite():
                raise ErroCobranca("Valor inválido.")
            return _MARCA_DECIMAL + format(valor, "f") + "»"
        raise TypeError(type(valor))
    texto = json.dumps(dados, default=conv, ensure_ascii=False, separators=(",", ":"))
    texto = re.sub(r'"«dec:(-?\d+(?:\.\d+)?)»"', r"\1", texto)
    return texto.encode("utf-8")


def manifesto(data_id: str, request_id: str, ts: str) -> str:
    """Modelo oficial: id em minúsculas, request-id e ts crus do cabeçalho, cada um com ponto e vírgula."""
    return f"id:{data_id.lower()};request-id:{request_id};ts:{ts};"


def validar_assinatura(x_signature: str | None, x_request_id: str | None, data_id: str | None) -> tuple[str, str]:
    """Confere o HMAC-SHA256 do x-signature (segredo MP_WEBHOOK_SECRET). Não olha o corpo."""
    segredo = os.environ.get("MP_WEBHOOK_SECRET", "").strip()
    if not segredo:
        raise WebhookNaoConfigurado("Webhook Mercado Pago não configurado.")
    if not x_signature or not x_request_id or data_id is None or data_id == "":
        raise AssinaturaInvalida("Assinatura ausente.")
    if not ID_EVENTO.fullmatch(x_request_id):
        raise AssinaturaInvalida("Identificador da notificação inválido.")
    ts = v1 = None
    for parte in x_signature.split(","):
        if "=" not in parte:
            continue
        chave, valor = parte.split("=", 1)
        chave, valor = chave.strip(), valor.strip()
        if chave == "ts":
            ts = valor
        elif chave == "v1":
            v1 = valor
    if not ts or not v1 or not ts.isdigit():
        raise AssinaturaInvalida("Assinatura malformada.")
    instante = int(ts)
    if instante > 10**11:
        instante //= 1000
    if abs(int(time.time()) - instante) > TOLERANCIA_ASSINATURA_SEG:
        raise AssinaturaInvalida("Assinatura fora do prazo.")
    esperado = hmac.new(
        segredo.encode("utf-8"), manifesto(data_id, x_request_id, ts).encode("utf-8"), hashlib.sha256).hexdigest()
    if len(esperado) != len(v1) or not hmac.compare_digest(esperado, v1):
        raise AssinaturaInvalida("Assinatura inválida.")
    return data_id, x_request_id


def varredura_habilitada() -> bool:
    if os.environ.get("MP_VARREDURA", "1").strip() == "0":
        return False
    return bool(os.environ.get("MP_ACCESS_TOKEN", "").strip())


def _token() -> str:
    token = os.environ.get("MP_ACCESS_TOKEN", "").strip()
    if not token:
        raise MercadoPagoIndisponivel("Configure MP_ACCESS_TOKEN no servidor.")
    return token


def modo_teste() -> bool:
    return _token().startswith("TEST-")


def url_notificacao() -> str | None:
    """No Render o endereço público já vem em RENDER_EXTERNAL_URL. Fora isso, vale o webhook do painel."""
    base = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if base.startswith("https://") and " " not in base:
        return base + "/v1/webhooks/mercadopago"
    return None


class _SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MercadoPagoIndisponivel("Mercado Pago respondeu com redirecionamento; consulta interrompida.")


def _abrir(requisicao: Request):
    return build_opener(_SemRedirecionamento).open(requisicao, timeout=TIMEOUT)


def requisitar(metodo: str, caminho: str, corpo: dict | None = None, idempotencia: str | None = None) -> dict:
    base, _, consulta = caminho.partition("?")
    if metodo not in ("GET", "POST", "PUT") or not CAMINHO_API.fullmatch(base) or ".." in caminho:
        raise ErroCobranca("Caminho inválido.")
    token = _token()
    dados = para_json(corpo) if corpo is not None else None
    cabecalhos = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "WillPDV/1.0",
    }
    if dados is not None:
        cabecalhos["Content-Type"] = "application/json"
    if idempotencia:
        cabecalhos["X-Idempotency-Key"] = idempotencia
    pedido = Request(API + caminho, data=dados, headers=cabecalhos, method=metodo)
    try:
        with _abrir(pedido) as resposta:
            bruto = resposta.read(LIMITE_RESPOSTA + 1)
    except MercadoPagoIndisponivel:
        raise
    except HTTPError as erro:
        if erro.code in (400, 409, 422):
            raise ErroCobranca(f"Mercado Pago recusou a operação (HTTP {erro.code}).") from None
        raise MercadoPagoIndisponivel(f"Mercado Pago indisponível (HTTP {erro.code}).") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise MercadoPagoIndisponivel("Não foi possível consultar o Mercado Pago.") from None
    if len(bruto) > LIMITE_RESPOSTA:
        raise MercadoPagoIndisponivel("Resposta do Mercado Pago excedeu o tamanho aceito.")
    if not bruto:
        return {}
    try:
        lido = json.loads(bruto, parse_float=Decimal)
    except ValueError:
        raise MercadoPagoIndisponivel("O Mercado Pago devolveu uma resposta inválida.") from None
    if not isinstance(lido, dict):
        raise MercadoPagoIndisponivel("O Mercado Pago devolveu uma resposta inválida.")
    return lido


def _id_pagamento(valor: object) -> str:
    texto = str(valor) if valor is not None else ""
    if not ID_PAGAMENTO.fullmatch(texto):
        raise ErroCobranca("Identificador de pagamento inválido.")
    return texto


def obter_pagamento(pagamento_id: str) -> dict:
    pagamento_id = _id_pagamento(pagamento_id)
    dados = requisitar("GET", f"/v1/payments/{pagamento_id}")
    if str(dados.get("id")) != pagamento_id:
        raise MercadoPagoIndisponivel("O Mercado Pago devolveu outro pagamento.")
    return dados


def ids_por_referencia(referencia: str) -> list[str]:
    if not re.fullmatch(r"[a-f0-9]{32}", referencia):
        raise ErroCobranca("Referência de cobrança inválida.")
    dados = requisitar(
        "GET",
        "/v1/payments/search?sort=date_created&criteria=desc&limit=50&external_reference=" + quote(referencia))
    resultados = dados.get("results")
    if not isinstance(resultados, list):
        raise MercadoPagoIndisponivel("Listagem de pagamentos inválida.")
    ids = []
    for item in resultados:
        if isinstance(item, dict) and item.get("id") is not None:
            ids.append(_id_pagamento(item.get("id")))
    return ids


def _email(valor: str) -> str:
    valor = (valor or "").strip()
    if not EMAIL.fullmatch(valor) or len(valor) > 120:
        raise ErroCobranca("Informe um e-mail válido do pagador (o Mercado Pago exige e-mail no Pix).")
    return valor


def _valor_plano(valor_cent: int) -> int:
    if isinstance(valor_cent, bool) or not isinstance(valor_cent, int) or not 1 <= valor_cent <= 10_000_000:
        raise ErroCobranca("A mensalidade em centavos deve ser um inteiro de 1 até 10000000.")
    return valor_cent


def definir_plano(db: Session, chave: str, valor_cent: int, email: str) -> str:
    from backend.main import Loja
    valor_cent = _valor_plano(valor_cent)
    email = _email(email)
    loja = db.query(Loja).filter_by(chave_loja=chave).first()
    if loja is None:
        raise ErroCobranca("Loja não encontrada; cadastre-a com backend.lojas.")
    plano = db.query(Plano).filter_by(chave_loja=chave).first()
    if plano is None:
        db.add(Plano(id=uuid.uuid4().hex, chave_loja=chave, valor_cent=valor_cent, email_pagador=email,
                     validade_anterior=loja.licenca_ate, criado_em=agora()))
        db.commit()
        return "criado"
    plano.valor_cent = valor_cent
    plano.email_pagador = email
    db.commit()
    return "atualizado"


def _iso_mp(momento: datetime) -> str:
    momento = momento.astimezone(timezone.utc).replace(microsecond=0)
    return momento.strftime("%Y-%m-%dT%H:%M:%S.000+00:00")


def _expiracao(vencimento: date) -> str:
    """Pix do Mercado Pago só aceita entre 30 minutos e 30 dias. A licença usa o vencimento, não esta data."""
    agora_utc = datetime.now(timezone.utc)
    minimo = agora_utc + timedelta(minutes=30)
    limite = agora_utc + timedelta(days=30) - timedelta(minutes=1)
    alvo = datetime(vencimento.year, vencimento.month, vencimento.day, 23, 59, 59, tzinfo=timezone.utc)
    alvo = alvo + timedelta(days=7)
    if alvo < minimo:
        alvo = minimo
    if alvo > limite:
        alvo = limite
    return _iso_mp(alvo)


def _https(valor: object) -> str | None:
    if isinstance(valor, str) and valor.startswith("https://") and len(valor) <= 2000 and " " not in valor:
        return valor
    return None


def _bloquear_plano(db: Session, plano_id: str) -> Plano:
    consulta = db.query(Plano).filter_by(id=plano_id)
    if db.get_bind().dialect.name == "postgresql":
        consulta = consulta.with_for_update()
    return consulta.one()


def gerar(db: Session, chave: str, vencimento: date) -> Cobranca:
    plano = db.query(Plano).filter_by(chave_loja=chave).first()
    if plano is None:
        raise ErroCobranca("Loja sem plano Mercado Pago. Cadastre com: cobranca plano.")
    iso = vencimento.isoformat()
    cobranca = db.query(Cobranca).filter_by(chave_vencimento=f"{chave}:{iso}").first()
    if cobranca is None:
        cobranca = Cobranca(
            id=uuid.uuid4().hex, plano=plano.id, chave_loja=chave, chave_vencimento=f"{chave}:{iso}",
            valor_cent=plano.valor_cent, vencimento=iso, status="criando", criada_em=agora(),
            consultada_em=agora())
        db.add(cobranca)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            cobranca = db.query(Cobranca).filter_by(chave_vencimento=f"{chave}:{iso}").one()
    if cobranca.pix_copia_cola and cobranca.preference_id:
        if cobranca.status == "criando":
            cobranca.status = "pendente"
            db.commit()
        return cobranca
    plano = db.get(Plano, cobranca.plano)
    notificacao = url_notificacao()
    descricao = f"Licença WillPDV {chave} {iso}"
    if not cobranca.pix_id or not cobranca.pix_copia_cola:
        corpo = {
            "transaction_amount": reais(cobranca.valor_cent),
            "description": descricao,
            "payment_method_id": "pix",
            "date_of_expiration": _expiracao(vencimento),
            "external_reference": cobranca.id,
            "payer": {"email": plano.email_pagador},
            "metadata": {"chave_loja": chave, "cobranca": cobranca.id},
        }
        if notificacao:
            corpo["notification_url"] = notificacao
        resposta = requisitar("POST", "/v1/payments", corpo, idempotencia=cobranca.id)
        transacao = ((resposta.get("point_of_interaction") or {}).get("transaction_data") or {})
        codigo = transacao.get("qr_code")
        if not isinstance(codigo, str) or len(codigo) < 10:
            raise ErroCobranca("Mercado Pago não devolveu o Pix copia e cola.")
        cobranca.pix_id = _id_pagamento(resposta.get("id"))
        cobranca.pix_copia_cola = codigo
        if isinstance(transacao.get("qr_code_base64"), str):
            cobranca.pix_qr_base64 = transacao["qr_code_base64"][:200_000]
        cobranca.pix_url = _https(transacao.get("ticket_url"))
        cobranca.consultada_em = agora()
        db.commit()
    if not cobranca.preference_id:
        corpo_pref = {
            "items": [{
                "id": cobranca.id,
                "title": descricao[:120],
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": reais(cobranca.valor_cent),
            }],
            "payer": {"email": plano.email_pagador},
            "external_reference": cobranca.id,
            "metadata": {"chave_loja": chave, "cobranca": cobranca.id},
            "expires": True,
            "expiration_date_from": _iso_mp(datetime.now(timezone.utc) - timedelta(minutes=1)),
            "expiration_date_to": _expiracao(vencimento),
            "payment_methods": {
                "excluded_payment_types": [{"id": "bank_transfer"}],
                "installments": 1,
                "default_installments": 1,
            },
        }
        if notificacao:
            corpo_pref["notification_url"] = notificacao
        try:
            resposta = requisitar("POST", "/checkout/preferences", corpo_pref, idempotencia=cobranca.id + "pref")
        except ErroCobranca as erro:
            cobranca.preference_erro = str(erro)[:200]
            cobranca.status = "pendente"
            db.commit()
            return cobranca
        link = _https(resposta.get("sandbox_init_point") if modo_teste() else resposta.get("init_point"))
        pref = resposta.get("id")
        if not link or not isinstance(pref, str) or not pref or len(pref) > 200:
            cobranca.preference_erro = "Mercado Pago não devolveu o link do Checkout Pro."
        else:
            cobranca.preference_id = pref
            cobranca.checkout_url = link
            cobranca.preference_erro = None
        cobranca.consultada_em = agora()
    if cobranca.status == "criando":
        cobranca.status = "pendente"
    db.commit()
    return cobranca


def _estornado(dados: dict) -> bool:
    if dados.get("status") in ("refunded", "charged_back", "cancelled"):
        return True
    valor = dados.get("transaction_amount_refunded")
    if valor in (None, 0, "0", "0.00", Decimal("0")):
        return False
    try:
        return Decimal(str(valor)) > 0
    except (InvalidOperation, ValueError, TypeError):
        return True


def _metadata_confere(dados: dict, plano: Plano) -> bool:
    meta = dados.get("metadata")
    if not isinstance(meta, dict) or "chave_loja" not in meta:
        return True
    return meta.get("chave_loja") == plano.chave_loja


def _registrar_evento(db: Session, evento_id: str | None, pagamento_id: str) -> None:
    if evento_id and db.get(Evento, evento_id) is None:
        db.add(Evento(id=evento_id, pagamento=pagamento_id, recebido_em=agora()))


def recalcular(db: Session, plano: Plano) -> None:
    from backend.main import Loja
    datas = [plano.validade_anterior] if plano.validade_anterior else []
    for cobranca in db.query(Cobranca).filter_by(plano=plano.id):
        pagamentos = db.query(Pagamento).filter_by(cobranca=cobranca.id).all()
        cobertos = [p.licenca_ate for p in pagamentos if p.licenca_ate]
        cobranca.licenca_ate = max(cobertos) if cobertos else None
        if cobranca.licenca_ate:
            cobranca.status = "aprovada"
        elif any(p.status in ("refunded", "charged_back") for p in pagamentos):
            cobranca.status = "estornada"
        elif any(p.status == "approved" for p in pagamentos):
            cobranca.status = "divergente"
        elif pagamentos:
            cobranca.status = "pendente"
        cobranca.consultada_em = agora()
        if cobranca.licenca_ate:
            datas.append(cobranca.licenca_ate)
    loja = db.query(Loja).filter_by(chave_loja=plano.chave_loja).one()
    loja.licenca_ate = max(datas) if datas else None


def _aplicar_dados(db: Session, dados: dict, evento_id: str | None, cobranca: Cobranca,
                   plano: Plano) -> tuple[str, str | None]:
    """Grava o pagamento. Devolve a situação e o Pix a cancelar, se outro meio já pagou a cobrança."""
    pagamento_id = _id_pagamento(dados.get("id"))
    if dados.get("external_reference") != cobranca.id:
        _registrar_evento(db, evento_id, pagamento_id)
        return "desconhecida", None
    try:
        vencimento = date.fromisoformat(cobranca.vencimento)
        valor = centavos(dados.get("transaction_amount"))
    except (ErroCobranca, ValueError):
        valor = 0
        vencimento = None
    status = dados.get("status") if isinstance(dados.get("status"), str) else ""
    concede = (status == APROVADO and not _estornado(dados) and vencimento is not None
               and valor == cobranca.valor_cent and dados.get("currency_id", "BRL") == "BRL"
               and _metadata_confere(dados, plano))
    registro = db.get(Pagamento, pagamento_id)
    if registro is None:
        registro = Pagamento(id=pagamento_id, cobranca=cobranca.id)
        db.add(registro)
    elif registro.cobranca != cobranca.id:
        log.warning("Pagamento %s já ligado a outra cobrança.", pagamento_id)
        _registrar_evento(db, evento_id, pagamento_id)
        return "processado", None
    meio = dados.get("payment_type_id") if isinstance(dados.get("payment_type_id"), str) else dados.get("payment_method_id")
    registro.status = (status or "desconhecido")[:40]
    registro.valor_cent = valor
    registro.meio = meio[:40] if isinstance(meio, str) and meio else None
    registro.licenca_ate = fim_periodo(vencimento).isoformat() if concede else None
    registro.consultado_em = agora()
    db.flush()
    recalcular(db, plano)
    _registrar_evento(db, evento_id, pagamento_id)
    if concede and cobranca.pix_id and cobranca.pix_id != pagamento_id:
        return "processado", cobranca.pix_id
    return "processado", None


def aplicar(db: Session, dados: dict, evento_id: str | None, *, confirmar: bool = True) -> str:
    pagamento_id = _id_pagamento(dados.get("id"))
    referencia = dados.get("external_reference")
    cobranca = db.get(Cobranca, referencia) if isinstance(referencia, str) else None
    if cobranca is None:
        _registrar_evento(db, evento_id, pagamento_id)
        if confirmar:
            db.commit()
        log.info("Pagamento %s sem cobrança conhecida.", pagamento_id)
        return "desconhecida"
    plano = _bloquear_plano(db, cobranca.plano)
    cobranca = db.get(Cobranca, cobranca.id)
    if evento_id and db.get(Evento, evento_id):
        return "repetido"
    dados = obter_pagamento(pagamento_id)
    situacao, pix_a_cancelar = _aplicar_dados(db, dados, evento_id, cobranca, plano)
    try:
        if confirmar:
            db.commit()
    except IntegrityError:
        db.rollback()
        return "repetido"
    if confirmar and pix_a_cancelar:
        encerrar_pix(pix_a_cancelar)
    log.info("Pagamento %s conciliado: %s; loja %s.", pagamento_id, dados.get("status"), plano.chave_loja)
    return situacao


def encerrar_pix(pix_id: str) -> None:
    """Melhor esforço: o cliente já pagou por outro meio. Falha aqui não desfaz a licença."""
    try:
        atual = obter_pagamento(pix_id)
        if atual.get("status") == "pending":
            requisitar("PUT", f"/v1/payments/{pix_id}", {"status": "cancelled"})
    except Exception:
        log.warning("Não foi possível cancelar o Pix %s depois de outro pagamento aprovado.", pix_id)


def processar_notificacao(db: Session, pagamento_id: str, evento_id: str | None) -> str:
    pagamento_id = _id_pagamento(pagamento_id)
    if evento_id is not None:
        if not ID_EVENTO.fullmatch(evento_id):
            raise ErroCobranca("Identificador da notificação inválido.")
        if db.get(Evento, evento_id):
            return "repetido"
    return aplicar(db, obter_pagamento(pagamento_id), evento_id, confirmar=True)


def reconciliar(db: Session, chave: str) -> int:
    plano = db.query(Plano).filter_by(chave_loja=chave).first()
    if plano is None:
        raise ErroCobranca("Loja sem plano Mercado Pago.")
    plano = _bloquear_plano(db, plano.id)
    ids: list[str] = []
    pix_pendentes: list[str] = []
    for cobranca in db.query(Cobranca).filter_by(plano=plano.id):
        if cobranca.pix_id:
            ids.append(cobranca.pix_id)
        ids.extend(ids_por_referencia(cobranca.id))
    vistos: list[str] = []
    for pagamento_id in ids:
        if pagamento_id not in vistos:
            vistos.append(pagamento_id)
    for pagamento_id in vistos:
        dados = obter_pagamento(pagamento_id)
        referencia = dados.get("external_reference")
        cobranca = db.get(Cobranca, referencia) if isinstance(referencia, str) else None
        if cobranca is None or cobranca.plano != plano.id:
            continue
        _situacao, pix = _aplicar_dados(db, dados, None, cobranca, plano)
        if pix:
            pix_pendentes.append(pix)
    db.commit()
    for pix_id in pix_pendentes:
        encerrar_pix(pix_id)
    return len(vistos)


def varrer(db: Session) -> int:
    chaves = [plano.chave_loja for plano in db.query(Plano).all()]
    total = 0
    for chave in chaves:
        try:
            total += reconciliar(db, chave)
        except ErroCobranca as erro:
            db.rollback()
            log.error("Varredura da loja %s falhou: %s", chave, erro)
        except Exception:
            db.rollback()
            log.error("Varredura da loja %s falhou (erro interno).", chave)
    return total


def _loop_varredura() -> None:
    if _parada.wait(ATRASO_VARREDURA):
        return
    while not _parada.is_set():
        try:
            from backend.main import SessionLocal
            with SessionLocal() as db:
                varrer(db)
        except Exception:
            log.error("Varredura Mercado Pago falhou (erro interno).")
        if _parada.wait(INTERVALO_VARREDURA):
            return


def iniciar_varredura() -> None:
    global _thread
    if not varredura_habilitada():
        return
    with _trava_thread:
        if _thread and _thread.is_alive():
            return
        _parada.clear()
        _thread = threading.Thread(target=_loop_varredura, name="mp-varredura", daemon=True)
        _thread.start()


def parar_varredura() -> None:
    _parada.set()
    thread = _thread
    if thread and thread.is_alive() and threading.current_thread() is not thread:
        thread.join(timeout=2)


def estado(db: Session) -> dict:
    pendentes = db.query(Cobranca).filter(Cobranca.status.in_(("criando", "pendente"))).count()
    recentes = db.query(Cobranca).order_by(Cobranca.consultada_em.desc()).limit(50)
    return {
        "provedor": "mercadopago",
        "varredura_no_processo": varredura_habilitada(),
        "planos": db.query(Plano).count(),
        "cobrancas_pendentes": pendentes,
        "consultado_em": agora(),
        "cobrancas": [
            {"loja": c.chave_loja, "vencimento": c.vencimento, "status": c.status,
             "licenca_ate": c.licenca_ate, "tem_pix": bool(c.pix_copia_cola),
             "tem_checkout": bool(c.checkout_url)}
            for c in recentes],
    }


def _imprimir(cobranca: Cobranca) -> None:
    print(f"Cobrança {cobranca.id} da loja {cobranca.chave_loja}.")
    print(f"Vencimento {cobranca.vencimento}. Valor {cobranca.valor_cent} centavos. Situação {cobranca.status}.")
    if cobranca.pix_copia_cola and cobranca.status != "aprovada":
        print("Pix copia e cola:")
        print(cobranca.pix_copia_cola)
    if cobranca.pix_url and cobranca.status != "aprovada":
        print(f"Página do Pix (QR Code): {cobranca.pix_url}")
    if cobranca.checkout_url and cobranca.status != "aprovada":
        print(f"Link para cartão ou boleto: {cobranca.checkout_url}")
    if cobranca.preference_erro:
        print(f"Aviso: Checkout Pro não foi gerado ({cobranca.preference_erro}). O Pix continua válido.",
              file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    comandos = parser.add_subparsers(dest="comando", required=True)
    plano = comandos.add_parser("plano", help="Cadastrar ou atualizar a mensalidade da loja.")
    plano.add_argument("loja")
    plano.add_argument("valor_cent", type=int)
    plano.add_argument("email")
    gerar_cmd = comandos.add_parser("gerar", help="Gerar Pix e link do Checkout Pro para um vencimento.")
    gerar_cmd.add_argument("loja")
    gerar_cmd.add_argument("vencimento", help="AAAA-MM-DD")
    comandos.add_parser("listar", help="Mostrar planos e cobranças, sem segredo.")
    conciliar = comandos.add_parser("conciliar", help="Reler os pagamentos na API e renovar o que estiver pago.")
    conciliar.add_argument("loja")
    args = parser.parse_args(argv)
    from backend.main import SessionLocal
    with SessionLocal() as db:
        try:
            if args.comando == "plano":
                situacao = definir_plano(db, args.loja, args.valor_cent, args.email)
                print(f"Plano {situacao} para {args.loja}: {args.valor_cent} centavos.")
            elif args.comando == "gerar":
                try:
                    vencimento = date.fromisoformat(args.vencimento)
                except ValueError:
                    raise ErroCobranca("Informe o vencimento como AAAA-MM-DD.") from None
                _imprimir(gerar(db, args.loja, vencimento))
            elif args.comando == "conciliar":
                print(f"Pagamentos conciliados: {reconciliar(db, args.loja)}")
            else:
                planos = {p.chave_loja: p for p in db.query(Plano).order_by(Plano.chave_loja)}
                if not planos:
                    print("Nenhum plano Mercado Pago.")
                for chave, plano_loja in planos.items():
                    print(f"{chave}  {plano_loja.valor_cent} centavos")
                    for cobranca in db.query(Cobranca).filter_by(plano=plano_loja.id).order_by(Cobranca.vencimento):
                        print(f"  {cobranca.vencimento}  {cobranca.status}  "
                              f"pix={'sim' if cobranca.pix_copia_cola else 'não'}  "
                              f"checkout={'sim' if cobranca.checkout_url else 'não'}  "
                              f"licença={cobranca.licenca_ate or '—'}")
                        if cobranca.status != "aprovada" and cobranca.pix_copia_cola:
                            print(f"  copia e cola: {cobranca.pix_copia_cola}")
                        if cobranca.status != "aprovada" and cobranca.checkout_url:
                            print(f"  link: {cobranca.checkout_url}")
        except ErroCobranca as erro:
            db.rollback()
            print(f"Erro: {erro}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
