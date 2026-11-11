"""Ferramenta do FORNECEDOR: gera o par de chaves e os códigos de licença mensal do PDV.

Não faz parte do instalador. A chave privada fica FORA do repositório (padrão:
~/.pdv-casa/licenca_privada.key ou o arquivo indicado em PDV_LICENCA_CHAVE) e nunca deve ser enviada ao cliente.

  python -m tools.gerar_licenca novo-par                           # uma única vez
  python -m tools.gerar_licenca emitir --loja CASAVERDE-01 --dias 30
  python -m tools.gerar_licenca emitir --loja CASAVERDE-01 --permanente     # sem vencimento na prática (100 anos)
  python -m tools.gerar_licenca emitir --loja ADEGA-01 --dias 30 --edicao willadega   # licença do Will Adega
  python -m tools.gerar_licenca ver CODIGO
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

from src.core import ed25519, edicao, licenca


DIAS_PERMANENTE = licenca.MAX_DIAS


def _arquivo_padrao() -> Path:
    return Path(os.environ.get("PDV_LICENCA_CHAVE") or Path.home() / ".pdv-casa" / "licenca_privada.key")


def _ler_semente(arquivo: Path) -> bytes:
    try:
        semente = bytes.fromhex(arquivo.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        raise SystemExit(f"Não foi possível ler a chave privada em {arquivo}. Rode 'novo-par' ou use --arquivo.") from None
    if len(semente) != 32:
        raise SystemExit(f"A chave privada em {arquivo} deve ter 32 bytes (64 caracteres hexadecimais).")
    return semente


def novo_par(arquivo: Path) -> None:
    if arquivo.exists():
        raise SystemExit(f"Já existe uma chave em {arquivo}. Não vou sobrescrever: trocar a chave invalida todas as licenças emitidas.")
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    semente = secrets.token_bytes(32)
    arquivo.write_text(semente.hex() + "\n", encoding="ascii")
    try:
        os.chmod(arquivo, 0o600)
    except OSError:
        pass
    print(f"Chave privada gravada em: {arquivo}  (faça backup e NUNCA coloque no repositório)")
    print("Chave pública (cole em CHAVE_PUBLICA_HEX, em src/core/licenca.py, e gere o instalador de novo):")
    print(ed25519.chave_publica(semente).hex())


def emitir(arquivo: Path, loja: str, dias: int, edicao_programa: str = edicao.PADRAO) -> None:
    semente = _ler_semente(arquivo)
    if ed25519.chave_publica(semente).hex() != licenca.CHAVE_PUBLICA_HEX:
        raise SystemExit("Esta chave privada não corresponde à CHAVE_PUBLICA_HEX de src/core/licenca.py; "
                         "os clientes rejeitariam o código.")
    codigo = licenca.gerar_licenca(semente, loja, dias, edicao_programa=edicao_programa)
    lic = licenca.ler_licenca(codigo)
    print(f"Loja: {lic['loja']}\nPrograma: {licenca.nome_da_edicao(lic['edicao'])}\nVálida até: {lic['expira_em'].strftime('%d/%m/%Y')} (inclusive)\n\n{codigo}")


def recuperar_senha(arquivo: Path, loja: str, pedido: str, horas: int) -> None:
    """Gerente esqueceu a senha: assina a liberação do pedido que o caixa mostra em "Esqueci a senha"."""
    from src.core import recuperacao_senha
    semente = _ler_semente(arquivo)
    if ed25519.chave_publica(semente).hex() != licenca.CHAVE_PUBLICA_HEX:
        raise SystemExit("Esta chave privada não corresponde à CHAVE_PUBLICA_HEX de src/core/licenca.py; "
                         "o caixa rejeitaria a liberação.")
    codigo = recuperacao_senha.gerar_liberacao(semente, loja, pedido, horas=horas)
    dados = recuperacao_senha.ler_liberacao(codigo)
    print(f"Loja: {dados['loja'] or '(sem chave de loja)'}\nPedido: {recuperacao_senha.formatar_pedido(dados['pedido'])}\n"
          f"Vale até: {dados['expira_em'].strftime('%d/%m/%Y %H:%M')}\n\n{codigo}")


def ver(codigo: str) -> None:
    lic = licenca.ler_licenca(codigo)
    print(f"Assinatura OK. Loja: {lic['loja']} | programa {licenca.nome_da_edicao(lic['edicao'])} | emitida em {lic['emitida_em'].strftime('%d/%m/%Y')} "
          f"| válida até {lic['expira_em'].strftime('%d/%m/%Y')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("novo-par", help="cria a chave privada e mostra a pública")
    p.add_argument("--arquivo", type=Path, default=None)
    p = sub.add_parser("emitir", help="gera o código de licença de uma loja")
    p.add_argument("--loja", required=True, help="chave da loja (a mesma de Configurações > Nuvem)")
    p.add_argument("--dias", type=int, default=30)
    p.add_argument("--permanente", action="store_true", help=f"sem vencimento na prática: {DIAS_PERMANENTE} dias (100 anos)")
    p.add_argument("--edicao", choices=sorted(edicao.EDICOES), default=edicao.PADRAO,
                   help="para qual programa (willpdv ou willadega); a licença só abre esse")
    p.add_argument("--arquivo", type=Path, default=None)
    p = sub.add_parser("recuperar-senha", help="libera a troca da senha de um gerente que esqueceu (pedido do caixa)")
    p.add_argument("--loja", required=True, help="chave da loja; use \"\" para uma instalação sem chave de loja")
    p.add_argument("--pedido", required=True, help="o pedido que aparece no caixa, ex.: K7QF-3MZD")
    p.add_argument("--horas", type=int, default=24, help="por quanto tempo a liberação vale (1 a 72)")
    p.add_argument("--arquivo", type=Path, default=None)
    p = sub.add_parser("ver", help="confere a assinatura de um código")
    p.add_argument("codigo")
    args = ap.parse_args(argv)
    try:
        if args.comando == "novo-par":
            novo_par(args.arquivo or _arquivo_padrao())
        elif args.comando == "emitir":
            emitir(args.arquivo or _arquivo_padrao(), args.loja, DIAS_PERMANENTE if args.permanente else args.dias, args.edicao)
        elif args.comando == "recuperar-senha":
            recuperar_senha(args.arquivo or _arquivo_padrao(), args.loja, args.pedido, args.horas)
        else:
            ver(args.codigo)
    except (ValueError, licenca.LicencaInvalida) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
