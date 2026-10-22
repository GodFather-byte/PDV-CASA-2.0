"""Conferência por forma, justificativa e preservação do fechamento já assinado."""
from unittest import mock
from uuid import uuid4

from src.controllers.cadastro_controller import CadastroController
from src.controllers.conferencia_turno import linhas_fita
from src.controllers.devolucoes_controller import DevolucoesController
from src.core.erros import ErroNegocio
from tests.test_caixa import BaseCaixa


class TesteFechamentoExplicativo(BaseCaixa):
    def contagens(self, **valores):
        return {f["tipo_id"]: valores.get(f["tipo"], 0)
                for f in self.turnos.formas_conferencia(self.turno, self.adm)}

    def venda_paga(self, forma, valor=800):
        venda = self.vender((self.skol, 1))
        self.pagar(venda, forma, valor)
        return self.caixa.fechar(venda)

    def test_gaveta_com_troco_sangria_suprimento_e_formas_nao_fisicas(self):
        self.venda_paga("Dinheiro", 1000)
        self.venda_paga("Cartão Débito")
        self.venda_paga("Pix")
        self.turnos.movimentar(self.turno, self.adm, "entrada", 500, "Troco")
        self.turnos.movimentar(self.turno, self.adm, "saida", 300, "Gelo")
        valores = self.contagens(**{"Dinheiro": 11000, "Cartão Débito": 800, "Pix": 800})
        res = self.turnos.fechar(self.turno, self.adm, 11000, informados_por_forma=valores)
        conf = res["conferencia_fechamento"]
        self.assertFalse(conf["tem_diferenca"])
        self.assertEqual(conf["composicao"]["troco_cent"], 200)
        self.assertEqual(res["esperado"], self.turnos.dinheiro_esperado(self.turno))
        self.assertEqual({l["tipo"]: l["esperado_cent"] for l in conf["linhas"]},
                         {"Dinheiro": 11000, "Cartão Débito": 800, "Cartão Crédito": 0, "Pix": 800})

    def test_diferenca_nao_fisica_exige_motivo_mesmo_com_gaveta_exata(self):
        self.venda_paga("Pix")
        valores = self.contagens(**{"Dinheiro": 10000, "Pix": 700})
        with self.assertRaisesRegex(ErroNegocio, "justificativa obrigatória"):
            self.turnos.fechar(self.turno, self.adm, 10000, informados_por_forma=valores)
        self.assertEqual(self.turnos.obter(self.turno)["status"], "aberto")
        res = self.turnos.fechar(self.turno, self.adm, 10000, informados_por_forma=valores,
                                 justificativa="  Pix ainda não localizado no extrato  ")
        self.assertEqual(res["resultado"], 0)
        self.assertTrue(res["conferencia_fechamento"]["tem_diferenca"])
        pix = next(l for l in res["conferencia_fechamento"]["linhas"] if l["tipo"] == "Pix")
        self.assertEqual(pix["diferenca_cent"], -100)
        self.assertEqual(res["conferencia_fechamento"]["justificativa"], "Pix ainda não localizado no extrato")

    def test_diferencas_compensadas_entre_cartao_e_pix_nao_desaparecem(self):
        self.venda_paga("Cartão Débito")
        self.venda_paga("Pix")
        valores = self.contagens(**{"Dinheiro": 10000, "Cartão Débito": 700, "Pix": 900})
        with self.assertRaisesRegex(ErroNegocio, "justificativa"):
            self.turnos.fechar(self.turno, self.adm, 10000, informados_por_forma=valores)

    def test_legado_exige_motivo_para_falta_e_nao_inventa_contagem_por_forma(self):
        with self.assertRaisesRegex(ErroNegocio, "justificativa"):
            self.turnos.fechar(self.turno, self.adm, 9900)
        res = self.turnos.fechar(self.turno, self.adm, 9900, justificativa="Falta identificada na contagem")
        conf = res["conferencia_fechamento"]
        self.assertEqual(res["resultado"], -100)
        self.assertFalse(conf["por_forma_informada"])
        self.assertTrue(all(l["informado_cent"] is None for l in conf["linhas"]))

    def test_nao_aceita_motivo_em_branco(self):
        for motivo in ("", " \n\t"):
            with self.subTest(motivo=motivo), self.assertRaisesRegex(ErroNegocio, "justificativa"):
                self.turnos.fechar(self.turno, self.adm, 10100, justificativa=motivo)

    def test_nao_aceita_mapa_parcial_nem_soma_fisica_incoerente(self):
        for valores in ({}, {self.tipo("Dinheiro"): 10000}, self.contagens(**{"Dinheiro": 9900})):
            with self.subTest(valores=valores), self.assertRaises(ErroNegocio):
                self.turnos.fechar(self.turno, self.adm, 10000, informados_por_forma=valores)
        self.assertEqual(self.turnos.obter(self.turno)["status"], "aberto")

    def test_valores_sao_inteiros_nao_negativos(self):
        for valor in (10000.0, True, -1, "10000"):
            with self.subTest(valor=valor), self.assertRaises(ErroNegocio):
                self.turnos.fechar(self.turno, self.adm, valor)
        valores = self.contagens(**{"Dinheiro": 10000})
        valores[self.tipo("Pix")] = 0.0
        with self.assertRaises(ErroNegocio):
            self.turnos.fechar(self.turno, self.adm, 10000, informados_por_forma=valores)

    def test_operador_ativo_obrigatorio_nivel_zero_preservado(self):
        operador = CadastroController(self.banco).salvar(
            "operadores", {"nome": "CAIXA", "senha": "1", "nivel": "0"})
        self.assertTrue(self.turnos.formas_conferencia(self.turno, operador))
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (operador,))
        with self.assertRaisesRegex(ErroNegocio, "operador ativo"):
            self.turnos.conferencia_fechamento(self.turno, operador, 10000)
        with self.assertRaises(ErroNegocio):
            self.turnos.fechar(self.turno, operador, 10000)

    def test_previa_nao_escreve_nem_fecha_turno(self):
        antes = self.banco.valor("SELECT COUNT(*) FROM auditoria_eventos")
        conf = self.turnos.conferencia_fechamento(self.turno, self.adm, 9900)
        self.assertTrue(conf["tem_diferenca"])
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM auditoria_eventos"), antes)
        self.assertEqual(self.turnos.obter(self.turno)["status"], "aberto")

    def test_falha_da_auditoria_reverte_fechamento_e_log(self):
        antes = self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'turno_fechado'")
        with mock.patch.object(self.banco, "registrar_auditoria", side_effect=RuntimeError("Falha simulada")):
            with self.assertRaises(RuntimeError):
                self.turnos.fechar(self.turno, self.adm, 9900, justificativa="Falta na contagem")
        self.assertEqual(self.turnos.obter(self.turno)["status"], "aberto")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'turno_fechado'"), antes)

    def test_snapshot_preserva_adiantamento_e_nome_forma_apos_turno_seguinte(self):
        self.banco.cfg_set("cobra_servico_mesa", "N")
        venda = self.vender((self.skol, 2), mesa=7)
        self.pagar(venda, "Dinheiro", 800)
        primeiro = self.turnos.fechar(self.turno, self.adm, 10800)
        novo = self.turnos.abrir(self.adm, 2, 10000)
        self.pagar(venda, "Dinheiro", 800)
        self.caixa.fechar(venda)
        self.banco.executar("UPDATE tipos_pagamento SET tipo = 'Espécie' WHERE tipo = 'Dinheiro'")
        preservado = self.turnos.resumo(self.turno)
        self.assertEqual(preservado, primeiro)
        self.assertEqual(self.turnos.resumo(novo)["recebido_turno_anterior"], 800)
        with self.assertRaisesRegex(ErroNegocio, "já foi fechado"):
            self.turnos.fechar(self.turno, self.adm, 10800)

    def test_recebimento_antigo_nao_e_cobrado_de_novo_e_motivo_no_turno_atual(self):
        self.banco.cfg_set("cobra_servico_mesa", "N")
        venda = self.vender((self.skol, 2), mesa=7)
        self.pagar(venda, "Pix", 800)
        self.turnos.fechar(self.turno, self.adm, 10000)
        self.turno = self.turnos.abrir(self.adm, 2, 10000)
        self.pagar(venda, "Dinheiro", 800)
        self.caixa.fechar(venda)
        valores = self.contagens(**{"Dinheiro": 10750})
        res = self.turnos.fechar(self.turno, self.adm, 10750, informados_por_forma=valores,
                                 justificativa="Faltam cinquenta centavos")
        self.assertEqual(res["recebido_turno_anterior"], 800)
        self.assertEqual(res["resultado"], -50)
        pix = next(l for l in res["conferencia_fechamento"]["linhas"] if l["tipo"] == "Pix")
        self.assertEqual(pix["esperado_cent"], 0)

    def test_fita_exibe_motivo_por_forma_e_nao_ultrapassa_largura(self):
        res = self.turnos.fechar(self.turno, self.adm, 9900, justificativa="Diferença de contagem " * 6)
        linhas = linhas_fita(res)
        self.assertTrue(all(len(l) <= 40 for l in linhas))
        self.assertIn("Justificativa da diferença:", linhas)
        self.assertTrue(any("POR FORMA" in l for l in linhas))

    def test_acrescimo_cartao_ja_esta_no_recebido_sem_duplicar_gaveta(self):
        self.banco.executar("UPDATE tipos_pagamento SET taxa_pct = 10 WHERE tipo = 'Cartão Crédito'")
        venda = self.vender((self.skol, 1))
        self.pagar(venda, "Cartão Crédito", 800)
        liquidacao = self.caixa.liquidar(venda)
        if liquidacao["falta"]:
            self.pagar(venda, "Cartão Crédito", liquidacao["falta"])
        self.caixa.fechar(venda)
        resumo = self.turnos.resumo(self.turno)
        recebido = next(r["valor"] for r in resumo["recebimentos"] if r["tipo"] == "Cartão Crédito")
        valores = self.contagens(**{"Dinheiro": 10000, "Cartão Crédito": recebido})
        res = self.turnos.fechar(self.turno, self.adm, 10000, informados_por_forma=valores)
        self.assertGreater(res["acrescimo"], 0)
        self.assertFalse(res["conferencia_fechamento"]["tem_diferenca"])

    def test_dinheiro_renomeado_usa_forma_fisica_que_permite_troco(self):
        self.banco.executar("UPDATE tipos_pagamento SET tipo = 'Espécie' WHERE tipo = 'Dinheiro'")
        valores = self.contagens(**{"Espécie": 10000})
        conf = self.turnos.conferencia_fechamento(self.turno, self.adm, 10000, informados_por_forma=valores)
        self.assertFalse(conf["tem_diferenca"])
        dinheiro = next(l for l in conf["linhas"] if l["dinheiro"])
        self.assertEqual(dinheiro["tipo"], "Espécie")
        self.assertEqual(dinheiro["esperado_cent"], 10000)

    def test_formas_fisicas_sao_conferidas_separadamente_sem_compensar(self):
        CadastroController(self.banco).salvar("tipos_pagamento", {"tipo": "Ticket"})
        self.venda_paga("Ticket")
        valores = self.contagens(**{"Dinheiro": 10100, "Ticket": 700})
        with self.assertRaisesRegex(ErroNegocio, "justificativa"):
            self.turnos.fechar(self.turno, self.adm, 10800, informados_por_forma=valores)
        res = self.turnos.fechar(self.turno, self.adm, 10800, informados_por_forma=valores,
                                 justificativa="Diferença na composição dinheiro e ticket")
        self.assertEqual(res["resultado"], 0)
        self.assertTrue(res["conferencia_fechamento"]["tem_diferenca"])

    def test_devolucao_dinheiro_de_turno_anterior_nao_desconta_duas_vezes(self):
        venda = self.venda_paga("Dinheiro")
        primeiro = self.turnos.fechar(self.turno, self.adm, 10800)
        antigo = self.turno
        self.turno = self.turnos.abrir(self.adm, 2, 10000)
        item = self.caixa.itens(venda["id"])[0]["id"]
        DevolucoesController(self.banco, self.adm).registrar(
            venda["id"], {item: 1}, "Produto devolvido", self.adm, "dinheiro_gaveta", str(uuid4()))
        valores = self.contagens(**{"Dinheiro": 9200})
        res = self.turnos.fechar(self.turno, self.adm, 9200, informados_por_forma=valores)
        self.assertEqual((res["saidas"], res["esperado"], res["resultado"]), (800, 9200, 0))
        self.assertEqual(res["devolucoes"]["dinheiro_gaveta_cent"], 800)
        self.assertEqual(self.turnos.resumo(antigo), primeiro)
        self.assertIn("  Dinheiro já incluído nas sangrias.", linhas_fita(res))

    def test_estorno_externo_fica_informativo_sem_reduzir_maquininha(self):
        venda = self.venda_paga("Pix")
        item = self.caixa.itens(venda["id"])[0]["id"]
        DevolucoesController(self.banco, self.adm).registrar(
            venda["id"], {item: 1}, "Produto devolvido", self.adm, "externo", str(uuid4()),
            tipo_pagamento_id=self.tipo("Pix"), referencia_externa="PIX-TESTE-123")
        valores = self.contagens(**{"Dinheiro": 10000, "Pix": 800})
        res = self.turnos.fechar(self.turno, self.adm, 10000, informados_por_forma=valores)
        conf = res["conferencia_fechamento"]
        pix = next(l for l in conf["linhas"] if l["tipo"] == "Pix")
        self.assertEqual(pix["esperado_cent"], 800)
        self.assertEqual(res["maquininha"]["total"], 800)
        self.assertEqual(conf["estornos_informados"][0]["valor_cent"], 800)
        self.assertFalse(conf["tem_diferenca"])
        self.assertEqual(res["saidas"], 0)
        self.assertIn("  Externo não comprova estorno bancário.", linhas_fita(res))
