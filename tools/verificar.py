"""Verificação antes do commit: roda o que prova que a mudança funciona, rápido e sempre do mesmo jeito.

    python -m tools.verificar              # o que mudou em relação à main (commits da branch + arquivos não commitados)
    python -m tools.verificar --tudo       # suíte inteira
    python -m tools.verificar --telas      # também fotografa as telas (build/telas) se mexeu em src/ui_qt

O que roda:
  1. Fumaça do caixa (sempre): venda, pagamento, troco, fechamento, troca de forma, recebimento direto e as
     propriedades do dinheiro e do estoque. É o fluxo que não pode quebrar em loja nenhuma.
  2. Os testes ligados ao que mudou: o teste com o mesmo nome do arquivo e todo teste que importa o módulo alterado.
  3. `node --check` em cada .js alterado.
No fim imprime a linha "Verificado: ..." para colar na mensagem do commit (ou "Verificado: nenhum" se nada rodou).
Saída com código 1 se algo falhou.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FUMACA = ("tests.test_caixa", "tests.test_propriedades_dinheiro", "tests.test_qt_trocar_forma",
          "tests.test_qt_pagamento_direto")
IGNORAR = re.compile(r"^(\.ai/|docs/|.*\.md$)")


def _git(*args: str) -> list[str]:
    r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True)
    return [l.strip() for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 else []


def alterados() -> list[str]:
    base = _git("merge-base", "HEAD", "origin/main") or _git("merge-base", "HEAD", "main")
    nomes = set(_git("diff", "--name-only", base[0], "HEAD")) if base else set()
    nomes |= set(_git("diff", "--name-only", "HEAD"))
    nomes |= set(_git("ls-files", "--others", "--exclude-standard"))
    return sorted(n for n in nomes if not IGNORAR.match(n) and (RAIZ / n).exists())


def modulo(caminho: str) -> str | None:
    if not caminho.endswith(".py"):
        return None
    partes = Path(caminho).with_suffix("").parts
    return ".".join(partes[:-1] if partes[-1] == "__init__" else partes)


def testes_para(arquivos: list[str]) -> list[str]:
    testes = set()
    todos = sorted((RAIZ / "tests").glob("test_*.py"))
    for arq in arquivos:
        if arq.startswith("tests/test_") and arq.endswith(".py"):
            testes.add(modulo(arq))
            continue
        mod = modulo(arq)
        if not mod:
            continue
        curto = mod.rsplit(".", 1)[-1]
        if (RAIZ / "tests" / f"test_{curto}.py").exists():
            testes.add(f"tests.test_{curto}")
        padrao = re.compile(rf"(from|import)\s+{re.escape(mod)}\b|from\s+{re.escape(mod.rsplit('.', 1)[0])}\s+import\s+[^\n]*\b{curto}\b")
        for t in todos:
            if padrao.search(t.read_text(encoding="utf-8", errors="ignore")):
                testes.add(f"tests.{t.stem}")
    return sorted(testes)


def rodar(cmd: list[str], rotulo: str) -> bool:
    print(f"\n== {rotulo}\n$ {' '.join(cmd)}", flush=True)
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    r = subprocess.run(cmd, cwd=RAIZ, env=env)
    print(f"-> {'OK' if r.returncode == 0 else 'FALHOU'}", flush=True)
    return r.returncode == 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tudo", action="store_true", help="roda a suíte inteira")
    p.add_argument("--telas", action="store_true", help="fotografa as telas se src/ui_qt mudou")
    a = p.parse_args(argv)
    arquivos = alterados()
    print("Arquivos alterados:", ", ".join(arquivos) or "nenhum")
    feito, ok = [], True
    if a.tudo:
        ok &= rodar([sys.executable, "-m", "unittest", "discover", "-s", "tests"], "suíte inteira")
        feito.append("suíte inteira")
    else:
        ok &= rodar([sys.executable, "-m", "unittest", *FUMACA], "fumaça do caixa")
        feito.append("fumaça do caixa")
        ligados = [t for t in testes_para(arquivos) if t not in FUMACA]
        if ligados:
            ok &= rodar([sys.executable, "-m", "unittest", *ligados], f"testes do que mudou ({len(ligados)})")
            feito.append(f"{len(ligados)} módulos de teste")
    js = [f for f in arquivos if f.endswith(".js")]
    if js:
        if shutil.which("node"):
            for f in js:
                ok &= rodar(["node", "--check", f], f"sintaxe {f}")
            feito.append("node --check")
        else:
            print("\n(node não instalado: sintaxe dos .js não conferida)")
    if a.telas and any(f.startswith("src/ui_qt/") for f in arquivos):
        ok &= rodar([sys.executable, "-m", "tools.capturar_telas", "build/telas"], "fotos das telas")
        feito.append("telas em build/telas")
    print(f"\n{'TUDO OK' if ok else 'ALGO FALHOU'}")
    print("Verificado: " + ("; ".join(feito) if feito else "nenhum") + ("" if ok else " (COM FALHA)"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
