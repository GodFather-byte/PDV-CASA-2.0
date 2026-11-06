"""Transferência explícita da emissão da ponte para o servidor, sem trocar a chave."""
from datetime import date, datetime
from uuid import uuid4

from fastapi import HTTPException
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


def renovar_ponte(db, chave):
    """Só lojas explicitamente transferidas. Mantém códigos anteriores e não reduz validade."""
    from backend import ponte
    from backend.main import Loja, semente_licenca
    from src.core import licenca
    if not habilitada(db, chave) or not ponte.em_modo_ponte(db, chave):
        return
    loja = db.query(Loja).filter_by(chave_loja=chave).with_for_update().first()
    if loja is None or not loja.ativa or not loja.licenca_ate:
        return
    hoje, validade = date.today(), date.fromisoformat(loja.licenca_ate)
    ultima = ponte._ultima(db, chave)
    if validade <= hoje or (ultima and ultima.expira_em >= validade.isoformat()):
        return
    if not chave_pronta():
        raise HTTPException(503, "A chave de emissão da nuvem precisa ser configurada.")
    codigo = licenca.gerar_licenca(semente_licenca(), chave, (validade - hoje).days, hoje)
    db.add(ponte.PonteLicenca(id=str(uuid4()), chave_loja=chave, codigo=codigo,
                             emitida_em=hoje.isoformat(), expira_em=validade.isoformat(),
                             publicada_em=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Duas consultas simultâneas podem produzir o mesmo código. Só aceita a corrida comprovada.
        existente = ponte._ultima(db, chave)
        if existente is None or existente.expira_em < validade.isoformat():
            raise
