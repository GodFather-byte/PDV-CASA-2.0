"""Ponto de entrada do WillPDV Licenças:  python -m licenciador.app   (ou WillLicencas.exe)

Com `--autoteste [arquivo]` confere se o programa está inteiro (ver licenciador/autoteste.py) e encerra.
"""
import sys

if __name__ == "__main__":
    if "--autoteste" in sys.argv[1:]:
        from licenciador.autoteste import executar
        resto = [a for a in sys.argv[1:] if not a.startswith("--")]
        sys.exit(executar(resto[0] if resto else None))
    from licenciador.tela import main
    main()
