"""Ponte de licenças entre os caixas e a central do fornecedor (docs/CENTRAL_TELEGRAM.md, entrega 3).

A central roda no PC exclusivo do fornecedor, assina as licenças com a chave privada dele e só PUBLICA aqui códigos
já assinados. A ponte confere a assinatura com a chave pública, guarda o código e entrega ao caixa da loja. Ela nunca
emite licença nem cuida de cobrança ou faturamento.

Credenciais (escopos separados, nenhuma substitui a outra):
    PDV_CENTRAL_TOKEN   token da central, só nas rotas /v1/central/*. Não pode ser igual ao PDV_API_TOKEN.
    token do caixa      emitido por POST /v1/central/caixas (aparece uma única vez), só nas rotas /v1/ponte/*.

Uma loja entra no "modo ponte" na primeira publicação de código pela central. A partir daí o GET /v1/licenca antigo
(token da loja) entrega o último código publicado e nunca mais assina na nuvem para ela. As demais lojas seguem como
antes. Este módulo não importa backend.main (evita importação circular): `instalar(app, Loja, hash_token)`.
"""
from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
import uuid
from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr
from sqlalchemy import Boolean, Column, Integer, String, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db
from src.core import licenca as licenca_pdv
from src.versao import valida as versao_valida

log = logging.getLogger("pdv.ponte")

CHAVE_LOJA = re.compile(r"[A-Za-z0-9._-]{1,64}")
UUID_TEXTO = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
TOKEN_CENTRAL_MINIMO = 32
CODIGO_MAXIMO = 1024
PREFIXO_TOKEN_CAIXA = "pdvcx_"


# ---------------------------------------------------------------- tabelas
class PonteLoja(Base):
    """Loja que passou para o modo ponte (entra na primeira publicação da central e não volta sozinha)."""
    __tablename__ = "ponte_lojas"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String(64), unique=True, index=True, nullable=False)
    modo_ponte = Column(Boolean, nullable=False, default=True)
    ativado_em = Column(String(19), nullable=False)


class PonteCaixa(Base):
    """Caixa aprovado pela central. Guarda só o SHA-256 do token do caixa."""
    __tablename__ = "ponte_caixas"
    id = Column(Integer, primary_key=True)
    caixa_id = Column(String(36), unique=True, index=True, nullable=False)
    chave_loja = Column(String(64), index=True, nullable=False)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    revogado = Column(Boolean, nullable=False, default=False)
    criado_em = Column(String(19), nullable=False)
    revogado_em = Column(String(19), nullable=True)
    versao = Column(String(20), nullable=True)
    ultimo_contato = Column(String(19), nullable=True)
    licenca_aplicada_id = Column(String(36), nullable=True)


class PonteLicenca(Base):
    """Código assinado pela central e publicado para a loja. `seq` dá a ordem de publicação."""
    __tablename__ = "ponte_licencas"
    seq = Column(Integer, primary_key=True)
    id = Column(String(36), unique=True, index=True, nullable=False)
    chave_loja = Column(String(64), index=True, nullable=False)
    codigo = Column(String(CODIGO_MAXIMO), unique=True, nullable=False)
    emitida_em = Column(String(10), nullable=False)
    expira_em = Column(String(10), nullable=False)
    publicada_em = Column(String(19), nullable=False)


class PonteSolicitacao(Base):
    """Pedido do caixa (ex.: renovação). Não autoriza emissão: a central decide. Vira 'atendida' só quando o MESMO
    caixa confirma no contato ter aplicado uma licença publicada depois do pedido (`licenca_seq_base` guarda a última
    publicação da loja no momento do pedido)."""
    __tablename__ = "ponte_solicitacoes"
    seq = Column(Integer, primary_key=True)
    id = Column(String(36), unique=True, index=True, nullable=False)
    chave_loja = Column(String(64), index=True, nullable=False)
    caixa_id = Column(String(36), nullable=False)
    tipo = Column(String(20), nullable=False)
    situacao = Column(String(20), nullable=False, default="pendente")
    criada_em = Column(String(19), nullable=False)
    licenca_seq_base = Column(Integer, nullable=False, default=0)
    atendida_em = Column(String(19), nullable=True)
    licenca_id = Column(String(36), nullable=True)


# ------------------------------------------------------------- utilidades
def agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hoje() -> date:
    return date.today()


def chave_publica() -> bytes:
    """Chave pública do fornecedor, a mesma que o PDV usa. Os testes trocam por uma chave de teste."""
    return bytes.fromhex(licenca_pdv.CHAVE_PUBLICA_HEX)


def _uuid(texto: str, campo: str) -> str:
    if not isinstance(texto, str) or not UUID_TEXTO.fullmatch(texto):
        raise HTTPException(status_code=422, detail=f"{campo} deve ser um UUID.")
    return str(uuid.UUID(texto))


def _chave(texto: str) -> str:
    if not isinstance(texto, str) or not CHAVE_LOJA.fullmatch(texto):
        raise HTTPException(status_code=422,
                            detail="A chave da loja deve ter de 1 a 64 letras, números, ponto, hífen ou sublinhado.")
    return texto


def _bearer(authorization: Optional[str]) -> str:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:].strip()
    return ""


def _ultima(db: Session, chave_loja: str) -> Optional[PonteLicenca]:
    return (db.query(PonteLicenca).filter(PonteLicenca.chave_loja == chave_loja)
            .order_by(PonteLicenca.expira_em.desc(), PonteLicenca.seq.desc()).first())


def em_modo_ponte(db: Session, chave_loja: str) -> bool:
    modo = db.query(PonteLoja).filter(PonteLoja.chave_loja == chave_loja).first()
    return bool(modo and modo.modo_ponte)


def licenca_legado(db: Session, chave_loja: str) -> Optional[dict]:
    """Para o GET /v1/licenca antigo: None se a loja não está no modo ponte (segue o caminho antigo). No modo ponte,
    o último código publicado, sem nunca assinar na nuvem; sem código publicado, 404."""
    if not em_modo_ponte(db, chave_loja):
        return None
    lic = _ultima(db, chave_loja)
    if lic is None:
        raise HTTPException(status_code=404, detail="Nenhuma licença publicada pela central para esta loja.")
    return {"codigo": lic.codigo, "expira_em": lic.expira_em}


# ----------------------------------------------------------------- corpos
class _Corpo(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CorpoLoja(_Corpo):
    nome: StrictStr = Field(min_length=1, max_length=100)
    ativa: StrictBool


class CorpoCaixa(_Corpo):
    chave_loja: StrictStr = Field(min_length=1, max_length=64)
    caixa_id: StrictStr = Field(min_length=36, max_length=36)


class CorpoLicenca(_Corpo):
    id: StrictStr = Field(min_length=36, max_length=36)
    chave_loja: StrictStr = Field(min_length=1, max_length=64)
    codigo: StrictStr = Field(min_length=1, max_length=CODIGO_MAXIMO)


class CorpoContato(_Corpo):
    versao: StrictStr = Field(min_length=1, max_length=20)
    licenca_aplicada_id: Optional[StrictStr] = Field(min_length=36, max_length=36)


class CorpoSolicitacao(_Corpo):
    id: StrictStr = Field(min_length=36, max_length=36)
    tipo: Literal["renovacao"]


# ----------------------------------------------------------------- rotas
def instalar(app: FastAPI, Loja, hash_token) -> APIRouter:
    """Cria as tabelas e registra as rotas /v1/central/* e /v1/ponte/*. `Loja` e `hash_token` vêm do backend.main."""
    Base.metadata.create_all(bind=engine)
    router = APIRouter()

    def autenticar_central(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> None:
        central = os.environ.get("PDV_CENTRAL_TOKEN", "").strip()
        admin = os.environ.get("PDV_API_TOKEN", "").strip()
        if len(central) < TOKEN_CENTRAL_MINIMO or (admin and hmac.compare_digest(central.encode(), admin.encode())):
            raise HTTPException(status_code=503, detail="Central não configurada: defina um PDV_CENTRAL_TOKEN próprio "
                                                        f"com pelo menos {TOKEN_CENTRAL_MINIMO} caracteres.")
        token = _bearer(authorization)
        if not token or not hmac.compare_digest(token.encode("utf-8"), central.encode("utf-8")):
            raise HTTPException(status_code=401, detail="Token da central inválido.")
        h = hash_token(token)
        if (db.query(Loja.id).filter(Loja.token_hash == h).first() is not None
                or db.query(PonteCaixa.id).filter(PonteCaixa.token_hash == h).first() is not None):
            raise HTTPException(status_code=503, detail="Central mal configurada: o PDV_CENTRAL_TOKEN coincide com "
                                                        "outra credencial. Troque-o.")

    def autenticar_caixa(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> PonteCaixa:
        token = _bearer(authorization)
        caixa = None
        if token.startswith(PREFIXO_TOKEN_CAIXA):
            caixa = db.query(PonteCaixa).filter(PonteCaixa.token_hash == hash_token(token)).first()
        if caixa is None:
            raise HTTPException(status_code=401, detail="Token do caixa inválido.")
        if caixa.revogado:
            raise HTTPException(status_code=403, detail="Credencial do caixa revogada.")
        loja = db.query(Loja).filter(Loja.chave_loja == caixa.chave_loja).first()
        if loja is None or not loja.ativa:
            raise HTTPException(status_code=403, detail="Loja desativada ou não cadastrada.")
        return caixa

    def _loja(db: Session, chave: str):
        loja = db.query(Loja).filter(Loja.chave_loja == chave).first()
        if loja is None:
            raise HTTPException(status_code=404, detail="Loja não cadastrada.")
        return loja

    def _licenca_ate(db: Session, loja) -> Optional[str]:
        if em_modo_ponte(db, loja.chave_loja):
            lic = _ultima(db, loja.chave_loja)
            return lic.expira_em if lic else None
        return loja.licenca_ate

    def _dados_loja(db: Session, loja) -> dict:
        return {"chave_loja": loja.chave_loja, "nome": loja.nome, "ativa": bool(loja.ativa),
                "licenca_ate": _licenca_ate(db, loja)}

    # ---- central (PDV_CENTRAL_TOKEN)
    @router.get("/v1/central/lojas", dependencies=[Depends(autenticar_central)])
    def central_lojas(db: Session = Depends(get_db)):
        return {"lojas": [_dados_loja(db, l) for l in db.query(Loja).order_by(Loja.chave_loja).all()]}

    @router.put("/v1/central/lojas/{chave_loja}", dependencies=[Depends(autenticar_central)])
    def central_salvar_loja(chave_loja: str, corpo: CorpoLoja, db: Session = Depends(get_db)):
        chave = _chave(chave_loja)
        nome = corpo.nome.strip()
        if not nome:
            raise HTTPException(status_code=422, detail="Informe o nome da loja.")
        loja = db.query(Loja).filter(Loja.chave_loja == chave).first()
        if loja is None:
            parecidas = [l.chave_loja for l in db.query(Loja.chave_loja).all()
                         if l.chave_loja.casefold() == chave.casefold()]
            if parecidas:
                raise HTTPException(status_code=409, detail="Já existe loja com essa chave em outra grafia.")
            # Token inacessível: ninguém conhece o segredo, então a loja nova não autentica pela rota antiga.
            loja = Loja(chave_loja=chave, nome=nome, ativa=corpo.ativa, criada_em=agora(),
                        token_hash=hash_token(secrets.token_urlsafe(48)))
            db.add(loja)
        else:
            loja.nome, loja.ativa = nome, corpo.ativa
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="A loja foi alterada ao mesmo tempo; tente de novo.") from None
        log.info("Central salvou a loja %s (ativa=%s).", chave, corpo.ativa)
        return _dados_loja(db, loja)

    @router.post("/v1/central/caixas", dependencies=[Depends(autenticar_central)])
    def central_novo_caixa(corpo: CorpoCaixa, db: Session = Depends(get_db)):
        chave = _chave(corpo.chave_loja)
        caixa_id = _uuid(corpo.caixa_id, "caixa_id")
        loja = _loja(db, chave)
        if not loja.ativa:
            raise HTTPException(status_code=409, detail="Loja desativada: ative antes de aprovar caixas.")
        if db.query(PonteCaixa.id).filter(PonteCaixa.caixa_id == caixa_id).first() is not None:
            raise HTTPException(status_code=409, detail="Caixa já cadastrado: a credencial não é reemitida. "
                                                        "Revogue e aprove um novo caixa_id.")
        token = PREFIXO_TOKEN_CAIXA + secrets.token_urlsafe(32)
        db.add(PonteCaixa(caixa_id=caixa_id, chave_loja=chave, token_hash=hash_token(token), revogado=False,
                          criado_em=agora()))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Caixa já cadastrado: a credencial não é reemitida.") from None
        log.info("Central aprovou o caixa %s da loja %s.", caixa_id, chave)
        return {"token": token}

    @router.post("/v1/central/caixas/{caixa_id}/revogar", dependencies=[Depends(autenticar_central)])
    def central_revogar_caixa(caixa_id: str, db: Session = Depends(get_db)):
        caixa_id = _uuid(caixa_id, "caixa_id")
        caixa = db.query(PonteCaixa).filter(PonteCaixa.caixa_id == caixa_id).first()
        if caixa is None:
            raise HTTPException(status_code=404, detail="Caixa não cadastrado.")
        if not caixa.revogado:
            caixa.revogado, caixa.revogado_em = True, agora()
            db.commit()
            log.info("Central revogou o caixa %s.", caixa_id)
        return {"caixa_id": caixa.caixa_id, "revogado": True}

    @router.get("/v1/central/estado", dependencies=[Depends(autenticar_central)])
    def central_estado(db: Session = Depends(get_db)):
        return {
            "caixas": [{"caixa_id": c.caixa_id, "chave_loja": c.chave_loja, "revogado": bool(c.revogado),
                        "versao": c.versao, "ultimo_contato": c.ultimo_contato,
                        "licenca_aplicada_id": c.licenca_aplicada_id}
                       for c in db.query(PonteCaixa).order_by(PonteCaixa.chave_loja, PonteCaixa.id).all()],
            "licencas": [{"id": l.id, "chave_loja": l.chave_loja, "codigo": l.codigo, "expira_em": l.expira_em}
                         for l in db.query(PonteLicenca).order_by(PonteLicenca.seq).all()],
            "solicitacoes": [{"id": s.id, "chave_loja": s.chave_loja, "caixa_id": s.caixa_id, "tipo": s.tipo,
                              "situacao": s.situacao, "criada_em": s.criada_em, "atendida_em": s.atendida_em,
                              "licenca_id": s.licenca_id}
                             for s in db.query(PonteSolicitacao).order_by(PonteSolicitacao.seq).all()],
        }

    @router.post("/v1/central/licencas", dependencies=[Depends(autenticar_central)])
    def central_publicar(corpo: CorpoLicenca, db: Session = Depends(get_db)):
        lic_id = _uuid(corpo.id, "id")
        chave = _chave(corpo.chave_loja)
        codigo = "".join(corpo.codigo.split())

        def resposta(lic: PonteLicenca) -> dict:
            return {"id": lic.id, "chave_loja": lic.chave_loja, "expira_em": lic.expira_em}

        existente = db.query(PonteLicenca).filter(PonteLicenca.id == lic_id).first()
        if existente is not None:
            if existente.chave_loja == chave and existente.codigo == codigo:
                return resposta(existente)
            raise HTTPException(status_code=409, detail="Este id já foi publicado com outro conteúdo.")
        # Trava a loja (PostgreSQL) para duas publicações simultâneas não furarem a regra do prazo que não retrocede.
        loja = db.query(Loja).filter(Loja.chave_loja == chave).with_for_update().first()
        if loja is None:
            raise HTTPException(status_code=404, detail="Loja não cadastrada.")
        if not loja.ativa:
            raise HTTPException(status_code=409, detail="Loja desativada: ative antes de publicar licenças.")
        try:
            dados = licenca_pdv.ler_licenca(codigo, chave_publica())
        except licenca_pdv.LicencaInvalida:
            raise HTTPException(status_code=422, detail="Código de licença inválido ou com assinatura que não confere.") from None
        if not licenca_pdv.mesma_loja(dados["loja"], chave):
            raise HTTPException(status_code=422, detail="O código foi emitido para outra loja.")
        if dados["expira_em"] < hoje():
            raise HTTPException(status_code=422, detail="O código já está vencido.")
        if db.query(PonteLicenca.seq).filter(PonteLicenca.codigo == codigo).first() is not None:
            raise HTTPException(status_code=409, detail="Este código já foi publicado com outro id.")
        ultima = _ultima(db, chave)
        expira = dados["expira_em"].isoformat()
        if ultima is not None and expira < ultima.expira_em:
            raise HTTPException(status_code=409, detail="O prazo não pode retroceder: já existe licença publicada "
                                                        f"até {ultima.expira_em}.")
        momento = agora()
        lic = PonteLicenca(id=lic_id, chave_loja=chave, codigo=codigo, emitida_em=dados["emitida_em"].isoformat(),
                           expira_em=expira, publicada_em=momento)
        db.add(lic)
        if db.query(PonteLoja).filter(PonteLoja.chave_loja == chave).first() is None:
            db.add(PonteLoja(chave_loja=chave, modo_ponte=True, ativado_em=momento))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            repetida = db.query(PonteLicenca).filter(PonteLicenca.id == lic_id).first()
            if repetida is not None and repetida.chave_loja == chave and repetida.codigo == codigo:
                return resposta(repetida)
            raise HTTPException(status_code=409, detail="Publicação concorrente em conflito; consulte o estado.") from None
        log.info("Central publicou a licença %s da loja %s até %s.", lic_id, chave, expira)
        return resposta(lic)

    # ---- caixa (token do caixa)
    @router.get("/v1/ponte/licenca")
    def ponte_licenca(caixa: PonteCaixa = Depends(autenticar_caixa), db: Session = Depends(get_db)):
        lic = _ultima(db, caixa.chave_loja)
        if lic is None:
            raise HTTPException(status_code=404, detail="Nenhuma licença publicada para esta loja.")
        return {"id": lic.id, "codigo": lic.codigo, "expira_em": lic.expira_em}

    @router.post("/v1/ponte/contato")
    def ponte_contato(corpo: CorpoContato, caixa: PonteCaixa = Depends(autenticar_caixa),
                      db: Session = Depends(get_db)):
        versao = corpo.versao.strip()
        if not versao_valida(versao):
            raise HTTPException(status_code=422, detail="Versão inválida.")
        aplicada = lic = None
        if corpo.licenca_aplicada_id is not None:
            aplicada = _uuid(corpo.licenca_aplicada_id, "licenca_aplicada_id")
            lic = db.query(PonteLicenca).filter(PonteLicenca.id == aplicada,
                                                PonteLicenca.chave_loja == caixa.chave_loja).first()
            if lic is None:
                raise HTTPException(status_code=422, detail="Licença aplicada não foi publicada para esta loja.")
        momento = agora()
        caixa.versao, caixa.licenca_aplicada_id, caixa.ultimo_contato = versao, aplicada, momento
        if lic is not None:
            atendidas = (db.query(PonteSolicitacao)
                         .filter(PonteSolicitacao.caixa_id == caixa.caixa_id,
                                 PonteSolicitacao.chave_loja == caixa.chave_loja,
                                 PonteSolicitacao.situacao == "pendente",
                                 PonteSolicitacao.licenca_seq_base < lic.seq)
                         .update({"situacao": "atendida", "atendida_em": momento, "licenca_id": lic.id},
                                 synchronize_session=False))
            if atendidas:
                log.info("Caixa %s aplicou a licença %s: %s pedido(s) atendido(s).", caixa.caixa_id, lic.id, atendidas)
        db.commit()
        return {"caixa_id": caixa.caixa_id, "ultimo_contato": caixa.ultimo_contato}

    @router.post("/v1/ponte/solicitacoes")
    def ponte_solicitacao(corpo: CorpoSolicitacao, caixa: PonteCaixa = Depends(autenticar_caixa),
                          db: Session = Depends(get_db)):
        sol_id = _uuid(corpo.id, "id")

        def conferir(sol: PonteSolicitacao) -> dict:
            if sol.caixa_id != caixa.caixa_id or sol.chave_loja != caixa.chave_loja or sol.tipo != corpo.tipo:
                raise HTTPException(status_code=409, detail="Este id já foi usado em outra solicitação.")
            return {"id": sol.id, "situacao": sol.situacao}

        existente = db.query(PonteSolicitacao).filter(PonteSolicitacao.id == sol_id).first()
        if existente is not None:
            return conferir(existente)
        ultima = (db.query(func.max(PonteLicenca.seq))
                  .filter(PonteLicenca.chave_loja == caixa.chave_loja).scalar())
        sol = PonteSolicitacao(id=sol_id, chave_loja=caixa.chave_loja, caixa_id=caixa.caixa_id, tipo=corpo.tipo,
                               situacao="pendente", criada_em=agora(), licenca_seq_base=ultima or 0)
        db.add(sol)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            repetida = db.query(PonteSolicitacao).filter(PonteSolicitacao.id == sol_id).first()
            if repetida is None:
                raise HTTPException(status_code=409, detail="Solicitação em conflito; tente de novo.") from None
            return conferir(repetida)
        log.info("Caixa %s pediu %s (solicitação %s).", caixa.caixa_id, corpo.tipo, sol_id)
        return {"id": sol.id, "situacao": sol.situacao}

    app.include_router(router)
    return router
