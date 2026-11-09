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


def para_pdf(rel: Relatorio) -> bytes:
    """PDF simples do mesmo texto do relatório, para abrir no celular ou no computador. Sem biblioteca extra."""
    texto = para_texto(rel, 90)
    linhas = texto.split("\n")
    paginas = [linhas[i:i + 48] for i in range(0, max(len(linhas), 1), 48)]

    def esc(linha: str) -> str:
        limpa = linha.encode("latin-1", "replace").decode("latin-1")
        return limpa.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    conteudos = []
    for bloco in paginas:
        comandos = ["BT /F1 9 Tf 40 800 Td 11 TL"]
        for linha in bloco:
            comandos.append(f"({esc(linha)}) Tj T*")
        comandos.append("ET")
        conteudos.append("\n".join(comandos).encode("latin-1", "replace"))
    n_pag = len(conteudos)
    # objetos: 1 catalog, 2 pages, 3 font, 4.. conteúdos, depois páginas
    ids_fluxo = list(range(4, 4 + n_pag))
    ids_pagina = list(range(4 + n_pag, 4 + 2 * n_pag))
    pecas = [b"%PDF-1.4\n"]
    offsets = [0]
    def acrescentar(dados: bytes) -> None:
        offsets.append(sum(len(p) for p in pecas))
        pecas.append(dados)
    acrescentar(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    kids = " ".join(f"{i} 0 R" for i in ids_pagina)
    acrescentar(f"2 0 obj\n<< /Type /Pages /Count {n_pag} /Kids [{kids}] >>\nendobj\n".encode())
    acrescentar(b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj\n")
    for i, fluxo in enumerate(conteudos):
        acrescentar(f"{ids_fluxo[i]} 0 obj\n<< /Length {len(fluxo)} >>\nstream\n".encode() + fluxo + b"\nendstream\nendobj\n")
    for i in range(n_pag):
        acrescentar(
            f"{ids_pagina[i]} 0 obj\n<< /Type /Page /Parent 2 0 R /Contents {ids_fluxo[i]} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> /MediaBox [0 0 595 842] >>\nendobj\n".encode())
    xref = sum(len(p) for p in pecas)
    total = 1 + 2 + n_pag * 2
    xref_linhas = [f"xref\n0 {total + 1}\n", "0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref_linhas.append(f"{off:010d} 00000 n \n")
    pecas.append("".join(xref_linhas).encode())
    pecas.append(f"trailer\n<< /Size {total + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return b"".join(pecas)
