"""Pacote de atualização do programa, por edição e canal.

O instalador grande não deve passar pelo Render (o pedido estoura o tempo e o disco é efêmero).
O manifesto assinado aponta para um HTTPS público (Cloudflare R2 ou equivalente). Se o arquivo
estiver em PDV_ATUALIZACAO_DIR, a própria nuvem também o entrega em /v1/atualizacao/arquivo.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import Column, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db
from src.atualizacao.manifesto import CANAIS, CHAVE_PUBLICA_HEX, EDICOES, conferir
from src.versao import chave, mais_nova, valida


class PacoteAtualizacao(Base):
    __tablename__ = "pacotes_atualizacao"
    __table_args__ = (UniqueConstraint("edicao", "canal", "versao", name="ux_pacote_atualizacao"),)
    id = Column(Integer, primary_key=True)
    edicao = Column(String, index=True, nullable=False)
    canal = Column(String, index=True, nullable=False)
    versao = Column(String, nullable=False)
    sha256 = Column(String, nullable=False)
    tamanho = Column(Integer, nullable=False)
    url = Column(String, nullable=False)
    notas = Column(Text, nullable=False, default="")
    obrigatoria = Column(Integer, nullable=False, default=0)
    minima = Column(String, nullable=False, default="")
    assinatura = Column(String, nullable=False)
    publicada_em = Column(String, nullable=False)


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def pasta_arquivos() -> Path:
    return Path(os.environ.get("PDV_ATUALIZACAO_DIR") or "atualizacoes")


def _chave_publica() -> str:
    # PDV_ATUALIZACAO_PUBLICA só existe nos testes. No Render ela fica vazia.
    return (os.environ.get("PDV_ATUALIZACAO_PUBLICA") or "").strip() or CHAVE_PUBLICA_HEX


def publicar(db: Session, pacote: dict) -> PacoteAtualizacao:
    if pacote.get("edicao") not in EDICOES or pacote.get("canal") not in CANAIS:
        raise ValueError("Edição ou canal inválido.")
    if not valida(str(pacote.get("versao") or "")):
        raise ValueError("Versão inválida.")
    minima = str(pacote.get("minima") or "")
    if minima and not valida(minima):
        raise ValueError("Versão mínima inválida.")
    url = str(pacote.get("url") or "").strip()
    if not url.startswith(("/", "https://", "http://")):
        raise ValueError("A URL de download deve ser HTTPS ou um caminho da própria nuvem.")
    sha = str(pacote.get("sha256") or "").lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("SHA-256 inválido.")
    try:
        tamanho = int(pacote.get("tamanho"))
    except (TypeError, ValueError):
        raise ValueError("Tamanho inválido.") from None
    if tamanho <= 0:
        raise ValueError("Tamanho inválido.")
    limpo = {
        "edicao": pacote["edicao"], "canal": pacote["canal"], "versao": str(pacote["versao"]).strip(),
        "sha256": sha, "tamanho": tamanho, "url": url, "notas": str(pacote.get("notas") or ""),
        "obrigatoria": 1 if pacote.get("obrigatoria") else 0, "minima": minima,
        "assinatura": str(pacote.get("assinatura") or ""),
    }
    if not conferir(limpo, _chave_publica()):
        raise ValueError("Assinatura inválida.")
    linha = db.query(PacoteAtualizacao).filter_by(
        edicao=limpo["edicao"], canal=limpo["canal"], versao=limpo["versao"]).first()
    if linha is None:
        linha = PacoteAtualizacao(edicao=limpo["edicao"], canal=limpo["canal"], versao=limpo["versao"])
        db.add(linha)
    for campo, valor in limpo.items():
        setattr(linha, campo, valor)
    linha.publicada_em = _agora()
    db.commit()
    return linha


def ultima(db: Session, edicao: str, canal: str) -> PacoteAtualizacao | None:
    linhas = db.query(PacoteAtualizacao).filter_by(edicao=edicao, canal=canal).all()
    if not linhas:
        return None
    return max(linhas, key=lambda linha: chave(linha.versao))


def resposta_publica(linha: PacoteAtualizacao, versao_instalada: str | None) -> dict:
    pacote = {
        "edicao": linha.edicao, "canal": linha.canal, "versao": linha.versao, "sha256": linha.sha256,
        "tamanho": linha.tamanho, "url": linha.url, "notas": linha.notas or "",
        "obrigatoria": int(linha.obrigatoria or 0), "minima": linha.minima or "",
        "assinatura": linha.assinatura,
    }
    if (versao_instalada and valida(versao_instalada) and pacote["minima"] and valida(pacote["minima"])
            and chave(versao_instalada) < chave(pacote["minima"])):
        pacote["obrigatoria"] = 1
    disponivel = not versao_instalada or not valida(versao_instalada) or mais_nova(linha.versao, versao_instalada)
    return {"disponivel": disponivel, "pacote": pacote}


def instalar_no_app(app: FastAPI, autenticar) -> None:
    Base.metadata.create_all(bind=engine)

    @app.get("/v1/atualizacao/ultima")
    def ler_ultima(edicao: str = Query(..., max_length=40), canal: str = Query("estavel", max_length=20),
                   versao: str = Query("", max_length=20), db: Session = Depends(get_db)):
        if edicao not in EDICOES or canal not in CANAIS:
            raise HTTPException(status_code=422, detail="Edição ou canal inválido.")
        linha = ultima(db, edicao, canal)
        if linha is None:
            return {"disponivel": False, "pacote": None}
        return resposta_publica(linha, versao or None)

    @app.post("/v1/admin/atualizacao")
    def admin_publicar(dados: dict = Body(...), acesso=Depends(autenticar), db: Session = Depends(get_db)):
        if not acesso.admin:
            raise HTTPException(status_code=403, detail="Só o administrador publica atualização.")
        try:
            linha = publicar(db, dados)
        except ValueError as erro:
            raise HTTPException(status_code=422, detail=str(erro)) from None
        return {"edicao": linha.edicao, "canal": linha.canal, "versao": linha.versao}

    @app.get("/v1/atualizacao/arquivo")
    def arquivo(edicao: str = Query(...), canal: str = Query("estavel"), versao: str = Query(...),
                db: Session = Depends(get_db)):
        linha = db.query(PacoteAtualizacao).filter_by(edicao=edicao, canal=canal, versao=versao).first()
        if linha is None:
            raise HTTPException(status_code=404, detail="Pacote não publicado.")
        caminho = pasta_arquivos() / edicao / canal / f"{versao}.exe"
        if not caminho.is_file():
            raise HTTPException(status_code=404, detail="Arquivo não está neste servidor.")
        digest = hashlib.sha256(caminho.read_bytes()).hexdigest()
        if digest != linha.sha256 or caminho.stat().st_size != int(linha.tamanho):
            raise HTTPException(status_code=409, detail="O arquivo no servidor não confere com o publicado.")
        return FileResponse(caminho, media_type="application/octet-stream", filename=caminho.name)
