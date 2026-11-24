"""Importação de produtos pelo painel do dono (e pelo assistente da loja).

A planilha é a mesma do caixa (CSV ou Excel). A nuvem só lê o espelho que o caixa já subiu, mostra a prévia
e enfileira `produtos.importar`. Quem grava é o caixa, na próxima sincronização. O mesmo código de barras
atualiza o produto; não cria outro.

Autenticação: a sessão do painel (`Authorization: Bearer`) ou um token `wpdv_...` gerado no painel.
O token aparece uma vez e fica guardado só como hash. Na rede, informe `loja` (a chave da loja de destino).
"""
from __future__ import annotations

import base64
import csv
import io
import json
import re
import secrets
from dataclasses import dataclass

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db
from src.core.formatacao import texto_planilha
from backend.retaguarda import (
    LIMITE_LOTE, LIMITE_PENDENTES, LIMITE_PLANILHA_BYTES, criar, pendentes, secao,
)
from src.controllers.importacao_produtos import (
    COLUNAS, LIMITE_LINHAS, TITULOS, ImportacaoProdutos, _coluna_de, classificar_espelho, codigo_curto,
    escrever_xlsx, ler_tabela_dados,
)
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

PREFIXO = "/v1/painel/importacao"
MODOS = ("substituir", "somar")
TEXTOS_QUANTIDADE = {
    "substituir": "A quantidade da planilha substitui o estoque atual do produto.",
    "somar": "A quantidade da planilha soma ao estoque atual. Produto novo começa com essa quantidade.",
}
LIMITE_TOKENS = 5
LIMITE_BUSCA = 50
COLUNAS_CSV = ("codigo", "nome", "preco", "custo", "grupo", "unidade", "quantidade", "codigo_barras")
NOME_TOKEN = re.compile(r"[A-Za-z0-9 ._-]{1,40}")


class PainelTokenApi(Base):
    """Token de API de uma loja. O segredo não fica aqui: só o hash."""
    __tablename__ = "painel_tokens_api"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    nome = Column(String, nullable=False)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    criado_em = Column(String, nullable=False)
    ultimo_uso = Column(String, nullable=True)
    revogado_em = Column(String, nullable=True)


class PainelImportacao(Base):
    """O que foi enfileirado, para o histórico e para desfazer a última."""
    __tablename__ = "painel_importacoes"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    autor = Column(String, nullable=False)
    criado_em = Column(String, nullable=False)
    modo_quantidade = Column(String, nullable=False)
    criar = Column(Integer, nullable=False, default=0)
    atualizar = Column(Integer, nullable=False, default=0)
    recusar = Column(Integer, nullable=False, default=0)
    resumo = Column(String, nullable=False, default="")
    snapshot = Column(Text, nullable=False, default="[]")
    comando_ids = Column(String, nullable=False, default="")
    desfeito_em = Column(String, nullable=True)


def garantir_tabelas() -> None:
    PainelTokenApi.__table__.create(bind=engine, checkfirst=True)
    PainelImportacao.__table__.create(bind=engine, checkfirst=True)


@dataclass
class AcessoImportacao:
    tipo: str                       # "sessao" ou "token"
    chave_loja: str | None          # loja da sessão ou do token; None na sessão da rede
    grupo_id: int | None
    autor: str


def _painel():
    from backend import painel
    return painel


def _agora() -> str:
    return _painel()._agora()


def _norm(texto: str) -> str:
    from backend.retaguarda import _norm as norm
    return norm(texto)


def instalar(router: APIRouter, Loja) -> None:
    garantir_tabelas()

    def acesso(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> AcessoImportacao:
        painel = _painel()
        token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
        if not token:
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        if token.startswith("wpdv_"):
            linha = db.query(PainelTokenApi).filter_by(token_hash=painel._hash(token), revogado_em=None).first()
            if linha is None:
                raise HTTPException(status_code=401, detail="Token inválido ou revogado.")
            linha.ultimo_uso = _agora()
            db.commit()
            return AcessoImportacao("token", linha.chave_loja, None, f"token:{linha.nome}"[:60])
        sessao = db.query(painel.PainelSessao).filter_by(token_hash=painel._hash(token)).first()
        if sessao is None or sessao.expira_em <= _agora():
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        sessao.ultimo_uso = _agora()
        db.commit()
        from backend.memoria_nuvem import memoria
        if sessao.grupo_id:
            return AcessoImportacao("sessao", None, sessao.grupo_id, "dono")
        memoria.lembrar_sessao(token, sessao.chave_loja)
        return AcessoImportacao("sessao", sessao.chave_loja, None, "dono")

    def loja_de(db: Session, quem: AcessoImportacao, pedida: str | None) -> str:
        pedida = str(pedida or "").strip()
        if quem.tipo == "token":
            if pedida and pedida != quem.chave_loja:
                raise HTTPException(status_code=403, detail="Este token é de outra loja.")
            return quem.chave_loja or ""
        if quem.grupo_id:
            if not pedida:
                raise HTTPException(status_code=422, detail="Escolha a loja de destino.")
            loja = db.query(Loja).filter(Loja.chave_loja == pedida, Loja.grupo_id == quem.grupo_id,
                                         Loja.ativa.is_(True)).first()
            if loja is None:
                raise HTTPException(status_code=404, detail="Esta loja não está na sua rede.")
            return pedida
        if not quem.chave_loja:
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        if pedida and pedida != quem.chave_loja:
            raise HTTPException(status_code=403, detail="A sessão é de outra loja.")
        loja = db.query(Loja).filter(Loja.chave_loja == quem.chave_loja, Loja.ativa.is_(True)).first()
        if loja is None:
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        return quem.chave_loja

    @router.post(PREFIXO)
    def importar_lote(corpo: dict = Body(...), quem: AcessoImportacao = Depends(acesso), db: Session = Depends(get_db)):
        """`dry_run: false` grava a fila. Sem esse campo, ou com true, só devolve a prévia."""
        return executar(db, Loja, quem, corpo, aplicar=corpo.get("dry_run") is False)

    @router.post(PREFIXO + "/previa")
    def previa(corpo: dict = Body(...), quem: AcessoImportacao = Depends(acesso), db: Session = Depends(get_db)):
        return executar(db, Loja, quem, corpo, aplicar=False)

    @router.post(PREFIXO + "/aplicar")
    def aplicar(corpo: dict = Body(...), quem: AcessoImportacao = Depends(acesso), db: Session = Depends(get_db)):
        return executar(db, Loja, quem, corpo, aplicar=True)

    @router.get(PREFIXO + "/modelo")
    def modelo(_: AcessoImportacao = Depends(acesso)):
        texto = "\ufeff" + object.__new__(ImportacaoProdutos).modelo()
        return Response(texto.encode("utf-8"), media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": 'attachment; filename="modelo-produtos.csv"'})

    @router.get(PREFIXO + "/produtos")
    def produtos(q: str = Query("", max_length=80), formato: str = Query("json", max_length=8),
                 loja: str = Query("", max_length=64), quem: AcessoImportacao = Depends(acesso),
                 db: Session = Depends(get_db)):
        chave = loja_de(db, quem, loja)
        lista = filtrar(catalogo(db, chave)["produtos"], q)
        if formato == "json":
            return {"loja": chave, "total": len(lista), "limite": LIMITE_BUSCA,
                    "produtos": [produto_publico(p) for p in lista[:LIMITE_BUSCA]]}
        if formato == "csv":
            conteudo = "\ufeff" + csv_produtos(lista)
            return Response(conteudo.encode("utf-8"), media_type="text/csv; charset=utf-8", headers={
                "Content-Disposition": f'attachment; filename="{nome_arquivo(chave, "csv")}"'})
        if formato == "xlsx":
            return Response(xlsx_produtos(lista), headers={
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "Content-Disposition": f'attachment; filename="{nome_arquivo(chave, "xlsx")}"'})
        raise HTTPException(status_code=422, detail="Formato inválido: use json, csv ou xlsx.")

    @router.get(PREFIXO + "/historico")
    def historico(loja: str = Query("", max_length=64), quem: AcessoImportacao = Depends(acesso),
                  db: Session = Depends(get_db)):
        chave = loja_de(db, quem, loja)
        return {"importacoes": historico_publico(db, chave)}

    @router.post(PREFIXO + "/desfazer")
    def desfazer(corpo: dict = Body(default={}), quem: AcessoImportacao = Depends(acesso),
                 db: Session = Depends(get_db)):
        chave = loja_de(db, quem, (corpo or {}).get("loja"))
        return desfazer_ultima(db, chave, quem.autor)

    @router.get(PREFIXO + "/tokens")
    def listar_tokens(loja: str = Query("", max_length=64), quem: AcessoImportacao = Depends(acesso),
                      db: Session = Depends(get_db)):
        chave = loja_de(db, quem, loja)
        return {"tokens": tokens_publicos(db, chave)}

    @router.post(PREFIXO + "/tokens")
    def criar_token(corpo: dict = Body(default={}), quem: AcessoImportacao = Depends(acesso),
                    db: Session = Depends(get_db)):
        if quem.tipo != "sessao":
            raise HTTPException(status_code=403, detail="Entre no painel para gerar um token. O token não cria outro token.")
        chave = loja_de(db, quem, (corpo or {}).get("loja"))
        return novo_token(db, chave, (corpo or {}).get("nome"))

    @router.delete(PREFIXO + "/tokens/{token_id}")
    def revogar_token(token_id: int, loja: str = Query("", max_length=64), quem: AcessoImportacao = Depends(acesso),
                      db: Session = Depends(get_db)):
        if quem.tipo != "sessao":
            raise HTTPException(status_code=403, detail="Entre no painel para revogar um token.")
        chave = loja_de(db, quem, loja)
        linha = db.query(PainelTokenApi).filter_by(id=token_id, chave_loja=chave).first()
        if linha is None:
            raise HTTPException(status_code=404, detail="Token não encontrado.")
        if not linha.revogado_em:
            linha.revogado_em = _agora()
            db.commit()
        return {"revogado": True}


def executar(db: Session, Loja, quem: AcessoImportacao, corpo: dict, *, aplicar: bool) -> dict:
    if not isinstance(corpo, dict):
        raise HTTPException(status_code=422, detail="Envio inválido.")
    chave = _loja_pedida(db, Loja, quem, corpo.get("loja"))
    modo = str(corpo.get("modo_quantidade") or "substituir")
    if modo not in MODOS:
        raise HTTPException(status_code=422, detail="Modo de quantidade inválido: use substituir ou somar.")
    tabela = ler_entrada(corpo)
    cat = catalogo(db, chave)
    linhas = classificar_espelho(tabela, cat["produtos"], unidades=cat["unidades"], grupos=cat["grupos"])
    resposta = montar_resposta(chave, modo, cat["quando"], linhas, aplicar=False)
    if not aplicar:
        return resposta
    importaveis = [l for l in linhas if l["acao"] != "recusar"]
    if not importaveis:
        raise HTTPException(status_code=422, detail="Nenhum produto para importar. Corrija as linhas com erro.")
    if importacao_pendente(db, chave):
        raise HTTPException(status_code=409, detail=(
            "Ainda há uma importação esperando o caixa. Aguarde a sincronização ou cancele em Alterações enviadas."))
    comandos = enfileirar(db, chave, quem.autor, modo, importaveis, resposta["erros"])
    mensagem = ("Enviado ao caixa. Ele busca em seguida: em geral em menos de meio minuto com a loja aberta, "
                "e em poucos segundos se o programa do caixa estiver atualizado.")
    if any(str((l.get("comando") or {}).get("custo") or "").strip() for l in importaveis):
        mensagem += (" O custo segue numa segunda alteração. Um caixa antigo grava os produtos e pode recusar só "
                     "o custo; em Alterações enviadas, use Enviar de novo depois de atualizar o programa.")
    resposta.update({"dry_run": False, "enfileirado": True, "comandos": comandos,
                     "importacao_id": comandos and _ultima_id(db, chave),
                     "mensagem": mensagem})
    return resposta


def _loja_pedida(db, Loja, quem: AcessoImportacao, pedida) -> str:
    """A mesma regra de `loja_de`, para a função usada fora das rotas."""
    pedida = str(pedida or "").strip()
    if quem.tipo == "token":
        if pedida and pedida != quem.chave_loja:
            raise HTTPException(status_code=403, detail="Este token é de outra loja.")
        return quem.chave_loja or ""
    if quem.grupo_id:
        if not pedida:
            raise HTTPException(status_code=422, detail="Escolha a loja de destino.")
        loja = db.query(Loja).filter(Loja.chave_loja == pedida, Loja.grupo_id == quem.grupo_id,
                                     Loja.ativa.is_(True)).first()
        if loja is None:
            raise HTTPException(status_code=404, detail="Esta loja não está na sua rede.")
        return pedida
    if not quem.chave_loja:
        raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
    if pedida and pedida != quem.chave_loja:
        raise HTTPException(status_code=403, detail="A sessão é de outra loja.")
    loja = db.query(Loja).filter(Loja.chave_loja == quem.chave_loja, Loja.ativa.is_(True)).first()
    if loja is None:
        raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
    return quem.chave_loja


def ler_entrada(corpo: dict) -> list[dict]:
    arquivo = corpo.get("conteudo_b64") or corpo.get("conteudo")
    texto = corpo.get("texto")
    linhas = corpo.get("linhas")
    tem_arquivo = bool(arquivo)
    tem_texto = isinstance(texto, str) and bool(texto.strip())
    tem_linhas = isinstance(linhas, list)
    if not (tem_arquivo or tem_texto or tem_linhas):
        raise HTTPException(status_code=422, detail="Envie a planilha, o texto colado ou a lista de produtos.")
    if sum((tem_arquivo, tem_texto, tem_linhas)) != 1:
        raise HTTPException(status_code=422, detail="Envie só um: a planilha, o texto colado ou a lista de produtos.")
    if tem_linhas:
        if not linhas or len(linhas) > LIMITE_LINHAS:
            raise HTTPException(status_code=422, detail=f"Envie de 1 a {LIMITE_LINHAS} produtos.")
        saida = []
        for n, item in enumerate(linhas, start=1):
            if not isinstance(item, dict):
                raise HTTPException(status_code=422, detail="Cada produto da lista precisa ser um objeto.")
            linha = {"_linha": int(item["_linha"]) if isinstance(item.get("_linha"), int) else n}
            for chave, valor in item.items():
                if str(chave).startswith("_"):
                    continue
                coluna = chave if chave in COLUNAS or chave == "comissao_pct" else _coluna_de(str(chave))
                if coluna and coluna not in linha:
                    linha[coluna] = _celula(valor)
            saida.append(linha)
        return saida
    if tem_texto:
        dados, nome = texto.encode("utf-8"), "colado.csv"
    else:
        try:
            dados = base64.b64decode(str(arquivo), validate=True)
        except ValueError:
            raise HTTPException(status_code=422, detail="Arquivo inválido.") from None
        nome = str(corpo.get("nome") or "planilha.csv")
        if dados[:2] == b"PK" and not nome.lower().endswith((".xlsx", ".xlsm")):
            nome = "planilha.xlsx"
    if not dados or len(dados) > LIMITE_PLANILHA_BYTES:
        raise HTTPException(status_code=413, detail="Planilha vazia ou maior que 3 MB.")
    try:
        return ler_tabela_dados(dados, nome)
    except ErroNegocio as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from None


def _celula(valor) -> str:
    if valor is None or isinstance(valor, bool):
        return ""
    if isinstance(valor, float):
        return format(valor, "f").rstrip("0").rstrip(".")
    if isinstance(valor, int):
        return str(valor)
    return str(valor).strip()


def catalogo(db: Session, chave: str) -> dict:
    produtos, quando = secao(db, chave, "cadastro:produtos")
    esquema, _ = secao(db, chave, "esquema")
    if esquema is None or produtos is None:
        raise HTTPException(status_code=409, detail=(
            "A loja ainda não enviou o cadastro. Ligue a retaguarda no caixa (Configurações > Nuvem) "
            "e aguarde a sincronização."))
    unidades = _linhas(secao(db, chave, "cadastro:unidades")[0])
    subgrupos = _linhas(secao(db, chave, "cadastro:subgrupos")[0])
    grupos = _linhas(secao(db, chave, "cadastro:grupos")[0])
    abrev, un_por_id = set(), {}
    for u in unidades:
        ab = str(u.get("abreviatura") or "").strip().upper()
        if ab:
            abrev.add(ab)
            un_por_id[u.get("id")] = ab
    if not abrev:
        abrev.add("UN")
    nomes = {ImportacaoProdutos._k(str(g.get("nome") or "")) for g in grupos}
    sub_por_id = {}
    for s in subgrupos:
        nome = str(s.get("nome") or "").strip()
        if nome:
            nomes.add(ImportacaoProdutos._k(nome))
            sub_por_id[s.get("id")] = nome
    lista = []
    for p in _linhas(produtos):
        lista.append({
            "id": p.get("id"),
            "codigo": p.get("codigo") or "",
            "nome": p.get("nome") or "",
            "cbarra": p.get("cbarra") or "",
            "ativo": bool(p.get("ativo")),
            "preco_cent": int(p.get("preco_cent") or 0),
            "custo_medio_cent": int(p.get("custo_medio_cent") or 0),
            "qt_atual": 0 if p.get("qt_atual") is None else p.get("qt_atual"),
            "controla_estoque": bool(p.get("controla_estoque")),
            "grupo": sub_por_id.get(p.get("subgrupo_id"), ""),
            "unidade": un_por_id.get(p.get("unidade_id"), "UN"),
        })
    return {"produtos": lista, "unidades": abrev, "grupos": nomes, "quando": quando}


def _linhas(dados) -> list[dict]:
    if not isinstance(dados, dict):
        return []
    campos = dados.get("campos") or []
    return [dict(zip(campos, linha)) for linha in (dados.get("linhas") or []) if isinstance(linha, (list, tuple))]


def montar_resposta(chave: str, modo: str, quando, linhas: list[dict], *, aplicar: bool) -> dict:
    return {
        "loja": chave,
        "dry_run": not aplicar,
        "modo_quantidade": modo,
        "quantidade_texto": TEXTOS_QUANTIDADE[modo],
        "espelho_em": quando,
        "criados": sum(l["acao"] == "criar" for l in linhas),
        "atualizados": sum(l["acao"] == "atualizar" for l in linhas),
        "erros": sum(l["acao"] == "recusar" for l in linhas),
        "linhas": [linha_publica(l) for l in linhas],
    }


def linha_publica(linha: dict) -> dict:
    return {k: v for k, v in linha.items() if k not in ("anterior", "comando")}


def separar_custo(linhas: list[dict]) -> tuple[list[dict], list[dict]]:
    """O caixa antigo recusa o lote inteiro se uma atualização traz custo e quem está logado não é gerente.

    O primeiro comando grava nome, preço e estoque sem custo (entra mesmo no programa antigo). O segundo
    só completa o custo, sem mexer de novo na quantidade. O programa novo aplica os dois; o antigo aplica
    o primeiro e pode recusar o segundo, que continua na fila para o botão Enviar de novo."""
    sem, com = [], []
    for linha in linhas:
        if str(linha.get("custo") or "").strip():
            sem.append({**linha, "custo": ""})
            com.append({**linha, "quantidade": ""})
        else:
            sem.append(dict(linha))
    return sem, com


def enfileirar(db: Session, chave: str, autor: str, modo: str, linhas: list[dict], erros: int = 0) -> list[int]:
    extra = {"casar_barras": True, "modo_quantidade": modo, "atualizar_existentes": True}
    sem_custo, so_custo = separar_custo([l["comando"] for l in linhas])
    lotes = fatiar("linhas", sem_custo, extra) if sem_custo else []
    lotes_custo = fatiar("linhas", so_custo, {**extra, "modo_quantidade": "substituir"}) if so_custo else []
    if pendentes(db, chave) + len(lotes) + len(lotes_custo) > LIMITE_PENDENTES:
        raise HTTPException(status_code=409, detail=(
            "Há alterações demais esperando o caixa. Aguarde a loja aplicar as que já estão na fila."))
    criados = sum(l["acao"] == "criar" for l in linhas)
    atualizados = sum(l["acao"] == "atualizar" for l in linhas)
    registro = PainelImportacao(
        chave_loja=chave, autor=autor, criado_em=_agora(), modo_quantidade=modo, criar=criados,
        atualizar=atualizados, recusar=erros, resumo=f"{criados} novos, {atualizados} atualizações",
        snapshot=json.dumps(snapshot(linhas), ensure_ascii=False, separators=(",", ":")), comando_ids="")
    db.add(registro)
    db.flush()
    ids = []
    partes = [("produtos", lotes), ("custo", lotes_custo)]
    for rotulo, grupo in partes:
        total = len(grupo)
        for i, dados in enumerate(grupo, start=1):
            resumo = resumo_do_lote(registro.id, rotulo, dados, i, total, criados, atualizados)
            comando = criar(db, chave, {"tipo": "produtos.importar", "dados": dados, "resumo": resumo[:200]},
                            autor, liberar_importacao=True)
            ids.append(comando.id)
    registro.comando_ids = ",".join(str(i) for i in ids)
    db.commit()
    return ids


def resumo_do_lote(ident: int, rotulo: str, dados: dict, indice: int, lotes: int, criados: int = 0,
                   atualizados: int = 0) -> str:
    qtd = len(dados.get("linhas") or [])
    if rotulo == "custo":
        return f"Importação #{ident}: custo de {qtd} produto(s) ({indice}/{lotes})"
    return f"Importação #{ident}: {criados} novos, {atualizados} atualizações ({indice}/{lotes})"


def snapshot(linhas: list[dict]) -> list[dict]:
    itens = []
    for linha in linhas:
        if linha["acao"] not in ("criar", "atualizar"):
            continue
        item = {"acao": linha["acao"], "nome": linha["nome"], "codigo": linha["codigo"],
                "codigo_barras": linha["codigo_barras"]}
        if linha["acao"] == "atualizar":
            item["anterior"] = linha.get("anterior") or {}
        itens.append(item)
    return itens


def fatiar(campo: str, itens: list, extra: dict) -> list[dict]:
    lotes, atual = [], []
    for item in itens:
        proposta = atual + [item]
        corpo = {**extra, campo: proposta}
        texto = json.dumps(corpo, ensure_ascii=False, separators=(",", ":"))
        if atual and (len(proposta) > LIMITE_LOTE or len(texto.encode("utf-8")) > 48_000):
            lotes.append({**extra, campo: atual})
            atual = [item]
        else:
            atual = proposta
    if atual:
        lotes.append({**extra, campo: atual})
    return lotes


def importacao_pendente(db: Session, chave: str) -> bool:
    from backend.retaguarda import RetaguardaComando
    return db.query(RetaguardaComando.id).filter_by(chave_loja=chave, situacao="pendente").filter(
        RetaguardaComando.tipo.in_(("produtos.importar", "produtos.desfazer"))).first() is not None


def _ultima_id(db: Session, chave: str) -> int | None:
    linha = (db.query(PainelImportacao).filter_by(chave_loja=chave)
             .order_by(PainelImportacao.id.desc()).first())
    return linha.id if linha else None


def historico_publico(db: Session, chave: str) -> list[dict]:
    linhas = (db.query(PainelImportacao).filter_by(chave_loja=chave)
              .order_by(PainelImportacao.id.desc()).limit(30).all())
    pendente = importacao_pendente(db, chave)
    saida = []
    for i, linha in enumerate(linhas):
        saida.append({
            "id": linha.id, "criado_em": linha.criado_em, "autor": linha.autor,
            "modo_quantidade": linha.modo_quantidade, "criados": linha.criar, "atualizados": linha.atualizar,
            "erros": linha.recusar, "resumo": linha.resumo, "desfeito_em": linha.desfeito_em,
            "pode_desfazer": i == 0 and not linha.desfeito_em and not pendente and bool(linha.snapshot not in ("", "[]")),
        })
    return saida


def desfazer_ultima(db: Session, chave: str, autor: str) -> dict:
    ultima = (db.query(PainelImportacao).filter_by(chave_loja=chave)
              .order_by(PainelImportacao.id.desc()).first())
    if ultima is None:
        raise HTTPException(status_code=404, detail="Nenhuma importação para desfazer.")
    if ultima.desfeito_em:
        raise HTTPException(status_code=409, detail="A última importação já foi desfeita.")
    if importacao_pendente(db, chave):
        raise HTTPException(status_code=409, detail=(
            "Ainda há uma importação esperando o caixa. Aguarde a sincronização antes de desfazer."))
    try:
        itens = json.loads(ultima.snapshot or "[]")
    except ValueError:
        itens = []
    if not isinstance(itens, list) or not itens:
        raise HTTPException(status_code=409, detail="Esta importação não tem o que desfazer.")
    lotes = fatiar("itens", itens, {})
    if pendentes(db, chave) + len(lotes) > LIMITE_PENDENTES:
        raise HTTPException(status_code=409, detail=(
            "Há alterações demais esperando o caixa. Aguarde a loja aplicar as que já estão na fila."))
    ids = []
    total = len(lotes)
    for i, dados in enumerate(lotes, start=1):
        resumo = f"Desfazer importação #{ultima.id} ({i}/{total})"
        comando = criar(db, chave, {"tipo": "produtos.desfazer", "dados": dados, "resumo": resumo}, autor)
        ids.append(comando.id)
    ultima.desfeito_em = _agora()
    db.commit()
    return {"importacao_id": ultima.id, "comandos": ids,
            "mensagem": "Desfazer enviado ao caixa. Ele aplica na próxima sincronização. "
                        "Produto novo que já foi vendido permanece no cadastro."}


def filtrar(produtos: list[dict], q: str) -> list[dict]:
    termo = _norm(q)
    digitos = re.sub(r"\D", "", q or "")
    if not termo and not digitos:
        return produtos
    saida = []
    for p in produtos:
        barras = re.sub(r"\D", "", str(p.get("cbarra") or ""))
        codigo = re.sub(r"\D", "", str(p.get("codigo") or ""))
        if termo and termo in _norm(p.get("nome")):
            saida.append(p)
        elif digitos and (digitos in barras or digitos in codigo):
            saida.append(p)
        elif termo and termo in _norm(str(p.get("codigo") or "")):
            saida.append(p)
    return saida


def produto_publico(p: dict) -> dict:
    return {
        "id": p.get("id"),
        "codigo": codigo_curto(p.get("codigo")),
        "nome": p.get("nome") or "",
        "codigo_barras": re.sub(r"\D", "", str(p.get("cbarra") or "")),
        "preco_cent": int(p.get("preco_cent") or 0),
        "custo_cent": int(p.get("custo_medio_cent") or 0),
        "quantidade": p.get("qt_atual") if p.get("controla_estoque") else None,
        "unidade": p.get("unidade") or "",
        "grupo": p.get("grupo") or "",
        "ativo": bool(p.get("ativo", True)),
    }


def _linha_csv(p: dict) -> list:
    qtd = ""
    if p.get("controla_estoque"):
        qtd = fmt.fmt_qtd(p.get("qt_atual") or 0, 4).rstrip("0").rstrip(",") or "0"
    custo = int(p.get("custo_medio_cent") or 0)
    return [codigo_curto(p.get("codigo")), p.get("nome") or "", fmt.fmt_num(int(p.get("preco_cent") or 0)),
            fmt.fmt_num(custo) if custo else "", p.get("grupo") or "", p.get("unidade") or "UN", qtd,
            re.sub(r"\D", "", str(p.get("cbarra") or ""))]


def csv_produtos(produtos: list[dict]) -> str:
    buf = io.StringIO()
    linhas = [[TITULOS[c] for c in COLUNAS_CSV]] + [_linha_csv(p) for p in produtos]
    csv.writer(buf, delimiter=";", lineterminator="\r\n").writerows(
        [[texto_planilha(celula) for celula in linha] for linha in linhas])
    return buf.getvalue()


def xlsx_produtos(produtos: list[dict]) -> bytes:
    return escrever_xlsx([[TITULOS[c] for c in COLUNAS_CSV]] + [_linha_csv(p) for p in produtos])


def nome_arquivo(chave: str, ext: str) -> str:
    seguro = re.sub(r"[^A-Za-z0-9._-]+", "-", chave)[:40] or "loja"
    return f"produtos-{seguro}.{ext}"


def novo_token(db: Session, chave: str, nome) -> dict:
    nome = re.sub(r"\s+", " ", str(nome or "assistente")).strip()[:40]
    if not NOME_TOKEN.fullmatch(nome):
        raise HTTPException(status_code=422, detail=(
            "Dê um nome curto ao token, só com letras, números, espaço, ponto ou traço."))
    ativos = db.query(PainelTokenApi).filter_by(chave_loja=chave, revogado_em=None).count()
    if ativos >= LIMITE_TOKENS:
        raise HTTPException(status_code=422, detail=f"Esta loja já tem {LIMITE_TOKENS} tokens. Revogue um para criar outro.")
    segredo = "wpdv_" + secrets.token_urlsafe(32)
    linha = PainelTokenApi(chave_loja=chave, nome=nome, token_hash=_painel()._hash(segredo), criado_em=_agora())
    db.add(linha)
    db.commit()
    db.refresh(linha)
    return {"id": linha.id, "nome": linha.nome, "criado_em": linha.criado_em, "token": segredo,
            "aviso": "Copie o token agora. Ele não será mostrado de novo."}


def tokens_publicos(db: Session, chave: str) -> list[dict]:
    linhas = (db.query(PainelTokenApi).filter_by(chave_loja=chave, revogado_em=None)
              .order_by(PainelTokenApi.id.desc()).all())
    return [{"id": l.id, "nome": l.nome, "criado_em": l.criado_em, "ultimo_uso": l.ultimo_uso} for l in linhas]
