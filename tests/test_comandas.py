"""Comandas: a comanda 2 convive com a mesa 2, aparece na lista de mesas abertas e segue as regras de mesa."""
from __future__ import annotations

import os
import tempfile
import unittest

from src.controllers.config_controller import ConfigController
from src.controllers.impressao_controller import ImpressaoController
from src.controllers.relatorio_controller import RelatorioController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroValidacao
from src.core.posicao import interpretar, nome, parece_comanda, rotulo
from src.database.conexao import BancoDados
from src.database.esquema import VERSAO_ESQUEMA
from src.ui.painel_mesas import montar_tiles
from tests.test_caixa import BaseCaixa


class TesteNotacao(unittest.TestCase):
    def test_interpreta_mesa_e_comanda(self):
        self.assertEqual(interpretar("5"), (False, 5))
        self.assertEqual(interpretar(" 12 "), (False, 12))
        for texto in ("C2", "c2", "c 2", " C2 ", "C002"):
            self.assertEqual(interpretar(texto), (True, 2), texto)
        self.assertEqual(interpretar("0"), (False, 0))          # a tela usa 0 para o balcão

    def test_recusa_o_que_nao_e_posicao(self):
        for texto in ("", "abc", "C", "CC2", "2C", "C-2", "C2.5", "C0", None, "123456"):
            with self.assertRaises(ValueError, msg=repr(texto)):
                interpretar(texto)

    def test_parece_comanda_so_com_a_letra_c(self):
        self.assertTrue(parece_comanda("C2"))
        self.assertTrue(parece_comanda("c 12"))
        for texto in ("2", "SKOL", "", None):
            self.assertFalse(parece_comanda(texto), repr(texto))

    def test_rotulo_e_nome(self):
        self.assertEqual((rotulo(False, 5), rotulo(True, 5)), ("5", "C5"))
        self.assertEqual((nome(False, 5), nome(True, 5)), ("Mesa 5", "Comanda 5"))


class TesteComandas(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("posicao_padrao", "mesa")        # notação clássica destes testes: 5 é a mesa e C2 a comanda

    def comanda(self, numero, *itens):
        vid, _ = self.caixa.abrir_mesa(numero, comanda=True)
        for pid, qtd in itens:
            self.caixa.adicionar_item(vid, pid, qtd)
        return vid

    def abertas(self):
        return [(m["rotulo"], m["subtotal_cent"]) for m in self.caixa.mesas()]

    def fechar(self, vid, forma="Dinheiro"):
        self.pagar(vid, forma, self.caixa.obter(vid)["total_cent"])
        return self.caixa.fechar(vid)

    # ------------------------------------------------------------- abertura
    def test_skol_na_comanda_2_aparece_como_uma_mesa_aberta(self):
        vid = self.comanda(2, (self.skol, 1))
        abertas = [(m["id"], m["rotulo"], m["comanda"], m["posicao"], m["status"], m["n_itens"]) for m in self.caixa.mesas()]
        self.assertEqual(abertas, [(vid, "C2", 1, 2, "aberta", 1)])
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 880)          # 8,00 + 10% de serviço

    def test_comanda_2_e_mesa_2_coexistem(self):
        mesa, _ = self.caixa.abrir_mesa(2)
        comanda, criada = self.caixa.abrir_mesa(2, comanda=True)
        self.assertTrue(criada)
        self.assertNotEqual(mesa, comanda)
        self.assertEqual(self.caixa.abrir_mesa(2), (mesa, False))
        self.assertEqual(self.caixa.abrir_mesa(2, comanda=True), (comanda, False))
        self.assertEqual([m["rotulo"] for m in self.caixa.mesas()], ["2", "C2"])      # mesas primeiro

    def test_nao_ha_duas_comandas_abertas_com_o_mesmo_numero(self):
        self.caixa.abrir_mesa(7, comanda=True)
        with self.assertRaises(Exception):
            self.banco.inserir("vendas", {"uuid": "x", "modalidade": "mesa", "posicao": 7, "comanda": 1,
                                          "aberta_em": "2026-10-03 21:00:00"})

    def test_comanda_fechada_libera_o_numero_para_outro_cliente(self):
        vid = self.comanda(2, (self.skol, 1))
        self.fechar(vid)
        novo, criada = self.caixa.abrir_mesa(2, comanda=True)
        self.assertTrue(criada)
        self.assertNotEqual(novo, vid)

    def test_numero_da_comanda_respeita_a_configuracao(self):
        for invalido in (0, 10001):
            with self.assertRaises(ErroNegocio):
                self.caixa.abrir_mesa(invalido, comanda=True)
        self.banco.cfg_set("num_comandas", 5)
        self.assertTrue(self.caixa.abrir_mesa(5, comanda=True)[1])
        with self.assertRaises(ErroNegocio):
            self.caixa.abrir_mesa(6, comanda=True)
        self.assertTrue(self.caixa.abrir_mesa(30)[1])                       # o limite das mesas é outro

    def test_comandas_desligadas_nao_afetam_as_mesas(self):
        self.banco.cfg_set("num_comandas", 0)
        with self.assertRaises(ErroNegocio) as e:
            self.caixa.abrir_mesa(1, comanda=True)
        self.assertIn("desligadas", str(e.exception))
        self.assertTrue(self.caixa.abrir_mesa(1)[1])

    # -------------------------------------------------------------- serviço
    def test_servico_da_comanda_e_o_da_mesa_sao_independentes(self):
        self.banco.cfg_set("cobra_servico_comanda", "N")
        c = self.comanda(3, (self.skol, 5))
        m = self.vender((self.skol, 5), mesa=3)
        self.assertEqual((self.caixa.obter(c)["total_cent"], self.caixa.obter(m)["total_cent"]), (4000, 4400))
        self.banco.cfg_set("cobra_servico_comanda", "S")
        self.banco.cfg_set("cobra_servico_mesa", "N")
        self.caixa.recalcular(c)
        self.caixa.recalcular(m)
        self.assertEqual((self.caixa.obter(c)["total_cent"], self.caixa.obter(m)["total_cent"]), (4400, 4000))

    # ------------------------------------------------- pré-conta e fechamento
    def test_pre_conta_cupom_e_fechamento_da_comanda(self):
        vid = self.comanda(2, (self.skol, 2))
        imp = ImpressaoController(self.banco)
        self.caixa.enviar_conta(vid)
        pre = imp.pre_conta(vid)
        self.assertIn("CONTA DA COMANDA", pre)
        self.assertIn("Comanda 2", pre)
        self.assertNotIn("CONTA DA MESA", pre)
        v = self.fechar(vid)
        self.assertEqual((v["status"], v["modalidade"], v["comanda"]), ("fechada", "mesa", 1))
        cupom = imp.cupom(vid)
        self.assertIn("Comanda 2", cupom)
        self.assertNotIn("Mesa 2", cupom)
        self.assertTrue(all(len(l) <= 40 for l in cupom.splitlines()))

    def test_pre_conta_da_mesa_continua_igual(self):
        vid = self.vender((self.skol, 1), mesa=2)
        pre = ImpressaoController(self.banco).pre_conta(vid)
        self.assertIn("CONTA DA MESA", pre)
        self.assertIn("Mesa 2", pre)

    # --------------------------------------------------------- transferências
    def test_transferir_mesa_para_comanda_livre_e_de_volta(self):
        vid = self.vender((self.skol, 2), mesa=5)
        self.assertEqual(self.caixa.transferir_mesa(5, "C2"), vid)
        v = self.caixa.obter(vid)
        self.assertEqual((v["comanda"], v["posicao"]), (1, 2))
        self.assertEqual(self.abertas(), [("C2", 1600)])
        self.assertEqual(self.caixa.transferir_mesa((True, 2), 5), vid)
        self.assertEqual(self.abertas(), [("5", 1600)])

    def test_transferir_para_posicao_aberta_soma_os_itens(self):
        self.vender((self.skol, 2), mesa=2)
        self.comanda(2, (self.agua, 1))
        self.caixa.transferir_mesa(2, "C2")             # mesma numeração, tipos diferentes
        self.assertEqual(self.abertas(), [("C2", 1950)])

    def test_transferencia_recusa_origem_igual_ou_fechada(self):
        self.comanda(2, (self.skol, 1))
        with self.assertRaises(ErroNegocio):
            self.caixa.transferir_mesa("C2", "C2")
        with self.assertRaises(ErroNegocio) as e:
            self.caixa.transferir_mesa("C9", 3)
        self.assertIn("comanda 9 não está aberta", str(e.exception))
        with self.assertRaises(ErroNegocio):
            self.caixa.transferir_mesa(2, 3)            # a mesa 2 não existe: só a comanda 2
        with self.assertRaises(ErroNegocio):
            self.caixa.transferir_mesa("C2", "C10001")  # fora do limite de comandas
        self.assertEqual(self.abertas(), [("C2", 800)])

    def test_transferir_varias_aceita_mesas_e_comandas(self):
        self.vender((self.skol, 1), mesa=3)
        self.comanda(1, (self.skol, 2))
        self.comanda(4, (self.agua, 1))
        destino = self.caixa.transferir_varias([3, "C1", (True, 4)], "C9")
        self.assertEqual(self.caixa.obter(destino)["subtotal_cent"], 800 + 1600 + 350)
        self.assertEqual(self.abertas(), [("C9", 2750)])

    def test_transferir_varias_nao_move_nada_se_uma_origem_falha(self):
        self.comanda(1, (self.skol, 1))
        with self.assertRaises(ErroNegocio):
            self.caixa.transferir_varias(["C1", "C8"], 5)
        self.assertEqual(self.abertas(), [("C1", 800)])

    def test_transferir_parte_dos_itens_para_comanda(self):
        vid = self.vender((self.skol, 5), mesa=10)
        item = self.caixa.itens(vid)[0]["id"]
        self.caixa.transferir_item(item, "C2", 2)
        self.assertEqual(self.abertas(), [("10", 2400), ("C2", 1600)])
        with self.assertRaises(ErroNegocio):
            self.caixa.transferir_item(item, 10, 1)     # a mesma mesa
        self.assertEqual(self.abertas(), [("10", 2400), ("C2", 1600)])

    # ------------------------------------------------ repique, turno, relatórios
    def test_repique_da_comanda_fica_ligado_a_venda_da_comanda(self):
        mesa = self.vender((self.skol, 1), mesa=2)
        comanda = self.comanda(2, (self.skol, 1))
        self.turnos.repique(self.turno, self.adm, 2, 300, comanda=True)
        self.turnos.repique(self.turno, self.adm, 2, 200)
        repiques = {r["valor_cent"]: r["venda_id"] for r in self.banco.todos("SELECT valor_cent, venda_id FROM repiques")}
        self.assertEqual(repiques, {300: comanda, 200: mesa})

    def test_turno_conta_mesa_2_e_comanda_2_como_posicoes_diferentes(self):
        self.fechar(self.vender((self.skol, 1), mesa=2))
        self.fechar(self.comanda(2, (self.skol, 1)))
        self.assertEqual(self.turnos.resumo(self.turno)["posicoes"], 2)

    def test_relatorios_listam_comandas_junto_das_mesas(self):
        for vid in (self.vender((self.skol, 1), mesa=2), self.comanda(2, (self.agua, 1))):
            self.pagar(vid, "Dinheiro", self.caixa.obter(vid)["total_cent"])
            self.caixa.fechar(vid, garcom_id=self.adm)
        rel = RelatorioController(self.banco)
        f = {"de": fmt.hoje(), "ate": fmt.hoje()}
        r = rel.comandas(f)
        self.assertEqual(r.titulo, "Mesas e comandas")
        self.assertEqual([(l[0], l[-1]) for l in r.linhas], [("2", "8,80"), ("C2", "3,85")])
        self.assertEqual(rel.garcons(f).linhas[0][:3], ["ADM", "2", "2"])       # 2 cupons em 2 posições

    def test_filtro_de_modalidade_separa_comanda_de_mesa(self):
        self.fechar(self.vender((self.skol, 1), mesa=2))
        self.fechar(self.comanda(2, (self.agua, 1)))
        self.fechar(self.vender((self.skol, 1)))
        rel = RelatorioController(self.banco)
        f = {"de": fmt.hoje(), "ate": fmt.hoje()}

        def cupons(modalidade):
            return [(c["modalidade"], c["comanda"], c["posicao"]) for c in rel.cupons({**f, "modalidade": modalidade})]
        self.assertEqual(cupons("mesa"), [("mesa", 0, 2)])
        self.assertEqual(cupons("comanda"), [("mesa", 1, 2)])
        self.assertEqual(cupons("balcao"), [("balcao", 0, 0)])
        self.assertEqual(len(rel.cupons(f)), 3)
        self.assertEqual(dict(rel.vendas_periodo(f).rodape)["  Mesa/Comanda/Balcão"], "19,50")


class TesteIconesDoRodape(BaseCaixa):
    """O modelo dos ícones do caixa (sem Tk): balcão primeiro, depois mesas e comandas, cada uma no seu estado."""

    def setUp(self):
        super().setUp()
        self.banco.cfg_set("posicao_padrao", "mesa")        # notação clássica destes testes: 5 é a mesa e C2 a comanda

    def test_estados_e_ordem_dos_icones(self):
        self.vender((self.skol, 1), mesa=5)                                   # fica parada: passam 40 min
        c2, _ = self.caixa.abrir_mesa(2, comanda=True)
        self.caixa.adicionar_item(c2, self.agua, 1)
        self.caixa.enviar_conta(c2)                                           # conta enviada (não é "parada")
        self.avancar(minutes=40)
        c3, _ = self.caixa.abrir_mesa(3, comanda=True)
        self.caixa.adicionar_item(c3, self.skol, 2)
        tiles = montar_tiles(self.caixa.mesas(), self.caixa.balcao_aberto())
        self.assertEqual([(t["chave"], t["tipo"], t["estado"], t["total"]) for t in tiles], [
            ("0", "balcao", "balcao", ""), ("5", "mesa", "parada", "8,80"),
            ("C2", "comanda", "conta", "3,85"), ("C3", "comanda", "consumindo", "17,60")])
        self.assertEqual(tiles[1]["minutos"], 40)

    def test_balcao_em_andamento_mostra_o_total(self):
        self.assertIsNone(self.caixa.balcao_aberto())
        self.assertEqual(montar_tiles([], None), [{"chave": "0", "rotulo": "Balcão", "tipo": "balcao",
                                                   "estado": "balcao", "total": "", "minutos": 0}])
        vid = self.vender((self.skol, 2))
        self.assertEqual(self.caixa.balcao_aberto()["id"], vid)
        self.assertEqual(montar_tiles([], self.caixa.balcao_aberto())[0]["total"], "16,00")
        self.assertEqual(self.caixa.abrir_balcao(), vid)                       # retomar a venda é o mesmo que consultá-la


class TesteConfigComandas(BaseCaixa):
    def test_configuracao_de_comandas(self):
        cfg = ConfigController(self.banco)
        cfg.salvar_config({"num_comandas": "0", "cobra_servico_comanda": "N", "painel_mesas_fixo": "N"})
        self.assertEqual((self.banco.cfg_int("num_comandas", 200), self.banco.cfg_bool("cobra_servico_comanda", True),
                          self.banco.cfg_bool("painel_mesas_fixo", True)), (0, False, False))
        for invalido in ("-1", "10001", "abc"):
            with self.assertRaises(ErroValidacao, msg=invalido):
                cfg.salvar_config({"num_comandas": invalido})
        self.assertNotIn("controle_comandas", cfg.todas())      # campo antigo, sem efeito, trocado por num_comandas


class TesteMigracaoV4(unittest.TestCase):
    def test_banco_v3_ganha_a_coluna_comanda_sem_perder_mesas_abertas(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "v3.db")
            b = BancoDados(caminho)
            # volta ao desenho da v3: sem a coluna e com o índice que só olhava a posição
            b.executar("DROP INDEX ix_posicao_aberta")
            b.executar("ALTER TABLE vendas DROP COLUMN comanda")
            b.executar("""CREATE UNIQUE INDEX ix_mesa_aberta ON vendas(posicao)
                          WHERE modalidade = 'mesa' AND status IN ('aberta','conta_enviada')""")
            b.executar("PRAGMA user_version = 3")
            b.inserir("vendas", {"uuid": "mesa-2", "modalidade": "mesa", "posicao": 2, "aberta_em": "2026-10-03 21:00:00"})
            b.fechar()

            b = BancoDados(caminho)
            try:
                self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
                self.assertEqual(b.valor("SELECT comanda FROM vendas WHERE uuid = 'mesa-2'"), 0)
                indices = {r[1] for r in b.todos("PRAGMA index_list(vendas)")}
                self.assertIn("ix_posicao_aberta", indices)
                self.assertNotIn("ix_mesa_aberta", indices)
                comanda = {"modalidade": "mesa", "posicao": 2, "comanda": 1, "aberta_em": "2026-10-03 21:05:00"}
                b.inserir("vendas", {"uuid": "comanda-2", **comanda})      # convive com a mesa 2 já aberta
                with self.assertRaises(Exception):
                    b.inserir("vendas", {"uuid": "comanda-2-de-novo", **comanda})
            finally:
                b.fechar()


class TesteNotacaoPorPadrao(unittest.TestCase):
    """As funções puras: o número sem letra segue o padrão da loja; C e M valem sempre."""

    def test_numero_sem_letra_segue_o_padrao(self):
        self.assertEqual(interpretar("123", "comanda"), (True, 123))
        self.assertEqual(interpretar("123", "mesa"), (False, 123))
        self.assertEqual(interpretar("10000", "comanda"), (True, 10000))

    def test_letra_explicita_vale_nos_dois_padroes(self):
        for padrao in ("comanda", "mesa"):
            for texto, esperado in (("C2", (True, 2)), ("c 2", (True, 2)), ("M5", (False, 5)), ("m5", (False, 5)),
                                    (" m 05 ", (False, 5)), ("0", (False, 0))):
                self.assertEqual(interpretar(texto, padrao), esperado, (padrao, texto))

    def test_zero_com_letra_nao_existe(self):
        for texto in ("C0", "M0", "c 0"):
            with self.assertRaises(ValueError, msg=texto):
                interpretar(texto, "comanda")

    def test_mensagem_de_erro_ensina_a_notacao_da_loja(self):
        with self.assertRaises(ValueError) as e:
            interpretar("abc", "comanda")
        self.assertIn("M5", str(e.exception))
        with self.assertRaises(ValueError) as e:
            interpretar("abc", "mesa")
        self.assertIn("C2", str(e.exception))

    def test_rotulo_nos_dois_padroes(self):
        self.assertEqual((rotulo(True, 123, "comanda"), rotulo(False, 5, "comanda")), ("123", "M5"))
        self.assertEqual((rotulo(True, 123, "mesa"), rotulo(False, 5, "mesa")), ("C123", "5"))

    def test_so_letra_mais_numero_troca_de_posicao_no_campo_do_codigo(self):
        from src.core.posicao import parece_posicao
        for texto in ("C2", "c 12", "M5", "m5"):
            self.assertTrue(parece_posicao(texto), texto)
        for texto in ("2", "123", "SKOL", "", None, "5M"):
            self.assertFalse(parece_posicao(texto), repr(texto))
        self.assertTrue(parece_comanda("C2"))
        self.assertFalse(parece_comanda("M5"))

    def test_padrao_estragado_volta_para_comanda(self):
        from src.core.posicao import padrao_valido
        self.assertEqual([padrao_valido(v) for v in ("mesa", "MESA", " comanda ", "", None, "garcom")],
                         ["mesa", "mesa", "comanda", "comanda", "comanda", "comanda"])

    def test_exemplos_e_titulo_do_campo(self):
        from src.core.posicao import exemplos, rotulo_do_campo
        self.assertEqual((exemplos("comanda"), exemplos("mesa")), (("123", "M5"), ("5", "C2")))
        self.assertIn("Comanda", rotulo_do_campo("comanda"))
        self.assertIn("Mesa ou comanda", rotulo_do_campo("mesa"))


class TesteComandaPorNumero(BaseCaixa):
    """O padrão da loja: o número digitado sem letra é a comanda (até 10 mil) e a mesa leva M (M5)."""

    def comanda(self, numero, *itens):
        vid, _ = self.caixa.abrir_mesa(numero, comanda=True)
        for pid, qtd in itens:
            self.caixa.adicionar_item(vid, pid, qtd)
        return vid

    def abertas(self):
        return [(m["rotulo"], m["subtotal_cent"]) for m in self.caixa.mesas()]

    def test_loja_nova_vem_com_comanda_por_numero_ate_10_mil(self):
        self.assertEqual(self.caixa.padrao_posicao(), "comanda")
        self.assertEqual(self.banco.cfg("posicao_padrao"), "comanda")
        self.assertEqual(self.banco.cfg_int("num_comandas"), 10000)

    def test_numero_sem_letra_e_comanda_e_a_mesa_leva_m(self):
        for texto, esperado in (("123", (True, 123)), ("10000", (True, 10000)), ("C7", (True, 7)), ("c 7", (True, 7)),
                                ("M5", (False, 5)), ("m5", (False, 5)), ("0", (False, 0))):
            self.assertEqual(self.caixa.ler_posicao(texto), esperado, texto)
        for ruim in ("", "abc", "M", "123456", "C0", "M0", "5M"):
            with self.assertRaises(ValueError, msg=ruim):
                self.caixa.ler_posicao(ruim)

    def test_rotulo_e_leitura_sao_inversos_nos_dois_padroes(self):
        for padrao in ("comanda", "mesa"):
            self.banco.cfg_set("posicao_padrao", padrao)
            for comanda in (True, False):
                for numero in (1, 9, 123, 10000):
                    rot = self.caixa.rotular_posicao(comanda, numero)
                    self.assertEqual(self.caixa.ler_posicao(rot), (comanda, numero), (padrao, comanda, numero, rot))

    def test_lista_de_abertas_usa_o_rotulo_que_se_digita(self):
        self.comanda(2, (self.skol, 1))
        self.comanda(123, (self.agua, 1))
        self.vender((self.skol, 1), mesa=7)
        self.assertEqual(self.abertas(), [("M7", 800), ("2", 800), ("123", 350)])         # mesas primeiro

    def test_comanda_10000_abre_e_a_10001_nao(self):
        self.assertTrue(self.caixa.abrir_mesa(10000, comanda=True)[1])
        with self.assertRaises(ErroNegocio) as e:
            self.caixa.abrir_mesa(10001, comanda=True)
        self.assertIn("1 a 10000", str(e.exception))

    def test_transferencias_aceitam_o_texto_digitado(self):
        vid = self.vender((self.skol, 2), mesa=5)
        self.assertEqual(self.caixa.transferir_mesa("M5", "123"), vid)               # mesa 5 -> comanda 123
        v = self.caixa.obter(vid)
        self.assertEqual((v["comanda"], v["posicao"]), (1, 123))
        self.comanda(9, (self.agua, 1))
        self.vender((self.skol, 1), mesa=3)
        destino = self.caixa.transferir_varias(["123", "9", "M3"], "456")
        self.assertEqual(self.abertas(), [("456", 1600 + 350 + 800)])
        item = self.caixa.itens(destino)[0]["id"]
        self.caixa.transferir_item(item, "M8", 1)                                     # parte para a mesa 8
        self.assertEqual([r for r, _ in self.abertas()], ["M8", "456"])

    def test_numero_inteiro_da_api_continua_sendo_mesa(self):
        vid = self.vender((self.skol, 1), mesa=4)
        self.assertEqual(self.caixa.transferir_mesa(4, 8), vid)
        self.assertEqual(self.abertas(), [("M8", 800)])

    def test_a_loja_pode_voltar_para_a_notacao_de_mesa(self):
        self.banco.cfg_set("posicao_padrao", "mesa")
        self.assertEqual(self.caixa.ler_posicao("5"), (False, 5))
        self.assertEqual(self.caixa.rotular_posicao(True, 2), "C2")
        self.banco.cfg_set("posicao_padrao", "qualquer coisa")
        self.assertEqual(self.caixa.padrao_posicao(), "comanda")                      # valor estragado volta ao padrão

    def test_relatorio_de_mesas_e_comandas_usa_a_mesma_notacao(self):
        for vid in (self.vender((self.skol, 1), mesa=3), self.comanda(2, (self.agua, 1))):
            self.pagar(vid, "Dinheiro", self.caixa.obter(vid)["total_cent"])
            self.caixa.fechar(vid, garcom_id=self.adm)
        r = RelatorioController(self.banco).comandas({"de": fmt.hoje(), "ate": fmt.hoje()})
        self.assertEqual([(l[0], l[-1]) for l in r.linhas], [("M3", "8,80"), ("2", "3,85")])

    def test_chave_do_icone_volta_igual_quando_digitada(self):
        self.comanda(123, (self.skol, 1))
        self.comanda(2, (self.agua, 1))
        self.vender((self.skol, 1), mesa=5)
        tiles = montar_tiles(self.caixa.mesas(), None)
        self.assertEqual([t["chave"] for t in tiles], ["0", "M5", "2", "123"])
        for t in tiles[1:]:
            comanda, numero = self.caixa.ler_posicao(t["chave"])
            self.assertEqual((comanda, numero), (t["tipo"] == "comanda", int(t["chave"].lstrip("M"))), t["chave"])


class TesteConfigNotacao(BaseCaixa):
    def test_posicao_padrao_grava_e_recusa_opcao_desconhecida(self):
        cfg = ConfigController(self.banco)
        cfg.salvar_config({"posicao_padrao": "mesa"})
        self.assertEqual(self.caixa.padrao_posicao(), "mesa")
        with self.assertRaises(ErroValidacao):
            cfg.salvar_config({"posicao_padrao": "garcom"})
        self.assertEqual(cfg.todas()["posicao_padrao"], "mesa")

    def test_limite_de_comandas_vai_ate_10_mil(self):
        cfg = ConfigController(self.banco)
        cfg.salvar_config({"num_comandas": "10000"})
        self.assertEqual(self.banco.cfg_int("num_comandas"), 10000)
        with self.assertRaises(ErroValidacao):
            cfg.salvar_config({"num_comandas": "10001"})


class TesteMigracaoV6(unittest.TestCase):
    def reabrir(self, pasta, limite_antigo):
        caminho = os.path.join(pasta, "v5.db")
        b = BancoDados(caminho)
        b.cfg_set("num_comandas", limite_antigo)
        b.executar("DELETE FROM config WHERE chave = 'posicao_padrao'")
        b.executar("PRAGMA user_version = 5")
        b.fechar()
        return BancoDados(caminho)

    def test_limite_antigo_de_200_sobe_para_10000_e_a_notacao_nasce_comanda(self):
        with tempfile.TemporaryDirectory() as pasta:
            b = self.reabrir(pasta, "200")
            try:
                self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
                self.assertEqual((b.cfg("num_comandas"), b.cfg("posicao_padrao")), ("10000", "comanda"))
            finally:
                b.fechar()

    def test_limite_que_o_dono_escolheu_nao_e_mexido(self):
        with tempfile.TemporaryDirectory() as pasta:
            b = self.reabrir(pasta, "350")
            try:
                self.assertEqual(b.cfg("num_comandas"), "350")
            finally:
                b.fechar()


if __name__ == "__main__":
    unittest.main()
