"""Senha de gerente esquecida: o caixa gera um pedido e só o fornecedor consegue liberar.

Fluxo:
  1. Na tela de entrada, "Esqueci a senha" cria um PEDIDO curto e aleatório (ex.: K7QF-3MZD), guardado no banco
     com validade de `HORAS_PEDIDO`.
  2. O dono passa o pedido ao fornecedor, que assina uma LIBERAÇÃO com a chave privada das licenças (central na
     nuvem ou `python -m tools.gerar_licenca recuperar-senha`). A liberação leva a loja, o pedido e um prazo.
  3. O caixa confere a assinatura com a chave PÚBLICA (a mesma da licença), a loja, o pedido e o prazo, e então
     deixa cadastrar a senha nova de um gerente. O pedido vale uma vez só.

Ler o código-fonte não permite gerar liberação: o PDV só carrega a chave pública. Editar o banco também não: o
pedido é só um número aleatório, e sem a assinatura do fornecedor ele não abre nada.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

from src.core import ed25519, licenca, seguranca
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

PREFIXO = "PDVR1"
CHAVE_PEDIDO = "recuperacao_senha_pedido"       # "PEDIDO;criado_em" nas configurações
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sem 0/O e 1/I: o pedido é ditado por telefone
TAMANHO_PEDIDO = 8
HORAS_PEDIDO = 24
HORAS_LIBERACAO = 24
NIVEL_GERENTE = 4
FORMATO = "%Y-%m-%d %H:%M:%S"


class RecuperacaoInvalida(ErroNegocio):
    """Liberação recusada: assinatura, loja, pedido ou prazo não conferem."""


# ------------------------------------------------------------------ pedido
def normalizar_pedido(texto: str) -> str:
    """'k7qf 3mzd' e 'K7QF-3MZD' são o mesmo pedido."""
    return "".join(c for c in (texto or "").upper() if c in ALFABETO)


def formatar_pedido(pedido: str) -> str:
    return f"{pedido[:4]}-{pedido[4:]}" if len(pedido) == TAMANHO_PEDIDO else pedido


def loja_desta_instalacao(banco) -> str:
    return banco.cfg("chave_loja").strip()


def _pedido_guardado(banco, agora: datetime | None = None) -> str | None:
    pedido, _, criado = banco.cfg(CHAVE_PEDIDO).partition(";")
    try:
        nascimento = datetime.strptime(criado, FORMATO)
    except ValueError:
        return None
    agora = agora or fmt.agora_dt()
    if len(pedido) != TAMANHO_PEDIDO or not (timedelta(0) <= agora - nascimento <= timedelta(hours=HORAS_PEDIDO)):
        return None
    return pedido


def pedido_atual(banco, agora: datetime | None = None) -> str:
    """O pedido em aberto desta instalação; cria um novo se não há ou se o anterior venceu."""
    agora = agora or fmt.agora_dt()
    pedido = _pedido_guardado(banco, agora)
    if pedido is None:
        pedido = "".join(secrets.choice(ALFABETO) for _ in range(TAMANHO_PEDIDO))
        banco.cfg_set(CHAVE_PEDIDO, f"{pedido};{agora.strftime(FORMATO)}")
        banco.log("senha_recuperacao_pedida", formatar_pedido(pedido))
    return pedido


# --------------------------------------------------------------- liberação
def gerar_liberacao(semente: bytes, loja: str, pedido: str, agora: datetime | None = None,
                    horas: int = HORAS_LIBERACAO) -> str:
    """Uso exclusivo do fornecedor, com a chave privada das licenças."""
    pedido = normalizar_pedido(pedido)
    if len(pedido) != TAMANHO_PEDIDO:
        raise ValueError(f"O pedido tem {TAMANHO_PEDIDO} letras e números (ex.: K7QF-3MZD). Confira com a loja.")
    if not 1 <= horas <= 72:
        raise ValueError("A liberação vale de 1 a 72 horas.")
    agora = agora or datetime.now()
    dados = {"loja": (loja or "").strip(), "pedido": pedido,
             "expira_em": (agora + timedelta(hours=horas)).strftime(FORMATO)}
    corpo = f"{PREFIXO}.{licenca._b64(json.dumps(dados, separators=(',', ':'), sort_keys=True).encode('utf-8'))}"
    return f"{corpo}.{licenca._b64(ed25519.assinar(semente, corpo.encode('ascii')))}"


def ler_liberacao(codigo: str, chave_publica: bytes | None = None) -> dict:
    """Confere a assinatura e devolve {'loja', 'pedido', 'expira_em'}. Não olha a loja, o pedido nem o prazo."""
    partes = "".join((codigo or "").split()).split(".")
    if len(partes) != 3 or partes[0] != PREFIXO:
        raise RecuperacaoInvalida("Este não é um código de liberação de senha. Cole o código inteiro.")
    try:
        assinatura = licenca._b64_decodificar(partes[2])
        carga = licenca._b64_decodificar(partes[1])
    except (ValueError, UnicodeError):
        raise RecuperacaoInvalida("Código de liberação ilegível. Cole o código inteiro, sem cortar.") from None
    publica = chave_publica if chave_publica is not None else bytes.fromhex(licenca.CHAVE_PUBLICA_HEX)
    if not ed25519.verificar(publica, f"{partes[0]}.{partes[1]}".encode("ascii"), assinatura):
        raise RecuperacaoInvalida("A assinatura da liberação não confere. Confira se o código foi copiado inteiro.")
    try:
        dados = json.loads(carga)
        return {"loja": str(dados["loja"]), "pedido": str(dados["pedido"]),
                "expira_em": datetime.strptime(dados["expira_em"], FORMATO)}
    except (ValueError, KeyError, TypeError):
        raise RecuperacaoInvalida("Os dados da liberação estão ilegíveis.") from None


def conferir(banco, codigo: str, agora: datetime | None = None, chave_publica: bytes | None = None) -> dict:
    """A liberação vale para ESTA instalação, para o pedido em aberto e ainda está no prazo?"""
    agora = agora or fmt.agora_dt()
    liberacao = ler_liberacao(codigo, chave_publica)
    loja = loja_desta_instalacao(banco)
    if not licenca.mesma_loja(liberacao["loja"], loja):
        raise RecuperacaoInvalida("Esta liberação foi emitida para outra loja.")
    pedido = _pedido_guardado(banco, agora)
    if pedido is None:
        raise RecuperacaoInvalida("O pedido deste caixa venceu. Gere um pedido novo e envie ao fornecedor.")
    if not secrets.compare_digest(liberacao["pedido"], pedido):
        raise RecuperacaoInvalida("Esta liberação é de outro pedido. Envie ao fornecedor o pedido que aparece nesta tela.")
    if agora > liberacao["expira_em"]:
        raise RecuperacaoInvalida("A liberação venceu. Peça uma nova ao fornecedor.")
    return liberacao


# ------------------------------------------------------------- senha nova
def gerentes(banco) -> list[dict]:
    """Os operadores que a recuperação pode destravar: gerentes ativos (o ADM primeiro)."""
    return [dict(r) for r in banco.todos(
        "SELECT id, nome FROM operadores WHERE ativo = 1 AND nivel >= ? ORDER BY nome <> 'ADM', nome", (NIVEL_GERENTE,))]


def redefinir(banco, codigo: str, operador_id: int, nova_senha: str, agora: datetime | None = None,
              chave_publica: bytes | None = None) -> str:
    """Com a liberação válida, grava a senha nova do gerente escolhido. Devolve o nome dele. O pedido é consumido."""
    conferir(banco, codigo, agora, chave_publica)
    operador = banco.um("SELECT id, nome FROM operadores WHERE id = ? AND ativo = 1 AND nivel >= ?",
                        (int(operador_id), NIVEL_GERENTE))
    if operador is None:
        raise ErroNegocio("Escolha um gerente ativo para receber a senha nova.")
    nova = (nova_senha or "").strip()
    if not seguranca.FORMATO_SENHA.fullmatch(nova):
        raise ErroNegocio("A senha deve ter de 1 a 10 letras ou números.")
    if seguranca.mesma_senha(nova, operador["nome"]):
        raise ErroNegocio("A senha não pode ser igual ao nome do operador.")
    with banco.transacao():
        banco.executar("UPDATE operadores SET senha = ? WHERE id = ?", (seguranca.gerar_hash(nova), operador["id"]))
        banco.cfg_set(CHAVE_PEDIDO, "")                                  # uma liberação, uma troca
        banco.executar("DELETE FROM config WHERE chave = ?", (f"tentativas:login:{operador['id']}",))   # o bloqueio por senha errada some junto
        banco.log("senha_recuperada", f"{operador['nome']} (liberação do fornecedor)", operador["id"])
    return operador["nome"]
