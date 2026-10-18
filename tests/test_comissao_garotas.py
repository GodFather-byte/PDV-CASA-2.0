"""Comissão das garotas: o código 50 marca a comissão no número da garota; pendente, paga (sai do caixa) ou cancelada."""
from __future__ import annotations

import os
import tempfile
import unittest

from src.controllers.cadastro_controller import CadastroController
from src.controllers.comissao_controller import ComissaoController
from src.controllers.config_controller import ConfigController
from src.controllers.impressao_controller import ImpressaoController
from src.controllers.relatorio_controller import RelatorioController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroValidacao
from src.database.conexao import BancoDados
from src.database.esquema import VERSAO_ESQUEMA
from tests.test_caixa import BaseCaixa


class BaseComissao(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.com = ComissaoController(self.banco)
        self.cad = CadastroController(self.banco)

    def lancar(self, garota, reais, turno=None):
        return self.com.lancar(garota, round(reais * 100), turno or self.turno, self.adm)

    def garota(self, numero, nome, ativo=1):
        return self.cad.salvar("garotas", {"numero": numero, "nome": nome, "ativo": "S" if ativo else "N"})


class TesteCodigoDaComissao(BaseComissao):
    def test_o_codigo_50_vem_de_fabrica(self):
        self.assertEqual(self.com.codigo(), "50")

    def test_50_050_e_o_codigo_com_zeros_sao_o_mesmo(self):
        for texto in ("50", " 50 ", "050", "0000000000050"):
            self.assertTrue(self.com.eh_codigo(texto), texto)
        for texto in ("5", "500", "51", "SKOL", "", None):
            self.assertFalse(self.com.eh_codigo(texto), repr(texto))

    def test_vazio_desliga_o_codigo(self):
        ConfigController(self.banco).salvar_config({"codigo_comissao": ""})
        self.assertEqual(self.com.codigo(), "")
        self.assertFalse(self.com.eh_codigo("50"))

    def test_o_dono_pode_trocar_o_codigo(self):
        ConfigController(self.banco).salvar_config({"codigo_comissao": "090"})
        self.assertEqual(self.com.codigo(), "90")                       # 090 e 90 são o mesmo código
        self.assertTrue(self.com.eh_codigo("90"))
        self.assertFalse(self.com.eh_codigo("50"))

    def test_codigo_com_letras_compara_sem_diferenciar_maiusculas(self):
        ConfigController(self.banco).salvar_config({"codigo_comissao": "COM"})
        self.assertTrue(self.com.eh_codigo("com"))

    def test_codigo_de_produto_nao_pode_virar_codigo_da_comissao(self):
        cfg = ConfigController(self.banco)
        with self.assertRaises(ErroValidacao) as e:
            cfg.salvar_config({"codigo_comissao": "1"})                 # BaseCaixa já tem produtos de código 1 e 2
        self.assertIn("já usa o código", str(e.exception))
        for ruim in ("5 0", "a-b", "x" * 14):
            with self.assertRaises(ErroValidacao, msg=ruim):
                cfg.salvar_config({"codigo_comissao": ruim})
        self.assertEqual(self.com.codigo(), "50")                       # nada mudou

    def test_produto_nao_pode_ter_o_codigo_reservado(self):
        sub = self.banco.valor("SELECT id FROM subgrupos LIMIT 1")
        un = self.banco.valor("SELECT id FROM unidades LIMIT 1")
        base = {"nome": "COISA", "codigo": "77", "subgrupo_id": sub, "unidade_id": un, "preco_cent": "5,00"}
        for campo in ("codigo", "atalho", "cbarra"):
            with self.assertRaises(ErroValidacao, msg=campo) as e:
                self.cad.salvar("produtos", {**base, campo: "50"})
            self.assertIn("reservado", str(e.exception))
        self.cad.salvar("produtos", {**base, "codigo": "51"})           # outro código vale
        ConfigController(self.banco).salvar_config({"codigo_comissao": ""})
        self.cad.salvar("produtos", {**base, "nome": "COISA 2", "codigo": "50"})   # sem reserva, o 50 volta a ser livre


class TesteLancarComissao(BaseComissao):
    def test_marca_a_comissao_no_numero_da_garota(self):
        cid = self.lancar(180, 25)
        c = self.banco.um("SELECT * FROM comissoes_garotas WHERE id = ?", (cid,))
        self.assertEqual((c["garota"], c["valor_cent"], c["status"], c["turno_id"], c["operador_id"]),
                         (180, 2500, "pendente", self.turno, self.adm))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'comissao_lancada'"), 1)

    def test_soma_o_que_falta_pagar_de_cada_garota(self):
        self.lancar(180, 25); self.lancar(180, 30); self.lancar(156, 40)
        self.assertEqual((self.com.pendente(180), self.com.pendente(156), self.com.pendente(7)), (5500, 4000, 0))

    def test_aceita_numeros_grandes_e_recusa_o_que_nao_e_numero(self):
        self.lancar(99999, 10)
        for ruim in (0, -3, 100000, "abc", "", None, "18,5"):
            with self.assertRaises(ErroNegocio, msg=repr(ruim)):
                self.com.lancar(ruim, 1000, self.turno, self.adm)

    def test_valor_precisa_ser_maior_que_zero(self):
        for ruim in (0, -100):
            with self.assertRaises(ErroNegocio, msg=str(ruim)):
                self.com.lancar(180, ruim, self.turno, self.adm)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM comissoes_garotas"), 0)

    def test_exige_turno_aberto(self):
        self.turnos.fechar(self.turno, self.adm, 10000)
        with self.assertRaises(ErroNegocio) as e:
            self.lancar(180, 25)
        self.assertIn("turno", str(e.exception))
        with self.assertRaises(ErroNegocio):
            self.com.lancar(180, 2500, None, self.adm)

    def test_nao_mexe_em_vendas_nem_no_dinheiro_do_caixa(self):
        esperado = self.turnos.resumo(self.turno)["esperado"]
        self.lancar(180, 25)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas"), 0)
        self.assertEqual(self.turnos.resumo(self.turno)["esperado"], esperado)

    def test_nome_vem_do_cadastro_e_e_vazio_sem_cadastro(self):
        self.assertTrue(self.com.cadastro_vazio())
        self.garota(180, "MARIA")
        self.assertFalse(self.com.cadastro_vazio())
        self.assertEqual((self.com.nome(180), self.com.nome(156), self.com.nome("x")), ("MARIA", "", ""))

    def test_pendentes_por_garota_com_nome_e_total(self):
        self.garota(180, "MARIA")
        self.lancar(180, 25); self.lancar(156, 40); self.lancar(180, 10)
        self.assertEqual([(p["garota"], p["nome"], p["lancamentos"], p["total_cent"]) for p in self.com.pendentes_por_garota()],
                         [(156, "", 1, 4000), (180, "MARIA", 2, 3500)])

    def test_lancamentos_da_garota_em_ordem_com_operador_e_turno(self):
        self.lancar(180, 25); self.lancar(156, 99); self.lancar(180, 10)
        l = self.com.lancamentos(180)
        self.assertEqual([(i["valor_cent"], i["operador"], i["turno"]) for i in l], [(2500, "ADM", 1), (1000, "ADM", 1)])

    def test_resumo_do_turno_ignora_cancelados(self):
        self.garota(180, "MARIA")
        a = self.lancar(180, 25); self.lancar(180, 10); self.lancar(156, 40)
        self.com.cancelar(a, self.adm, "digitei errado")
        r = self.com.resumo_turno(self.turno)
        self.assertEqual((r["quantidade"], r["total_cent"]), (2, 5000))
        self.assertEqual([(g["garota"], g["nome"], g["total_cent"]) for g in r["por_garota"]], [(156, "", 4000), (180, "MARIA", 1000)])


class TesteCancelarComissao(BaseComissao):
    def test_cancela_o_pendente_e_guarda_quem_e_quando(self):
        cid = self.lancar(180, 25)
        self.com.cancelar(cid, self.adm, "valor errado")
        c = self.banco.um("SELECT * FROM comissoes_garotas WHERE id = ?", (cid,))
        self.assertEqual((c["status"], c["cancelada_por"], c["motivo_cancelamento"]), ("cancelada", self.adm, "valor errado"))
        self.assertTrue(c["cancelada_em"])
        self.assertEqual(self.com.pendente(180), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'comissao_cancelada'"), 1)

    def test_nao_cancela_duas_vezes_nem_o_que_ja_foi_pago(self):
        a, b = self.lancar(180, 25), self.lancar(156, 40)
        self.com.cancelar(a, self.adm)
        with self.assertRaises(ErroNegocio):
            self.com.cancelar(a, self.adm)
        self.com.pagar(156, self.turno, self.adm)
        with self.assertRaises(ErroNegocio) as e:
            self.com.cancelar(b, self.adm)
        self.assertIn("pendente", str(e.exception))


class TestePagarComissao(BaseComissao):
    def test_paga_tudo_da_garota_e_tira_o_dinheiro_do_caixa(self):
        self.garota(180, "MARIA")
        self.lancar(180, 25); self.lancar(180, 30); self.lancar(156, 40)
        esperado = self.turnos.resumo(self.turno)["esperado"]
        p = self.com.pagar(180, self.turno, self.adm)
        self.assertEqual((p["garota"], p["nome"], p["total_cent"], p["quantidade"], p["tirou_do_caixa"]), (180, "MARIA", 5500, 2, True))
        self.assertEqual(self.com.pendente(180), 0)
        self.assertEqual(self.com.pendente(156), 4000)                                  # só a garota paga
        m = self.banco.um("SELECT * FROM movimentos_caixa")
        self.assertEqual((m["tipo"], m["valor_cent"], m["descricao"]), ("saida", 5500, "Comissão garota 180 MARIA"))
        self.assertEqual(self.turnos.resumo(self.turno)["esperado"], esperado - 5500)  # a conferência da gaveta já conta
        pagas = self.banco.todos("SELECT status, movimento_id, pago_por FROM comissoes_garotas WHERE garota = 180")
        self.assertEqual([(r["status"], r["movimento_id"], r["pago_por"]) for r in pagas], [("paga", m["id"], self.adm)] * 2)

    def test_pagar_fora_do_caixa_nao_registra_saida(self):
        self.lancar(180, 25)
        p = self.com.pagar(180, self.turno, self.adm, tirar_do_caixa=False)
        self.assertEqual((p["total_cent"], p["movimento_id"], p["tirou_do_caixa"]), (2500, None, False))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 0)
        self.assertEqual(self.com.pendente(180), 0)

    def test_nao_paga_duas_vezes_nem_o_que_nao_existe(self):
        self.lancar(180, 25)
        self.com.pagar(180, self.turno, self.adm)
        for numero in (180, 7):
            with self.assertRaises(ErroNegocio, msg=str(numero)) as e:
                self.com.pagar(numero, self.turno, self.adm)
            self.assertIn("não tem comissão pendente", str(e.exception))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 1)

    def test_turno_fechado_nao_deixa_pagar_com_dinheiro_do_caixa_e_nada_muda(self):
        self.lancar(180, 25)
        self.turnos.fechar(self.turno, self.adm, 10000)
        with self.assertRaises(ErroNegocio):
            self.com.pagar(180, self.turno, self.adm)
        self.assertEqual(self.com.pendente(180), 2500)                                  # a transação desfez tudo
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 0)

    def test_o_que_foi_cancelado_nao_e_pago(self):
        a = self.lancar(180, 25); self.lancar(180, 10)
        self.com.cancelar(a, self.adm)
        p = self.com.pagar(180, self.turno, self.adm)
        self.assertEqual((p["total_cent"], p["quantidade"]), (1000, 1))

    def test_comissao_paga_em_um_turno_e_lancada_em_outro(self):
        self.lancar(180, 25)
        self.turnos.fechar(self.turno, self.adm, 10000)
        turno2 = self.turnos.abrir(self.adm, 2, 5000)
        p = self.com.pagar(180, turno2, self.adm)                                       # pendente atravessa o turno
        self.assertEqual(p["total_cent"], 2500)
        self.assertEqual(self.banco.valor("SELECT turno_id FROM movimentos_caixa"), turno2)

    def test_recibo_traz_lancamentos_total_e_assinatura(self):
        self.garota(180, "MARIA")
        self.lancar(180, 25); self.lancar(180, 30)
        p = self.com.pagar(180, self.turno, self.adm)
        recibo = ImpressaoController(self.banco).recibo_comissao(p, "ADM")
        for trecho in ("RECIBO DE COMISSÃO", "Garota: 180 MARIA", "55,00", "TOTAL PAGO (2)", "Saiu do dinheiro do caixa.",
                       "Operador: ADM", "Assinatura da garota"):
            self.assertIn(trecho, recibo)
        self.assertTrue(all(len(l) <= 40 for l in recibo.splitlines()), recibo)
        fora = self.com.pagar(156, self.turno, self.adm, False) if self.lancar(156, 1) else None
        self.assertIn("Pago fora do caixa.", ImpressaoController(self.banco).recibo_comissao(fora, "ADM"))


class TesteRelatorioDeComissao(BaseComissao):
    def setUp(self):
        super().setUp()
        self.rel = RelatorioController(self.banco)
        self.f = {"de": fmt.hoje(), "ate": fmt.hoje()}
        self.garota(180, "MARIA")
        self.lancar(180, 25); self.lancar(180, 30); self.lancar(156, 40)
        self.com.pagar(156, self.turno, self.adm)
        errado = self.lancar(156, 999)
        self.com.cancelar(errado, self.adm)

    def test_resumo_por_garota_com_pago_e_a_pagar(self):
        r = self.rel.comissoes_garotas(self.f)
        self.assertEqual(r.titulo, "Comissão das garotas")
        self.assertEqual(r.linhas, [["156", "", "1", "40,00", "40,00", "0,00"], ["180", "MARIA", "2", "55,00", "0,00", "55,00"]])
        self.assertEqual(dict(r.rodape), {"Total lançado": "95,00", "Já pago": "40,00", "A pagar": "55,00"})

    def test_cancelado_so_aparece_quando_a_situacao_e_pedida(self):
        r = self.rel.comissoes_garotas({**self.f, "situacao_comissao": "cancelada"})
        self.assertEqual([(l[0], l[3]) for l in r.linhas], [("156", "999,00")])
        pendentes = self.rel.comissoes_garotas({**self.f, "situacao_comissao": "pendente"})
        self.assertEqual([(l[0], l[3]) for l in pendentes.linhas], [("180", "55,00")])

    def test_filtra_por_garota_e_por_turno(self):
        r = self.rel.comissoes_garotas({**self.f, "garota": "180"})
        self.assertEqual([l[0] for l in r.linhas], ["180"])
        self.assertIn("Garota: 180", r.criterios)
        self.assertEqual(len(self.rel.comissoes_garotas({**self.f, "turno": "1"}).linhas), 2)
        self.assertEqual(self.rel.comissoes_garotas({**self.f, "turno": "9"}).linhas, [])

    def test_periodo_sem_lancamentos_vem_vazio(self):
        ontem = fmt.somar_dias(fmt.hoje(), -1)
        self.assertEqual(self.rel.comissoes_garotas({"de": ontem, "ate": ontem}).linhas, [])

    def test_comissao_da_madrugada_conta_na_noite_anterior(self):
        hoje = fmt.hoje()                                       # 03/10 às 21h
        self.avancar(hours=5)                                   # 04/10 às 2h: ainda é a noite de 03/10 (virada às 6h)
        self.lancar(180, 10)
        r = self.rel.comissoes_garotas({"de": hoje, "ate": hoje, "garota": "180"})
        self.assertEqual(r.linhas[0][2:4], ["3", "65,00"])
        amanha = fmt.somar_dias(hoje, 1)
        self.assertEqual(self.rel.comissoes_garotas({"de": amanha, "ate": amanha}).linhas, [])

    def test_detalhado_lista_cada_lancamento_com_situacao_e_operador(self):
        r = self.rel.comissoes_garotas({**self.f, "detalhar": True})
        self.assertEqual(r.titulo, "Comissão das garotas (lançamentos)")
        self.assertEqual([(l[1], l[4], l[5], l[6]) for l in r.linhas],
                         [("180", "25,00", "A pagar", "ADM"), ("180", "30,00", "A pagar", "ADM"), ("156", "40,00", "Paga", "ADM")])
        self.assertEqual(dict(r.rodape)["Total (sem os cancelados)"], "95,00")

    def test_detalhado_com_cancelados_mostra_a_situacao(self):
        r = self.rel.comissoes_garotas({**self.f, "detalhar": True, "situacao_comissao": "cancelada"})
        self.assertEqual([(l[1], l[4], l[5]) for l in r.linhas], [("156", "999,00", "Cancelada")])


class TesteCadastroDeGarotas(BaseComissao):
    def test_cadastra_e_lista_pelo_numero(self):
        self.garota(180, "MARIA"); self.garota(156, "ANA")
        self.assertEqual([(g["numero"], g["nome"]) for g in self.cad.listar("garotas")], [(156, "ANA"), (180, "MARIA")])

    def test_numero_repetido_e_fora_da_faixa_sao_recusados(self):
        self.garota(180, "MARIA")
        with self.assertRaises(ErroNegocio):
            self.garota(180, "OUTRA")
        for ruim in (0, 100000, -5):
            with self.assertRaises((ErroNegocio, ErroValidacao), msg=str(ruim)):
                self.garota(ruim, "X")

    def test_nome_e_obrigatorio(self):
        with self.assertRaises((ErroNegocio, ErroValidacao)):
            self.cad.salvar("garotas", {"numero": 5, "nome": ""})

    def test_garota_com_comissao_registrada_nao_e_excluida_mas_pode_ficar_inativa(self):
        gid = self.garota(180, "MARIA")
        self.lancar(180, 25)
        with self.assertRaises(ErroNegocio) as e:
            self.cad.excluir("garotas", gid)
        self.assertIn("Desmarque 'Ativa'", str(e.exception))
        self.cad.salvar("garotas", {"numero": 180, "nome": "MARIA", "ativo": "N"}, gid)
        self.assertEqual(self.com.garota(180)["ativo"], 0)

    def test_garota_sem_comissao_pode_ser_excluida(self):
        gid = self.garota(7, "NOVA")
        self.cad.excluir("garotas", gid)
        self.assertIsNone(self.com.garota(7))

    def test_o_cadastro_exige_o_modulo_cad_garotas(self):
        from src.controllers.entidades import ENTIDADES
        self.assertEqual(ENTIDADES["garotas"].modulo, "cad_garotas")
        self.assertIsNotNone(self.banco.valor("SELECT nivel FROM acessos WHERE modulo = 'cad_garotas'"))


class TesteMigracaoV7(unittest.TestCase):
    def test_banco_da_versao_6_ganha_as_tabelas_e_as_chaves_da_comissao(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "v6.db")
            b = BancoDados(caminho)
            b.executar("DROP TABLE comissoes_garotas")
            b.executar("DROP TABLE garotas")
            b.executar("DELETE FROM config WHERE chave IN ('codigo_comissao', 'exigir_senha_comissao')")
            b.executar("DELETE FROM acessos WHERE modulo IN ('cad_garotas', 'caixa_comissao', 'caixa_pagar_comissao', 'rel_comissao_garotas')")
            b.executar("PRAGMA user_version = 6")
            b.fechar()
            b = BancoDados(caminho)
            try:
                self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
                tabelas = {r[0] for r in b.todos("SELECT name FROM sqlite_master WHERE type = 'table'")}
                self.assertTrue({"garotas", "comissoes_garotas"} <= tabelas)
                self.assertEqual((b.cfg("codigo_comissao"), b.cfg("exigir_senha_comissao")), ("50", "N"))
                self.assertEqual(b.valor("SELECT COUNT(*) FROM acessos WHERE modulo IN "
                                         "('cad_garotas','caixa_comissao','caixa_pagar_comissao','rel_comissao_garotas')"), 4)
            finally:
                b.fechar()


class TesteConferenciaDoTurnoComComissoes(BaseComissao):
    """O dono vê, ao fechar o turno, quanto de comissão foi lançado e o que ainda está a pagar."""

    def fita(self, turno=None):
        from src.controllers.conferencia_turno import linhas_fita
        return linhas_fita(self.turnos.resumo(turno or self.turno), 40)

    def test_resumo_do_turno_traz_o_lancado_e_o_que_falta_pagar(self):
        self.garota(180, "MARIA")
        self.lancar(180, 25); self.lancar(180, 30); self.lancar(156, 40)
        c = self.turnos.resumo(self.turno)["comissoes"]
        self.assertEqual((c["quantidade"], c["total_cent"], c["a_pagar_cent"]), (3, 9500, 9500))
        self.assertEqual([(g["garota"], g["nome"], g["lancamentos"], g["total_cent"]) for g in c["por_garota"]],
                         [(156, "", 1, 4000), (180, "MARIA", 2, 5500)])

    def test_pago_sai_do_a_pagar_mas_continua_lancado_no_turno(self):
        self.lancar(180, 25); self.lancar(156, 40)
        self.com.pagar(180, self.turno, self.adm)
        c = self.turnos.resumo(self.turno)["comissoes"]
        self.assertEqual((c["total_cent"], c["a_pagar_cent"]), (6500, 4000))

    def test_cancelado_nao_conta_nem_no_lancado_nem_no_a_pagar(self):
        errado = self.lancar(180, 999); self.lancar(180, 25)
        self.com.cancelar(errado, self.adm)
        c = self.turnos.resumo(self.turno)["comissoes"]
        self.assertEqual((c["quantidade"], c["total_cent"], c["a_pagar_cent"]), (1, 2500, 2500))

    def test_fita_traz_a_secao_com_as_garotas_o_total_e_o_a_pagar(self):
        self.garota(180, "MARIA")
        self.lancar(180, 25); self.lancar(180, 30); self.lancar(156, 40)
        linhas = self.fita()
        texto = "\n".join(linhas)
        for trecho in ("COMISSÕES DAS GAROTAS (2)", "156 (1x)", "180 MARIA (2x)", "55,00", "Total lançado no turno", "95,00",
                       "A pagar às garotas (todas)"):
            self.assertIn(trecho, texto)
        self.assertTrue(all(len(l) <= 40 for l in linhas), linhas)

    def test_turno_sem_comissao_nao_ganha_secao_na_fita(self):
        self.assertNotIn("COMISSÕES", "\n".join(self.fita()))

    def test_pendente_de_turno_anterior_aparece_como_a_pagar_no_turno_novo(self):
        self.lancar(180, 25)
        self.turnos.fechar(self.turno, self.adm, 10000)
        turno2 = self.turnos.abrir(self.adm, 2, 5000)
        texto = "\n".join(self.fita(turno2))
        self.assertIn("COMISSÕES DAS GAROTAS (0)", texto)
        self.assertIn("A pagar às garotas (todas)", texto)
        self.assertNotIn("Total lançado no turno", texto)

    def test_fechamento_impresso_leva_a_secao(self):
        self.lancar(180, 25)
        texto = ImpressaoController(self.banco).fechamento(self.turnos.resumo(self.turno))
        self.assertIn("COMISSÕES DAS GAROTAS", texto)
        self.assertIn("180 (1x)", texto)

    def test_total_a_pagar_soma_todas_as_garotas(self):
        self.assertEqual(self.com.total_a_pagar(), 0)
        self.lancar(180, 25); self.lancar(156, 40)
        self.assertEqual(self.com.total_a_pagar(), 6500)
        self.com.pagar(156, self.turno, self.adm)
        self.assertEqual(self.com.total_a_pagar(), 2500)


class TesteLimpezaDoMovimentoComComissoes(BaseComissao):
    """A limpeza do movimento apaga turnos e sangrias antigos: não pode quebrar nem sumir com comissão que ainda se deve."""

    def setUp(self):
        super().setUp()
        from src.controllers.utilitario_controller import UtilitarioController
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.banco.cfg_set("pasta_backup", self.pasta.name)
        self.util = UtilitarioController(self.banco, self.adm)

    def abrir_turno_antigo(self, dias=10):
        """Fecha o turno de hoje e abre outro `dias` atrás; devolve o id do antigo."""
        self.turnos.fechar(self.turno, self.adm, 10000)
        self.avancar(days=-dias)
        return self.turnos.abrir(self.adm, 2, 0)

    def voltar_ao_presente(self, antigo, dias=10):
        self.turnos.fechar(antigo, self.adm, 0)
        self.avancar(days=dias)
        self.turno = self.turnos.abrir(self.adm, 3, 0)

    def test_apaga_as_pagas_e_canceladas_e_guarda_as_pendentes(self):
        antigo = self.abrir_turno_antigo()
        self.lancar(180, 25, antigo); self.lancar(180, 30, antigo)
        self.lancar(156, 40, antigo)
        errado = self.lancar(7, 10, antigo)
        self.com.cancelar(errado, self.adm)
        self.com.pagar(180, antigo, self.adm)                        # gera uma sangria no turno antigo
        self.voltar_ao_presente(antigo)
        self.lancar(99, 5)                                           # do turno de hoje: não se mexe
        res = self.util.limpar_movimento(fmt.fmt_data(fmt.somar_dias(fmt.hoje(), -2)))
        self.assertEqual((res["turnos"], res["comissoes"]), (1, 3))                      # 2 pagas e 1 cancelada
        restantes = {r["garota"]: (r["status"], r["turno_id"]) for r in
                     self.banco.todos("SELECT garota, status, turno_id FROM comissoes_garotas")}
        self.assertEqual(restantes, {156: ("pendente", None), 99: ("pendente", self.turno)})
        self.assertEqual(self.com.pendente(156), 4000)                                   # o que se deve não some
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 0)   # a sangria antiga foi limpa
        self.com.pagar(156, self.turno, self.adm)                                        # e ainda dá para pagar depois
        self.assertEqual(self.com.pendente(156), 0)

    def test_limpeza_sem_nenhuma_comissao_segue_igual(self):
        antigo = self.abrir_turno_antigo()
        self.voltar_ao_presente(antigo)
        res = self.util.limpar_movimento(fmt.fmt_data(fmt.somar_dias(fmt.hoje(), -2)))
        self.assertEqual((res["turnos"], res["comissoes"]), (1, 0))


class TesteMarcadasNaComanda(BaseComissao):
    """O que aparece quando se abre a comanda da garota: o pendente e o que foi pago neste turno."""

    def test_pendente_aparece_em_ordem_com_o_nome_do_operador(self):
        self.lancar(180, 25); self.lancar(180, 30); self.lancar(156, 99)
        m = self.com.marcadas(180, self.turno)
        self.assertEqual([(c["valor_cent"], c["status"], c["operador"]) for c in m], [(2500, "pendente", "ADM"), (3000, "pendente", "ADM")])

    def test_sem_turno_so_o_pendente(self):
        self.lancar(180, 25)
        self.com.pagar(180, self.turno, self.adm)
        self.lancar(180, 30)
        self.assertEqual([c["status"] for c in self.com.marcadas(180)], ["pendente"])
        self.assertEqual([c["status"] for c in self.com.marcadas(180, self.turno)], ["paga", "pendente"])

    def test_cancelado_nao_aparece(self):
        errado = self.lancar(180, 999); self.lancar(180, 25)
        self.com.cancelar(errado, self.adm)
        self.assertEqual([c["valor_cent"] for c in self.com.marcadas(180, self.turno)], [2500])

    def test_pendente_de_turno_anterior_aparece_mas_a_paga_de_turno_anterior_nao(self):
        self.lancar(180, 25); self.lancar(156, 40)
        self.com.pagar(180, self.turno, self.adm)
        self.turnos.fechar(self.turno, self.adm, 10000)
        turno2 = self.turnos.abrir(self.adm, 2, 0)
        self.assertEqual(self.com.marcadas(180, turno2), [])                              # paga no turno 1
        self.assertEqual([c["valor_cent"] for c in self.com.marcadas(156, turno2)], [4000])   # pendente atravessa o turno

    def test_numero_invalido_e_recusado(self):
        with self.assertRaises(ErroNegocio):
            self.com.marcadas(0)


class TesteLimpezaDeComissaoPagaEmOutroTurno(BaseComissao):
    """Comissão lançada num turno que a limpeza mantém e paga em outro que ela apaga não pode quebrar a limpeza."""

    def setUp(self):
        super().setUp()
        from src.controllers.utilitario_controller import UtilitarioController
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.banco.cfg_set("pasta_backup", self.pasta.name)
        self.util = UtilitarioController(self.banco, self.adm)

    def test_lancada_em_turno_que_fica_e_paga_em_turno_apagado(self):
        self.turnos.fechar(self.turno, self.adm, 10000)
        self.avancar(days=-10)
        a = self.turnos.abrir(self.adm, 2, 0)
        # Caso raro, forçado: uma venda ainda aberta presa ao turno A o impede de ser apagado (mesa aberta normal não tem turno).
        self.banco.inserir("vendas", {"uuid": "prende-o-turno-a", "modalidade": "mesa", "posicao": 9, "turno_id": a,
                                      "aberta_em": fmt.agora()})
        self.lancar(180, 25, a)
        self.turnos.fechar(a, self.adm, 0)
        self.avancar(days=2)
        b = self.turnos.abrir(self.adm, 3, 0)
        self.com.pagar(180, b, self.adm)                          # paga em B: sangria e pago_turno_id apontam para B
        self.turnos.fechar(b, self.adm, 0)
        self.avancar(days=8)
        self.turno = self.turnos.abrir(self.adm, 4, 0)
        res = self.util.limpar_movimento(fmt.fmt_data(fmt.somar_dias(fmt.hoje(), -2)))
        self.assertEqual(res["turnos"], 1)                        # só o B
        c = self.banco.um("SELECT turno_id, status, pago_turno_id, movimento_id FROM comissoes_garotas")
        self.assertEqual((c["turno_id"], c["status"], c["pago_turno_id"], c["movimento_id"]), (a, "paga", None, None))


class TesteMigracaoV8(unittest.TestCase):
    """Bancos que já estavam na v7 criaram a tabela de comissões sem pago_turno_id: a v8 acrescenta a coluna."""

    TABELA_DA_V7 = """CREATE TABLE comissoes_garotas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        garota INTEGER NOT NULL CHECK (garota BETWEEN 1 AND 99999),
        valor_cent INTEGER NOT NULL CHECK (valor_cent > 0),
        turno_id INTEGER REFERENCES turnos(id),
        operador_id INTEGER REFERENCES operadores(id),
        observacao TEXT,
        criado_em TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','paga','cancelada')),
        paga_em TEXT,
        pago_por INTEGER REFERENCES operadores(id),
        movimento_id INTEGER REFERENCES movimentos_caixa(id),
        cancelada_em TEXT,
        cancelada_por INTEGER REFERENCES operadores(id),
        motivo_cancelamento TEXT
    )"""

    def test_banco_da_v7_ganha_a_coluna_e_as_pagas_antigas_recebem_o_turno(self):
        from src.controllers.turno_controller import TurnoController
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "v7.db")
            b = BancoDados(caminho)
            adm = b.valor("SELECT id FROM operadores WHERE nome = 'ADM'")
            turno = TurnoController(b).abrir(adm, 1, 10000)
            mov = TurnoController(b).movimentar(turno, adm, "saida", 2500, "Comissão garota 180")
            b.executar("DROP TABLE comissoes_garotas")            # volta ao desenho da v7: sem pago_turno_id
            b.executar(self.TABELA_DA_V7)
            b.executar("INSERT INTO comissoes_garotas (garota, valor_cent, turno_id, operador_id, criado_em, status, paga_em, "
                       "pago_por, movimento_id) VALUES (180, 2500, ?, ?, '2026-10-03 21:00:00', 'paga', '2026-10-03 22:00:00', ?, ?)",
                       (turno, adm, adm, mov))
            b.executar("INSERT INTO comissoes_garotas (garota, valor_cent, turno_id, operador_id, criado_em) "
                       "VALUES (156, 4000, ?, ?, '2026-10-03 21:05:00')", (turno, adm))
            b.executar("PRAGMA user_version = 7")
            b.fechar()
            b = BancoDados(caminho)
            try:
                self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
                self.assertIn("pago_turno_id", [r[1] for r in b.todos("PRAGMA table_info(comissoes_garotas)")])
                self.assertEqual(b.valor("SELECT pago_turno_id FROM comissoes_garotas WHERE garota = 180"), turno)   # preenchido
                self.assertIsNone(b.valor("SELECT pago_turno_id FROM comissoes_garotas WHERE garota = 156"))
                # e o fluxo novo funciona sobre o banco migrado
                com = ComissaoController(b)
                self.assertEqual([c["garota"] for c in com.marcadas(180, turno)] + [c["garota"] for c in com.marcadas(156, turno)],
                                 [180, 156])
                pago = com.pagar(156, turno, adm)
                self.assertEqual(pago["total_cent"], 4000)
                self.assertEqual(b.valor("SELECT pago_turno_id FROM comissoes_garotas WHERE garota = 156"), turno)
            finally:
                b.fechar()

    def test_banco_novo_ja_nasce_com_a_coluna_e_a_migracao_nao_estraga_nada(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "novo.db")
            b = BancoDados(caminho)
            b.executar("PRAGMA user_version = 6")                  # simula um banco antigo que já tinha a tabela nova
            b.fechar()
            b = BancoDados(caminho)
            try:
                colunas = [r[1] for r in b.todos("PRAGMA table_info(comissoes_garotas)")]
                self.assertEqual(colunas.count("pago_turno_id"), 1)
                self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
            finally:
                b.fechar()


if __name__ == "__main__":
    unittest.main()


class TesteComissaoEmPontos(BaseComissao):
    """A casa marca em pontos: 0,1 = R$ 5,00, 0,2 = R$ 10,00, 0,3 = R$ 15,00."""

    def test_padrao_e_pontos_de_cinco_reais(self):
        com = self.com
        self.assertTrue(com.em_pontos())
        self.assertEqual([com.para_centavos(t) for t in ("0,1", "0,2", "0,3", "1,5")], [500, 1000, 1500, 7500])
        self.assertEqual(com.rotulo_valor(), "Pontos (1 = 0,1 = R$ 5,00)")

    def test_numero_sem_virgula_conta_em_decimos(self):
        """Na casa: digitou 1 é 0,1 (R$ 5,00), 2 é 0,2 (R$ 10,00), 10 é 1,0 (R$ 50,00)."""
        self.assertEqual([self.com.para_centavos(t) for t in ("1", "2", "3", " 6 ", "10")], [500, 1000, 1500, 3000, 5000])
        self.assertEqual(self.com.em_pontos_texto(self.com.para_centavos("2")), "0,2 (R$ 10,00)")
        self.assertEqual(self.com.em_pontos_texto(1500), "0,3 (R$ 15,00)")

    def test_fracao_menor_que_0_1_e_recusada(self):
        with self.assertRaisesRegex(ErroNegocio, "0,1 em 0,1"):
            self.com.para_centavos("0,15")
        with self.assertRaises(ValueError):
            self.com.para_centavos("abc")

    def test_valor_do_ponto_configuravel_e_modo_reais(self):
        self.banco.cfg_set("comissao_valor_ponto", "2,50")
        self.assertEqual(self.com.para_centavos("0,4"), 1000)
        self.banco.cfg_set("comissao_em_pontos", "N")
        self.assertEqual(self.com.para_centavos("25,00"), 2500)
        self.assertEqual(self.com.rotulo_valor(), "Valor (R$)")
        self.assertEqual(self.com.em_pontos_texto(2500), "R$ 25,00")

    def test_via_da_garota_mostra_os_pontos(self):
        from src.controllers.impressao_controller import ImpressaoController
        cid = self.com.lancar(180, self.com.para_centavos("0,3"), self.turno, self.adm)
        lanc = self.com.lancamento(cid)
        via = ImpressaoController(self.banco).via_comissao(lanc, "Bia", "ADM")
        self.assertIn("Pontos desta comissão", via)
        self.assertIn("0,3 (R$ 15,00)", via)

    def test_pontos_saem_em_letra_grande_na_termica(self):
        from src.controllers.impressao_controller import _ESTILOS
        self.assertIn("Pontos desta", _ESTILOS["via_comissao"]["grande_prefixos"])

