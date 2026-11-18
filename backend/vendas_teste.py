"""Vendas de teste apagadas: o que o caixa apagou some da nuvem, e o dono também pode apagar pelo painel.

- A senha de segurança do dono nasce no caixa; só o hash sobe (no envio do painel) e fica em `painel_seguranca`.
- O caixa apagou (com a senha): o lote traz `vendas_apagadas`; a nuvem apaga a venda do painel, dos relatórios e da
  central e não aceita mais aquele uuid (um reenvio atrasado não a ressuscita).
- O dono apagou pelo painel (sessão + senha de segurança): vira um pedido "aguardando o caixa". A nuvem não sabe se a
  venda tem NFC-e, devolução ou fiado; quem confere é o caixa. Ele apaga e confirma (aí some daqui) ou recusa com o
  motivo, que o painel mostra.
- Cinco senhas erradas seguidas bloqueiam por 15 minutos (contador da nuvem, separado do caixa).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db

TENTATIVAS_MAXIMAS = 5
BLOQUEIO_MINUTOS = 15
LIMITE_POR_VEZ = 500
LIMITE_ITERACOES = 2_000_000          # hash vindo do caixa: barra um custo absurdo de conferência


class PainelSeguranca(Base):
    __tablename__ = "painel_seguranca"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, unique=True, index=True, nullable=False)
    senha_hash = Column(String, nullable=False)
    atualizada_em = Column(String, nullable=False)
    tentativas = Column(Integer, nullable=False, default=0)
    bloqueada_ate = Column(String)


class PainelExclusao(Base):
    """Uma venda apagada como teste (ou pedida pelo painel). (chave_loja, uuid) é único."""
    __tablename__ = "painel_exclusoes"
    __table_args__ = (UniqueConstraint("chave_loja", "uuid", name="ux_painel_exclusao"),)
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    uuid = Column(String, nullable=False)
    origem = Column(String, nullable=False)              # caixa | painel
    situacao = Column(String, nullable=False)            # aguardando | apagada | recusada
    motivo = Column(String)
    cupom = Column(Integer)
    dia = Column(String)
    total_cent = Column(Integer, nullable=False, default=0)
    pedida_em = Column(String, nullable=False)
    resolvida_em = Column(String)


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _hash_valido(h) -> bool:
    if not isinstance(h, str) or len(h) > 300:
        return False
    partes = h.split("$")
    if len(partes) != 4 or partes[0] != "pbkdf2":
        return False
    try:
        iteracoes = int(partes[1])
        bytes.fromhex(partes[2])
        bytes.fromhex(partes[3])
    except ValueError:
        return False
    return 10_000 <= iteracoes <= LIMITE_ITERACOES and len(partes[3]) == 64


# ------------------------------------------------------------ envio do caixa (chamado por painel.envio)
def uuids_apagados(db: Session, chave_loja: str, uuids: list[str]) -> set[str]:
    """Dos uuids que chegaram, os que já foram apagados (não guardar de novo)."""
    if not uuids:
        return set()
    return {u for (u,) in db.query(PainelExclusao.uuid).filter(
        PainelExclusao.chave_loja == chave_loja, PainelExclusao.situacao == "apagada",
        PainelExclusao.uuid.in_(uuids)).all()}


def receber(db: Session, chave_loja: str, dados: dict) -> dict:
    """Processa o que o caixa mandou sobre vendas de teste e devolve as chaves da resposta. Não faz commit."""
    from backend.painel import PainelVenda
    resposta: dict = {}
    agora = _agora()
    h = dados.get("seguranca_hash")
    if h is not None:
        if _hash_valido(h):
            linha = db.query(PainelSeguranca).filter_by(chave_loja=chave_loja).first()
            if linha is None:
                linha = PainelSeguranca(chave_loja=chave_loja, tentativas=0)
                db.add(linha)
            if linha.senha_hash != h:
                linha.senha_hash, linha.tentativas, linha.bloqueada_ate = h, 0, None
            linha.atualizada_em = agora
            resposta["seguranca_ok"] = True
        else:
            resposta["seguranca_ok"] = False
    apagadas = dados.get("vendas_apagadas")
    if isinstance(apagadas, list):
        ok = []
        for item in apagadas[:LIMITE_POR_VEZ]:
            uuid = str(item.get("uuid") or "").strip() if isinstance(item, dict) else ""
            if not uuid or len(uuid) > 64:
                continue
            venda = db.query(PainelVenda).filter_by(chave_loja=chave_loja, uuid=uuid).first()
            linha = db.query(PainelExclusao).filter_by(chave_loja=chave_loja, uuid=uuid).first()
            if linha is None:
                linha = PainelExclusao(chave_loja=chave_loja, uuid=uuid, pedida_em=agora,
                                       origem="painel" if item.get("origem") == "painel" else "caixa")
                db.add(linha)
            if venda is not None:
                linha.cupom, linha.dia, linha.total_cent = venda.cupom, venda.dia, int(venda.total_cent or 0)
                db.delete(venda)
            linha.situacao, linha.motivo, linha.resolvida_em = "apagada", None, agora
            ok.append(uuid)
        resposta["apagadas_uuids"] = ok
    recusadas = dados.get("vendas_recusadas")
    if isinstance(recusadas, list):
        ok = []
        for item in recusadas[:LIMITE_POR_VEZ]:
            uuid = str(item.get("uuid") or "").strip() if isinstance(item, dict) else ""
            if not uuid:
                continue
            linha = db.query(PainelExclusao).filter_by(chave_loja=chave_loja, uuid=uuid).first()
            if linha is not None and linha.situacao == "aguardando":
                linha.situacao, linha.resolvida_em = "recusada", agora
                linha.motivo = str(item.get("motivo") or "o caixa não deixou")[:200]
            ok.append(uuid)
        resposta["recusadas_uuids"] = ok
    if apagadas or recusadas:
        from backend.cache_leitura import limpar
        limpar()
    return resposta


def pedidos_para_o_caixa(db: Session, chave_loja: str) -> list[str]:
    return [u for (u,) in db.query(PainelExclusao.uuid).filter_by(chave_loja=chave_loja, situacao="aguardando")
            .order_by(PainelExclusao.id).limit(LIMITE_POR_VEZ).all()]


def podar(db: Session, corte: str) -> int:
    """Esquece exclusões resolvidas além da retenção do painel (venda tão antiga não é mais guardada mesmo)."""
    from sqlalchemy import and_, or_
    return db.query(PainelExclusao).filter(
        PainelExclusao.situacao != "aguardando",
        or_(PainelExclusao.dia < corte, and_(PainelExclusao.dia.is_(None), PainelExclusao.pedida_em < corte)),
    ).delete(synchronize_session=False)


# ------------------------------------------------------------ painel do dono
def _conferir_senha(db: Session, chave_loja: str, senha: str) -> None:
    from src.core import seguranca
    linha = db.query(PainelSeguranca).filter_by(chave_loja=chave_loja).first()
    if linha is None:
        raise HTTPException(status_code=409, detail="Crie antes a senha de segurança no caixa "
                                                    "(Configurações > Segurança) e espere ele sincronizar.")
    agora = _agora()
    if linha.bloqueada_ate and linha.bloqueada_ate > agora:
        raise HTTPException(status_code=423, detail="Senha de segurança bloqueada por excesso de erros. "
                                                    f"Tente depois de {linha.bloqueada_ate[11:16]}.")
    if seguranca.conferir(senha or "", linha.senha_hash):
        linha.tentativas, linha.bloqueada_ate = 0, None
        return
    linha.tentativas = int(linha.tentativas or 0) + 1
    if linha.tentativas >= TENTATIVAS_MAXIMAS:
        linha.tentativas = 0
        linha.bloqueada_ate = (datetime.now() + timedelta(minutes=BLOQUEIO_MINUTOS)).strftime("%Y-%m-%d %H:%M:%S")
        db.commit()
        raise HTTPException(status_code=423, detail=f"Senha de segurança errada {TENTATIVAS_MAXIMAS} vezes: "
                                                    f"bloqueada por {BLOQUEIO_MINUTOS} minutos.")
    restantes = TENTATIVAS_MAXIMAS - linha.tentativas
    db.commit()
    raise HTTPException(status_code=403, detail=f"Senha de segurança incorreta ({restantes} tentativa(s) antes "
                                                "do bloqueio).")


def instalar(app: FastAPI, Loja) -> APIRouter:
    from backend.painel import PainelSessao, PainelVenda, sessao_do_dono
    Base.metadata.create_all(bind=engine)
    router = APIRouter()

    def sessao_ativa(sessao: PainelSessao = Depends(sessao_do_dono), db: Session = Depends(get_db)):
        loja = db.query(Loja).filter(Loja.chave_loja == sessao.chave_loja).first()
        if loja is None or not loja.ativa:
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        return sessao

    @router.get("/v1/painel/vendas-teste")
    def listar(inicio: str, fim: str, sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        for d in (inicio, fim):
            try:
                datetime.strptime(d, "%Y-%m-%d")
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="Informe as datas como AAAA-MM-DD.")
        chave = sessao.chave_loja
        pedidos = {e.uuid: e for e in db.query(PainelExclusao).filter_by(chave_loja=chave).all()}
        vendas = (db.query(PainelVenda).filter(PainelVenda.chave_loja == chave, PainelVenda.dia >= inicio,
                                               PainelVenda.dia <= fim)
                  .order_by(PainelVenda.fechada_em, PainelVenda.id).limit(LIMITE_POR_VEZ * 2).all())
        saida = []
        for v in vendas:
            e = pedidos.get(v.uuid)
            saida.append({"uuid": v.uuid, "cupom": v.cupom, "dia": v.dia, "status": v.status,
                          "modalidade": v.modalidade, "fechada_em": v.fechada_em, "total_cent": int(v.total_cent or 0),
                          "pedido": e.situacao if e else None, "motivo": e.motivo if e else None})
        recentes = (db.query(PainelExclusao).filter_by(chave_loja=chave)
                    .order_by(PainelExclusao.id.desc()).limit(50).all())
        return {
            "senha_configurada": db.query(PainelSeguranca).filter_by(chave_loja=chave).first() is not None,
            "vendas": saida,
            "historico": [{"uuid": e.uuid, "cupom": e.cupom, "dia": e.dia, "total_cent": e.total_cent,
                           "origem": e.origem, "situacao": e.situacao, "motivo": e.motivo,
                           "pedida_em": e.pedida_em, "resolvida_em": e.resolvida_em} for e in recentes],
        }

    @router.post("/v1/painel/vendas-teste/apagar")
    def apagar(dados: dict = Body(...), sessao=Depends(sessao_ativa), db: Session = Depends(get_db)):
        uuids = dados.get("uuids")
        if not isinstance(uuids, list) or not uuids or len(uuids) > LIMITE_POR_VEZ:
            raise HTTPException(status_code=422, detail=f"Escolha de 1 a {LIMITE_POR_VEZ} vendas.")
        chave = sessao.chave_loja
        _conferir_senha(db, chave, str(dados.get("senha") or ""))
        agora = _agora()
        pedidas, total = 0, 0
        for uuid in dict.fromkeys(str(u) for u in uuids if isinstance(u, str)):
            venda = db.query(PainelVenda).filter_by(chave_loja=chave, uuid=uuid).first()
            if venda is None:
                continue
            linha = db.query(PainelExclusao).filter_by(chave_loja=chave, uuid=uuid).first()
            if linha is not None and linha.situacao in ("aguardando", "recusada"):
                continue                                 # já pedida; a recusada o caixa não deixa
            if linha is None:
                linha = PainelExclusao(chave_loja=chave, uuid=uuid)
                db.add(linha)
            linha.origem, linha.situacao, linha.motivo, linha.pedida_em, linha.resolvida_em = \
                "painel", "aguardando", None, agora, None
            linha.cupom, linha.dia, linha.total_cent = venda.cupom, venda.dia, int(venda.total_cent or 0)
            pedidas += 1
            total += int(venda.total_cent or 0) if venda.status == "fechada" else 0
        db.commit()
        from backend.cache_leitura import limpar
        limpar()
        return {"pedidas": pedidas, "total_cent": total,
                "aviso": "O caixa confere e apaga na próxima sincronização; enquanto isso a venda aparece como "
                         "aguardando."}

    app.include_router(router)
    return router
