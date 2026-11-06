"""Transferência explícita da emissão da ponte para o servidor, sem trocar a chave."""
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Column, String
from sqlalchemy.exc import IntegrityError

from backend.database import Base


class EmissaoNuvem(Base):
    __tablename__ = "fornecedor_emissao_nuvem"
    loja = Column(String(64), primary_key=True)
    habilitada_em = Column(String(19), nullable=False)


def chave_pronta():
    from backend.main import semente_licenca
    from src.core import ed25519, licenca
    semente = semente_licenca()
    return semente is not None and ed25519.chave_publica(semente).hex() == licenca.CHAVE_PUBLICA_HEX


def habilitada(db, chave):
    return db.get(EmissaoNuvem, chave) is not None


def edicao_da_loja(loja) -> str:
    """Programa da loja (willpdv, willadega...). Sem cadastro, o WillPDV, como sempre foi."""
    from src.core import edicao
    valor = (getattr(loja, "edicao", None) or "").strip().lower()
    return valor if valor in edicao.EDICOES else edicao.PADRAO


def edicao_do_codigo(codigo: str):
    """Programa gravado num código já publicado, ou None se ele não validar com a chave pública dos caixas."""
    from src.core import licenca
    try:
        return licenca.ler_licenca(codigo, bytes.fromhex(licenca.CHAVE_PUBLICA_HEX))["edicao"]
    except (licenca.LicencaInvalida, ValueError):
        return None


def assinar_ate(semente: bytes, chave: str, validade: date, edicao_programa: str, hoje: date | None = None):
    """Código da loja válido até `validade` (no máximo 100 anos), para o programa dela. Devolve (código, expira_em)."""
    from datetime import timedelta
    from src.core import licenca
    hoje = hoje or date.today()
    dias = min((validade - hoje).days, licenca.MAX_DIAS)
    if dias < 1:
        raise ValueError("A validade precisa ser futura.")
    return licenca.gerar_licenca(semente, chave, dias, hoje, edicao_programa), (hoje + timedelta(days=dias)).isoformat()


def renovar_ponte(db, chave):
    """Só lojas explicitamente transferidas. Mantém códigos anteriores e não reduz validade.

    Nunca derruba a consulta do caixa: sem a chave da nuvem, ou numa corrida entre dois pedidos, o caixa continua
    recebendo o último código publicado (o erro fica no log)."""
    import logging
    from backend import ponte
    from backend.main import Loja, semente_licenca
    log = logging.getLogger("pdv.nuvem")
    if not habilitada(db, chave) or not ponte.em_modo_ponte(db, chave):
        return
    loja = db.query(Loja).filter_by(chave_loja=chave).with_for_update().first()
    if loja is None or not loja.ativa or not loja.licenca_ate:
        return
    hoje, validade = date.today(), date.fromisoformat(loja.licenca_ate)
    ultima = ponte._ultima(db, chave)
    if validade <= hoje:
        return
    if not chave_pronta():
        log.error("Renovação da loja %s pendente: a chave de emissão da nuvem não está configurada.", chave)
        return
    codigo, expira = assinar_ate(semente_licenca(), chave, validade, edicao_da_loja(loja), hoje)
    if ultima and ultima.expira_em >= expira:
        return
    db.add(ponte.PonteLicenca(id=str(uuid4()), chave_loja=chave, codigo=codigo,
                             emitida_em=hoje.isoformat(), expira_em=expira,
                             publicada_em=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Duas consultas simultâneas produzem o mesmo código (assinatura determinística): a outra já publicou.
        existente = ponte._ultima(db, chave)
        if existente is None or existente.expira_em < expira:
            log.error("Renovação da loja %s não publicada por conflito; o caixa segue com o código anterior.", chave)
