"""Preparação de integrações não habilita operações nem altera a venda local."""
from unittest.mock import patch

from src.controllers.config_controller import CAMPOS_CONFIG, ConfigController
from src.controllers.integracoes_controller import IntegracoesController
from src.controllers.perfil_controller import PERFIS, PerfilController
from src.core.erros import ErroNegocio, ErroValidacao
from src.database import sementes
from tests.base import BaseTeste


class TesteIntegracoes(BaseTeste):
    def setUp(self):
        super().setUp()
        self.integracoes = IntegracoesController(self.banco)
        self.config = ConfigController(self.banco)
        self.perfil = PerfilController(self.banco)

    def test_padroes_desativados_e_campos_sem_ativacao_real(self):
        campos = {c[0]: c for c in CAMPOS_CONFIG}
        for modulo in ("ifood", "nfce"):
            situacao = self.integracoes.situacao(modulo)
            self.assertEqual(situacao["estado"], "desativado")
            self.assertFalse(situacao["operacional"])
            opcoes = {o[0] for o in campos[f"integracao_{modulo}_estado"][4]}
            self.assertEqual(opcoes, {"desativado", "preparacao"})
        self.assertEqual(self.banco.cfg("nfce_regime_tributario"), "nao_definido")

    def test_todos_os_perfis_menos_boate_sao_elegiveis_sem_ativar(self):
        for perfil in PERFIS:
            with self.subTest(perfil=perfil):
                self.perfil.aplicar(perfil)
                for modulo in ("ifood", "nfce"):
                    situacao = self.integracoes.situacao(modulo)
                    self.assertEqual(situacao["disponivel_no_perfil"], perfil != "boate")
                    self.assertFalse(situacao["operacional"])
                    self.assertEqual(situacao["estado"], "desativado")

    def test_preparacao_nao_liga_delivery_nem_altera_vendas(self):
        self.perfil.aplicar("bar")
        antes = self.banco.valor("SELECT COUNT(*) FROM vendas")
        with patch("urllib.request.urlopen") as rede:
            self.config.salvar_config({"integracao_ifood_estado": "preparacao",
                                       "integracao_nfce_estado": "preparacao"})
            resumo = self.integracoes.resumo()
            rede.assert_not_called()
        self.assertFalse(self.banco.cfg_bool("usar_delivery"))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas"), antes)
        self.assertIn("não emite notas fiscais", resumo)
        self.assertIn("NÃO FISCAL", resumo)
        self.assertFalse(self.integracoes.situacao("nfce")["operacional"])

    def test_ifood_informa_delivery_desligado_sem_ligar_por_conta_propria(self):
        self.perfil.aplicar("comercio")
        self.assertIn("Habilitar o delivery manual", self.integracoes.resumo())
        self.config.salvar_config({"usar_delivery": "S"})
        self.assertNotIn("Habilitar o delivery manual", self.integracoes.resumo())
        self.assertIn("Obter acesso de desenvolvedor", self.integracoes.resumo())

    def test_nfce_informa_uf_dados_da_loja_e_regime_pendentes(self):
        pendencias = "\n".join(self.integracoes.situacao("nfce")["pendencias"])
        for texto in ("lojas em SP", "Informar CNPJ", "Informar inscrição estadual", "regime tributário"):
            self.assertIn(texto, pendencias)
        self.config.salvar_loja({"uf": "sp", "cnpj": "DADO DE TESTE", "ie": "DADO DE TESTE"})
        self.config.salvar_config({"nfce_regime_tributario": "simples_nacional"})
        pendencias = "\n".join(self.integracoes.situacao("nfce")["pendencias"])
        for texto in ("lojas em SP", "Informar CNPJ", "Informar inscrição estadual", "Confirmar o regime"):
            self.assertNotIn(texto, pendencias)
        self.assertIn("validar", pendencias.lower())
        self.assertIn("Escolher o provedor", pendencias)
        self.assertFalse(self.integracoes.situacao("nfce")["operacional"])

    def test_outra_uf_nao_e_apresentada_como_homologada(self):
        self.config.salvar_loja({"uf": "RJ"})
        self.assertIn("lojas em SP", self.integracoes.resumo())
        self.assertFalse(self.integracoes.situacao("nfce")["operacional"])

    def test_ativacao_e_regime_invalidos_rejeitados_com_rollback(self):
        for chave in ("integracao_ifood_estado", "integracao_nfce_estado", "nfce_regime_tributario"):
            with self.subTest(chave=chave):
                antes = self.config.todas()
                with self.assertRaises(ErroValidacao):
                    self.config.salvar_config({"usar_delivery": "S", chave: "ativo"})
                self.assertEqual(self.config.todas(), antes)

    def test_estado_e_perfil_corrompidos_sao_erros_explicitos(self):
        self.banco.cfg_set("integracao_ifood_estado", "ativo")
        with self.assertRaisesRegex(ErroNegocio, "Estado inválido"):
            self.integracoes.situacao("ifood")
        self.banco.cfg_set("integracao_ifood_estado", "desativado")
        self.banco.cfg_set("perfil_operacao", "inexistente")
        with self.assertRaisesRegex(ErroNegocio, "Perfil desconhecido"):
            self.integracoes.situacao("ifood")

    def test_modulo_desconhecido_e_cadastro_ausente_sao_erros(self):
        with self.assertRaisesRegex(ErroNegocio, "Integração desconhecida"):
            self.integracoes.situacao("outro")
        self.banco.executar("DELETE FROM loja")
        with self.assertRaisesRegex(ErroNegocio, "Cadastro da loja não encontrado"):
            self.integracoes.situacao("nfce")

    def test_semear_banco_existente_preserva_preparacao(self):
        self.config.salvar_config({"integracao_ifood_estado": "preparacao"})
        self.banco.executar("DELETE FROM config WHERE chave = 'integracao_nfce_estado'")
        sementes.aplicar(self.banco)
        self.assertEqual(self.banco.cfg("integracao_ifood_estado"), "preparacao")
        self.assertEqual(self.banco.cfg("integracao_nfce_estado"), "desativado")

    def test_voltar_a_boate_preserva_preferencias_mas_nao_disponibiliza_modulos(self):
        self.perfil.aplicar("adega")
        self.config.salvar_config({"integracao_ifood_estado": "preparacao",
                                   "integracao_nfce_estado": "preparacao"})
        self.perfil.aplicar("boate")
        for modulo in ("ifood", "nfce"):
            situacao = self.integracoes.situacao(modulo)
            self.assertEqual(situacao["estado"], "preparacao")
            self.assertFalse(situacao["disponivel_no_perfil"])
            self.assertFalse(situacao["operacional"])
        self.assertIn("Boate está fora", self.integracoes.resumo())
