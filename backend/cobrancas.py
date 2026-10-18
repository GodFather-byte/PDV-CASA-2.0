"""Cobrança mensal de licenças pelo Asaas; nenhum segredo vai para o PDV."""
from __future__ import annotations

import argparse
import calendar
import json
import logging
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Session

from backend.database import Base

log = logging.getLogger("pdv.cobrancas")
IDENTIFICADOR = re.compile(r"[A-Za-z0-9_-]{1,100}")
PAGOS = {"CONFIRMED", "RECEIVED"}


class ErroCobranca(Exception):
    """Erro que deve ser mostrado ao administrador sem expor credenciais."""


class AsaasIndisponivel(ErroCobranca):
    pass


class Assinatura(Base):
    __tablename__ = "assinaturas_asaas"
    id = Column(String, primary_key=True)
    chave_loja = Column(String, unique=True, nullable=False, index=True)
    cliente = Column(String, nullable=False)
    valor_cent = Column(Integer, nullable=False)
    ambiente = Column(String, nullable=False)
    validade_anterior = Column(String, nullable=True)
    criada_em = Column(String, nullable=False)


class Cobranca(Base):
    __tablename__ = "cobrancas_asaas"
    id = Column(String, primary_key=True)
    assinatura = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)
    vencimento = Column(String, nullable=False)
    valor_cent = Column(Integer, nullable=False)
    licenca_ate = Column(String, nullable=True)
    url = Column(String, nullable=True)
    consultada_em = Column(String, nullable=False)


class Evento(Base):
    __tablename__ = "eventos_asaas"
    id = Column(String, primary_key=True)
    cobranca = Column(String, nullable=False)
    recebido_em = Column(String, nullable=False)


def agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ambiente() -> str:
    valor = os.environ.get("ASAAS_AMBIENTE", "sandbox")
    if valor not in ("sandbox", "producao"):
        raise ErroCobranca("ASAAS_AMBIENTE deve ser sandbox ou producao.")
    return valor


def identificador(valor: object, prefixo: str) -> str:
    if not isinstance(valor, str) or not valor.startswith(prefixo) or not IDENTIFICADOR.fullmatch(valor):
        raise ErroCobranca(f"Identificador {prefixo} inválido.")
    return valor


def centavos(valor: object) -> int:
    try:
        decimal = Decimal(str(valor)) * 100
        if not decimal.is_finite() or decimal <= 0 or decimal != decimal.to_integral_value():
            raise ValueError
        return int(decimal)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        raise ErroCobranca("Valor da cobrança deve ser positivo, com até duas casas decimais.") from None


def consultar(caminho: str) -> dict:
    token = os.environ.get("ASAAS_API_KEY", "").strip()
    if not token:
        raise AsaasIndisponivel("Configure ASAAS_API_KEY no servidor.")
    base = "https://api.asaas.com/v3" if ambiente() == "producao" else "https://api-sandbox.asaas.com/v3"
    requisicao = Request(base + caminho, headers={"access_token": token, "User-Agent": "WillPDV/1.0",
                                                  "Accept": "application/json"})
    try:
        with urlopen(requisicao, timeout=10) as resposta:
            dados = json.loads(resposta.read(), parse_float=Decimal)
    except HTTPError as erro:
        raise AsaasIndisponivel(f"Asaas recusou a consulta (HTTP {erro.code}); confira credenciais e logs do provedor.") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise AsaasIndisponivel("Não foi possível consultar o Asaas; tente novamente e confira a conexão.") from None
    if not isinstance(dados, dict):
        raise AsaasIndisponivel("O Asaas devolveu uma resposta inválida.")
    return dados


def vincular(db: Session, chave: str, assinatura_id: str, valor_cent: int) -> None:
    from backend.main import Loja
    identificador(assinatura_id, "sub_")
    if valor_cent <= 0:
        raise ErroCobranca("A mensalidade em centavos deve ser positiva.")
    loja = db.query(Loja).filter_by(chave_loja=chave).first()
    if loja is None:
        raise ErroCobranca("Loja não encontrada; cadastre-a com backend.lojas.")
    if db.query(Assinatura).filter(
            (Assinatura.id == assinatura_id) | (Assinatura.chave_loja == chave)).first():
        raise ErroCobranca("Loja ou assinatura já vinculada; não crie uma segunda cobrança.")
    dados = consultar(f"/subscriptions/{assinatura_id}")
    if (dados.get("id") != assinatura_id or dados.get("cycle") != "MONTHLY"
            or dados.get("billingType") not in ("PIX", "BOLETO", "UNDEFINED")
            or dados.get("status") != "ACTIVE" or centavos(dados.get("value")) != valor_cent):
        raise ErroCobranca("Confira a assinatura: deve estar ativa, mensal, por Pix/boleto e com o valor informado.")
    cliente = identificador(dados.get("customer"), "cus_")
    db.add(Assinatura(id=assinatura_id, chave_loja=chave, cliente=cliente, valor_cent=valor_cent,
                      ambiente=ambiente(), validade_anterior=loja.licenca_ate, criada_em=agora()))
    db.commit()


def fim_periodo(vencimento: date) -> date:
    """Um mês de calendário a partir do vencimento, inclusive; nunca a partir do recebimento do webhook."""
    ano = vencimento.year + (vencimento.month == 12)
    mes = vencimento.month % 12 + 1
    return date(ano, mes, min(vencimento.day, calendar.monthrange(ano, mes)[1]))


def processar(db: Session, assinatura_id: str, pagamento_id: str, evento_id: str | None = None,
              *, confirmar: bool = True) -> str:
    from backend.main import Loja
    identificador(assinatura_id, "sub_")
    identificador(pagamento_id, "pay_")
    if evento_id is not None:
        identificador(evento_id, "evt_")
    # Serializa a atualização de uma loja em PostgreSQL, inclusive a consulta remota:
    # uma resposta antiga não pode sobrescrever um estorno consultado por outra requisição.
    assinatura = db.query(Assinatura).filter_by(id=assinatura_id).with_for_update().first()
    if assinatura is None:
        log.warning("Cobrança recebida para assinatura não vinculada: %s.", assinatura_id)
        return "nao_vinculada"
    if assinatura.ambiente != ambiente():
        raise ErroCobranca("A assinatura pertence a outro ambiente Asaas.")
    if evento_id and db.get(Evento, evento_id):
        return "repetido"
    dados = consultar(f"/payments/{pagamento_id}")
    if (dados.get("id") != pagamento_id or dados.get("subscription") != assinatura.id
            or dados.get("customer") != assinatura.cliente):
        raise ErroCobranca("Cobrança não pertence à assinatura e ao cliente vinculados.")
    try:
        vencimento = date.fromisoformat(dados["dueDate"])
    except (KeyError, ValueError, TypeError):
        raise ErroCobranca("Asaas não informou um vencimento válido.") from None
    valor = centavos(dados.get("value"))
    if valor != assinatura.valor_cent or dados.get("billingType") not in ("PIX", "BOLETO"):
        raise ErroCobranca("Valor ou forma de pagamento diverge do plano; confira no Asaas antes de liberar.")
    status = dados.get("status")
    if not isinstance(status, str) or not status or len(status) > 100:
        raise ErroCobranca("Asaas não informou um status válido.")
    registro = db.get(Cobranca, pagamento_id)
    if registro is not None and registro.assinatura != assinatura.id:
        raise ErroCobranca("Cobrança já registrada para outra assinatura.")
    if registro is None:
        registro = Cobranca(id=pagamento_id, assinatura=assinatura.id)
        db.add(registro)
    registro.status, registro.vencimento, registro.valor_cent = status, vencimento.isoformat(), valor
    registro.licenca_ate = fim_periodo(vencimento).isoformat() if status in PAGOS and not dados.get("deleted") else None
    registro.url = dados.get("invoiceUrl") if isinstance(dados.get("invoiceUrl"), str) else None
    registro.consultada_em = agora()
    db.flush()
    datas = [c.licenca_ate for c in db.query(Cobranca).filter_by(assinatura=assinatura.id)
             if c.licenca_ate]
    if assinatura.validade_anterior:
        datas.append(assinatura.validade_anterior)
    loja = db.query(Loja).filter_by(chave_loja=assinatura.chave_loja).one()
    loja.licenca_ate = max(datas) if datas else None
    if evento_id:
        db.add(Evento(id=evento_id, cobranca=pagamento_id, recebido_em=agora()))
    if confirmar:
        db.commit()
        log.info("Cobrança %s conciliada: %s; loja %s.", pagamento_id, status, assinatura.chave_loja)
    return "processado"


def reconciliar(db: Session, chave: str, *, confirmar: bool = True) -> int:
    assinatura = db.query(Assinatura).filter_by(chave_loja=chave).with_for_update().first()
    if assinatura is None:
        raise ErroCobranca("Loja sem assinatura Asaas vinculada.")
    if assinatura.ambiente != ambiente():
        raise ErroCobranca("A assinatura pertence a outro ambiente Asaas.")
    assinatura_id = assinatura.id
    ids = set()
    offset = 0
    while True:
        pagina = consultar(f"/subscriptions/{assinatura_id}/payments?limit=100&offset={offset}")
        dados = pagina.get("data")
        if not isinstance(dados, list) or not isinstance(pagina.get("hasMore"), bool):
            raise AsaasIndisponivel("Listagem de cobranças inválida.")
        for pagamento in dados:
            if not isinstance(pagamento, dict):
                raise AsaasIndisponivel("Listagem de cobranças inválida.")
            ids.add(identificador(pagamento.get("id"), "pay_"))
        if not pagina["hasMore"]:
            break
        if not dados:
            raise AsaasIndisponivel("Paginação do Asaas não avançou.")
        offset += len(dados)
    # Inclui as já conhecidas: cobranças removidas podem desaparecer da listagem.
    ids.update(c.id for c in db.query(Cobranca).filter_by(assinatura=assinatura_id))
    for pagamento_id in sorted(ids):
        processar(db, assinatura_id, pagamento_id, confirmar=confirmar)
    return len(ids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    comandos = parser.add_subparsers(dest="comando", required=True)
    vinculo = comandos.add_parser("vincular", help="Vincular assinatura criada no painel Asaas.")
    vinculo.add_argument("loja")
    vinculo.add_argument("assinatura")
    vinculo.add_argument("valor_cent", type=int)
    conciliacao = comandos.add_parser("conciliar", help="Recuperar pagamentos sem webhook.")
    conciliacao.add_argument("loja")
    comandos.add_parser("listar", help="Mostrar vínculos, sem dados pessoais nem segredos.")
    args = parser.parse_args(argv)
    from backend.main import SessionLocal
    with SessionLocal() as db:
        try:
            if args.comando == "vincular":
                vincular(db, args.loja, args.assinatura, args.valor_cent)
                print("Assinatura vinculada. Execute conciliar para recuperar cobranças anteriores.")
            elif args.comando == "conciliar":
                print(f"Cobranças conciliadas: {reconciliar(db, args.loja)}")
            else:
                for assinatura in db.query(Assinatura).order_by(Assinatura.chave_loja):
                    print(f"{assinatura.chave_loja}  {assinatura.id}  {assinatura.valor_cent} centavos  {assinatura.ambiente}")
        except ErroCobranca as erro:
            db.rollback()
            print(f"Erro: {erro}", file=sys.stderr)
            return 1
    return 0
