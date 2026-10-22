"""Endurecimento pós-auditoria: vetores oficiais do Ed25519, hash de senha e nomes SQL."""
from __future__ import annotations

import hashlib
import unittest

from src.controllers.acesso_controller import AcessoController
from src.core import ed25519, seguranca
from src.core import formatacao as fmt
from tests.base import BaseTeste

# RFC 8032, seção 7.1 (semente, chave pública, mensagem, assinatura).
VETORES = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]


class TestEd25519Rfc8032(unittest.TestCase):
    def test_vetores_oficiais(self):
        for semente, publica, msg, assinatura in VETORES:
            semente, publica, msg, assinatura = map(bytes.fromhex, (semente, publica, msg, assinatura))
            self.assertEqual(ed25519.chave_publica(semente), publica)
            self.assertEqual(ed25519.assinar(semente, msg), assinatura)
            self.assertTrue(ed25519.verificar(publica, msg, assinatura))

    def test_rejeita_mensagem_ou_assinatura_adulterada(self):
        semente, publica, msg, assinatura = map(bytes.fromhex, VETORES[1])
        self.assertFalse(ed25519.verificar(publica, b"\x73", assinatura))
        ruim = bytearray(assinatura)
        ruim[10] ^= 1
        self.assertFalse(ed25519.verificar(publica, msg, bytes(ruim)))
        self.assertFalse(ed25519.verificar(publica, msg, assinatura[:-1]))


class TestSenhaIteracoes(BaseTeste):
    def _hash_antigo(self, senha: str, iteracoes: int = 60_000) -> str:
        sal = b"\x01" * 16
        h = hashlib.pbkdf2_hmac("sha256", senha.upper().encode(), sal, iteracoes)
        return f"pbkdf2${iteracoes}${sal.hex()}${h.hex()}"

    def test_hash_novo_usa_iteracoes_atuais(self):
        armazenado = seguranca.gerar_hash("abc")
        self.assertFalse(seguranca.precisa_atualizar(armazenado))
        self.assertTrue(seguranca.conferir("ABC", armazenado))

    def test_hash_antigo_ainda_confere_e_pede_atualizacao(self):
        antigo = self._hash_antigo("abc")
        self.assertTrue(seguranca.conferir("abc", antigo))
        self.assertTrue(seguranca.precisa_atualizar(antigo))
        self.assertFalse(seguranca.precisa_atualizar(None))
        self.assertFalse(seguranca.precisa_atualizar("lixo"))

    def test_login_regrava_hash_antigo(self):
        op = self.banco.um("SELECT id, nome FROM operadores WHERE ativo = 1 ORDER BY id LIMIT 1")
        self.banco.executar("UPDATE operadores SET senha = ? WHERE id = ?", (self._hash_antigo("abc"), op["id"]))
        AcessoController(self.banco).autenticar(op["nome"], "abc")
        novo = self.banco.valor("SELECT senha FROM operadores WHERE id = ?", (op["id"],))
        self.assertFalse(seguranca.precisa_atualizar(novo))
        self.assertTrue(seguranca.conferir("abc", novo))

    def test_senha_errada_nao_regrava(self):
        op = self.banco.um("SELECT id, nome FROM operadores WHERE ativo = 1 ORDER BY id LIMIT 1")
        antigo = self._hash_antigo("abc")
        self.banco.executar("UPDATE operadores SET senha = ? WHERE id = ?", (antigo, op["id"]))
        with self.assertRaises(Exception):
            AcessoController(self.banco).autenticar(op["nome"], "errada")
        self.assertEqual(self.banco.valor("SELECT senha FROM operadores WHERE id = ?", (op["id"],)), antigo)


class TestIdentificadoresSql(BaseTeste):
    def test_inserir_e_atualizar_recusam_nome_malicioso(self):
        with self.assertRaises(ValueError):
            self.banco.inserir("config; DROP TABLE config", {"chave": "x"})
        with self.assertRaises(ValueError):
            self.banco.inserir("config", {"chave) VALUES ('a'); --": "x"})
        with self.assertRaises(ValueError):
            self.banco.atualizar("config", 1, {"valor = 'x', chave": "y"})

    def test_nomes_validos_seguem_funcionando(self):
        id_ = self.banco.inserir("config", {"chave": "teste_aud", "valor": "1"})
        self.assertTrue(id_)


class TestServicoPercentual(unittest.TestCase):
    def test_percentual_em_texto_sem_float(self):
        self.assertEqual(fmt.pct_de(1000, "10"), 100)
        self.assertEqual(fmt.pct_de(1005, "10"), 101)       # 100,5 -> meio para cima
        self.assertEqual(fmt.pct_de(3333, " 12.5 "), 417)


if __name__ == "__main__":
    unittest.main()
