"""Melhoria 6 do caixa: divisão da conta por item (vínculo pagamento x item) e por valor, em centavos exatos."""
from __future__ import annotations

import json
from unittest.mock import patch

from src.core.erros import ErroNegocio
from tests.test_caixa_cancelamento_parcial import BaseCancelamentoParcial


class TestDivisaoPorItem(BaseCancelamentoParcial):
    def vinculos(self, vid):
        return [dict(r) for r in self.banco.todos(
            """SELECT x.* FROM pagamentos_itens x JOIN pagamentos_venda p ON p.id = x.pagamento_id
               WHERE p.venda_id = ? ORDER BY x.id""", (vid,))]

    def test_paga_o_valor_exato_do_item_e_vincula(self):
        vid = self.vender((self.skol, 2), (self.agua, 1))
        skol, agua = (i["id"] for i in self.caixa.itens(vid))
        self.assertEqual(self.caixa.previa_pagamento_itens(vid, [(agua, 1)])["valor_cent"], 350)
        pid = self.caixa.pagar_itens(vid, self.tipo("Pix"), [(agua, 1)], valor_esperado_cent=350)
        p = self.caixa.pagamentos(vid)[0]
        self.assertEqual((p["id"], p["valor_cent"], p["tipo"]), (pid, 350, "Pix"))
        self.assertEqual([(x["item_id"], x["quantidade"], x["valor_cent"]) for x in self.vinculos(vid)], [(agua, 1, 350)])
        self.assertEqual(self.caixa.liquidar(vid)["falta"], 1600)
        d = {x["item_id"]: x for x in self.caixa.itens_para_divisao(vid)}
        self.assertEqual((d[agua]["qtd_livre"], d[agua]["valor_livre_cent"], d[agua]["qtd_paga"]), (0, 0, 1))
        self.assertEqual((d[skol]["qtd_livre"], d[skol]["valor_livre_cent"]), (2, 1600))
        self.assertEqual(self.caixa.itens_do_pagamento(pid)[0]["nome"], "AGUA")
        aud = self.auditorias("pagamento_por_item")
        self.assertEqual(json.loads(aud[0]["depois"])["itens"], [{"item_id": agua, "quantidade": 1, "valor_cent": 350}])

    def test_nao_cobra_duas_vezes_o_mesmo_item(self):
        vid = self.vender((self.skol, 2), (self.agua, 1))
        skol, agua = (i["id"] for i in self.caixa.itens(vid))
        self.caixa.pagar_itens(vid, self.tipo("Pix"), [(agua, 1)])
        with self.assertRaisesRegex(ErroNegocio, "já foi pago"):
            self.caixa.pagar_itens(vid, self.tipo("Dinheiro"), [(agua, 1)])
        with self.assertRaisesRegex(ErroNegocio, "mais de uma vez"):
            self.caixa.pagar_itens(vid, self.tipo("Dinheiro"), [(skol, 1), (skol, 1)])
        with self.assertRaisesRegex(ErroNegocio, "só 2"):
            self.caixa.pagar_itens(vid, self.tipo("Dinheiro"), [(skol, 3)])
        self.assertEqual(len(self.caixa.pagamentos(vid)), 1)

    def test_fracoes_somam_exatamente_o_total_do_item(self):
        queijo = self.novo_produto("QUEIJO", 999, aceita_decimal="S")
        vid = self.vender((queijo, 1.5))
        item = self.caixa.itens(vid)[0]
        valores = []
        for _ in range(3):
            valores.append(self.caixa.previa_pagamento_itens(vid, [(item["id"], 0.5)])["valor_cent"])
            self.caixa.pagar_itens(vid, self.tipo("Pix"), [(item["id"], 0.5)], valor_esperado_cent=valores[-1])
        self.assertEqual(valores, [500, 500, 499])                                # o último leva o centavo que sobra
        self.assertEqual(sum(valores), item["total_cent"])
        self.assertEqual(sum(p["valor_cent"] for p in self.caixa.pagamentos(vid)), item["total_cent"])
        self.assertEqual(self.caixa.liquidar(vid)["falta"], 0)
        with self.assertRaisesRegex(ErroNegocio, "já foi pago"):
            self.caixa.pagar_itens(vid, self.tipo("Pix"), [(item["id"], 0.5)])

    def test_mesa_itens_por_item_e_servico_dividido_por_valor_fecha_sem_sobra(self):
        vid = self.vender((self.skol, 3), (self.agua, 1), mesa=4)              # 24,00 + 3,50 + 10% = 30,25
        skol, agua = (i["id"] for i in self.caixa.itens(vid))
        self.caixa.pagar_itens(vid, self.tipo("Pix"), [(skol, 1)])
        self.caixa.pagar_itens(vid, self.tipo("Dinheiro"), [(skol, 2), (agua, 1)])
        partes = self.caixa.dividir_restante(vid, 2)                          # sobra o serviço (2,75)
        self.assertEqual(partes, [138, 137])
        for parte in partes:
            self.pagar(vid, "Dinheiro", parte)
        r = self.caixa.fechar(vid)
        v = self.caixa.obter(vid)
        self.assertEqual((v["status"], v["total_cent"], v["pago_cent"], v["troco_cent"]), ("fechada", 3025, 3025, 0))
        self.assertIsNotNone(r)

    def test_forma_com_acrescimo_soma_a_taxa_uma_vez(self):
        vid = self.vender((self.skol, 2))
        item = self.caixa.itens(vid)[0]["id"]
        credito = self.tipo("Cartão Crédito")
        with self.assertRaisesRegex(ErroNegocio, "mudou para R\\$ 13,00"):
            self.caixa.pagar_itens(vid, credito, [(item, 1)], valor_esperado_cent=800)
        self.assertEqual(self.caixa.pagamentos(vid), [])
        self.caixa.pagar_itens(vid, credito, [(item, 1)], valor_esperado_cent=1300)
        self.assertEqual(self.vinculos(vid)[0]["valor_cent"], 800)               # o vínculo é só do item
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 2100)
        self.caixa.pagar_itens(vid, credito, [(item, 1)], valor_esperado_cent=800)   # a taxa já foi cobrada
        self.assertEqual(self.caixa.liquidar(vid)["falta"], 0)

    def test_pagamento_por_valor_sem_item_limita_a_divisao(self):
        vid = self.vender((self.skol, 2), (self.agua, 1))                         # 19,50
        skol, agua = (i["id"] for i in self.caixa.itens(vid))
        self.pagar(vid, "Dinheiro", 1800)                                          # faltam 1,50
        with self.assertRaisesRegex(ErroNegocio, "faltam só R\\$ 1,50"):
            self.caixa.pagar_itens(vid, self.tipo("Pix"), [(agua, 1)])
        self.assertEqual(len(self.caixa.pagamentos(vid)), 1)

    def test_remover_pagamento_libera_os_itens(self):
        vid = self.vender((self.skol, 2))
        item = self.caixa.itens(vid)[0]["id"]
        pid = self.caixa.pagar_itens(vid, self.tipo("Pix"), [(item, 2)])
        self.caixa.remover_pagamento(pid)
        self.assertEqual(self.vinculos(vid), [])
        aud = self.auditorias("vinculo_itens_liberado")
        self.assertEqual(json.loads(aud[0]["antes"])["itens"], [{"item_id": item, "quantidade": 2, "valor_cent": 1600}])
        self.caixa.pagar_itens(vid, self.tipo("Dinheiro"), [(item, 2)])
        self.assertEqual(self.caixa.liquidar(vid)["falta"], 0)

    def test_cancelar_a_conta_aberta_apaga_os_vinculos_do_turno(self):
        vid = self.vender((self.skol, 2))
        self.caixa.pagar_itens(vid, self.tipo("Pix"), [(self.caixa.itens(vid)[0]["id"], 1)])
        self.caixa.cancelar_venda(vid, "desistiu")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM pagamentos_itens"), 0)
        self.assertEqual(self.caixa.obter(vid)["status"], "cancelada")

    def test_vinculos_ficam_no_historico_da_venda_fechada(self):
        vid = self.vender((self.skol, 2))
        item = self.caixa.itens(vid)[0]["id"]
        pid = self.caixa.pagar_itens(vid, self.tipo("Pix"), [(item, 2)])
        self.caixa.fechar(vid)
        self.assertEqual(len(self.caixa.itens_do_pagamento(pid)), 1)
        with self.assertRaisesRegex(ErroNegocio, "encerrada"):
            self.caixa.remover_pagamento(pid)

    def test_transferir_item_respeita_a_parte_paga(self):
        vid = self.vender((self.skol, 3), mesa=1)
        item = self.caixa.itens(vid)[0]["id"]
        self.caixa.pagar_itens(vid, self.tipo("Pix"), [(item, 1)])
        with self.assertRaisesRegex(ErroNegocio, "até 2"):
            self.caixa.transferir_item(item, 2, 3)
        self.caixa.transferir_item(item, 2, 2)
        self.assertEqual(self.caixa.itens(vid)[0]["quantidade"], 1)
        self.assertEqual(self.vinculos(vid)[0]["item_id"], item)

    def test_recusas_por_modalidade_e_item_sem_valor(self):
        cad = self.caixa.abrir_caderneta(self.cliente("ANA", limite=100000))
        self.caixa.adicionar_item(cad, self.skol, 1)
        with self.assertRaisesRegex(ErroNegocio, "caderneta"):
            self.caixa.pagar_itens(cad, self.tipo("Pix"), [(self.caixa.itens(cad)[0]["id"], 1)])
        self.banco.cfg_set("usar_prepago", "S")
        pre, _ = self.caixa.abrir_mesa(15, comanda=True)
        self.caixa.recarregar(pre, self.tipo("Dinheiro"), 5000)
        self.caixa.adicionar_item(pre, self.skol, 1)
        with self.assertRaisesRegex(ErroNegocio, "pré-paga"):
            self.caixa.pagar_itens(pre, self.tipo("Pix"), [(self.caixa.itens(pre)[0]["id"], 1)])
        vid = self.vender((self.skol, 1))
        with self.assertRaisesRegex(ErroNegocio, "não encontrado"):
            self.caixa.pagar_itens(vid, self.tipo("Pix"), [(999999, 1)])
        with self.assertRaisesRegex(ErroNegocio, "ao menos um"):
            self.caixa.pagar_itens(vid, self.tipo("Pix"), [])

    def test_item_incluso_no_rodizio_nao_e_pago_por_item(self):
        self.banco.cfg_set("usar_rodizio", "S")
        self.banco.cfg_set("valor_rodizio_pessoa", "50,00")
        sub = self.banco.valor("SELECT id FROM subgrupos LIMIT 1")
        self.banco.executar("UPDATE subgrupos SET rodizio_incluso = 1 WHERE id = ?", (sub,))
        vid = self.vender((self.agua, 1), mesa=7)
        self.caixa.ativar_rodizio(vid, 2)
        with self.assertRaisesRegex(ErroNegocio, "rodízio"):
            self.caixa.pagar_itens(vid, self.tipo("Pix"), [(self.caixa.itens(vid)[0]["id"], 1)])

    def test_falha_ao_gravar_vinculo_desfaz_o_pagamento(self):
        vid = self.vender((self.skol, 2))
        item = self.caixa.itens(vid)[0]["id"]
        with patch.object(self.banco, "registrar_auditoria", side_effect=RuntimeError("falhou")):
            with self.assertRaises(RuntimeError):
                self.caixa.pagar_itens(vid, self.tipo("Pix"), [(item, 1)])
        self.assertEqual(self.caixa.pagamentos(vid), [])
        self.assertEqual(self.vinculos(vid), [])

    def test_sem_a_tabela_recusa_com_mensagem_clara(self):
        self.banco.conexao.executescript("DROP TABLE pagamentos_itens;")
        vid = self.vender((self.skol, 2))
        self.assertEqual(self.caixa.itens_para_divisao(vid)[0]["qtd_livre"], 2)
        with self.assertRaisesRegex(ErroNegocio, "atualização do banco"):
            self.caixa.pagar_itens(vid, self.tipo("Pix"), [(self.caixa.itens(vid)[0]["id"], 1)])
        self.assertEqual(self.caixa.pagamentos(vid), [])


class TestTravaDosVinculos(BaseCancelamentoParcial):
    """Nenhuma mutação da conta pode deixar um pagamento por item cobrindo outro preço, outra quantidade ou outro item."""

    vinculos = TestDivisaoPorItem.vinculos

    def estado(self, vid):
        return (self.linhas(vid), [dict(p) for p in self.caixa.pagamentos(vid)],
                [dict(r) for r in self.banco.todos("SELECT * FROM pagamentos_itens ORDER BY id")],
                {k: self.caixa.obter(vid)[k] for k in ("total_cent", "desconto_cent", "servico_cent", "rodizio")})

    def test_nova_leitura_que_muda_a_faixa_do_atacado_e_recusada(self):
        lata = self.novo_produto("LATA", 800, atacado_qtd="6", preco_atacado_cent="7,00")
        vid = self.vender((lata, 5))
        item = self.caixa.itens(vid)[0]["id"]
        pid = self.caixa.pagar_itens(vid, self.tipo("Pix"), [(item, 2)])
        antes = self.estado(vid)
        with self.assertRaisesRegex(ErroNegocio, "faixa de atacado.*Remova o pagamento"):
            self.caixa.adicionar_item(vid, lata, 1)
        self.assertEqual(self.estado(vid), antes)                                  # rollback completo
        self.caixa.remover_pagamento(pid)
        self.caixa.adicionar_item(vid, lata, 1)
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 4200)

    def test_cancelar_outro_item_que_tira_da_faixa_e_recusado(self):
        lata = self.novo_produto("LATA", 800, atacado_qtd="6", preco_atacado_cent="7,00")
        vid = self.vender((lata, 3), (lata, 3))
        pago, livre = (i["id"] for i in self.caixa.itens(vid))
        self.caixa.pagar_itens(vid, self.tipo("Pix"), [(pago, 3)], valor_esperado_cent=2100)
        antes = self.estado(vid)
        with self.assertRaisesRegex(ErroNegocio, "já foi pago na divisão por item"):
            self.caixa.cancelar_item(livre, "devolveu", quantidade=1)
        with self.assertRaisesRegex(ErroNegocio, "já foi pago na divisão por item"):
            self.caixa.cancelar_item(livre, "devolveu")
        self.assertEqual(self.estado(vid), antes)

    def test_agrupamento_nao_soma_leitura_nova_na_linha_paga(self):
        self.banco.cfg_set("agrupar_itens_balcao", "S")
        vid = self.vender((self.skol, 2))
        item = self.caixa.itens(vid)[0]["id"]
        self.caixa.pagar_itens(vid, self.tipo("Pix"), [(item, 2)])
        self.caixa.adicionar_item(vid, self.skol, 1)
        itens = self.caixa.itens(vid)
        self.assertEqual([(i["id"] == item, i["quantidade"]) for i in itens], [(True, 2), (False, 1)])
        self.assertEqual([(x["item_id"], x["quantidade"]) for x in self.vinculos(vid)], [(item, 2)])
        self.assertEqual(self.caixa.liquidar(vid)["falta"], 800)                   # a leitura nova continua a pagar

    def test_desconto_que_deixa_a_conta_abaixo_do_pago_por_item_e_recusado(self):
        self.banco.cfg_set("usar_desconto", "S")
        vid = self.vender((self.skol, 2))
        item = self.caixa.itens(vid)[0]["id"]
        self.caixa.pagar_itens(vid, self.tipo("Pix"), [(item, 1)])
        antes = self.estado(vid)
        with self.assertRaisesRegex(ErroNegocio, r"abaixo dos R\$ 8,00 já pagos"):
            self.caixa.definir_desconto(vid, valor_cent=900)
        with self.assertRaisesRegex(ErroNegocio, "abaixo"):
            self.caixa.definir_desconto(vid, pct=60)
        self.assertEqual(self.estado(vid), antes)
        self.assertEqual(self.caixa.definir_desconto(vid, valor_cent=800)["total"], 800)

    def test_retirar_servico_abaixo_do_pago_por_item_e_recusado(self):
        self.banco.cfg_set("usar_desconto", "S")
        vid = self.vender((self.skol, 1), (self.agua, 1), mesa=6)
        self.caixa.definir_desconto(vid, valor_cent=100)                           # 11,50 - 1,00 + 1,15 = 11,65
        self.caixa.pagar_itens(vid, self.tipo("Pix"), [(i["id"], 1) for i in self.caixa.itens(vid)])
        antes = self.estado(vid)
        with self.assertRaisesRegex(ErroNegocio, r"abaixo dos R\$ 11,50"):
            self.caixa.definir_servico(vid, 0)
        self.assertEqual(self.estado(vid), antes)
        self.assertEqual(self.caixa.obter(vid)["servico_manual"], 0)
        self.assertEqual(self.caixa.definir_servico(vid, 100)["total"], 1150)

    def test_rodizio_nao_zera_item_ja_pago(self):
        self.banco.cfg_set("usar_rodizio", "S")
        self.banco.cfg_set("valor_rodizio_pessoa", "50,00")
        vid = self.vender((self.agua, 1), mesa=7)
        self.caixa.pagar_itens(vid, self.tipo("Pix"), [(self.caixa.itens(vid)[0]["id"], 1)])
        sub = self.banco.valor("SELECT subgrupo_id FROM produtos WHERE id = ?", (self.agua,))
        self.banco.executar("UPDATE subgrupos SET rodizio_incluso = 1 WHERE id = ?", (sub,))
        antes = self.estado(vid)
        with self.assertRaisesRegex(ErroNegocio, "rodízio"):
            self.caixa.ativar_rodizio(vid, 2)
        self.assertEqual(self.estado(vid), antes)

    def test_transferir_mesa_leva_pagamento_e_vinculo_juntos(self):
        vid = self.vender((self.skol, 2), mesa=1)
        destino = self.vender((self.agua, 1), mesa=2)
        item = self.caixa.itens(vid)[0]["id"]
        pid = self.caixa.pagar_itens(vid, self.tipo("Pix"), [(item, 2)])
        self.assertEqual(self.caixa.transferir_mesa(1, 2), destino)
        self.assertEqual([p["id"] for p in self.caixa.pagamentos(destino)], [pid])
        d = {x["item_id"]: x for x in self.caixa.itens_para_divisao(destino)}
        self.assertEqual((d[item]["qtd_livre"], d[item]["valor_pago_cent"]), (0, 1600))
        with self.assertRaisesRegex(ErroNegocio, "já foi pago"):
            self.caixa.pagar_itens(destino, self.tipo("Pix"), [(item, 1)])

    def test_cancelar_a_parte_livre_deixa_a_linha_com_o_valor_exato_pago(self):
        queijo = self.novo_produto("QUEIJO", 1999, aceita_decimal="S")
        vid = self.vender((queijo, 1.5))
        original = self.caixa.itens(vid)[0]
        pid = self.caixa.pagar_itens(vid, self.tipo("Pix"), [(original["id"], 0.75)])
        pago = self.caixa.pagamentos(vid)[0]["valor_cent"]
        self.caixa.cancelar_item(original["id"], "sobrou", quantidade=0.75)
        linhas = self.linhas(vid)
        self.assertEqual(linhas[0]["total_cent"], pago)
        self.assertEqual(sum(l["total_cent"] for l in linhas), original["total_cent"])
        self.assertEqual(self.caixa.liquidar(vid)["falta"], 0)
        self.caixa.remover_pagamento(pid)
        self.caixa.cancelar_item(original["id"], "desistiu")
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 0)
