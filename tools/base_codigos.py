"""Confere e junta uma lista de produtos na base de códigos de barras que vai junto com o programa.

    python -m tools.base_codigos juntar lista.csv        # confere, mostra o relatório e grava em src/dados
    python -m tools.base_codigos conferir lista.csv      # só o relatório, sem gravar
    python -m tools.base_codigos modelo                  # imprime o cabeçalho e um exemplo

A lista é um CSV (ponto e vírgula ou vírgula) com as colunas codigo_barras;nome;categoria;ncm. Código com o dígito
verificador errado é descartado: é o que pega boa parte dos códigos inventados por uma IA. Um código que existe mas é de
outro produto não tem como ser pego aqui: o caixa mostra o nome e o operador confere antes de cadastrar.
"""
from __future__ import annotations

import sys
from pathlib import Path

from src.controllers import base_codigos as base

MODELO = ("codigo_barras;nome;categoria;ncm\n"
          "7891149103102;CERVEJA SKOL PILSEN LATA 350ML;CERVEJAS;22030000\n")


def relatorio(validas: int, descartes: list[str], entraram: int | None = None, repetidas: int | None = None,
              total: int | None = None) -> str:
    linhas = [f"Linhas válidas: {validas}", f"Descartadas: {len(descartes)}"]
    linhas += [f"  - {motivo}" for motivo in descartes[:30]]
    if len(descartes) > 30:
        linhas.append(f"  ... e mais {len(descartes) - 30}")
    if entraram is not None:
        linhas += [f"Novas na base: {entraram}", f"Já estavam: {repetidas}", f"Total na base: {total}"]
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("juntar", "conferir", "modelo"):
        print(__doc__)
        return 2
    if argv[0] == "modelo":
        print(MODELO, end="")
        return 0
    if len(argv) < 2:
        print("Informe o arquivo CSV.")
        return 2
    try:
        validas, descartes = base.ler_csv(Path(argv[1]).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as erro:
        print(f"Não consegui ler a lista: {erro}")
        return 1
    if argv[0] == "conferir":
        print(relatorio(len(validas), descartes))
        return 0
    destino = base.caminho_padrao()
    existentes, _ = base.ler_csv(destino.read_text(encoding="utf-8-sig")) if destino.is_file() else ([], [])
    linhas, entraram, repetidas = base.juntar(existentes, validas)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(base.escrever_csv(linhas), encoding="utf-8")
    print(relatorio(len(validas), descartes, entraram, repetidas, len(linhas)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
