"""Dono com várias lojas: um painel só.

O dono entra por uma loja e vincula as outras informando a chave e a senha do painel de cada uma (é a prova de que
a loja é dele). As lojas vinculadas formam um grupo. Dentro do grupo ele vê o resumo de todas e troca de loja sem
digitar senha de novo.

Trocar de loja abre uma sessão NOVA para a loja escolhida e encerra a atual. Assim cada resposta guardada no cache
de leitura (que usa o token como chave) continua valendo só para a loja a que pertence.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db

MAXIMO_LOJAS = 20


class PainelGrupo(Base):
    """Uma linha por loja vinculada; lojas com o mesmo `grupo` aparecem juntas no painel."""
    __tablename__ = "painel_grupos"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, unique=True, index=True, nullable=False)
    grupo = Column(String, index=True, nullable=False)
    vinculada_em = Column(String, nullable=False)


def lojas_do_grupo(db: Session, chave_loja: str) -> list[str]:
    """As chaves das lojas que este dono enxerga (a própria sempre entra), em ordem alfabética."""
    linha = db.query(PainelGrupo).filter_by(chave_loja=chave_loja).first()
    if linha is None:
        return [chave_loja]
    chaves = [g.chave_loja for g in db.query(PainelGrupo).filter_by(grupo=linha.grupo)]
    return sorted(set(chaves) | {chave_loja})


def vincular(db: Session, chave_a: str, chave_b: str, agora: str) -> list[str]:
    """Junta as duas lojas (e os grupos em que cada uma já está) num grupo só."""
    if chave_a == chave_b:
        raise HTTPException(status_code=409, detail="Esta loja já é a que você está vendo.")
    a = db.query(PainelGrupo).filter_by(chave_loja=chave_a).first()
    b = db.query(PainelGrupo).filter_by(chave_loja=chave_b).first()
    if a is not None and b is not None and a.grupo == b.grupo:
        raise HTTPException(status_code=409, detail="Esta loja já está no seu painel.")
    juntas = set(lojas_do_grupo(db, chave_a)) | set(lojas_do_grupo(db, chave_b))
    if len(juntas) > MAXIMO_LOJAS:
        raise HTTPException(status_code=409, detail=f"O painel reúne no máximo {MAXIMO_LOJAS} lojas.")
    grupo = a.grupo if a is not None else (b.grupo if b is not None else secrets.token_hex(12))
    for chave in juntas:
        linha = db.query(PainelGrupo).filter_by(chave_loja=chave).first()
        if linha is None:
            db.add(PainelGrupo(chave_loja=chave, grupo=grupo, vinculada_em=agora))
        else:
            linha.grupo = grupo
    db.flush()
    return sorted(juntas)


def desvincular(db: Session, chave_loja: str) -> None:
    """Tira a loja do grupo. Grupo que ficaria com uma loja só deixa de existir."""
    linha = db.query(PainelGrupo).filter_by(chave_loja=chave_loja).first()
    if linha is None:
        return
    grupo = linha.grupo
    db.delete(linha)
    db.flush()
    restantes = db.query(PainelGrupo).filter_by(grupo=grupo).all()
    if len(restantes) == 1:
        db.delete(restantes[0])
        db.flush()


def instalar(app: FastAPI, Loja) -> APIRouter:
    from backend import painel
    from backend import painel_devolucoes as devolucoes
    Base.metadata.create_all(bind=engine)
    router = APIRouter()

    def sessao_ativa(sessao: painel.PainelSessao = Depends(painel.sessao_do_dono), db: Session = Depends(get_db)):
        loja = db.query(Loja).filter(Loja.chave_loja == sessao.chave_loja).first()
        if loja is None or not loja.ativa:
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        return sessao

    def _resumo(db: Session, loja, atual: bool) -> dict:
        """Os números da loja no dia operacional dela e no mês até esse dia, como nos cartões do painel."""
        pares = painel._ler_caixas(db, loja.chave_loja)
        retrato, momento, recebido_em = painel._mais_recente(pares)
        dias = painel._dias_recentes(db, loja.chave_loja, 1)
        dia = retrato.get("dia_operacional") or (dias[0] if dias else painel._hoje().isoformat())
        do_dia = painel.resumo_do_dia(painel._vendas_do_dia(db, loja.chave_loja, dia))["vendas"]
        devolvido = devolucoes.resumo(db, loja.chave_loja, dia, dia)["valor_cent"]
        mes = painel.faturamento_do_mes(db, loja.chave_loja, painel._data_segura(dia, painel._hoje()))
        return {"chave": loja.chave_loja, "nome": loja.nome, "atual": atual, "dia": dia,
                "hoje_cent": do_dia["faturamento_cent"] - devolvido, "vendas_hoje": do_dia["quantidade"],
                "mes_cent": mes["faturamento_cent"], "atualizado_em": recebido_em,
                "atraso_min": painel._atraso_min(momento, recebido_em)}

    def _lista(db: Session, chave_atual: str) -> dict:
        chaves = lojas_do_grupo(db, chave_atual)
        lojas = {l.chave_loja: l for l in db.query(Loja).filter(Loja.chave_loja.in_(chaves))}
        resumos = [_resumo(db, lojas[c], c == chave_atual) for c in chaves if c in lojas and lojas[c].ativa]
        resumos.sort(key=lambda r: (not r["atual"], r["nome"].lower()))
        return {"lojas": resumos,
                "total": {"hoje_cent": sum(r["hoje_cent"] for r in resumos),
                          "vendas_hoje": sum(r["vendas_hoje"] for r in resumos),
                          "mes_cent": sum(r["mes_cent"] for r in resumos)},
                "maximo": MAXIMO_LOJAS}

    @router.get("/v1/painel/lojas")
    def listar(sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        return _lista(db, sessao.chave_loja)

    @router.post("/v1/painel/lojas/vincular")
    def vincular_loja(dados: dict = Body(...), sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        """A prova de que a outra loja é do mesmo dono é a senha do painel dela, com o mesmo limite de tentativas do login."""
        chave = str(dados.get("loja") or "").strip()
        senha = str(dados.get("senha") or "")
        if not chave or not senha:
            raise HTTPException(status_code=422, detail="Informe o código e a senha do painel da outra loja.")
        if len(chave) > 64 or len(senha) > 128:
            raise HTTPException(status_code=422, detail="Loja ou senha longa demais.")
        if painel.tentativas.bloqueada(chave):
            raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde alguns minutos.")
        loja = db.query(Loja).filter(Loja.chave_loja == chave).first()
        acesso = db.query(painel.PainelAcesso).filter_by(chave_loja=chave).first()
        if loja is None or not loja.ativa or acesso is None or not painel.conferir_senha(senha, acesso.senha_hash):
            painel.tentativas.falhou(chave)
            # 403, não 401: no painel, 401 quer dizer "a sua sessão acabou" e derruba o dono para a tela de entrada.
            raise HTTPException(status_code=403, detail="Código ou senha da outra loja não conferem.")
        painel.tentativas.acertou(chave)
        vincular(db, sessao.chave_loja, loja.chave_loja, painel._agora())
        db.commit()
        return _lista(db, sessao.chave_loja)

    @router.post("/v1/painel/lojas/trocar")
    def trocar(dados: dict = Body(...), sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        """Passa a ver outra loja do grupo: sessão nova para ela, a atual é encerrada."""
        chave = str(dados.get("loja") or "").strip()
        if chave == sessao.chave_loja or chave not in lojas_do_grupo(db, sessao.chave_loja):
            raise HTTPException(status_code=404, detail="Esta loja não está no seu painel.")
        loja = db.query(Loja).filter(Loja.chave_loja == chave).first()
        if loja is None or not loja.ativa:
            raise HTTPException(status_code=404, detail="Esta loja não está disponível.")
        db.delete(sessao)
        token, expira = painel.abrir_sessao(db, loja.chave_loja)        # grava a sessão nova e a saída da antiga
        from backend.memoria_nuvem import memoria
        memoria.lembrar_sessao(token, loja.chave_loja)
        return {"token": token, "loja": {"chave": loja.chave_loja, "nome": loja.nome}, "expira_em": expira}

    @router.delete("/v1/painel/lojas/{chave}")
    def remover(chave: str, sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        """Tira uma loja do painel reunido. A loja em que a sessão está não sai por aqui: troque de loja antes."""
        if chave == sessao.chave_loja:
            raise HTTPException(status_code=409, detail="Troque para outra loja antes de remover esta do painel.")
        if chave not in lojas_do_grupo(db, sessao.chave_loja):
            raise HTTPException(status_code=404, detail="Esta loja não está no seu painel.")
        desvincular(db, chave)
        db.commit()
        return _lista(db, sessao.chave_loja)

    app.include_router(router)
    return router
