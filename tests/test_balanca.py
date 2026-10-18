"""Leitura da balança serial (Toledo/Filizola) sem hardware: a porta é simulada."""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from src.hardware.dispositivos import Balanca, DispositivoIndisponivel


def serial_falso(resposta: bytes):
    mod = types.ModuleType("serial")

    class SerialException(Exception):
        pass

    class Serial:
        def __init__(self, *a, **kw):
            self.escrito = b""

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def flushInput(self):
            pass

        def write(self, dado):
            self.escrito += dado

        def read(self, n):
            return resposta

    mod.Serial, mod.SerialException = Serial, SerialException
    return mod


class TesteBalanca(unittest.TestCase):
    def ler(self, resposta, modelo="Toledo"):
        with mock.patch.dict(sys.modules, {"serial": serial_falso(resposta)}), mock.patch("time.sleep"):
            return Balanca(modelo, "COM1").ler_peso()

    def test_peso_do_protocolo_toledo(self):
        self.assertEqual(self.ler(b"\x0201234\x03"), 1.234)
        self.assertEqual(self.ler(b"lixo\x02012500\x03"), 12.5)

    def test_resposta_irreconhecivel_ou_vazia(self):
        with self.assertRaises(DispositivoIndisponivel):
            self.ler(b"\x02ABCDE\x03")
        with self.assertRaisesRegex(DispositivoIndisponivel, "não respondeu"):
            self.ler(b"")

    def test_sem_pyserial_avisa_em_vez_de_quebrar(self):
        with mock.patch.dict(sys.modules, {"serial": None}):
            with self.assertRaisesRegex(DispositivoIndisponivel, "pyserial"):
                Balanca("Toledo", "COM1").ler_peso()

    def test_nao_configurada(self):
        with self.assertRaises(DispositivoIndisponivel):
            Balanca().ler_peso()


if __name__ == "__main__":
    unittest.main()
