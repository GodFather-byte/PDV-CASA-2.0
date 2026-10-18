"""Arquivos de backup autenticados; a senha de recuperação nunca vai para o banco."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

CABECALHO = b"WILLPDV-BKP\x01"
BLOCO = 1024 * 1024
TAMANHO_SAL = 16
TAMANHO_NONCE = 12
TAMANHO_TAG = 16
EXTENSAO = ".pdvbkp"


def validar_senha(senha: str) -> str:
    if not isinstance(senha, str) or not 12 <= len(senha) <= 1024:
        raise ValueError("Use uma senha de recuperação de 12 a 1024 caracteres.")
    return senha


def _chave(senha: str, sal: bytes) -> bytes:
    validar_senha(senha)
    return Scrypt(salt=sal, length=32, n=2**15, r=8, p=1).derive(senha.encode("utf-8"))


def _temporario(destino: Path) -> Path:
    return destino.with_name(f".{destino.name}.{uuid4().hex}.tmp")


def criptografar(origem: str | Path, destino: str | Path, senha: str) -> None:
    """Publica apenas arquivo cifrado completo, sem criar texto aberto na pasta externa."""
    origem, destino = Path(origem), Path(destino)
    sal, nonce = os.urandom(TAMANHO_SAL), os.urandom(TAMANHO_NONCE)
    cabecalho = CABECALHO + sal + nonce
    cifrador = Cipher(algorithms.AES(_chave(senha, sal)), modes.GCM(nonce)).encryptor()
    cifrador.authenticate_additional_data(cabecalho)
    temporario = _temporario(destino)
    try:
        with origem.open("rb") as entrada, temporario.open("xb") as saida:
            saida.write(cabecalho)
            while dados := entrada.read(BLOCO):
                saida.write(cifrador.update(dados))
            saida.write(cifrador.finalize())
            saida.write(cifrador.tag)
            saida.flush()
            os.fsync(saida.fileno())
        os.replace(temporario, destino)
    finally:
        temporario.unlink(missing_ok=True)


def descriptografar(origem: str | Path, destino: str | Path, senha: str) -> None:
    """Destino deve ser local: só publica o conteúdo depois de autenticar o arquivo inteiro."""
    origem, destino = Path(origem), Path(destino)
    tamanho_cabecalho = len(CABECALHO) + TAMANHO_SAL + TAMANHO_NONCE
    temporario = _temporario(destino)
    try:
        with origem.open("rb") as entrada:
            tamanho = os.fstat(entrada.fileno()).st_size
            if tamanho < tamanho_cabecalho + TAMANHO_TAG:
                raise ValueError("Backup criptografado incompleto.")
            cabecalho = entrada.read(tamanho_cabecalho)
            if not cabecalho.startswith(CABECALHO):
                raise ValueError("Formato ou versão de backup criptografado não suportado.")
            sal = cabecalho[len(CABECALHO):len(CABECALHO) + TAMANHO_SAL]
            nonce = cabecalho[-TAMANHO_NONCE:]
            entrada.seek(-TAMANHO_TAG, os.SEEK_END)
            tag = entrada.read(TAMANHO_TAG)
            entrada.seek(tamanho_cabecalho)
            decifrador = Cipher(algorithms.AES(_chave(senha, sal)), modes.GCM(nonce, tag)).decryptor()
            decifrador.authenticate_additional_data(cabecalho)
            restantes = tamanho - tamanho_cabecalho - TAMANHO_TAG
            with temporario.open("xb") as saida:
                while restantes:
                    dados = entrada.read(min(BLOCO, restantes))
                    if not dados:
                        raise ValueError("Backup criptografado incompleto.")
                    saida.write(decifrador.update(dados))
                    restantes -= len(dados)
                saida.write(decifrador.finalize())
                saida.flush()
                os.fsync(saida.fileno())
        os.replace(temporario, destino)
    except InvalidTag:
        raise ValueError("Senha incorreta ou backup criptografado alterado/danificado.") from None
    finally:
        temporario.unlink(missing_ok=True)


def _dpapi(dados: bytes, proteger: bool) -> bytes:
    if os.name != "nt":
        raise ValueError("O armazenamento automático da senha usa a proteção do usuário do Windows.")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("tamanho", wintypes.DWORD), ("dados", ctypes.POINTER(ctypes.c_ubyte))]

    biblioteca = ctypes.WinDLL("crypt32", use_last_error=True)
    sistema = ctypes.WinDLL("kernel32", use_last_error=True)
    liberar = sistema.LocalFree
    liberar.argtypes = [ctypes.c_void_p]
    liberar.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(dados)
    entrada = Blob(len(dados), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    saida = Blob()
    funcao = biblioteca.CryptProtectData if proteger else biblioteca.CryptUnprotectData
    funcao.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    funcao.restype = wintypes.BOOL
    if not funcao(ctypes.byref(entrada), None, None, None, None, 1, ctypes.byref(saida)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(saida.dados, saida.tamanho)
    finally:
        liberar(ctypes.cast(saida.dados, ctypes.c_void_p))


def guardar_senha(caminho: str | Path, senha: str) -> None:
    """DPAPI vincula o segredo ao usuário Windows; outra máquina precisa da senha original."""
    protegido = _dpapi(validar_senha(senha).encode("utf-8"), True)
    caminho = Path(caminho)
    temporario = _temporario(caminho)
    try:
        with temporario.open("xb") as arquivo:
            arquivo.write(protegido)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, caminho)
    finally:
        temporario.unlink(missing_ok=True)


def ler_senha(caminho: str | Path) -> str:
    return validar_senha(_dpapi(Path(caminho).read_bytes(), False).decode("utf-8"))
