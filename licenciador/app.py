"""Ponto de entrada do WillPDV Licenças:  python -m licenciador.app   (ou WillLicencas.exe)

Com `--autoteste [arquivo]` confere se o programa está inteiro (ver licenciador/autoteste.py) e encerra.
"""
import sys

if __name__ == "__main__":
    if "--central" in sys.argv[1:]:
        from licenciador.central_tela import main as abrir_central
        abrir_central()
        sys.exit(0)
    if "--central-cli" in sys.argv[1:]:
        from licenciador.central_cli import main as central_cli
        sys.exit(central_cli(sys.argv[sys.argv.index("--central-cli") + 1:]))
    if "--autoteste" in sys.argv[1:]:
        from licenciador.autoteste import executar
        resto = [a for a in sys.argv[1:] if not a.startswith("--")]
        sys.exit(executar(resto[0] if resto else None))
    from licenciador.tela import main
    main()
