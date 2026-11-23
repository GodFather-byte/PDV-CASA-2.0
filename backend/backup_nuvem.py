"""Backup do caixa na nuvem: o banco inteiro (produtos, cadastros, vendas, configurações) para recuperar a loja num
computador novo se o do caixa queimar, travar ou sumir.

- O caixa manda o arquivo do backup local (o mesmo que ele já faz) compactado em gzip, no máximo a cada poucas horas.
  O corpo é o próprio gzip (sem base64); os cabeçalhos dizem a data, a versão do esquema e o SHA-256.
- Fica guardado no banco da nuvem, por loja: os 7 dias mais recentes (o último de cada dia) e o último de cada mês dos
  últimos 4 meses, sem passar de LIMITE_LOJA_BYTES por loja (o mais novo nunca sai).
- O caixa lista e baixa os da própria loja (token da loja). A central do fornecedor também (fica na auditoria).
"""
from __future__ import annotations

import gzip
import hashlib
import io
import re
from datetime import datetime

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy import Column, Integer, LargeBinary, String
from sqlalchemy.orm import Session, defer

from backend.database import Base, engine, get_db

LIMITE_ARQUIVO = 40 * 1024 * 1024          # gzip de um envio
LIMITE_LOJA_BYTES = 80 * 1024 * 1024       # soma guardada por loja
DIAS = 7
MESES = 4
CABECALHO_SQLITE = b"SQLite format 3\x00"
DATA_VALIDA = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class BackupNuvem(Base):
    __tablename__ = "backups_nuvem"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    feito_em = Column(String, nullable=False)          # hora do backup no caixa
    recebido_em = Column(String, nullable=False)
    esquema = Column(Integer, nullable=False, default=0)
    tamanho = Column(Integer, nullable=False)          # bytes do gzip
    tamanho_banco = Column(Integer, nullable=False)    # bytes do banco descompactado
    sha256 = Column(String, nullable=False)
    conteudo = Column(LargeBinary, nullable=False)


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conferir(dados: bytes, sha: str) -> int:
    """Valida o gzip e devolve o tamanho do banco descompactado. Levanta HTTPException 422."""
    if not dados or len(dados) > LIMITE_ARQUIVO:
        raise HTTPException(status_code=422, detail="Backup vazio ou grande demais.")
    if hashlib.sha256(dados).hexdigest() != (sha or "").lower():
        raise HTTPException(status_code=422, detail="O backup chegou incompleto (SHA-256 não confere). Tente de novo.")
    total = 0
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(dados)) as gz:
            inicio = gz.read(len(CABECALHO_SQLITE))
            if inicio != CABECALHO_SQLITE:
                raise HTTPException(status_code=422, detail="O arquivo não é um banco do caixa.")
            total = len(inicio)
            while bloco := gz.read(1024 * 1024):
                total += len(bloco)
                if total > LIMITE_ARQUIVO * 8:
                    raise HTTPException(status_code=422, detail="Banco grande demais para o backup na nuvem.")
    except (OSError, EOFError):
        raise HTTPException(status_code=422, detail="Backup compactado inválido.") from None
    return total


def podar(db: Session, chave_loja: str) -> int:
    """Mantém o último de cada um dos 7 dias mais recentes e o último de cada mês (4 meses), dentro do limite."""
    linhas = (db.query(BackupNuvem).options(defer(BackupNuvem.conteudo)).filter_by(chave_loja=chave_loja)
              .order_by(BackupNuvem.feito_em.desc(), BackupNuvem.id.desc()).all())
    manter, dias, meses = [], set(), set()
    for b in linhas:
        dia, mes = b.feito_em[:10], b.feito_em[:7]
        if dia not in dias and len(dias) < DIAS:
            dias.add(dia)
            meses.add(mes)
            manter.append(b)
        elif mes not in meses and len(meses) < MESES + 1:
            meses.add(mes)
            manter.append(b)
    soma, final = 0, []
    for b in manter:                                   # do mais novo ao mais velho
        if final and soma + b.tamanho > LIMITE_LOJA_BYTES:
            continue
        soma += b.tamanho
        final.append(b.id)
    apagar = [b.id for b in linhas if b.id not in final]
    if apagar:
        db.query(BackupNuvem).filter(BackupNuvem.id.in_(apagar)).delete(synchronize_session=False)
    return len(apagar)


def lista(db: Session, chave_loja: str) -> list[dict]:
    linhas = (db.query(BackupNuvem).options(defer(BackupNuvem.conteudo)).filter_by(chave_loja=chave_loja)
              .order_by(BackupNuvem.feito_em.desc(), BackupNuvem.id.desc()).all())
    return [{"id": b.id, "feito_em": b.feito_em, "recebido_em": b.recebido_em, "esquema": b.esquema,
             "tamanho": b.tamanho, "tamanho_banco": b.tamanho_banco} for b in linhas]


def _arquivo(db: Session, chave_loja: str, backup_id: int) -> Response:
    b = db.query(BackupNuvem).filter_by(id=backup_id, chave_loja=chave_loja).first()
    if b is None:
        raise HTTPException(status_code=404, detail="Backup não encontrado.")
    nome = re.sub(r"[^A-Za-z0-9_-]", "_", chave_loja) + "-" + re.sub(r"\D", "", b.feito_em)
    return Response(bytes(b.conteudo), media_type="application/gzip", headers={
        "Content-Disposition": f'attachment; filename="backup-{nome}.db.gz"', "Cache-Control": "no-store",
        "X-Backup-Sha256": b.sha256, "X-Backup-Esquema": str(b.esquema), "X-Backup-Feito-Em": b.feito_em})


def instalar(app: FastAPI, autenticar) -> APIRouter:
    Base.metadata.create_all(bind=engine)
    router = APIRouter()

    def loja_do_caixa(acesso=Depends(autenticar)) -> str:
        if acesso.admin:
            raise HTTPException(status_code=403, detail="Use o token da loja.")
        return acesso.loja

    @router.post("/v1/backup")
    async def receber(request: Request, chave_loja: str = Depends(loja_do_caixa), db: Session = Depends(get_db)):
        tamanho = int(request.headers.get("content-length") or 0)
        if tamanho > LIMITE_ARQUIVO:
            raise HTTPException(status_code=413, detail="Backup grande demais.")
        dados = await request.body()
        feito_em = request.headers.get("x-backup-feito-em", "")
        if not DATA_VALIDA.match(feito_em):
            raise HTTPException(status_code=422, detail="Informe a hora do backup.")
        try:
            esquema = int(request.headers.get("x-backup-esquema", "0"))
        except ValueError:
            esquema = 0
        sha = request.headers.get("x-backup-sha256", "")
        tamanho_banco = conferir(dados, sha)
        repetido = db.query(BackupNuvem.id).filter_by(chave_loja=chave_loja, sha256=sha.lower()).first()
        if repetido is None:
            db.add(BackupNuvem(chave_loja=chave_loja, feito_em=feito_em, recebido_em=_agora(), esquema=esquema,
                               tamanho=len(dados), tamanho_banco=tamanho_banco, sha256=sha.lower(), conteudo=dados))
            db.flush()
            podar(db, chave_loja)
        db.commit()
        return {"ok": True, "feito_em": feito_em}

    @router.get("/v1/backup/lista")
    def listar(chave_loja: str = Depends(loja_do_caixa), db: Session = Depends(get_db)):
        return {"backups": lista(db, chave_loja)}

    @router.get("/v1/backup/{backup_id}")
    def baixar(backup_id: int, chave_loja: str = Depends(loja_do_caixa), db: Session = Depends(get_db)):
        return _arquivo(db, chave_loja, backup_id)

    app.include_router(router)
    return router


def instalar_fornecedor(app: FastAPI, sessao, obter, auditar) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/fornecedor/lojas/{chave}/backups")
    def listar_loja(chave: str, _=Depends(sessao), db: Session = Depends(get_db)):
        return {"backups": lista(db, obter(db, chave).chave_loja)}

    @router.get("/v1/fornecedor/lojas/{chave}/backups/{backup_id}")
    def baixar_loja(chave: str, backup_id: int, _=Depends(sessao), db: Session = Depends(get_db)):
        loja = obter(db, chave).chave_loja
        resposta = _arquivo(db, loja, backup_id)
        auditar(db, "baixar_backup_nuvem", loja, str(backup_id))
        db.commit()
        return resposta

    app.include_router(router)
    return router
