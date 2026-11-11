"""Rede de lojas de um mesmo dono.

Uma rede tem um login só no painel e, se o fornecedor cadastrar, uma mensalidade só.
Cada loja continua com o próprio caixa, estoque e vendas. Loja sem grupo_id não muda.
"""
from __future__ import annotations

import re

from sqlalchemy import Boolean, Column, Integer, String, inspect, text
from sqlalchemy.orm import Session

from backend.database import Base, engine

CHAVE = re.compile(r"[A-Za-z0-9._-]{1,64}")


class ErroGrupo(Exception):
    pass


class Grupo(Base):
    __tablename__ = "grupos"
    id = Column(Integer, primary_key=True)
    chave = Column(String, unique=True, index=True, nullable=False)
    nome = Column(String, nullable=False)
    login = Column(String, unique=True, index=True, nullable=False)
    senha_hash = Column(String, nullable=False)
    deve_trocar_senha = Column(Boolean, nullable=False, default=True)
    criado_em = Column(String, nullable=False)


def garantir_esquema(bind=None) -> None:
    alvo = bind or engine
    Grupo.__table__.create(bind=alvo, checkfirst=True)
    with alvo.begin() as con:
        inspetor = inspect(con)
        if not inspetor.has_table("grupos"):
            return
        existentes = {c["name"] for c in inspetor.get_columns("grupos")}
        if "deve_trocar_senha" not in existentes:
            con.execute(text("ALTER TABLE grupos ADD COLUMN deve_trocar_senha BOOLEAN NOT NULL DEFAULT 1"))


def _chave(valor: str, rotulo: str) -> str:
    chave = (valor or "").strip().upper()
    if not CHAVE.fullmatch(chave):
        raise ErroGrupo(f"{rotulo} usa letras, números, ponto, _ ou -, com até 64 caracteres.")
    return chave


def _nome(valor: str) -> str:
    nome = " ".join((valor or "").split())
    if not nome or len(nome) > 80:
        raise ErroGrupo("Informe o nome da rede, com até 80 caracteres.")
    return nome


def criar(db: Session, nome: str, chave: str, senha: str, *, temporaria: bool = True) -> tuple[Grupo, str | None]:
    from backend import painel
    from backend.main import Loja
    nome = _nome(nome)
    chave = _chave(chave, "A chave da rede")
    if db.query(Loja).filter_by(chave_loja=chave).first() is not None:
        raise ErroGrupo("A chave da rede não pode ser igual à identificação de uma loja.")
    if db.query(Grupo).filter_by(chave=chave).first() is not None:
        raise ErroGrupo("Já existe uma rede com essa chave.")
    gerada = None
    if not (senha or "").strip():
        senha = painel.gerar_senha()
        gerada = senha
    try:
        senha = painel.validar_senha(senha)
    except ValueError as erro:
        raise ErroGrupo(str(erro)) from None
    grupo = Grupo(chave=chave, nome=nome, login=chave, senha_hash=painel.gerar_hash_senha(senha),
                  deve_trocar_senha=bool(temporaria), criado_em=painel._agora())
    db.add(grupo)
    db.commit()
    db.refresh(grupo)
    return grupo, gerada


def definir_senha(db: Session, grupo: Grupo, senha: str, *, temporaria: bool = True) -> str | None:
    from backend import painel
    gerada = None
    if not (senha or "").strip():
        senha = painel.gerar_senha()
        gerada = senha
    try:
        senha = painel.validar_senha(senha)
    except ValueError as erro:
        raise ErroGrupo(str(erro)) from None
    grupo.senha_hash = painel.gerar_hash_senha(senha)
    grupo.deve_trocar_senha = bool(temporaria)
    db.query(painel.PainelSessao).filter_by(grupo_id=grupo.id).delete(synchronize_session=False)
    db.commit()
    return gerada


def trocar_senha(db: Session, grupo: Grupo, atual: str, nova: str) -> None:
    from backend import painel
    if not painel.conferir_senha(atual, grupo.senha_hash):
        raise ErroGrupo("A senha atual não confere.")
    try:
        nova = painel.validar_senha(nova)
    except ValueError as erro:
        raise ErroGrupo(str(erro)) from None
    if painel.conferir_senha(nova, grupo.senha_hash):
        raise ErroGrupo("Escolha uma senha diferente da temporária.")
    grupo.senha_hash = painel.gerar_hash_senha(nova)
    grupo.deve_trocar_senha = False
    db.commit()


def por_identificador(db: Session, valor: str) -> Grupo | None:
    texto = (valor or "").strip()
    if not texto:
        return None
    if texto.isdigit():
        achado = db.get(Grupo, int(texto))
        if achado is not None:
            return achado
    chave = texto.upper()
    return db.query(Grupo).filter((Grupo.chave == chave) | (Grupo.login == chave)).first()


def obter(db: Session, chave: str) -> Grupo:
    grupo = por_identificador(db, chave)
    if grupo is None:
        raise ErroGrupo("Rede não encontrada.")
    return grupo


def lojas(db: Session, grupo_id: int):
    from backend.main import Loja
    return db.query(Loja).filter_by(grupo_id=grupo_id).order_by(Loja.chave_loja).all()


def adicionar_loja(db: Session, grupo: Grupo, chave_loja: str):
    from backend.main import Loja
    loja = db.query(Loja).filter_by(chave_loja=(chave_loja or "").strip()).first()
    if loja is None:
        raise ErroGrupo("Loja não encontrada.")
    if loja.grupo_id and loja.grupo_id != grupo.id:
        raise ErroGrupo("Essa loja já está em outra rede.")
    loja.grupo_id = grupo.id
    db.commit()
    return loja


def remover_loja(db: Session, grupo: Grupo, chave_loja: str):
    from backend.main import Loja
    loja = db.query(Loja).filter_by(chave_loja=(chave_loja or "").strip(), grupo_id=grupo.id).first()
    if loja is None:
        raise ErroGrupo("Essa loja não está nesta rede.")
    loja.grupo_id = None
    db.commit()
    return loja


def resumo(db: Session, grupo: Grupo) -> dict:
    return {
        "id": grupo.id,
        "chave": grupo.chave,
        "nome": grupo.nome,
        "login": grupo.login,
        "deve_trocar_senha": bool(grupo.deve_trocar_senha),
        "criado_em": grupo.criado_em,
        "link": f"/painel/?grupo={grupo.chave}",
        "lojas": [{"chave": loja.chave_loja, "nome": loja.nome, "ativa": bool(loja.ativa),
                   "licenca_ate": loja.licenca_ate} for loja in lojas(db, grupo.id)],
    }


def listar(db: Session) -> list[dict]:
    return [resumo(db, grupo) for grupo in db.query(Grupo).order_by(Grupo.chave)]


def definir_assinatura(db: Session, grupo: Grupo, dados: dict) -> str:
    """Uma mensalidade da rede. Loja que está na rede não gera a cobrança dela enquanto permanecer no grupo."""
    from backend import cobranca_mercadopago as cobranca
    from backend.main import Loja
    if not isinstance(dados, dict):
        raise ErroGrupo("Corpo inválido.")
    pedido = dict(dados)
    pedido["chave_loja"] = grupo.chave
    try:
        valor = cobranca._valor_plano(pedido.get("valor_cent"))
        dia = pedido.get("dia_vencimento")
        if isinstance(dia, bool) or not isinstance(dia, int) or not 1 <= dia <= 31:
            raise cobranca.ErroCobranca("O dia de vencimento deve ser um inteiro de 1 a 31.")
        antecedencia = pedido.get("antecedencia_dias", cobranca.ANTECEDENCIA_PADRAO)
        if isinstance(antecedencia, bool) or not isinstance(antecedencia, int) or not 1 <= antecedencia <= 20:
            raise cobranca.ErroCobranca("A antecedência deve ser de 1 a 20 dias.")
        email = cobranca._email(pedido.get("email"))
        telefone = cobranca.normalizar_whatsapp(pedido.get("whatsapp"))
        nome = cobranca._texto_curto(pedido.get("nome"), "O nome do pagador", 5, 80)
        _tipo, documento = cobranca.validar_documento(pedido.get("documento"))
        cep = cobranca._digitos(pedido.get("cep"))
        if len(cep) != 8:
            raise cobranca.ErroCobranca("CEP deve ter 8 dígitos.")
        logradouro = cobranca._texto_curto(pedido.get("logradouro"), "O logradouro", 2, 80)
        numero = cobranca._texto_curto(pedido.get("numero"), "O número", 1, 10)
        bairro = cobranca._texto_curto(pedido.get("bairro"), "O bairro", 2, 50)
        cidade = cobranca._texto_curto(pedido.get("cidade"), "A cidade", 2, 50)
        uf = str(pedido.get("uf") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", uf):
            raise cobranca.ErroCobranca("UF deve ter 2 letras.")
    except cobranca.ErroCobranca as erro:
        raise ErroGrupo(str(erro)) from None
    if db.query(Loja).filter_by(chave_loja=grupo.chave).first() is not None:
        raise ErroGrupo("A chave da rede não pode ser igual à identificação de uma loja.")
    plano = db.query(cobranca.Plano).filter_by(chave_loja=grupo.chave).first()
    situacao = "atualizada"
    if plano is None:
        import uuid
        plano = cobranca.Plano(id=uuid.uuid4().hex, chave_loja=grupo.chave, valor_cent=valor,
                               email_pagador=email, validade_anterior=None, criado_em=cobranca.agora())
        db.add(plano)
        situacao = "criada"
    plano.grupo_id = grupo.id
    plano.valor_cent = valor
    plano.email_pagador = email
    plano.email_gerente = email
    plano.whatsapp = telefone
    plano.dia_vencimento = dia
    plano.antecedencia_dias = antecedencia
    plano.pagador_nome = nome
    plano.pagador_documento = documento
    plano.cep = cep
    plano.logradouro = logradouro
    plano.numero = numero
    plano.bairro = bairro
    plano.cidade = cidade
    plano.uf = uf
    for loja in lojas(db, grupo.id):
        proprio = db.query(cobranca.Plano).filter_by(chave_loja=loja.chave_loja).first()
        if proprio is not None and proprio.id != plano.id:
            proprio.dia_vencimento = None
    db.commit()
    return situacao


def consolidado(db: Session, grupo: Grupo, inicio, fim) -> dict:
    """Soma o lucro das lojas da rede. Não devolve item cru."""
    from backend import painel
    chaves = [loja.chave_loja for loja in lojas(db, grupo.id) if loja.ativa]
    vendas = []
    retratos = []
    por_loja = []
    if chaves:
        linhas = (db.query(painel.PainelVenda.chave_loja, painel.PainelVenda.status,
                           painel.PainelVenda.total_cent, painel.PainelVenda.dados)
                  .filter(painel.PainelVenda.chave_loja.in_(chaves),
                          painel.PainelVenda.dia >= inicio.isoformat(),
                          painel.PainelVenda.dia <= fim.isoformat()))
        por_chave: dict[str, list] = {chave: [] for chave in chaves}
        for chave, status, total, dados in linhas:
            import json
            try:
                venda = json.loads(dados) if isinstance(dados, str) else {}
            except (TypeError, ValueError):
                venda = {}
            if not isinstance(venda, dict):
                venda = {}
            venda["status"] = status
            venda["total_cent"] = total
            vendas.append(venda)
            por_chave.setdefault(chave, []).append(venda)
        for loja in lojas(db, grupo.id):
            if not loja.ativa:
                continue
            bloco = painel.montar_lucro(por_chave.get(loja.chave_loja, []), [])
            por_loja.append({
                "chave": loja.chave_loja, "nome": loja.nome,
                "faturamento_cent": bloco["faturamento_cent"],
                "custo_cent": bloco["custo_cent"], "lucro_cent": bloco["lucro_cent"],
                "margem": bloco["margem"],
            })
            retratos.extend(dados for _, dados in painel._ler_caixas(db, loja.chave_loja))
    corpo = painel.montar_lucro(vendas, retratos)
    por_loja.sort(key=lambda item: (-(item["lucro_cent"] or 0), item["nome"]))
    corpo.update({
        "de": inicio.isoformat(), "ate": fim.isoformat(),
        "grupo": {"id": grupo.id, "chave": grupo.chave, "nome": grupo.nome},
        "lojas": [{"chave": loja.chave_loja, "nome": loja.nome} for loja in lojas(db, grupo.id) if loja.ativa],
        "por_loja": por_loja,
    })
    return corpo
