"""Senha de gerente esquecida: a central assina a liberação e o caixa da loja pode buscá-la sozinho.

A regra e o formato ficam em `src/core/recuperacao_senha.py`. Aqui a nuvem só assina (com a chave das licenças,
a pedido do fornecedor autenticado na central) e guarda a liberação até vencer, para o caixa com internet não
precisar que alguém digite o código. Sem internet, o fornecedor passa o código e ele é colado no caixa.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db
from src.core import recuperacao_senha as regra


class LiberacaoSenha(Base):
    __tablename__ = "fornecedor_liberacoes_senha"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String(64), nullable=False, index=True)
    pedido = Column(String(16), nullable=False)
    codigo = Column(Text, nullable=False)
    criada_em = Column(String(19), nullable=False)
    expira_em = Column(String(19), nullable=False)


def _agora() -> str:
    return datetime.now().strftime(regra.FORMATO)


def emitir(db: Session, semente: bytes, chave_loja: str, pedido: str) -> dict:
    """Assina a liberação do `pedido` para a loja e a deixa disponível ao caixa. ValueError se o pedido é inválido."""
    pedido = regra.normalizar_pedido(pedido)
    codigo = regra.gerar_liberacao(semente, chave_loja, pedido)
    expira = regra.ler_liberacao(codigo)["expira_em"].strftime(regra.FORMATO)
    agora = _agora()
    db.query(LiberacaoSenha).filter(LiberacaoSenha.expira_em < agora).delete(synchronize_session=False)
    db.query(LiberacaoSenha).filter_by(chave_loja=chave_loja).delete(synchronize_session=False)   # só a última vale
    db.add(LiberacaoSenha(chave_loja=chave_loja, pedido=pedido, codigo=codigo, criada_em=agora, expira_em=expira))
    return {"codigo": codigo, "pedido": regra.formatar_pedido(pedido), "expira_em": expira}


def instalar(app: FastAPI, autenticar) -> None:
    Base.metadata.create_all(bind=engine)

    @app.get("/v1/recuperacao-senha")
    def buscar(pedido: str = "", acesso=Depends(autenticar), db: Session = Depends(get_db)):
        """O caixa pergunta se o fornecedor já liberou o pedido que ele mostra na tela."""
        if acesso.admin:
            raise HTTPException(status_code=403, detail="Use o token da loja.")
        pedido = regra.normalizar_pedido(pedido)
        linha = (db.query(LiberacaoSenha).filter_by(chave_loja=acesso.loja, pedido=pedido)
                 .filter(LiberacaoSenha.expira_em >= _agora()).first()) if pedido else None
        if linha is None:
            raise HTTPException(status_code=404, detail="O fornecedor ainda não liberou este pedido.")
        return {"codigo": linha.codigo, "expira_em": linha.expira_em}
