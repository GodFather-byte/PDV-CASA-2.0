"""Painel do dono no celular (nuvem): recebe o que o PDV envia e responde ao app web em /painel/.

Duas credenciais, de propósito separadas:
  * o TOKEN DA LOJA (o do PDV) envia vendas e retrato em POST /v1/painel/envio;
  * a SENHA DO PAINEL, definida pelo fornecedor (`python -m backend.lojas painel ADEGA-1` ou POST /v1/admin/lojas/{chave}/painel),
    abre uma sessão para o dono (POST /v1/painel/login) que vale 30 dias; o app guarda só o token da sessão.

Os dados ficam por loja (chave_loja) e nenhuma consulta cruza lojas. A nuvem guarda a venda como o PDV mandou (itens e
pagamentos em JSON) e calcula os totais na hora da consulta; para o movimento de uma loja num dia isso é barato.

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

from backend.database import Base, SessionLocal, engine, get_db

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
            return fila is not None and len(fila) >= TENTATIVAS_LOGIN

    def falhou(self, chave: str, agora: float | None = None) -> None:
        agora = time.monotonic() if agora is None else agora
        with self._lock:
            if len(self._falhas) >= LIMITE_CHAVES_TENTATIVAS:
                # Quem erra com nomes de loja inventados não pode encher a memória do servidor: varre o que já venceu.
                for outra in list(self._falhas):
                    self._vigentes(outra, agora)
            self._falhas.setdefault(chave, deque()).append(agora)

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
    linha = db.query(PainelVenda).filter_by(chave_loja=chave_loja, uuid=uuid).first()
    if linha is None:
        linha = PainelVenda(chave_loja=chave_loja, uuid=uuid)
        db.add(linha)
    linha.dia = dia
    linha.cupom = _int(v.get("cupom"), 0) or None
    linha.status = v["status"]
    linha.modalidade = str(v.get("modalidade") or "balcao")[:20]
    linha.posicao_rotulo = str(v.get("posicao_rotulo") or "")[:80]
    linha.operador = str(v.get("operador") or "")[:60]
    linha.aberta_em = str(v.get("aberta_em") or "")[:19] or None
    linha.fechada_em = str(v.get("fechada_em") or "")[:19] or None
    linha.total_cent = _int(v.get("total_cent"))
    linha.desconto_cent = _int(v.get("desconto_cent"))
    linha.motivo_cancelamento = str(v.get("motivo_cancelamento") or "")[:200] or None
    linha.dados = json.dumps(v, ensure_ascii=False)
    linha.recebida_em = agora
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
    return [l[0] for l in linhas]


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


# ---------------------------------------------------------------- limpeza
def limpar_antigos(db: Session) -> dict[str, int]:
    """Apaga o que o painel não mostra mais e devolve quantas linhas saíram de cada coisa. O arquivo da loja é o PDV: a nuvem
    guarda só a janela que o app consulta (vendas dos últimos `retencao_vendas_dias()`), tira as sessões vencidas e os caixas
    que não mandam retrato há DIAS_CAIXA_PARADO dias. Seguro repetir: só apaga o que já passou do prazo."""
    agora = datetime.now()
    removidas = {
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

    # ---- envio do PDV (token da loja)
    @router.post("/v1/painel/envio")
    def envio(tarefas: BackgroundTasks, dados: dict = Body(...), acesso=Depends(autenticar), db: Session = Depends(get_db)):
        if acesso.admin:
            raise HTTPException(status_code=403, detail="Use o token da loja para enviar dados.")
        vendas = dados.get("vendas") or []
        if not isinstance(vendas, list) or len(vendas) > LOTE_MAXIMO:
            raise HTTPException(status_code=422, detail=f"Envie uma lista de até {LOTE_MAXIMO} vendas.")
        agora = _agora()
        recebidos = []
        for v in vendas:
            if isinstance(v, dict):
                uuid = _guardar_venda(db, acesso.loja, v, agora)
                if uuid:
                    recebidos.append(uuid)
        retrato = dados.get("retrato")
        if isinstance(retrato, dict):
            _guardar_retrato(db, acesso.loja, retrato, dados.get("enviado_em"), agora)
        db.commit()
        tarefas.add_task(limpeza_periodica)         # depois da resposta: o PDV não espera pela limpeza
        return {"recebidas": len(recebidos), "uuids": recebidos}

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
        if tentativas.bloqueada(chave):
            raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde alguns minutos.")
        loja = db.query(Loja).filter(Loja.chave_loja == chave).first()
        acesso = db.query(PainelAcesso).filter_by(chave_loja=chave).first()
        if loja is None or not loja.ativa or acesso is None or not conferir_senha(senha, acesso.senha_hash):
            tentativas.falhou(chave)
            raise HTTPException(status_code=401, detail="Loja ou senha inválida.")
        tentativas.acertou(chave)
        token, expira = abrir_sessao(db, chave)
        return {"token": token, "loja": {"chave": loja.chave_loja, "nome": loja.nome}, "expira_em": expira}

    @router.post("/v1/painel/sair")
    def sair(sessao: PainelSessao = Depends(sessao_do_dono), db: Session = Depends(get_db)):
        db.delete(sessao)
        db.commit()
        return {"ok": True}

    # ---- consultas do dono
    @router.get("/v1/painel/resumo")
    def resumo(dia: Optional[str] = Query(None, max_length=10), sessao: PainelSessao = Depends(sessao_do_dono),
               db: Session = Depends(get_db)):
        loja = _loja(db, sessao.chave_loja)
        pares = _ler_caixas(db, loja.chave_loja)
        retrato, momento, recebido_em = _mais_recente(pares)
        caixas = [_caixa_publico(linha, dados_) for linha, dados_ in pares]
        dias = _dias_recentes(db, loja.chave_loja)
        dia = _dia_valido(dia) or retrato.get("dia_operacional") or (dias[0] if dias else date.today().isoformat())
        r = resumo_do_dia(_vendas_do_dia(db, loja.chave_loja, dia))
        r.update({
            "loja": {"chave": loja.chave_loja, "nome": retrato.get("loja_nome") or loja.nome},
            "dia": dia, "atualizado_em": momento, "atraso_min": _atraso_min(momento, recebido_em),
            **_totais_dos_caixas(caixas), "caixas": caixas,
            "dias": dias if dia in dias else [dia] + dias,
        })
        return r

    @router.get("/v1/painel/vendas")
    def vendas(dia: Optional[str] = Query(None, max_length=10), pagina: int = Query(1, ge=1),
               sessao: PainelSessao = Depends(sessao_do_dono), db: Session = Depends(get_db)):
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
    def historico(dias: int = Query(14, ge=1, le=90), sessao: PainelSessao = Depends(sessao_do_dono),
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
