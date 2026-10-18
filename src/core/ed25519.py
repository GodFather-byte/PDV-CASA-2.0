"""Ed25519 (RFC 8032) em Python puro, só com a biblioteca padrão.

O PDV só precisa VERIFICAR assinaturas (licença mensal). `assinar` e `chave_publica` existem para a
ferramenta do fornecedor (tools/gerar_licenca.py) e para os testes. A implementação não é de tempo
constante: serve para uso offline, nunca para assinar em um servidor exposto.
"""
from __future__ import annotations

import hashlib

_P = 2**255 - 19
_Q = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_RAIZ_DE_MENOS_1 = pow(2, (_P - 1) // 4, _P)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _hash_mod_q(dados: bytes) -> int:
    return int.from_bytes(hashlib.sha512(dados).digest(), "little") % _Q


# Pontos em coordenadas estendidas (X, Y, Z, T).
def _somar(a: tuple, b: tuple) -> tuple:
    A = (a[1] - a[0]) * (b[1] - b[0]) % _P
    B = (a[1] + a[0]) * (b[1] + b[0]) % _P
    C = 2 * a[3] * b[3] * _D % _P
    D = 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _multiplicar(escalar: int, ponto: tuple) -> tuple:
    resultado = (0, 1, 1, 0)  # elemento neutro
    while escalar > 0:
        if escalar & 1:
            resultado = _somar(resultado, ponto)
        ponto = _somar(ponto, ponto)
        escalar >>= 1
    return resultado


def _iguais(a: tuple, b: tuple) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _recuperar_x(y: int, sinal: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sinal else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _RAIZ_DE_MENOS_1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sinal:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recuperar_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _comprimir(ponto: tuple) -> bytes:
    zinv = _inv(ponto[2])
    x, y = ponto[0] * zinv % _P, ponto[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _descomprimir(dados: bytes) -> tuple | None:
    if len(dados) != 32:
        return None
    y = int.from_bytes(dados, "little")
    sinal, y = y >> 255, y & ((1 << 255) - 1)
    x = _recuperar_x(y, sinal)
    return None if x is None else (x, y, 1, x * y % _P)


def _expandir(semente: bytes) -> tuple[int, bytes]:
    if len(semente) != 32:
        raise ValueError("A chave privada (semente) deve ter 32 bytes.")
    h = hashlib.sha512(semente).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def chave_publica(semente: bytes) -> bytes:
    a, _ = _expandir(semente)
    return _comprimir(_multiplicar(a, _G))


def assinar(semente: bytes, mensagem: bytes) -> bytes:
    a, prefixo = _expandir(semente)
    publica = _comprimir(_multiplicar(a, _G))
    r = _hash_mod_q(prefixo + mensagem)
    R = _comprimir(_multiplicar(r, _G))
    h = _hash_mod_q(R + publica + mensagem)
    s = (r + h * a) % _Q
    return R + int.to_bytes(s, 32, "little")


def verificar(publica: bytes, mensagem: bytes, assinatura: bytes) -> bool:
    """True só se a assinatura for válida. Entradas malformadas devolvem False, nunca levantam erro."""
    if len(publica) != 32 or len(assinatura) != 64:
        return False
    A = _descomprimir(publica)
    R = _descomprimir(assinatura[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(assinatura[32:], "little")
    if s >= _Q:
        return False
    h = _hash_mod_q(assinatura[:32] + publica + mensagem)
    return _iguais(_multiplicar(s, _G), _somar(R, _multiplicar(h, A)))
