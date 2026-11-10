"""Edição de restaurante: isolamento, perfis, módulos e licença própria."""
import os
import unittest
from datetime import date
from unittest.mock import patch
from types import SimpleNamespace

from src.core import edicao, ed25519, licenca
from src.core.erros import ErroNegocio
from src.controllers.config_controller import ConfigController
from src.controllers.perfil_controller import PerfilController
from src.controllers.primeiros_passos import PrimeirosPassos
from src.database.conexao import BancoDados
from src.sync import cardapio_envio, pedidos_online


class TesteWillRestaurante(unittest.TestCase):
    def setUp(self):
        contexto = patch.dict(os.environ, {"PDV_EDICAO": "willrestaurante"})
        contexto.start()
        self.addCleanup(contexto.stop)
        self.banco = BancoDados(":memory:")
        self.addCleanup(self.banco.fechar)
        edicao.preparar(self.banco)

    def test_edicao_tem_dados_executavel_e_instalador_proprios(self):
        ed = edicao.atual()
        self.assertEqual((ed.nome, ed.pasta_dados, ed.executavel, ed.script_instalador),
                         ("Will Restaurante", "WILL-RESTAURANTE", "WillRestaurante", "WillRestaurante.iss"))
        self.assertEqual(self.banco.cfg("edicao"), "willrestaurante")
        self.assertEqual(self.banco.cfg("perfil_operacao"), "hamburgueria")

    def test_hamburgueria_liga_operacao_e_bloqueia_casa_noturna(self):
        for chave in ("usar_mesas", "usar_cozinha_bar", "usar_delivery", "pedido_online", "cardapio_digital"):
            self.assertTrue(self.banco.cfg_bool(chave), chave)
        for chave in ("usar_garotas", "usar_quartos", "usar_portaria", "porteiro_ativo"):
            self.assertFalse(self.banco.cfg_bool(chave), chave)
            with self.assertRaises(ErroNegocio):
                ConfigController(self.banco).salvar_config({chave: "S"})
        fora = edicao.atual().fora_das_configuracoes()
        for chave in ("num_mesas", "pedido_online", "usar_cozinha_bar", "usar_delivery"):
            self.assertNotIn(chave, fora)
        self.assertTrue({"quartos", "porteiro"} <= edicao.atual().menu_oculto)
        self.assertNotIn("cozinha", edicao.atual().menu_oculto)

    def test_quatro_perfis_disponiveis_sem_aceitar_boate(self):
        perfis = PerfilController(self.banco)
        for chave in ("pizzaria", "a_la_carte", "rodizio", "hamburgueria"):
            perfis.aplicar(chave)
            self.assertEqual(perfis.atual(), chave)
            self.assertTrue(self.banco.cfg_bool("usar_mesas"))
            self.assertTrue(self.banco.cfg_bool("usar_cozinha_bar"))
            self.assertEqual(self.banco.cfg_bool("usar_rodizio"), chave == "rodizio")
        with self.assertRaises(ErroNegocio):
            perfis.aplicar("boate")
        self.assertFalse(edicao.atual().perfil_fixo())
        self.assertIn("perfil", {p["chave"] for p in PrimeirosPassos(self.banco).passos()})

    def test_reabrir_preserva_perfil_e_ajustes_e_restaura_bloqueios(self):
        PerfilController(self.banco).aplicar("pizzaria")
        self.banco.cfg_set("pedido_online", "N")
        self.banco.cfg_set("usar_garotas", "S")
        edicao.preparar(self.banco)
        self.assertEqual(self.banco.cfg("perfil_operacao"), "pizzaria")
        self.assertFalse(self.banco.cfg_bool("pedido_online"))
        self.assertFalse(self.banco.cfg_bool("usar_garotas"))

    def test_licenca_restaurante_nao_abre_outra_edicao(self):
        semente = bytes(range(32))
        publica = ed25519.chave_publica(semente)
        hoje = date(2026, 11, 10)
        codigo = licenca.gerar_licenca(semente, "HAMBURGUERIA", 30, hoje, "willrestaurante")
        self.assertTrue(licenca.desta_edicao(licenca.ler_licenca(codigo, publica)))
        with patch.dict(os.environ, {"PDV_EDICAO": "willadega"}):
            self.assertFalse(licenca.desta_edicao(licenca.ler_licenca(codigo, publica)))

    def test_online_exige_mesma_edicao_cadastrada_na_nuvem(self):
        from backend.pedido_online import pode_pedir
        loja = SimpleNamespace(edicao="willrestaurante")
        self.assertTrue(pode_pedir(loja, "willrestaurante"))
        self.assertFalse(pode_pedir(loja, "willadega"))
        self.assertFalse(pode_pedir(SimpleNamespace(edicao="willpdv"), "willrestaurante"))

    def test_online_nao_publica_sem_contato_e_sem_nuvem_configurados(self):
        self.assertFalse(cardapio_envio.config_pedido(self.banco)["ligado"])
        self.assertFalse(pedidos_online.ligado(self.banco))
        self.banco.cfg_set("pedido_online_whatsapp", "11987654321")
        self.banco.cfg_set("api_url", "https://example.test/v1/sincronizar")
        self.banco.cfg_set("api_token", "token-de-teste")
        self.assertTrue(cardapio_envio.config_pedido(self.banco)["ligado"])
        self.assertTrue(pedidos_online.ligado(self.banco))


if __name__ == "__main__":
    unittest.main()
