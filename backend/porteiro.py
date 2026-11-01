"""Consulta da portaria na nuvem: o celular no 4G lê o retrato que o caixa enviou.

O caixa manda, com o token da loja, só as comandas e mesas abertas e o hash do PIN (POST /v1/porteiro/retrato).
O porteiro entra com a chave da loja e o mesmo PIN do caixa; a resposta é só leitura e não atravessa lojas.
Cada caixa substitui o próprio retrato. Na hora de consultar vale o mais novo, e um caixa parado não segura
uma conta que o caixa que acabou de falar já não mostra.

A página em /porteiro/ é a mesma do caixa. No plano grátis o serviço dorme: a primeira abertura depois de um
tempo parado espera ele acordar.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Session

from backend.database import Base, SessionLocal, engine, get_db
from src.core import formatacao as fmt
from src.core import seguranca
from src.core.posicao import interpretar, nome as nome_posicao
from src.porteiro.consulta import frescura

PASTA_WEB = Path(__file__).resolve().parents[1] / "src" / "porteiro" / "web"
SESSAO_SEGUNDOS = 12 * 60 * 60
MAX_FALHAS = 5
BLOQUEIO_SEGUNDOS = 60
MAX_POSICOES = 500
MAX_ITENS = 80
JANELA_CAIXAS_SEG = 180
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
CHAVE_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_CAMPOS = ("situacao", "titulo", "motivo", "detalhe", "cabecalho", "rotulo", "nome", "apelido",
           "comanda", "numero", "devido_cent", "total_cent", "pago_cent", "valor_txt", "itens", "cupom",
           "garota", "aberta_em", "aberta_txt")
_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}


class PorteiroRetrato(Base):
    """Último retrato de um caixa. (chave_loja, terminal_id) substitui o anterior; não guarda histórico."""
    __tablename__ = "porteiro_retratos"
    __table_args__ = (UniqueConstraint("chave_loja", "terminal_id", name="ux_porteiro_retrato"),)
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    terminal_id = Column(String, nullable=False)
    pin_hash = Column(String, nullable=False)
    momento = Column(String, nullable=False)
    url_lan = Column(String)
    dados = Column(Text, nullable=False)
    recebido_em = Column(String, nullable=False)


class _Sessoes:
    def __init__(self):
        self._lock = threading.Lock()
        self._tokens: dict[str, tuple[str, str, float]] = {}
        self._falhas: dict[str, tuple[int, float]] = {}

    def bloqueado(self, chave: str) -> int:
        with self._lock:
            _n, ate = self._falhas.get(chave, (0, 0.0))
            falta = ate - time.monotonic()
            return int(falta) + 1 if falta > 0 else 0

    def falhou(self, chave: str) -> int:
        with self._lock:
            n, ate = self._falhas.get(chave, (0, 0.0))
            if ate > time.monotonic():
                return int(ate - time.monotonic()) + 1
            n += 1
            if n >= MAX_FALHAS:
                self._falhas[chave] = (0, time.monotonic() + BLOQUEIO_SEGUNDOS)
                return BLOQUEIO_SEGUNDOS
            self._falhas[chave] = (n, 0.0)
            return 0

    def abrir(self, chave: str, selo: str, freio: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens[token] = (chave, selo, time.monotonic() + SESSAO_SEGUNDOS)
            self._falhas.pop(freio, None)
        return token

    def ler(self, token: str) -> tuple[str, str] | None:
        if not token or len(token) > 200:
            return None
        with self._lock:
            achado = self._tokens.get(token)
            if achado is None:
                return None
            chave, selo, expira = achado
            if expira < time.monotonic():
                self._tokens.pop(token, None)
                return None
            return chave, selo

    def fechar(self, token: str) -> None:
        with self._lock:
            self._tokens.pop(token, None)

    def zerar(self) -> None:
        with self._lock:
            self._falhas.clear()


sessoes = _Sessoes()


def _selo(hashes: list[str]) -> str:
    return hashlib.sha256("|".join(sorted(hashes)).encode()).hexdigest()[:16]


def _token_do_pedido(authorization: str | None, request: Request) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get("porteiro", "")


def _cookie(token: str, request: Request, apagar: bool = False) -> str:
    seguro = "; Secure" if request.url.scheme == "https" else ""
    idade = "0" if apagar else str(SESSAO_SEGUNDOS)
    valor = "" if apagar else token
    return f"porteiro={valor}; HttpOnly; SameSite=Lax; Path=/porteiro; Max-Age={idade}{seguro}"


def _vigentes(linhas: list[PorteiroRetrato]) -> list[PorteiroRetrato]:
    """O caixa que falou por último manda. Outro caixa só entra se falou nos últimos 3 minutos junto com ele."""
    if not linhas:
        return []
    def instante(linha: PorteiroRetrato) -> datetime:
        try:
            return datetime.strptime((linha.momento or "")[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return datetime.min
    mais = max(instante(linha) for linha in linhas)
    limite = mais - timedelta(seconds=JANELA_CAIXAS_SEG)
    return [linha for linha in linhas if instante(linha) >= limite] or linhas[:1]


def _posicao_limpa(bruta: dict) -> dict | None:
    try:
        numero = int(bruta.get("numero"))
        comanda = bool(bruta.get("comanda"))
    except (TypeError, ValueError):
        return None
    if not 1 <= numero <= 10000 or bruta.get("situacao") not in ("liberada", "devendo"):
        return None
    itens = []
    for item in (bruta.get("itens") or [])[:MAX_ITENS]:
        if isinstance(item, dict) and item.get("nome"):
            itens.append({k: item.get(k) for k in ("nome", "quantidade", "quantidade_txt", "total_cent", "total_txt")})
    limpa = {k: bruta.get(k) for k in _CAMPOS}
    limpa["numero"] = numero
    limpa["comanda"] = comanda
    limpa["garota"] = bruta.get("garota") is True
    aberta = bruta.get("aberta_em")
    limpa["aberta_em"] = aberta[:19] if isinstance(aberta, str) else ""
    hora = bruta.get("aberta_txt")
    limpa["aberta_txt"] = hora[:24] if isinstance(hora, str) else ""
    limpa["itens"] = itens
    return limpa


def _url_lan(texto) -> str:
    texto = (texto or "").strip()
    if texto.startswith(("http://", "https://")) and len(texto) <= 200 and " " not in texto:
        return texto
    return ""


def guardar_retrato(db: Session, chave: str, corpo: dict) -> None:
    terminal = (corpo.get("terminal_id") or "").strip()
    if not ID_RE.fullmatch(terminal):
        raise HTTPException(status_code=422, detail="terminal_id inválido.")
    pin_hash = corpo.get("pin_hash") or ""
    if not isinstance(pin_hash, str) or not pin_hash.startswith("pbkdf2$") or len(pin_hash) > 300:
        raise HTTPException(status_code=422, detail="O retrato precisa do hash do PIN.")
    momento = (corpo.get("momento") or "")[:19]
    try:
        datetime.strptime(momento, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise HTTPException(status_code=422, detail="momento inválido.") from None
    brutas = corpo.get("posicoes") or []
    if not isinstance(brutas, list) or len(brutas) > MAX_POSICOES:
        raise HTTPException(status_code=422, detail=f"No máximo {MAX_POSICOES} posições.")
    posicoes = []
    for bruta in brutas:
        if isinstance(bruta, dict):
            limpa = _posicao_limpa(bruta)
            if limpa:
                posicoes.append(limpa)
    padrao = corpo.get("posicao_padrao") if corpo.get("posicao_padrao") in ("comanda", "mesa") else "comanda"
    dados = json.dumps({"posicao_padrao": padrao, "posicoes": posicoes}, ensure_ascii=False)
    linha = db.query(PorteiroRetrato).filter_by(chave_loja=chave, terminal_id=terminal).first()
    if linha is None:
        linha = PorteiroRetrato(chave_loja=chave, terminal_id=terminal)
        db.add(linha)
    linha.pin_hash = pin_hash
    linha.momento = momento
    linha.url_lan = _url_lan(corpo.get("url_lan"))
    linha.dados = dados
    linha.recebido_em = fmt.agora()
    db.commit()


def _hashes(linhas: list[PorteiroRetrato]) -> list[str]:
    vistos = []
    for linha in linhas:
        if linha.pin_hash and linha.pin_hash not in vistos:
            vistos.append(linha.pin_hash)
    return vistos[:5]


def consultar_chave(db: Session, chave: str, texto: str) -> dict:
    linhas = _vigentes(db.query(PorteiroRetrato).filter_by(chave_loja=chave).all())
    if not linhas:
        raise HTTPException(status_code=503, detail="O caixa ainda não enviou as comandas.")
    linhas.sort(key=lambda linha: linha.momento or "", reverse=True)
    try:
        pacote = json.loads(linhas[0].dados or "{}")
    except json.JSONDecodeError:
        pacote = {}
    padrao = pacote.get("posicao_padrao") or "comanda"
    try:
        comanda, numero = interpretar(texto, padrao)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if numero <= 0:
        raise HTTPException(status_code=400, detail="Informe o número da comanda.")
    candidatos = []
    for linha in linhas:
        try:
            foto = json.loads(linha.dados or "{}")
        except json.JSONDecodeError:
            continue
        for pos in foto.get("posicoes") or []:
            if bool(pos.get("comanda")) == bool(comanda) and int(pos.get("numero") or 0) == numero:
                candidatos.append((linha.momento or "", pos))
    if not candidatos:
        nome = nome_posicao(comanda, numero)
        pos = {"situacao": "liberada", "titulo": "LIBERADA", "motivo": "sem_registro",
               "detalhe": f"{nome}: nada em aberto no último envio do caixa.",
               "cabecalho": nome, "nome": nome, "apelido": "", "comanda": bool(comanda), "numero": numero,
               "rotulo": str(numero) if comanda else f"M{numero}",
               "devido_cent": 0, "total_cent": 0, "pago_cent": 0, "valor_txt": "", "itens": [], "cupom": None}
        momento = linhas[0].momento
    else:
        devendo = [c for c in candidatos if c[1].get("situacao") == "devendo"]
        momento, pos = max(devendo or candidatos, key=lambda c: c[0])
        pos = dict(pos)
    pos.update(frescura(momento))
    return pos


def listar_abertas_chave(db: Session, chave: str) -> dict:
    """Comandas abertas do retrato, sem mesa e sem comanda marcada como garota."""
    linhas = _vigentes(db.query(PorteiroRetrato).filter_by(chave_loja=chave).all())
    if not linhas:
        raise HTTPException(status_code=503, detail="O caixa ainda não enviou as comandas.")
    linhas.sort(key=lambda linha: linha.momento or "", reverse=True)
    escolhidas: dict[int, tuple[str, dict]] = {}
    for linha in linhas:
        try:
            foto = json.loads(linha.dados or "{}")
        except json.JSONDecodeError:
            continue
        for pos in foto.get("posicoes") or []:
            if not isinstance(pos, dict) or not pos.get("comanda") or pos.get("garota") is True:
                continue
            try:
                numero = int(pos.get("numero") or 0)
            except (TypeError, ValueError):
                continue
            if numero <= 0:
                continue
            anterior = escolhidas.get(numero)
            if anterior is None or (linha.momento or "") >= anterior[0]:
                escolhidas[numero] = (linha.momento or "", pos)
    comandas = []
    for numero in escolhidas:
        _momento, pos = escolhidas[numero]
        comandas.append({
            "numero": numero,
            "rotulo": pos.get("rotulo") or str(numero),
            "cabecalho": pos.get("cabecalho") or nome_posicao(True, numero),
            "situacao": pos.get("situacao") or "",
            "titulo": pos.get("titulo") or "",
            "devido_cent": int(pos.get("devido_cent") or 0),
            "total_cent": int(pos.get("total_cent") or 0),
            "pago_cent": int(pos.get("pago_cent") or 0),
            "valor_txt": pos.get("valor_txt") or "",
            "aberta_em": pos.get("aberta_em") or "",
            "aberta_txt": pos.get("aberta_txt") or "",
        })
    comandas.sort(key=lambda item: (0 if item["situacao"] == "devendo" else 1, item["numero"]))
    dados = {"comandas": comandas}
    dados.update(frescura(linhas[0].momento))
    return dados


def instalar(app: FastAPI, Loja, autenticar) -> APIRouter:
    Base.metadata.create_all(bind=engine)
    router = APIRouter()

    def _loja(db: Session, chave: str):
        if not CHAVE_RE.fullmatch(chave or ""):
            raise HTTPException(status_code=422, detail="Chave da loja inválida.")
        loja = db.query(Loja).filter(Loja.chave_loja == chave).first()
        if loja is None:
            raise HTTPException(status_code=404, detail="Loja não encontrada.")
        if not loja.ativa:
            raise HTTPException(status_code=403, detail="Loja desativada na nuvem.")
        return loja

    def _sessao(authorization: str | None, request: Request, db: Session) -> str:
        achado = sessoes.ler(_token_do_pedido(authorization, request))
        if achado is None:
            raise HTTPException(status_code=401, detail="Informe o PIN.")
        chave, selo = achado
        linhas = db.query(PorteiroRetrato).filter_by(chave_loja=chave).all()
        if _selo(_hashes(linhas)) != selo:
            raise HTTPException(status_code=401, detail="O PIN mudou. Entre de novo.")
        return chave

    @router.post("/v1/porteiro/retrato")
    def retrato(corpo: dict = Body(...), acesso=Depends(autenticar), db: Session = Depends(get_db)):
        if acesso.admin:
            raise HTTPException(status_code=403, detail="Use o token da loja para enviar o retrato.")
        guardar_retrato(db, acesso.loja, corpo)
        return {"ok": True}

    def entrar(corpo: dict, request: Request, db: Session):
        chave = (corpo.get("chave") or "").strip()
        loja = _loja(db, chave)
        freio = f"{request.client.host if request.client else '?'}|{loja.chave_loja}"
        espera = sessoes.bloqueado(freio)
        if espera:
            raise HTTPException(status_code=429, detail="Muitas tentativas. Espere um minuto e tente de novo.",
                                headers={"Retry-After": str(espera)})
        linhas = db.query(PorteiroRetrato).filter_by(chave_loja=loja.chave_loja).all()
        hashes = _hashes(linhas)
        if not hashes:
            raise HTTPException(status_code=503, detail="O caixa ainda não enviou o PIN do porteiro.")
        pin = corpo.get("pin", "")
        if isinstance(pin, bool) or not isinstance(pin, (str, int)):
            pin = ""
        pin = str(pin).strip()
        if len(pin) > 32:
            pin = ""
        if not any(seguranca.conferir(pin, guardado) for guardado in hashes):
            if sessoes.falhou(freio):
                raise HTTPException(status_code=429, detail="Muitas tentativas. Espere um minuto e tente de novo.",
                                    headers={"Retry-After": str(BLOQUEIO_SEGUNDOS)})
            raise HTTPException(status_code=401, detail="PIN incorreto.")
        token = sessoes.abrir(loja.chave_loja, _selo(hashes), freio)
        recente = max(linhas, key=lambda linha: linha.momento or "")
        return {"ok": True, "token": token, "caixa_url": recente.url_lan or ""}, token

    @router.post("/v1/porteiro/entrar")
    def entrar_v1(request: Request, corpo: dict = Body(...), db: Session = Depends(get_db)):
        dados, token = entrar(corpo, request, db)
        resposta = Response(content=json.dumps(dados, ensure_ascii=False), media_type="application/json")
        resposta.headers["Set-Cookie"] = _cookie(token, request)
        return resposta

    @router.post("/porteiro/api/entrar")
    def entrar_pagina(request: Request, corpo: dict = Body(...), db: Session = Depends(get_db)):
        return entrar_v1(request, corpo, db)

    @router.post("/v1/porteiro/sair")
    def sair_v1(request: Request, authorization: str | None = Header(None)):
        sessoes.fechar(_token_do_pedido(authorization, request))
        resposta = Response(content='{"ok": true}', media_type="application/json")
        resposta.headers["Set-Cookie"] = _cookie("", request, apagar=True)
        return resposta

    @router.post("/porteiro/api/sair")
    def sair_pagina(request: Request, authorization: str | None = Header(None)):
        return sair_v1(request, authorization)

    @router.get("/v1/porteiro/sessao")
    def sessao_v1(request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
        _sessao(authorization, request, db)
        return {"ok": True}

    @router.get("/porteiro/api/sessao")
    def sessao_pagina(request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
        return sessao_v1(request, authorization, db)

    @router.get("/v1/porteiro/saude")
    def saude_v1():
        return {"ok": True, "modo": "nuvem"}

    @router.get("/porteiro/api/saude")
    def saude_pagina():
        return saude_v1()

    @router.get("/v1/porteiro/consulta")
    def consulta_v1(request: Request, q: str = Query(""), authorization: str | None = Header(None),
                    db: Session = Depends(get_db)):
        if len(q) > 32:
            raise HTTPException(status_code=400, detail="Número da comanda longo demais.")
        chave = _sessao(authorization, request, db)
        return consultar_chave(db, chave, q)

    @router.get("/porteiro/api/consulta")
    def consulta_pagina(request: Request, q: str = Query(""), authorization: str | None = Header(None),
                        db: Session = Depends(get_db)):
        return consulta_v1(request, q, authorization, db)

    @router.get("/v1/porteiro/abertas")
    def abertas_v1(request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
        chave = _sessao(authorization, request, db)
        return listar_abertas_chave(db, chave)

    @router.get("/porteiro/api/abertas")
    def abertas_pagina(request: Request, authorization: str | None = Header(None),
                       db: Session = Depends(get_db)):
        return abertas_v1(request, authorization, db)

    @app.middleware("http")
    async def cors_porteiro(request: Request, call_next):
        caminho = request.url.path
        if not (caminho.startswith("/porteiro/api/") or caminho.startswith("/v1/porteiro/")):
            return await call_next(request)
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=_CORS)
        resposta = await call_next(request)
        for nome, valor in _CORS.items():
            resposta.headers[nome] = valor
        return resposta

    app.include_router(router)
    if PASTA_WEB.is_dir():
        @app.get("/porteiro", include_in_schema=False)
        def porteiro_raiz():
            return RedirectResponse(url="/porteiro/")

        @app.get("/porteiro/", include_in_schema=False)
        def porteiro_index():
            return FileResponse(PASTA_WEB / "index.html", headers={"Cache-Control": "no-cache"})

        app.mount("/porteiro", StaticFiles(directory=str(PASTA_WEB)), name="porteiro")
    return router
