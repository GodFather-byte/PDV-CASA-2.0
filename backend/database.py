import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker


def normalizar_url(url: str) -> str:
    """O endereço do PostgreSQL como o Neon, o Render e o Supabase entregam ('postgres://...' ou 'postgresql://...') vira o
    do driver instalado (psycopg 3). Os demais endereços passam sem mudança."""
    for prefixo in ("postgres://", "postgresql://"):
        if url.startswith(prefixo):
            return "postgresql+psycopg://" + url[len(prefixo):]
    return url


# Padrão: SQLite local (./pdv_casa.db). Em produção use PDV_NUVEM_DB_URL, por exemplo
# postgresql://usuario:senha@servidor/pdv (o endereço que o Neon/Render mostram, colado do jeito que vem)
SQLALCHEMY_DATABASE_URL = normalizar_url(os.environ.get("PDV_NUVEM_DB_URL") or "sqlite:///./pdv_casa.db")


def argumentos_engine(url: str) -> dict:
    """SQLite local não precisa de pool. No Postgres (Neon) a conexão ociosa se fecha sozinha:
    não há laço de keepalive. pool_pre_ping só testa na hora de usar, quando já vai ter consulta."""
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}, "pool_pre_ping": True}
    return {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 2,
        "max_overflow": 2,
        "pool_use_lifo": True,
    }


engine = create_engine(SQLALCHEMY_DATABASE_URL, **argumentos_engine(SQLALCHEMY_DATABASE_URL))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
