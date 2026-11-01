"""Painel do dono no celular (nuvem): recebe o que o PDV envia e responde ao app web em /painel/.

Duas credenciais, de propósito separadas:
  * o TOKEN DA LOJA (o do PDV) envia vendas e retrato em POST /v1/painel/envio;
  * a SENHA DO PAINEL, definida pelo fornecedor (`python -m backend.lojas painel ADEGA-1` ou POST /v1/admin/lojas/{chave}/painel),
    abre uma sessão para o dono (POST /v1/painel/login) que vale 30 dias; o app guarda só o token da sessão.

Os dados ficam por loja (chave_loja) e nenhuma consulta cruza lojas. A nuvem guarda a venda como o PDV mandou (itens e
pagamentos em JSON) e calcula os totais na hora da consulta; para o movimento de uma loja num dia isso é barato.
Comandas abertas, comissões, fechamentos, sangrias e o faturamento dos últimos 12 meses vêm do retrato do caixa
(a venda em si continua só fechada ou cancelada).

Uma loja pode ter mais de um caixa (cada um com o seu banco local): as vendas se somam pelo uuid e cada caixa guarda o seu
retrato (turno, estoque, caderneta, entregas), identificado por `terminal_id`. PDV de versão anterior, que não manda o
identificador, entra como um caixa só ("unico").

A nuvem não é o arquivo da loja: o histórico completo fica no PDV. Vendas além da retenção (padrão 120 dias,
PDV_PAINEL_RETENCAO_DIAS), sessões vencidas e caixas parados há semanas saem sozinhos (`limpar_antigos`).

Este módulo não importa backend.main (evita importação circular): `instalar(app, Loja, autenticar)` recebe o que precisa.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, Integer, String, Text, UniqueConstraint, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as inserir_postgres
from sqlalchemy.dialects.sqlite import insert as inserir_sqlite

from backend.database import Base, SessionLocal, engine, get_db
from backend import painel_devolucoes as devolucoes

log = logging.getLogger("pdv.nuvem.painel")

PASTA_WEB = Path(__file__).resolve().parent / "painel_web"
DIAS_SESSAO = 30
TENTATIVAS_LOGIN = 8          # por loja, na janela abaixo; depois 429 até a janela passar
JANELA_LOGIN_SEG = 15 * 60
LOTE_MAXIMO = 500
VENDAS_POR_PAGINA = 50
DIA_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
ID_CAIXA_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
CAIXA_LEGADO = "unico"        # retrato de um PDV que ainda não manda o terminal_id
MINUTOS_CAIXA_LEGADO = 15     # o "unico" some quando o PDV atualizado manda o seu e o antigo calou há este tempo
MAX_CAIXAS_POR_LOJA = 20      # passando disto, o caixa parado há mais tempo sai para o novo entrar

# Limpeza (ver limpar_antigos). A retenção cobre os 90 dias que a tela de histórico pode pedir.
RETENCAO_VENDAS_DIAS = 120
RETENCAO_MINIMA_DIAS = 7      # um valor de ambiente errado (0, 1) não pode apagar o movimento recente
DIAS_CAIXA_PARADO = 14        # caixa que não manda retrato há tanto tempo deixou de existir (ou voltará e reaparece)
INTERVALO_LIMPEZA_SEG = 6 * 3600
LIMITE_CHAVES_TENTATIVAS = 500


# ------------------------------------------------------------------ modelos
class PainelAcesso(Base):
    """Senha do painel de uma loja (só o hash). Sem linha aqui, o dono não entra."""
    __tablename__ = "painel_acessos"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, unique=True, index=True, nullable=False)
    senha_hash = Column(String, nullable=False)
    atualizado_em = Column(String)


class PainelSessao(Base):
    __tablename__ = "painel_sessoes"
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    criada_em = Column(String, nullable=False)
    expira_em = Column(String, nullable=False)
    ultimo_uso = Column(String)


class PainelVenda(Base):
    """Uma venda fechada ou cancelada, como o PDV mandou. (chave_loja, uuid) é a identidade: reenviar atualiza."""
    __tablename__ = "painel_vendas"
    __table_args__ = (UniqueConstraint("chave_loja", "uuid", name="ux_painel_venda"),)
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    uuid = Column(String, nullable=False)
    dia = Column(String, index=True, nullable=False)
    cupom = Column(Integer)
    status = Column(String, nullable=False)
    modalidade = Column(String, nullable=False)
    posicao_rotulo = Column(String)
    operador = Column(String)
    aberta_em = Column(String)
    fechada_em = Column(String)
    total_cent = Column(Integer, nullable=False, default=0)
    desconto_cent = Column(Integer, nullable=False, default=0)
    motivo_cancelamento = Column(String)
    dados = Column(Text, nullable=False)          # a venda inteira (itens, pagamentos e os demais valores)
    recebida_em = Column(String, nullable=False)


class PainelCaixa(Base):
    """O último "momento" de cada caixa da loja: turno, estoque, caderneta, entregas e o relógio do PDV. Cada caixa tem o
    seu banco local e manda o seu retrato; (chave_loja, terminal_id) é a identidade e reenviar substitui o anterior."""
    __tablename__ = "painel_caixas"
    __table_args__ = (UniqueConstraint("chave_loja", "terminal_id", name="ux_painel_caixa"),)
    id = Column(Integer, primary_key=True)
    chave_loja = Column(String, index=True, nullable=False)
    terminal_id = Column(String, nullable=False)  # gerado pelo PDV e guardado no banco dele; "unico" = PDV sem identificação
    terminal = Column(Integer)                    # nº do terminal na loja: só ordena e rotula
    dados = Column(Text, nullable=False)
    momento = Column(String)                      # relógio da loja quando o retrato foi tirado
    recebido_em = Column(String, nullable=False)  # relógio da nuvem


# ------------------------------------------------------------------- senha
def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def gerar_hash_senha(senha: str) -> str:
    sal = secrets.token_hex(16)
    digesto = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(sal), 310_000)
    return f"pbkdf2_sha256$310000${sal}${digesto.hex()}"


def conferir_senha(senha: str, guardado: str | None) -> bool:
    try:
        algoritmo, iteracoes, sal, esperado = (guardado or "").split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        digesto = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(sal), int(iteracoes))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digesto.hex(), esperado)


def validar_senha(senha: str) -> str:
    senha = (senha or "").strip()
    if len(senha) < 8:
        raise ValueError("A senha do painel precisa ter pelo menos 8 caracteres.")
    if len(senha) > 128:
        raise ValueError("A senha do painel é longa demais.")
    return senha


def definir_senha(db: Session, chave_loja: str, senha: str) -> None:
    """Grava (ou troca) a senha do painel da loja e encerra as sessões abertas com a senha antiga."""
    senha = validar_senha(senha)
    acesso = db.query(PainelAcesso).filter_by(chave_loja=chave_loja).first()
    if acesso is None:
        acesso = PainelAcesso(chave_loja=chave_loja)
        db.add(acesso)
    acesso.senha_hash = gerar_hash_senha(senha)
    acesso.atualizado_em = _agora()
    db.query(PainelSessao).filter_by(chave_loja=chave_loja).delete()
    db.commit()
    from backend.cache_leitura import limpar
    limpar()


def gerar_senha() -> str:
    """Senha legível para passar ao dono por telefone: 3 grupos de 4 letras/números sem ambiguidade."""
    alfabeto = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3))


# ---------------------------------------------------------- tentativas
class _Tentativas:
    """Freio de força bruta por loja, em memória (por processo). Reinício do servidor zera; é o bastante para a senha
    do painel, que é longa e trocável."""

    def __init__(self):
        self._lock = threading.Lock()
        self._falhas: dict[str, deque] = {}

    def _vigentes(self, chave: str, agora: float) -> deque | None:
        """As falhas que ainda estão na janela (com a trava tomada). Sem nenhuma, a chave sai do dicionário."""
        fila = self._falhas.get(chave)
        if fila is None:
            return None
        while fila and agora - fila[0] > JANELA_LOGIN_SEG:
            fila.popleft()
        if not fila:
            del self._falhas[chave]
            return None
        return fila

    def bloqueada(self, chave: str, agora: float | None = None) -> bool:
        agora = time.monotonic() if agora is None else agora
        with self._lock:
            fila = self._vigentes(chave, agora)
            if fila is None and len(self._falhas) >= LIMITE_CHAVES_TENTATIVAS:
                self._limpar_vencidas(agora)
                # Saturação não pode expulsar o bloqueio de outra loja, nem aceitar chaves sem limite.
                return len(self._falhas) >= LIMITE_CHAVES_TENTATIVAS
            return fila is not None and len(fila) >= TENTATIVAS_LOGIN

    def _limpar_vencidas(self, agora: float) -> None:
        for chave in list(self._falhas):
            self._vigentes(chave, agora)

    def falhou(self, chave: str, agora: float | None = None) -> None:
        agora = time.monotonic() if agora is None else agora
        with self._lock:
            fila = self._vigentes(chave, agora)
            if fila is None:
                if len(self._falhas) >= LIMITE_CHAVES_TENTATIVAS:
                    self._limpar_vencidas(agora)
                    if len(self._falhas) >= LIMITE_CHAVES_TENTATIVAS:
                        return
                fila = self._falhas.setdefault(chave, deque(maxlen=TENTATIVAS_LOGIN))
            if len(fila) < TENTATIVAS_LOGIN:
                fila.append(agora)

    def acertou(self, chave: str) -> None:
        with self._lock:
            self._falhas.pop(chave, None)


tentativas = _Tentativas()


# ------------------------------------------------------------------ sessão
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def abrir_sessao(db: Session, chave_loja: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    expira = (datetime.now() + timedelta(days=DIAS_SESSAO)).strftime("%Y-%m-%d %H:%M:%S")
    db.add(PainelSessao(chave_loja=chave_loja, token_hash=_hash(token), criada_em=_agora(), expira_em=expira))
    db.commit()
    return token, expira


def sessao_do_dono(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> PainelSessao:
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
    sessao = db.query(PainelSessao).filter_by(token_hash=_hash(token)).first() if token else None
    if sessao is None or sessao.expira_em <= _agora():
        raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
    sessao.ultimo_uso = _agora()
    db.commit()
    from backend.memoria_nuvem import memoria
    memoria.lembrar_sessao(token, sessao.chave_loja)
    return sessao


# ---------------------------------------------------------------- cálculos
def _int(valor, padrao: int = 0) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def _dia_valido(dia: str | None) -> str | None:
    if not dia:
        return None
    if not DIA_RE.fullmatch(dia):
        raise HTTPException(status_code=422, detail="Informe o dia como AAAA-MM-DD.")
    try:
        date.fromisoformat(dia)
    except ValueError:
        raise HTTPException(status_code=422, detail="Dia inválido.") from None
    return dia


def _hoje() -> date:
    return date.today()


def retencao_vendas_dias() -> int:
    """Quantos dias de vendas a nuvem guarda: PDV_PAINEL_RETENCAO_DIAS, nunca menos de RETENCAO_MINIMA_DIAS."""
    try:
        dias = int(os.environ.get("PDV_PAINEL_RETENCAO_DIAS", ""))
    except ValueError:
        return RETENCAO_VENDAS_DIAS
    return max(dias, RETENCAO_MINIMA_DIAS)


def _corte_das_vendas() -> str:
    """Primeiro dia guardado (AAAA-MM-DD): o que for anterior sai na limpeza e nem entra."""
    return (_hoje() - timedelta(days=retencao_vendas_dias())).isoformat()


def _guardar_venda(db: Session, chave_loja: str, v: dict, agora: str) -> str | None:
    uuid = str(v.get("uuid") or "").strip()
    if not uuid or len(uuid) > 64 or v.get("status") not in ("fechada", "cancelada"):
        return None
    dia = v.get("dia") if isinstance(v.get("dia"), str) and DIA_RE.fullmatch(v["dia"]) else None
    if dia is None:
        dia = str(v.get("fechada_em") or v.get("aberta_em") or agora)[:10]
    if dia < _corte_das_vendas():
        return uuid          # além da retenção: confirma (o PDV para de mandar) mas não guarda, para a limpeza não apagar depois
    valores = dict(
        dia=dia, cupom=_int(v.get("cupom"), 0) or None, status=v["status"],
        modalidade=str(v.get("modalidade") or "balcao")[:20],
        posicao_rotulo=str(v.get("posicao_rotulo") or "")[:80], operador=str(v.get("operador") or "")[:60],
        aberta_em=str(v.get("aberta_em") or "")[:19] or None,
        fechada_em=str(v.get("fechada_em") or "")[:19] or None,
        total_cent=_int(v.get("total_cent")), desconto_cent=_int(v.get("desconto_cent")),
        motivo_cancelamento=str(v.get("motivo_cancelamento") or "")[:200] or None,
        dados=json.dumps(v, ensure_ascii=False), recebida_em=agora)
    # Upsert atômico nos dois bancos suportados: duplicatas e envios concorrentes não fazem duas inserções.
    inserir = inserir_sqlite if db.get_bind().dialect.name == "sqlite" else inserir_postgres
    comando = inserir(PainelVenda).values(chave_loja=chave_loja, uuid=uuid, **valores)
    db.execute(comando.on_conflict_do_update(
        index_elements=["chave_loja", "uuid"], set_=valores,
        # Cancelamento é definitivo: uma resposta/envio antigo de venda fechada não pode ressuscitá-la.
        where=(PainelVenda.status != "cancelada") | (comando.excluded.status == "cancelada")))
    return uuid


def _id_do_caixa(retrato: dict) -> str:
    bruto = str(retrato.get("terminal_id") or "").strip()
    return bruto if ID_CAIXA_RE.fullmatch(bruto) else CAIXA_LEGADO


def _guardar_retrato(db: Session, chave_loja: str, retrato: dict, enviado_em, agora: str) -> None:
    """Guarda (ou substitui) o retrato do caixa que mandou. Caixas diferentes da mesma loja não se sobrescrevem."""
    terminal_id = _id_do_caixa(retrato)
    linha = db.query(PainelCaixa).filter_by(chave_loja=chave_loja, terminal_id=terminal_id).first()
    if linha is None:
        # Um caixa novo sempre entra: passando do limite, sai o que está calado há mais tempo.
        antigos = db.query(PainelCaixa).filter_by(chave_loja=chave_loja).order_by(PainelCaixa.recebido_em).all()
        for velho in antigos[:max(len(antigos) - MAX_CAIXAS_POR_LOJA + 1, 0)]:
            db.delete(velho)
        linha = PainelCaixa(chave_loja=chave_loja, terminal_id=terminal_id)
        db.add(linha)
    linha.terminal = _int(retrato.get("terminal"), 1)
    linha.dados = json.dumps(retrato, ensure_ascii=False)
    linha.momento = str(retrato.get("momento") or enviado_em or "")[:19] or None
    linha.recebido_em = agora
    if terminal_id != CAIXA_LEGADO:
        # O PDV desta loja já se identifica: o "unico" que um PDV antigo deixou (e que ninguém mais renova) é o mesmo caixa.
        corte = (datetime.now() - timedelta(minutes=MINUTOS_CAIXA_LEGADO)).strftime("%Y-%m-%d %H:%M:%S")
        db.query(PainelCaixa).filter(PainelCaixa.chave_loja == chave_loja, PainelCaixa.terminal_id == CAIXA_LEGADO,
                                     PainelCaixa.recebido_em < corte).delete(synchronize_session=False)


def _ler_caixas(db: Session, chave_loja: str) -> list[tuple[PainelCaixa, dict]]:
    """Cada caixa da loja com o retrato já lido, na ordem do terminal."""
    pares = []
    for linha in db.query(PainelCaixa).filter_by(chave_loja=chave_loja).all():
        try:
            dados = json.loads(linha.dados)
        except ValueError:
            dados = {}
        pares.append((linha, dados if isinstance(dados, dict) else {}))
    pares.sort(key=lambda p: (p[0].terminal if p[0].terminal is not None else 1, _rotulo_do_caixa(*p), p[0].terminal_id))
    return pares


def _rotulo_do_caixa(linha: PainelCaixa, dados: dict) -> str:
    rotulo = str(dados.get("terminal_rotulo") or "").strip()[:60]
    return rotulo or f"Caixa {linha.terminal if linha.terminal is not None else 1}"


def _mais_recente(pares: list[tuple[PainelCaixa, dict]]) -> tuple[dict, str | None, str | None]:
    """O retrato do caixa que falou por último: é dele o dia operacional, o nome da loja e o "atualizado às"."""
    if not pares:
        return {}, None, None
    linha, dados = max(pares, key=lambda p: p[0].recebido_em)
    return dados, linha.momento, linha.recebido_em


def _retrato(db: Session, chave_loja: str) -> tuple[dict, str | None, str | None]:
    return _mais_recente(_ler_caixas(db, chave_loja))


def _estoque_vazio() -> dict:
    return {"controlados": 0, "zerados": 0, "abaixo_minimo": []}


def _caixa_publico(linha: PainelCaixa, dados: dict) -> dict:
    """O que o app recebe de cada caixa. Estoque e caderneta são do banco DAQUELE caixa: não se misturam aqui."""
    estoque, caderneta, turno = dados.get("estoque"), dados.get("caderneta"), dados.get("caixa")
    return {
        "id": linha.terminal_id, "terminal": linha.terminal if linha.terminal is not None else 1,
        "rotulo": _rotulo_do_caixa(linha, dados), "computador": str(dados.get("terminal_computador") or "").strip()[:60],
        "atualizado_em": linha.momento, "atraso_min": _atraso_min(linha.momento, linha.recebido_em),
        "caixa": turno if isinstance(turno, dict) else None,
        "estoque": estoque if isinstance(estoque, dict) else _estoque_vazio(),
        "caderneta": caderneta if isinstance(caderneta, dict) else {"a_receber_cent": 0, "clientes_devendo": 0},
        "entregas_pendentes": _int(dados.get("entregas_pendentes")),
        "vendas_pendentes_envio": _int(dados.get("vendas_pendentes_envio")),
    }


def _totais_dos_caixas(caixas: list[dict]) -> dict:
    """Os campos de sempre do /resumo (pensados para um caixa só), calculados de todos: o primeiro turno aberto, o primeiro
    estoque controlado, caderneta e entregas somadas. O app antigo só conhece estes campos e continua certo."""
    com_turno = next((c for c in caixas if c["caixa"]), None)
    com_estoque = next((c for c in caixas if _int(c["estoque"].get("controlados")) > 0), None) or (caixas[0] if caixas else None)
    return {
        "caixa": com_turno["caixa"] if com_turno else None,
        "estoque": com_estoque["estoque"] if com_estoque else _estoque_vazio(),
        "caderneta": {"a_receber_cent": sum(_int(c["caderneta"].get("a_receber_cent")) for c in caixas),
                      "clientes_devendo": sum(_int(c["caderneta"].get("clientes_devendo")) for c in caixas)},
        "entregas_pendentes": sum(c["entregas_pendentes"] for c in caixas),
        "vendas_pendentes_envio": sum(c["vendas_pendentes_envio"] for c in caixas),
    }


def _atraso_min(momento: str | None, recebido_em: str | None) -> int | None:
    """Minutos desde o último envio, pelo relógio da NUVEM (o do PDV pode estar errado): o dono vê há quanto tempo o PDV
    não fala com a nuvem, não a hora que o caixa marca."""
    if not recebido_em:
        return None
    try:
        return max(int((datetime.now() - datetime.strptime(recebido_em[:19], "%Y-%m-%d %H:%M:%S")).total_seconds() // 60), 0)
    except ValueError:
        return None


def _dias_recentes(db: Session, chave_loja: str, limite: int = 30) -> list[str]:
    linhas = (db.query(PainelVenda.dia).filter_by(chave_loja=chave_loja).distinct()
              .order_by(PainelVenda.dia.desc()).limit(limite).all())
    dias_devolucao = db.query(devolucoes.PainelDevolucao.dia).filter_by(chave_loja=chave_loja).distinct().order_by(
        devolucoes.PainelDevolucao.dia.desc()).limit(limite).all()
    return sorted({l[0] for l in linhas} | {l[0] for l in dias_devolucao}, reverse=True)[:limite]


def _vendas_do_dia(db: Session, chave_loja: str, dia: str) -> list[dict]:
    linhas = (db.query(PainelVenda).filter_by(chave_loja=chave_loja, dia=dia)
              .order_by(PainelVenda.fechada_em.desc(), PainelVenda.id.desc()).all())
    saida = []
    for l in linhas:
        try:
            v = json.loads(l.dados)
        except ValueError:
            v = {}
        v.update({"uuid": l.uuid, "cupom": l.cupom, "status": l.status, "modalidade": l.modalidade,
                  "posicao_rotulo": l.posicao_rotulo or "", "operador": l.operador or "", "fechada_em": l.fechada_em,
                  "total_cent": l.total_cent, "desconto_cent": l.desconto_cent,
                  "motivo_cancelamento": l.motivo_cancelamento or ""})
        v["itens"] = [i for i in (v.get("itens") or []) if isinstance(i, dict)]
        v["pagamentos"] = [p for p in (v.get("pagamentos") or []) if isinstance(p, dict)]
        saida.append(v)
    return saida


def resumo_do_dia(vendas: list[dict]) -> dict:
    """Os totais que o app mostra na aba Hoje, calculados das vendas guardadas (fechadas contam; canceladas só se contam)."""
    fechadas = [v for v in vendas if v["status"] == "fechada"]
    canceladas = [v for v in vendas if v["status"] == "cancelada"]
    faturamento = sum(_int(v["total_cent"]) for v in fechadas)
    formas: dict[str, int] = defaultdict(int)
    modalidades: dict[str, dict] = defaultdict(lambda: {"quantidade": 0, "valor_cent": 0})
    por_hora: dict[str, dict] = defaultdict(lambda: {"valor_cent": 0, "quantidade": 0})
    produtos: dict[str, dict] = defaultdict(lambda: {"quantidade": 0.0, "valor_cent": 0, "geladas": 0.0, "naturais": 0.0})
    itens_total = 0
    economia = 0
    for v in fechadas:
        for p in v["pagamentos"]:
            formas[str(p.get("tipo") or "?")] += _int(p.get("valor_cent")) - _int(p.get("troco_cent"))
        m = modalidades[str(v.get("modalidade") or "balcao")]
        m["quantidade"] += 1
        m["valor_cent"] += _int(v["total_cent"])
        hora = str(v.get("fechada_em") or "")[11:13] or "--"
        por_hora[hora]["valor_cent"] += _int(v["total_cent"])
        por_hora[hora]["quantidade"] += 1
        for i in v["itens"]:
            if _int(i.get("cancelado")):
                continue
            qtd = float(i.get("quantidade") or 0)
            itens_total += 1
            prod = produtos[str(i.get("nome") or "?")]
            prod["quantidade"] += qtd
            prod["valor_cent"] += _int(i.get("total_cent"))
            prod["geladas" if i.get("temperatura") == "gelada" else "naturais"] += qtd
            base = i.get("preco_base_cent")
            if isinstance(base, int) and base > _int(i.get("preco_unit_cent")):
                economia += round((base - _int(i.get("preco_unit_cent"))) * qtd)
    mais_vendidos = sorted(produtos.items(), key=lambda kv: (-kv[1]["valor_cent"], -kv[1]["quantidade"], kv[0]))[:15]
    return {
        "vendas": {"faturamento_cent": faturamento, "quantidade": len(fechadas),
                   "ticket_medio_cent": round(faturamento / len(fechadas)) if fechadas else 0,
                   "desconto_cent": sum(_int(v["desconto_cent"]) for v in fechadas), "itens": itens_total,
                   "canceladas": len(canceladas), "canceladas_cent": sum(_int(v["total_cent"]) for v in canceladas)},
        "formas": [{"tipo": t, "valor_cent": val} for t, val in sorted(formas.items(), key=lambda kv: -kv[1])],
        "modalidades": [{"modalidade": k, **m} for k, m in sorted(modalidades.items(), key=lambda kv: -kv[1]["valor_cent"])],
        "por_hora": [{"hora": h, **d} for h, d in sorted(por_hora.items())],
        "produtos": [{"nome": n, "quantidade": round(d["quantidade"], 4), "valor_cent": d["valor_cent"],
                      "geladas": round(d["geladas"], 4), "naturais": round(d["naturais"], 4)} for n, d in mais_vendidos],
        "atacado_economia_cent": economia,
    }


def _txt(valor, limite: int) -> str:
    return str(valor or "")[:limite]


def _data_segura(texto, padrao: date | None = None) -> date:
    try:
        return date.fromisoformat(str(texto)[:10])
    except (TypeError, ValueError):
        return padrao or _hoje()


def _chaves_meses(ultimo: date, n: int = 12) -> list[str]:
    ano, mes = ultimo.year, ultimo.month
    for _ in range(n - 1):
        mes -= 1
        if mes == 0:
            mes, ano = 12, ano - 1
    chaves = []
    for _ in range(n):
        chaves.append(f"{ano:04d}-{mes:02d}")
        mes += 1
        if mes == 13:
            mes, ano = 1, ano + 1
    return chaves


def _grade_meses(ultimo: date, somas: dict[str, dict]) -> list[dict]:
    return [{"mes": m, "faturamento_cent": int(somas.get(m, {}).get("faturamento_cent", 0)),
             "quantidade": int(somas.get(m, {}).get("quantidade", 0))} for m in _chaves_meses(ultimo)]


def _comandas_publicas(dados: dict) -> list[dict] | None:
    bruto = dados.get("comandas")
    if not isinstance(bruto, list):
        return None
    saida = []
    for item in bruto[:80]:
        if not isinstance(item, dict):
            continue
        itens = []
        for i in (item.get("itens") or [])[:8]:
            if isinstance(i, dict):
                itens.append({"nome": _txt(i.get("nome"), 60), "quantidade": i.get("quantidade"),
                              "total_cent": _int(i.get("total_cent"))})
        saida.append({
            "numero": _int(item.get("numero")), "rotulo": _txt(item.get("rotulo"), 40),
            "devido_cent": _int(item.get("devido_cent")), "total_cent": _int(item.get("total_cent")),
            "pago_cent": _int(item.get("pago_cent")), "aberta_em": _txt(item.get("aberta_em"), 19),
            "aberta_txt": _txt(item.get("aberta_txt"), 20), "garota": bool(item.get("garota")),
            "situacao": _txt(item.get("situacao"), 20),
            # Sem a chave, o retrato antigo só tinha comanda (a mesa não subia).
            "comanda": True if "comanda" not in item else bool(item.get("comanda")),
            "garcom": _txt(item.get("garcom"), 40), "pessoas": _int(item.get("pessoas")), "itens": itens,
        })
    return saida


def _comissoes_publicas(dados: dict) -> dict | None:
    bloco = dados.get("comissoes")
    if not isinstance(bloco, dict):
        return None
    linhas = []
    for item in (bloco.get("linhas") or [])[:300]:
        if not isinstance(item, dict) or item.get("status") not in ("pendente", "paga"):
            continue
        dia = _txt(item.get("dia"), 10)
        if not DIA_RE.fullmatch(dia):
            dia = ""
        linhas.append({
            "garota": _int(item.get("garota")), "nome": _txt(item.get("nome"), 60),
            "valor_cent": _int(item.get("valor_cent")), "status": item["status"],
            "criado_em": _txt(item.get("criado_em"), 19), "dia": dia,
        })
    return {"linhas": linhas, "pendente_total_cent": _int(bloco.get("pendente_total_cent"))}


def _fechamentos_publicos(dados: dict) -> list[dict] | None:
    bruto = dados.get("fechamentos")
    if not isinstance(bruto, list):
        return None
    saida = []
    for item in bruto[:40]:
        if not isinstance(item, dict):
            continue
        dia = _txt(item.get("dia"), 10)
        if not DIA_RE.fullmatch(dia):
            continue
        saida.append({
            "turno_numero": _int(item.get("turno_numero")), "operador": _txt(item.get("operador"), 60),
            "aberto_em": _txt(item.get("aberto_em"), 19), "fechado_em": _txt(item.get("fechado_em"), 19), "dia": dia,
            "valor_inicial_cent": _int(item.get("valor_inicial_cent")),
            "valor_final_cent": _int(item.get("valor_final_cent")),
            "esperado_cent": _int(item.get("esperado_cent")), "resultado_cent": _int(item.get("resultado_cent")),
            "sangrias_cent": _int(item.get("sangrias_cent")), "suprimentos_cent": _int(item.get("suprimentos_cent")),
        })
    return saida


def _sangrias_publicas(dados: dict) -> list[dict] | None:
    bruto = dados.get("sangrias")
    if not isinstance(bruto, list):
        return None
    saida = []
    for item in bruto[:200]:
        if not isinstance(item, dict):
            continue
        dia = _txt(item.get("dia"), 10)
        if not DIA_RE.fullmatch(dia):
            continue
        saida.append({
            "valor_cent": _int(item.get("valor_cent")), "descricao": _txt(item.get("descricao"), 80),
            "criado_em": _txt(item.get("criado_em"), 19), "dia": dia,
            "operador": _txt(item.get("operador"), 60), "turno_numero": _int(item.get("turno_numero")),
        })
    return saida


def _meses_publicos(dados: dict) -> list[dict] | None:
    bruto = dados.get("faturamento_meses")
    if not isinstance(bruto, list):
        return None
    saida = []
    for item in bruto[:24]:
        if not isinstance(item, dict):
            continue
        mes = str(item.get("mes") or "")
        if not re.fullmatch(r"\d{4}-\d{2}", mes):
            continue
        saida.append({"mes": mes, "faturamento_cent": _int(item.get("faturamento_cent")),
                      "quantidade": _int(item.get("quantidade"))})
    return saida


def _modulos_publicos(dados: dict) -> dict | None:
    bruto = dados.get("modulos")
    if not isinstance(bruto, dict) or "usar_mesas" not in bruto:
        return None
    try:
        servico = float(bruto.get("servico_pct") or 0)
        comissao = float(bruto.get("comissao_garcom_pct") or 0)
    except (TypeError, ValueError):
        servico = comissao = 0.0
    return {
        "usar_mesas": bool(bruto.get("usar_mesas")),
        "usar_garotas": bool(bruto.get("usar_garotas")),
        "usar_portaria": bool(bruto.get("usar_portaria")),
        "usar_cozinha_bar": bool(bruto.get("usar_cozinha_bar")),
        "servico_pct": servico, "comissao_garcom_pct": comissao,
    }


def perfil_do_painel(modulos: dict | None, comandas: list[dict], comissoes: dict | None) -> dict:
    """O que a tela mostra. Sem o flag, garota só aparece se o retrato tiver comissão de verdade
    (um bar antigo não ganha uma seção vazia de boate). Portaria não tem bloco no painel."""
    linhas = (comissoes or {}).get("linhas") or []
    tem_garota = any(c.get("garota") for c in comandas) or bool(linhas)
    if isinstance(modulos, dict):
        return {"conhecido": True, "mostrar_garotas": bool(modulos.get("usar_garotas")),
                "mostrar_portaria": bool(modulos.get("usar_portaria")),
                "mostrar_salao": bool(modulos.get("usar_mesas")), "modulos": modulos}
    return {"conhecido": False, "mostrar_garotas": tem_garota, "mostrar_portaria": False,
            "mostrar_salao": True, "modulos": {}}


def _minutos_entre(inicio, fim) -> int | None:
    try:
        a = datetime.strptime(str(inicio)[:19], "%Y-%m-%d %H:%M:%S")
        b = datetime.strptime(str(fim)[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    return max(int((b - a).total_seconds() // 60), 0)


def _consumo_da_venda(v: dict) -> int:
    if "subtotal_cent" in v:
        return max(_int(v.get("subtotal_cent")) - _int(v.get("desconto_cent")), 0)
    return max(_int(v.get("total_cent")) - _int(v.get("servico_cent")), 0)


def indicadores_bar(vendas: list[dict], pct_comissao: float = 0) -> dict:
    """Serviço, mesa, garçom, setor, grupo, CMV, cancelamento e desconto. Campos ausentes não inventam zero de custo."""
    from src.core import formatacao as fmt
    fechadas = [v for v in vendas if v.get("status") == "fechada"]
    canceladas = [v for v in vendas if v.get("status") == "cancelada"]
    servico = sum(_int(v.get("servico_cent")) for v in fechadas)
    tem_servico = any("servico_cent" in v for v in fechadas)
    mesas = [v for v in fechadas if v.get("modalidade") == "mesa"]
    pessoas = sum(_int(v.get("pessoas")) for v in mesas if _int(v.get("pessoas")) > 0)
    tempos = [m for m in (_minutos_entre(v.get("aberta_em"), v.get("fechada_em")) for v in mesas) if m is not None]
    garcons: dict[str, dict] = {}
    tem_garcom = any("garcom" in v for v in mesas)
    setores: dict[str, dict] = {}
    grupos: dict[str, dict] = {}
    cmv = 0
    tem_custo = False
    tem_setor = False
    tem_grupo = False
    for v in fechadas:
        for i in v.get("itens") or []:
            if not isinstance(i, dict) or _int(i.get("cancelado")):
                continue
            qtd = float(i.get("quantidade") or 0)
            valor = _int(i.get("total_cent"))
            if "grupo" in i:
                tem_grupo = True
                g = grupos.setdefault(str(i.get("grupo") or "Sem grupo"), {"nome": str(i.get("grupo") or "Sem grupo"),
                                                                            "valor_cent": 0, "quantidade": 0.0})
                g["valor_cent"] += valor
                g["quantidade"] += qtd
            if "setor" in i:
                tem_setor = True
                nome = str(i.get("setor") or "").strip() or "Sem setor"
                s = setores.setdefault(nome, {"nome": nome, "valor_cent": 0, "quantidade": 0.0})
                s["valor_cent"] += valor
                s["quantidade"] += qtd
            if "custo_unit_cent" in i:
                tem_custo = True
                cmv += int(round(qtd * _int(i.get("custo_unit_cent"))))
    for v in mesas:
        nome = str(v.get("garcom") or "").strip() or "Sem garçom"
        g = garcons.setdefault(nome, {"nome": nome, "vendas": 0, "consumo_cent": 0, "servico_cent": 0, "comissao_cent": 0})
        g["vendas"] += 1
        consumo = _consumo_da_venda(v)
        g["consumo_cent"] += consumo
        g["servico_cent"] += _int(v.get("servico_cent"))
        dos_itens = sum(_int(i.get("comissao_cent")) for i in (v.get("itens") or [])
                        if isinstance(i, dict) and not _int(i.get("cancelado")) and "comissao_cent" in i)
        g["comissao_cent"] += fmt.pct_de(consumo, pct_comissao) if pct_comissao else dos_itens
    faturamento_mesas = sum(_int(v.get("total_cent")) for v in mesas)
    return {
        "servico_cent": servico, "servico_sincronizado": tem_servico,
        "consumo_cent": sum(_consumo_da_venda(v) for v in fechadas),
        "mesas": {"quantidade": len(mesas),
                  "ticket_medio_cent": round(faturamento_mesas / len(mesas)) if mesas else 0,
                  "pessoas": pessoas,
                  "ticket_pessoa_cent": round(faturamento_mesas / pessoas) if pessoas else 0,
                  "permanencia_min": round(sum(tempos) / len(tempos)) if tempos else 0},
        "garcons": sorted(garcons.values(), key=lambda g: (-g["consumo_cent"], g["nome"])),
        "garcons_sincronizados": tem_garcom,
        "setores": sorted(setores.values(), key=lambda s: -s["valor_cent"]),
        "setores_sincronizados": tem_setor,
        "grupos": sorted(grupos.values(), key=lambda g: -g["valor_cent"]),
        "grupos_sincronizados": tem_grupo,
        "cmv_cent": cmv, "cmv_sincronizado": tem_custo,
        "margem_cent": sum(_int(i.get("total_cent")) for v in fechadas for i in (v.get("itens") or [])
                           if isinstance(i, dict) and not _int(i.get("cancelado"))) - cmv if tem_custo else 0,
        "cancelamentos": [{"cupom": v.get("cupom"), "total_cent": _int(v.get("total_cent")),
                           "motivo": _txt(v.get("motivo_cancelamento"), 120),
                           "operador": _txt(v.get("cancelada_por") or v.get("operador"), 40),
                           "hora": _txt(v.get("fechada_em"), 19)} for v in canceladas[:20]],
        "descontos": [{"cupom": v.get("cupom"), "desconto_cent": _int(v.get("desconto_cent")),
                       "total_cent": _int(v.get("total_cent")), "operador": _txt(v.get("operador"), 40),
                       "rotulo": _txt(v.get("posicao_rotulo"), 40)}
                      for v in fechadas if _int(v.get("desconto_cent")) > 0][:20],
    }


def faixa_mes_ate(ate: date) -> tuple[date, date, date, date]:
    """Do dia 1 até `ate`, e o mesmo tanto de dias no mês anterior (31/03 compara com 28/02)."""
    inicio = ate.replace(day=1)
    if ate.month == 1:
        ano, mes = ate.year - 1, 12
    else:
        ano, mes = ate.year, ate.month - 1
    primeiro_depois = date(ano + (mes == 12), 1 if mes == 12 else mes + 1, 1)
    ultimo = primeiro_depois - timedelta(days=1)
    return inicio, ate, date(ano, mes, 1), date(ano, mes, min(ate.day, ultimo.day))


def agregar_periodo(linhas) -> dict:
    """Totais, formas, dias e meses a partir das linhas (dia, status, total_cent, dados)."""
    formas: dict[str, int] = defaultdict(int)
    por_dia: dict[str, dict] = {}
    por_mes: dict[str, dict] = {}
    faturamento = quantidade = servico = 0
    tem_servico = False
    for dia, status, total, dados in linhas:
        if status != "fechada":
            continue
        try:
            v = json.loads(dados) if isinstance(dados, str) else {}
        except (TypeError, ValueError):
            v = {}
        if not isinstance(v, dict):
            v = {}
        valor = _int(total)
        faturamento += valor
        quantidade += 1
        if "servico_cent" in v:
            tem_servico = True
            servico += _int(v.get("servico_cent"))
        for p in v.get("pagamentos") or []:
            if isinstance(p, dict):
                formas[str(p.get("tipo") or "?")] += _int(p.get("valor_cent")) - _int(p.get("troco_cent"))
        dia_txt = str(dia)
        bloco = por_dia.setdefault(dia_txt, {"dia": dia_txt, "faturamento_cent": 0, "quantidade": 0})
        bloco["faturamento_cent"] += valor
        bloco["quantidade"] += 1
        mes = dia_txt[:7]
        acumulado = por_mes.setdefault(mes, {"mes": mes, "faturamento_cent": 0, "quantidade": 0, "servico_cent": 0})
        acumulado["faturamento_cent"] += valor
        acumulado["quantidade"] += 1
        if "servico_cent" in v:
            acumulado["servico_cent"] += _int(v.get("servico_cent"))
    return {
        "faturamento_cent": faturamento, "quantidade": quantidade,
        "ticket_medio_cent": round(faturamento / quantidade) if quantidade else 0,
        "servico_cent": servico, "servico_sincronizado": tem_servico,
        "formas": [{"tipo": t, "valor_cent": val} for t, val in sorted(formas.items(), key=lambda kv: -kv[1])],
        "por_dia": por_dia, "meses": [por_mes[k] for k in sorted(por_mes)],
    }


def _linhas_do_periodo(db: Session, chave_loja: str, de: str, ate: str):
    return (db.query(PainelVenda.dia, PainelVenda.status, PainelVenda.total_cent, PainelVenda.dados)
            .filter(PainelVenda.chave_loja == chave_loja, PainelVenda.dia >= de, PainelVenda.dia <= ate).all())


def relatorio_periodo(db: Session, chave_loja: str, de: date, ate: date) -> dict:
    """Um intervalo fechado, com os dias vazios no gráfico e um total por mês."""
    agregado = agregar_periodo(_linhas_do_periodo(db, chave_loja, de.isoformat(), ate.isoformat()))
    dias = []
    cursor = de
    while cursor <= ate:
        iso = cursor.isoformat()
        dias.append(agregado["por_dia"].get(iso, {"dia": iso, "faturamento_cent": 0, "quantidade": 0}))
        cursor += timedelta(days=1)
    return {
        "de": de.isoformat(), "ate": ate.isoformat(),
        "faturamento_cent": agregado["faturamento_cent"], "quantidade": agregado["quantidade"],
        "ticket_medio_cent": agregado["ticket_medio_cent"],
        "servico_cent": agregado["servico_cent"], "servico_sincronizado": agregado["servico_sincronizado"],
        "formas": agregado["formas"], "dias": dias, "meses": agregado["meses"],
        "parcial": de.isoformat() < _corte_das_vendas(),
    }


def faturamento_do_mes(db: Session, chave_loja: str, ate: date) -> dict:
    """Do dia 1 até `ate`, comparado com o mesmo período do mês anterior."""
    inicio, fim, inicio_ant, fim_ant = faixa_mes_ate(ate)
    atual = agregar_periodo(_linhas_do_periodo(db, chave_loja, inicio.isoformat(), fim.isoformat()))
    anterior = agregar_periodo(_linhas_do_periodo(db, chave_loja, inicio_ant.isoformat(), fim_ant.isoformat()))
    return {
        "de": inicio.isoformat(), "ate": fim.isoformat(),
        "faturamento_cent": atual["faturamento_cent"], "quantidade": atual["quantidade"],
        "anterior": {"de": inicio_ant.isoformat(), "ate": fim_ant.isoformat(),
                     "faturamento_cent": anterior["faturamento_cent"], "quantidade": anterior["quantidade"]},
        "variacao_cent": atual["faturamento_cent"] - anterior["faturamento_cent"],
        "parcial": inicio_ant.isoformat() < _corte_das_vendas(),
    }


def _servico_entre(db: Session, chave_loja: str, inicio: str, fim: str) -> tuple[int, bool]:
    """Soma a taxa de serviço das vendas fechadas no intervalo. O segundo valor diz se o caixa mandou o campo."""
    linhas = (db.query(PainelVenda.dados).filter(
        PainelVenda.chave_loja == chave_loja, PainelVenda.status == "fechada",
        PainelVenda.dia >= inicio, PainelVenda.dia <= fim).all())
    total = 0
    tem = False
    for (dados,) in linhas:
        try:
            v = json.loads(dados)
        except (TypeError, ValueError):
            continue
        if isinstance(v, dict) and "servico_cent" in v:
            tem = True
            total += _int(v.get("servico_cent"))
    return total, tem


def _com_origem(itens: list[dict], origem: str) -> list[dict]:
    if not origem:
        return itens
    for item in itens:
        item["caixa"] = origem
    return itens


def _gestao_dos_retratos(pares: list[tuple], ultimo: date) -> dict:
    """Junta o que cada caixa mandou no retrato. Lista ausente (PDV antigo) não é o mesmo que lista vazia."""
    varios = len(pares) > 1
    comandas, linhas, fechamentos, sangrias = [], [], [], []
    pendente = 0
    com_comandas = com_movimento = com_meses = 0
    somas: dict[str, dict] = defaultdict(lambda: {"faturamento_cent": 0, "quantidade": 0})
    modulos_fonte = [(linha, dados) for linha, dados in pares if _modulos_publicos(dados)]
    modulos = _modulos_publicos(max(modulos_fonte, key=lambda p: p[0].recebido_em)[1]) if modulos_fonte else None
    for linha, dados in pares:
        origem = _rotulo_do_caixa(linha, dados) if varios else ""
        lista = _comandas_publicas(dados)
        if lista is not None:
            com_comandas += 1
            comandas.extend(_com_origem(lista, origem))
        bloco = _comissoes_publicas(dados)
        if bloco is not None:
            pendente += bloco["pendente_total_cent"]
            linhas.extend(_com_origem(bloco["linhas"], origem))
        fechados = _fechamentos_publicos(dados)
        if fechados is not None:
            com_movimento += 1
            fechamentos.extend(_com_origem(fechados, origem))
        saidas = _sangrias_publicas(dados)
        if saidas is not None:
            sangrias.extend(_com_origem(saidas, origem))
        meses = _meses_publicos(dados)
        if meses is not None:
            com_meses += 1
            for m in meses:
                somas[m["mes"]]["faturamento_cent"] += m["faturamento_cent"]
                somas[m["mes"]]["quantidade"] += m["quantidade"]
    n = len(pares)
    return {
        "comandas": comandas,
        "comandas_sincronizadas": com_comandas > 0,
        "comandas_parciais": bool(n) and com_comandas != n,
        "comissoes": {"linhas": linhas, "pendente_total_cent": pendente},
        "fechamentos": fechamentos, "sangrias": sangrias,
        "movimento_sincronizado": com_movimento > 0,
        "movimento_parcial": bool(n) and com_movimento != n,
        "faturamento_meses": _grade_meses(ultimo, somas) if com_meses else None,
        "meses_origem": "caixa" if com_meses else "nuvem",
        "meses_parcial": not (com_meses and com_meses == n and n > 0),
        "modulos": modulos,
        "perfil": perfil_do_painel(modulos, comandas, {"linhas": linhas}),
    }


def _meses_das_vendas(db: Session, chave_loja: str, ultimo: date) -> list[dict]:
    """Os meses que ainda estão nas vendas guardadas. O que a retenção já apagou fica zerado."""
    chaves = _chaves_meses(ultimo)
    primeiro = chaves[0] + "-01"
    linhas = (db.query(PainelVenda.dia, PainelVenda.total_cent)
              .filter(PainelVenda.chave_loja == chave_loja, PainelVenda.status == "fechada",
                      PainelVenda.dia >= primeiro, PainelVenda.dia <= ultimo.isoformat()).all())
    somas: dict[str, dict] = defaultdict(lambda: {"faturamento_cent": 0, "quantidade": 0})
    for dia, total in linhas:
        mes = str(dia)[:7]
        somas[mes]["faturamento_cent"] += _int(total)
        somas[mes]["quantidade"] += 1
    return _grade_meses(ultimo, somas)


def ranking_produtos(vendas: list[dict], limite: int = 15) -> list[dict]:
    """Os mais vendidos de um conjunto de vendas fechadas: quantidade e faturamento, o valor decide a ordem."""
    return resumo_do_dia(vendas)["produtos"][:limite]


# ---------------------------------------------------------------- limpeza
def limpar_antigos(db: Session) -> dict[str, int]:
    """Apaga o que o painel não mostra mais e devolve quantas linhas saíram de cada coisa. O arquivo da loja é o PDV: a nuvem
    guarda só a janela que o app consulta (vendas dos últimos `retencao_vendas_dias()`), tira as sessões vencidas e os caixas
    que não mandam retrato há DIAS_CAIXA_PARADO dias. Seguro repetir: só apaga o que já passou do prazo."""
    agora = datetime.now()
    removidas = {
        "devolucoes": db.query(devolucoes.PainelDevolucao).filter(
            devolucoes.PainelDevolucao.dia < _corte_das_vendas()).delete(synchronize_session=False),
        "vendas": db.query(PainelVenda).filter(PainelVenda.dia < _corte_das_vendas()).delete(synchronize_session=False),
        "sessoes": db.query(PainelSessao).filter(PainelSessao.expira_em <= _agora()).delete(synchronize_session=False),
        "caixas": db.query(PainelCaixa).filter(
            PainelCaixa.recebido_em < (agora - timedelta(days=DIAS_CAIXA_PARADO)).strftime("%Y-%m-%d %H:%M:%S")
        ).delete(synchronize_session=False),
    }
    db.commit()
    return removidas


_limpeza = {"ultima": None}
_trava_limpeza = threading.Lock()


def limpeza_periodica() -> dict[str, int] | None:
    """A limpeza que roda sozinha: chamada a cada envio do PDV (em segundo plano, depois da resposta), mas só trabalha na
    primeira vez do processo e depois a cada INTERVALO_LIMPEZA_SEG. Falha aqui nunca atrapalha o envio."""
    agora = time.monotonic()
    with _trava_limpeza:
        ultima = _limpeza["ultima"]
        if ultima is not None and agora - ultima < INTERVALO_LIMPEZA_SEG:
            return None
        _limpeza["ultima"] = agora
    db = SessionLocal()
    try:
        removidas = limpar_antigos(db)
    except Exception:
        db.rollback()
        log.exception("Painel: a limpeza dos dados antigos falhou; a próxima tentativa é daqui a algumas horas.")
        return None
    finally:
        db.close()
    if any(removidas.values()):
        log.info("Painel: limpeza removeu %s.", ", ".join(f"{n} {nome}" for nome, n in removidas.items() if n))
    return removidas


def _descartar_retratos_antigos() -> None:
    """`painel_retratos` (um retrato por loja) virou `painel_caixas` (um por caixa). O retrato é só o último "momento" e cada
    PDV o refaz na próxima rodada de envio (cerca de 1 minuto), então nada é copiado: a tabela antiga apenas sai do caminho."""
    try:
        if inspect(engine).has_table("painel_retratos"):
            with engine.begin() as con:
                con.execute(text("DROP TABLE painel_retratos"))
    except Exception:
        log.exception("Painel: não consegui apagar a tabela antiga painel_retratos; ela fica sem uso.")


# ----------------------------------------------------------------- rotas
def instalar(app: FastAPI, Loja, autenticar) -> APIRouter:
    """Cria as tabelas, registra as rotas e serve o app web. `autenticar` é a dependência do backend.main (token da loja
    ou do administrador) e `Loja` o modelo das lojas."""
    Base.metadata.create_all(bind=engine)
    _descartar_retratos_antigos()
    router = APIRouter()

    def _loja(db: Session, chave: str):
        loja = db.query(Loja).filter(Loja.chave_loja == chave).first()
        if loja is None:
            raise HTTPException(status_code=404, detail=f"Loja {chave} não encontrada.")
        return loja

    def sessao_ativa(sessao: PainelSessao = Depends(sessao_do_dono), db: Session = Depends(get_db)):
        loja = db.query(Loja).filter(Loja.chave_loja == sessao.chave_loja).first()
        if loja is None or not loja.ativa:
            db.query(PainelSessao).filter_by(chave_loja=sessao.chave_loja).delete(synchronize_session=False)
            db.commit()
            raise HTTPException(status_code=401, detail="Sessão inválida ou vencida. Entre de novo.")
        return sessao

    # ---- envio do PDV (token da loja)
    @router.post("/v1/painel/envio")
    def envio(tarefas: BackgroundTasks, dados: dict = Body(...), acesso=Depends(autenticar), db: Session = Depends(get_db)):
        if acesso.admin:
            raise HTTPException(status_code=403, detail="Use o token da loja para enviar dados.")
        vendas = dados.get("vendas") or []
        if not isinstance(vendas, list) or len(vendas) > LOTE_MAXIMO:
            raise HTTPException(status_code=422, detail=f"Envie uma lista de até {LOTE_MAXIMO} vendas.")
        retornos = dados.get("devolucoes") or []
        if not isinstance(retornos, list) or len(retornos) > LOTE_MAXIMO:
            raise HTTPException(status_code=422, detail=f"Envie até {LOTE_MAXIMO} devoluções por lote.")
        agora = _agora()
        recebidos = []
        for v in vendas:
            if isinstance(v, dict):
                uuid = _guardar_venda(db, acesso.loja, v, agora)
                if uuid and uuid not in recebidos:
                    recebidos.append(uuid)
        retrato = dados.get("retrato")
        if isinstance(retrato, dict):
            _guardar_retrato(db, acesso.loja, retrato, dados.get("enviado_em"), agora)
        recebidas_devolucoes = [devolucoes.guardar(db, acesso.loja, d, agora, _corte_das_vendas()) for d in retornos]
        batimento = dados.get("heartbeat")
        heartbeat_confirmado = False
        if isinstance(batimento, dict):
            linha = db.query(PainelCaixa).filter_by(chave_loja=acesso.loja, terminal_id=_id_do_caixa(batimento)).first()
            if linha is not None:
                linha.recebido_em = agora
                linha.momento = str(dados.get("enviado_em") or agora)[:19]
                foto = json.loads(linha.dados)
                foto["momento"] = linha.momento
                for campo in ("vendas_pendentes_envio", "devolucoes_pendentes_envio"):
                    foto[campo] = max(_int(batimento.get(campo)), 0)
                linha.dados = json.dumps(foto, ensure_ascii=False)
                heartbeat_confirmado = True
        db.commit()
        tarefas.add_task(limpeza_periodica)         # depois da resposta: o PDV não espera pela limpeza
        resposta = {"recebidas": len(recebidos), "uuids": recebidos}
        if "devolucoes" in dados:
            resposta["devolucoes_uuids"] = list(dict.fromkeys(recebidas_devolucoes))
        if "heartbeat" in dados:
            resposta["heartbeat_confirmado"] = heartbeat_confirmado
        return resposta

    # ---- senha do painel (administrador ou o próprio PDV da loja)
    @router.post("/v1/admin/lojas/{chave}/painel")
    def admin_senha(chave: str, dados: dict = Body(default={}), acesso=Depends(autenticar), db: Session = Depends(get_db)):
        if not acesso.admin:
            raise HTTPException(status_code=403, detail="Só o administrador define a senha do painel de uma loja.")
        _loja(db, chave)
        return _gravar_senha(db, chave, dados)

    @router.post("/v1/painel/senha")
    def senha_pelo_pdv(dados: dict = Body(default={}), acesso=Depends(autenticar), db: Session = Depends(get_db)):
        if acesso.admin:
            raise HTTPException(status_code=403, detail="Use o token da loja (ou a rota de administrador com a chave).")
        return _gravar_senha(db, acesso.loja, dados)

    def _gravar_senha(db: Session, chave: str, dados: dict) -> dict:
        senha = str(dados.get("senha") or "").strip() or gerar_senha()
        try:
            definir_senha(db, chave, senha)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        # A senha gerada aparece UMA vez, para o fornecedor passar ao dono; uma informada não é devolvida.
        return {"loja": chave, "senha": senha if not dados.get("senha") else None, "definida": True}

    # ---- sessão do dono
    @router.post("/v1/painel/login")
    def login(dados: dict = Body(...), db: Session = Depends(get_db)):
        chave = str(dados.get("loja") or "").strip()
        senha = str(dados.get("senha") or "")
        if not chave or not senha:
            raise HTTPException(status_code=422, detail="Informe a loja e a senha.")
        if len(chave) > 64 or len(senha) > 128:
            raise HTTPException(status_code=422, detail="Loja ou senha longa demais.")
        if tentativas.bloqueada(chave):
            raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde alguns minutos.")
        loja = db.query(Loja).filter(Loja.chave_loja == chave).first()
        acesso = db.query(PainelAcesso).filter_by(chave_loja=chave).first()
        if loja is None or not loja.ativa or acesso is None or not conferir_senha(senha, acesso.senha_hash):
            tentativas.falhou(chave)
            raise HTTPException(status_code=401, detail="Loja ou senha inválida.")
        tentativas.acertou(chave)
        token, expira = abrir_sessao(db, chave)
        from backend.memoria_nuvem import memoria
        memoria.lembrar_sessao(token, chave)
        return {"token": token, "loja": {"chave": loja.chave_loja, "nome": loja.nome}, "expira_em": expira}

    @router.post("/v1/painel/sair")
    def sair(sessao: PainelSessao = Depends(sessao_ativa), db: Session = Depends(get_db)):
        db.delete(sessao)
        db.commit()
        from backend.cache_leitura import limpar
        limpar()
        return {"ok": True}

    # ---- consultas do dono
    @router.get("/v1/painel/resumo")
    def resumo(dia: Optional[str] = Query(None, max_length=10), sessao: PainelSessao = Depends(sessao_ativa),
               db: Session = Depends(get_db)):
        loja = _loja(db, sessao.chave_loja)
        pares = _ler_caixas(db, loja.chave_loja)
        retrato, momento, recebido_em = _mais_recente(pares)
        caixas = [_caixa_publico(linha, dados_) for linha, dados_ in pares]
        dias = _dias_recentes(db, loja.chave_loja)
        dia = _dia_valido(dia) or retrato.get("dia_operacional") or (dias[0] if dias else date.today().isoformat())
        r = resumo_do_dia(_vendas_do_dia(db, loja.chave_loja, dia))
        reembolsos = devolucoes.resumo(db, loja.chave_loja, dia, dia)
        r["devolucoes"] = reembolsos
        r["vendas"].update({"bruto_cent": r["vendas"]["faturamento_cent"],
                            "devolucoes_cent": reembolsos["valor_cent"],
                            "liquido_cent": r["vendas"]["faturamento_cent"] - reembolsos["valor_cent"]})
        r["devolucoes_completas"] = bool(pares) and all(
            d.get("devolucoes_suportadas") and not d.get("devolucoes_pendentes_envio") for _, d in pares)
        dia_op = _data_segura(retrato.get("dia_operacional"), _hoje())
        gestao = _gestao_dos_retratos(pares, dia_op)
        if gestao["faturamento_meses"] is None:
            gestao["faturamento_meses"] = _meses_das_vendas(db, loja.chave_loja, dia_op)
        pct = (gestao.get("modulos") or {}).get("comissao_garcom_pct") or 0
        bar = indicadores_bar(_vendas_do_dia(db, loja.chave_loja, dia), pct)
        try:
            anterior = (date.fromisoformat(str(dia)[:10]) - timedelta(days=7)).isoformat()
        except ValueError:
            anterior = None
        if anterior:
            antes = resumo_do_dia(_vendas_do_dia(db, loja.chave_loja, anterior))
            bar["semana_anterior"] = {"dia": anterior, "faturamento_cent": antes["vendas"]["faturamento_cent"],
                                      "quantidade": antes["vendas"]["quantidade"], "por_hora": antes["por_hora"]}
        else:
            bar["semana_anterior"] = None
        inicio_mes = str(dia)[:7] + "-01" if DIA_RE.fullmatch(str(dia)[:10]) else dia
        bar["servico_mes_cent"], bar["servico_mes_sincronizado"] = _servico_entre(
            db, loja.chave_loja, inicio_mes, str(dia)[:10])
        r["bar"] = bar
        r["mes"] = faturamento_do_mes(db, loja.chave_loja, dia_op)
        from src.whatsapp.alertas import montar as montar_alertas
        r["alertas"] = montar_alertas(r, retrato, retrato.get("whatsapp") or {})
        r["perdas"] = retrato.get("perdas") or []
        r["conferencias"] = retrato.get("fechamentos") or []
        r.update({
            "loja": {"chave": loja.chave_loja, "nome": retrato.get("loja_nome") or loja.nome},
            "dia": dia, "dia_operacional": dia_op.isoformat(),
            "atualizado_em": momento, "atraso_min": _atraso_min(momento, recebido_em),
            "atualizacao_seg": 60,
            **_totais_dos_caixas(caixas), "caixas": caixas,
            "dias": dias if dia in dias else [dia] + dias,
            **gestao,
        })
        return r

    @router.get("/v1/painel/whatsapp")
    def whatsapp(de: str = Query(..., max_length=10), ate: str = Query(..., max_length=10),
                 sessao: PainelSessao = Depends(sessao_ativa), db: Session = Depends(get_db)):
        """Texto do resumo para o link do WhatsApp. Só quando o dono pede; não entra na consulta automática."""
        inicio, fim = _data_segura(de, None), _data_segura(ate, None)
        if inicio is None or fim is None or fim < inicio or (fim - inicio).days > 400:
            raise HTTPException(status_code=422, detail="Informe o período como AAAA-MM-DD, com no máximo 400 dias.")
        loja = _loja(db, sessao.chave_loja)
        retrato, _, _ = _mais_recente(_ler_caixas(db, loja.chave_loja))
        linhas = (db.query(PainelVenda).filter(
            PainelVenda.chave_loja == loja.chave_loja, PainelVenda.dia >= inicio.isoformat(),
            PainelVenda.dia <= fim.isoformat()).all())
        vendas = []
        for l in linhas:
            try:
                v = json.loads(l.dados)
            except ValueError:
                v = {}
            if not isinstance(v, dict):
                v = {}
            v.update({"status": l.status, "total_cent": l.total_cent, "desconto_cent": l.desconto_cent,
                      "fechada_em": l.fechada_em, "garcom": v.get("garcom") or ""})
            v["itens"] = [i for i in (v.get("itens") or []) if isinstance(i, dict)]
            v["pagamentos"] = [p for p in (v.get("pagamentos") or []) if isinstance(p, dict)]
            vendas.append(v)
        base = resumo_do_dia(vendas)
        garcons: dict[str, dict] = {}
        for v in vendas:
            if v.get("status") != "fechada":
                continue
            nome = str(v.get("garcom") or "").strip() or "Sem garçom"
            bloco = garcons.setdefault(nome, {"nome": nome, "faturamento_cent": 0, "quantidade": 0})
            bloco["faturamento_cent"] += _int(v.get("total_cent"))
            bloco["quantidade"] += 1
        dia_conf = fim.isoformat()
        conferencias = [f for f in (retrato.get("fechamentos") or []) if str(f.get("dia") or "") == dia_conf] \
            if inicio == fim else list(retrato.get("fechamentos") or [])[:8]
        from src.whatsapp.resumo import links as links_whatsapp
        from src.whatsapp.resumo import texto_resumo
        cfg = retrato.get("whatsapp") or {}
        texto = texto_resumo({
            "loja": retrato.get("loja_nome") or loja.nome,
            "periodo": f"{inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}",
            "vendas": base["vendas"],
            "servico_cent": sum(_int(v.get("servico_cent")) for v in vendas if v.get("status") == "fechada"),
            "garcons": sorted(garcons.values(), key=lambda g: -g["faturamento_cent"]),
            "produtos": base["produtos"],
            "formas": base["formas"],
            "sangrias_cent": sum(_int(s.get("valor_cent")) for s in (retrato.get("sangrias") or [])
                                if inicio.isoformat() <= str(s.get("dia") or "") <= fim.isoformat()),
            "conferencias": conferencias,
            "perdas": retrato.get("perdas") or [],
        })
        return {"texto": texto, "links": links_whatsapp(cfg.get("numeros") or [], texto)}

    @router.get("/v1/painel/periodo")
    def periodo(de: str = Query(..., max_length=10), ate: str = Query(..., max_length=10),
                sessao: PainelSessao = Depends(sessao_ativa), db: Session = Depends(get_db)):
        """Relatório de um intervalo. Serve boate, bar e adega: só vendas fechadas já na nuvem."""
        inicio, fim = _data_segura(de, None), _data_segura(ate, None)
        if inicio is None or fim is None or str(de)[:10] != inicio.isoformat() or str(ate)[:10] != fim.isoformat():
            raise HTTPException(status_code=422, detail="Informe as datas como AAAA-MM-DD.")
        if fim < inicio:
            raise HTTPException(status_code=422, detail="A data final é anterior à inicial.")
        if (fim - inicio).days > 400:
            raise HTTPException(status_code=422, detail="O intervalo pode ter no máximo 400 dias.")
        return relatorio_periodo(db, sessao.chave_loja, inicio, fim)

    @router.get("/v1/painel/produtos")
    def produtos(periodo: str = Query("hoje"), sessao: PainelSessao = Depends(sessao_ativa),
                 db: Session = Depends(get_db)):
        """Ranking dos mais vendidos. `hoje`, `7d` e `30d` contam a partir do dia operacional da loja."""
        janela = {"hoje": 1, "7d": 7, "30d": 30}.get(periodo)
        if janela is None:
            raise HTTPException(status_code=422, detail="Período inválido. Use hoje, 7d ou 30d.")
        retrato, _, _ = _retrato(db, sessao.chave_loja)
        ate = _data_segura(retrato.get("dia_operacional"), _hoje())
        de = (ate - timedelta(days=janela - 1)).isoformat()
        linhas = (db.query(PainelVenda).filter(
            PainelVenda.chave_loja == sessao.chave_loja, PainelVenda.status == "fechada",
            PainelVenda.dia >= de, PainelVenda.dia <= ate.isoformat()).all())
        vendas = []
        for l in linhas:
            try:
                v = json.loads(l.dados)
            except ValueError:
                v = {}
            if not isinstance(v, dict):
                v = {}
            v["status"] = "fechada"
            v["total_cent"] = l.total_cent
            v["itens"] = [i for i in (v.get("itens") or []) if isinstance(i, dict)]
            v["pagamentos"] = []
            vendas.append(v)
        return {"periodo": periodo, "de": de, "ate": ate.isoformat(),
                "produtos": ranking_produtos(vendas)}

    @router.get("/v1/painel/vendas")
    def vendas(dia: Optional[str] = Query(None, max_length=10), pagina: int = Query(1, ge=1),
               sessao: PainelSessao = Depends(sessao_ativa), db: Session = Depends(get_db)):
        retrato, _, _ = _retrato(db, sessao.chave_loja)
        dia = _dia_valido(dia) or retrato.get("dia_operacional") or date.today().isoformat()
        todas = _vendas_do_dia(db, sessao.chave_loja, dia)
        paginas = max((len(todas) + VENDAS_POR_PAGINA - 1) // VENDAS_POR_PAGINA, 1)
        inicio = (min(pagina, paginas) - 1) * VENDAS_POR_PAGINA
        chaves = ("uuid", "cupom", "status", "modalidade", "posicao_rotulo", "operador", "fechada_em", "total_cent",
                  "desconto_cent", "motivo_cancelamento", "itens", "pagamentos", "terminal_id")
        return {"dia": dia, "pagina": min(pagina, paginas), "paginas": paginas, "total": len(todas),
                "vendas": [{k: v.get(k) for k in chaves} for v in todas[inicio:inicio + VENDAS_POR_PAGINA]]}

    @router.get("/v1/painel/historico")
    def historico(dias: int = Query(14, ge=1, le=90), sessao: PainelSessao = Depends(sessao_ativa),
                  db: Session = Depends(get_db)):
        retrato, _, _ = _retrato(db, sessao.chave_loja)
        ultimo = date.fromisoformat(retrato.get("dia_operacional") or date.today().isoformat())
        primeiro = (ultimo - timedelta(days=dias - 1)).isoformat()
        linhas = (db.query(PainelVenda.dia, PainelVenda.status, PainelVenda.total_cent)
                  .filter(PainelVenda.chave_loja == sessao.chave_loja, PainelVenda.dia >= primeiro,
                          PainelVenda.dia <= ultimo.isoformat()).all())
        por_dia: dict[str, dict] = {}
        for n in range(dias):
            d = (ultimo - timedelta(days=dias - 1 - n)).isoformat()
            por_dia[d] = {"dia": d, "faturamento_cent": 0, "quantidade": 0, "canceladas": 0}
        for dia_, status, total in linhas:
            if dia_ not in por_dia:
                continue
            if status == "fechada":
                por_dia[dia_]["faturamento_cent"] += _int(total)
                por_dia[dia_]["quantidade"] += 1
            else:
                por_dia[dia_]["canceladas"] += 1
        reembolsos = devolucoes.por_dia(db, sessao.chave_loja, primeiro, ultimo.isoformat())
        for d, registro in por_dia.items():
            registro["devolucoes_cent"] = reembolsos.get(d, 0)
            registro["liquido_cent"] = registro["faturamento_cent"] - registro["devolucoes_cent"]
        return {"dias": list(por_dia.values())}

    app.include_router(router)

    # ---- o app web: /painel/ abre o index; os demais arquivos são estáticos. Sem a pasta (instalação parcial) só a API sobe.
    if PASTA_WEB.is_dir():
        @app.get("/painel", include_in_schema=False)
        def painel_raiz():
            return RedirectResponse(url="/painel/")

        @app.get("/painel/", include_in_schema=False)
        def painel_index():
            return FileResponse(PASTA_WEB / "index.html", headers={"Cache-Control": "no-cache"})

        app.mount("/painel", StaticFiles(directory=str(PASTA_WEB)), name="painel")
    return router
