"""Publicação das versões do PDV: os caixas conectados à nuvem avisam o dono da loja quando há versão nova.

    python -m backend.atualizacoes publicar 1.2.0 --notas "Corrige o troco em dinheiro." --url https://.../WillPDV-1.2.0.zip
    python -m backend.atualizacoes publicar 1.2.1 --notas "Corrige perda de vendas." --critica
    python -m backend.atualizacoes listar
    python -m backend.atualizacoes remover 1.2.0

--critica: o aviso aparece em vermelho e o dono não pode dispensá-lo (use para correções de dinheiro ou dados).
--url: onde baixar; sem ela vale a URL da versão mais nova que tiver uma.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from sqlalchemy.orm import Session

from backend.main import SessionLocal, Versao
from src.versao import chave, valida


class ErroVersao(Exception):
    pass


def publicar(db: Session, versao: str, notas: str, url: str | None = None, critica: bool = False) -> Versao:
    versao, notas, url = (versao or "").strip(), (notas or "").strip(), (url or "").strip() or None
    if not valida(versao):
        raise ErroVersao(f"Versão inválida: {versao!r}. Use números separados por ponto, ex.: 1.2.0.")
    if not notas:
        raise ErroVersao("Escreva as notas da versão (o que mudou): é o que o dono da loja vai ler.")
    if url and not url.startswith(("https://", "http://")):
        raise ErroVersao("A URL de download deve começar com https://.")
    if db.query(Versao).filter(Versao.versao == versao).first() is not None:
        raise ErroVersao(f"A versão {versao} já foi publicada. Remova antes para publicar de novo.")
    v = Versao(versao=versao, notas=notas, url_download=url, critica=critica,
               publicada_em=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    db.add(v)
    db.commit()
    return v


def remover(db: Session, versao: str) -> None:
    v = db.query(Versao).filter(Versao.versao == (versao or "").strip()).first()
    if v is None:
        raise ErroVersao(f"Versão {versao} não encontrada.")
    db.delete(v)
    db.commit()


def listar(db: Session) -> list[Versao]:
    return sorted(db.query(Versao).all(), key=lambda v: chave(v.versao), reverse=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m backend.atualizacoes", description="Versões do PDV publicadas na nuvem.")
    sub = p.add_subparsers(dest="comando", required=True)
    pub = sub.add_parser("publicar")
    pub.add_argument("versao")
    pub.add_argument("--notas", required=True)
    pub.add_argument("--url")
    pub.add_argument("--critica", action="store_true")
    sub.add_parser("listar")
    rem = sub.add_parser("remover")
    rem.add_argument("versao")
    try:
        args = p.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:
        return int(e.code or 0)
    db = SessionLocal()
    try:
        if args.comando == "publicar":
            v = publicar(db, args.versao, args.notas, args.url, args.critica)
            print(f"Versão {v.versao} publicada{' como CRÍTICA' if v.critica else ''}. Os caixas avisam na próxima consulta.")
        elif args.comando == "remover":
            remover(db, args.versao)
            print(f"Versão {args.versao} removida.")
        else:
            versoes = listar(db)
            for v in versoes:
                print(f"{v.versao:<10} {v.publicada_em or '':<19} {'CRÍTICA ' if v.critica else '        '} {v.notas[:60]}")
            if not versoes:
                print("Nenhuma versão publicada.")
    except ErroVersao as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
