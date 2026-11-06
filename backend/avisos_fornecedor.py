"""Resumo diário ao fornecedor: lojas com licença vencendo em até 7 dias ou vencida há até 30 dias.

Sai por e-mail (Brevo ou SMTP, os mesmos da cobrança) para PDV_AVISOS_EMAIL, ou para EMAIL_FROM quando ela não existe.
No máximo um envio por dia (tabela `fornecedor_avisos`). No Render grátis o servidor dorme, então não há horário fixo:
o envio é tentado na varredura do Mercado Pago, quando o fornecedor abre a central e quando um caixa consulta a licença.
Nada aqui bloqueia a resposta ao caixa: falha de e-mail fica no log e tenta de novo no próximo gatilho.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime

from sqlalchemy import Column, Integer, String

from backend.database import Base

log = logging.getLogger("pdv.nuvem")

DIAS_ANTES = 7
DIAS_DEPOIS = 30
_trava = threading.Lock()
_ultimo_dia_verificado: str | None = None     # evita ir ao banco a cada consulta de caixa


class AvisoFornecedor(Base):
    __tablename__ = "fornecedor_avisos"
    dia = Column(String(10), primary_key=True)
    enviado_em = Column(String(19), nullable=False)
    destino = Column(String(200), nullable=False)
    lojas = Column(Integer, nullable=False)


def destino() -> str:
    return (os.environ.get("PDV_AVISOS_EMAIL") or os.environ.get("EMAIL_FROM") or "").strip()


def vencimentos(db, hoje: date | None = None) -> list[dict]:
    """Lojas ativas vencendo em até 7 dias ou vencidas há até 30, da mais urgente para a menos."""
    from backend import ponte
    from backend.main import Loja
    hoje = hoje or date.today()
    ultimas: dict[str, str] = {}
    for p in db.query(ponte.PonteLicenca).order_by(ponte.PonteLicenca.expira_em, ponte.PonteLicenca.seq):
        ultimas[p.chave_loja] = p.expira_em
    modos = {p.chave_loja for p in db.query(ponte.PonteLoja).filter_by(modo_ponte=True)}
    saida = []
    for loja in db.query(Loja).filter_by(ativa=True).order_by(Loja.chave_loja):
        validade = ultimas.get(loja.chave_loja) if loja.chave_loja in modos else loja.licenca_ate
        if not validade:
            continue
        try:
            dias = (date.fromisoformat(validade[:10]) - hoje).days
        except ValueError:
            continue
        if -DIAS_DEPOIS <= dias <= DIAS_ANTES:
            saida.append({"chave": loja.chave_loja, "nome": loja.nome, "validade": validade[:10], "dias": dias})
    return sorted(saida, key=lambda l: (l["dias"], l["chave"]))


def texto(lojas: list[dict], hoje: date) -> tuple[str, str]:
    def situacao(l):
        if l["dias"] < 0:
            return f"VENCIDA há {-l['dias']} dia(s)"
        if l["dias"] == 0:
            return "vence HOJE"
        return f"vence em {l['dias']} dia(s)"
    assunto = f"WillPDV: {len(lojas)} licença(s) vencendo ou vencida(s) — {hoje.strftime('%d/%m/%Y')}"
    linhas = ["Resumo das licenças das suas lojas (central do fornecedor):", ""]
    linhas += [f"- {l['nome']} ({l['chave']}): {situacao(l)}, validade {l['validade'][8:10]}/{l['validade'][5:7]}/"
               f"{l['validade'][:4]}" for l in lojas]
    linhas += ["", "Confira pagamentos e renove na central: abra o endereço da nuvem + /central/.",
               "Este aviso sai no máximo uma vez por dia."]
    return assunto, "\n".join(linhas)


def enviar_se_preciso(db, hoje: date | None = None, forcar: bool = False, enviar=None) -> dict:
    """Envia o resumo de hoje se ainda não saiu. Devolve {"enviado", "lojas", "motivo"}."""
    global _ultimo_dia_verificado
    hoje = hoje or date.today()
    dia = hoje.isoformat()
    if not forcar and db.get(AvisoFornecedor, dia) is not None:
        _ultimo_dia_verificado = dia
        return {"enviado": False, "lojas": 0, "motivo": "Resumo de hoje já enviado."}
    lojas = vencimentos(db, hoje)
    para = destino()
    if not lojas:
        _ultimo_dia_verificado = dia
        return {"enviado": False, "lojas": 0, "motivo": "Nenhuma loja vencendo."}
    if not para:
        return {"enviado": False, "lojas": len(lojas), "motivo": "Defina PDV_AVISOS_EMAIL (ou EMAIL_FROM) no servidor."}
    if enviar is None:
        from backend.cobranca_mercadopago import enviar_email as enviar
    assunto, corpo = texto(lojas, hoje)
    try:
        enviar(para, assunto, corpo)
    except Exception as erro:  # noqa: BLE001 - e-mail fora do ar não pode derrubar quem chamou
        log.error("Resumo de vencimentos não enviado: %s", type(erro).__name__)
        return {"enviado": False, "lojas": len(lojas), "motivo": f"E-mail não enviado ({erro})."}
    linha = db.get(AvisoFornecedor, dia)
    if linha is None:
        db.add(AvisoFornecedor(dia=dia, enviado_em=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                               destino=para[:200], lojas=len(lojas)))
    db.commit()
    _ultimo_dia_verificado = dia
    return {"enviado": True, "lojas": len(lojas), "motivo": f"Resumo enviado para {para}."}


def disparar_em_segundo_plano() -> None:
    """Gatilho barato para rotas de caixa: no máximo uma ida ao banco por dia e por processo, fora da requisição."""
    hoje = date.today().isoformat()
    if not destino() or _ultimo_dia_verificado == hoje or not _trava.acquire(blocking=False):
        return

    def rodar():
        try:
            from backend.main import SessionLocal
            with SessionLocal() as db:
                enviar_se_preciso(db)
        except Exception:  # noqa: BLE001
            log.error("Resumo de vencimentos falhou (erro interno).")
        finally:
            _trava.release()

    threading.Thread(target=rodar, name="aviso-vencimentos", daemon=True).start()
