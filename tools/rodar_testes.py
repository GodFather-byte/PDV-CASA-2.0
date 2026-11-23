"""Roda a suíte em paralelo, um processo por módulo de teste, com tempo-limite por módulo.

    python -m tools.rodar_testes                 # todos os tests/test_*.py, um processo por núcleo
    python -m tools.rodar_testes -j 4 --limite 600 tests.test_caixa tests.test_nfce

Por quê: no PC do dono (runner próprio) a suíte inteira em série passa de 30 minutos e, se um teste trava, só se vê
um silêncio. Aqui cada módulo roda sozinho (pasta temporária própria), em paralelo, e o resultado diz o tempo de cada
um; módulo que passa do limite é encerrado e aparece como TRAVOU. Código de saída 1 se algum falhou ou travou.
Os mais demorados da última rodada vão primeiro (tests/.tempos.json), para o paralelo terminar junto.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
TEMPOS = RAIZ / "tests" / ".tempos.json"


def modulos() -> list[str]:
    return sorted(f"tests.{p.stem}" for p in (RAIZ / "tests").glob("test_*.py"))


def _ler_tempos() -> dict:
    try:
        return json.loads(TEMPOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def rodar(modulo: str, limite: int) -> tuple[str, str, float, str]:
    inicio = time.monotonic()
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="pdvteste-") as tmp:
        env["TMP"] = env["TEMP"] = env["TMPDIR"] = tmp      # cada módulo com a própria pasta temporária
        try:
            r = subprocess.run([sys.executable, "-m", "unittest", modulo], cwd=RAIZ, env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=limite)
        except subprocess.TimeoutExpired as e:
            saida = (e.stdout or "") + (e.stderr or "") if isinstance(e.stdout, str) else ""
            return modulo, "TRAVOU", time.monotonic() - inicio, saida[-4000:]
    saida = (r.stdout or "") + (r.stderr or "")
    situacao = "OK" if r.returncode == 0 else "FALHOU"
    if situacao != "OK":        # testes "OK" com saída diferente de zero = o processo caiu ao encerrar (ex.: Qt no Windows)
        saida = saida[-6000:] + f"\n(código de saída do processo: {r.returncode})"
    return modulo, situacao, time.monotonic() - inicio, saida if situacao != "OK" else ""


def _saida_tolerante() -> None:
    """No console do Windows (cp1252) a saída de um teste pode trazer caractere que o terminal não escreve. Sem isto o
    `print` do relatório levanta UnicodeEncodeError e some justamente a causa da falha; com isto o caractere vira "?"."""
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if callable(reconfigurar):
            try:
                reconfigurar(errors="replace")
            except (OSError, ValueError):
                pass


def main(argv: list[str] | None = None) -> int:
    _saida_tolerante()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("modulos", nargs="*", help="módulos (padrão: todos)")
    p.add_argument("-j", "--paralelo", type=int, default=max(2, os.cpu_count() or 2))
    p.add_argument("--limite", type=int, default=900, help="segundos por módulo antes de considerar travado")
    a = p.parse_args(argv)
    lista = a.modulos or modulos()
    tempos = _ler_tempos()
    lista.sort(key=lambda m: -float(tempos.get(m, 30)))
    print(f"{len(lista)} módulos, {a.paralelo} em paralelo, limite {a.limite}s cada", flush=True)
    inicio = time.monotonic()
    ruins = []
    with ThreadPoolExecutor(max_workers=a.paralelo) as pool:
        futuros = [pool.submit(rodar, m, a.limite) for m in lista]
        for f in as_completed(futuros):
            modulo, situacao, segundos, saida = f.result()
            tempos[modulo] = round(segundos, 1)
            print(f"{situacao:7} {segundos:7.1f}s  {modulo}", flush=True)
            if situacao != "OK":
                ruins.append((modulo, situacao, saida))
    try:
        TEMPOS.write_text(json.dumps(tempos, indent=0, sort_keys=True), encoding="utf-8")
    except OSError:
        pass
    for modulo, situacao, saida in ruins:
        print(f"\n===== {situacao}: {modulo} =====\n{saida}", flush=True)
    mais_lentos = sorted(((t, m) for m, t in tempos.items() if m in lista), reverse=True)[:8]
    print("\nMais demorados: " + ", ".join(f"{m.split('.')[-1]} {t:.0f}s" for t, m in mais_lentos))
    print(f"{len(lista) - len(ruins)}/{len(lista)} módulos OK em {time.monotonic() - inicio:.0f}s"
          + (f"; {len(ruins)} com problema" if ruins else ""))
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main())
