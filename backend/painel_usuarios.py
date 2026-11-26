"""Login do dono por e-mail.

O fornecedor cadastra o e-mail do dono na central (de uma loja ou de uma rede inteira) e manda o convite. O dono abre
o link, cria a própria senha (o fornecedor nunca a conhece) e passa a entrar no painel com e-mail + senha. Num aparelho
novo chega um código de 6 dígitos no e-mail; confirmado, o aparelho fica lembrado por 30 dias. "Esqueci a senha"
manda um link que vale 30 minutos. O login antigo (código da loja + senha) continua funcionando.

Segurança: só hashes ficam no banco (senha em PBKDF2, links e códigos em SHA-256), cada link e código vale uma vez,
códigos aceitam 5 tentativas, e "esqueci a senha" responde igual exista o e-mail ou não.
"""
from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.orm import Session

from backend.database import Base, get_db
from backend import painel

EMAIL_RE = re.compile(r"^[^@\s,;<>]{1,64}@[^@\s,;<>]{1,190}\.[A-Za-z]{2,24}$")
COOKIE_APARELHO = "willpdv_aparelho"
DIAS_APARELHO = 30
DIAS_CONVITE = 7
MINUTOS_REDEFINIR = 30
MINUTOS_CODIGO = 10
TENTATIVAS_CODIGO = 5

tentativas_email = painel._Tentativas()


class PainelUsuario(Base):
    """Uma pessoa que entra no painel por e-mail. Vale para uma loja (`chave_loja`) ou para a rede (`grupo_id`)."""
    __tablename__ = "painel_usuarios"
    id = Column(Integer, primary_key=True)
    email = Column(String(254), unique=True, index=True, nullable=False)
    nome = Column(String(80), nullable=False, default="")
    senha_hash = Column(String, nullable=True)              # vazio até o dono aceitar o convite
    chave_loja = Column(String, index=True, nullable=True)
    grupo_id = Column(Integer, index=True, nullable=True)
    ativo = Column(Boolean, nullable=False, default=True)
    criado_em = Column(String(19), nullable=False)
    atualizado_em = Column(String(19), nullable=False)
    ultimo_login = Column(String(19), nullable=True)


class PainelUsuarioToken(Base):
    """Link de convite, link de nova senha e desafio do código. Só o hash do link fica guardado."""
    __tablename__ = "painel_usuario_tokens"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, index=True, nullable=False)
    tipo = Column(String(10), nullable=False)               # convite | senha | codigo
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    codigo_hash = Column(String(64), nullable=True)
    expira_em = Column(String(19), nullable=False)
    usado_em = Column(String(19), nullable=True)
    tentativas = Column(Integer, nullable=False, default=0)


class PainelAparelho(Base):
    """Aparelho confirmado pelo código: dispensa o código por 30 dias."""
    __tablename__ = "painel_aparelhos"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, index=True, nullable=False)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    criado_em = Column(String(19), nullable=False)
    expira_em = Column(String(19), nullable=False)


class ErroUsuario(ValueError):
    pass


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _daqui(**delta) -> str:
    return (datetime.now() + timedelta(**delta)).strftime("%Y-%m-%d %H:%M:%S")


def endereco_publico() -> str:
    return (os.environ.get("PAINEL_URL_PUBLICA") or os.environ.get("PUBLIC_BASE_URL")
            or "https://willpdv.com.br").rstrip("/")


def normalizar_email(texto: str) -> str:
    email = (texto or "").strip().lower()
    if not EMAIL_RE.fullmatch(email):
        raise ErroUsuario("E-mail inválido.")
    return email


def _enviar(destino: str, assunto: str, corpo: str, enviar=None) -> None:
    from backend.cobranca_mercadopago import enviar_email
    (enviar or enviar_email)(destino, assunto, corpo)


def _novo_token(db: Session, usuario: PainelUsuario, tipo: str, expira: str, codigo: str | None = None) -> str:
    # Um pedido novo do mesmo tipo derruba os anteriores (o link velho para de valer).
    db.query(PainelUsuarioToken).filter_by(usuario_id=usuario.id, tipo=tipo, usado_em=None).update(
        {"usado_em": _agora()}, synchronize_session=False)
    token = secrets.token_urlsafe(32)
    db.add(PainelUsuarioToken(usuario_id=usuario.id, tipo=tipo, token_hash=painel._hash(token),
                              codigo_hash=painel._hash(codigo) if codigo else None, expira_em=expira, tentativas=0))
    db.commit()
    return token


def _token_valido(db: Session, token: str, tipos: tuple[str, ...]) -> PainelUsuarioToken | None:
    if not token or len(token) > 100:
        return None
    linha = db.query(PainelUsuarioToken).filter_by(token_hash=painel._hash(token)).first()
    if linha is None or linha.tipo not in tipos or linha.usado_em or linha.expira_em <= _agora():
        return None
    return linha


def _destino(db: Session, usuario: PainelUsuario) -> str:
    """Nome da loja ou da rede, para o texto dos e-mails."""
    if usuario.grupo_id:
        from backend.grupos import Grupo
        grupo = db.get(Grupo, usuario.grupo_id)
        return f"a rede {grupo.nome}" if grupo is not None else "a sua rede"
    from backend.main import Loja
    loja = db.query(Loja).filter(Loja.chave_loja == usuario.chave_loja).first()
    return f"a loja {(loja.nome if loja is not None else '') or usuario.chave_loja}"


# ---------------------------------------------------------------- central: cadastro e convite
def cadastrar(db: Session, email: str, nome: str = "", chave_loja: str | None = None,
              grupo_id: int | None = None) -> PainelUsuario:
    """Cria o acesso por e-mail (ou atualiza o vínculo de quem já existe). Uma loja ou uma rede, nunca as duas."""
    email = normalizar_email(email)
    if bool(chave_loja) == bool(grupo_id):
        raise ErroUsuario("Informe a loja ou a rede do acesso.")
    usuario = db.query(PainelUsuario).filter_by(email=email).first()
    agora = _agora()
    if usuario is None:
        usuario = PainelUsuario(email=email, criado_em=agora)
        db.add(usuario)
    usuario.nome = (nome or "").strip()[:80] or usuario.nome or ""
    usuario.chave_loja, usuario.grupo_id = (chave_loja or None), (grupo_id or None)
    usuario.ativo = True
    usuario.atualizado_em = agora
    db.commit()
    return usuario


def enviar_convite(db: Session, usuario: PainelUsuario, enviar=None) -> None:
    token = _novo_token(db, usuario, "convite", _daqui(days=DIAS_CONVITE))
    link = f"{endereco_publico()}/painel/?senha={token}"
    _enviar(usuario.email, "Seu acesso ao painel WillPDV", "\n".join([
        f"Olá{(' ' + usuario.nome) if usuario.nome else ''},",
        "",
        f"Você recebeu acesso ao painel do dono de {_destino(db, usuario)}.",
        "Para começar, crie a sua senha neste link (vale por 7 dias):",
        "",
        link,
        "",
        "Depois é só entrar em willpdv.com.br/painel com este e-mail e a sua senha.",
        "Se você não esperava este e-mail, ignore.",
        "",
        "WillPDV · WB Sistemas",
    ]), enviar)


def listar(db: Session, chave_loja: str | None = None, grupo_id: int | None = None) -> list[dict]:
    consulta = db.query(PainelUsuario)
    consulta = consulta.filter_by(grupo_id=grupo_id) if grupo_id else consulta.filter_by(chave_loja=chave_loja)
    return [{"id": u.id, "email": u.email, "nome": u.nome, "ativo": bool(u.ativo),
             "senha_criada": bool(u.senha_hash), "ultimo_login": u.ultimo_login}
            for u in consulta.order_by(PainelUsuario.email).all()]


def remover(db: Session, usuario: PainelUsuario) -> None:
    db.query(PainelAparelho).filter_by(usuario_id=usuario.id).delete(synchronize_session=False)
    db.query(PainelUsuarioToken).filter_by(usuario_id=usuario.id).delete(synchronize_session=False)
    db.delete(usuario)
    db.commit()


# ---------------------------------------------------------------- dono: senha
def pedir_nova_senha(db: Session, email: str, enviar=None) -> None:
    """'Esqueci a senha'. Não diz se o e-mail existe: quem tenta adivinhar não aprende nada."""
    try:
        email = normalizar_email(email)
    except ErroUsuario:
        return
    usuario = db.query(PainelUsuario).filter_by(email=email, ativo=True).first()
    if usuario is None:
        return
    token = _novo_token(db, usuario, "senha", _daqui(minutes=MINUTOS_REDEFINIR))
    _enviar(usuario.email, "Criar nova senha do painel WillPDV", "\n".join([
        "Pediram uma nova senha para o seu acesso ao painel WillPDV.",
        "Para criar a nova senha, abra este link (vale por 30 minutos):",
        "",
        f"{endereco_publico()}/painel/?senha={token}",
        "",
        "Se não foi você, ignore: a senha atual continua valendo.",
        "",
        "WillPDV · WB Sistemas",
    ]), enviar)


def ver_link(db: Session, token: str) -> dict:
    linha = _token_valido(db, token, ("convite", "senha"))
    if linha is None:
        raise ErroUsuario("Este link venceu ou já foi usado. Peça outro em \"Esqueci a senha\".")
    usuario = db.get(PainelUsuario, linha.usuario_id)
    return {"email": usuario.email, "nome": usuario.nome, "tipo": linha.tipo}


def definir_senha(db: Session, token: str, senha: str) -> PainelUsuario:
    linha = _token_valido(db, token, ("convite", "senha"))
    if linha is None:
        raise ErroUsuario("Este link venceu ou já foi usado. Peça outro em \"Esqueci a senha\".")
    try:
        senha = painel.validar_senha(senha)
    except ValueError as erro:
        raise ErroUsuario(str(erro)) from None
    usuario = db.get(PainelUsuario, linha.usuario_id)
    usuario.senha_hash = painel.gerar_hash_senha(senha)
    usuario.atualizado_em = _agora()
    linha.usado_em = _agora()
    db.query(PainelAparelho).filter_by(usuario_id=usuario.id).delete(synchronize_session=False)  # senha nova: reconfirma
    db.commit()
    return usuario


# ---------------------------------------------------------------- dono: entrar
def conferir(db: Session, email: str, senha: str) -> PainelUsuario | None:
    try:
        email = normalizar_email(email)
    except ErroUsuario:
        return None
    usuario = db.query(PainelUsuario).filter_by(email=email, ativo=True).first()
    if usuario is None or not usuario.senha_hash or not painel.conferir_senha(senha, usuario.senha_hash):
        return None
    return usuario


def aparelho_lembrado(db: Session, usuario: PainelUsuario, token: str) -> bool:
    if not token or len(token) > 100:
        return False
    linha = db.query(PainelAparelho).filter_by(token_hash=painel._hash(token), usuario_id=usuario.id).first()
    return linha is not None and linha.expira_em > _agora()


def mandar_codigo(db: Session, usuario: PainelUsuario, enviar=None) -> str:
    codigo = f"{secrets.randbelow(1_000_000):06d}"
    desafio = _novo_token(db, usuario, "codigo", _daqui(minutes=MINUTOS_CODIGO), codigo=codigo)
    _enviar(usuario.email, f"{codigo} é o seu código do painel WillPDV", "\n".join([
        f"Código para entrar no painel: {codigo}",
        "",
        "Ele vale por 10 minutos. Depois de confirmar, este aparelho fica lembrado por 30 dias.",
        "Se não foi você tentando entrar, troque a senha em \"Esqueci a senha\".",
        "",
        "WillPDV · WB Sistemas",
    ]), enviar)
    return desafio


def conferir_codigo(db: Session, desafio: str, codigo: str) -> PainelUsuario:
    linha = _token_valido(db, desafio, ("codigo",))
    if linha is None:
        raise ErroUsuario("O código venceu. Entre de novo para receber outro.")
    if linha.tentativas >= TENTATIVAS_CODIGO:
        raise ErroUsuario("Muitas tentativas. Entre de novo para receber outro código.")
    linha.tentativas += 1
    codigo = re.sub(r"\D", "", codigo or "")
    if len(codigo) != 6 or painel._hash(codigo) != linha.codigo_hash:
        db.commit()
        restantes = TENTATIVAS_CODIGO - linha.tentativas
        raise ErroUsuario("Código errado." + (f" Restam {restantes} tentativa(s)." if restantes else
                                              " Entre de novo para receber outro código."))
    linha.usado_em = _agora()
    db.commit()
    return db.get(PainelUsuario, linha.usuario_id)


def lembrar_aparelho(db: Session, usuario: PainelUsuario) -> str:
    token = secrets.token_urlsafe(32)
    db.query(PainelAparelho).filter(PainelAparelho.usuario_id == usuario.id,
                                    PainelAparelho.expira_em <= _agora()).delete(synchronize_session=False)
    db.add(PainelAparelho(usuario_id=usuario.id, token_hash=painel._hash(token), criado_em=_agora(),
                          expira_em=_daqui(days=DIAS_APARELHO)))
    db.commit()
    return token


# ---------------------------------------------------------------- rotas
def instalar(app: FastAPI, Loja) -> APIRouter:
    router = APIRouter()

    def _abrir(request: Request, response: Response, db: Session, usuario: PainelUsuario) -> dict:
        """Sessão do painel do jeito de sempre: a da rede (com o seletor de lojas) ou a da loja."""
        from backend.memoria_nuvem import memoria
        usuario.ultimo_login = _agora()
        db.commit()
        if usuario.grupo_id:
            from backend.grupos import Grupo, lojas
            grupo = db.get(Grupo, usuario.grupo_id)
            if grupo is None:
                raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")
            token, expira = painel.abrir_sessao(db, grupo.chave, grupo.id)
            memoria.lembrar_sessao(token, grupo.chave)
            corpo = {"grupo": {"id": grupo.id, "chave": grupo.chave, "nome": grupo.nome,
                               "lojas": [{"chave": l.chave_loja, "nome": l.nome or l.chave_loja, "ativa": bool(l.ativa)}
                                         for l in lojas(db, grupo.id)]},
                     "deve_trocar_senha": False, "expira_em": expira}
            return painel.entregar_sessao(response, request, corpo, token, rede=True)
        loja = db.query(Loja).filter(Loja.chave_loja == usuario.chave_loja).first()
        if loja is None or not loja.ativa:
            raise HTTPException(status_code=401, detail="Esta loja não está ativa. Fale com o suporte.")
        token, expira = painel.abrir_sessao(db, loja.chave_loja)
        memoria.lembrar_sessao(token, loja.chave_loja)
        return painel.entregar_sessao(response, request,
                                      {"loja": {"chave": loja.chave_loja, "nome": loja.nome}, "expira_em": expira}, token)

    def _cookie_aparelho(request: Request, response: Response, token: str) -> None:
        response.set_cookie(COOKIE_APARELHO, token, httponly=True, secure=painel._https(request), samesite="strict",
                            max_age=DIAS_APARELHO * 86400, path="/v1/painel")

    @router.post("/v1/painel/login-email")
    def entrar(request: Request, response: Response, dados: dict = Body(...), db: Session = Depends(get_db)):
        email = str((dados or {}).get("email") or "").strip().lower()[:254]
        senha = str((dados or {}).get("senha") or "")[:128]
        if not email or not senha:
            raise HTTPException(status_code=422, detail="Informe o e-mail e a senha.")
        if tentativas_email.bloqueada(email):
            raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde alguns minutos.")
        usuario = conferir(db, email, senha)
        if usuario is None:
            tentativas_email.falhou(email)
            raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")
        tentativas_email.acertou(email)
        if aparelho_lembrado(db, usuario, request.cookies.get(COOKIE_APARELHO, "")):
            return _abrir(request, response, db, usuario)
        try:
            desafio = mandar_codigo(db, usuario)
        except Exception as erro:                          # noqa: BLE001 - sem e-mail não dá para confirmar
            raise HTTPException(status_code=502, detail=f"Não consegui mandar o código por e-mail: {str(erro)[:120]}") \
                from None
        email_mascarado = re.sub(r"(^.).*(@.*$)", r"\1***\2", usuario.email)
        return {"precisa_codigo": True, "desafio": desafio, "email": email_mascarado}

    @router.post("/v1/painel/login-email/codigo")
    def confirmar(request: Request, response: Response, dados: dict = Body(...), db: Session = Depends(get_db)):
        desafio = str((dados or {}).get("desafio") or "")
        if tentativas_email.bloqueada("codigo:" + desafio[:20]):
            raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde alguns minutos.")
        try:
            usuario = conferir_codigo(db, desafio, str((dados or {}).get("codigo") or ""))
        except ErroUsuario as erro:
            tentativas_email.falhou("codigo:" + desafio[:20])
            raise HTTPException(status_code=401, detail=str(erro)) from None
        if usuario is None or not usuario.ativo:
            raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")
        _cookie_aparelho(request, response, lembrar_aparelho(db, usuario))
        return _abrir(request, response, db, usuario)

    @router.post("/v1/painel/senha/esqueci")
    def esqueci(dados: dict = Body(...), db: Session = Depends(get_db)):
        email = str((dados or {}).get("email") or "").strip().lower()[:254]
        if tentativas_email.bloqueada("esqueci:" + email):
            raise HTTPException(status_code=429, detail="Muitos pedidos. Aguarde alguns minutos.")
        tentativas_email.falhou("esqueci:" + email)          # conta cada pedido: no máximo alguns por janela
        try:
            pedir_nova_senha(db, email)
        except Exception:                                    # noqa: BLE001 - a resposta é sempre a mesma
            pass
        return {"mensagem": "Se este e-mail tiver acesso, chega em instantes um link para criar a nova senha."}

    @router.get("/v1/painel/senha/link")
    def link(token: str, db: Session = Depends(get_db)):
        try:
            return ver_link(db, token)
        except ErroUsuario as erro:
            raise HTTPException(status_code=410, detail=str(erro)) from None

    @router.post("/v1/painel/senha/definir")
    def definir(request: Request, response: Response, dados: dict = Body(...), db: Session = Depends(get_db)):
        try:
            usuario = definir_senha(db, str((dados or {}).get("token") or ""), str((dados or {}).get("senha") or ""))
        except ErroUsuario as erro:
            raise HTTPException(status_code=422, detail=str(erro)) from None
        # Quem abriu o link no e-mail já provou que é dono do e-mail: este aparelho fica lembrado e entra direto.
        _cookie_aparelho(request, response, lembrar_aparelho(db, usuario))
        return _abrir(request, response, db, usuario)

    app.include_router(router)
    return router


def instalar_fornecedor(app: FastAPI, sessao, obter, auditar) -> APIRouter:
    """Central: acessos por e-mail de uma loja (ou da rede dela) e convites."""
    router = APIRouter()

    def _alvo(db: Session, chave: str, rede: bool) -> tuple[str | None, int | None]:
        loja = obter(db, chave)
        if rede:
            if not loja.grupo_id:
                raise HTTPException(status_code=422, detail="Esta loja não está em uma rede.")
            return None, loja.grupo_id
        return loja.chave_loja, None

    @router.get("/v1/fornecedor/lojas/{chave}/acessos-email")
    def ver(chave: str, _=Depends(sessao), db: Session = Depends(get_db)):
        loja = obter(db, chave)
        return {"loja": listar(db, chave_loja=loja.chave_loja),
                "rede": listar(db, grupo_id=loja.grupo_id) if loja.grupo_id else None,
                "tem_rede": bool(loja.grupo_id)}

    @router.post("/v1/fornecedor/lojas/{chave}/acessos-email")
    def convidar(chave: str, dados: dict = Body(...), _=Depends(sessao), db: Session = Depends(get_db)):
        loja_chave, grupo_id = _alvo(db, chave, bool((dados or {}).get("rede")))
        try:
            usuario = cadastrar(db, str((dados or {}).get("email") or ""), str((dados or {}).get("nome") or ""),
                                chave_loja=loja_chave, grupo_id=grupo_id)
        except ErroUsuario as erro:
            raise HTTPException(status_code=422, detail=str(erro)) from None
        auditar(db, "acesso_email", chave, f"{usuario.email} {'rede' if grupo_id else 'loja'}")
        try:
            enviar_convite(db, usuario)
        except Exception as erro:                            # noqa: BLE001 - o acesso fica; o convite pode ser reenviado
            return {"usuario": usuario.email, "convite": False, "erro": f"Convite não enviado: {str(erro)[:150]}"}
        return {"usuario": usuario.email, "convite": True}

    @router.post("/v1/fornecedor/lojas/{chave}/acessos-email/{usuario_id}/reenviar")
    def reenviar(chave: str, usuario_id: int, _=Depends(sessao), db: Session = Depends(get_db)):
        usuario = _do_alvo(db, chave, usuario_id)
        try:
            enviar_convite(db, usuario)
        except Exception as erro:                            # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Convite não enviado: {str(erro)[:150]}") from None
        auditar(db, "acesso_email_convite", chave, usuario.email)
        return {"convite": True}

    @router.post("/v1/fornecedor/lojas/{chave}/acessos-email/{usuario_id}/remover")
    def tirar(chave: str, usuario_id: int, _=Depends(sessao), db: Session = Depends(get_db)):
        usuario = _do_alvo(db, chave, usuario_id)
        auditar(db, "acesso_email_removido", chave, usuario.email)
        remover(db, usuario)
        return {"ok": True}

    def _do_alvo(db: Session, chave: str, usuario_id: int) -> PainelUsuario:
        loja = obter(db, chave)
        usuario = db.get(PainelUsuario, usuario_id)
        if usuario is None or not (usuario.chave_loja == loja.chave_loja
                                   or (loja.grupo_id and usuario.grupo_id == loja.grupo_id)):
            raise HTTPException(status_code=404, detail="Acesso não encontrado nesta loja.")
        return usuario

    app.include_router(router)
    return router
