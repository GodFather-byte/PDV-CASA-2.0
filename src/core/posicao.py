"""Posições de consumo: comanda e mesa.

Uma comanda é uma venda de modalidade 'mesa' com comanda = 1: aparece junto das mesas, tem serviço, pré-conta e
transferência iguais, mas a numeração é própria (a comanda 2 e a mesa 2 coexistem).

O número digitado sem letra segue a configuração da loja (`posicao_padrao`); a letra C (comanda) ou M (mesa) vale sempre:

    padrao "comanda" (boate: quase tudo é comanda)     padrao "mesa" (restaurante: quase tudo é mesa)
      "123" -> comanda 123    "M5" -> mesa 5              "5" -> mesa 5    "C2" -> comanda 2
      "C123" também vale                                   "M5" também vale

O 0 é o balcão (venda sem mesa nem comanda). A tela mostra a posição na mesma notação que o operador digita.
"""
from __future__ import annotations

import re

PADROES = ("comanda", "mesa")
MAX_DIGITOS = 5                  # a comanda vai até 10 mil

_PADRAO = re.compile(r"^\s*([cCmM])?\s*(\d{1,5})\s*$")


def padrao_valido(valor) -> str:
    """'comanda' ou 'mesa'; qualquer outra coisa (config vazia ou estragada) volta para 'comanda'."""
    v = str(valor or "").strip().lower()
    return v if v in PADROES else "comanda"


def exemplos(padrao: str = "mesa") -> tuple[str, str]:
    """(como se digita a posição comum, como se digita a outra) na notação da loja: ('123', 'M5') ou ('5', 'C2')."""
    return ("123", "M5") if padrao_valido(padrao) == "comanda" else ("5", "C2")


def rotulo_do_campo(padrao: str = "mesa") -> str:
    """Título do campo da posição no caixa."""
    return "Comanda (ou M + nº da mesa)" if padrao_valido(padrao) == "comanda" else "Mesa ou comanda (ex.: 5 ou C2)"


def interpretar(texto, padrao: str = "mesa") -> tuple[bool, int]:
    """Devolve (comanda, número). Sem letra vale o `padrao` da loja; 'C2', 'c2' ou 'c 2' é comanda; 'M5' é mesa.

    Levanta ValueError se não for uma posição. O 0 é aceito como balcão (devolve (False, 0)); C0 e M0 não existem."""
    m = _PADRAO.match("" if texto is None else str(texto))
    if m is None:
        if padrao_valido(padrao) == "comanda":
            raise ValueError("Digite o número da comanda (ex.: 123) ou M e o número da mesa (ex.: M5).")
        raise ValueError("Digite o número da mesa ou C e o número da comanda (ex.: 5 ou C2).")
    letra, numero = (m.group(1) or "").upper(), int(m.group(2))
    if numero == 0:
        if letra == "C":
            raise ValueError("A comanda 0 não existe: use de 1 em diante (ex.: C2).")
        if letra == "M":
            raise ValueError("A mesa 0 não existe: use de 1 em diante (ex.: M5).")
        return False, 0
    if letra:
        return letra == "C", numero
    return padrao_valido(padrao) == "comanda", numero


def parece_comanda(texto) -> bool:
    """True para a letra C seguida de número ('C2')."""
    m = _PADRAO.match("" if texto is None else str(texto))
    return bool(m and (m.group(1) or "").upper() == "C")


def parece_posicao(texto) -> bool:
    """True para a letra C ou M seguida de número ('C2', 'M5'): o que o operador digita no campo do código, ou o leitor
    lê do cartão, para trocar de comanda ou mesa. Número sem letra é código de produto, nunca posição."""
    m = _PADRAO.match("" if texto is None else str(texto))
    return bool(m and m.group(1))


def rotulo(comanda, posicao, padrao: str = "mesa") -> str:
    """Como a posição aparece nas listas, na notação da loja: 'comanda' dá '123' e 'M5'; 'mesa' dá '5' e 'C2'."""
    if padrao_valido(padrao) == "comanda":
        return str(posicao) if comanda else f"M{posicao}"
    return f"C{posicao}" if comanda else str(posicao)


def nome(comanda, posicao) -> str:
    return f"Comanda {posicao}" if comanda else f"Mesa {posicao}"
