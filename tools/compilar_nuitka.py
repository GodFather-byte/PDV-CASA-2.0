"""Compila o código do PDV com o Nuitka (vira C compilado) antes do PyInstaller empacotar.

Por quê: o PyInstaller sozinho leva o código como bytecode Python, que qualquer um extrai do .exe e lê quase como o
original. Compilado, cada pacote de `src/` vira uma extensão nativa (`.pyd` no Windows), muito mais difícil de ler e de
alterar (por exemplo, para tirar a checagem da licença).

Como: cada subpacote de `src/` (core, controllers, ui_qt...) vira UMA extensão (`--mode=package`), gravada em
`build/nuitka/src/`. O `build_pdv.py` entrega essas extensões ao PyInstaller no lugar dos `.py` desses pacotes. Os
arquivos soltos de `src/` (app, autoteste, versao...) continuam Python: são a entrada e quase não têm regra.

O PyInstaller não enxerga os `import` de dentro de uma extensão. Por isso `imports_externos` lê os `.py` e devolve tudo
o que eles importam de fora de `src`; o build passa isso como `--hidden-import`.

    python -m tools.compilar_nuitka            # só compila (para conferir)
"""
from __future__ import annotations

import ast
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SRC = RAIZ / "src"
SAIDA = RAIZ / "build" / "nuitka"


def pacotes() -> list[str]:
    """Os subpacotes de `src` que viram extensão (pastas com `__init__.py`)."""
    return sorted(p.name for p in SRC.iterdir() if p.is_dir() and (p / "__init__.py").is_file())


def imports_externos(nomes: list[str] | None = None) -> list[str]:
    """Tudo o que os `.py` desses pacotes importam de fora de `src` (ex.: `PySide6.QtWidgets`, `lxml.etree`).

    De `from X import Y` entram X e X.Y (Y pode ser um submódulo); o PyInstaller só avisa quando um nome não é módulo."""
    encontrados: set[str] = set()
    for nome in nomes or pacotes():
        for arquivo in (SRC / nome).rglob("*.py"):
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"), str(arquivo))
            for no in ast.walk(arvore):
                if isinstance(no, ast.Import):
                    encontrados.update(alias.name for alias in no.names)
                elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
                    encontrados.add(no.module)
                    encontrados.update(f"{no.module}.{alias.name}" for alias in no.names
                                       if alias.name != "*" and eh_modulo(f"{no.module}.{alias.name}"))
    return sorted(m for m in encontrados if m != "src" and not m.startswith("src."))


def eh_modulo(nome: str) -> bool:
    """Se `X.Y` é um submódulo instalado (em `from X import Y`, Y quase sempre é uma classe ou função)."""
    if nome.startswith("src."):
        return False
    try:
        return importlib.util.find_spec(nome) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def compilar(saida: Path = SAIDA, nomes: list[str] | None = None) -> list[Path]:
    """Compila cada pacote e devolve as extensões geradas (em `saida/src`). Para no primeiro erro."""
    destino = saida / "src"
    if saida.exists():
        shutil.rmtree(saida)
    destino.mkdir(parents=True)
    trabalho = saida / "trabalho"
    jobs = str(os.cpu_count() or 2)
    for nome in nomes or pacotes():
        print(f"Nuitka: compilando src.{nome}...", flush=True)
        comando = [sys.executable, "-m", "nuitka", "--mode=package", str(SRC / nome),
                   f"--include-package=src.{nome}", "--nofollow-imports", f"--output-dir={trabalho}",
                   "--remove-output", "--no-pyi-file", f"--jobs={jobs}", "--assume-yes-for-downloads",
                   "--python-flag=no_docstrings"]
        if os.name == "nt":
            comando.append("--msvc=latest")      # o Visual Studio do runner do GitHub; não baixa compilador
        subprocess.run(comando, check=True, cwd=RAIZ)
        gerados = [a for a in trabalho.iterdir() if a.is_file() and a.name.startswith(nome + ".")
                   and a.suffix in (".pyd", ".so")]
        if len(gerados) != 1:
            raise RuntimeError(f"O Nuitka não gerou a extensão de src.{nome} (achei: {[a.name for a in gerados]}).")
        shutil.move(str(gerados[0]), destino / gerados[0].name)
    shutil.rmtree(trabalho, ignore_errors=True)
    extensoes = sorted(destino.iterdir())
    print(f"Nuitka: {len(extensoes)} pacotes compilados em {destino}")
    return extensoes


if __name__ == "__main__":
    compilar()
