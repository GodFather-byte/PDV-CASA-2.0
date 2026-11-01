"""Gera o executável do PDV (PyInstaller) e, no Windows com o Inno Setup instalado, o instalador.

    python build_pdv.py                  -> dist/WillPDV/WillPDV.exe  e  instalador/saida/WillPDV-Setup-<versão>.exe
    python build_pdv.py --sem-instalador -> só o executável
    python build_pdv.py --edicao ea_superacoes
                                         -> dist/EASuperacoes/EASuperacoes.exe  e  instalador/saida/EASuperacoes-Setup-<versão>.exe
                                            (edição só de adega; ver src/core/edicao.py)

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
PASTA_INSTALADOR = RAIZ / "instalador"
ICONE = PASTA_INSTALADOR / "willpdv.ico"          # opcional: coloque o ícone aqui e ele vai no .exe e no instalador
SCRIPT_INNO = PASTA_INSTALADOR / "WillPDV.iss"


def versao() -> str:
    sys.path.insert(0, str(RAIZ))
    from src.versao import VERSAO
    return VERSAO


def edicao_escolhida(argv: list[str]):
    """A edição pedida em `--edicao X` (ou `--edicao=X`); sem a opção, o WillPDV."""
    sys.path.insert(0, str(RAIZ))
    from src.core import edicao
    chave = edicao.PADRAO
    for i, arg in enumerate(argv):
        if arg == "--edicao" and i + 1 < len(argv):
            chave = argv[i + 1]
        elif arg.startswith("--edicao="):
            chave = arg.split("=", 1)[1]
    if chave not in edicao.EDICOES:
        sys.exit(f"Edição desconhecida: {chave}. Use uma de: {', '.join(edicao.EDICOES)}.")
    return edicao.EDICOES[chave]


def gerar_executavel(ed) -> None:
    nome = ed.executavel
    comando = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
               "--windowed",                                # sem a janela preta do CMD atrás do caixa
               "--name", nome, "--paths", str(RAIZ)]        # a raiz no caminho: os imports são "from src..."
    from src.autoteste import MODULOS
    for modulo in MODULOS:
        comando += ["--hidden-import", modulo]
    comando += ["--collect-data", "tzdata"]  # fuso de Brasília também no Windows
    icone = PASTA_INSTALADOR / ed.icone
    if icone.exists():
        # --icon: ícone do .exe; --add-data: o mesmo arquivo dentro do pacote, para as janelas do programa
        comando += ["--icon", str(icone), "--add-data", f"{icone}{os.pathsep}."]
    if ed.logotipo and (PASTA_INSTALADOR / ed.logotipo).exists():
        comando += ["--add-data", f"{PASTA_INSTALADOR / ed.logotipo}{os.pathsep}."]      # logotipo no alto do menu
    web_porteiro = RAIZ / "src" / "porteiro" / "web"
    comando += ["--add-data", f"{web_porteiro}{os.pathsep}porteiro_web"]                 # página do porteiro no celular
    comando.append(str(RAIZ / "src" / "app.py"))
    subprocess.run(comando, check=True, cwd=RAIZ)
    destino = RAIZ / "dist" / nome
    (destino / "edicao.txt").write_text(ed.chave + "\n", encoding="utf-8")       # o programa sabe qual edição é
    copiar_licencas(destino)
    print(f"Executável pronto: {destino / (nome + '.exe')}")


def copiar_licencas(destino: Path) -> None:
    pasta = destino / "licencas"
    pasta.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RAIZ / "docs" / "TERCEIROS_QT.md", pasta / "TERCEIROS_QT.md")
    for arquivo in (RAIZ / "instalador" / "licencas").glob("*.txt"):
        shutil.copyfile(arquivo, pasta / arquivo.name)
    manifesto = []
    for nome in ("PySide6-Essentials", "shiboken6", "cryptography", "cffi", "Pillow", "segno"):
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


def gerar_instalador(ed) -> None:
    script = PASTA_INSTALADOR / ed.script_instalador
    iscc = achar_iscc()
    if iscc is None:
        print("Inno Setup não encontrado: instale o Inno Setup 6 (ou defina a variável ISCC com o caminho do ISCC.exe) "
              f"e rode de novo, ou abra instalador/{script.name} no Inno Setup e clique em Compile.")
        return
    icone = PASTA_INSTALADOR / ed.icone
    definicoes = [f"/DVersao={versao()}"] + ([f"/DIcone={icone}"] if icone.exists() else [])
    subprocess.run([iscc, *definicoes, str(script)], check=True, cwd=RAIZ)
    print(f"Instalador pronto em {RAIZ / 'instalador' / 'saida'}")


if __name__ == "__main__":
    edicao_programa = edicao_escolhida(sys.argv[1:])
    print(f"Gerando o {edicao_programa.nome} {versao()}...")
    try:
        gerar_executavel(edicao_programa)
        if "--sem-instalador" not in sys.argv[1:]:
            if os.name == "nt":
                gerar_instalador(edicao_programa)
            else:
                print("O instalador (Inno Setup) só é gerado no Windows.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"Erro no build: {e}")
