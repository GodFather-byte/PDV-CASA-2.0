"""Gera o executável do PDV (PyInstaller) e, no Windows com o Inno Setup instalado, o instalador.

    python build_pdv.py                  -> dist/WillPDV/WillPDV.exe  e  instalador/saida/WillPDV-Setup-<versão>.exe
    python build_pdv.py --sem-instalador -> só o executável

Requisitos (uma vez, na máquina que gera a versão): pip install pyinstaller  e  o Inno Setup 6 (jrsoftware.org).
O compilador do Inno (ISCC.exe) é procurado na variável de ambiente ISCC e nas pastas padrão de instalação.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ICONE = RAIZ / "instalador" / "willpdv.ico"          # opcional: coloque o ícone aqui e ele vai no .exe e no instalador
SCRIPT_INNO = RAIZ / "instalador" / "WillPDV.iss"


def versao() -> str:
    sys.path.insert(0, str(RAIZ))
    from src.versao import VERSAO
    return VERSAO


def gerar_executavel() -> None:
    comando = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
               "--windowed",                                # sem a janela preta do CMD atrás do caixa
               "--name", "WillPDV", "--paths", str(RAIZ)]   # a raiz no caminho: os imports são "from src..."
    if ICONE.exists():
        # --icon: ícone do .exe; --add-data: o mesmo arquivo dentro do pacote, para as janelas do programa (janelas do programa)
        comando += ["--icon", str(ICONE), "--add-data", f"{ICONE}{os.pathsep}."]
    comando.append(str(RAIZ / "src" / "app.py"))
    subprocess.run(comando, check=True, cwd=RAIZ)
    copiar_licencas(RAIZ / "dist" / "WillPDV")
    print(f"Executável pronto: {RAIZ / 'dist' / 'WillPDV' / 'WillPDV.exe'}")


def copiar_licencas(destino: Path) -> None:
    pasta = destino / "licencas"
    pasta.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RAIZ / "docs" / "TERCEIROS_QT.md", pasta / "TERCEIROS_QT.md")
    for arquivo in (RAIZ / "instalador" / "licencas").glob("*.txt"):
        shutil.copyfile(arquivo, pasta / arquivo.name)
    manifesto = []
    for nome in ("PySide6-Essentials", "shiboken6", "cryptography", "cffi", "Pillow"):
        pacote = distribution(nome)
        manifesto.append(f"{nome} {pacote.version}: {pacote.metadata.get('License-Expression') or pacote.metadata.get('License', '')}")
        for arquivo in pacote.files or ():
            if ".dist-info" in str(arquivo) and (
                    "license" in str(arquivo).lower() or "copying" in str(arquivo).lower()):
                origem = Path(pacote.locate_file(arquivo))
                alvo = pasta / "pacotes" / nome / Path(arquivo).name
                alvo.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(origem, alvo)
    (pasta / "DEPENDENCIAS.txt").write_text("\n".join(manifesto) + "\n", encoding="utf-8")


def achar_iscc() -> str | None:
    candidatos = [os.environ.get("ISCC"), shutil.which("ISCC"), shutil.which("iscc")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidatos += [str(Path(base) / "Inno Setup 6" / "ISCC.exe"), str(Path(base) / "Programs" / "Inno Setup 6" / "ISCC.exe")]
    return next((c for c in candidatos if c and Path(c).is_file()), None)


def gerar_instalador() -> None:
    iscc = achar_iscc()
    if iscc is None:
        print("Inno Setup não encontrado: instale o Inno Setup 6 (ou defina a variável ISCC com o caminho do ISCC.exe) "
              "e rode de novo, ou abra instalador/WillPDV.iss no Inno Setup e clique em Compile.")
        return
    definicoes = [f"/DVersao={versao()}"] + ([f"/DIcone={ICONE}"] if ICONE.exists() else [])
    subprocess.run([iscc, *definicoes, str(SCRIPT_INNO)], check=True, cwd=RAIZ)
    print(f"Instalador pronto em {RAIZ / 'instalador' / 'saida'}")


if __name__ == "__main__":
    print(f"Gerando o WillPDV {versao()}...")
    try:
        gerar_executavel()
        if "--sem-instalador" not in sys.argv[1:]:
            if os.name == "nt":
                gerar_instalador()
            else:
                print("O instalador (Inno Setup) só é gerado no Windows.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"Erro no build: {e}")
