"""Estrutura comum dos relatórios e conversores para texto (tela/impressora) e CSV (Excel)."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field


@dataclass
class Coluna:
    titulo: str
    largura: int = 12
    alinha: str = "e"       # e = esquerda, d = direita, c = centro


@dataclass
class Relatorio:
    titulo: str
    colunas: list[Coluna]
    linhas: list[list] = field(default_factory=list)
    estilos: list[str] = field(default_factory=list)       # '', 'secao', 'subtotal', 'total' (um por linha)
    criterios: list[str] = field(default_factory=list)
    rodape: list[tuple[str, str]] = field(default_factory=list)
    cabecalho: list[str] = field(default_factory=list)     # linhas extras sob o título (loja, data...)

    def add(self, *valores, estilo: str = "") -> None:
        self.linhas.append([("" if v is None else str(v)) for v in valores])
        self.estilos.append(estilo)

    def vazio(self) -> bool:
        return not self.linhas


def _ajustar(texto: str, largura: int, alinha: str) -> str:
    if len(texto) > largura:   # corta com ponto final (ASCII: impressoras térmicas não têm reticências)
        texto = texto[: largura - 1] + "." if largura > 1 else texto[:largura]
    if alinha == "d":
        return texto.rjust(largura)
    if alinha == "c":
        return texto.center(largura)
    return texto.ljust(largura)


def _larguras(rel: Relatorio, largura: int) -> list[int]:
    ws = [max(c.largura, len(c.titulo) if len(rel.colunas) > 2 else 1) for c in rel.colunas]
    espacos = len(ws) - 1
    sobra = largura - (sum(ws) + espacos)
    if sobra >= 0:
        # distribui o que sobrou na maior coluna alinhada à esquerda (normalmente a descrição)
        flex = max((i for i, c in enumerate(rel.colunas) if c.alinha == "e"), key=lambda i: ws[i], default=0)
        ws[flex] += sobra
    else:
        flex = max(range(len(ws)), key=lambda i: ws[i])
        ws[flex] = max(ws[flex] + sobra, 4)
    return ws


def para_texto(rel: Relatorio, largura: int = 80) -> str:
    """Texto monoespaçado pronto para tela (80 colunas) ou fita (40)."""
    saida = [rel.titulo.upper().center(largura)]
    saida += [c.center(largura) for c in rel.cabecalho]
    saida.append("=" * largura)
    for c in rel.criterios:
        saida.append(c[:largura])
    if rel.criterios:
        saida.append("-" * largura)
    ws = _larguras(rel, largura)
    if len(rel.colunas) > 2:
        saida.append(" ".join(_ajustar(c.titulo, w, c.alinha) for c, w in zip(rel.colunas, ws)))
        saida.append("-" * largura)
    for valores, estilo in zip(rel.linhas, rel.estilos or [""] * len(rel.linhas)):
        if estilo == "secao":
            saida.append(str(valores[0]).upper()[:largura])
            continue
        if estilo in ("total", "subtotal"):
            saida.append(("=" if estilo == "total" else "-") * largura)
        saida.append(" ".join(_ajustar(str(v), w, c.alinha) for v, w, c in zip(valores, ws, rel.colunas)).rstrip())
    if rel.rodape:
        saida.append("-" * largura)
        for rotulo, valor in rel.rodape:
            valor = str(valor)
            saida.append(rotulo[: max(largura - len(valor) - 1, 1)].ljust(largura - len(valor)) + valor)
    return "\n".join(saida)


def para_csv(rel: Relatorio) -> str:
    """CSV com separador ';' e vírgula decimal, como o Excel em português espera."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow([rel.titulo])
    for c in rel.criterios:
        w.writerow([c])
    w.writerow([c.titulo for c in rel.colunas])
    for valores, estilo in zip(rel.linhas, rel.estilos or [""] * len(rel.linhas)):
        w.writerow(valores)
    for rotulo, valor in rel.rodape:
        w.writerow([rotulo, valor])
    return buf.getvalue()
