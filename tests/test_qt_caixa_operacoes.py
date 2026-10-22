"""Operações complementares Qt com banco real em memória e periféricos controlados."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from src.hardware.dispositivos import DispositivoIndisponivel
from src.hardware.impressora_termica import ErroImpressao
from tests.test_qt_caixa import BaseCaixaQt


class TestOperacoesQt(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.turno_id = self.abrir_turno()
        self.produto = self.novo_produto("PRODUTO", 1000, codigo="10", aceita_decimal="S", usa_observacao="S")
        self.cliente = self.ctx.cadastros.salvar("clientes", {
            "numero_consulta": "123", "nome": "CLIENTE", "telefone": "1199999", "limite_cent": "100,00"})
        for chave in ("usar_caderneta", "usar_delivery", "usar_desconto"):
            self.banco.cfg_set(chave, "1")
        self.j = self.janela()

    def acao(self, chave, textos=(), escolhas=(), confirmacoes=()):
        self.j.dialogos.textos = list(textos)
        self.j.dialogos.escolhas = list(escolhas)
        self.j.dialogos.confirmacoes = list(confirmacoes)
        self.j.acoes[chave].trigger()

    def mesa(self, pos="M1", qtd="1"):
        self.j.ent_pos.setText(pos)
        self.j.btn_chamar.click()
        self.lancar(self.j, "10", qtd)
        self.j.tabela.selectRow(0)
        return self.j.venda_id

    def caderneta(self):
        self.acao("caderneta", textos=["123"], escolhas=["venda", self.cliente], confirmacoes=[True])
        return self.j.venda_id

    def entrega(self):
        self.acao("entrega", textos=["123"], escolhas=["novo", self.cliente], confirmacoes=[True])
        return self.j.venda_id

    def test_partes_montagem_e_composto_gravam_componentes(self):
        a = self.novo_produto("PARTE A", 1200, montagem="S", compoe="S")
        b = self.novo_produto("PARTE B", 1600, montagem="S", compoe="S")
        for composto in (False, True):
            with self.subTest(composto=composto):
                self.banco.executar("UPDATE produtos SET partes=3, composto=? WHERE id=?", (int(composto), self.produto))
                self.j.dialogos.textos = ["2"]
                self.j.dialogos.escolhas = [a, b]
                self.lancar(self.j, "10", "1,2345")
                it = self.ctx.caixa.itens(self.j.venda_id)[-1]
                self.assertEqual(it["partes"], 2)
                self.assertEqual(it["quantidade"], 1.2345)
                self.assertEqual(it["partes_nomes"], ["PARTE A", "PARTE B"])
                self.assertIsInstance(it["total_cent"], int)
                self.assertIn("PARTE A", self.j.tabela.item(self.j.tabela.rowCount() - 1, 1).text())

    def test_partes_sem_divisao_cancelamento_e_falha_atomica(self):
        self.banco.executar("UPDATE produtos SET partes=2, composto=1 WHERE id=?", (self.produto,))
        self.j.dialogos.textos = ["2"]
        self.lancar(self.j, "10")
        self.assertIn("Não há produtos", self.j.dialogos.avisos[-1])
        self.assertEqual(self.contar("vendas"), 0)
        a = self.novo_produto("PARTE", 1200, compoe="S")
        self.j.dialogos.textos = ["2"]
        self.j.dialogos.escolhas = [a, None]
        self.lancar(self.j, "10")
        self.assertEqual(self.contar("itens_venda"), 0)
        self.j.dialogos.textos = ["2"]
        self.j.dialogos.escolhas = [a, a]
        self.lancar(self.j, "10", "0")
        self.assertEqual(self.contar("vendas"), 0)
        self.assertTrue(self.j.dialogos.erros)
        self.j.dialogos.textos = ["1"]
        self.lancar(self.j, "10")
        self.assertEqual(self.ctx.caixa.itens(self.j.venda_id)[0]["partes_nomes"], [])

    def test_desconto_valor_percentual_zero_e_limites_do_controlador(self):
        self.mesa()
        self.acao("desconto", textos=["1,23"], escolhas=["valor"])
        self.assertEqual(self.j.venda()["desconto_cent"], 123)
        self.acao("desconto", textos=["10"], escolhas=["pct"])
        self.assertEqual(self.j.venda()["desconto_cent"], 100)
        self.acao("desconto", textos=["11,00"], escolhas=["valor"])
        self.assertEqual(self.j.venda()["desconto_cent"], 100)
        self.assertIn("maior", self.j.dialogos.erros[-1])
        self.acao("desconto", textos=["0"], escolhas=["valor"])
        self.assertEqual(self.j.venda()["desconto_cent"], 0)
        self.acao("desconto", textos=["nan", None], escolhas=["pct"])
        self.assertEqual(self.j.venda()["desconto_cent"], 0)
        self.assertIn("percentual", self.j.dialogos.avisos[-1])

    def test_desconto_desligado_e_senha_cancelada_nao_alteram_venda(self):
        self.mesa()
        self.banco.cfg_set("usar_desconto", "0")
        self.acao("desconto")
        self.assertEqual(self.j.venda()["desconto_cent"], 0)
        self.banco.cfg_set("usar_desconto", "1")
        self.operador_bar()
        self.banco.cfg_set("exigir_senha_desconto", "1")
        self.acao("desconto", textos=[None])
        self.assertEqual(self.j.venda()["desconto_cent"], 0)

    def test_servico_manual_zero_automatico_e_cancelamento(self):
        self.mesa()
        self.acao("servico", textos=["2,34"])
        self.assertEqual((self.j.venda()["servico_manual"], self.j.venda()["servico_cent"]), (1, 234))
        self.acao("servico", textos=[None])
        self.assertEqual(self.j.venda()["servico_cent"], 234)
        self.acao("servico", textos=["0"])
        self.assertEqual(self.j.venda()["servico_cent"], 0)
        self.acao("servico", textos=[""])
        self.assertEqual((self.j.venda()["servico_manual"], self.j.venda()["servico_cent"]), (0, 100))
        self.acao("servico", textos=["-1"])
        self.assertEqual(self.j.venda()["servico_cent"], 100)

    def test_observacao_livre_cadastrada_e_produto_sem_permissao(self):
        self.mesa()
        with patch.object(self.j, "_enviar_remoto") as remoto:
            self.acao("observacao", textos=["Sem gelo"])
            remoto.assert_called_once()
        self.assertEqual(self.ctx.caixa.itens(self.j.venda_id)[0]["observacao"], "Sem gelo")
        self.assertIn("Sem gelo", self.j.tabela.item(0, 1).text())
        self.j.tabela.selectRow(0)
        self.ctx.cadastros.salvar("observacoes", {"codigo": "1", "texto": "Bem passado"})
        self.acao("observacao", escolhas=["Bem passado"])
        self.assertEqual(self.ctx.caixa.itens(self.j.venda_id)[0]["observacao"], "Bem passado")
        self.banco.executar("UPDATE produtos SET usa_observacao=0 WHERE id=?", (self.produto,))
        self.j.tabela.selectRow(0)
        self.acao("observacao")
        self.assertIn("não permite", self.j.dialogos.avisos[-1])

    def test_transferencia_total_para_comanda_ocupada(self):
        origem = self.mesa("M1", "2")
        destino, _ = self.ctx.caixa.abrir_mesa(2, comanda=True)
        self.ctx.caixa.adicionar_item(destino, self.produto, 1)
        self.acao("transferir_mesa", textos=["C2"])
        self.assertEqual(self.j.venda_id, destino)
        self.assertEqual(sum(it["quantidade"] for it in self.ctx.caixa.itens(destino)), 3)
        self.assertEqual(self.ctx.caixa.itens(origem), [])
        self.assertEqual(self.j.venda()["total_cent"], 3300)

    def test_transferir_item_fracionado_preserva_partes_e_observacao(self):
        a = self.novo_produto("COMPONENTE", 1000, compoe="S")
        self.banco.executar("UPDATE produtos SET partes=2, composto=1 WHERE id=?", (self.produto,))
        self.j.dialogos.textos = ["2"]
        self.j.dialogos.escolhas = [a, a]
        self.mesa(qtd="2")
        it = self.ctx.caixa.itens(self.j.venda_id)[0]
        self.ctx.caixa.definir_observacao(it["id"], "Gelado")
        self.acao("transferir_item", textos=["C4", "0,1234"])
        origem = self.ctx.caixa.itens(self.j.venda_id)[0]
        destino = next(m for m in self.ctx.caixa.mesas() if m["posicao"] == 4)
        transferido = self.ctx.caixa.itens(destino["id"])[0]
        self.assertEqual(transferido["quantidade"], 0.1234)
        self.assertEqual(transferido["observacao"], "Gelado")
        self.assertEqual(transferido["partes_nomes"], ["COMPONENTE", "COMPONENTE"])
        self.assertEqual(origem["total_cent"] + transferido["total_cent"], 2000)

    def test_transferencia_varias_e_origem_inexistente_atomica(self):
        self.mesa("M1")
        outro, _ = self.ctx.caixa.abrir_mesa(2)
        self.ctx.caixa.adicionar_item(outro, self.produto, 2)
        self.acao("transferir_varias", textos=["C5", "M1,M99"])
        self.assertEqual(len(self.ctx.caixa.mesas()), 2)
        self.assertTrue(self.j.dialogos.erros)
        self.acao("transferir_varias", textos=["C5", "M1,M2"])
        destino = self.ctx.caixa.mesas()[0]
        self.assertEqual((destino["comanda"], destino["posicao"], destino["total_cent"]), (1, 5, 3300))
        self.assertIsNone(self.j.venda_id)

    def test_transferir_recusa_mesma_posicao_quantidade_excessiva_e_cancelamento(self):
        vid = self.mesa()
        self.acao("transferir_mesa", textos=["M1"])
        self.assertEqual(self.j.venda_id, vid)
        self.assertIn("mesma", self.j.dialogos.erros[-1])
        self.acao("transferir_item", textos=["C2", "2"])
        self.assertEqual(len(self.ctx.caixa.mesas()), 1)
        self.acao("transferir_mesa", textos=[None])
        self.assertEqual(self.j.venda_id, vid)

    def test_pre_conta_enviada_sem_encerrar_e_impressao_falha(self):
        vid = self.mesa()
        with patch.object(type(self.ctx.impressao), "deve_mostrar_na_tela", return_value=False), \
                patch.object(type(self.ctx.impressao), "enviar", side_effect=ErroImpressao("offline")):
            self.acao("pre_conta")
        self.assertEqual(self.ctx.caixa.obter(vid)["status"], "conta_enviada")
        self.assertIsNone(self.j.venda_id)
        self.assertTrue(self.j.documentos)
        self.assertIn("offline", self.j.dialogos.erros[-1])
        self.assertIsNone(self.ctx.caixa.obter(vid)["cupom"])

    def test_caderneta_debito_limite_confirmacao_e_recusa_de_pagamento(self):
        vid = self.caderneta()
        self.lancar(self.j, "10")
        self.assertFalse(self.j.btn_receber.isEnabled())
        self.j.ent_valor.setText("1,00")
        self.j.receber()
        self.assertEqual(self.contar("pagamentos_venda"), 0)
        self.j.dialogos.confirmacoes = [False]
        self.j.btn_fechar_venda.click()
        self.assertEqual(self.j.venda_id, vid)
        self.j.dialogos.confirmacoes = [True]
        self.j.btn_fechar_venda.click()
        self.assertEqual(self.ctx.caderneta.obter(self.cliente)["saldo_cent"], -1000)
        self.assertEqual(self.ctx.caixa.obter(vid)["status"], "fechada")
        self.caderneta()
        self.lancar(self.j, "10", "10")
        self.j.dialogos.confirmacoes = [True]
        self.j.btn_fechar_venda.click()
        self.assertIn("Limite", self.j.dialogos.erros[-1])
        self.assertEqual(self.ctx.caderneta.obter(self.cliente)["saldo_cent"], -1000)

    def test_caderneta_recebimento_de_divida_excesso_credito_ou_troco(self):
        for credito in (True, False):
            with self.subTest(credito=credito):
                self.banco.executar("UPDATE clientes SET saldo_cent=-1000 WHERE id=?", (self.cliente,))
                vid = self.caderneta()
                self.assertEqual(self.j.ent_valor.text(), "10,00")
                self.j.ent_valor.setText("12,34")
                self.j.btn_receber.click()
                self.assertEqual(self.j.lbl_total.text(), "12,34")
                self.assertEqual(self.j.lbl_troco.text(), "2,34")
                self.assertIn("decidir", self.j.lbl_falta_rotulo.text())
                self.assertTrue(self.j.btn_fechar_venda.isEnabled())
                self.j.dialogos.confirmacoes = [credito]
                self.j.btn_fechar_venda.click()
                venda = self.ctx.caixa.obter(vid)
                self.assertEqual(venda["troco_cent"], 0 if credito else 234)
                self.assertEqual(self.ctx.caderneta.obter(self.cliente)["saldo_cent"], 234 if credito else 0)

    def test_caderneta_recebimento_sem_pagamento_e_modalidade_bloqueada(self):
        vid = self.caderneta()
        self.j.btn_fechar_venda.click()
        self.assertIn("valor recebido", self.j.dialogos.erros[-1])
        self.j.ent_valor.setText("5,00")
        self.j.btn_receber.click()
        self.j.ent_pos.setText("M2")
        self.j.btn_chamar.click()
        self.assertEqual(self.j.venda_id, vid)
        self.acao("entrega", escolhas=["novo"])
        self.assertEqual(self.j.venda_id, vid)
        self.assertIn("modalidade", self.j.dialogos.avisos[-1])
        self.j.btn_trocar_turno.click()
        self.assertEqual(self.j.venda_id, vid)
        self.assertIsNotNone(self.ctx.turnos.atual())

    def test_consulta_cliente_ultimas_compras_extrato_lancamento(self):
        vid = self.caderneta()
        self.lancar(self.j, "10")
        self.j.dialogos.confirmacoes = [True]
        self.j.btn_fechar_venda.click()
        self.j.dialogos.escolhas = ["compras"]
        self.j.consultar_cliente(self.cliente)
        self.assertIn("PRODUTO", self.j.documentos[-1].texto.toPlainText())
        self.j.dialogos.escolhas = ["extrato"]
        with patch.object(type(self.ctx.impressao), "deve_mostrar_na_tela", return_value=True):
            self.j.consultar_cliente(self.cliente)
        self.assertIn("CLIENTE", self.j.documentos[-1].texto.toPlainText())
        lanc = self.ctx.caderneta.lancamentos(self.cliente)[0]
        self.j.dialogos.escolhas = ["lancamentos", lanc["id"]]
        self.j.consultar_cliente(self.cliente)
        self.assertIn("PRODUTO", self.j.documentos[-1].texto.toPlainText())
        self.assertEqual(self.ctx.caixa.obter(vid)["status"], "fechada")

    def test_entrega_taxa_troco_mensagem_emissao_atribuicao_e_recebimento(self):
        bairro = self.ctx.cadastros.salvar("bairros", {"nome": "CENTRO", "taxa_cent": "3,50"})
        self.banco.executar("UPDATE clientes SET bairro_id=? WHERE id=?", (bairro, self.cliente))
        entregador = self.ctx.cadastros.salvar("operadores", {"nome": "MOTO", "senha": "1234", "entregador": "S"})
        vid = self.entrega()
        self.lancar(self.j, "10", "2")
        self.assertEqual(self.j.venda()["total_cent"], 2350)
        self.acao("troco_entrega", textos=["30,00", "Portão azul"], escolhas=[entregador])
        self.assertEqual(self.ctx.entregas.troco_a_levar(vid), 650)
        self.assertEqual(self.j.venda()["mensagem"], "Portão azul")
        with patch.object(type(self.ctx.impressao), "deve_mostrar_na_tela", return_value=True):
            self.acao("pre_conta")
        self.assertEqual(self.ctx.caixa.obter(vid)["status"], "conta_enviada")
        self.assertIn("Portão azul", self.j.documentos[-1].texto.toPlainText())
        self.acao("entrega", escolhas=["lista", vid, "entregador", entregador])
        self.assertIsNotNone(self.ctx.caixa.obter(vid)["saida_entrega_em"])
        self.acao("entrega", escolhas=["lista", vid, "receber"])
        self.assertEqual(self.j.venda_id, vid)
        self.j.btn_receber.click()
        self.j.btn_fechar_venda.click()
        self.assertEqual(self.ctx.caixa.obter(vid)["status"], "fechada")
        self.assertEqual(self.ctx.entregas.pendentes(), [])

    def test_lista_entregas_nao_descarta_venda_ao_atribuir_entregador(self):
        entregador = self.ctx.cadastros.salvar(
            "operadores", {"nome": "MOTO", "senha": "1234", "entregador": "S"})
        pedido = self.ctx.entregas.abrir(self.cliente)
        self.ctx.caixa.adicionar_item(pedido, self.produto, 1)
        self.ctx.entregas.emitir_pedido(pedido)
        atual = self.mesa("M2")

        self.acao("entrega", escolhas=["lista", pedido, "entregador", entregador])

        self.assertEqual(self.j.venda_id, atual)
        self.assertEqual(self.ctx.caixa.obter(atual)["status"], "aberta")
        self.assertEqual(self.ctx.caixa.itens(atual)[0]["quantidade"], 1)
        self.assertEqual(self.ctx.caixa.obter(pedido)["entregador_id"], entregador)

    def test_retomar_entrega_nao_substitui_venda_atual_com_itens(self):
        pedido = self.ctx.entregas.abrir(self.cliente)
        self.ctx.caixa.adicionar_item(pedido, self.produto, 1)
        self.ctx.entregas.emitir_pedido(pedido)
        atual = self.mesa("M2")

        self.acao("entrega", escolhas=["lista", pedido, "receber"])

        self.assertEqual(self.j.venda_id, atual)
        self.assertEqual(self.ctx.caixa.obter(atual)["status"], "aberta")
        self.assertEqual(self.ctx.caixa.obter(pedido)["status"], "conta_enviada")
        self.assertIn("Conclua, pague ou cancele", self.j.dialogos.avisos[-1])

    def test_entrega_sem_itens_troco_insuficiente_cancelamento_e_modulo_desligado(self):
        vid = self.entrega()
        self.acao("pre_conta")
        self.assertIn("não tem itens", self.j.dialogos.erros[-1])
        self.lancar(self.j, "10")
        self.acao("troco_entrega", textos=["1,00", ""], escolhas=["manter"])
        self.acao("pre_conta")
        self.assertIn("menor", self.j.dialogos.erros[-1])
        self.assertEqual(self.j.venda_id, vid)
        self.j.venda_id = None
        self.acao("entrega", escolhas=["lista", vid, "cancelar"], confirmacoes=[True])
        self.assertEqual(self.ctx.caixa.obter(vid)["status"], "cancelada")
        self.banco.cfg_set("usar_delivery", "0")
        self.acao("entrega")
        self.assertEqual(self.contar("vendas"), 1)

    def test_sangria_suprimento_comprovante_e_falha_na_impressao(self):
        for tipo in ("saida", "entrada"):
            with self.subTest(tipo=tipo), \
                    patch.object(type(self.ctx.impressao), "deve_mostrar_na_tela", return_value=False), \
                    patch.object(type(self.ctx.impressao), "enviar", side_effect=ErroImpressao("offline")) as enviar:
                self.acao("sangria", textos=["12,34", "Conferência"], escolhas=[tipo])
                enviar.assert_called_once()
                self.assertTrue(enviar.call_args.kwargs["abrir_gaveta"])
                mov = self.ctx.turnos.movimentos(self.turno_id)[-1]
                self.assertEqual((mov["tipo"], mov["valor_cent"], mov["descricao"]), (tipo, 1234, "Conferência"))
                self.assertTrue(self.j.documentos)
        self.assertEqual(self.contar("movimentos_caixa"), 2)

    def test_sangria_e_gaveta_exigem_autorizacao_e_cancelamento_nao_grava(self):
        self.operador_bar()
        for chave, cfg in (("sangria", "exigir_senha_sangria"), ("gaveta", "exigir_senha_gaveta")):
            self.banco.cfg_set(cfg, "1")
            with patch.object(self.ctx, "gaveta") as gaveta:
                self.acao(chave, textos=[None])
                gaveta.assert_not_called()
        self.assertEqual(self.contar("movimentos_caixa"), 0)

    def test_senhas_invalidas_recusam_e_supervisor_autoriza_novos_fluxos(self):
        self.mesa()
        self.operador_bar()
        for chave in ("exigir_senha_sangria", "exigir_senha_gaveta", "exigir_senha_desconto"):
            self.banco.cfg_set(chave, "1")
        self.acao("desconto", textos=["x", "y", "z"])
        self.assertEqual(self.j.venda()["desconto_cent"], 0)
        self.acao("desconto", textos=["ADM", "1,23"], escolhas=["valor"])
        self.assertEqual(self.j.venda()["desconto_cent"], 123)
        with patch.object(type(self.ctx.impressao), "deve_mostrar_na_tela", return_value=True):
            self.acao("sangria", textos=["ADM", "abc", "2,34", "Conferência"], escolhas=["saida"])
        self.assertEqual(self.ctx.turnos.movimentos(self.turno_id)[0]["valor_cent"], 234)
        hardware = SimpleNamespace(abrir=Mock())
        with patch.object(self.ctx, "gaveta", return_value=hardware):
            self.acao("gaveta", textos=["ADM"])
        hardware.abrir.assert_called_once()

    def test_inclusao_cliente_reutiliza_formulario_qt_e_controlador(self):
        from src.ui_qt.cadastros import FormularioCadastro

        def preencher(dlg):
            dlg.campos["numero_consulta"].setText("456")
            dlg.campos["nome"].setText("CLIENTE NOVO")
            dlg.salvar()
            return dlg.result()

        with patch.object(FormularioCadastro, "exec", preencher):
            self.acao("caderneta", textos=[""], escolhas=["venda", "novo"])
        novo = self.ctx.caderneta.buscar("456")[0]
        self.assertEqual(self.j.venda()["cliente_id"], novo["id"])
        self.assertEqual(novo["nome"], "CLIENTE NOVO")

    def test_cliente_inativo_e_inclusao_sem_permissao_nao_abrem_venda(self):
        self.banco.executar("UPDATE clientes SET ativo=0 WHERE id=?", (self.cliente,))
        self.acao("caderneta", textos=["123"], escolhas=["venda", self.cliente], confirmacoes=[True])
        self.assertIsNone(self.j.venda_id)
        self.assertIn("inativo", self.j.dialogos.erros[-1])
        self.operador_bar()
        self.acao("caderneta", textos=[""], escolhas=["venda", "novo"])
        self.assertIsNone(self.j.venda_id)
        self.assertIn("acesso", self.j.dialogos.erros[-1])

    def test_repique_posicao_atual_e_pergunta_sem_mudar_venda(self):
        vid = self.mesa("C7")
        self.acao("repique", textos=["2,34"])
        mov = self.banco.um("SELECT * FROM repiques")
        self.assertEqual(mov["valor_cent"], 234)
        self.assertEqual((mov["posicao"], mov["venda_id"]), (7, vid))
        self.assertEqual(self.j.venda_id, vid)
        self.j.venda_id = None
        self.acao("repique", textos=["M2", "1,00"])
        self.assertEqual(self.contar("repiques"), 2)

    def test_gaveta_indisponivel_nao_anuncia_sucesso_e_registra_tentativa(self):
        hardware = SimpleNamespace(abrir=Mock(side_effect=DispositivoIndisponivel("offline")))
        with patch.object(self.ctx, "gaveta", return_value=hardware):
            self.acao("gaveta")
        self.assertIn("não confirmou", self.j.dialogos.avisos[-1])
        self.assertNotIn("Comando de abertura enviado", self.j.lbl_status.text())
        hardware.abrir.side_effect = None
        with patch.object(self.ctx, "gaveta", return_value=hardware):
            self.acao("gaveta")
        self.assertIn("Comando de abertura enviado", self.j.lbl_status.text())

    def test_balanca_peso_real_e_manual_sem_lancar_automaticamente(self):
        self.j.ent_codigo.setText("10")
        hardware = SimpleNamespace(ler_peso=Mock(return_value=1.2345))
        with patch.object(self.ctx, "balanca", return_value=hardware):
            self.acao("balanca")
        self.assertEqual(self.j.ent_qtd.text(), "1,2345")
        self.assertEqual(self.contar("itens_venda"), 0)
        hardware.ler_peso.side_effect = DispositivoIndisponivel("sem porta")
        with patch.object(self.ctx, "balanca", return_value=hardware):
            self.acao("balanca", textos=["abc", "0,4321"])
        self.j.btn_lancar.click()
        self.assertEqual(self.ctx.caixa.itens(self.j.venda_id)[0]["quantidade"], 0.4321)

    def test_balanca_cancelada_preserva_quantidade_e_controlador_recusa_fracao(self):
        self.j.ent_codigo.setText("10")
        self.j.ent_qtd.setText("2")
        hardware = SimpleNamespace(ler_peso=Mock(side_effect=DispositivoIndisponivel("offline")))
        with patch.object(self.ctx, "balanca", return_value=hardware):
            self.acao("balanca", textos=[None])
        self.assertEqual(self.j.ent_qtd.text(), "2")
        self.banco.executar("UPDATE produtos SET aceita_decimal=0 WHERE id=?", (self.produto,))
        self.lancar(self.j, "10", "0,5")
        self.assertEqual(self.contar("itens_venda"), 0)
        self.assertIn("fracionada", self.j.dialogos.erros[-1])

    def test_reimpressao_ultimo_por_numero_sem_alterar_venda(self):
        self.lancar(self.j, "10")
        self.j.btn_receber.click()
        vid = self.j.venda_id
        self.j.btn_fechar_venda.click()
        cupom = self.ctx.caixa.obter(vid)["cupom"]
        for modo, textos in (("ultimo", []), ("numero", [str(cupom)])):
            with self.subTest(modo=modo), patch.object(type(self.ctx.impressao), "deve_mostrar_na_tela", return_value=True):
                self.acao("reimpressao", textos=textos, escolhas=[modo])
                self.assertIn("2", self.j.documentos[-1].windowTitle())
                self.assertIn("PRODUTO", self.j.documentos[-1].texto.toPlainText())
        self.assertEqual(self.contar("vendas"), 1)
        self.assertEqual(self.contar("pagamentos_venda"), 1)
        self.acao("reimpressao", textos=["99999"], escolhas=["numero"])
        self.assertIn("não encontrado", self.j.dialogos.avisos[-1])

    def test_reimprimir_cancelada_e_falha_nao_abre_gaveta_nem_duplica_pagamento(self):
        self.lancar(self.j, "10")
        vid = self.j.venda_id
        self.j.dialogos.confirmacoes = [True]
        self.j.btn_cancelar_venda.click()
        with patch.object(type(self.ctx.impressao), "deve_mostrar_na_tela", return_value=False), \
                patch.object(type(self.ctx.impressao), "enviar", side_effect=ErroImpressao("offline")) as enviar:
            self.acao("reimpressao", escolhas=["ultimo"])
        self.assertFalse(enviar.call_args.kwargs["abrir_gaveta"])
        self.assertEqual(enviar.call_args.kwargs["venda_id"], vid)
        self.assertEqual(self.ctx.caixa.obter(vid)["status"], "cancelada")
        self.assertEqual(self.contar("pagamentos_venda"), 0)
        self.assertEqual(self.contar("vendas"), 1)
        self.assertTrue(self.j.documentos)

    def test_cancelamentos_dos_dialogos_financeiros_nao_gravam(self):
        self.acao("sangria", escolhas=["saida"], textos=[None])
        self.acao("sangria", escolhas=["entrada"], textos=["5,00", None])
        self.acao("repique", textos=[None])
        self.acao("reimpressao", escolhas=["ultimo"])
        self.assertIn("não encontrado", self.j.dialogos.avisos[-1])
        self.assertEqual(self.contar("movimentos_caixa"), 0)
        self.assertEqual(self.contar("repiques"), 0)
        self.banco.cfg_set("usar_caderneta", "0")
        self.acao("caderneta")
        self.assertEqual(self.contar("vendas"), 0)

    def test_consulta_comanda_estados_e_comissao_pendente_nao_troca_venda(self):
        atual = self.mesa("M1")
        for pos, esperado in (("C2", "nenhum registro"), ("M1", "ABERTA")):
            self.acao("consultar_comanda", textos=[pos])
            self.assertIn(esperado, self.j.documentos[-1].texto.toPlainText())
            self.assertEqual(self.j.venda_id, atual)
        outra, _ = self.ctx.caixa.abrir_mesa(2, comanda=True)
        self.ctx.comissoes.lancar(2, 500, self.turno_id, self.ctx.operador_id)
        self.acao("consultar_comanda", textos=["C2"])
        texto = self.j.documentos[-1].texto.toPlainText()
        self.assertIn("sem nenhum consumo", texto)
        self.assertIn("Comissão da garota 2 a pagar: R$ 5,00", texto)
        self.ctx.caixa.adicionar_item(outra, self.produto, 1)
        self.ctx.caixa.adicionar_pagamento(outra, self.tipo(), 1100)
        self.ctx.caixa.fechar(outra)
        self.acao("consultar_comanda", textos=["C2"])
        self.assertIn("PAGA", self.j.documentos[-1].texto.toPlainText())
        self.ctx.caixa.cancelar_venda(outra, "teste")
        self.acao("consultar_comanda", textos=["C2"])
        self.assertIn("CANCELADA", self.j.documentos[-1].texto.toPlainText())
        self.assertEqual(self.j.venda_id, atual)

    def test_modo_cancelar_itens_e_comissao_autorizacao_unica_esc_e_troca(self):
        self.mesa("C2")
        self.lancar(self.j, "10")
        self.ctx.comissoes.lancar(2, 500, self.turno_id, self.ctx.operador_id)
        self.j.recarregar()
        with patch.object(self.j, "_autorizar", return_value=True) as autorizar:
            self.acao("modo_cancelar")
            for linha in (0, 0):
                self.j.tabela.selectRow(linha)
                self.j.dialogos.confirmacoes = [True]
                QTest.keyClick(self.j.tabela, Qt.Key_Return)
            self.j.tabela.selectRow(0)
            self.j.dialogos.confirmacoes = [True]
            QTest.keyClick(self.j.tabela, Qt.Key_Return)
            self.assertEqual(autorizar.call_count, 1)
        self.assertEqual(self.ctx.caixa.itens(self.j.venda_id), [])
        self.assertEqual(self.ctx.comissoes.pendente(2), 0)
        self.j.cancelar_modo_comissao()
        self.assertFalse(self.j._em_cancelamento())
        self.acao("modo_cancelar")
        self.j.ent_pos.setText("C3")
        self.j.btn_chamar.click()
        self.assertFalse(self.j._em_cancelamento())

    def test_devolucoes_nao_abrem_sem_turno_ou_durante_gravacao(self):
        with patch("src.ui_qt.devolucoes.JanelaDevolucoes") as janela:
            self.j._ocupado = True
            self.j.abrir_devolucoes()
            self.j._ocupado = False
            self.j._fechando_venda = True
            self.j.abrir_devolucoes()
            self.j._fechando_venda = False
            self.ctx.turnos.fechar(self.turno_id, self.ctx.operador_id, 10000)
            self.j.abrir_devolucoes()
            janela.assert_not_called()

    def test_operacoes_nao_executam_sem_turno_ou_durante_gravacao(self):
        self.j._ocupado = True
        for chave in self.j.acoes:
            self.acao(chave)
        self.assertEqual(self.contar("vendas"), 0)
        self.assertEqual(self.contar("movimentos_caixa"), 0)
        self.j._ocupado = False
        self.ctx.turnos.fechar(self.turno_id, self.ctx.operador_id, 10000)
        for chave in self.j.acoes:
            self.acao(chave)
        self.assertEqual(self.contar("vendas"), 0)
        self.assertEqual(self.contar("movimentos_caixa"), 0)
