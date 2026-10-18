"""Gera o executável do WillPDV Licenças (PyInstaller) e, no Windows com o Inno Setup instalado, o instalador.

    python build_licenciador.py                  -> dist/WillLicencas/WillLicencas.exe  e  instalador/saida/WillLicencas-Setup-<versão>.exe
    python build_licenciador.py --sem-instalador -> só o executável

É o programa SEPARADO do fornecedor (emite licenças); o PDV do cliente é gerado por `build_pdv.py`.
Requisitos: pip install pyinstaller  e o Inno Setup 6.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from build_pdv import achar_iscc

RAIZ = Path(__file__).resolve().parent
ICONE = RAIZ / "instalador" / "willlicencas.ico"
SCRIPT_INNO = RAIZ / "instalador" / "WillLicencas.iss"


def versao() -> str:
    sys.path.insert(0, str(RAIZ))
    from licenciador.nucleo import VERSAO
    return VERSAO


def gerar_executavel() -> None:
    comando = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
               "--name", "WillLicencas", "--paths", str(RAIZ)]
    if ICONE.exists():
        comando += ["--icon", str(ICONE), "--add-data", f"{ICONE}{os.pathsep}."]
    comando.append(str(RAIZ / "licenciador" / "app.py"))
    subprocess.run(comando, check=True, cwd=RAIZ)
    print(f"Executável pronto: {RAIZ / 'dist' / 'WillLicencas' / 'WillLicencas.exe'}")


def gerar_instalador() -> None:
    iscc = achar_iscc()
    if iscc is None:
        print("Inno Setup não encontrado: instale o Inno Setup 6 (ou defina a variável ISCC com o caminho do ISCC.exe).")
        return
    definicoes = [f"/DVersao={versao()}"] + ([f"/DIcone={ICONE}"] if ICONE.exists() else [])
    subprocess.run([iscc, *definicoes, str(SCRIPT_INNO)], check=True, cwd=RAIZ)
    print(f"Instalador pronto em {RAIZ / 'instalador' / 'saida'}")


if __name__ == "__main__":
    print(f"Gerando o WillPDV Licenças {versao()}...")
    try:
        gerar_executavel()
        if "--sem-instalador" not in sys.argv[1:]:
            if os.name == "nt":
                gerar_instalador()
            else:
                print("O instalador (Inno Setup) só é gerado no Windows.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"Erro no build: {e}")
