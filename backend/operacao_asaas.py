"""Inbox e agenda duráveis de cobrança; execute python -m backend.worker_asaas."""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import Column, Integer, String, func
from sqlalchemy.orm import Session

from backend import cobrancas
from backend.database import Base

log = logging.getLogger("pdv.asaas.operacao")
INTERVALO_CONCILIACAO = 6 * 60 * 60
ATRASO_ALERTA = 15 * 60
BATIDA_ALERTA = 5 * 60


class Tarefa(Base):
    """A própria linha é o inbox do evento ou a agenda recorrente da assinatura."""
    __tablename__ = "tarefas_asaas"
    id = Column(String, primary_key=True)
    tipo = Column(String, nullable=False, index=True)
    assinatura = Column(String, nullable=False)
    pagamento = Column(String, nullable=True)
    evento = Column(String, nullable=True)
    criada_em = Column(String, nullable=False)
    proxima_em = Column(String, nullable=False, index=True)
    estado = Column(String, nullable=False, index=True)
    tentativas = Column(Integer, nullable=False, default=0)
    falhas_seguidas = Column(Integer, nullable=False, default=0)
    ultima_inicio = Column(String, nullable=True)
    ultima_fim = Column(String, nullable=True)
    ultimo_sucesso = Column(String, nullable=True)
    ultimo_erro = Column(String, nullable=True)
    ultimo_erro_em = Column(String, nullable=True)


class Worker(Base):
    __tablename__ = "workers_asaas"
    id = Column(String, primary_key=True)
    batida_em = Column(String, nullable=False)


def instante() -> datetime:
    return datetime.now().replace(microsecond=0)


def texto(valor: datetime) -> str:
    return valor.strftime("%Y-%m-%d %H:%M:%S")


def _inserir(db: Session, registro) -> bool:
    # A PK resolve entregas e agendadores concorrentes, sem perder a transação externa.
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    valores = {coluna.name: getattr(registro, coluna.name)
               for coluna in registro.__table__.columns if getattr(registro, coluna.name) is not None}
    # INSERT não garante rowcount válido no psycopg/SQLAlchemy. RETURNING distingue
    # inclusão de conflito pela linha retornada, inclusive entre entregas concorrentes.
    resultado = db.execute(insert(type(registro)).values(**valores).on_conflict_do_nothing(
        index_elements=["id"]).returning(type(registro).id))
    return resultado.scalar_one_or_none() is not None


def receber(db: Session, evento: str, assinatura: str, pagamento: str, tipo: str) -> str:
    cobrancas.identificador(evento, "evt_")
    cobrancas.identificador(assinatura, "sub_")
    cobrancas.identificador(pagamento, "pay_")
    recebido = texto(instante())
    registro = db.get(Tarefa, "evento:" + evento)
    novo = False
    if registro is None:
        novo = _inserir(db, Tarefa(
            id="evento:" + evento, tipo="evento", assinatura=assinatura, pagamento=pagamento,
            evento=tipo, criada_em=recebido, proxima_em=recebido, estado="pendente"))
        registro = db.get(Tarefa, "evento:" + evento)
    if (registro.assinatura, registro.pagamento, registro.evento) != (assinatura, pagamento, tipo):
        raise cobrancas.ErroCobranca("Evento repetido com identificadores divergentes.")
    # Nunca responder sucesso antes de o inbox estar confirmado no banco.
    db.commit()
    return "enfileirado" if novo else "repetido"


def agendar(db: Session, agora: datetime) -> None:
    existentes = {tarefa_id for (tarefa_id,) in db.query(Tarefa.id).filter_by(tipo="conciliacao")}
    for assinatura in db.query(cobrancas.Assinatura).filter_by(ambiente=cobrancas.ambiente()):
        if "conciliar:" + assinatura.id in existentes:
            continue
        _inserir(db, Tarefa(
            id="conciliar:" + assinatura.id, tipo="conciliacao", assinatura=assinatura.id,
            criada_em=texto(agora), proxima_em=texto(agora), estado="pendente"))
    db.commit()


def _erro_seguro(erro: Exception) -> str:
    if isinstance(erro, cobrancas.ErroCobranca):
        return str(erro)[:500]
    # Exceções de banco/HTTP podem conter URL, SQL, credenciais ou dados pessoais.
    return f"Falha interna ({type(erro).__name__}); confira banco e configuração do servidor."


def _falhar(tarefa: Tarefa, erro: Exception, agora: datetime) -> None:
    tarefa.falhas_seguidas += 1
    espera = min(3600, 60 * 2 ** min(tarefa.falhas_seguidas - 1, 6))
    tarefa.estado = "erro"
    tarefa.ultima_fim = texto(agora)
    tarefa.ultimo_erro = _erro_seguro(erro)
    tarefa.ultimo_erro_em = texto(agora)
    tarefa.proxima_em = texto(agora + timedelta(seconds=espera))
    log.error("ALERTA_ASAAS tarefa=%s falhas=%s proxima=%s erro=%s",
              tarefa.id, tarefa.falhas_seguidas, tarefa.proxima_em, tarefa.ultimo_erro)


def executar_uma(db: Session, agora: datetime | None = None) -> bool:
    """Lock transacional, sem lease: morte do processo libera a tarefa para outro worker.

    PostgreSQL usa SKIP LOCKED. SQLite serve somente aos testes unitários/uso serial.
    Nenhum commit de licença/evento pode ocorrer antes da conclusão atômica do inbox.
    """
    agora = agora or instante()
    tarefa = (db.query(Tarefa).filter(Tarefa.estado != "concluida", Tarefa.proxima_em <= texto(agora))
              .order_by(Tarefa.proxima_em, Tarefa.id).with_for_update(skip_locked=True).first())
    if tarefa is None:
        db.rollback()
        return False
    tarefa_id = tarefa.id
    tentativa_anterior = tarefa.tentativas
    tarefa.tentativas += 1
    tarefa.ultima_inicio = texto(agora)
    try:
        # O savepoint permite persistir o erro mantendo o lock do inbox até o commit.
        with db.begin_nested():
            if tarefa.tipo == "evento":
                resultado = cobrancas.processar(
                    db, tarefa.assinatura, tarefa.pagamento,
                    tarefa.id.removeprefix("evento:"), confirmar=False)
                if resultado == "nao_vinculada":
                    raise cobrancas.ErroCobranca("Assinatura não vinculada; vincule-a antes de processar.")
                tarefa.estado = "concluida"
            else:
                assinatura = db.get(cobrancas.Assinatura, tarefa.assinatura)
                if assinatura is None:
                    raise cobrancas.ErroCobranca("Assinatura agendada não encontrada.")
                cobrancas.reconciliar(db, assinatura.chave_loja, confirmar=False)
                tarefa.estado = "pendente"
                tarefa.proxima_em = texto(agora + timedelta(seconds=INTERVALO_CONCILIACAO))
            tarefa.falhas_seguidas = 0
            tarefa.ultima_fim = tarefa.ultimo_sucesso = texto(instante())
    except Exception as erro:
        _falhar(tarefa, erro, instante())
    try:
        db.commit()
        log.info("Execução Asaas registrada: %s.", tarefa_id)
    except Exception as erro:
        db.rollback()
        # Falha de commit não pode confirmar evento/licença parcialmente. Se houve
        # resultado ambíguo de rede, não sobrescrever sucesso de outro processo.
        tarefa = db.query(Tarefa).filter_by(id=tarefa_id).with_for_update().one()
        if tarefa.tentativas == tentativa_anterior:
            tarefa.tentativas += 1
            tarefa.ultima_inicio = texto(agora)
            _falhar(tarefa, erro, instante())
            db.commit()
        else:
            db.rollback()
    return True


def batida(db: Session, agora: datetime) -> None:
    _inserir(db, Worker(id="principal", batida_em=texto(agora)))
    db.query(Worker).filter_by(id="principal").update({"batida_em": texto(agora)})
    db.commit()


def estado(db: Session, agora: datetime | None = None) -> dict:
    agora = agora or instante()
    fila = db.query(Tarefa).filter(Tarefa.tipo == "evento", Tarefa.estado != "concluida")
    pendentes = fila.count()
    mais_antiga = fila.with_entities(func.min(Tarefa.criada_em)).scalar()
    erros = db.query(Tarefa).filter(Tarefa.falhas_seguidas > 0)
    atrasadas = db.query(Tarefa).filter(
        Tarefa.estado != "concluida",
        Tarefa.proxima_em < texto(agora - timedelta(seconds=ATRASO_ALERTA))).count()
    assinaturas = db.query(cobrancas.Assinatura).filter_by(ambiente=cobrancas.ambiente()).all()
    agendas = {t.assinatura: t for t in db.query(Tarefa).filter_by(tipo="conciliacao")}
    sem_conciliacao = sum(
        1 for assinatura in assinaturas
        if assinatura.id not in agendas or not agendas[assinatura.id].ultimo_sucesso
        or agendas[assinatura.id].ultimo_sucesso <
        texto(agora - timedelta(seconds=INTERVALO_CONCILIACAO + ATRASO_ALERTA)))
    worker = db.get(Worker, "principal")
    worker_atrasado = (worker is None or
                       worker.batida_em < texto(agora - timedelta(seconds=BATIDA_ALERTA)))
    alertas = []
    if worker_atrasado:
        alertas.append("worker_sem_batida")
    if erros.count():
        alertas.append("tarefas_com_erro")
    if atrasadas or (mais_antiga and mais_antiga < texto(agora - timedelta(seconds=ATRASO_ALERTA))):
        alertas.append("fila_atrasada")
    if sem_conciliacao:
        alertas.append("conciliacao_atrasada")
    recentes = db.query(Tarefa).order_by(Tarefa.ultima_fim.desc(), Tarefa.criada_em.desc()).limit(50)
    pendencias = db.query(Tarefa).filter(
        Tarefa.estado != "concluida",
        (Tarefa.tipo == "evento") | (Tarefa.proxima_em <= texto(agora)))
    return {
        "pronto": not alertas, "alertas": alertas, "consultado_em": texto(agora),
        "worker_batida_em": worker.batida_em if worker else None,
        "eventos_pendentes": pendentes, "evento_mais_antigo_em": mais_antiga,
        "tarefas_com_erro": erros.count(), "tarefas_atrasadas": atrasadas,
        "assinaturas_sem_conciliacao_recente": sem_conciliacao,
        "ultimas_execucoes": [
            {campo: getattr(t, campo) for campo in (
                "id", "tipo", "assinatura", "estado", "tentativas", "falhas_seguidas",
                "proxima_em", "ultima_inicio", "ultima_fim", "ultimo_sucesso",
                "ultimo_erro", "ultimo_erro_em")} for t in recentes],
        "falhas": [{"id": t.id, "erro": t.ultimo_erro, "em": t.ultimo_erro_em,
                    "proxima_em": t.proxima_em} for t in
                   erros.order_by(Tarefa.ultimo_erro_em.desc()).limit(50)],
        "pendencias": [{"id": t.id, "tipo": t.tipo, "estado": t.estado,
                        "criada_em": t.criada_em, "proxima_em": t.proxima_em} for t in
                       pendencias.order_by(Tarefa.proxima_em, Tarefa.id).limit(50)],
    }


def ciclo(fabrica, limite: int = 100) -> int:
    with fabrica() as db:
        agendar(db, instante())
        batida(db, instante())
    quantidade = 0
    for _ in range(limite):
        with fabrica() as db:
            if not executar_uma(db):
                break
        quantidade += 1
        with fabrica() as db:
            batida(db, instante())
    with fabrica() as db:
        indicadores = estado(db)
        if indicadores["alertas"]:
            log.warning("ALERTA_ASAAS_OPERACAO alertas=%s pendentes=%s erros=%s",
                        ",".join(indicadores["alertas"]), indicadores["eventos_pendentes"],
                        indicadores["tarefas_com_erro"])
    return quantidade


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uma-vez", action="store_true", help="Executar um lote e sair (agendador externo).")
    parser.add_argument("--limite", type=int, default=100)
    parser.add_argument("--pausa", type=int, default=5)
    args = parser.parse_args(argv)
    if args.limite < 1 or args.pausa < 1:
        parser.error("Limite e pausa devem ser positivos.")
    logging.basicConfig(level=logging.INFO)
    from backend.main import SessionLocal
    while True:
        try:
            ciclo(SessionLocal, args.limite)
        except Exception as erro:
            log.error("ALERTA_ASAAS_WORKER %s", _erro_seguro(erro))
            if args.uma_vez:
                return 1
        if args.uma_vez:
            with SessionLocal() as db:
                return 0 if estado(db)["pronto"] else 1
        time.sleep(args.pausa)
