"""Caixa: turno, venda, mesas, desconto, serviço, pagamento, troco, vale, caderneta e cancelamentos."""
from __future__ import annotations

from src.controllers.cadastro_controller import CadastroController
from src.controllers.caixa_controller import CaixaController
from src.controllers.estoque_controller import EstoqueController
from src.controllers.produto_controller import ProdutoController
from src.controllers.turno_controller import TurnoController
from src.core.erros import ErroNegocio
from tests.base import BaseTeste


class BaseCaixa(BaseTeste):
    def setUp(self):
        super().setUp()
        self.adm = self.operador_adm()
        self.caixa = CaixaController(self.banco, self.adm)
        self.turnos = TurnoController(self.banco)
        self.prod = ProdutoController(self.banco)
        self.skol = self.novo_produto("SKOL", 800, estoque=True, qt=100)
        self.agua = self.novo_produto("AGUA", 350)
        self.turno = self.turnos.abrir(self.adm, 1, 10000)   # fundo de R$ 100,00

    def vender(self, *itens, mesa=None):
        if mesa:
            vid, _ = self.caixa.abrir_mesa(mesa)
        else:
            vid = self.caixa.abrir_balcao()
        for pid, qtd in itens:
            self.caixa.adicionar_item(vid, pid, qtd)
        return vid

    def pagar(self, vid, forma, valor):
        self.caixa.adicionar_pagamento(vid, self.tipo(forma), valor)

    def cliente(self, nome="JOAO", limite=0):
        return CadastroController(self.banco).salvar(
            "clientes", {"numero_consulta": nome[:3], "nome": nome, "limite_cent": f"{limite / 100:.2f}"})


class TesteTurno(BaseCaixa):
    def test_nao_vende_sem_turno_aberto(self):
        self.turnos.fechar(self.turno, self.adm, 10000)
        with self.assertRaises(ErroNegocio):
            self.caixa.abrir_balcao()

    def test_apenas_um_turno_aberto_por_caixa(self):
        with self.assertRaises(ErroNegocio):
            self.turnos.abrir(self.adm, 2, 0)

    def test_numero_do_turno_volta_ao_primeiro_depois_do_ultimo(self):
        self.banco.cfg_set("num_turnos", 2)
        self.assertEqual(self.turnos.atual()["numero"], 1)
        self.turnos.fechar(self.turno, self.adm, 10000)
        self.assertEqual(self.turnos.numero_sugerido(), 2)
        t2 = self.turnos.abrir(self.adm, 2, 0)
        self.turnos.fechar(t2, self.adm, 0)
        self.assertEqual(self.turnos.numero_sugerido(), 1)

    def test_fechamento_com_sobra_falta_e_exato(self):
        vid = self.vender((self.skol, 2))
        self.pagar(vid, "Dinheiro", 1600)
        self.caixa.fechar(vid)
        # esperado = 100,00 (fundo) + 16,00 (venda)
        self.assertEqual(self.turnos.resumo(self.turno)["esperado"], 11600)
        res = self.turnos.fechar(self.turno, self.adm, 11000)     # entregou R$ 6,00 a menos
        self.assertEqual(res["resultado"], -600)
        t = self.turnos.obter(self.turno)
        self.assertEqual((t["status"], t["resultado_cent"], t["esperado_cent"]), ("fechado", -600, 11600))

    def test_sangria_e_suprimento_entram_no_esperado(self):
        self.turnos.movimentar(self.turno, self.adm, "saida", 3000, "pagamento fornecedor")
        self.turnos.movimentar(self.turno, self.adm, "entrada", 500, "troco extra")
        self.assertEqual(self.turnos.resumo(self.turno)["esperado"], 10000 - 3000 + 500)
        with self.assertRaises(ErroNegocio):
            self.turnos.movimentar(self.turno, self.adm, "saida", 0)

    def test_nao_fecha_turno_com_venda_de_balcao_em_andamento(self):
        self.vender((self.skol, 1))
        with self.assertRaises(ErroNegocio):
            self.turnos.fechar(self.turno, self.adm, 10000)

    def test_resumo_tc_tm_recebimentos_por_forma(self):
        v1 = self.vender((self.skol, 1))                 # 8,00
        self.pagar(v1, "Dinheiro", 1000)                  # troco 2,00
        self.caixa.fechar(v1)
        v2 = self.vender((self.skol, 1), (self.agua, 1))  # 11,50
        self.pagar(v2, "Cartão Débito", 1150)
        self.caixa.fechar(v2)
        r = self.turnos.resumo(self.turno)
        self.assertEqual((r["tc"], r["tm"], r["venda"], r["troco"]), (2, 975, 1950, 200))
        formas = {x["tipo"]: x["valor"] for x in r["recebimentos"]}
        self.assertEqual(formas, {"Dinheiro": 800, "Cartão Débito": 1150})   # dinheiro já líquido do troco
        self.assertEqual((r["cupom_inicial"], r["cupom_final"]), (1, 2))


class TesteVenda(BaseCaixa):
    def test_venda_simples_baixa_estoque_so_ao_fechar(self):
        vid = self.vender((self.skol, 3), (self.agua, 1))
        self.assertEqual(self.prod.por_id(self.skol)["qt_atual"], 100)    # ainda não baixou
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 2750)
        self.pagar(vid, "Dinheiro", 2750)
        v = self.caixa.fechar(vid)
        self.assertEqual((v["status"], v["cupom"], v["turno_id"], v["troco_cent"]), ("fechada", 1, self.turno, 0))
        self.assertEqual(self.prod.por_id(self.skol)["qt_atual"], 97)
        with self.assertRaises(ErroNegocio):
            self.caixa.fechar(vid)                                         # já fechada

    def test_cupons_sao_sequenciais(self):
        for _ in range(3):
            vid = self.vender((self.agua, 1))
            self.pagar(vid, "Dinheiro", 350)
            self.caixa.fechar(vid)
        self.assertEqual([r[0] for r in self.banco.todos("SELECT cupom FROM vendas ORDER BY id")], [1, 2, 3])

    def test_pagamento_insuficiente_e_multiplas_formas(self):
        vid = self.vender((self.skol, 5))                                  # 40,00
        self.pagar(vid, "Dinheiro", 1000)
        with self.assertRaises(ErroNegocio) as e:
            self.caixa.fechar(vid)
        self.assertIn("Faltam R$ 30,00", str(e.exception))
        self.pagar(vid, "Pix", 3000)
        self.assertEqual(self.caixa.fechar(vid)["pago_cent"], 4000)

    def test_troco_em_dinheiro_e_rateio(self):
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Dinheiro", 5000)
        v = self.caixa.fechar(vid)
        self.assertEqual(v["troco_cent"], 4200)
        self.assertEqual(self.caixa.pagamentos(vid)[0]["troco_cent"], 4200)

    def test_excesso_em_forma_sem_troco_e_recusado(self):
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Pix", 1000)
        with self.assertRaises(ErroNegocio):
            self.caixa.fechar(vid)

    def test_forma_que_emite_vale_com_excesso_emite_contra_vale(self):
        self.banco.inserir("tipos_pagamento", {"tipo": "Ticket", "ordem": 50, "emite_vale": 1})
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Ticket", 1000)
        v = self.caixa.fechar(vid)
        self.assertEqual((v["vale_cent"], v["troco_cent"]), (200, 0))
        self.assertEqual(self.turnos.resumo(self.turno)["vale_emitido"], 200)

    def test_cancelar_item_antes_de_fechar(self):
        vid = self.vender((self.skol, 1))
        item = self.caixa.adicionar_item(vid, self.agua, 1)
        self.caixa.cancelar_item(item)
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 800)
        self.assertEqual(len(self.caixa.itens(vid)), 1)
        self.assertEqual(len(self.caixa.itens(vid, cancelados=True)), 2)
        self.pagar(vid, "Dinheiro", 800)
        self.caixa.fechar(vid)
        self.assertEqual(self.prod.por_id(self.skol)["qt_atual"], 99)

    def test_quantidade_fracionada_so_se_o_produto_aceita(self):
        vid = self.caixa.abrir_balcao()
        with self.assertRaises(ErroNegocio):
            self.caixa.adicionar_item(vid, self.skol, 1.5)
        queijo = self.novo_produto("QUEIJO KG", 4000, aceita_decimal="S")
        self.caixa.adicionar_item(vid, queijo, 0.315)
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 1260)       # 40,00 x 0,315

    def test_produto_fora_de_venda_nao_vende(self):
        pid = self.novo_produto("SAZONAL", 500, venda="N")
        vid = self.caixa.abrir_balcao()
        with self.assertRaises(ErroNegocio):
            self.caixa.adicionar_item(vid, pid, 1)

    def test_balcao_em_andamento_e_retomado(self):
        vid = self.vender((self.skol, 1))
        self.assertEqual(self.caixa.abrir_balcao(), vid)

    def test_cancelar_venda_vazia_nao_deixa_rastro_e_com_itens_vira_cupom_cancelado(self):
        vazia = self.caixa.abrir_balcao()
        self.caixa.cancelar_venda(vazia)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas"), 0)
        vid = self.vender((self.skol, 2))
        self.caixa.cancelar_venda(vid, "cliente desistiu")
        v = self.caixa.obter(vid)
        self.assertEqual((v["status"], v["cupom"], v["motivo_cancelamento"]), ("cancelada", 1, "cliente desistiu"))
        self.assertEqual(self.prod.por_id(self.skol)["qt_atual"], 100)

    def test_cancelar_cupom_fechado_estorna_estoque_so_no_turno_aberto(self):
        vid = self.vender((self.skol, 4))
        self.pagar(vid, "Dinheiro", 3200)
        self.caixa.fechar(vid)
        self.assertEqual(self.prod.por_id(self.skol)["qt_atual"], 96)
        self.caixa.cancelar_venda(vid, "erro de lançamento")
        self.assertEqual(self.prod.por_id(self.skol)["qt_atual"], 100)
        self.assertEqual(self.turnos.resumo(self.turno)["tc"], 0)
        v2 = self.vender((self.agua, 1))
        self.pagar(v2, "Dinheiro", 350)
        self.caixa.fechar(v2)
        self.turnos.fechar(self.turno, self.adm, 10350)
        with self.assertRaises(ErroNegocio):
            self.caixa.cancelar_venda(v2)                                 # turno já fechado


class TesteDescontoServico(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("usar_desconto", "S")

    def test_desconto_desligado_por_padrao(self):
        self.banco.cfg_set("usar_desconto", "N")
        vid = self.vender((self.skol, 5))
        with self.assertRaises(ErroNegocio):
            self.caixa.definir_desconto(vid, valor_cent=500)
        self.assertEqual(self.caixa.definir_desconto(vid, valor_cent=0)["total"], 4000)    # zerar é sempre permitido

    def test_desconto_percentual_e_em_valor(self):
        vid = self.vender((self.skol, 5))                                  # 40,00
        self.assertEqual(self.caixa.definir_desconto(vid, pct=10)["total"], 3600)
        self.assertEqual(self.caixa.definir_desconto(vid, valor_cent=500)["total"], 3500)
        with self.assertRaises(ErroNegocio):
            self.caixa.definir_desconto(vid, valor_cent=5000)
        with self.assertRaises(ErroNegocio):
            self.caixa.definir_desconto(vid, pct=101)
        with self.assertRaises(ErroNegocio):
            self.caixa.definir_desconto(vid, pct=5, valor_cent=100)

    def test_desconto_acompanha_novos_itens_quando_percentual(self):
        vid = self.vender((self.skol, 1))
        self.caixa.definir_desconto(vid, pct=50)
        self.caixa.adicionar_item(vid, self.skol, 1)
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 800)

    def test_servico_10_por_cento_so_em_mesa(self):
        balcao = self.vender((self.skol, 1))
        self.assertEqual(self.caixa.obter(balcao)["servico_cent"], 0)
        mesa = self.vender((self.skol, 5), mesa=7)                         # 40,00 + 4,00
        v = self.caixa.obter(mesa)
        self.assertEqual((v["subtotal_cent"], v["servico_cent"], v["total_cent"]), (4000, 400, 4400))

    def test_servico_nao_cobra_produto_marcado_e_desconto_nao_o_reduz(self):
        isento = self.novo_produto("COUVERT", 1000, cobrar_servico="N")
        mesa = self.vender((self.skol, 5), (isento, 1), mesa=3)            # serviço só sobre 40,00
        self.assertEqual(self.caixa.obter(mesa)["servico_cent"], 400)
        self.caixa.definir_desconto(mesa, valor_cent=1000)
        v = self.caixa.obter(mesa)
        self.assertEqual((v["servico_cent"], v["total_cent"]), (400, 5000 - 1000 + 400))

    def test_cliente_pode_pagar_servico_menor_ou_zero(self):
        mesa = self.vender((self.skol, 5), mesa=1)
        self.assertEqual(self.caixa.definir_servico(mesa, 0)["total"], 4000)
        self.assertEqual(self.caixa.definir_servico(mesa, 150)["total"], 4150)
        self.assertEqual(self.caixa.definir_servico(mesa, None)["total"], 4400)   # volta ao automático

    def test_servico_desligado_na_configuracao(self):
        self.banco.cfg_set("cobra_servico_mesa", "N")
        mesa = self.vender((self.skol, 5), mesa=2)
        self.assertEqual(self.caixa.obter(mesa)["total_cent"], 4000)

    def test_fechar_mesa_exige_garcom_quando_configurado(self):
        self.banco.cfg_set("controle_garcom", "S")
        mesa = self.vender((self.skol, 1), mesa=4)
        self.pagar(mesa, "Dinheiro", 880)
        with self.assertRaises(ErroNegocio):
            self.caixa.fechar(mesa)
        self.assertEqual(self.caixa.fechar(mesa, garcom_id=self.adm)["garcom_id"], self.adm)


class TesteMesas(BaseCaixa):
    def test_abrir_e_chamar_mesa(self):
        vid, criada = self.caixa.abrir_mesa(12)
        self.assertTrue(criada)
        self.assertEqual(self.caixa.abrir_mesa(12), (vid, False))
        with self.assertRaises(ErroNegocio):
            self.caixa.abrir_mesa(0)
        with self.assertRaises(ErroNegocio):
            self.caixa.abrir_mesa(51)

    def test_transferir_mesa_inteira_para_posicao_livre(self):
        self.vender((self.skol, 2), mesa=12)
        novo = self.caixa.transferir_mesa(12, 25)
        self.assertEqual([m["posicao"] for m in self.caixa.mesas()], [25])
        self.assertEqual(self.caixa.obter(novo)["subtotal_cent"], 1600)

    def test_transferir_mesa_para_outra_aberta_soma_os_itens(self):
        self.vender((self.skol, 2), mesa=12)
        self.vender((self.agua, 1), mesa=25)
        self.caixa.transferir_mesa(12, 25)
        mesas = self.caixa.mesas()
        self.assertEqual([(m["posicao"], m["subtotal_cent"]) for m in mesas], [(25, 1950)])

    def test_transferir_varias_mesas_para_uma(self):
        self.vender((self.skol, 1), mesa=12)
        self.vender((self.skol, 2), mesa=25)
        self.vender((self.agua, 1), mesa=26)
        destino = self.caixa.transferir_varias([12, 25], 38)
        self.assertEqual(self.caixa.obter(destino)["subtotal_cent"], 2400)
        self.assertEqual([m["posicao"] for m in self.caixa.mesas()], [26, 38])

    def test_transferir_parte_dos_itens(self):
        vid = self.vender((self.skol, 5), mesa=10)
        item = self.caixa.itens(vid)[0]["id"]
        self.caixa.transferir_item(item, 11, 2)
        por_mesa = {m["posicao"]: m["subtotal_cent"] for m in self.caixa.mesas()}
        self.assertEqual(por_mesa, {10: 2400, 11: 1600})
        with self.assertRaises(ErroNegocio):
            self.caixa.transferir_item(item, 11, 99)

    def test_conta_enviada_e_reaberta_ao_lancar_novo_item(self):
        vid = self.vender((self.skol, 1), mesa=5)
        self.caixa.enviar_conta(vid)
        self.assertEqual(self.caixa.obter(vid)["status"], "conta_enviada")
        self.caixa.adicionar_item(vid, self.agua, 1)
        self.assertEqual(self.caixa.obter(vid)["status"], "aberta")

    def test_mesa_inativa_aparece_com_relogio(self):
        self.banco.cfg_set("tempo_inatividade_min", 30)
        self.vender((self.skol, 1), mesa=5)
        self.avancar(minutes=29)
        self.assertFalse(self.caixa.mesas()[0]["inativa"])
        self.avancar(minutes=2)
        self.assertTrue(self.caixa.mesas()[0]["inativa"])

    def test_nao_ha_duas_vendas_abertas_na_mesma_mesa(self):
        self.caixa.abrir_mesa(9)
        with self.assertRaises(Exception):
            self.banco.inserir("vendas", {"uuid": "x", "modalidade": "mesa", "posicao": 9,
                                          "aberta_em": "2026-10-03 21:00:00"})


class TesteCaderneta(BaseCaixa):
    def vender_caderneta(self, cid, *itens):
        vid = self.caixa.abrir_caderneta(cid)
        for pid, qtd in itens:
            self.caixa.adicionar_item(vid, pid, qtd)
        return vid

    def saldo(self, cid):
        return self.banco.valor("SELECT saldo_cent FROM clientes WHERE id = ?", (cid,))

    def test_venda_em_caderneta_debita_sem_pagamento(self):
        cid = self.cliente()
        vid = self.vender_caderneta(cid, (self.skol, 3))
        with self.assertRaises(ErroNegocio):
            self.pagar(vid, "Dinheiro", 100)
        self.caixa.fechar(vid)
        self.assertEqual(self.saldo(cid), -2400)
        r = self.turnos.resumo(self.turno)
        self.assertEqual((r["venda_caderneta"], r["total_recebido"]), (2400, 0))

    def test_limite_de_credito(self):
        cid = self.cliente(limite=1500)
        vid = self.vender_caderneta(cid, (self.skol, 2))                   # 16,00 > 15,00
        with self.assertRaises(ErroNegocio) as e:
            self.caixa.fechar(vid)
        self.assertIn("Limite", str(e.exception))
        self.assertEqual(self.saldo(cid), 0)                               # nada foi alterado
        self.assertEqual(self.caixa.obter(vid)["status"], "aberta")

    def test_recebimento_de_divida_e_credito_com_excedente(self):
        cid = self.cliente()
        self.caixa.fechar(self.vender_caderneta(cid, (self.skol, 3)))      # deve 24,00
        pag = self.caixa.abrir_caderneta(cid)
        self.pagar(pag, "Dinheiro", 3000)
        info = self.caixa.info_credito(pag)
        self.assertEqual((info["divida"], info["excedente"]), (2400, 600))
        with self.assertRaises(ErroNegocio):
            self.caixa.fechar(pag)                                         # precisa decidir o troco
        self.caixa.fechar(pag, excesso_como_credito=True)
        self.assertEqual(self.saldo(cid), 600)                             # ficou com crédito

    def test_recebimento_com_excedente_devolvido_em_troco(self):
        cid = self.cliente()
        self.caixa.fechar(self.vender_caderneta(cid, (self.skol, 3)))
        pag = self.caixa.abrir_caderneta(cid)
        self.pagar(pag, "Dinheiro", 3000)
        v = self.caixa.fechar(pag, excesso_como_credito=False)
        self.assertEqual((self.saldo(cid), v["troco_cent"]), (0, 600))

    def test_cancelar_venda_em_caderneta_devolve_o_saldo(self):
        cid = self.cliente()
        vid = self.vender_caderneta(cid, (self.skol, 2))
        self.caixa.fechar(vid)
        self.caixa.cancelar_venda(vid)
        self.assertEqual(self.saldo(cid), 0)


class TesteMontagem(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.calabresa = self.novo_produto("PIZZA CALABRESA", 4000, estoque=True, qt=10, montagem="S")
        self.mussarela = self.novo_produto("PIZZA MUSSARELA", 3200, estoque=True, qt=10, montagem="S")
        self.meio = self.novo_produto("PIZZA MEIO A MEIO", 0, partes="2", maior="S")

    def test_tres_partes_baixam_exatamente_uma_unidade_no_total(self):
        terco = self.novo_produto("PIZZA TRES SABORES", 0, partes="3", maior="S")
        sabores = [self.novo_produto(f"SABOR {i}", 1000, estoque=True, qt=10, montagem="S") for i in range(3)]
        vid = self.caixa.abrir_balcao()
        item = self.caixa.adicionar_item(vid, terco, 1, partes=sabores)
        fracoes = [r["fracao"] for r in self.banco.todos("SELECT fracao FROM itens_venda_partes WHERE item_id = ?", (item,))]
        self.assertEqual(sum(fracoes), 1.0)                  # 3 x 0.333333 deixaria 0.999999 e uma sobra a cada venda
        self.pagar(vid, "Dinheiro", 1000)
        self.caixa.fechar(vid)
        baixado = sum(10 - self.prod.por_id(p)["qt_atual"] for p in sabores)
        self.assertAlmostEqual(baixado, 1.0, places=9)

    def test_meio_a_meio_cobra_pelo_maior_e_baixa_metade_de_cada(self):
        vid = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(vid, self.meio, 1, partes=[self.calabresa, self.mussarela])
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 4000)
        self.pagar(vid, "Dinheiro", 4000)
        self.caixa.fechar(vid)
        self.assertEqual(self.prod.por_id(self.calabresa)["qt_atual"], 9.5)
        self.assertEqual(self.prod.por_id(self.mussarela)["qt_atual"], 9.5)

    def test_meio_a_meio_proporcional(self):
        self.banco.executar("UPDATE produtos SET maior = 0 WHERE id = ?", (self.meio,))
        vid = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(vid, self.meio, 1, partes=[self.calabresa, self.mussarela])
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 3600)

    def test_validacoes_de_montagem(self):
        vid = self.caixa.abrir_balcao()
        with self.assertRaises(ErroNegocio):
            self.caixa.adicionar_item(vid, self.meio, 1, partes=[self.calabresa, self.mussarela, self.skol])  # 3 > 2
        with self.assertRaises(ErroNegocio):
            self.caixa.adicionar_item(vid, self.meio, 1, partes=[self.skol, self.skol])   # não é de montagem

    def test_combo_composto_tem_preco_unico(self):
        lanche = self.novo_produto("LANCHE", 700, compoe="S")
        suco = self.novo_produto("SUCO", 500, compoe="S")
        combo = self.novo_produto("COMBO 1", 1000, composto="S", partes="2")
        vid = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(vid, combo, 1, partes=[lanche, suco])
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 1000)


if __name__ == "__main__":
    import unittest
    unittest.main()
