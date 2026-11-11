"""Retaguarda na nuvem: o dono (painel) e o fornecedor (central) alteram a loja de longe; o caixa aplica.

A nuvem guarda duas coisas por loja:

- o **espelho** que o caixa sobe (`retaguarda_espelhos`): o esquema das telas, as linhas de cada cadastro e o
  financeiro. É só leitura: serve para a página mostrar o que existe na loja. Senha e token não sobem;
- a **fila de comandos** (`retaguarda_comandos`): cada alteração pedida na página vira um comando `pendente`, que o
  caixa busca, aplica pelas regras do PDV e devolve como `aplicado` ou `recusado` (com o motivo).

A nuvem não valida regra de negócio nem altera o espelho: quem decide é o caixa (src/controllers/retaguarda_controller.py),
e o espelho novo sobe depois que ele aplica. A loja precisa ter ligado a retaguarda no próprio caixa.
"""
from __future__ import annotations

import base64
import json
import re
import unicodedata
import zlib
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db

PASTA_WEB = Path(__file__).resolve().parent / "retaguarda_web"
LIMITE_SECAO_BYTES = 6 * 1024 * 1024        # JSON de uma seção do espelho
LIMITE_SECOES = 60
LIMITE_COMANDO_BYTES = 64 * 1024
LIMITE_PENDENTES = 300                      # comandos esperando o caixa, por loja
LOTE_ENTREGA = 20
PAGINA = 100
DIAS_HISTORICO = 90
SECAO_VALIDA = re.compile(r"^(esquema|financeiro|cadastro:[a-z_]{1,40})$")
TIPOS_COMANDO = ("cadastro.salvar", "cadastro.excluir", "estoque.movimento", "config.salvar",
                 "conta.incluir", "conta.alterar", "conta.quitar", "conta.desfazer", "conta.excluir")
SITUACOES_FINAIS = ("aplicado", "recusado")


class RetaguardaEspelho(Base):
    __tablename__ = "retaguarda_espelhos"
    __table_args__ = (UniqueConstraint("chave_loja", "secao", name="ux_retaguarda_espelho"),)
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    secao = Column(String, nullable=False)
    digital = Column(String, nullable=False, default="")
    dados = Column(Text, nullable=False)                # JSON comprimido (zlib) em base64
    atualizado_em = Column(String, nullable=False)


class RetaguardaComando(Base):
    __tablename__ = "retaguarda_comandos"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    tipo = Column(String, nullable=False)
    dados = Column(Text, nullable=False)                # JSON; a senha sai daqui quando o caixa confirma
    resumo = Column(String, nullable=False, default="")
    autor = Column(String, nullable=False, default="")  # "dono" ou "fornecedor"
    criado_em = Column(String, nullable=False)
    situacao = Column(String, nullable=False, default="pendente")
    situacao_em = Column(String, nullable=False)
    detalhe = Column(String, nullable=False, default="")
    novo_id = Column(Integer, nullable=True)


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _guardar_json(dados) -> str:
    bruto = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(zlib.compress(bruto, 6)).decode("ascii")


def _ler_json(texto: str):
    return json.loads(zlib.decompress(base64.b64decode(texto)).decode("utf-8"))


def _norm(texto) -> str:
    sem = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")
    return sem.lower().strip()


def pendentes(db: Session, chave_loja: str) -> int:
    """Quantos comandos esperam o caixa. O envio do painel devolve este número: o caixa só busca se houver."""
    return db.query(RetaguardaComando.id).filter_by(chave_loja=chave_loja, situacao="pendente").count()


def secao(db: Session, chave_loja: str, nome: str):
    linha = db.query(RetaguardaEspelho).filter_by(chave_loja=chave_loja, secao=nome).first()
    if linha is None:
        return None, None
    try:
        return _ler_json(linha.dados), linha.atualizado_em
    except (ValueError, zlib.error):
        return None, None


def _sem_senha(dados: dict) -> dict:
    """Cópia do comando sem a senha digitada (a lista da página e o histórico nunca mostram senha)."""
    valores = dados.get("valores")
    if isinstance(valores, dict) and "senha" in valores:
        dados = {**dados, "valores": {**valores, "senha": "***"}}
    return dados


def publico(c: RetaguardaComando) -> dict:
    try:
        dados = json.loads(c.dados)
    except ValueError:
        dados = {}
    return {"id": c.id, "tipo": c.tipo, "dados": _sem_senha(dados), "resumo": c.resumo, "autor": c.autor,
            "criado_em": c.criado_em, "situacao": c.situacao, "situacao_em": c.situacao_em, "detalhe": c.detalhe,
            "novo_id": c.novo_id}


def limpar_antigos(db: Session, chave_loja: str) -> None:
    corte = (datetime.now() - timedelta(days=DIAS_HISTORICO)).strftime("%Y-%m-%d %H:%M:%S")
    db.query(RetaguardaComando).filter(RetaguardaComando.chave_loja == chave_loja,
                                       RetaguardaComando.situacao.in_(SITUACOES_FINAIS),
                                       RetaguardaComando.situacao_em < corte).delete(synchronize_session=False)


# ------------------------------------------------------------------ leitura (dono e fornecedor usam as mesmas)
def visao(db: Session, chave_loja: str) -> dict:
    """O que a página precisa para abrir: o esquema das telas, quantas linhas há em cada cadastro e a fila."""
    esquema, quando = secao(db, chave_loja, "esquema")
    linhas = db.query(RetaguardaEspelho.secao, RetaguardaEspelho.atualizado_em).filter_by(chave_loja=chave_loja).all()
    return {"ligada": esquema is not None, "esquema": esquema, "atualizado_em": quando,
            "secoes": {nome: em for nome, em in linhas}, "pendentes": pendentes(db, chave_loja)}


def cadastro(db: Session, chave_loja: str, entidade: str, busca: str = "", pagina: int = 1,
             inativos: bool = True) -> dict:
    if not re.fullmatch(r"[a-z_]{1,40}", entidade or ""):
        raise HTTPException(status_code=404, detail="Cadastro não encontrado.")
    dados, quando = secao(db, chave_loja, f"cadastro:{entidade}")
    if dados is None:
        raise HTTPException(status_code=404, detail="A loja ainda não enviou este cadastro.")
    campos, linhas = dados.get("campos") or [], dados.get("linhas") or []
    termo = _norm(busca)
    if termo:
        linhas = [l for l in linhas if any(termo in _norm(v) for v in l if isinstance(v, str))]
    if not inativos and "ativo" in campos:
        posicao = campos.index("ativo")
        linhas = [l for l in linhas if l[posicao]]
    pagina = max(int(pagina or 1), 1)
    fila = (db.query(RetaguardaComando).filter_by(chave_loja=chave_loja, situacao="pendente")
            .filter(RetaguardaComando.tipo.in_(("cadastro.salvar", "cadastro.excluir", "estoque.movimento")))
            .order_by(RetaguardaComando.id).all())
    return {"campos": campos, "linhas": linhas[(pagina - 1) * PAGINA: pagina * PAGINA], "encontradas": len(linhas),
            "total": dados.get("total", len(dados.get("linhas") or [])), "pagina": pagina, "por_pagina": PAGINA,
            "atualizado_em": quando, "pendentes": [publico(c) for c in fila]}


def financeiro(db: Session, chave_loja: str) -> dict:
    dados, quando = secao(db, chave_loja, "financeiro")
    fila = (db.query(RetaguardaComando).filter_by(chave_loja=chave_loja, situacao="pendente")
            .filter(RetaguardaComando.tipo.like("conta.%")).order_by(RetaguardaComando.id).all())
    return {"contas": (dados or {}).get("contas") or [], "devedores": (dados or {}).get("devedores") or [],
            "atualizado_em": quando, "pendentes": [publico(c) for c in fila]}


def historico(db: Session, chave_loja: str) -> dict:
    limpar_antigos(db, chave_loja)
    db.commit()
    comandos = (db.query(RetaguardaComando).filter_by(chave_loja=chave_loja)
                .order_by(RetaguardaComando.id.desc()).limit(150).all())
    return {"comandos": [publico(c) for c in comandos]}


# ------------------------------------------------------------------ escrita (vira comando para o caixa)
def criar(db: Session, chave_loja: str, corpo: dict, autor: str) -> RetaguardaComando:
    tipo = corpo.get("tipo")
    dados = corpo.get("dados")
    if tipo not in TIPOS_COMANDO or not isinstance(dados, dict):
        raise HTTPException(status_code=422, detail="Alteração inválida.")
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    if len(texto.encode("utf-8")) > LIMITE_COMANDO_BYTES:
        raise HTTPException(status_code=413, detail="Alteração grande demais.")
    esquema, _ = secao(db, chave_loja, "esquema")
    if esquema is None:
        raise HTTPException(status_code=409, detail="A loja ainda não ligou a retaguarda no caixa (Configurações > Nuvem).")
    if pendentes(db, chave_loja) >= LIMITE_PENDENTES:
        raise HTTPException(status_code=409, detail="Há alterações demais esperando o caixa. Aguarde a loja aplicar as que já estão na fila.")
    agora = _agora()
    resumo = re.sub(r"\s+", " ", str(corpo.get("resumo") or "")).strip()[:200] or tipo
    comando = RetaguardaComando(chave_loja=chave_loja, tipo=tipo, dados=texto, resumo=resumo, autor=autor[:60],
                                criado_em=agora, situacao="pendente", situacao_em=agora, detalhe="")
    db.add(comando)
    db.commit()
    return comando


def cancelar(db: Session, chave_loja: str, comando_id: int) -> None:
    comando = db.query(RetaguardaComando).filter_by(id=comando_id, chave_loja=chave_loja).first()
    if comando is None:
        raise HTTPException(status_code=404, detail="Alteração não encontrada.")
    if comando.situacao != "pendente":
        raise HTTPException(status_code=409, detail="O caixa já recebeu esta alteração.")
    db.delete(comando)
    db.commit()


def _rotas_de_leitura_e_escrita(router: APIRouter, prefixo: str, loja_da_sessao, autor: str, ao_criar=None) -> None:
    """As mesmas rotas para o dono (`/v1/painel/retaguarda`) e o fornecedor (`/v1/fornecedor/lojas/{chave}/retaguarda`)."""

    @router.get(prefixo)
    def abrir(chave_loja: str = Depends(loja_da_sessao), db: Session = Depends(get_db)):
        return visao(db, chave_loja)

    @router.get(prefixo + "/cadastro/{entidade}")
    def listar(entidade: str, busca: str = "", pagina: int = 1, inativos: int = 1,
               chave_loja: str = Depends(loja_da_sessao), db: Session = Depends(get_db)):
        return cadastro(db, chave_loja, entidade, busca[:80], pagina, bool(inativos))

    @router.get(prefixo + "/financeiro")
    def contas(chave_loja: str = Depends(loja_da_sessao), db: Session = Depends(get_db)):
        return financeiro(db, chave_loja)

    @router.get(prefixo + "/comandos")
    def fila(chave_loja: str = Depends(loja_da_sessao), db: Session = Depends(get_db)):
        return historico(db, chave_loja)

    @router.post(prefixo + "/comandos")
    def pedir(corpo: dict = Body(...), chave_loja: str = Depends(loja_da_sessao), db: Session = Depends(get_db)):
        comando = criar(db, chave_loja, corpo, autor)
        if ao_criar is not None:
            ao_criar(db, chave_loja, comando)
        return {"comando": publico(comando)}

    @router.delete(prefixo + "/comandos/{comando_id}")
    def desistir(comando_id: int, chave_loja: str = Depends(loja_da_sessao), db: Session = Depends(get_db)):
        cancelar(db, chave_loja, comando_id)
        return {"cancelado": True}


def instalar(app: FastAPI, Loja, autenticar) -> APIRouter:
    """Rotas do dono e do caixa. As do fornecedor entram por `instalar_fornecedor`, chamada pela central."""
    from backend.painel import PainelSessao, sessao_do_dono
    Base.metadata.create_all(bind=engine)
    router = APIRouter()

    def loja_do_dono(sessao: PainelSessao = Depends(sessao_do_dono), db: Session = Depends(get_db)) -> str:
        loja = db.query(Loja).filter(Loja.chave_loja == sessao.chave_loja).first()
        if loja is None or not loja.ativa:
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        return sessao.chave_loja

    def loja_do_caixa(acesso=Depends(autenticar)) -> str:
        if acesso.admin:
            raise HTTPException(status_code=403, detail="Use o token da loja para a retaguarda.")
        return acesso.loja

    _rotas_de_leitura_e_escrita(router, "/v1/painel/retaguarda", loja_do_dono, "dono")

    # ---- caixa da loja (token da loja)
    @router.post("/v1/retaguarda/espelho")
    async def subir_espelho(request: Request, chave_loja: str = Depends(loja_do_caixa), db: Session = Depends(get_db)):
        """Uma seção por chamada: {secao, digital, dados}. Ou {remover: [seções]} para o que a loja deixou de usar."""
        bruto = await request.body()
        if len(bruto) > LIMITE_SECAO_BYTES + 4096:
            raise HTTPException(status_code=413, detail="Seção do espelho grande demais.")
        try:
            corpo = json.loads(bruto)
        except ValueError:
            raise HTTPException(status_code=422, detail="Espelho inválido.") from None
        if not isinstance(corpo, dict):
            raise HTTPException(status_code=422, detail="Espelho inválido.")
        remover = corpo.get("remover")
        if isinstance(remover, list):
            nomes = [n for n in remover if isinstance(n, str) and SECAO_VALIDA.match(n)]
            if nomes:
                db.query(RetaguardaEspelho).filter(RetaguardaEspelho.chave_loja == chave_loja,
                                                   RetaguardaEspelho.secao.in_(nomes)).delete(synchronize_session=False)
        nome = corpo.get("secao")
        if nome is not None:
            if not isinstance(nome, str) or not SECAO_VALIDA.match(nome) or not isinstance(corpo.get("dados"), dict):
                raise HTTPException(status_code=422, detail="Seção do espelho inválida.")
            linha = db.query(RetaguardaEspelho).filter_by(chave_loja=chave_loja, secao=nome).first()
            if linha is None:
                if db.query(RetaguardaEspelho.id).filter_by(chave_loja=chave_loja).count() >= LIMITE_SECOES:
                    raise HTTPException(status_code=409, detail="Seções demais no espelho desta loja.")
                linha = RetaguardaEspelho(chave_loja=chave_loja, secao=nome, dados="", atualizado_em=_agora())
                db.add(linha)
            linha.dados = _guardar_json(corpo["dados"])
            linha.digital = str(corpo.get("digital") or "")[:64]
            linha.atualizado_em = _agora()
        db.commit()
        return {"guardada": True, "retaguarda_pendentes": pendentes(db, chave_loja)}

    @router.get("/v1/retaguarda/comandos")
    def buscar(chave_loja: str = Depends(loja_do_caixa), db: Session = Depends(get_db)):
        """Os comandos pendentes, mais antigos primeiro. Continuam pendentes até o caixa contar o resultado."""
        fila = (db.query(RetaguardaComando).filter_by(chave_loja=chave_loja, situacao="pendente")
                .order_by(RetaguardaComando.id).limit(LOTE_ENTREGA).all())
        saida = []
        for c in fila:
            try:
                dados = json.loads(c.dados)
            except ValueError:
                dados = {}
            saida.append({"id": c.id, "tipo": c.tipo, "dados": dados, "resumo": c.resumo, "autor": c.autor,
                          "criado_em": c.criado_em})
        return {"comandos": saida, "restantes": max(pendentes(db, chave_loja) - len(saida), 0)}

    @router.post("/v1/retaguarda/confirmar")
    def confirmar(corpo: dict = Body(...), chave_loja: str = Depends(loja_do_caixa), db: Session = Depends(get_db)):
        """`resultados`: [{id, situacao: aplicado|recusado, detalhe, novo_id}]."""
        resultados = corpo.get("resultados") or []
        if not isinstance(resultados, list) or len(resultados) > 200:
            raise HTTPException(status_code=422, detail="Confirmação inválida.")
        agora, confirmados = _agora(), []
        for item in resultados:
            if not isinstance(item, dict) or type(item.get("id")) is not int or item.get("situacao") not in SITUACOES_FINAIS:
                continue
            comando = db.query(RetaguardaComando).filter_by(id=item["id"], chave_loja=chave_loja).first()
            if comando is None:
                confirmados.append(item["id"])           # cancelado na nuvem: o caixa pode parar de avisar
                continue
            if comando.situacao == "pendente":
                comando.situacao, comando.situacao_em = item["situacao"], agora
                comando.detalhe = str(item.get("detalhe") or "")[:300]
                comando.novo_id = item["novo_id"] if type(item.get("novo_id")) is int else None
                try:                                     # a senha digitada não fica guardada depois de entregue
                    comando.dados = json.dumps(_sem_senha(json.loads(comando.dados)), ensure_ascii=False,
                                               separators=(",", ":"))
                except ValueError:
                    pass
            confirmados.append(item["id"])
        db.commit()
        return {"confirmados": list(dict.fromkeys(confirmados))}

    app.include_router(router)

    # ---- a página: /retaguarda/ serve ao dono (sessão do painel) e ao fornecedor (/retaguarda/?loja=CHAVE, sessão da central).
    if PASTA_WEB.is_dir():
        @app.get("/retaguarda", include_in_schema=False)
        def retaguarda_raiz():
            return RedirectResponse(url="/retaguarda/")

        @app.get("/retaguarda/", include_in_schema=False)
        def retaguarda_index():
            return FileResponse(PASTA_WEB / "index.html", headers={"Cache-Control": "no-cache"})

        app.mount("/retaguarda", StaticFiles(directory=str(PASTA_WEB)), name="retaguarda")
    return router


def instalar_fornecedor(app: FastAPI, sessao, obter, auditar) -> APIRouter:
    """Rotas da central: o fornecedor mexe em qualquer loja. Cada alteração pedida entra na auditoria da central."""
    router = APIRouter()

    def loja_escolhida(chave: str, _=Depends(sessao), db: Session = Depends(get_db)) -> str:
        return obter(db, chave).chave_loja

    def registrar(db: Session, chave_loja: str, comando: RetaguardaComando) -> None:
        auditar(db, "retaguarda", chave_loja, f"{comando.tipo}: {comando.resumo}"[:500])
        db.commit()

    _rotas_de_leitura_e_escrita(router, "/v1/fornecedor/lojas/{chave}/retaguarda", loja_escolhida, "fornecedor", registrar)
    app.include_router(router)
    return router
