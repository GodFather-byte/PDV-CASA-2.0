"""Conversão e formatação de dinheiro, quantidades e datas.

Convenções do sistema inteiro:
  * Dinheiro é sempre INTEIRO em centavos (R$ 3,50 -> 350). Nunca float.
  * Quantidades são float arredondado a 4 casas (kg, litros...).
  * Datas/horas são gravadas como texto ISO local: 'YYYY-MM-DD HH:MM:SS'.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CASAS_QTD = 4

# ---------------------------------------------------------------- relógio
_relogio = datetime.now  # testes podem trocar por uma função fixa


def definir_relogio(funcao) -> None:
    global _relogio
    _relogio = funcao or datetime.now


def agora_dt() -> datetime:
    return _relogio().replace(microsecond=0)


def agora() -> str:
    return agora_dt().strftime("%Y-%m-%d %H:%M:%S")


def hoje() -> str:
    return agora_dt().strftime("%Y-%m-%d")


# ---------------------------------------------------------------- dinheiro
def _dec(valor) -> Decimal:
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))


def arredondar(valor: Decimal) -> int:
    """Arredonda para inteiro com meio-para-cima (regra comercial)."""
    return int(valor.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def para_centavos(texto) -> int:
    """'1.234,56' | '12,5' | '8.00' | 8 | 8.5 -> centavos.

    Com vírgula, a vírgula é o separador decimal e os pontos são milhares.
    Sem vírgula, o ponto é o separador decimal.
    """
    if texto is None:
        return 0
    if isinstance(texto, bool):
        raise ValueError("valor inválido")
    if isinstance(texto, int):
        return texto * 100
    if isinstance(texto, (float, Decimal)):
        return arredondar(_dec(texto) * 100)
    s = str(texto).strip().replace("R$", "").replace(" ", "")
    if not s:
        return 0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return arredondar(Decimal(s) * 100)
    except InvalidOperation:
        raise ValueError(f"valor monetário inválido: {texto!r}") from None


def fmt_num(cent: int | None) -> str:
    """12345 -> '123,45' (com milhar: '1.234,56')."""
    cent = int(cent or 0)
    sinal = "-" if cent < 0 else ""
    reais, centavos = divmod(abs(cent), 100)
    return f"{sinal}{reais:,}".replace(",", ".") + f",{centavos:02d}"


def fmt_brl(cent: int | None) -> str:
    cent = int(cent or 0)
    return ("-R$ " if cent < 0 else "R$ ") + fmt_num(abs(cent))


def pct_de(cent: int, pct) -> int:
    """pct% de um valor em centavos, arredondado."""
    return arredondar(_dec(cent) * _dec(pct) / 100)


def dividir_cent(total_cent: int, qtd) -> int:
    """Valor unitário em centavos = total / quantidade (0 se a quantidade for 0)."""
    return arredondar(_dec(total_cent) / _dec(qtd)) if qtd else 0


def mult_cent(preco_cent: int, qtd) -> int:
    """Preço unitário (centavos) x quantidade (pode ser fracionada)."""
    return arredondar(_dec(preco_cent) * _dec(qtd))


# -------------------------------------------------------------- quantidade
def para_qtd(texto) -> float:
    if texto is None or str(texto).strip() == "":
        return 0.0
    s = str(texto).strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        valor = round(float(s), CASAS_QTD)
    except ValueError:
        raise ValueError(f"quantidade inválida: {texto!r}") from None
    if not math.isfinite(valor):            # 'nan', 'inf' e '1e999' também passam por float()
        raise ValueError(f"quantidade inválida: {texto!r}")
    return valor


def fmt_qtd(q, casas: int = 3) -> str:
    q = float(q or 0)
    return f"{q:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def arred_qtd(q) -> float:
    return round(float(q), CASAS_QTD)


# ------------------------------------------------------------------- datas
def fmt_data(iso: str | None) -> str:
    if not iso:
        return ""
    return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")


def fmt_datahora(iso: str | None) -> str:
    if not iso:
        return ""
    if len(iso) < 19:
        return fmt_data(iso)
    return datetime.strptime(iso[:19], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M:%S")


def fmt_hora(iso: str | None) -> str:
    return iso[11:19] if iso and len(iso) >= 19 else (iso or "")


def para_data_iso(texto: str | None) -> str | None:
    """'03/10/2026' | '2026-10-03' | '' -> 'YYYY-MM-DD' (ou None se vazio)."""
    if texto is None or not str(texto).strip():
        return None
    s = str(texto).strip()
    for formato, tamanho in (("%d/%m/%Y", 10), ("%Y-%m-%d", 10), ("%d/%m/%y", 8)):
        try:
            return datetime.strptime(s[:tamanho], formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"data inválida: {texto!r} (use dd/mm/aaaa)")


def para_hora(texto: str | None) -> str | None:
    """'18', '18:30' -> 'HH:MM' (ou None)."""
    if texto is None or not str(texto).strip():
        return None
    s = str(texto).strip()
    try:
        if ":" not in s:
            s += ":00"
        h, m = (int(p) for p in s.split(":")[:2])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        return f"{h:02d}:{m:02d}"
    except ValueError:
        raise ValueError(f"hora inválida: {texto!r} (use hh:mm)") from None


def somar_meses(iso_data: str, meses: int) -> str:
    """Soma meses mantendo o dia (ou o último dia válido do mês destino)."""
    d = datetime.strptime(iso_data[:10], "%Y-%m-%d").date()
    mes0 = d.month - 1 + meses
    ano, mes = d.year + mes0 // 12, mes0 % 12 + 1
    dia = d.day
    while True:
        try:
            return date(ano, mes, dia).strftime("%Y-%m-%d")
        except ValueError:
            dia -= 1


def somar_dias(iso_data: str, dias: int) -> str:
    d = datetime.strptime(iso_data[:10], "%Y-%m-%d").date() + timedelta(days=dias)
    return d.strftime("%Y-%m-%d")


def dia_operacional(iso: str | None = None, virada: int = 0) -> str:
    """Dia a que pertence o momento (padrão: agora). Numa boate a noite atravessa a meia-noite: antes da hora de
    virada (ex.: 6), ainda é a noite do dia anterior. Com virada 0, é o dia do calendário."""
    momento = datetime.strptime(iso[:19], "%Y-%m-%d %H:%M:%S") if iso else agora_dt()
    return (momento - timedelta(hours=virada)).strftime("%Y-%m-%d")


def faixa_dia_operacional(dia: str, virada: int = 0) -> tuple[str, str]:
    """[início, fim) do dia operacional, para comparar com colunas 'AAAA-MM-DD hh:mm:ss' (usa os índices)."""
    return f"{dia[:10]} {virada:02d}:00:00", f"{somar_dias(dia, 1)} {virada:02d}:00:00"


def dia_semana(iso: str) -> int:
    """1=Domingo ... 7=Sábado."""
    return (datetime.strptime(iso[:10], "%Y-%m-%d").weekday() + 1) % 7 + 1


NOMES_DIA = {1: "Domingo", 2: "Segunda", 3: "Terça", 4: "Quarta", 5: "Quinta", 6: "Sexta", 7: "Sábado"}


def minutos_entre(inicio_iso: str, fim: datetime | None = None) -> int:
    ini = datetime.strptime(inicio_iso[:19], "%Y-%m-%d %H:%M:%S")
    return int(((fim or agora_dt()) - ini) / timedelta(minutes=1))
