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
TIPOS_COMANDO = ("cadastro.salvar", "cadastro.excluir", "estoque.movimento", "config.salvar", "produtos.importar",
                 "produtos.desfazer", "conta.incluir", "conta.alterar", "conta.quitar", "conta.desfazer", "conta.excluir")
SITUACOES_FINAIS = ("aplicado", "recusado")
SO_FORNECEDOR = ("produtos.importar",)      # pela rota genérica, o lote continua serviço do fornecedor
LIMITE_PLANILHA_BYTES = 3 * 1024 * 1024
LIMITE_LOTE = 200                           # produtos por comando (o caixa aplica numa transação só)
CAMPOS_LOTE = ("codigo", "nome", "preco", "custo", "comissao", "comissao_pct", "grupo", "unidade", "quantidade",
               "estoque_minimo", "codigo_barras", "atalho", "controla_estoque", "preco_gelada", "atacado_qtd",
               "preco_atacado", "ncm")


class RetaguardaEspelho(Base):
    __tablename__ = "retaguarda_espelhos"
    __table_args__ = (UniqueConstraint("chave_loja", "secao", name="ux_retaguarda_espelho"),)
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    secao = Column(String, nullable=False)
    digital = Column(String, nullable=False, default="")
    dados = Column(Text, nullable=False)                # JSON comprimido (zlib) em base64
    atualizado_em = Column(String, nullable=False)


class RetaguardaServico(Base):
    """Serviço avulso do fornecedor numa loja (ex.: cadastro de 120 produtos), para cobrar à parte da mensalidade."""
    __tablename__ = "retaguarda_servicos"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    descricao = Column(String, nullable=False)
    valor_cent = Column(Integer, nullable=False)
    criado_em = Column(String, nullable=False)
    pago_em = Column(String, nullable=True)
    pix_id = Column(String, nullable=True)
    pix_copia_cola = Column(Text, nullable=True)
    pix_url = Column(String, nullable=True)


class PrecoServico(Base):
    """Tabela de preços dos serviços do fornecedor (vale para todas as lojas). `por_unidade`: o valor é multiplicado
    pela quantidade informada no lançamento (ex.: R$ 1,50 por produto cadastrado)."""
    __tablename__ = "retaguarda_precos_servico"
    id = Column(Integer, primary_key=True)
    descricao = Column(String, nullable=False)
    valor_cent = Column(Integer, nullable=False)
    por_unidade = Column(Integer, nullable=False, default=0)


COLUNAS_NOVAS = {"retaguarda_servicos": {"pix_id": "VARCHAR", "pix_copia_cola": "TEXT", "pix_url": "VARCHAR"}}


def garantir_colunas(bind=None) -> None:
    from sqlalchemy import inspect, text
    alvo = bind or engine
    with alvo.begin() as con:
        inspetor = inspect(con)
        for tabela, colunas in COLUNAS_NOVAS.items():
            if not inspetor.has_table(tabela):
                continue
            existentes = {c["name"] for c in inspetor.get_columns(tabela)}
            for nome, tipo in colunas.items():
                if nome not in existentes:
                    con.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}"))


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
def criar(db: Session, chave_loja: str, corpo: dict, autor: str, *, liberar_importacao: bool = False) -> RetaguardaComando:
    tipo = corpo.get("tipo")
    dados = corpo.get("dados")
    if tipo not in TIPOS_COMANDO or not isinstance(dados, dict):
        raise HTTPException(status_code=422, detail="Alteração inválida.")
    # O dono importa pela rota do painel (`liberar_importacao`), que grava a prévia e o histórico.
    # A rota genérica de comandos continua restrita ao fornecedor.
    if tipo in SO_FORNECEDOR and autor != "fornecedor" and not (liberar_importacao and tipo == "produtos.importar"):
        raise HTTPException(status_code=403, detail="O cadastro em massa é feito pelo suporte.")
    if tipo == "produtos.importar":
        linhas = dados.get("linhas")
        if not isinstance(linhas, list) or not 0 < len(linhas) <= LIMITE_LOTE or not all(isinstance(l, dict) for l in linhas):
            raise HTTPException(status_code=422, detail=f"Envie de 1 a {LIMITE_LOTE} produtos por vez.")
        modo = dados.get("modo_quantidade", "substituir")
        if modo not in ("substituir", "somar"):
            raise HTTPException(status_code=422, detail="Modo de quantidade inválido: use substituir ou somar.")
    if tipo == "produtos.desfazer":
        itens = dados.get("itens")
        if not isinstance(itens, list) or not 0 < len(itens) <= LIMITE_LOTE or not all(isinstance(i, dict) for i in itens):
            raise HTTPException(status_code=422, detail=f"Envie de 1 a {LIMITE_LOTE} itens para desfazer.")
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
    garantir_colunas()
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


def ler_planilha(nome: str, conteudo_b64: str) -> list[dict]:
    """Planilha (CSV ou Excel) enviada pela central -> linhas com as colunas que o caixa importa. Pelas mesmas regras de
    leitura do caixa (títulos reconhecidos: Produto, Preço, Quantidade...)."""
    from src.controllers.importacao_produtos import ler_tabela_dados
    from src.core.erros import ErroNegocio
    try:
        dados = base64.b64decode(conteudo_b64 or "", validate=True)
    except ValueError:
        raise HTTPException(status_code=422, detail="Arquivo inválido.") from None
    if not dados or len(dados) > LIMITE_PLANILHA_BYTES:
        raise HTTPException(status_code=413, detail="Planilha vazia ou maior que 3 MB.")
    try:
        tabela = ler_tabela_dados(dados, str(nome or "planilha.csv"))
    except ErroNegocio as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from None
    return [{c: str(l.get(c) or "") for c in CAMPOS_LOTE} for l in tabela]


def _servico_publico(s: RetaguardaServico) -> dict:
    return {"id": s.id, "descricao": s.descricao, "valor_cent": s.valor_cent, "criado_em": s.criado_em,
            "pago_em": s.pago_em, "pix_copia_cola": s.pix_copia_cola, "pix_url": s.pix_url}


REFERENCIA_SERVICO = "servico-"


def _texto_servico(nome_loja: str, s: RetaguardaServico) -> str:
    valor = f"R$ {s.valor_cent / 100:.2f}".replace(".", ",")
    linhas = [f"WB SISTEMAS: {s.descricao}", f"Loja: {nome_loja}", f"Valor: {valor}"]
    if s.pix_copia_cola:
        linhas += ["Pix copia e cola:", s.pix_copia_cola]
    return "\n".join(linhas)


def gerar_pix_servico(db: Session, servico: RetaguardaServico) -> RetaguardaServico:
    """Pix do Mercado Pago para o serviço, uma vez só (idempotente). O pagador é o e-mail do plano da loja."""
    from backend import cobranca_mercadopago as mp
    if servico.pago_em:
        raise HTTPException(status_code=409, detail="Este serviço já foi pago.")
    if servico.pix_copia_cola:
        return servico
    plano = db.query(mp.Plano).filter_by(chave_loja=servico.chave_loja).first()
    if plano is None or not plano.email_pagador:
        raise HTTPException(status_code=422, detail="Loja sem e-mail de cobrança: cadastre a mensalidade dela primeiro.")
    referencia = f"{REFERENCIA_SERVICO}{servico.id}"
    corpo = {
        "transaction_amount": mp.reais(servico.valor_cent),
        "description": f"Serviço WillPDV {servico.chave_loja}: {servico.descricao}"[:200],
        "payment_method_id": "pix",
        "date_of_expiration": mp._iso_mp(datetime.now().astimezone() + timedelta(days=7)),
        "external_reference": referencia,
        "payer": {"email": plano.email_pagador},
        "metadata": {"chave_loja": servico.chave_loja, "servico": servico.id},
    }
    notificacao = mp.url_notificacao()
    if notificacao:
        corpo["notification_url"] = notificacao
    try:
        resposta = mp.requisitar("POST", "/v1/payments", corpo, idempotencia=f"willpdv-{referencia}")
    except mp.ErroCobranca as erro:
        raise HTTPException(status_code=502, detail=str(erro)[:200]) from None
    transacao = ((resposta.get("point_of_interaction") or {}).get("transaction_data") or {})
    codigo = transacao.get("qr_code")
    if not isinstance(codigo, str) or len(codigo) < 10:
        raise HTTPException(status_code=502, detail="Mercado Pago não devolveu o Pix copia e cola.")
    servico.pix_id = mp._id_pagamento(resposta.get("id"))
    servico.pix_copia_cola = codigo
    servico.pix_url = mp._https(transacao.get("ticket_url"))
    db.commit()
    return servico


def aplicar_pagamento_servico(db: Session, dados: dict) -> str:
    """Webhook ou conferência: dá baixa no serviço quando o Pix aprovado tem o valor certo. Chamada pela cobrança."""
    from backend import cobranca_mercadopago as mp
    referencia = str(dados.get("external_reference") or "")
    try:
        ident = int(referencia[len(REFERENCIA_SERVICO):])
    except ValueError:
        return "desconhecida"
    servico = db.get(RetaguardaServico, ident)
    if servico is None:
        return "desconhecida"
    try:
        valor = mp.centavos(dados.get("transaction_amount"))
    except mp.ErroCobranca:
        valor = 0
    aprovado = (dados.get("status") == mp.APROVADO and not mp._estornado(dados) and valor == servico.valor_cent
                and dados.get("currency_id", "BRL") == "BRL")
    if aprovado and not servico.pago_em:
        servico.pago_em = _agora()
        db.commit()
    return "processado" if aprovado else "pendente"


def _preco_publico(p: PrecoServico) -> dict:
    return {"id": p.id, "descricao": p.descricao, "valor_cent": p.valor_cent, "por_unidade": bool(p.por_unidade)}


def _valor_valido(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool) and 0 < valor <= 10_000_000


def instalar_fornecedor(app: FastAPI, sessao, obter, auditar) -> APIRouter:
    """Rotas da central: o fornecedor mexe em qualquer loja. Cada alteração pedida entra na auditoria da central."""
    router = APIRouter()
    prefixo = "/v1/fornecedor/lojas/{chave}/retaguarda"

    def loja_escolhida(chave: str, _=Depends(sessao), db: Session = Depends(get_db)) -> str:
        return obter(db, chave).chave_loja

    def registrar(db: Session, chave_loja: str, comando: RetaguardaComando) -> None:
        auditar(db, "retaguarda", chave_loja, f"{comando.tipo}: {comando.resumo}"[:500])
        db.commit()

    @router.post(prefixo + "/planilha")
    def planilha(corpo: dict = Body(...), chave_loja: str = Depends(loja_escolhida)):
        linhas = ler_planilha(corpo.get("nome", ""), corpo.get("conteudo", ""))
        return {"linhas": linhas, "lote": LIMITE_LOTE}

    @router.get(prefixo + "/servicos")
    def servicos(chave_loja: str = Depends(loja_escolhida), db: Session = Depends(get_db)):
        lista = (db.query(RetaguardaServico).filter_by(chave_loja=chave_loja)
                 .order_by(RetaguardaServico.id.desc()).limit(100).all())
        return {"servicos": [_servico_publico(s) for s in lista],
                "a_receber_cent": sum(s.valor_cent for s in lista if not s.pago_em)}

    @router.post(prefixo + "/servicos")
    def novo_servico(corpo: dict = Body(...), chave_loja: str = Depends(loja_escolhida), db: Session = Depends(get_db)):
        descricao = re.sub(r"\s+", " ", str(corpo.get("descricao") or "")).strip()[:200]
        valor = corpo.get("valor_cent")
        if not descricao or not isinstance(valor, int) or isinstance(valor, bool) or not 0 < valor <= 10_000_000:
            raise HTTPException(status_code=422, detail="Informe a descrição e um valor maior que zero.")
        servico = RetaguardaServico(chave_loja=chave_loja, descricao=descricao, valor_cent=valor, criado_em=_agora())
        db.add(servico)
        db.commit()
        auditar(db, "servico", chave_loja, f"{descricao} ({valor / 100:.2f})"[:500])
        db.commit()
        return {"servico": _servico_publico(servico)}

    @router.get("/v1/fornecedor/servicos/a-receber")
    def a_receber(_=Depends(sessao), db: Session = Depends(get_db)):
        """Serviços ainda não pagos de todas as lojas, somados por loja (para a tela inicial da central)."""
        from sqlalchemy import func
        linhas = (db.query(RetaguardaServico.chave_loja, func.count(RetaguardaServico.id), func.sum(RetaguardaServico.valor_cent))
                  .filter(RetaguardaServico.pago_em.is_(None)).group_by(RetaguardaServico.chave_loja).all())
        lojas = [{"chave": c, "servicos": n, "valor_cent": int(v or 0)} for c, n, v in linhas]
        return {"lojas": sorted(lojas, key=lambda x: -x["valor_cent"]), "total_cent": sum(l["valor_cent"] for l in lojas)}

    @router.get("/v1/fornecedor/servicos/catalogo")
    def catalogo(tipo: str = "adega", _=Depends(sessao)):
        from src.controllers.catalogo import CATALOGOS
        if tipo not in CATALOGOS:
            raise HTTPException(422, "Catálogo desconhecido: " + ", ".join(CATALOGOS) + ".")
        linhas = [{**{c: "" for c in CAMPOS_LOTE}, "nome": i.nome, "grupo": i.subgrupo, "ncm": i.ncm, "unidade": "UN"}
                  for i in CATALOGOS[tipo].itens]
        return {"linhas": linhas}

    @router.get("/v1/fornecedor/servicos/precos")
    def precos(_=Depends(sessao), db: Session = Depends(get_db)):
        return {"precos": [_preco_publico(p) for p in db.query(PrecoServico).order_by(PrecoServico.descricao).all()]}

    @router.post("/v1/fornecedor/servicos/precos")
    def novo_preco(corpo: dict = Body(...), _=Depends(sessao), db: Session = Depends(get_db)):
        descricao = re.sub(r"\s+", " ", str(corpo.get("descricao") or "")).strip()[:120]
        if not descricao or not _valor_valido(corpo.get("valor_cent")):
            raise HTTPException(status_code=422, detail="Informe a descrição e um valor maior que zero.")
        preco = PrecoServico(descricao=descricao, valor_cent=corpo["valor_cent"], por_unidade=int(bool(corpo.get("por_unidade"))))
        db.add(preco)
        db.commit()
        return {"preco": _preco_publico(preco)}

    @router.post("/v1/fornecedor/servicos/precos/{preco_id}/excluir")
    def excluir_preco(preco_id: int, _=Depends(sessao), db: Session = Depends(get_db)):
        db.query(PrecoServico).filter_by(id=preco_id).delete()
        db.commit()
        return {"excluido": True}

    @router.post(prefixo + "/servicos/{servico_id}/pix")
    def pix_do_servico(servico_id: int, chave_loja: str = Depends(loja_escolhida), db: Session = Depends(get_db)):
        servico = db.query(RetaguardaServico).filter_by(id=servico_id, chave_loja=chave_loja).first()
        if servico is None:
            raise HTTPException(status_code=404, detail="Serviço não encontrado.")
        servico = gerar_pix_servico(db, servico)
        from backend import cobranca_mercadopago as mp
        plano = db.query(mp.Plano).filter_by(chave_loja=chave_loja).first()
        texto = _texto_servico(obter(db, chave_loja).nome or chave_loja, servico)
        whatsapp = mp.link_whatsapp(plano.whatsapp, texto) if plano is not None and plano.whatsapp else None
        return {"servico": _servico_publico(servico), "texto": texto, "whatsapp": whatsapp}

    @router.post(prefixo + "/servicos/{servico_id}/conferir")
    def conferir_servico(servico_id: int, chave_loja: str = Depends(loja_escolhida), db: Session = Depends(get_db)):
        from backend import cobranca_mercadopago as mp
        servico = db.query(RetaguardaServico).filter_by(id=servico_id, chave_loja=chave_loja).first()
        if servico is None:
            raise HTTPException(status_code=404, detail="Serviço não encontrado.")
        if servico.pix_id and not servico.pago_em:
            try:
                aplicar_pagamento_servico(db, mp.obter_pagamento(servico.pix_id))
            except mp.ErroCobranca as erro:
                raise HTTPException(status_code=502, detail=str(erro)[:200]) from None
        return {"servico": _servico_publico(servico)}

    @router.post(prefixo + "/servicos/{servico_id}/pago")
    def servico_pago(servico_id: int, chave_loja: str = Depends(loja_escolhida), db: Session = Depends(get_db)):
        servico = db.query(RetaguardaServico).filter_by(id=servico_id, chave_loja=chave_loja).first()
        if servico is None:
            raise HTTPException(status_code=404, detail="Serviço não encontrado.")
        if not servico.pago_em:
            servico.pago_em = _agora()
            auditar(db, "servico_pago", chave_loja, servico.descricao[:500])
            db.commit()
        return {"servico": _servico_publico(servico)}

    _rotas_de_leitura_e_escrita(router, prefixo, loja_escolhida, "fornecedor", registrar)
    app.include_router(router)
    return router
