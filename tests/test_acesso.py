"""Senhas: troca obrigatória da senha igual ao nome (ADM/ADM) e bloqueio depois de senhas erradas seguidas."""
from __future__ import annotations

from src.controllers.acesso_controller import BLOQUEIO_MINUTOS, MAX_TENTATIVAS, AcessoController
from src.controllers.cadastro_controller import CadastroController
from src.core.erros import ErroNegocio
from tests.base import BaseTeste


class BaseAcesso(BaseTeste):
    def setUp(self):
        super().setUp()
        self.acesso = AcessoController(self.banco)
        CadastroController(self.banco).salvar("operadores", {"nome": "BAR", "senha": "1234", "nivel": "0"})

    def errar(self, vezes, nome="ADM"):
        for _ in range(vezes):
            with self.assertRaises(ErroNegocio):
                self.acesso.autenticar(nome, "errada")


class TesteSenhaDeFabrica(BaseAcesso):
    def test_senha_igual_ao_nome_exige_troca(self):
        adm = self.acesso.autenticar("ADM", "adm")
        self.assertTrue(self.acesso.precisa_trocar_senha(adm, "adm"))
        bar = self.acesso.autenticar("BAR", "1234")
        self.assertFalse(self.acesso.precisa_trocar_senha(bar, "1234"))

    def test_trocar_senha(self):
        adm = self.acesso.autenticar("ADM", "ADM")
        self.acesso.trocar_senha(adm, "Forte77")
        with self.assertRaises(ErroNegocio):
            self.acesso.autenticar("ADM", "ADM")
        nova = self.acesso.autenticar("ADM", "forte77")            # sem diferenciar maiúsculas, como sempre
        self.assertFalse(self.acesso.precisa_trocar_senha(nova, "forte77"))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'senha_trocada'"), 1)

    def test_senha_nova_invalida(self):
        adm = self.acesso.autenticar("ADM", "ADM")
        for ruim in ("", "adm", " Adm ", "com espaço", "12345678901", "açaí"):
            with self.subTest(senha=ruim), self.assertRaises(ErroNegocio):
                self.acesso.trocar_senha(adm, ruim)
        self.acesso.autenticar("ADM", "ADM")                       # nada mudou


class TesteBloqueioPorTentativas(BaseAcesso):
    def test_bloqueia_depois_de_senhas_erradas_seguidas(self):
        self.errar(MAX_TENTATIVAS)
        with self.assertRaises(ErroNegocio) as e:
            self.acesso.autenticar("ADM", "ADM")                   # nem a senha certa entra durante o bloqueio
        self.assertIn("Aguarde", str(e.exception))
        self.avancar(minutes=BLOQUEIO_MINUTOS)
        self.acesso.autenticar("ADM", "ADM")

    def test_acertar_zera_o_contador(self):
        self.errar(MAX_TENTATIVAS - 1)
        self.acesso.autenticar("ADM", "ADM")
        self.errar(MAX_TENTATIVAS - 1)
        self.acesso.autenticar("ADM", "ADM")

    def test_o_bloqueio_e_por_operador_e_sobrevive_a_reabrir_o_sistema(self):
        self.errar(MAX_TENTATIVAS)
        self.acesso.autenticar("BAR", "1234")                      # outro operador continua entrando
        with self.assertRaises(ErroNegocio):
            AcessoController(self.banco).autenticar("ADM", "ADM")  # instância nova (sistema reaberto): segue bloqueado
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'senha_bloqueada'"), 1)

    def test_vencido_o_bloqueio_ganha_novas_tentativas(self):
        self.errar(MAX_TENTATIVAS)
        self.avancar(minutes=BLOQUEIO_MINUTOS)
        self.errar(MAX_TENTATIVAS - 1)
        self.acesso.autenticar("ADM", "ADM")

    def test_senha_de_supervisor_tambem_bloqueia(self):
        for _ in range(MAX_TENTATIVAS):
            self.assertIsNone(self.acesso.validar_supervisor("errada", "caixa_cancelamento"))
        with self.assertRaises(ErroNegocio):
            self.acesso.validar_supervisor("ADM", "caixa_cancelamento")
        self.avancar(minutes=BLOQUEIO_MINUTOS)
        self.assertEqual(self.acesso.validar_supervisor("ADM", "caixa_cancelamento").nome, "ADM")
