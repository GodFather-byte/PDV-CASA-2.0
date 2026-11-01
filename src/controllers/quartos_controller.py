"""Controle de tempo dos quartos (módulo de operação usar_quartos).

O cliente paga antes, no caixa (venda normal pelo CaixaController); aqui só se conta o tempo. O tempo é vendido em
blocos (padrão 30 min) e o valor do bloco é só informativo na tela. O início fica gravado no banco e o restante é
calculado pelo relógio: fechar o PDV ou faltar luz não perde a contagem.

Situações de um quarto: 'livre', 'uso', 'alerta' (faltam `quartos_alerta_min` minutos) e 'estourou' (tempo acabou e o
quarto ainda não foi liberado). A campainha do quarto (ESP32 na rede local) é opcional: `quartos_campainhas` mapeia o
número do quarto ao endereço do aparelho.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroValidacao

MAX_BLOCOS = 24          # 12 h com o bloco de 30 min
MAX_QUARTOS = 50


def ler_campainhas(texto: str | None) -> dict[int, str]:
    """'1=192.168.0.51; 2=192.168.0.52' -> {1: '192.168.0.51', 2: '192.168.0.52'}. Vazio: sem campainhas."""
    mapa: dict[int, str] = {}
    for parte in (texto or "").replace("\n", ";").replace(",", ";").split(";"):
        parte = parte.strip()
        if not parte:
            continue
        if "=" not in parte:
            raise ErroValidacao(f"Campainha '{parte}': use quarto=endereço (ex.: 1=192.168.0.51).",
                                {"quartos_campainhas": "inválido"})
        num, endereco = (p.strip() for p in parte.split("=", 1))
        if not num.isdigit() or not 1 <= int(num) <= MAX_QUARTOS:
            raise ErroValidacao(f"Campainha '{parte}': o quarto deve ser um número de 1 a {MAX_QUARTOS}.",
                                {"quartos_campainhas": "inválido"})
        if not endereco or any(c in endereco for c in " /?#@"):
            raise ErroValidacao(f"Campainha '{parte}': endereço inválido (ex.: 192.168.0.51).",
                                {"quartos_campainhas": "inválido"})
        mapa[int(num)] = endereco
    return mapa


def fmt_duracao(minutos: int) -> str:
    h, m = divmod(int(minutos), 60)
    if h and m:
        return f"{h}h{m:02d}"
    return f"{h}h" if h else f"{m} min"


def fmt_relogio(segundos: float) -> str:
    s = int(abs(segundos))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _dt(iso: str) -> datetime:
    return datetime.strptime(iso[:19], "%Y-%m-%d %H:%M:%S")


class QuartosController:
    def __init__(self, banco, operador_id: int | None = None):
        self.banco = banco
        self.operador_id = operador_id

    # ------------------------------------------------------------ configuração
    def ligado(self) -> bool:
        return self.banco.cfg_bool("usar_quartos", False)

    def config(self) -> dict:
        b = self.banco
        try:
            valor = fmt.para_centavos(b.cfg("quartos_valor_bloco", "90") or 0)
        except ValueError:
            valor = 0
        return {
            "quartos": max(1, min(MAX_QUARTOS, b.cfg_int("quartos_qtd", 7))),
            "minutos_bloco": max(1, b.cfg_int("quartos_minutos_bloco", 30)),
            "valor_bloco_cent": valor,
            "alerta_min": max(0, b.cfg_int("quartos_alerta_min", 5)),
        }

    def campainhas(self) -> dict[int, str]:
        try:
            return ler_campainhas(self.banco.cfg("quartos_campainhas", ""))
        except ErroValidacao:
            return {}

    def rotulo_blocos(self, blocos: int) -> str:
        """'1h30 — R$ 270,00' para mostrar na escolha do tempo."""
        c = self.config()
        return f"{fmt_duracao(blocos * c['minutos_bloco'])}  —  {fmt.fmt_brl(blocos * c['valor_bloco_cent'])}"

    # ---------------------------------------------------------------- operação
    def _exigir_ligado(self) -> None:
        if not self.ligado():
            raise ErroNegocio("O módulo Quartos está desligado (Configurações > Módulos).")

    def _ativo(self, quarto: int):
        return self.banco.um("SELECT * FROM quartos_uso WHERE quarto = ? AND liberado_em IS NULL", (quarto,))

    def _validar(self, quarto: int, blocos: int) -> None:
        if not 1 <= int(quarto) <= self.config()["quartos"]:
            raise ErroValidacao("Quarto inexistente.", {"quarto": "inválido"})
        if not 1 <= int(blocos) <= MAX_BLOCOS:
            raise ErroValidacao(f"Escolha de 1 a {MAX_BLOCOS} blocos de tempo.", {"blocos": "inválido"})

    def iniciar(self, quarto: int, blocos: int) -> int:
        """Começa a contar o tempo do quarto (o cliente já pagou no caixa)."""
        self._exigir_ligado()
        self._validar(quarto, blocos)
        if self._ativo(quarto):
            raise ErroNegocio(f"O quarto {quarto} já está em uso. Libere antes de iniciar de novo.")
        c = self.config()
        with self.banco.transacao():
            uso_id = self.banco.inserir("quartos_uso", {
                "quarto": int(quarto), "inicio": fmt.agora(), "blocos": int(blocos),
                "minutos_bloco": c["minutos_bloco"], "valor_bloco_cent": c["valor_bloco_cent"],
                "operador_id": self.operador_id,
            })
        self.banco.log("quarto_iniciado", f"quarto {quarto}: {fmt_duracao(blocos * c['minutos_bloco'])}",
                       self.operador_id)
        return uso_id

    def adicionar_tempo(self, quarto: int, blocos: int) -> None:
        """O cliente pagou mais tempo: soma blocos ao que está contando (conta a partir do fim previsto)."""
        self._exigir_ligado()
        self._validar(quarto, blocos)
        uso = self._ativo(quarto)
        if uso is None:
            raise ErroNegocio(f"O quarto {quarto} está livre.")
        if uso["blocos"] + int(blocos) > MAX_BLOCOS:
            raise ErroValidacao(f"O total passaria de {MAX_BLOCOS} blocos.", {"blocos": "inválido"})
        self.banco.executar("UPDATE quartos_uso SET blocos = blocos + ? WHERE id = ?", (int(blocos), uso["id"]))
        self.banco.log("quarto_mais_tempo", f"quarto {quarto}: +{blocos} bloco(s)", self.operador_id)

    def liberar(self, quarto: int) -> dict:
        """Encerra o uso; guarda quanto passou do tempo (0 se saiu dentro do tempo)."""
        self._exigir_ligado()
        uso = self._ativo(quarto)
        if uso is None:
            raise ErroNegocio(f"O quarto {quarto} já está livre.")
        agora = fmt.agora_dt()
        fim = _dt(uso["inicio"]) + timedelta(minutes=uso["blocos"] * uso["minutos_bloco"])
        excedeu = max(0, int((agora - fim).total_seconds()))
        self.banco.executar(
            "UPDATE quartos_uso SET liberado_em = ?, liberado_por = ?, excedeu_seg = ? WHERE id = ?",
            (fmt.agora(), self.operador_id, excedeu, uso["id"]))
        self.banco.log("quarto_liberado", f"quarto {quarto}" + (f", passou {fmt_relogio(excedeu)}" if excedeu else ""),
                       self.operador_id)
        return {"quarto": quarto, "excedeu_seg": excedeu}

    # ------------------------------------------------------------------ painel
    def situacao(self) -> list[dict]:
        """Um item por quarto, na ordem, com o estado e o tempo restante (negativo = passou do tempo)."""
        c = self.config()
        agora = fmt.agora_dt()
        ativos = {r["quarto"]: r for r in self.banco.todos(
            "SELECT * FROM quartos_uso WHERE liberado_em IS NULL")}
        lista = []
        for n in range(1, c["quartos"] + 1):
            uso = ativos.get(n)
            if uso is None:
                lista.append({"quarto": n, "estado": "livre", "uso_id": None})
                continue
            inicio = _dt(uso["inicio"])
            minutos = uso["blocos"] * uso["minutos_bloco"]
            fim = inicio + timedelta(minutes=minutos)
            restante = (fim - agora).total_seconds()
            if restante <= 0:
                estado = "estourou"
            elif restante <= c["alerta_min"] * 60:
                estado = "alerta"
            else:
                estado = "uso"
            lista.append({
                "quarto": n, "estado": estado, "uso_id": uso["id"], "inicio": inicio, "fim": fim,
                "blocos": uso["blocos"], "minutos": minutos, "restante_seg": restante,
                "valor_cent": uso["blocos"] * uso["valor_bloco_cent"],
            })
        # Quarto em uso acima do número configurado (o dono diminuiu a quantidade): continua visível até ser liberado.
        for n in sorted(q for q in ativos if q > c["quartos"]):
            uso = ativos[n]
            fim = _dt(uso["inicio"]) + timedelta(minutes=uso["blocos"] * uso["minutos_bloco"])
            restante = (fim - agora).total_seconds()
            lista.append({
                "quarto": n, "estado": "estourou" if restante <= 0 else "uso", "uso_id": uso["id"],
                "inicio": _dt(uso["inicio"]), "fim": fim, "blocos": uso["blocos"],
                "minutos": uso["blocos"] * uso["minutos_bloco"], "restante_seg": restante,
                "valor_cent": uso["blocos"] * uso["valor_bloco_cent"],
            })
        return lista

    def resumo_noite(self) -> dict:
        """Usos que começaram na noite atual (o dia vira em `virada_dia_hora`, como no painel)."""
        virada = self.banco.cfg_int("virada_dia_hora", 6)
        ini, fim = fmt.faixa_dia_operacional(fmt.dia_operacional(virada=virada), virada)
        r = self.banco.um(
            "SELECT COUNT(*) AS usos, COALESCE(SUM(blocos * minutos_bloco), 0) AS minutos, "
            "COALESCE(SUM(blocos * valor_bloco_cent), 0) AS valor_cent, "
            "COALESCE(SUM(CASE WHEN excedeu_seg > 0 THEN 1 ELSE 0 END), 0) AS estouros "
            "FROM quartos_uso WHERE inicio >= ? AND inicio < ?", (ini, fim))
        return dict(r)
