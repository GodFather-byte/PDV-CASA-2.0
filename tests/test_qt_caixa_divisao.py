"""Caixa Qt: cancelamento parcial por quantidade e divisão da conta (por valor e por item)."""
from tests.test_caixa_cancelamento_parcial import criar_vinculos
from tests.test_qt_caixa import BaseCaixaQt


class TestCaixaQtParcialDivisao(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        criar_vinculos(self.banco)
        self.abrir_turno()
        self.cerveja = self.novo_produto("CERVEJA", 800, codigo="71")
        self.queijo = self.novo_produto("QUEIJO", 1000, codigo="72", aceita_decimal="S")
        self.j = self.janela()

    def ativos(self):
        return [dict(r) for r in self.banco.todos(
            "SELECT produto_id, quantidade, total_cent, cancelado FROM itens_venda ORDER BY id")]

    def cancelar(self, linha, textos, confirmacoes=(True,)):
        self.j.tabela.selectRow(linha)
        self.j.dialogos.textos = list(textos)
        self.j.dialogos.confirmacoes = list(confirmacoes)
        self.j.btn_cancelar_item.click()

    def test_cancelamento_parcial_pede_quantidade_e_motivo(self):
        self.lancar(self.j, "71", "5")
        self.cancelar(0, ["2", "", "cliente desistiu"])          # motivo vazio é recusado e perguntado de novo
        self.assertIn("Informe o motivo.", self.j.dialogos.avisos)
        self.assertEqual(self.ativos(), [
            {"produto_id": self.cerveja, "quantidade": 3, "total_cent": 2400, "cancelado": 0},
            {"produto_id": self.cerveja, "quantidade": 2, "total_cent": 1600, "cancelado": 1}])
        self.assertEqual(self.j.lbl_total.text(), "24,00")
        self.assertIn("Cancelado 2", self.j.lbl_status.text())

    def test_quantidade_invalida_e_fracao(self):
        self.lancar(self.j, "71", "3")
        self.cancelar(0, ["9", "1,5", None])                     # acima do lançado, fração num inteiro, desiste
        self.assertEqual(len(self.j.dialogos.avisos), 2)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda WHERE cancelado = 1"), 0)
        self.lancar(self.j, "72", "1,5")
        self.cancelar(1, ["0,75", "quebrou"])                    # quantidade fracionada: pergunta
        self.assertEqual(self.banco.valor("SELECT quantidade FROM itens_venda WHERE produto_id = ? AND cancelado = 0",
                                          (self.queijo,)), 0.75)

    def test_quantidade_total_mantem_o_cancelamento_antigo(self):
        self.lancar(self.j, "71", "2")
        self.cancelar(0, ["2"])                                   # tudo: sem motivo obrigatório (configuração desligada)
        self.assertEqual(self.ativos(), [{"produto_id": self.cerveja, "quantidade": 2, "total_cent": 1600, "cancelado": 1}])
        self.lancar(self.j, "71", "1")
        self.cancelar(0, [])                                      # uma unidade: não pergunta quantidade
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda WHERE cancelado = 0"), 0)

    def test_dividir_conta_sugere_as_partes_em_ordem(self):
        self.lancar(self.j, "71", "1")
        self.lancar(self.j, "72", "0,2")                          # 8,00 + 2,00 = 10,00 em 3 partes
        self.j.dialogos.textos = ["1", "3"]
        self.j.btn_dividir.click()
        self.assertTrue(self.j.dialogos.avisos)
        self.assertEqual(self.j.ent_valor.text(), "3,34")
        self.forma(self.j, "Pix")
        self.assertEqual(self.j.ent_valor.text(), "3,34")
        self.j.btn_receber.click()
        self.assertEqual(self.j.ent_valor.text(), "3,33")
        self.j.btn_receber.click()
        self.j.btn_receber.click()
        self.assertEqual(sum(p["valor_cent"] for p in self.ctx.caixa.pagamentos(self.j.venda_id)), 1000)
        self.assertIsNone(self.j._divisao)

    def test_pagar_itens_vincula_e_impede_duplicidade(self):
        self.lancar(self.j, "71", "3")
        self.lancar(self.j, "72", "1")
        vid = self.j.venda_id
        cerveja = self.ctx.caixa.itens(vid)[0]["id"]
        self.forma(self.j, "Pix")
        self.j.dialogos.escolhas = [cerveja, "ok"]
        self.j.dialogos.textos = ["2"]
        self.j.dialogos.confirmacoes = [True]
        self.j.btn_pagar_itens.click()
        pags = self.ctx.caixa.pagamentos(vid)
        self.assertEqual([p["valor_cent"] for p in pags], [1600])
        self.assertEqual([(x["item_id"], x["quantidade"]) for x in self.ctx.caixa.itens_do_pagamento(pags[0]["id"])],
                         [(cerveja, 2)])
        self.cancelar(0, ["2", "engano"])                         # só 1 cerveja está livre: o controlador recusa
        self.assertTrue(any("já foi paga" in e for e in self.j.dialogos.erros))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda WHERE cancelado = 1"), 0)
        self.j.dialogos.escolhas = [cerveja, "ok"]                # a cerveja livre: 1 unidade, sem perguntar
        self.j.dialogos.confirmacoes = [True]
        self.j.btn_pagar_itens.click()
        self.assertEqual(sum(p["valor_cent"] for p in self.ctx.caixa.pagamentos(vid)), 2400)
        opcoes = []
        self.j.dialogos.escolher = lambda t, r, o: opcoes.extend(o)
        self.j.btn_pagar_itens.click()
        self.assertNotIn(cerveja, [v for v, _ in opcoes])         # já paga: nem aparece
        self.j.lista_pagamentos.setCurrentRow(0)
        self.j.btn_remover_pag.click()                            # remover libera os itens
        livre = {d["item_id"]: d["qtd_livre"] for d in self.ctx.caixa.itens_para_divisao(vid)}
        self.assertEqual(livre[cerveja], 2)

    def test_pagar_itens_com_taxa_da_forma_e_desistencia(self):
        self.lancar(self.j, "71", "1")
        vid = self.j.venda_id
        item = self.ctx.caixa.itens(vid)[0]["id"]
        self.forma(self.j, "Cartão Crédito")
        self.j.dialogos.escolhas = [item, "ok"]
        self.j.dialogos.confirmacoes = [False]
        self.j.btn_pagar_itens.click()
        self.assertEqual(self.ctx.caixa.pagamentos(vid), [])
        self.j.dialogos.escolhas = [item, "ok"]
        self.j.dialogos.confirmacoes = [True]
        self.j.btn_pagar_itens.click()
        self.assertIn("Taxa da forma", self.j.dialogos.perguntas[-1])
        self.assertEqual([p["valor_cent"] for p in self.ctx.caixa.pagamentos(vid)], [1300])
        self.assertEqual(self.ctx.caixa.liquidar(vid)["falta"], 0)
