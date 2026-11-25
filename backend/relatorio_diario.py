"""Relatório diário de vendas por e-mail: todo dia, a partir das 08:00 (horário de Brasília), cada loja com o envio
ligado recebe o relatório do dia operacional anterior, com tudo explicado.

O dono liga e põe os e-mails no painel (aba Relatórios). Não há worker separado no Render grátis: qualquer requisição
à nuvem chama `disparar_em_segundo_plano()`, que só olha a memória e, depois das 08:00, roda o envio numa linha de
execução à parte. Um agendamento do GitHub também faz uma chamada às 08:00 para acordar o servidor se nenhum caixa
estiver ligado. Cada loja só recebe uma vez por dia: a linha é reservada no banco antes do envio (vale com mais de um
processo) e volta a ficar pendente se o e-mail falhar.

Os números saem das vendas que o caixa já manda ao painel (as mesmas da aba Hoje) e do último retrato de cada caixa
(fechamentos de caixa, sangrias, comissões e estoque).
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Boolean, Column, String, update
from sqlalchemy.orm import Session

from backend.database import Base

log = logging.getLogger("pdv.relatorio_diario")

HORA_ENVIO = 8
LIMITE_EMAILS = 3
ESPERA_NOVA_TENTATIVA_SEG = 30 * 60
EMAIL_RE = re.compile(r"^[^@\s,;<>]{1,64}@[^@\s,;<>]{1,190}\.[A-Za-z]{2,24}$")
DIAS_SEMANA = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")


class RelatorioDiario(Base):
    __tablename__ = "relatorios_diarios"
    chave_loja = Column(String, primary_key=True)
    emails = Column(String(300), nullable=False, default="")
    ativo = Column(Boolean, nullable=False, default=False)
    ultimo_dia = Column(String(10), nullable=True)            # dia do último relatório enviado (ou reservado)
    ultimo_status = Column(String(200), nullable=False, default="")
    atualizado_em = Column(String(19), nullable=False, default="")


# ---------------------------------------------------------------- horário de Brasília
def agora_brasilia() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Sao_Paulo"))
    except Exception:                                     # noqa: BLE001 - sem base de fusos: Brasília é UTC-3
        return datetime.now(timezone(timedelta(hours=-3)))


def dia_do_relatorio(agora: datetime | None = None) -> str | None:
    """O dia que deve ser mandado agora: o de ontem, a partir das 08:00. Antes disso, nada."""
    agora = agora or agora_brasilia()
    if agora.hour < HORA_ENVIO:
        return None
    return (agora.date() - timedelta(days=1)).isoformat()


# ---------------------------------------------------------------- configuração da loja
def limpar_emails(texto: str) -> list[str]:
    emails = []
    for parte in re.split(r"[,;\s]+", texto or ""):
        parte = parte.strip().lower()
        if not parte:
            continue
        if not EMAIL_RE.fullmatch(parte):
            raise ValueError(f"E-mail inválido: {parte[:60]}")
        if parte not in emails:
            emails.append(parte)
    if len(emails) > LIMITE_EMAILS:
        raise ValueError(f"Use no máximo {LIMITE_EMAILS} e-mails.")
    return emails


def config(db: Session, chave_loja: str) -> dict:
    linha = db.get(RelatorioDiario, chave_loja)
    from backend.cobranca_mercadopago import brevo_configurado, smtp_configurado
    return {"emails": (linha.emails if linha else "").split(",") if linha and linha.emails else [],
            "ativo": bool(linha.ativo) if linha else False, "ultimo_dia": linha.ultimo_dia if linha else None,
            "ultimo_status": linha.ultimo_status if linha else "", "hora": f"{HORA_ENVIO:02d}:00",
            "email_configurado": brevo_configurado() or smtp_configurado()}


def salvar(db: Session, chave_loja: str, emails_texto: str, ativo: bool) -> dict:
    emails = limpar_emails(emails_texto)
    if ativo and not emails:
        raise ValueError("Informe pelo menos um e-mail para ligar o relatório.")
    linha = db.get(RelatorioDiario, chave_loja)
    if linha is None:
        linha = RelatorioDiario(chave_loja=chave_loja)
        db.add(linha)
        # Ligado hoje depois das 08:00: o relatório de ontem não sai sozinho (use "Enviar agora"), o de amanhã sim.
        linha.ultimo_dia = dia_do_relatorio()
    linha.emails = ",".join(emails)
    linha.ativo = bool(ativo)
    linha.atualizado_em = agora_brasilia().strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    return config(db, chave_loja)


# ---------------------------------------------------------------- o relatório
def _dinheiro(cent: int) -> str:
    valor = f"{abs(int(cent)) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if cent < 0 else "R$ ") + valor


def _qtd(valor) -> str:
    numero = float(valor or 0)
    return str(int(numero)) if numero == int(numero) else f"{numero:.3f}".rstrip("0").replace(".", ",")


def _custo(vendas: list[dict]) -> tuple[int, bool]:
    """Custo dos produtos vendidos (CMV) com o que o caixa mandou; False se algum item veio sem custo."""
    total, completo = 0, True
    for v in vendas:
        if v.get("status") != "fechada":
            continue
        for i in v.get("itens") or []:
            if i.get("cancelado"):
                continue
            if i.get("custo_linha_cent") is None:
                completo = False
                continue
            total += int(i.get("custo_linha_cent") or 0)
    return total, completo


def montar(db: Session, chave_loja: str, dia: str) -> tuple[str, str]:
    """(assunto, corpo) do relatório de `dia` para a loja. Texto simples, que todo e-mail abre bem no celular."""
    from backend import painel
    from backend import painel_devolucoes as devolucoes
    from backend.main import Loja
    loja = db.query(Loja).filter(Loja.chave_loja == chave_loja).first()
    nome = (loja.nome if loja is not None else "") or chave_loja
    data = date.fromisoformat(dia)
    vendas = painel._vendas_do_dia(db, chave_loja, dia)
    r = painel.resumo_do_dia(vendas)
    v = r["vendas"]
    devol = devolucoes.resumo(db, chave_loja, dia, dia)
    anterior = painel.resumo_do_dia(painel._vendas_do_dia(db, chave_loja, (data - timedelta(days=7)).isoformat()))
    custo, custo_completo = _custo(vendas)
    liquido = v["faturamento_cent"] - devol["valor_cent"]
    linhas: list[str] = []
    add = linhas.append
    secao = iter(range(1, 20))

    def titulo(texto: str) -> None:
        add(f"{next(secao)}) {texto}")
    add(f"RELATÓRIO DE VENDAS — {nome}")
    add(f"{DIAS_SEMANA[data.weekday()]}, {data.strftime('%d/%m/%Y')} (dia operacional: a madrugada conta no dia em "
        "que a noite começou)")
    add("")
    titulo("RESUMO DO DIA")
    add(f"Faturamento: {_dinheiro(v['faturamento_cent'])} em {v['quantidade']} venda(s).")
    ant = anterior["vendas"]["faturamento_cent"]
    if ant:
        pct = (v["faturamento_cent"] - ant) * 100 / ant
        add(f"   Comparado com o mesmo dia da semana passada ({_dinheiro(ant)}): "
            f"{abs(pct):.0f}% {'a mais' if pct >= 0 else 'a menos'}.")
    else:
        add("   Sem vendas no mesmo dia da semana passada para comparar.")
    add(f"Ticket médio: {_dinheiro(v['ticket_medio_cent'])} (quanto cada venda deixou, em média).")
    unidades = sum(float(p.get("quantidade") or 0) for p in r["produtos"])
    add(f"Unidades vendidas (produtos mais vendidos): {_qtd(unidades)}.")
    if devol["valor_cent"]:
        add(f"Devoluções: {_dinheiro(devol['valor_cent'])}. Faturamento líquido: {_dinheiro(liquido)}.")
    if v["desconto_cent"]:
        add(f"Descontos dados: {_dinheiro(v['desconto_cent'])} (já descontados do faturamento).")
    if r.get("atacado_economia_cent"):
        add(f"Preço de atacado/promoção: os clientes economizaram {_dinheiro(r['atacado_economia_cent'])}.")
    if v["canceladas"]:
        add(f"Vendas canceladas: {v['canceladas']} ({_dinheiro(v['canceladas_cent'])}). Confira o motivo de cada uma "
            "no painel, aba Vendas.")
    if custo and v["faturamento_cent"]:
        lucro = v["faturamento_cent"] - custo
        add(f"Custo dos produtos vendidos: {_dinheiro(custo)}. Lucro bruto: {_dinheiro(lucro)} "
            f"({lucro * 100 / v['faturamento_cent']:.0f}% de margem)"
            + ("" if custo_completo else ". Atenção: há produtos sem custo cadastrado, o lucro real é menor") + ".")
    elif v["faturamento_cent"]:
        add("Lucro: sem custo cadastrado nos produtos vendidos. Cadastre o preço de custo para ver o lucro aqui.")
    add("")
    titulo("COMO FOI PAGO")
    if r["formas"]:
        for f in r["formas"]:
            parte = f["valor_cent"] * 100 / v["faturamento_cent"] if v["faturamento_cent"] else 0
            add(f"- {f['tipo']}: {_dinheiro(f['valor_cent'])} ({parte:.0f}%)")
        add("   O dinheiro em espécie é o que deve estar na gaveta (menos troco inicial e sangrias).")
    else:
        add("Nenhum pagamento no dia.")
    add("")
    titulo("PRODUTOS QUE MAIS VENDERAM")
    if r["produtos"]:
        for i, p in enumerate(r["produtos"][:10], start=1):
            add(f"{i:>2}. {p['nome']} — {_qtd(p['quantidade'])} un. — {_dinheiro(p['valor_cent'])}")
    else:
        add("Nenhum produto vendido.")
    if r["por_hora"]:
        pico = max(r["por_hora"], key=lambda h: h["valor_cent"])
        add(f"   Horário mais forte: {pico['hora']}h ({_dinheiro(pico['valor_cent'])} em {pico['quantidade']} venda(s)).")
    add("")
    pares = painel._ler_caixas(db, chave_loja)
    fechamentos, sangrias, acertos, estoque = [], [], [], {}
    for linha, dados in pares:
        fechamentos += [f for f in (painel._fechamentos_publicos(dados) or []) if f["dia"] == dia]
        sangrias += [s for s in (painel._sangrias_publicas(dados) or []) if s["dia"] == dia]
        bloco = painel._comissoes_publicas(dados) or {}
        acertos += [a for a in (bloco.get("acertos") or []) if a.get("dia") == dia]
        if isinstance(dados.get("estoque"), dict) and not estoque:
            estoque = dados["estoque"]
    titulo("CAIXA (FECHAMENTOS E SANGRIAS)")
    if fechamentos:
        for f in fechamentos:
            diferenca = f["resultado_cent"]
            situacao = ("bateu certinho" if diferenca == 0 else
                        f"SOBROU {_dinheiro(diferenca)}" if diferenca > 0 else f"FALTOU {_dinheiro(-diferenca)}")
            add(f"- Turno {f['turno_numero']} ({f['operador'] or 'sem operador'}): esperado {_dinheiro(f['esperado_cent'])}, "
                f"contado {_dinheiro(f['valor_final_cent'])} — {situacao}.")
        add("   'Esperado' é o que o sistema calcula que deveria ter na gaveta; 'contado' é o que o operador contou.")
    else:
        add("Nenhum turno fechado neste dia (ou o caixa ainda não mandou o fechamento).")
    if sangrias:
        total = sum(s["valor_cent"] for s in sangrias)
        add(f"Sangrias (dinheiro retirado da gaveta): {len(sangrias)}, total {_dinheiro(total)}.")
        for s in sangrias[:10]:
            add(f"   - {_dinheiro(s['valor_cent'])} {('— ' + s['descricao']) if s['descricao'] else ''}"
                f"{(' (' + s['operador'] + ')') if s['operador'] else ''}")
    add("")
    if acertos:
        por_garota: dict[str, int] = defaultdict(int)
        for a in acertos:
            por_garota[f"{a['garota']} {a.get('nome') or ''}".strip()] += a["total_cent"]
        titulo("GAROTAS (COMISSÕES PAGAS)")
        add(f"Pago no dia: {_dinheiro(sum(a['dinheiro_cent'] + a['pix_cent'] for a in acertos))} "
            f"(dinheiro {_dinheiro(sum(a['dinheiro_cent'] for a in acertos))}, "
            f"Pix {_dinheiro(sum(a['pix_cent'] for a in acertos))}).")
        for quem, total in sorted(por_garota.items(), key=lambda kv: -kv[1])[:15]:
            add(f"   - {quem}: {_dinheiro(total)}")
        add("")
    titulo("ESTOQUE (AGORA)")
    abaixo = estoque.get("abaixo_minimo") or []
    if estoque:
        add(f"Produtos zerados: {estoque.get('zerados', 0)}. No mínimo ou abaixo: "
            f"{estoque.get('abaixo_minimo_total', len(abaixo))}.")
        for p in abaixo[:15]:
            add(f"   - {p.get('nome')}: {_qtd(p.get('qt_atual'))} {p.get('unidade') or ''} "
                f"(mínimo {_qtd(p.get('estoque_minimo'))})")
        if abaixo:
            add("   Estes são os produtos para repor primeiro.")
    else:
        add("O caixa ainda não mandou o estoque.")
    add("")
    atencao = []
    if v["canceladas"]:
        atencao.append(f"{v['canceladas']} venda(s) cancelada(s)")
    if any(f["resultado_cent"] < 0 for f in fechamentos):
        atencao.append("faltou dinheiro no fechamento de caixa")
    if v["faturamento_cent"] and v["desconto_cent"] * 10 > v["faturamento_cent"]:
        atencao.append("descontos acima de 10% do faturamento")
    if not vendas:
        atencao.append("nenhuma venda chegou: confira se o caixa abriu e está ligado à internet")
    add("PONTOS DE ATENÇÃO: " + ("; ".join(atencao) + "." if atencao else "nada fora do normal."))
    add("")
    add("Detalhes de cada venda: abra o painel do dono (aba Vendas).")
    add("Relatório automático do WillPDV · WB Sistemas. Para parar de receber, desligue no painel, aba Relatórios.")
    assunto = f"{nome}: vendas de {data.strftime('%d/%m')} — {_dinheiro(v['faturamento_cent'])}"
    return assunto[:150], "\n".join(linhas)


# ---------------------------------------------------------------- envio
_envios_manuais: dict[str, list[float]] = {}


def pode_enviar_agora(chave_loja: str, limite: int = 3, janela_seg: int = 3600) -> bool:
    """O botão "Enviar agora" vale no máximo `limite` vezes por hora por loja (é e-mail de verdade)."""
    agora = time.monotonic()
    with _trava_manual:
        vez = [t for t in _envios_manuais.get(chave_loja, []) if agora - t < janela_seg]
        if len(vez) >= limite:
            _envios_manuais[chave_loja] = vez
            return False
        vez.append(agora)
        _envios_manuais[chave_loja] = vez
        return True


_trava_manual = threading.Lock()


def enviar_para(db: Session, chave_loja: str, dia: str, emails: list[str], enviar=None) -> str:
    from backend.cobranca_mercadopago import enviar_email
    assunto, corpo = montar(db, chave_loja, dia)
    for email in emails:
        (enviar or enviar_email)(email, assunto, corpo)
    return f"Enviado em {agora_brasilia().strftime('%d/%m %H:%M')} para {len(emails)} e-mail(s)."


def enviar_pendentes(db: Session, dia: str | None = None, enviar=None) -> dict:
    """Manda o relatório de `dia` para cada loja ligada que ainda não recebeu. Reserva a linha antes (sem duplicar com
    outro processo) e devolve a reserva se o e-mail falhar, para a próxima tentativa."""
    dia = dia or dia_do_relatorio()
    if dia is None:
        return {"enviados": 0, "falhas": 0}
    enviados = falhas = 0
    candidatos = db.query(RelatorioDiario).filter(RelatorioDiario.ativo.is_(True)).all()
    for linha in candidatos:
        if linha.ultimo_dia == dia or not linha.emails:
            continue
        anterior = linha.ultimo_dia
        reservado = db.execute(update(RelatorioDiario)
                               .where(RelatorioDiario.chave_loja == linha.chave_loja,
                                      RelatorioDiario.ultimo_dia.is_(None) if anterior is None
                                      else RelatorioDiario.ultimo_dia == anterior)
                               .values(ultimo_dia=dia)).rowcount
        db.commit()
        if reservado != 1:
            continue                                      # outro processo pegou esta loja
        try:
            status = enviar_para(db, linha.chave_loja, dia, linha.emails.split(","), enviar)
            enviados += 1
        except Exception as erro:                         # noqa: BLE001 - uma loja com problema não para as outras
            log.error("Relatório diário de %s não enviado: %s", linha.chave_loja, type(erro).__name__)
            db.rollback()
            db.execute(update(RelatorioDiario).where(RelatorioDiario.chave_loja == linha.chave_loja)
                       .values(ultimo_dia=anterior))
            status = f"Falhou em {agora_brasilia().strftime('%d/%m %H:%M')}: {str(erro)[:120]}"
            falhas += 1
        db.execute(update(RelatorioDiario).where(RelatorioDiario.chave_loja == linha.chave_loja)
                   .values(ultimo_status=status[:200]))
        db.commit()
    return {"enviados": enviados, "falhas": falhas}


_trava = threading.Lock()
_feito: str | None = None                                 # dia cujo envio já terminou sem falhas neste processo
_proxima_tentativa = 0.0


def disparar_em_segundo_plano(agora: datetime | None = None) -> bool:
    """Chamado em toda requisição: só memória. Depois das 08:00, roda o envio uma vez por dia neste processo (e de novo
    em 30 min se alguma loja falhou). Devolve True se disparou."""
    global _proxima_tentativa
    dia = dia_do_relatorio(agora)
    if dia is None or _feito == dia or time.monotonic() < _proxima_tentativa or not _trava.acquire(blocking=False):
        return False

    def rodar():
        global _feito, _proxima_tentativa
        try:
            from backend.main import SessionLocal
            with SessionLocal() as db:
                resultado = enviar_pendentes(db, dia)
            if resultado["falhas"]:
                _proxima_tentativa = time.monotonic() + ESPERA_NOVA_TENTATIVA_SEG
            else:
                _feito = dia
        except Exception:                                 # noqa: BLE001
            log.error("Relatório diário falhou (erro interno).")
            _proxima_tentativa = time.monotonic() + ESPERA_NOVA_TENTATIVA_SEG
        finally:
            _trava.release()

    threading.Thread(target=rodar, name="relatorio-diario", daemon=True).start()
    return True
