"""Paridade da adega no caixa Qt, com banco real e diálogos roteirizados."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from tests.test_qt_caixa import BaseCaixaQt, QApplication

if QApplication is not None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from src.core.erros import ErroNegocio


class TestAdegaQt(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("usar_mesas", "N")
        self.banco.cfg_set("perfil_operacao", "adega")
        self.banco.cfg_set("agrupar_itens_balcao", "S")
        self.abrir_turno()
        self.produto = self.novo_produto("CERVEJA", 800, codigo="10", estoque=True, qt=30)
        self.subgrupo = self.banco.valor("SELECT subgrupo_id FROM produtos WHERE id=?", (self.produto,))
        self.j = self.janela()

    def itens(self):
        return self.ctx.caixa.itens(self.j.venda_id) if self.j.venda_id else []

    def fechar_balcao(self):
        self.j.ent_valor.setText(self.j.lbl_total.text())
        self.j.receber()
        self.j.fechar_venda()

    def bebida_retornavel(self):
        casco = self.novo_produto("CASCO", 200, codigo="11", estoque=True, qt=30)
        self.banco.executar("UPDATE produtos SET preco_gelada_cent=1000, casco_produto_id=? WHERE id=?",
                           (casco, self.produto))
        return casco

    def cadastro(self, codigo="7891234567890", textos=None):
        self.j.dialogos.confirmacoes = [True]
        self.j.dialogos.textos = textos if textos is not None else ["NOVA BEBIDA", "5,50", "", ""]
        self.j.dialogos.escolhas = [self.subgrupo]
        self.lancar(self.j, codigo)

    def test_sem_painel_posicao_e_acoes_de_mesa(self):
        self.assertFalse(self.j.com_mesas)
        for widget in (self.j.painel_mesas, self.j.ent_pos, self.j.btn_chamar, self.j.lista_mesas):
            self.assertFalse(widget.isVisible())
        for chave in ("servico", "transferir_mesa", "transferir_varias", "transferir_item",
                      "repique", "consultar_comanda"):
            self.assertFalse(self.j.acoes[chave].isVisible())
        for chave in ("entrega", "caderneta", "pre_conta"):
            self.assertTrue(self.j.acoes[chave].isVisible())
        with patch.object(type(self.ctx.caixa), "mesas", side_effect=AssertionError("Não consultar mesas")):
            self.j.recarregar()

    def test_posicao_no_codigo_nao_abre_mesa(self):
        with patch.object(type(self.ctx.caixa), "abrir_mesa") as abrir:
            self.lancar(self.j, "M5")
            self.j.ent_pos.setText("C2")
            self.j.chamar_posicao()
            self.j.transferir_mesa()
            self.j.transferir_varias()
            self.j.consultar_comanda()
            self.j.repique()
        abrir.assert_not_called()
        self.assertEqual(self.contar("vendas"), 0)
        self.assertEqual(self.j.dialogos.perguntas, [])

    def test_atalhos_sem_mesas_so_limpam_entrada(self):
        self.j.activateWindow()
        self.aplicacao.processEvents()
        self.lancar(self.j, "10")
        venda = self.j.venda_id
        for tecla in (Qt.Key_F4, Qt.Key_Escape):
            self.j.ent_codigo.setText("6*10")
            self.j.ent_qtd.setText("6")
            self.j.ent_codigo.setFocus()
            QTest.keyClick(self.j.ent_codigo, tecla)
            self.aplicacao.processEvents()
            self.assertEqual(self.j.ent_codigo.text(), "")
            self.assertEqual(self.j.ent_qtd.text(), "1")
        for tecla in (Qt.Key_F9, Qt.Key_F10, Qt.Key_PageUp, Qt.Key_PageDown):
            QTest.keyClick(self.j.ent_codigo, tecla)
        self.assertEqual(self.j.venda_id, venda)
        self.assertEqual(len(self.itens()), 1)
        self.assertEqual(self.j.dialogos.perguntas, [])

    def test_f8_no_balcao_avisa_sem_emitir(self):
        self.lancar(self.j, "10")
        self.j.pre_conta()
        self.assertIn("balcão não há pré-conta", self.j.dialogos.avisos[-1])
        self.assertEqual(self.j.venda()["status"], "aberta")

    def test_com_mesas_preserva_painel_e_posicao(self):
        self.banco.cfg_set("usar_mesas", "S")
        j = self.janela()
        self.assertTrue(j.painel_mesas.isVisible())
        self.lancar(j, "M5")
        self.assertEqual((j.venda()["modalidade"], j.venda()["posicao"]), ("mesa", 5))

    def test_quantidade_antes_do_codigo_e_leitor(self):
        self.banco.executar("UPDATE produtos SET cbarra='7891234567890' WHERE id=?", (self.produto,))
        self.lancar(self.j, "6*7891234567890", "2")
        self.assertEqual(self.itens()[0]["quantidade"], 6)
        self.assertEqual(self.j.venda()["total_cent"], 4800)
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id=?", (self.produto,)), 30)
        self.assertEqual(self.j.ent_codigo.text(), "")
        self.assertEqual(self.j.ent_qtd.text(), "1")
        self.fechar_balcao()
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id=?", (self.produto,)), 24)

    def test_quantidade_fracionada_e_busca_por_nome(self):
        self.banco.executar("UPDATE produtos SET aceita_decimal=1 WHERE id=?", (self.produto,))
        self.lancar(self.j, "1,2345 * cerveja")
        self.assertEqual(self.itens()[0]["quantidade"], 1.2345)

    def test_quantidade_e_escolha_de_produto_preservadas(self):
        outro = self.novo_produto("CERVEJA LATA", 500, codigo="12")
        self.lancar(self.j, "6*cerveja")
        self.assertTrue(self.j.lista_produtos.isVisible())
        linha = next(i for i in range(self.j.lista_produtos.count())
                     if self.j.lista_produtos.item(i).data(Qt.UserRole) == outro)
        self.j.lista_produtos.setCurrentRow(linha)
        self.j.lancar_item()
        self.assertEqual((self.itens()[0]["produto_id"], self.itens()[0]["quantidade"]), (outro, 6))

    def test_asterisco_nao_dispara_comissao_saida_ou_mesa(self):
        with patch.object(self.j, "lancar_comissao") as comissao, \
                patch.object(self.j, "liberar_saida") as saida, \
                patch.object(self.j, "chamar_posicao") as mesa:
            for codigo in ("6*50", "6*1002", "6*M5"):
                self.lancar(self.j, codigo)
            comissao.assert_not_called()
            saida.assert_not_called()
            mesa.assert_not_called()
        self.assertEqual(self.contar("vendas"), 0)

    def test_cadastro_leitor_com_permissao_lanca_e_nao_abre_tk(self):
        self.cadastro()
        p = self.ctx.produtos.buscar_codigo("7891234567890")
        self.assertIsNotNone(p)
        self.assertEqual((p["nome"], p["preco_cent"], p["controla_estoque"]), ("NOVA BEBIDA", 550, 0))
        self.assertEqual(self.itens()[0]["produto_id"], p["id"])
        self.assertEqual(self.j._subgrupo_rapido, self.subgrupo)

    def test_cadastro_com_estoque_e_quantidade_antes_do_codigo(self):
        self.cadastro("6*7891234567890", ["NOVA", "5,50", "", "20"])
        p = self.ctx.produtos.buscar_codigo("7891234567890")
        self.assertEqual((p["controla_estoque"], p["qt_atual"]), (1, 20))
        self.assertEqual(self.itens()[0]["quantidade"], 6)
        self.fechar_balcao()
        self.assertEqual(self.ctx.produtos.por_id(p["id"])["qt_atual"], 14)

    def test_cadastro_com_preco_gelada_pergunta_a_temperatura_na_hora(self):
        self.j.dialogos.confirmacoes = [True]
        self.j.dialogos.textos = ["BRAHMA LATA", "4,50", "5,50", ""]
        self.j.dialogos.escolhas = [self.subgrupo, "gelada"]          # categoria e, já no lançamento, a temperatura
        self.lancar(self.j, "7891234567890")
        p = self.ctx.produtos.buscar_codigo("7891234567890")
        self.assertEqual((p["preco_cent"], p["preco_gelada_cent"]), (450, 550))
        item = self.itens()[0]
        self.assertEqual((item["temperatura"], item["preco_unit_cent"]), ("gelada", 550))

    def test_cadastro_exige_supervisor_sem_permissao_mesmo_senhas_desligadas(self):
        self.operador_bar()
        self.cadastro(textos=["ADM", "NOVA", "5,00", "", ""])
        self.assertIsNotNone(self.ctx.produtos.buscar_codigo("7891234567890"))
        self.assertIn("Cadastrar produto exige autorização", self.j.dialogos.perguntas[1])

    def test_supervisor_negado_cancelado_e_recusa_cadastro_nao_gravam(self):
        self.operador_bar()
        self.j.dialogos.confirmacoes = [False]
        self.lancar(self.j, "7891234567890")
        self.assertEqual(self.j.dialogos.textos, [])
        for respostas in (["ERRADA", "ERRADA", "ERRADA"], [None]):
            self.j.dialogos.confirmacoes = [True]
            self.j.dialogos.textos = list(respostas)
            self.lancar(self.j, "7891234567890")
            self.assertIsNone(self.ctx.produtos.buscar_codigo("7891234567890"))
        self.assertEqual(self.contar("vendas"), 0)

    def test_cancelamento_de_cada_etapa_cadastro_nao_grava(self):
        for textos, escolhas in (([None], []), (["NOVA", None], []), (["NOVA", "5", None], []),
                                 (["NOVA", "5", ""], [None]), (["NOVA", "5", "", None], [self.subgrupo])):
            self.j.dialogos.confirmacoes = [True]
            self.j.dialogos.textos = textos
            self.j.dialogos.escolhas = escolhas
            self.lancar(self.j, "7891234567890")
            self.assertIsNone(self.ctx.produtos.buscar_codigo("7891234567890"))
        self.assertEqual(self.contar("vendas"), 0)

    def test_codigo_curto_e_ean_existente_nao_oferecem_cadastro(self):
        self.lancar(self.j, "1234567")
        self.assertEqual(self.j.dialogos.perguntas, [])
        self.banco.executar("UPDATE produtos SET cbarra='12345678' WHERE id=?", (self.produto,))
        self.lancar(self.j, "12345678")
        self.assertEqual(self.itens()[0]["produto_id"], self.produto)
        self.assertEqual(self.j.dialogos.perguntas, [])

    def test_sem_preco_gelado_nao_pergunta_temperatura(self):
        self.lancar(self.j, "10")
        self.assertEqual(self.itens()[0]["temperatura"], "natural")
        self.assertEqual(self.j.dialogos.perguntas, [])

    def test_gelada_cascos_mesma_transacao_e_troca(self):
        casco = self.bebida_retornavel()
        self.j.dialogos.escolhas = ["gelada"]
        self.j.dialogos.textos = ["2"]
        self.lancar(self.j, "6*10")
        bebida = next(i for i in self.itens() if i["produto_id"] == self.produto)
        vasilhame = next(i for i in self.itens() if i["produto_id"] == casco)
        self.assertEqual((bebida["temperatura"], bebida["preco_base_cent"]), ("gelada", 1000))
        self.assertTrue(bebida["observacao"].startswith("Gelada"))
        self.assertEqual(vasilhame["quantidade"], 2)
        self.assertEqual(self.j.venda()["total_cent"], 6400)
        self.assertIn("cancelar a bebida NÃO cancela o casco e vice-versa", self.j.dialogos.perguntas[-1])

    def cancelar_retornavel(self, cancelar_casco):
        casco = self.bebida_retornavel()
        self.j.dialogos.escolhas = ["natural"]
        self.j.dialogos.textos = ["1"]
        self.lancar(self.j, "10")
        alvo = casco if cancelar_casco else self.produto
        linha = next(n for n, item in enumerate(self.itens()) if item["produto_id"] == alvo)
        self.j.tabela.selectRow(linha)
        self.j.dialogos.confirmacoes = [True]
        self.j.cancelar_item()
        restante = self.produto if cancelar_casco else casco
        self.assertEqual([item["produto_id"] for item in self.itens()], [restante])
        self.assertEqual(self.j.venda()["total_cent"], 800 if cancelar_casco else 200)
        self.assertEqual(self.j.tabela.rowCount(), 1)

    def test_cancelar_bebida_nao_cancela_casco(self):
        self.cancelar_retornavel(cancelar_casco=False)

    def test_cancelar_casco_nao_cancela_bebida(self):
        self.cancelar_retornavel(cancelar_casco=True)

    def test_natural_troca_sem_cobranca_de_casco(self):
        self.bebida_retornavel()
        self.j.dialogos.escolhas = ["natural"]
        self.j.dialogos.textos = ["0"]
        self.lancar(self.j, "10", "3")
        self.assertEqual(len(self.itens()), 1)
        self.assertEqual(self.j.venda()["total_cent"], 2400)

    def test_casco_sem_preco_gelado_tambem_pergunta(self):
        self.bebida_retornavel()
        self.banco.executar("UPDATE produtos SET preco_gelada_cent=0 WHERE id=?", (self.produto,))
        self.j.dialogos.textos = ["1"]
        self.lancar(self.j, "10")
        self.assertEqual(self.j.venda()["total_cent"], 1000)

    def test_cancelar_temperatura_ou_cascos_cancela_lancamento_inteiro(self):
        self.bebida_retornavel()
        for escolhas, textos in (([None], []), (["gelada"], [None])):
            self.j.dialogos.escolhas = escolhas
            self.j.dialogos.textos = textos
            self.lancar(self.j, "10")
            self.assertEqual(self.contar("itens_venda"), 0)
            self.assertEqual(self.contar("vendas"), 0)
            self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id=?", (self.produto,)), 30)

    def test_cancelar_cascos_preserva_venda_existente(self):
        self.lancar(self.j, "10")
        self.bebida_retornavel()
        self.j.dialogos.escolhas = ["gelada"]
        self.j.dialogos.textos = [None]
        self.lancar(self.j, "10")
        self.assertEqual(self.j.venda()["total_cent"], 800)
        self.assertEqual(len(self.itens()), 1)

    def test_cascos_inteiros_entre_zero_e_quantidade(self):
        self.bebida_retornavel()
        self.j.dialogos.escolhas = ["natural"]
        self.j.dialogos.textos = ["-1", "4", "1,5", "1.0", "abc", "1"]
        self.lancar(self.j, "10", "3")
        self.assertEqual(len(self.j.dialogos.avisos), 5)
        self.assertEqual(self.j.venda()["total_cent"], 2600)

    def test_falha_core_reverte_bebida_casco_e_balcao(self):
        self.bebida_retornavel()
        self.j.dialogos.escolhas = ["gelada"]
        self.j.dialogos.textos = ["1"]
        with patch.object(type(self.ctx.caixa), "adicionar_item", side_effect=ErroNegocio("Estoque insuficiente.")):
            self.lancar(self.j, "10")
        self.assertIsNone(self.j.venda_id)
        self.assertEqual(self.contar("vendas"), 0)
        self.assertEqual(self.contar("itens_venda"), 0)

    def test_atacado_e_agrupamento_ficam_no_core(self):
        self.banco.executar("UPDATE produtos SET preco_gelada_cent=1000, atacado_qtd=6, preco_atacado_cent=700, "
                           "atacado_gelada_qtd=6, preco_atacado_gelada_cent=900 WHERE id=?", (self.produto,))
        for temperatura in ("natural", "gelada"):
            for _ in range(6):
                self.j.dialogos.escolhas = [temperatura]
                self.lancar(self.j, "10")
        self.assertEqual(len(self.itens()), 2)
        self.assertEqual([(i["temperatura"], i["quantidade"], i["preco_unit_cent"]) for i in self.itens()],
                         [("natural", 6, 700), ("gelada", 6, 900)])
        self.assertEqual(self.j.venda()["total_cent"], 9600)
        self.assertIn("Natural · Atacado", self.j.tabela.item(0, 1).text())
        self.assertIn("Gelada · Atacado", self.j.tabela.item(1, 1).text())

    def test_delivery_e_caderneta_preservados_sem_mesas(self):
        cliente = self.ctx.cadastros.salvar("clientes", {"numero_consulta": "123", "nome": "CLIENTE",
                                                       "telefone": "1199999", "limite_cent": "100,00"})
        self.banco.cfg_set("usar_caderneta", "S")
        self.banco.cfg_set("usar_delivery", "S")
        self.j.dialogos.escolhas = ["novo", cliente]
        self.j.dialogos.textos = ["123"]
        self.j.dialogos.confirmacoes = [True]
        self.j.entrega()
        self.assertEqual(self.j.venda()["modalidade"], "entrega")
        self.lancar(self.j, "10")
        with patch.object(self.j, "emitir_pedido_entrega") as emitir:
            self.j.pre_conta()
        emitir.assert_called_once()
        self.ctx.caixa.cancelar_venda(self.j.venda_id, "teste")
        self.j.venda_id = None
        self.j.dialogos.escolhas = ["venda", cliente]
        self.j.dialogos.textos = ["123"]
        self.j.dialogos.confirmacoes = [True]
        self.j.caderneta()
        self.assertEqual(self.j.venda()["modalidade"], "caderneta")
        self.lancar(self.j, "10")
        self.j.dialogos.confirmacoes = [True]
        self.j.fechar_venda()
        self.assertEqual(self.ctx.caderneta.obter(cliente)["saldo_cent"], -800)
