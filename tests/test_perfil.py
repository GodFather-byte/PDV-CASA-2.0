"""Perfil do estabelecimento (boate, bar, restaurante, churrascaria, comércio pequeno) e os dois módulos da casa noturna que
ele desliga nos outros negócios: garotas (comissão pelo código 50) e portaria (ticket e código de saída 1002)."""
from __future__ import annotations

import unittest

from src.controllers.cadastro_controller import CadastroController
from src.controllers.comissao_controller import ComissaoController
from src.controllers.config_controller import CAMPOS_CONFIG, ConfigController, modulos_desligados
from src.controllers.importacao_produtos import ImportacaoProdutos
from src.controllers.impressao_controller import ImpressaoController
from src.controllers.perfil_controller import ITENS, PERFIS, PerfilController
from src.core.erros import ErroNegocio, ErroValidacao
from src.database.sementes import CONFIG_PADRAO
from tests.test_caixa import BaseCaixa

MODULOS_GAROTAS = {"cad_garotas", "caixa_comissao", "caixa_pagar_comissao", "rel_comissao_garotas"}


def produto_com_codigo(banco, codigo: str, nome: str = "PAO FRANCES") -> int:
    sub = banco.valor("SELECT id FROM subgrupos LIMIT 1")
    un = banco.valor("SELECT id FROM unidades LIMIT 1")
    return CadastroController(banco).salvar("produtos", {"codigo": codigo, "nome": nome, "subgrupo_id": sub, "unidade_id": un,
                                                         "preco_cent": "0,80"})


class BasePerfil(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.perfil = PerfilController(self.banco, self.adm)


class TestePerfis(BasePerfil):
    def test_a_boate_e_o_padrao_de_fabrica(self):
        self.assertEqual(PERFIS["boate"][2], {chave: CONFIG_PADRAO[chave] for chave in ITENS})
        self.assertEqual(self.perfil.atual(), "boate")
        self.assertEqual(self.perfil.mudancas("boate"), [])           # banco novo já é boate: aplicar não muda nada
        self.assertFalse(self.perfil.ajustado())

    def test_todo_perfil_define_todos_os_itens_com_valor_valido(self):
        campos = {c[0]: c for c in CAMPOS_CONFIG}
        for chave, (_, _, valores) in PERFIS.items():
            with self.subTest(perfil=chave):
                self.assertEqual(set(valores), set(ITENS))
                for item, valor in valores.items():
                    permitidos = [o[0] for o in campos[item][4]] if campos[item][2] == "escolha" else ["S", "N"]
                    self.assertIn(valor, permitidos, item)

    def test_restaurante_liga_cozinha_delivery_e_mesa_e_desliga_o_que_e_da_boate(self):
        mudou = self.perfil.aplicar("restaurante")
        self.assertEqual({m["chave"] for m in mudou}, {"usar_garotas", "usar_portaria", "usar_cozinha_bar", "usar_delivery",
                                                        "posicao_padrao", "pergunta_pessoas", "usar_desconto"})
        for chave, valor in (("usar_garotas", "N"), ("usar_portaria", "N"), ("usar_cozinha_bar", "S"), ("usar_delivery", "S"),
                             ("posicao_padrao", "mesa"), ("pergunta_pessoas", "S"), ("usar_desconto", "S"),
                             ("cobra_servico_mesa", "S"), ("usar_rodizio", "N")):
            self.assertEqual(self.banco.cfg(chave), valor, chave)
        self.assertEqual(self.perfil.atual(), "restaurante")
        self.assertEqual(self.perfil.mudancas("restaurante"), [])
        self.assertIn("Restaurante", self.banco.valor("SELECT detalhe FROM log_eventos WHERE evento = 'perfil_operacao'"))
        self.assertTrue(MODULOS_GAROTAS <= modulos_desligados(self.banco))

    def test_churrascaria_liga_o_rodizio_e_comercio_a_caderneta_sem_servico(self):
        self.perfil.aplicar("churrascaria")
        self.assertEqual((self.banco.cfg("usar_rodizio"), self.banco.cfg("usar_delivery")), ("S", "N"))
        self.perfil.aplicar("comercio")
        self.assertEqual((self.banco.cfg("usar_rodizio"), self.banco.cfg("usar_caderneta"), self.banco.cfg("cobra_servico_mesa"),
                          self.banco.cfg("cobra_servico_comanda")), ("N", "S", "N", "N"))

    def test_textos_da_confirmacao(self):
        mudancas = {m["item"]: (m["de"], m["para"]) for m in self.perfil.mudancas("restaurante")}
        self.assertEqual(mudancas["Número digitado no caixa é"], ("Comanda", "Mesa"))
        self.assertEqual(mudancas["Garotas (comissão e shows)"], ("Ligado", "Desligado"))
        self.assertEqual(mudancas["Perguntar o nº de pessoas ao abrir a mesa"], ("Não", "Sim"))
        self.assertNotIn("Serviço nas mesas", mudancas)                  # já cobrava serviço: não aparece

    def test_voltar_para_a_boate_nao_mexe_no_que_o_dono_digitou(self):
        ConfigController(self.banco).salvar_config({"codigo_comissao": "77", "servico_pct": "12", "num_mesas": "30",
                                                    "valor_rodizio_pessoa": "89,90"})
        self.perfil.aplicar("comercio")
        self.perfil.aplicar("boate")
        self.assertEqual(self.perfil.mudancas("boate"), [])
        self.assertEqual((self.banco.cfg("codigo_comissao"), self.banco.cfg("num_mesas"), self.banco.cfg("valor_rodizio_pessoa")),
                         ("77", "30", "89,90"))
        self.assertEqual(float(self.banco.cfg("servico_pct")), 12.0)
        self.assertTrue(ComissaoController(self.banco).eh_codigo("77"))

    def test_perfil_desconhecido_e_recusado(self):
        with self.assertRaises(ErroNegocio):
            self.perfil.aplicar("padaria")
        self.assertEqual(self.perfil.atual(), "boate")

    def test_ajuste_feito_a_mao_depois_aparece_como_ajustado(self):
        self.perfil.aplicar("bar")
        self.assertFalse(self.perfil.ajustado())
        self.banco.cfg_set("usar_delivery", "S")
        self.assertTrue(self.perfil.ajustado())
        self.assertEqual([(m["item"], m["de"], m["para"]) for m in self.perfil.mudancas("bar")],
                         [("Delivery", "Ligado", "Desligado")])

    def test_voltar_para_a_boate_com_produto_no_codigo_50_e_recusado_sem_mudar_nada(self):
        self.perfil.aplicar("restaurante")
        produto_com_codigo(self.banco, "50")                  # sem garotas, o 50 é um código de produto como outro qualquer
        with self.assertRaisesRegex(ErroValidacao, "já usa o código 50"):
            self.perfil.aplicar("boate")
        self.assertEqual(self.perfil.atual(), "restaurante")  # tudo ou nada
        self.assertEqual((self.banco.cfg("usar_garotas"), self.banco.cfg("usar_cozinha_bar")), ("N", "S"))


class TesteModulosDaCasaNoturna(BasePerfil):
    def test_nascem_ligados_na_aba_modulos(self):
        secoes = {c[0]: c[3] for c in CAMPOS_CONFIG}
        for chave in ("usar_garotas", "usar_portaria"):
            self.assertTrue(self.banco.cfg_bool(chave, False), chave)
            self.assertEqual(secoes[chave], "Módulos")
        self.assertFalse(MODULOS_GAROTAS & modulos_desligados(self.banco))

    def test_sem_garotas_o_50_nao_lanca_comissao_e_fica_livre_para_produto(self):
        self.banco.cfg_set("usar_garotas", "N")
        com = ComissaoController(self.banco)
        self.assertFalse(com.ligada())
        self.assertEqual(com.codigo(), "")
        self.assertFalse(com.eh_codigo("50"))
        self.assertTrue(MODULOS_GAROTAS <= modulos_desligados(self.banco))
        produto_com_codigo(self.banco, "50")
        reservados = ImportacaoProdutos(self.banco).reservados()
        self.assertNotIn("50".zfill(13), reservados)
        self.assertIn("1002".zfill(13), reservados)                     # a portaria continua ligada

    def test_sem_portaria_o_1002_nao_libera_saida_e_o_ticket_nao_sai(self):
        self.banco.cfg_set("usar_portaria", "N")
        self.assertFalse(self.caixa.eh_codigo_saida("1002"))
        produto_com_codigo(self.banco, "1002", "AGUA COM GAS")
        vid, _ = self.caixa.abrir_mesa(100, comanda=True)
        self.caixa.adicionar_item(vid, self.skol, 1)
        self.pagar(vid, "Dinheiro", self.caixa.recalcular(vid)["total"])
        self.caixa.fechar(vid)
        self.assertIsNone(ImpressaoController(self.banco).saida_da_venda(vid))   # imprimir_saida_ao_pagar continua S

    def test_gravar_as_configuracoes_com_produto_no_codigo_de_modulo_desligado(self):
        self.banco.cfg_set("usar_garotas", "N")
        produto_com_codigo(self.banco, "50")
        cfg = ConfigController(self.banco)
        cfg.salvar_config(cfg.todas())                                   # a tela grava todos os campos de uma vez
        self.assertEqual(self.banco.cfg("codigo_comissao"), "50")        # guardado para quando a casa ligar de novo

    def test_ligar_garotas_com_produto_no_codigo_50_e_recusado(self):
        self.banco.cfg_set("usar_garotas", "N")
        produto_com_codigo(self.banco, "50")
        with self.assertRaisesRegex(ErroValidacao, "já usa o código 50"):
            ConfigController(self.banco).salvar_config({"usar_garotas": "S"})
        self.assertEqual(self.banco.cfg("usar_garotas"), "N")

    def test_comissao_e_saida_com_o_mesmo_codigo_so_conflitam_com_os_dois_ligados(self):
        cfg = ConfigController(self.banco)
        self.banco.cfg_set("usar_garotas", "N")
        cfg.salvar_config({"codigo_saida": "50"})                        # o 50 da comissão está desligado: não conflita
        self.assertTrue(self.caixa.eh_codigo_saida("50"))
        with self.assertRaisesRegex(ErroValidacao, "mesmo código"):
            cfg.salvar_config({"usar_garotas": "S"})


if __name__ == "__main__":
    unittest.main()
