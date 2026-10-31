"""API de nuvem do PDV (FastAPI): licença das lojas, aviso de versão nova e o painel do dono no celular.

O PDV funciona sozinho em cada loja; a nuvem não é necessária para vender. Ela guarda a lista de lojas e a data até
quando cada uma pagou (Mercado Pago ou lançamento manual; cada loja com o SEU token), entrega a licença e publica as
versões novas do PDV.
Com o painel do dono ligado na loja (opcional), recebe também as vendas fechadas e um retrato do caixa/estoque, que o dono
consulta pelo celular em /painel/ (backend/painel.py). Cadastro das lojas (o token aparece uma única vez):
    python -m backend.lojas criar BOATE-CENTRO "Boate Centro"

Como rodar, na raiz do repositório:
    $env:PDV_API_TOKEN = "um-segredo-longo-e-aleatorio"      # token do ADMINISTRADOR (lista de lojas)
    python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

O PDV usa o token da loja em Configurações > Nuvem (Token da API) e envia `Authorization: Bearer <token>`. Sem nenhuma
loja e sem PDV_API_TOKEN o servidor recusa tudo (503): não existe token padrão.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.orm import Session

from backend.database import Base, SessionLocal, engine
from backend import cobranca_mercadopago as cobranca
from backend import ponte as _ponte     # tabelas e rotas da ponte de licenças (central do fornecedor)
from src.core import ed25519, licenca as licenca_pdv
from src.versao import chave, mais_nova, valida      # a mesma regra de comparação de versões do PDV

log = logging.getLogger("pdv.nuvem")

class Loja(Base):
    """Uma loja cliente da nuvem. Guarda só o SHA-256 do token (aleatório e longo), nunca o token."""
    __tablename__ = "lojas"
    id = Column(Integer, primary_key=True, index=True)
    chave_loja = Column(String, unique=True, index=True, nullable=False)
    nome = Column(String, nullable=False)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    ativa = Column(Boolean, nullable=False, default=True)
    criada_em = Column(String)
    licenca_ate = Column(String, nullable=True)     # AAAA-MM-DD: até quando a assinatura está paga (backend.lojas assinatura)


class Versao(Base):
    """Versão do PDV publicada pelo fornecedor (python -m backend.atualizacoes). Os caixas consultam /v1/atualizacoes."""
    __tablename__ = "versoes"
    id = Column(Integer, primary_key=True, index=True)
    versao = Column(String, unique=True, index=True, nullable=False)
    notas = Column(String, nullable=False)
    url_download = Column(String, nullable=True)
    critica = Column(Boolean, nullable=False, default=False)
    publicada_em = Column(String)


def situacao_assinatura(licenca_ate: str | None, hoje: date | None = None) -> str:
    """'paga até 30/11/2026', com o alerta do que precisa de atenção: VENCIDA ou quantos dias faltam (7 ou menos)."""
    if not licenca_ate:
        return "sem assinatura"
    ate = date.fromisoformat(licenca_ate)
    dias = (ate - (hoje or date.today())).days
    texto = f"paga até {ate.strftime('%d/%m/%Y')}"
    if dias <= 0:
        return texto + " (VENCIDA)"
    if dias <= 7:
        return texto + f" (vence em {dias} dia{'s' if dias > 1 else ''})"
    return texto


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


Base.metadata.create_all(bind=engine)


def _acrescentar_colunas() -> None:
    """create_all não altera tabela existente: colunas novas de tabelas que já existiam entram aqui."""
    from sqlalchemy import inspect, text
    novas = {"lojas": {"licenca_ate": "VARCHAR"}}
    with engine.begin() as con:
        for tabela, colunas in novas.items():
            existentes = {c["name"] for c in inspect(con).get_columns(tabela)}
            for nome, tipo in colunas.items():
                if nome not in existentes:
                    con.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}"))


_acrescentar_colunas()
cobranca.garantir_esquema(engine)


@asynccontextmanager
async def _ciclo_de_vida(_aplicacao):
    # A varredura vive neste processo: no Render grátis não há worker separado.
    try:
        cobranca.iniciar_varredura()
    except Exception:
        log.error("Não foi possível iniciar a varredura do Mercado Pago.")
    try:
        yield
    finally:
        cobranca.parar_varredura()


app = FastAPI(title="WillPDV - API de nuvem", lifespan=_ciclo_de_vida)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@dataclass(frozen=True)
class Acesso:
    """Quem chamou: uma loja (pelo token dela) ou o administrador (PDV_API_TOKEN), que tem `loja` None."""
    loja: Optional[str]

    @property
    def admin(self) -> bool:
        return self.loja is None


def autenticar(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> Acesso:
    admin = os.environ.get("PDV_API_TOKEN", "")
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
    if token:
        if admin and hmac.compare_digest(token.encode("utf-8"), admin.encode("utf-8")):
            return Acesso(None)
        loja = db.query(Loja).filter(Loja.token_hash == hash_token(token)).first()
        if loja is not None:
            if not loja.ativa:
                raise HTTPException(status_code=403, detail="Loja desativada na nuvem.")
            return Acesso(loja.chave_loja)
    if not admin and db.query(Loja.id).first() is None:
        raise HTTPException(status_code=503, detail="Servidor sem lojas cadastradas nem PDV_API_TOKEN configurado.")
    raise HTTPException(status_code=401, detail="Token invalido")


@app.post("/v1/webhooks/mercadopago")
def webhook_mercadopago(request: Request, db: Session = Depends(get_db)):
    """Notificação do Mercado Pago. O corpo não é comprovante: a assinatura cobre data.id na URL."""
    try:
        data_id, evento_id = cobranca.validar_assinatura(
            request.headers.get("x-signature"),
            request.headers.get("x-request-id"),
            request.query_params.get("data.id"))
    except cobranca.WebhookNaoConfigurado:
        raise HTTPException(status_code=503, detail="Webhook Mercado Pago não configurado.") from None
    except cobranca.AssinaturaInvalida:
        raise HTTPException(status_code=401, detail="Assinatura do webhook inválida.") from None
    if request.query_params.get("type") != "payment":
        return {"situacao": "ignorado"}
    if not cobranca.ID_PAGAMENTO.fullmatch(data_id):
        log.info("Notificação Mercado Pago ignorada: id de pagamento não numérico.")
        return {"situacao": "ignorado"}
    try:
        return {"situacao": cobranca.processar_notificacao(db, data_id, evento_id)}
    except cobranca.MercadoPagoIndisponivel:
        db.rollback()
        log.error("Mercado Pago indisponível ao processar o pagamento %s.", data_id)
        raise HTTPException(
            status_code=503, detail="Mercado Pago indisponível; a notificação será reenviada.") from None
    except Exception:
        db.rollback()
        log.error("Falha ao processar notificação Mercado Pago (erro interno).")
        raise HTTPException(status_code=503, detail="Não foi possível processar a notificação.") from None


@app.get("/v1/admin/cobrancas/operacao")
def admin_operacao_cobrancas(acesso: Acesso = Depends(autenticar), db: Session = Depends(get_db)):
    if not acesso.admin:
        raise HTTPException(status_code=403, detail="Só o administrador vê a operação de cobrança.")
    return cobranca.estado(db)


@app.get("/v1/saude")
def saude():
    return {"status": "ok"}


@app.get("/v1/admin/lojas")
def admin_lojas(acesso: Acesso = Depends(autenticar), db: Session = Depends(get_db)):
    """Lista do fornecedor (só com o PDV_API_TOKEN): cada loja, se está ativa e até quando pagou. É o 'lojas listar' na
    tela, para quem não tem terminal no servidor (ex.: Render grátis)."""
    if not acesso.admin:
        raise HTTPException(status_code=403, detail="Só o token do administrador vê a lista de lojas.")
    hoje = date.today()
    return {"lojas": [
        {"chave_loja": l.chave_loja, "nome": l.nome, "ativa": bool(l.ativa), "licenca_ate": l.licenca_ate,
         "dias_restantes": (date.fromisoformat(l.licenca_ate) - hoje).days if l.licenca_ate else None,
         "situacao": situacao_assinatura(l.licenca_ate, hoje)}
        for l in db.query(Loja).order_by(Loja.chave_loja).all()]}


# ------------------------------------------------------------ atualizações
@app.get("/v1/atualizacoes")
def atualizacoes(versao: str = Query(..., max_length=20), acesso: Acesso = Depends(autenticar),
                 db: Session = Depends(get_db)):
    """O que há de novo para um PDV na `versao` informada: as versões mais novas publicadas, da mais nova para a
    mais antiga, com as notas. `critica` diz se alguma delas é correção que não deve esperar."""
    if not valida(versao):
        raise HTTPException(status_code=422, detail="versão inválida")
    novas = sorted((v for v in db.query(Versao).all() if mais_nova(v.versao, versao)),
                   key=lambda v: chave(v.versao), reverse=True)
    return {
        "versao_atual": versao,
        "disponivel": bool(novas),
        "ultima": novas[0].versao if novas else None,
        "critica": any(v.critica for v in novas),
        "url_download": next((v.url_download for v in novas if v.url_download), None),
        "versoes": [{"versao": v.versao, "notas": v.notas, "critica": bool(v.critica), "publicada_em": v.publicada_em}
                    for v in novas[:20]],
    }


# ------------------------------------------------------------- licença
def semente_licenca() -> Optional[bytes]:
    """Chave privada do fornecedor (a mesma de tools.gerar_licenca): PDV_LICENCA_CHAVE ou ~/.pdv-casa/licenca_privada.key."""
    arquivo = Path(os.environ.get("PDV_LICENCA_CHAVE") or Path.home() / ".pdv-casa" / "licenca_privada.key")
    try:
        semente = bytes.fromhex(arquivo.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    return semente if len(semente) == 32 else None


@app.get("/v1/licenca")
def licenca(acesso: Acesso = Depends(autenticar), db: Session = Depends(get_db)):
    """Código de licença da loja do token, válido até a data paga (`python -m backend.lojas assinatura`). O PDV renova
    sozinho com ele; se a loja não pagou, a data não avança e a licença vence normalmente no caixa."""
    if acesso.admin:
        raise HTTPException(status_code=403, detail="Use o token da loja.")
    loja = db.query(Loja).filter(Loja.chave_loja == acesso.loja).first()
    publicada = _ponte.licenca_legado(db, loja.chave_loja)
    if publicada is not None:       # loja migrada: só o código assinado pela central, nunca assinatura na nuvem
        return publicada
    if not loja.licenca_ate:
        raise HTTPException(status_code=404, detail="Nenhuma assinatura registrada para esta loja.")
    ate = date.fromisoformat(loja.licenca_ate)
    hoje = date.today()
    if ate <= hoje:
        raise HTTPException(status_code=409, detail=f"Assinatura paga até {ate.strftime('%d/%m/%Y')}: renove com o fornecedor.")
    semente = semente_licenca()
    if semente is None or ed25519.chave_publica(semente).hex() != licenca_pdv.CHAVE_PUBLICA_HEX:
        log.error("Licença pedida pela loja %s, mas a nuvem não tem a chave privada do fornecedor certa.", loja.chave_loja)
        raise HTTPException(status_code=503, detail="A nuvem não está configurada para emitir licenças.")
    return {"codigo": licenca_pdv.gerar_licenca(semente, loja.chave_loja, (ate - hoje).days, hoje),
            "expira_em": ate.isoformat()}


# ------------------------------------------------------- painel do dono
# Opcional por loja (Configurações > Nuvem > painel_dono no PDV): vendas, caixa e estoque para o celular do dono, em
# /painel/. Fica em backend/painel.py; recebe daqui o modelo de loja e a autenticação por token.
from backend import painel as _painel   # noqa: E402  (depois de Loja e autenticar existirem)

_painel.instalar(app, Loja, autenticar)
_ponte.instalar(app, Loja, hash_token)

# Porteiro no celular pelo 4G: retrato das comandas abertas e a mesma página em /porteiro/.
from backend import porteiro as _porteiro_nuvem  # noqa: E402

_porteiro_nuvem.instalar(app, Loja, autenticar)
