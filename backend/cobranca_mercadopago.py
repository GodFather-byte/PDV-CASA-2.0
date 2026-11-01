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
import smtplib
import sys
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
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
ANTECEDENCIA_PADRAO = 5
FOLGA_ATRASO_DIAS = 20
_MARCA_DECIMAL = "«dec:"
_COLUNAS_NOVAS = {
    "planos_mercadopago": {
        "dia_vencimento": "INTEGER",
        "antecedencia_dias": "INTEGER",
        "email_gerente": "VARCHAR",
        "whatsapp": "VARCHAR",
        "pagador_nome": "VARCHAR",
        "pagador_documento": "VARCHAR",
        "cep": "VARCHAR",
        "logradouro": "VARCHAR",
        "numero": "VARCHAR",
        "bairro": "VARCHAR",
        "cidade": "VARCHAR",
        "uf": "VARCHAR",
    },
    "cobrancas_mercadopago": {
        "boleto_id": "VARCHAR",
        "boleto_url": "VARCHAR",
        "boleto_linha": "VARCHAR",
        "boleto_erro": "VARCHAR",
        "avisada_em": "VARCHAR",
        "aviso_email": "VARCHAR",
        "aviso_whatsapp": "VARCHAR",
    },
}
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
    dia_vencimento = Column(Integer, nullable=True)
    antecedencia_dias = Column(Integer, nullable=True)
    email_gerente = Column(String, nullable=True)
    whatsapp = Column(String, nullable=True)
    pagador_nome = Column(String, nullable=True)
    pagador_documento = Column(String, nullable=True)
    cep = Column(String, nullable=True)
    logradouro = Column(String, nullable=True)
    numero = Column(String, nullable=True)
    bairro = Column(String, nullable=True)
    cidade = Column(String, nullable=True)
    uf = Column(String, nullable=True)


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
    boleto_id = Column(String, nullable=True)
    boleto_url = Column(String, nullable=True)
    boleto_linha = Column(String, nullable=True)
    boleto_erro = Column(String, nullable=True)
    avisada_em = Column(String, nullable=True)
    aviso_email = Column(String, nullable=True)
    aviso_whatsapp = Column(String, nullable=True)


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
    from sqlalchemy import inspect, text
    from backend.database import engine
    alvo = bind or engine
    for modelo in (Plano, Cobranca, Pagamento, Evento):
        modelo.__table__.create(bind=alvo, checkfirst=True)
    with alvo.begin() as con:
        inspetor = inspect(con)
        for tabela, colunas in _COLUNAS_NOVAS.items():
            if not inspetor.has_table(tabela):
                continue
            existentes = {c["name"] for c in inspetor.get_columns(tabela)}
            for nome, tipo in colunas.items():
                if nome not in existentes:
                    con.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}"))


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


def _digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def _cpf_valido(numero: str) -> bool:
    if len(numero) != 11 or numero == numero[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(numero[i]) * ((tamanho + 1) - i) for i in range(tamanho))
        digito = (soma * 10) % 11 % 10
        if digito != int(numero[tamanho]):
            return False
    return True


def _cnpj_valido(numero: str) -> bool:
    if len(numero) != 14 or numero == numero[0] * 14:
        return False
    pesos = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    for tamanho in (12, 13):
        soma = sum(int(numero[i]) * pesos[i] for i in range(tamanho))
        resto = soma % 11
        digito = 0 if resto < 2 else 11 - resto
        if digito != int(numero[tamanho]):
            return False
        pesos = (6,) + pesos
    return True


def validar_documento(valor: str) -> tuple[str, str]:
    numero = _digitos(valor)
    if _cpf_valido(numero):
        return "CPF", numero
    if _cnpj_valido(numero):
        return "CNPJ", numero
    raise ErroCobranca("Informe um CPF (11 dígitos) ou CNPJ (14 dígitos) válido.")


def normalizar_whatsapp(valor: str) -> str:
    """Celular ou fixo do Brasil em +55DDDNÚMERO. Aceita (11) 99999-9999 e +55 11 99999-9999."""
    numero = _digitos(valor)
    if numero.startswith("55") and len(numero) in (12, 13):
        nacional = numero[2:]
    elif len(numero) in (10, 11):
        nacional = numero
    else:
        raise ErroCobranca("WhatsApp inválido. Use o formato +55 11 99999-9999.")
    ddd = int(nacional[:2])
    if not 11 <= ddd <= 99:
        raise ErroCobranca("DDD do WhatsApp inválido.")
    if len(nacional) == 11 and nacional[2] != "9":
        raise ErroCobranca("Celular brasileiro deve começar com 9 depois do DDD.")
    return "+55" + nacional


def _texto_curto(valor: str, nome: str, minimo: int, maximo: int) -> str:
    texto = " ".join((valor or "").split())
    if not minimo <= len(texto) <= maximo:
        raise ErroCobranca(f"{nome} deve ter de {minimo} a {maximo} caracteres.")
    return texto


def _partir_nome(nome: str) -> tuple[str, str]:
    partes = nome.split()
    if len(partes) == 1:
        return partes[0][:40], partes[0][:40]
    return partes[0][:40], " ".join(partes[1:])[:60]


def dia_no_mes(ano: int, mes: int, dia: int) -> date:
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def _deslocar_mes(ano: int, mes: int, delta: int) -> tuple[int, int]:
    indice = ano * 12 + (mes - 1) + delta
    return indice // 12, indice % 12 + 1


def vencimentos_abertos(hoje: date, dia: int, antecedencia: int) -> list[date]:
    """Vencimentos cuja janela de emissão já abriu e que ainda dá tempo de cobrar."""
    saida = []
    for delta in (-1, 0, 1):
        ano, mes = _deslocar_mes(hoje.year, hoje.month, delta)
        vencimento = dia_no_mes(ano, mes, dia)
        inicio = vencimento - timedelta(days=antecedencia)
        fim = vencimento + timedelta(days=FOLGA_ATRASO_DIAS)
        if inicio <= hoje <= fim:
            saida.append(vencimento)
    return saida


def proximo_vencimento(hoje: date, dia: int, antecedencia: int) -> date:
    abertos = vencimentos_abertos(hoje, dia, antecedencia)
    if abertos:
        return abertos[-1]
    for delta in (0, 1, 2):
        ano, mes = _deslocar_mes(hoje.year, hoje.month, delta)
        vencimento = dia_no_mes(ano, mes, dia)
        if vencimento - timedelta(days=antecedencia) > hoje:
            return vencimento
    ano, mes = _deslocar_mes(hoje.year, hoje.month, 2)
    return dia_no_mes(ano, mes, dia)


def dados_boleto_completos(plano: Plano) -> bool:
    return all((plano.pagador_nome, plano.pagador_documento, plano.cep, plano.logradouro,
                plano.numero, plano.bairro, plano.cidade, plano.uf))


def definir_assinatura_mensal(db: Session, chave: str, valor_cent: int, dia: int, email: str, whatsapp: str,
                              nome: str, documento: str, cep: str, logradouro: str, numero: str, bairro: str,
                              cidade: str, uf: str, antecedencia: int = ANTECEDENCIA_PADRAO) -> str:
    """Cadastra ou atualiza a recorrência. Não chama o Mercado Pago."""
    from backend.main import Loja
    valor_cent = _valor_plano(valor_cent)
    if isinstance(dia, bool) or not isinstance(dia, int) or not 1 <= dia <= 31:
        raise ErroCobranca("O dia de vencimento deve ser um inteiro de 1 a 31.")
    if isinstance(antecedencia, bool) or not isinstance(antecedencia, int) or not 1 <= antecedencia <= 20:
        raise ErroCobranca("A antecedência deve ser de 1 a 20 dias.")
    email = _email(email)
    telefone = normalizar_whatsapp(whatsapp)
    nome = _texto_curto(nome, "O nome do pagador", 5, 80)
    if len(nome.split()) < 1:
        raise ErroCobranca("Informe o nome do pagador.")
    _tipo, documento_limpo = validar_documento(documento)
    cep_limpo = _digitos(cep)
    if len(cep_limpo) != 8:
        raise ErroCobranca("CEP deve ter 8 dígitos.")
    logradouro = _texto_curto(logradouro, "O logradouro", 2, 80)
    numero = _texto_curto(numero, "O número", 1, 10)
    bairro = _texto_curto(bairro, "O bairro", 2, 50)
    cidade = _texto_curto(cidade, "A cidade", 2, 50)
    uf = (uf or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", uf):
        raise ErroCobranca("UF deve ter 2 letras.")
    loja = db.query(Loja).filter_by(chave_loja=chave).first()
    if loja is None:
        raise ErroCobranca("Loja não encontrada; cadastre-a com backend.lojas.")
    plano = db.query(Plano).filter_by(chave_loja=chave).first()
    situacao = "atualizada"
    if plano is None:
        plano = Plano(id=uuid.uuid4().hex, chave_loja=chave, valor_cent=valor_cent, email_pagador=email,
                      validade_anterior=loja.licenca_ate, criado_em=agora())
        db.add(plano)
        situacao = "criada"
    plano.valor_cent = valor_cent
    plano.email_pagador = email
    plano.email_gerente = email
    plano.whatsapp = telefone
    plano.dia_vencimento = dia
    plano.antecedencia_dias = antecedencia
    plano.pagador_nome = nome
    plano.pagador_documento = documento_limpo
    plano.cep = cep_limpo
    plano.logradouro = logradouro
    plano.numero = numero
    plano.bairro = bairro
    plano.cidade = cidade
    plano.uf = uf
    db.commit()
    return situacao


def definir_assinatura_de_pedido(db: Session, dados: dict) -> str:
    """Mesmos campos do comando e do POST /v1/admin/cobrancas/assinatura."""
    if not isinstance(dados, dict):
        raise ErroCobranca("Corpo inválido.")
    rotulos = (
        ("chave_loja", "chave da loja"),
        ("valor_cent", "valor em centavos"),
        ("dia_vencimento", "dia de vencimento"),
        ("email", "e-mail do responsável"),
        ("whatsapp", "WhatsApp do responsável"),
        ("nome", "nome do pagador"),
        ("documento", "CPF ou CNPJ"),
        ("cep", "CEP"),
        ("logradouro", "logradouro"),
        ("numero", "número"),
        ("bairro", "bairro"),
        ("cidade", "cidade"),
        ("uf", "UF"),
    )
    faltando = [rotulo for chave, rotulo in rotulos if dados.get(chave) in (None, "")]
    if faltando:
        raise ErroCobranca("Para o boleto informe: " + ", ".join(faltando) + ".")
    valor, dia = dados["valor_cent"], dados["dia_vencimento"]
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErroCobranca("valor_cent deve ser inteiro em centavos (24999 = R$ 249,99).")
    if isinstance(dia, bool) or not isinstance(dia, int):
        raise ErroCobranca("dia_vencimento deve ser inteiro de 1 a 31.")
    antecedencia = dados.get("antecedencia_dias", ANTECEDENCIA_PADRAO)
    if antecedencia is None:
        antecedencia = ANTECEDENCIA_PADRAO
    if isinstance(antecedencia, bool) or not isinstance(antecedencia, int):
        raise ErroCobranca("antecedencia_dias deve ser um inteiro de 1 a 20.")
    return definir_assinatura_mensal(
        db, str(dados["chave_loja"]).strip(), valor, dia, str(dados["email"]), str(dados["whatsapp"]),
        str(dados["nome"]), str(dados["documento"]), str(dados["cep"]), str(dados["logradouro"]),
        str(dados["numero"]), str(dados["bairro"]), str(dados["cidade"]), str(dados["uf"]), antecedencia)


def parar_assinatura_mensal(db: Session, chave: str) -> None:
    plano = db.query(Plano).filter_by(chave_loja=chave).first()
    if plano is None or plano.dia_vencimento is None:
        raise ErroCobranca("Loja sem assinatura mensal.")
    plano.dia_vencimento = None
    db.commit()


def metodo_boleto() -> str:
    valor = (os.environ.get("MP_BOLETO_METODO", "bolbradesco") or "bolbradesco").strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{1,32}", valor):
        raise ErroCobranca("MP_BOLETO_METODO inválido.")
    return valor


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


def _boleto_pendente(plano: Plano, cobranca: Cobranca, forcar: bool) -> bool:
    if not dados_boleto_completos(plano) or cobranca.boleto_id:
        return False
    return forcar or not cobranca.boleto_erro


def _extrair_boleto(resposta: dict) -> tuple[str | None, str | None]:
    detalhes = resposta.get("transaction_details") if isinstance(resposta.get("transaction_details"), dict) else {}
    url = _https(detalhes.get("external_resource_url"))
    barra = resposta.get("barcode") if isinstance(resposta.get("barcode"), dict) else {}
    linha = barra.get("content")
    if not isinstance(linha, str) or not linha.strip():
        candidato = detalhes.get("digitable_line") or detalhes.get("payment_method_reference_id")
        linha = candidato if isinstance(candidato, str) else ""
    linha = re.sub(r"\s+", "", linha).strip()[:64] or None
    return url, linha


def _pagador_boleto(plano: Plano) -> dict:
    primeiro, resto = _partir_nome(plano.pagador_nome)
    tipo = "CNPJ" if len(plano.pagador_documento) == 14 else "CPF"
    return {
        "email": plano.email_pagador,
        "first_name": primeiro,
        "last_name": resto,
        "identification": {"type": tipo, "number": plano.pagador_documento},
        "address": {
            "zip_code": plano.cep,
            "street_name": plano.logradouro,
            "street_number": plano.numero,
            "neighborhood": plano.bairro,
            "city": plano.cidade,
            "federal_unit": plano.uf,
        },
    }


def _criar_boleto(cobranca: Cobranca, plano: Plano, vencimento: date, notificacao: str | None, descricao: str) -> None:
    corpo = {
        "transaction_amount": reais(cobranca.valor_cent),
        "description": descricao,
        "payment_method_id": metodo_boleto(),
        "date_of_expiration": _expiracao(vencimento),
        "external_reference": cobranca.id,
        "payer": _pagador_boleto(plano),
        "metadata": {"chave_loja": plano.chave_loja, "cobranca": cobranca.id},
    }
    if notificacao:
        corpo["notification_url"] = notificacao
    try:
        resposta = requisitar("POST", "/v1/payments", corpo, idempotencia=cobranca.id + "boleto")
    except ErroCobranca as erro:
        cobranca.boleto_erro = str(erro)[:200]
        return
    url, linha = _extrair_boleto(resposta)
    try:
        cobranca.boleto_id = _id_pagamento(resposta.get("id"))
    except ErroCobranca:
        cobranca.boleto_erro = "Mercado Pago não devolveu o boleto."
        return
    cobranca.boleto_url = url
    cobranca.boleto_linha = linha
    cobranca.boleto_erro = None if (url or linha) else "Mercado Pago não devolveu o link nem a linha digitável."


def gerar(db: Session, chave: str, vencimento: date, *, forcar: bool = False) -> Cobranca:
    plano = db.query(Plano).filter_by(chave_loja=chave).first()
    if plano is None:
        raise ErroCobranca("Loja sem plano Mercado Pago. Cadastre com: cobranca plano.")
    iso = vencimento.isoformat()
    cobranca = db.query(Cobranca).filter_by(chave_vencimento=f"{chave}:{iso}").first()
    if cobranca is not None and forcar:
        cobranca.preference_erro = None
        cobranca.boleto_erro = None
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
    if (cobranca.pix_copia_cola and (cobranca.preference_id or cobranca.preference_erro)
            and not _boleto_pendente(plano, cobranca, forcar)):
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
                "excluded_payment_types": (
                    [{"id": "bank_transfer"}, {"id": "ticket"}] if dados_boleto_completos(plano)
                    else [{"id": "bank_transfer"}]),
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
        else:
            link = _https(resposta.get("sandbox_init_point") if modo_teste() else resposta.get("init_point"))
            pref = resposta.get("id")
            if not link or not isinstance(pref, str) or not pref or len(pref) > 200:
                cobranca.preference_erro = "Mercado Pago não devolveu o link do Checkout Pro."
            else:
                cobranca.preference_id = pref
                cobranca.checkout_url = link
                cobranca.preference_erro = None
        cobranca.consultada_em = agora()
    if _boleto_pendente(plano, cobranca, forcar):
        _criar_boleto(cobranca, plano, vencimento, notificacao, descricao)
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
        return "desconhecida", []
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
        return "processado", []
    meio = dados.get("payment_type_id") if isinstance(dados.get("payment_type_id"), str) else dados.get("payment_method_id")
    registro.status = (status or "desconhecido")[:40]
    registro.valor_cent = valor
    registro.meio = meio[:40] if isinstance(meio, str) and meio else None
    registro.licenca_ate = fim_periodo(vencimento).isoformat() if concede else None
    registro.consultado_em = agora()
    db.flush()
    recalcular(db, plano)
    _registrar_evento(db, evento_id, pagamento_id)
    cancelar = []
    if concede:
        for outro in (cobranca.pix_id, cobranca.boleto_id):
            if outro and outro != pagamento_id and outro not in cancelar:
                cancelar.append(outro)
    return "processado", cancelar


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
    situacao, cancelar = _aplicar_dados(db, dados, evento_id, cobranca, plano)
    try:
        if confirmar:
            db.commit()
    except IntegrityError:
        db.rollback()
        return "repetido"
    if confirmar:
        for pagamento_aberto in cancelar:
            encerrar_pagamento(pagamento_aberto)
    log.info("Pagamento %s conciliado: %s; loja %s.", pagamento_id, dados.get("status"), plano.chave_loja)
    return situacao


def encerrar_pagamento(pagamento_id: str) -> None:
    """Melhor esforço: o cliente já pagou por outro meio. Falha aqui não desfaz a licença."""
    try:
        atual = obter_pagamento(pagamento_id)
        if atual.get("status") == "pending":
            requisitar("PUT", f"/v1/payments/{pagamento_id}", {"status": "cancelled"})
    except Exception:
        log.warning("Não foi possível cancelar o pagamento %s depois de outro meio aprovado.", pagamento_id)


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
    cancelar: list[str] = []
    for cobranca in db.query(Cobranca).filter_by(plano=plano.id):
        if cobranca.pix_id:
            ids.append(cobranca.pix_id)
        if cobranca.boleto_id:
            ids.append(cobranca.boleto_id)
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
        _situacao, extras = _aplicar_dados(db, dados, None, cobranca, plano)
        for extra in extras:
            if extra not in cancelar:
                cancelar.append(extra)
    db.commit()
    for pagamento_id in cancelar:
        encerrar_pagamento(pagamento_id)
    return len(vistos)


def smtp_configurado() -> bool:
    return all(os.environ.get(nome, "").strip() for nome in
               ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"))


def brevo_configurado() -> bool:
    """A chave basta para preferir a Brevo. O remetente é exigido na hora do envio."""
    return bool(os.environ.get("BREVO_API_KEY", "").strip())


def whatsapp_configurado() -> bool:
    return bool(os.environ.get("WHATSAPP_API_URL", "").strip() and os.environ.get("WHATSAPP_API_TOKEN", "").strip())


def texto_cobranca(nome_loja: str, cobranca: Cobranca) -> str:
    valor = f"R$ {reais(cobranca.valor_cent):.2f}".replace(".", ",")
    linhas = [
        f"Licença WillPDV — {nome_loja}",
        f"Vencimento: {cobranca.vencimento}",
        f"Valor: {valor}",
    ]
    if cobranca.boleto_url:
        linhas.append(f"Boleto (PDF): {cobranca.boleto_url}")
    if cobranca.boleto_linha:
        linhas.append(f"Linha digitável: {cobranca.boleto_linha}")
    if cobranca.pix_copia_cola:
        linhas.append("Pix copia e cola:")
        linhas.append(cobranca.pix_copia_cola)
    if cobranca.boleto_erro and not cobranca.boleto_url:
        linhas.append("O boleto ainda não foi gerado. O Pix acima paga a mesma mensalidade.")
    return "\n".join(linhas)


def link_whatsapp(telefone: str, texto: str) -> str:
    enxuto = texto if len(texto) <= 1500 else texto[:1500]
    return "https://wa.me/" + telefone.lstrip("+") + "?text=" + quote(enxuto)


def enviar_email_brevo(destino: str, assunto: str, corpo: str) -> None:
    """POST https://api.brevo.com/v3/smtp/email com o cabeçalho api-key. Não usa porta SMTP."""
    chave = os.environ.get("BREVO_API_KEY", "").strip()
    remetente = os.environ.get("EMAIL_FROM", "").strip()
    if not chave:
        raise ErroCobranca("Configure BREVO_API_KEY no servidor.")
    if not remetente:
        raise ErroCobranca("Configure EMAIL_FROM com um remetente verificado na Brevo.")
    _email(remetente)
    _email(destino)
    nome = os.environ.get("EMAIL_FROM_NAME", "").strip()
    if nome and ("\n" in nome or "\r" in nome or len(nome) > 70):
        raise ErroCobranca("EMAIL_FROM_NAME inválido.")
    sender = {"email": remetente}
    if nome:
        sender["name"] = nome
    pedido = Request(
        "https://api.brevo.com/v3/smtp/email",
        data=para_json({
            "sender": sender,
            "to": [{"email": destino}],
            "subject": assunto,
            "textContent": corpo,
        }),
        method="POST",
        headers={
            "api-key": chave,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "WillPDV/1.0",
        })
    try:
        with _abrir(pedido) as resposta:
            resposta.read(LIMITE_RESPOSTA)
    except HTTPError as erro:
        raise ErroCobranca(f"Brevo recusou o envio (HTTP {erro.code}).") from None
    except (URLError, TimeoutError, OSError, MercadoPagoIndisponivel):
        raise ErroCobranca("Não foi possível chamar a Brevo.") from None


def enviar_email(destino: str, assunto: str, corpo: str) -> None:
    """Brevo (HTTPS) quando BREVO_API_KEY existe; senão SMTP."""
    if brevo_configurado():
        enviar_email_brevo(destino, assunto, corpo)
        return
    if not smtp_configurado():
        raise ErroCobranca("E-mail não configurado. Defina BREVO_API_KEY e EMAIL_FROM, ou o SMTP.")
    _enviar_email_smtp(destino, assunto, corpo)


def _enviar_email_smtp(destino: str, assunto: str, corpo: str) -> None:
    host = os.environ["SMTP_HOST"].strip()
    try:
        porta = int(os.environ["SMTP_PORT"].strip())
    except ValueError:
        raise ErroCobranca("SMTP_PORT inválida.") from None
    usuario = os.environ["SMTP_USER"].strip()
    senha = os.environ["SMTP_PASSWORD"]
    remetente = os.environ["SMTP_FROM"].strip()
    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = remetente
    mensagem["To"] = destino
    mensagem.set_content(corpo)
    try:
        if porta == 465:
            with smtplib.SMTP_SSL(host, porta, timeout=15) as smtp:
                smtp.login(usuario, senha)
                smtp.send_message(mensagem)
        else:
            with smtplib.SMTP(host, porta, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(usuario, senha)
                smtp.send_message(mensagem)
    except ErroCobranca:
        raise
    except Exception:
        raise ErroCobranca("Não foi possível enviar o e-mail. Confira SMTP_HOST, SMTP_PORT, SMTP_USER e SMTP_PASSWORD.") from None


def enviar_whatsapp_api(telefone: str, texto: str) -> None:
    """POST genérico. Corpo: {"to": "+55...", "text": "..."} e Authorization: Bearer WHATSAPP_API_TOKEN."""
    url = os.environ.get("WHATSAPP_API_URL", "").strip()
    token = os.environ.get("WHATSAPP_API_TOKEN", "").strip()
    if not url.startswith("https://") or " " in url:
        raise ErroCobranca("WHATSAPP_API_URL deve ser https.")
    pedido = Request(url, data=para_json({"to": telefone, "text": texto}), method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "WillPDV/1.0",
    })
    try:
        with _abrir(pedido) as resposta:
            resposta.read(LIMITE_RESPOSTA)
    except HTTPError as erro:
        raise ErroCobranca(f"WhatsApp recusou o envio (HTTP {erro.code}).") from None
    except (URLError, TimeoutError, OSError, MercadoPagoIndisponivel):
        raise ErroCobranca("Não foi possível chamar a API de WhatsApp.") from None


def entregar(db: Session, plano: Plano, cobranca: Cobranca) -> dict:
    from backend.main import Loja
    loja = db.query(Loja).filter_by(chave_loja=plano.chave_loja).first()
    nome = loja.nome if loja is not None else plano.chave_loja
    texto = texto_cobranca(nome, cobranca)
    resultado = {
        "email": "nao_configurado",
        "whatsapp": "nao_configurado",
        "whatsapp_link": link_whatsapp(plano.whatsapp, texto) if plano.whatsapp else None,
    }
    if plano.email_gerente and (brevo_configurado() or smtp_configurado()):
        try:
            enviar_email(plano.email_gerente, f"Licença WillPDV {plano.chave_loja} — {cobranca.vencimento}", texto)
            resultado["email"] = "enviado"
        except ErroCobranca:
            resultado["email"] = "erro"
    if plano.whatsapp and whatsapp_configurado():
        try:
            enviar_whatsapp_api(plano.whatsapp, texto)
            resultado["whatsapp"] = "enviado"
        except ErroCobranca:
            resultado["whatsapp"] = "erro"
    cobranca.avisada_em = agora()
    cobranca.aviso_email = resultado["email"]
    cobranca.aviso_whatsapp = resultado["whatsapp"]
    db.commit()
    return resultado


def reenviar(db: Session, chave: str) -> dict:
    plano = db.query(Plano).filter_by(chave_loja=chave).first()
    if plano is None:
        raise ErroCobranca("Loja sem plano Mercado Pago.")
    cobranca = (db.query(Cobranca).filter_by(plano=plano.id)
                .filter(Cobranca.status != "aprovada")
                .order_by(Cobranca.vencimento.desc()).first())
    if cobranca is None:
        cobranca = db.query(Cobranca).filter_by(plano=plano.id).order_by(Cobranca.vencimento.desc()).first()
    if cobranca is None:
        raise ErroCobranca("Loja sem cobrança para reenviar.")
    resultado = entregar(db, plano, cobranca)
    resultado["vencimento"] = cobranca.vencimento
    resultado["boleto_url"] = cobranca.boleto_url
    resultado["boleto_linha"] = cobranca.boleto_linha
    resultado["pix_copia_cola"] = cobranca.pix_copia_cola
    return resultado


def gerar_recorrencias(db: Session, hoje: date | None = None, chave: str | None = None) -> int:
    """Gera a cobrança do mês (boleto + Pix) na janela antes do vencimento e avisa uma vez."""
    hoje = hoje or date.today()
    consulta = db.query(Plano).filter(Plano.dia_vencimento.isnot(None))
    if chave:
        consulta = consulta.filter_by(chave_loja=chave)
    emitidas = 0
    for plano in consulta.all():
        if not dados_boleto_completos(plano):
            log.error("Assinatura %s sem dados do pagador; boleto não gerado.", plano.chave_loja)
            continue
        antecedencia = plano.antecedencia_dias or ANTECEDENCIA_PADRAO
        for vencimento in vencimentos_abertos(hoje, plano.dia_vencimento, antecedencia):
            marca = f"{plano.chave_loja}:{vencimento.isoformat()}"
            existente = db.query(Cobranca).filter_by(chave_vencimento=marca).first()
            if (existente and existente.avisada_em and existente.pix_copia_cola
                    and (existente.boleto_id or existente.boleto_erro)):
                continue
            try:
                cobranca = gerar(db, plano.chave_loja, vencimento)
            except ErroCobranca as erro:
                db.rollback()
                log.error("Assinatura %s: %s", plano.chave_loja, erro)
                continue
            if not cobranca.avisada_em:
                entregar(db, plano, cobranca)
                emitidas += 1
    return emitidas


def resumo_assinatura(plano: Plano, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    tipo = None
    if plano.pagador_documento:
        tipo = "CNPJ" if len(plano.pagador_documento) == 14 else "CPF"
    proximo = None
    if plano.dia_vencimento:
        proximo = proximo_vencimento(hoje, plano.dia_vencimento, plano.antecedencia_dias or ANTECEDENCIA_PADRAO).isoformat()
    return {
        "chave_loja": plano.chave_loja,
        "valor_cent": plano.valor_cent,
        "dia_vencimento": plano.dia_vencimento,
        "antecedencia_dias": plano.antecedencia_dias or ANTECEDENCIA_PADRAO,
        "email": plano.email_gerente,
        "whatsapp": plano.whatsapp,
        "documento_tipo": tipo,
        "proximo_vencimento": proximo,
    }


def varrer(db: Session) -> int:
    try:
        gerar_recorrencias(db)
    except Exception:
        db.rollback()
        log.error("Geração das assinaturas falhou (erro interno).")
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


def _link_da_cobranca(db: Session, cobranca: Cobranca) -> str | None:
    if whatsapp_configurado() or cobranca.status == "aprovada":
        return None
    plano = db.get(Plano, cobranca.plano)
    if plano is None or not plano.whatsapp:
        return None
    from backend.main import Loja
    loja = db.query(Loja).filter_by(chave_loja=plano.chave_loja).first()
    nome = loja.nome if loja is not None else plano.chave_loja
    return link_whatsapp(plano.whatsapp, texto_cobranca(nome, cobranca))


def estado(db: Session) -> dict:
    pendentes = db.query(Cobranca).filter(Cobranca.status.in_(("criando", "pendente"))).count()
    recentes = db.query(Cobranca).order_by(Cobranca.consultada_em.desc()).limit(50)
    return {
        "provedor": "mercadopago",
        "varredura_no_processo": varredura_habilitada(),
        "planos": db.query(Plano).count(),
        "assinaturas": db.query(Plano).filter(Plano.dia_vencimento.isnot(None)).count(),
        "cobrancas_pendentes": pendentes,
        "consultado_em": agora(),
        "cobrancas": [
            {"loja": c.chave_loja, "vencimento": c.vencimento, "status": c.status,
             "licenca_ate": c.licenca_ate, "tem_pix": bool(c.pix_copia_cola),
             "tem_boleto": bool(c.boleto_url or c.boleto_linha),
             "tem_checkout": bool(c.checkout_url),
             "whatsapp_link": _link_da_cobranca(db, c)}
            for c in recentes],
    }


def _imprimir(db: Session, cobranca: Cobranca) -> None:
    print(f"Cobrança {cobranca.id} da loja {cobranca.chave_loja}.")
    print(f"Vencimento {cobranca.vencimento}. Valor {cobranca.valor_cent} centavos. Situação {cobranca.status}.")
    if cobranca.boleto_url and cobranca.status != "aprovada":
        print(f"Boleto (PDF): {cobranca.boleto_url}")
    if cobranca.boleto_linha and cobranca.status != "aprovada":
        print(f"Linha digitável: {cobranca.boleto_linha}")
    if cobranca.boleto_erro:
        print(f"Aviso: boleto não gerado ({cobranca.boleto_erro}).", file=sys.stderr)
    if cobranca.pix_copia_cola and cobranca.status != "aprovada":
        print("Pix copia e cola:")
        print(cobranca.pix_copia_cola)
    if cobranca.pix_url and cobranca.status != "aprovada":
        print(f"Página do Pix (QR Code): {cobranca.pix_url}")
    if cobranca.checkout_url and cobranca.status != "aprovada":
        print(f"Link para cartão: {cobranca.checkout_url}")
    if cobranca.preference_erro:
        print(f"Aviso: Checkout Pro não foi gerado ({cobranca.preference_erro}). O Pix continua válido.",
              file=sys.stderr)
    link = _link_da_cobranca(db, cobranca)
    if link:
        print("WhatsApp (abra e envie; a API de WhatsApp não está configurada):")
        print(link)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    comandos = parser.add_subparsers(dest="comando", required=True)
    plano = comandos.add_parser("plano", help="Cadastrar ou atualizar a mensalidade da loja.")
    plano.add_argument("loja")
    plano.add_argument("valor_cent", type=int)
    plano.add_argument("email")
    gerar_cmd = comandos.add_parser("gerar", help="Gerar Pix, boleto (se houver dados) e link de cartão.")
    gerar_cmd.add_argument("loja")
    gerar_cmd.add_argument("vencimento", help="AAAA-MM-DD")
    assinatura = comandos.add_parser("assinatura", help="Cadastrar ou atualizar a mensalidade recorrente.")
    assinatura.add_argument("loja")
    assinatura.add_argument("valor_cent", type=int)
    assinatura.add_argument("dia", type=int, help="Dia do mês, de 1 a 31.")
    assinatura.add_argument("--email", required=True)
    assinatura.add_argument("--whatsapp", required=True)
    assinatura.add_argument("--nome", required=True, help="Nome completo do pagador do boleto.")
    assinatura.add_argument("--documento", required=True, help="CPF ou CNPJ.")
    assinatura.add_argument("--cep", required=True)
    assinatura.add_argument("--logradouro", required=True)
    assinatura.add_argument("--numero", required=True)
    assinatura.add_argument("--bairro", required=True)
    assinatura.add_argument("--cidade", required=True)
    assinatura.add_argument("--uf", required=True)
    assinatura.add_argument("--antecedencia", type=int, default=ANTECEDENCIA_PADRAO,
                            help="Dias antes do vencimento para gerar a cobrança (padrão 5).")
    parar = comandos.add_parser("assinatura-parar", help="Para de gerar cobranças novas desta loja.")
    parar.add_argument("loja")
    emitir = comandos.add_parser("emitir", help="Gera agora a cobrança que já está na janela do mês.")
    emitir.add_argument("loja")
    reenvio = comandos.add_parser("reenviar", help="Reenvia a cobrança atual por e-mail e WhatsApp.")
    reenvio.add_argument("loja")
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
                _imprimir(db, gerar(db, args.loja, vencimento, forcar=True))
            elif args.comando == "assinatura":
                situacao = definir_assinatura_mensal(
                    db, args.loja, args.valor_cent, args.dia, args.email, args.whatsapp, args.nome,
                    args.documento, args.cep, args.logradouro, args.numero, args.bairro, args.cidade,
                    args.uf, args.antecedencia)
                plano = db.query(Plano).filter_by(chave_loja=args.loja).one()
                emitidas = gerar_recorrencias(db, chave=args.loja)
                print(f"Assinatura {situacao} para {args.loja}: {args.valor_cent} centavos, "
                      f"vence todo dia {args.dia}.")
                print(f"Próximo vencimento: {resumo_assinatura(plano)['proximo_vencimento']}.")
                print(f"Cobranças emitidas agora: {emitidas}.")
                if emitidas == 0:
                    print("Fora da janela de emissão, nada foi gerado. Use emitir quando a data chegar, "
                          "ou aguarde a varredura do servidor.")
            elif args.comando == "assinatura-parar":
                parar_assinatura_mensal(db, args.loja)
                print(f"Assinatura mensal de {args.loja} interrompida. Cobranças já geradas continuam válidas.")
            elif args.comando == "emitir":
                quantidade = gerar_recorrencias(db, chave=args.loja)
                print(f"Cobranças emitidas: {quantidade}.")
                if quantidade == 0:
                    plano = db.query(Plano).filter_by(chave_loja=args.loja).first()
                    if plano and plano.dia_vencimento:
                        print(f"Nada na janela. Próximo vencimento: {resumo_assinatura(plano)['proximo_vencimento']}.")
            elif args.comando == "reenviar":
                resultado = reenviar(db, args.loja)
                print(f"Reenvio da cobrança {resultado['vencimento']}: e-mail {resultado['email']}, "
                      f"WhatsApp {resultado['whatsapp']}.")
                if resultado.get("boleto_url"):
                    print(f"Boleto (PDF): {resultado['boleto_url']}")
                if resultado.get("boleto_linha"):
                    print(f"Linha digitável: {resultado['boleto_linha']}")
                if resultado.get("whatsapp_link"):
                    print("WhatsApp (abra e envie):")
                    print(resultado["whatsapp_link"])
            elif args.comando == "conciliar":
                print(f"Pagamentos conciliados: {reconciliar(db, args.loja)}")
            else:
                planos = {p.chave_loja: p for p in db.query(Plano).order_by(Plano.chave_loja)}
                if not planos:
                    print("Nenhum plano Mercado Pago.")
                for chave, plano_loja in planos.items():
                    dia = f"  dia {plano_loja.dia_vencimento}" if plano_loja.dia_vencimento else ""
                    print(f"{chave}  {plano_loja.valor_cent} centavos{dia}")
                    for cobranca in db.query(Cobranca).filter_by(plano=plano_loja.id).order_by(Cobranca.vencimento):
                        print(f"  {cobranca.vencimento}  {cobranca.status}  "
                              f"pix={'sim' if cobranca.pix_copia_cola else 'não'}  "
                              f"boleto={'sim' if cobranca.boleto_url else 'não'}  "
                              f"checkout={'sim' if cobranca.checkout_url else 'não'}  "
                              f"licença={cobranca.licenca_ate or '—'}")
                        if cobranca.status != "aprovada" and cobranca.boleto_linha:
                            print(f"  linha digitável: {cobranca.boleto_linha}")
                        if cobranca.status != "aprovada" and cobranca.pix_copia_cola:
                            print(f"  copia e cola: {cobranca.pix_copia_cola}")
                        link = _link_da_cobranca(db, cobranca)
                        if link:
                            print(f"  whatsapp: {link}")
        except ErroCobranca as erro:
            db.rollback()
            print(f"Erro: {erro}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
