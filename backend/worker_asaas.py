"""Entrada do worker durável; não inicia processos junto ao servidor HTTP."""
from backend.operacao_asaas import main

if __name__ == "__main__":
    raise SystemExit(main())
