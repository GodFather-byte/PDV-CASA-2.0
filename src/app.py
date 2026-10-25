"""Ponto de entrada do PDV: python -m src.app  (ou iniciar_pdv.bat no Windows).

Com `--sync` roda só a verificação de licença e de versão nova na nuvem (sem janela), a partir do mesmo programa:
python -m src.app --sync   ou   WillPDV.exe --sync

Com `--autoteste [arquivo] [--rede]` confere se o programa instalado está inteiro (ver src/autoteste.py) e encerra.
Com `--homologacao [arquivo.json]` exercita retomada e fechamento em banco descartável, sem hardware.
Com `--edicao ea_superacoes` abre a edição E&A Superações (adega) em vez do WillPDV (ver src/core/edicao.py).
A interface é Qt (PySide6).
"""
import os
import sys


def _tirar_edicao(argv: list[str]) -> list[str]:
    """`--edicao X` (ou `--edicao=X`) vira a variável PDV_EDICAO e sai dos argumentos (o X não é o arquivo do autoteste)."""
    resto, i = [], 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--edicao" and i + 1 < len(argv):
            os.environ["PDV_EDICAO"] = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--edicao="):
            os.environ["PDV_EDICAO"] = arg.split("=", 1)[1]
        else:
            resto.append(arg)
        i += 1
    return resto


if __name__ == "__main__":
    sys.argv[1:] = _tirar_edicao(sys.argv[1:])
    if "--homologacao" in sys.argv[1:]:
        from src.homologacao import executar
        resto = [a for a in sys.argv[1:] if not a.startswith("--")]
        sys.exit(executar(resto[0] if resto else None))
    if "--autoteste-qt" in sys.argv[1:]:
        from src.autoteste_qt import executar
        resto = [a for a in sys.argv[1:] if not a.startswith("--")]
        sys.exit(executar(resto[0] if resto else None))
    if "--autoteste" in sys.argv[1:]:
        from src.autoteste import executar
        resto = [a for a in sys.argv[1:] if not a.startswith("--")]
        sys.exit(executar(resto[0] if resto else None, rede="--rede" in sys.argv[1:]))
    if "--sync" in sys.argv[1:]:
        from src.sync.sincronizador import main as sincronizar
        sincronizar()
    else:
        from src.ui_qt.app import main
        main()
