"""Base de produtos por código de barras, que vai junto com o programa (src/dados/base_codigos.csv).

Quando o leitor passa um código que a loja não tem cadastrado, o caixa procura aqui antes da internet. Achando, o
"Produto novo" já vem com o nome, a categoria e o NCM, e o operador só põe o preço de venda, o custo e a quantidade
("ativar" o produto). Funciona sem internet e é instantâneo.

O arquivo é um CSV separado por ponto e vírgula, em UTF-8, com cabeçalho:

    codigo_barras;nome;categoria;ncm

- `codigo_barras`: GTIN/EAN de 8, 12, 13 ou 14 números, com o dígito verificador certo (o que não confere é
  descartado: é o filtro contra código inventado);
- `nome`: o nome como deve aparecer no caixa;
- `categoria` (opcional): o nome do subgrupo do perfil (CERVEJAS, DESTILADOS...). Se a loja tiver um igual, já vem
  escolhido;
- `ncm` (opcional): 8 números.

A base só sugere: o operador confere o nome antes de cadastrar. Para juntar uma lista nova (por exemplo, a feita com
outra IA) use `python -m tools.base_codigos juntar arquivo.csv`, que confere e limpa antes de gravar.
"""
from __future__ import annotations

import csv
import io
import re
import sys
import threading
from pathlib import Path

COLUNAS = ("codigo_barras", "nome", "categoria", "ncm")
TAMANHOS_GTIN = (8, 12, 13, 14)
LIMITE_NOME = 120
_cache: dict[str, dict] | None = None
_trava = threading.Lock()


def caminho_padrao() -> Path:
    """No executável o build copia o arquivo para `dados/` dentro do pacote; no código-fonte fica em src/dados."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", "")) / "dados" / "base_codigos.csv"
    return Path(__file__).resolve().parents[1] / "dados" / "base_codigos.csv"


def digito_ok(codigo: str) -> bool:
    """Confere o dígito verificador do GTIN (EAN-8, UPC-12, EAN-13, GTIN-14)."""
    if not codigo.isdigit() or len(codigo) not in TAMANHOS_GTIN:
        return False
    corpo, dv = codigo[:-1], int(codigo[-1])
    soma = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(corpo)))
    return (10 - soma % 10) % 10 == dv


def normalizar(codigo: str) -> str:
    """Só números, completado com zeros à esquerda até 14 (o mesmo produto em UPC-12 e EAN-13 vira a mesma chave)."""
    numeros = re.sub(r"\D", "", codigo or "")
    return numeros.zfill(14) if len(numeros) in TAMANHOS_GTIN else ""


def limpar_nome(nome: str) -> str:
    return re.sub(r"\s+", " ", (nome or "").strip()).upper()[:LIMITE_NOME]


def ler_csv(texto: str) -> tuple[list[dict], list[str]]:
    """Linhas válidas e os motivos das descartadas (para o relatório). Aceita ; ou , como separador."""
    amostra = texto[:2048]
    separador = ";" if amostra.count(";") >= amostra.count(",") else ","
    leitor = csv.DictReader(io.StringIO(texto.lstrip("﻿")), delimiter=separador)
    campos = {(c or "").strip().lower(): c for c in (leitor.fieldnames or [])}
    if "codigo_barras" not in campos or "nome" not in campos:
        raise ValueError("O arquivo precisa das colunas codigo_barras e nome (cabeçalho na primeira linha).")
    validas, descartes = [], []
    for numero, linha in enumerate(leitor, start=2):
        bruto = str(linha.get(campos["codigo_barras"]) or "").strip()
        nome = limpar_nome(linha.get(campos["nome"]) or "")
        numeros = re.sub(r"\D", "", bruto)
        if not nome:
            descartes.append(f"linha {numero}: sem nome")
            continue
        if not digito_ok(numeros):
            descartes.append(f"linha {numero}: código {bruto or '(vazio)'} inválido (dígito verificador não confere)")
            continue
        ncm = re.sub(r"\D", "", str(linha.get(campos.get("ncm", ""), "") or ""))
        validas.append({
            "codigo_barras": numeros, "nome": nome,
            "categoria": limpar_nome(linha.get(campos.get("categoria", ""), "") or "")[:60],
            "ncm": ncm if len(ncm) == 8 else "",
        })
    return validas, descartes


def escrever_csv(linhas: list[dict]) -> str:
    saida = io.StringIO()
    escritor = csv.DictWriter(saida, fieldnames=COLUNAS, delimiter=";", lineterminator="\n")
    escritor.writeheader()
    for linha in linhas:
        escritor.writerow({c: linha.get(c, "") for c in COLUNAS})
    return saida.getvalue()


def juntar(existentes: list[dict], novas: list[dict]) -> tuple[list[dict], int, int]:
    """Junta sem duplicar pelo código. O que já estava na base vale (só completa categoria e NCM vazios).
    Devolve (linhas ordenadas pelo nome, quantas entraram, quantas eram repetidas)."""
    por_codigo = {normalizar(l["codigo_barras"]): dict(l) for l in existentes}
    entraram = repetidas = 0
    for linha in novas:
        chave = normalizar(linha["codigo_barras"])
        atual = por_codigo.get(chave)
        if atual is None:
            por_codigo[chave] = dict(linha)
            entraram += 1
            continue
        repetidas += 1
        for campo in ("categoria", "ncm"):
            if not atual.get(campo) and linha.get(campo):
                atual[campo] = linha[campo]
    return sorted(por_codigo.values(), key=lambda l: (l["nome"], l["codigo_barras"])), entraram, repetidas


def carregar(caminho: Path | None = None) -> dict[str, dict]:
    """A base em memória (código normalizado -> linha). Lida uma vez; sem arquivo, base vazia."""
    global _cache
    if caminho is None and _cache is not None:
        return _cache
    alvo = caminho or caminho_padrao()
    try:
        linhas, _ = ler_csv(alvo.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        linhas = []
    base = {normalizar(l["codigo_barras"]): l for l in linhas}
    if caminho is None:
        with _trava:
            _cache = base
    return base


def esquecer_cache() -> None:
    global _cache
    with _trava:
        _cache = None


def procurar(codigo: str, caminho: Path | None = None) -> dict | None:
    chave = normalizar(codigo)
    return carregar(caminho).get(chave) if chave else None


def quantidade(caminho: Path | None = None) -> int:
    return len(carregar(caminho))
