"""Pedido online pelo cardápio (só Will Adega). O cliente monta o pedido no celular, a nuvem guarda e o caixa da adega
busca, aceita (vira uma entrega já preenchida) ou recusa. O WhatsApp do cliente abre com a mensagem pronta para a adega.

Rotas públicas (sem senha, pelo cardápio):
  POST /v1/cardapio/pedido               novo pedido; devolve o número e o link do WhatsApp
  GET  /v1/cardapio/pedido               situação de um pedido (loja + número + telefone)
Rotas do caixa (token da loja):
  GET  /v1/pedidos-online                pedidos novos da loja
  POST /v1/pedidos-online/{id}/aceitar
  POST /v1/pedidos-online/{id}/recusar   {"motivo": "..."}

A configuração (ligado, WhatsApp, bairros e taxas, mínimo, retirada) chega no envio do cardápio. Só vale para loja da
edição Will Adega: boate mostra o cardápio só para consulta. O preço aqui é uma estimativa; o caixa recalcula ao aceitar.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Query
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db

EDICAO = "willadega"
PAGAMENTOS = {"dinheiro": "Dinheiro", "pix": "Pix na entrega", "cartao": "Cartão na entrega"}
MAX_LINHAS = 40
MAX_QTD = 99
ABERTOS_POR_TELEFONE = 3        # pedidos ainda não respondidos pelo caixa, por telefone
POR_TELEFONE_HORA = 6
POR_LOJA_HORA = 120
_TEL = re.compile(r"\d{10,13}")
_CODIGO = re.compile(r"\d{1,14}")


class PedidoOnlineConfig(Base):
    """O que o caixa da adega publicou para o pedido online. Sem linha (ou desligado): só consulta."""
    __tablename__ = "pedido_online_config"
    chave_loja = Column(String, primary_key=True)
    dados = Column(Text, nullable=False, default="{}")
    atualizado_em = Column(String, nullable=False)


class PedidoOnline(Base):
    __tablename__ = "pedidos_online"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chave_loja = Column(String, nullable=False, index=True)
    numero = Column(Integer, nullable=False)
    telefone = Column(String, nullable=False, index=True)
    situacao = Column(String, nullable=False, default="novo")        # novo, aceito, recusado
    dados = Column(Text, nullable=False, default="{}")
    motivo = Column(String, nullable=True)
    criado_em = Column(String, nullable=False, index=True)
    atualizado_em = Column(String, nullable=False)


def _agora() -> datetime:
    return datetime.now()


def _txt(valor, limite: int) -> str:
    return " ".join(str(valor or "").split())[:limite]


def _int(valor, padrao: int = 0) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def _so_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def reais(cent: int) -> str:
    inteiro, centavos = divmod(abs(int(cent)), 100)
    return ("-" if cent < 0 else "") + "R$ " + f"{inteiro:,}".replace(",", ".") + f",{centavos:02d}"


def config_limpa(bruto) -> dict:
    """Só o que o cardápio mostra; nada do que vier a mais."""
    if not isinstance(bruto, dict) or not bruto.get("ligado"):
        return {"ligado": False}
    bairros = []
    for b in (bruto.get("bairros") or [])[:300]:
        if isinstance(b, dict) and _txt(b.get("nome"), 60):
            bairros.append({"nome": _txt(b.get("nome"), 60), "taxa_cent": max(0, min(_int(b.get("taxa_cent")), 100000))})
    whatsapp = _so_digitos(bruto.get("whatsapp"))
    return {
        "ligado": True,
        "whatsapp": whatsapp if _TEL.fullmatch(whatsapp) else "",
        "minimo_cent": max(0, min(_int(bruto.get("minimo_cent")), 10_000_000)),
        "taxa_padrao_cent": max(0, min(_int(bruto.get("taxa_padrao_cent")), 100000)),
        "retirada": bool(bruto.get("retirada", True)),
        "bairros": bairros,
    }


def pode_pedir(loja, edicao_enviada) -> bool:
    """Só loja Will Adega: o caixa diz a edição e o cadastro da central não pode dizer outra."""
    cadastro = (getattr(loja, "edicao", None) or "").strip().lower()
    return str(edicao_enviada or "").strip().lower() == EDICAO and cadastro in ("", EDICAO)


def gravar_config(db: Session, loja, bruto, edicao_enviada) -> dict:
    """Chamado no envio do cardápio. Boate (ou cadastro de outra edição) fica sempre desligada."""
    cfg = config_limpa(bruto) if pode_pedir(loja, edicao_enviada) else {"ligado": False}
    linha = db.get(PedidoOnlineConfig, loja.chave_loja)
    if linha is None:
        linha = PedidoOnlineConfig(chave_loja=loja.chave_loja)
        db.add(linha)
    linha.dados = json.dumps(cfg, ensure_ascii=False)
    linha.atualizado_em = _agora().strftime("%Y-%m-%d %H:%M:%S")
    return cfg


def config_da_loja(db: Session, loja) -> dict:
    linha = db.get(PedidoOnlineConfig, loja.chave_loja)
    if linha is None:
        return {"ligado": False}
    try:
        cfg = json.loads(linha.dados or "{}")
    except ValueError:
        return {"ligado": False}
    if not isinstance(cfg, dict) or not cfg.get("ligado") or (getattr(loja, "edicao", None) or "").strip().lower() \
            not in ("", EDICAO):
        return {"ligado": False}
    return cfg


def config_publica(db: Session, loja) -> dict | None:
    """Para o cardápio: None quando não há pedido online (boate, desligado ou sem WhatsApp)."""
    cfg = config_da_loja(db, loja)
    if not cfg.get("ligado") or not cfg.get("whatsapp"):
        return None
    return {k: cfg[k] for k in ("minimo_cent", "taxa_padrao_cent", "retirada", "bairros")} | {
        "pagamentos": [{"chave": k, "nome": v} for k, v in PAGAMENTOS.items()]}


def texto_whatsapp(nome_loja: str, numero: int, d: dict) -> str:
    linhas = [f"*Pedido #{numero}* - {nome_loja}".strip(" -"), ""]
    for i in d["itens"]:
        linhas.append(f"{i['qtd']}x {i['nome']} - {reais(i['qtd'] * i['preco_cent'])}")
    linhas.append("")
    if d["retirada"]:
        linhas.append("Retirar na loja")
    else:
        linhas.append(f"Entrega: {d['endereco']} - {d['bairro'] or 'bairro não informado'}")
        linhas.append(f"Taxa de entrega: {reais(d['taxa_cent'])}")
    linhas.append(f"*Total: {reais(d['total_cent'])}*")
    pagamento = PAGAMENTOS[d["pagamento"]]
    if d["pagamento"] == "dinheiro" and d.get("troco_para_cent"):
        pagamento += f" (troco para {reais(d['troco_para_cent'])})"
    linhas.append(f"Pagamento: {pagamento}")
    if d.get("observacao"):
        linhas.append(f"Obs.: {d['observacao']}")
    linhas.append(f"{d['nome']} - {d['telefone']}")
    return "\n".join(linhas)


def montar_pedido(cfg: dict, catalogo: dict[str, dict], corpo: dict, quando: datetime | None = None) -> dict:
    """Valida o que o cliente mandou e calcula o total estimado com o preço do cardápio naquele momento."""
    from src.cardapio.preco import preco_para_cardapio
    nome = _txt(corpo.get("nome"), 60)
    telefone = _so_digitos(corpo.get("telefone"))
    retirada = bool(corpo.get("retirada")) and cfg.get("retirada", True)
    endereco = _txt(corpo.get("endereco"), 160)
    bairro = _txt(corpo.get("bairro"), 60)
    pagamento = str(corpo.get("pagamento") or "")
    if len(nome) < 2:
        raise HTTPException(status_code=422, detail="Informe o seu nome.")
    if not _TEL.fullmatch(telefone):
        raise HTTPException(status_code=422, detail="Informe o telefone com DDD (só números).")
    if not retirada and len(endereco) < 5:
        raise HTTPException(status_code=422, detail="Informe o endereço de entrega.")
    if pagamento not in PAGAMENTOS:
        raise HTTPException(status_code=422, detail="Escolha a forma de pagamento.")
    linhas = corpo.get("itens")
    if not isinstance(linhas, list) or not linhas:
        raise HTTPException(status_code=422, detail="O carrinho está vazio.")
    if len(linhas) > MAX_LINHAS:
        raise HTTPException(status_code=422, detail=f"No máximo {MAX_LINHAS} produtos diferentes por pedido.")
    itens: dict[str, dict] = {}
    for linha in linhas:
        if not isinstance(linha, dict):
            raise HTTPException(status_code=422, detail="Item inválido.")
        codigo = str(linha.get("codigo") or "").strip()
        qtd = _int(linha.get("qtd"), 0)
        produto = catalogo.get(codigo) if _CODIGO.fullmatch(codigo) else None
        if produto is None:
            raise HTTPException(status_code=422, detail="Um produto do carrinho saiu do cardápio. Atualize a página.")
        if not 1 <= qtd <= MAX_QTD:
            raise HTTPException(status_code=422, detail=f"Quantidade de 1 a {MAX_QTD} por produto.")
        atual = itens.get(codigo)
        if atual:
            atual["qtd"] = min(MAX_QTD, atual["qtd"] + qtd)
        else:
            itens[codigo] = {"codigo": codigo, "nome": produto["nome"], "qtd": qtd,
                             "preco_cent": preco_para_cardapio(produto, quando)["preco_cent"]}
    subtotal = sum(i["qtd"] * i["preco_cent"] for i in itens.values())
    if subtotal < cfg.get("minimo_cent", 0):
        raise HTTPException(status_code=422, detail=f"O pedido mínimo é {reais(cfg['minimo_cent'])}.")
    taxa = 0
    if not retirada:
        achado = next((b for b in cfg.get("bairros", []) if b["nome"].lower() == bairro.lower()), None)
        taxa = achado["taxa_cent"] if achado else cfg.get("taxa_padrao_cent", 0)
        bairro = achado["nome"] if achado else bairro
    troco = max(0, _int(corpo.get("troco_para_cent"))) if pagamento == "dinheiro" else 0
    total = subtotal + taxa
    if troco and troco < total:
        raise HTTPException(status_code=422, detail="O valor para troco é menor que o total.")
    return {
        "nome": nome, "telefone": telefone, "retirada": retirada, "endereco": "" if retirada else endereco,
        "bairro": "" if retirada else bairro, "pagamento": pagamento, "troco_para_cent": troco,
        "observacao": _txt(corpo.get("observacao"), 200), "itens": list(itens.values()),
        "subtotal_cent": subtotal, "taxa_cent": taxa, "total_cent": total,
    }


def _publico(p: PedidoOnline) -> dict:
    try:
        dados = json.loads(p.dados or "{}")
    except ValueError:
        dados = {}
    return {"id": p.id, "numero": p.numero, "situacao": p.situacao, "criado_em": p.criado_em,
            "motivo": p.motivo or "", **(dados if isinstance(dados, dict) else {})}


def instalar(app: FastAPI, Loja, autenticar, loja_ativa, catalogo_da_loja) -> APIRouter:
    """`loja_ativa(db, chave)` e `catalogo_da_loja(db, chave)` vêm do cardápio (mesma validação e mesmo catálogo)."""
    Base.metadata.create_all(bind=engine)
    router = APIRouter()

    @router.post("/v1/cardapio/pedido")
    def novo(corpo: dict = Body(...), db: Session = Depends(get_db)):
        loja = loja_ativa(db, str(corpo.get("loja") or "").strip())
        cfg = config_publica(db, loja)
        if cfg is None:
            raise HTTPException(status_code=404, detail="Esta loja não recebe pedidos online.")
        cfg = config_da_loja(db, loja)
        nome_loja, catalogo = catalogo_da_loja(db, loja)
        from backend.cardapio import agora_local
        dados = montar_pedido(cfg, catalogo, corpo, agora_local())
        agora = _agora()
        hora_atras = (agora - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        base = db.query(PedidoOnline).filter(PedidoOnline.chave_loja == loja.chave_loja)
        if base.filter(PedidoOnline.telefone == dados["telefone"], PedidoOnline.situacao == "novo").count() \
                >= ABERTOS_POR_TELEFONE or base.filter(PedidoOnline.telefone == dados["telefone"],
                                                        PedidoOnline.criado_em >= hora_atras).count() >= POR_TELEFONE_HORA:
            raise HTTPException(status_code=429, detail="Você já tem pedidos aguardando. Fale com a loja pelo WhatsApp.")
        if base.filter(PedidoOnline.criado_em >= hora_atras).count() >= POR_LOJA_HORA:
            raise HTTPException(status_code=429, detail="A loja está com muitos pedidos agora. Tente em instantes.")
        numero = (db.query(PedidoOnline.numero).filter(PedidoOnline.chave_loja == loja.chave_loja)
                  .order_by(PedidoOnline.numero.desc()).limit(1).scalar() or 0) + 1
        quando = agora.strftime("%Y-%m-%d %H:%M:%S")
        pedido = PedidoOnline(chave_loja=loja.chave_loja, numero=numero, telefone=dados["telefone"], situacao="novo",
                              dados=json.dumps(dados, ensure_ascii=False), criado_em=quando, atualizado_em=quando)
        db.add(pedido)
        db.commit()
        texto = texto_whatsapp(nome_loja, numero, dados)
        return {"numero": numero, "total_cent": dados["total_cent"], "texto": texto,
                "whatsapp_url": f"https://wa.me/{cfg['whatsapp']}?text={quote(texto)}"}

    @router.get("/v1/cardapio/pedido")
    def situacao(loja: str = Query(..., max_length=64), numero: int = Query(..., ge=1),
                 telefone: str = Query(..., max_length=20), db: Session = Depends(get_db)):
        cadastro = loja_ativa(db, loja.strip())
        p = (db.query(PedidoOnline).filter(PedidoOnline.chave_loja == cadastro.chave_loja,
                                           PedidoOnline.numero == numero,
                                           PedidoOnline.telefone == _so_digitos(telefone)).first())
        if p is None:
            raise HTTPException(status_code=404, detail="Pedido não encontrado.")
        return {"numero": p.numero, "situacao": p.situacao, "motivo": p.motivo or ""}

    def _do_caixa(acesso) -> str:
        if acesso.admin:
            raise HTTPException(status_code=403, detail="Use o token da loja.")
        return acesso.loja

    @router.get("/v1/pedidos-online")
    def listar(acesso=Depends(autenticar), db: Session = Depends(get_db)):
        chave = _do_caixa(acesso)
        pedidos = (db.query(PedidoOnline).filter(PedidoOnline.chave_loja == chave, PedidoOnline.situacao == "novo")
                   .order_by(PedidoOnline.id).limit(50).all())
        return {"pedidos": [_publico(p) for p in pedidos]}

    def _responder(pedido_id: int, acesso, db: Session, situacao_nova: str, motivo: str | None = None) -> dict:
        chave = _do_caixa(acesso)
        p = db.get(PedidoOnline, pedido_id)
        if p is None or p.chave_loja != chave:
            raise HTTPException(status_code=404, detail="Pedido não encontrado.")
        if p.situacao != "novo":
            if p.situacao == situacao_nova:
                return {"situacao": p.situacao}          # repetir é inofensivo (o caixa tenta de novo sem rede)
            raise HTTPException(status_code=409, detail=f"Este pedido já foi {p.situacao}.")
        p.situacao = situacao_nova
        p.motivo = motivo
        p.atualizado_em = _agora().strftime("%Y-%m-%d %H:%M:%S")
        db.commit()
        return {"situacao": p.situacao}

    @router.post("/v1/pedidos-online/{pedido_id}/aceitar")
    def aceitar(pedido_id: int, acesso=Depends(autenticar), db: Session = Depends(get_db)):
        return _responder(pedido_id, acesso, db, "aceito")

    @router.post("/v1/pedidos-online/{pedido_id}/recusar")
    def recusar(pedido_id: int, corpo: dict = Body(default={}), acesso=Depends(autenticar),
                db: Session = Depends(get_db)):
        motivo = _txt((corpo or {}).get("motivo"), 160)
        if not motivo:
            raise HTTPException(status_code=422, detail="Informe o motivo da recusa.")
        return _responder(pedido_id, acesso, db, "recusado", motivo)

    app.include_router(router)
    return router
