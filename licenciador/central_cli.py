"""Administração local da central; nenhuma credencial administrativa é aceita pelo bot."""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from licenciador.central import Central, ClientePonte, ErroCentral, caminho_padrao
from licenciador.central_bot import servir
from src.core.erros import ErroNegocio


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WillPDV Central exclusiva do fornecedor")
    parser.add_argument("--banco", type=Path, default=caminho_padrao())
    comandos = parser.add_subparsers(dest="comando", required=True)
    cad = comandos.add_parser("loja")
    cad.add_argument("chave")
    cad.add_argument("nome")
    cad.add_argument("--desativada", action="store_true")
    admin = comandos.add_parser("administrador")
    admin.add_argument("chat_id", type=int)
    admin.add_argument("--remover", action="store_true")
    importar = comandos.add_parser("importar")
    importar.add_argument("historico", type=Path)
    caixa = comandos.add_parser("aprovar-caixa")
    caixa.add_argument("loja")
    caixa.add_argument("caixa_id")
    revogar = comandos.add_parser("revogar-caixa")
    revogar.add_argument("caixa_id")
    publicar = comandos.add_parser("publicar-loja")
    publicar.add_argument("loja")
    backup = comandos.add_parser("backup")
    backup.add_argument("destino", type=Path)
    restaurar = comandos.add_parser("restaurar")
    restaurar.add_argument("origem", type=Path)
    comandos.add_parser("sincronizar")
    comandos.add_parser("listar")
    comandos.add_parser("servir")
    args = parser.parse_args(argumentos)
    central = None
    try:
        if args.comando == "restaurar":
            Central.restaurar(args.origem, args.banco)
            print("Backup restaurado em banco novo. Confira administradores antes de iniciar.")
            return 0
        ponte = None
        if args.comando in ("aprovar-caixa", "revogar-caixa", "sincronizar", "servir"):
            ponte = ClientePonte(os.environ.get("WILLCENTRAL_API_URL", ""),
                                 os.environ.get("PDV_CENTRAL_TOKEN", ""))
        central = Central(args.banco, ponte)
        if args.comando == "loja":
            central.cadastrar(args.chave, args.nome, not args.desativada)
            print("Cadastro local salvo. Sincronize para atualizar a ponte.")
        elif args.comando == "administrador":
            central.administrador(args.chat_id, args.remover)
            print("Autorização local atualizada.")
        elif args.comando == "importar":
            print(f"Licenças importadas: {central.importar_historico(args.historico)}. Original preservado.")
        elif args.comando == "aprovar-caixa":
            token = central.provisionar(args.loja, args.caixa_id)
            print("Credencial exibida uma única vez. Configure localmente no caixa; não envie pelo bot:")
            print(token)
        elif args.comando == "revogar-caixa":
            central.revogar_caixa(args.caixa_id)
            print("Credencial do caixa revogada. Isso não apaga sua licença instalada.")
        elif args.comando == "publicar-loja":
            identificador = central.autorizar_publicacao(args.loja)
            print(f"Publicação autorizada: {identificador}. Sincronize para migrar a entrega dessa loja.")
        elif args.comando == "backup":
            central.backup(args.destino)
            print("Backup verificado. A chave privada precisa de backup criptografado separado no licenciador.")
        elif args.comando == "sincronizar":
            central.sincronizar()
            print("Sincronização concluída; confirme aplicação por caixa no painel.")
        elif args.comando == "listar":
            for loja in central.lojas():
                print(f"{loja['chave']} — {loja['nome']} — validade {loja['validade'] or 'sem licença'}")
        elif args.comando == "servir":
            servir(central, os.environ.get("WILLCENTRAL_TELEGRAM_TOKEN", ""))
        return 0
    except (ErroNegocio, OSError) as erro:
        print(f"Central: {erro}")
        return 1
    except sqlite3.Error:
        print("Central: falha no banco local. Confira acesso, espaço livre e integridade do arquivo.")
        return 1
    finally:
        if central:
            central.fechar()


if __name__ == "__main__":
    raise SystemExit(main())
