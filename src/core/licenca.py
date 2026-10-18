"""Licença mensal offline do PDV (assinatura Ed25519).

O fornecedor emite um código assinado com a loja e o último dia de validade (ferramenta
`tools/gerar_licenca.py`). O PDV só carrega a chave PÚBLICA: ler o código-fonte não permite emitir
licença. O código fica no banco e é revalidado a cada entrada, então editar o banco não estende o prazo.

Para uma falha de licença nunca parar a loja no meio do serviço:
  * `AVISO_DIAS` antes do vencimento a entrada passa a avisar;
  * depois do vencimento há `CARENCIA_DIAS` de uso normal, com aviso;
  * só depois disso a entrada é bloqueada, e nunca com um turno aberto RECENTE (o operador consegue fechá-lo);
    abrir um turno novo com a licença bloqueada é recusado pelo TurnoController;
  * voltar o relógio do Windows não reabre o prazo (vale a maior data já vista); essa data avança no máximo
    SALTO_MAXIMO_DIAS por uso, para uma data errada no futuro não travar a loja de vez.

A exigência só vale no executável (PyInstaller) ou com `licenca_exigir = S` nas configurações;
rodando do código-fonte, como no desenvolvimento e nos testes, o sistema não pede licença.
"""
from __future__ import annotations

import base64
import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta

from src.core import ed25519
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

PREFIXO = "PDVL1"
# Trocar esta chave invalida todos os códigos já emitidos: gere o par uma única vez
# (`python -m tools.gerar_licenca novo-par`) e guarde a chave privada fora do repositório.
CHAVE_PUBLICA_HEX = "e02c6389919a7f2dd1876a4acba0651d0779ef58ac59a3cd73efdc88d278b6aa"
AVISO_DIAS = 7
CARENCIA_DIAS = 5
MAX_DIAS = 36500       # validade máxima de um código (100 anos = licença permanente)
SALTO_MAXIMO_DIAS = 3   # a "última data vista" avança no máximo isto por uso (ver registrar_uso)


class LicencaInvalida(ErroNegocio):
    """Código ilegível, adulterado ou de outra loja."""


class LicencaExpirada(ErroNegocio):
    """Código válido, porém já vencido."""


@dataclass(frozen=True)
class Estado:
    situacao: str            # desativada | ok | aviso | carencia | bloqueada | sem_licenca
    expira_em: date | None = None
    dias: int | None = None  # dias até o vencimento (negativo = vencida há N dias)
    mensagem: str = ""

    @property
    def bloqueia(self) -> bool:
        return self.situacao in ("bloqueada", "sem_licenca")

    @property
    def avisa(self) -> bool:
        return self.situacao in ("aviso", "carencia")


# ----------------------------------------------------------------- código
def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode("ascii").rstrip("=")


def _b64_decodificar(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def gerar_licenca(semente: bytes, loja: str, dias: int, hoje: date | None = None) -> str:
    """Código válido até `hoje + dias` (inclusive). Uso exclusivo do fornecedor, com a chave privada."""
    loja = (loja or "").strip()
    if not loja:
        raise ValueError("Informe a chave da loja.")
    if dias < 1:
        raise ValueError("A validade deve ser de pelo menos 1 dia.")
    if dias > MAX_DIAS:
        raise ValueError(f"A validade máxima é {MAX_DIAS} dias (use --permanente).")
    hoje = hoje or date.today()
    dados = {"loja": loja, "emitida_em": hoje.isoformat(), "expira_em": (hoje + timedelta(days=dias)).isoformat()}
    corpo = f"{PREFIXO}.{_b64(json.dumps(dados, separators=(',', ':'), sort_keys=True).encode('utf-8'))}"
    return f"{corpo}.{_b64(ed25519.assinar(semente, corpo.encode('ascii')))}"


def ler_licenca(codigo: str, chave_publica: bytes | None = None) -> dict:
    """Confere a assinatura e devolve {'loja', 'emitida_em', 'expira_em'}. Não olha o prazo nem a loja."""
    partes = "".join((codigo or "").split()).split(".")
    if len(partes) != 3 or partes[0] != PREFIXO:
        raise LicencaInvalida("Formato de licença inválido. Cole o código inteiro, sem espaços extras.")
    try:
        assinatura = _b64_decodificar(partes[2])
        carga = _b64_decodificar(partes[1])
    except (ValueError, UnicodeError):
        raise LicencaInvalida("Formato de licença inválido. Cole o código inteiro, sem espaços extras.") from None
    publica = chave_publica if chave_publica is not None else bytes.fromhex(CHAVE_PUBLICA_HEX)
    if not ed25519.verificar(publica, f"{partes[0]}.{partes[1]}".encode("ascii"), assinatura):
        raise LicencaInvalida("A assinatura da licença não confere. Confira se o código foi copiado inteiro.")
    try:
        dados = json.loads(carga)
        return {"loja": str(dados["loja"]), "emitida_em": date.fromisoformat(dados["emitida_em"]),
                "expira_em": date.fromisoformat(dados["expira_em"])}
    except (ValueError, KeyError, TypeError):
        raise LicencaInvalida("Os dados da licença estão ilegíveis.") from None


# ------------------------------------------------------------------ estado
def exigida(banco) -> bool:
    """No executável é sempre exigida (o banco local não desliga); no código-fonte, só com licenca_exigir = S."""
    if getattr(sys, "frozen", False):
        return True
    return banco.cfg("licenca_exigir").strip().upper() in ("S", "1", "SIM", "TRUE")


def mesma_loja(a: str, b: str) -> bool:
    """Nome da loja sem diferenciar maiúsculas de minúsculas nem espaços nas pontas (digitar Boate-X no lugar de BOATE-X
    não pode fazer a renovação ser recusada na frente do operador)."""
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def _data(texto: str) -> date | None:
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def _ultimo_registro(banco) -> date | None:
    """Data do movimento mais recente da loja (venda encerrada ou turno aberto). Voltar o relógio para antes dela
    exigiria adulterar o histórico de vendas e turnos, não só apagar ou editar a linha `licenca_ultimo_uso`."""
    datas = [_data(str(banco.valor(sql) or "")[:10]) for sql in (
        "SELECT MAX(fechada_em) FROM vendas", "SELECT MAX(aberto_em) FROM turnos")]
    datas = [d for d in datas if d]
    return max(datas) if datas else None


def _hoje(banco, hoje: date | None) -> date:
    """Data de hoje, mas nunca anterior à última vista nem ao movimento mais recente da loja (relógio atrasado não
    reabre o prazo). A data errada no futuro só pesa aqui se a loja chegou a vender com ela."""
    atual = hoje or date.fromisoformat(fmt.hoje())
    vistas = [d for d in (_data(banco.cfg("licenca_ultimo_uso")), _ultimo_registro(banco)) if d]
    return max([atual, *vistas])


def _br(dia: date) -> str:
    return dia.strftime("%d/%m/%Y")


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def estado(banco, hoje: date | None = None, chave_publica: bytes | None = None) -> Estado:
    if not exigida(banco):
        return Estado("desativada")
    codigo = banco.cfg("licenca_token").strip()
    if not codigo:
        return Estado("sem_licenca", mensagem="Nenhuma licença ativada neste caixa.")
    try:
        lic = ler_licenca(codigo, chave_publica)
    except LicencaInvalida as e:
        return Estado("sem_licenca", mensagem=f"A licença guardada neste caixa é inválida. {e}")
    loja = banco.cfg("chave_loja").strip()
    if loja and not mesma_loja(lic["loja"], loja):
        return Estado("sem_licenca", mensagem="A licença guardada neste caixa pertence a outra loja.")
    venc = lic["expira_em"]
    dias = (venc - _hoje(banco, hoje)).days
    if dias > AVISO_DIAS:
        return Estado("ok", venc, dias)
    if dias >= 0:
        quando = "vence hoje" if dias == 0 else f"vence em {_plural(dias, 'dia', 'dias')}"
        return Estado("aviso", venc, dias, f"A licença {quando} ({_br(venc)}). Peça o código de renovação ao fornecedor.")
    if dias >= -CARENCIA_DIAS:
        restam = CARENCIA_DIAS + dias + 1
        return Estado("carencia", venc, dias,
                      f"A licença venceu em {_br(venc)}. O uso segue liberado por mais "
                      f"{_plural(restam, 'dia', 'dias')}; renove para evitar o bloqueio.")
    return Estado("bloqueada", venc, dias, f"A licença venceu em {_br(venc)} e o prazo de carência terminou.")


def registrar_uso(banco, hoje: date | None = None) -> None:
    """Guarda a maior data vista (para detectar relógio voltado). Avança no máximo SALTO_MAXIMO_DIAS por vez:
    uma data digitada no futuro por engano não trava a loja, porque ao corrigir o relógio a licença volta ao normal."""
    atual = hoje or date.fromisoformat(fmt.hoje())
    ultimo = _data(banco.cfg("licenca_ultimo_uso"))
    novo = atual if ultimo is None else max(ultimo, min(atual, ultimo + timedelta(days=SALTO_MAXIMO_DIAS)))
    banco.cfg_set("licenca_ultimo_uso", novo.isoformat())


def turno_vale_como_isencao(banco, turno: dict | None, hoje: date | None = None) -> bool:
    """Turno aberto que deixa a loja terminar o serviço com a licença bloqueada. Precisa ser recente (aberto no
    máximo 1 dia antes da última data vista): um turno esquecido ou inserido à mão não desliga a licença."""
    if not turno:
        return False
    aberto = _data(str(turno.get("aberto_em") or "")[:10])
    return aberto is not None and aberto >= _hoje(banco, hoje) - timedelta(days=1)


def _guardada(banco, chave_publica: bytes | None) -> dict | None:
    """A licença guardada, só se ainda validar (assinatura e loja); senão None."""
    try:
        lic = ler_licenca(banco.cfg("licenca_token"), chave_publica)
    except LicencaInvalida:
        return None
    loja = banco.cfg("chave_loja").strip()
    return lic if not loja or mesma_loja(lic["loja"], loja) else None


def ativar(banco, codigo: str, hoje: date | None = None, chave_publica: bytes | None = None) -> dict:
    """Valida o código digitado e o guarda. A primeira ativação também grava a chave da loja."""
    codigo = "".join((codigo or "").split())
    lic = ler_licenca(codigo, chave_publica)
    loja = banco.cfg("chave_loja").strip()
    if loja and not mesma_loja(lic["loja"], loja):
        raise LicencaInvalida(f"Esta licença é da loja '{lic['loja']}', e este caixa está configurado como '{loja}'.")
    if lic["expira_em"] < _hoje(banco, hoje):
        raise LicencaExpirada(f"Esta licença já venceu em {_br(lic['expira_em'])}.")
    anterior = _guardada(banco, chave_publica)       # só vale como comparação se ainda validar (chave ou loja trocada, não)
    if anterior and mesma_loja(anterior["loja"], lic["loja"]) and lic["expira_em"] < anterior["expira_em"]:
        raise LicencaInvalida(f"Esta licença é mais antiga que a atual (válida até {_br(anterior['expira_em'])}).")
    with banco.transacao():
        banco.cfg_set("licenca_token", codigo)         # o prazo vem sempre do código assinado, nunca de outra linha do banco
        registrar_uso(banco, hoje)
        if not loja:
            banco.cfg_set("chave_loja", lic["loja"])
        banco.log("licenca_ativada", f"loja {lic['loja']} válida até {lic['expira_em'].isoformat()}")
    return lic
