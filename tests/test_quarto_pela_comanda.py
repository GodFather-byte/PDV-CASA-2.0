"""Quarto lançado na comanda do cliente (G25): ao pagar, inicia o quarto, soma tempo ou vai para a fila; cancelar desfaz."""
from __future__ import annotations

from src.core.erros import ErroNegocio
from tests.test_shows_quartos import BaseShows


class TesteQuartoPelaComanda(BaseShows):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("quartos_qtd", "3")
        self.produto = self.q.produto_quarto()

    def vender(self, garota=180, blocos=1, quarto=None, pagar=True, extras=()):
        vid = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(vid, self.produto["id"], blocos, garota_quarto=garota, quarto_pedido=quarto)
        for pid, qtd in extras:
            self.caixa.adicionar_item(vid, pid, qtd)
        if pagar:
            self.caixa.adicionar_pagamento(vid, self.tipo("Dinheiro"), self.caixa.obter(vid)["total_cent"])
            self.caixa.fechar(vid)
        return vid

    def ativo(self, quarto):
        return self.banco.um("SELECT * FROM quartos_uso WHERE quarto = ? AND liberado_em IS NULL", (quarto,))

    def test_produto_do_quarto_nasce_com_o_preco_do_bloco_uma_vez_so(self):
        self.assertEqual((self.produto["nome"], self.produto["preco_cent"]), ("QUARTO 30 min", 9000))
        self.assertEqual(self.q.produto_quarto()["id"], self.produto["id"])

    def test_pagar_inicia_o_quarto_livre_ha_mais_tempo_e_conta_os_shows_dela(self):
        self.q.iniciar(1, 1)
        self.avancar(minutes=5)
        self.q.liberar(1)                                   # o 1 acabou de liberar; 2 e 3 nunca foram usados
        vid = self.vender(blocos=2, extras=((self.skol, 2),))
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 2 * 9000 + 2 * 800)
        uso = self.ativo(2)
        self.assertEqual((uso["codigo_profissional"], uso["blocos"]), ("180", 2))
        self.assertEqual(self.com.quantidade_shows_quartos(180), 2)
        self.assertEqual([(r["quarto"], r["situacao"], r["nome"]) for r in self.caixa.ultimos_quartos],
                         [(2, "iniciado", "ANA")])

    def test_nao_inicia_antes_de_pagar(self):
        self.vender(pagar=False)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM quartos_uso"), 0)
        self.assertEqual(self.com.quantidade_shows_quartos(180), 0)

    def test_quarto_pedido_e_ela_ja_no_quarto_soma_o_tempo(self):
        self.vender(quarto=3)
        self.assertEqual(self.ativo(3)["codigo_profissional"], "180")
        self.vender(blocos=1)                               # pagou mais 30 min: soma no 3, não abre outro
        self.assertEqual(self.ativo(3)["blocos"], 2)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM quartos_uso WHERE liberado_em IS NULL"), 1)
        self.assertEqual(self.com.quantidade_shows_quartos(180), 2)
        self.assertEqual(self.caixa.ultimos_quartos[0]["situacao"], "somado")

    def test_duas_garotas_na_mesma_comanda_vao_para_quartos_diferentes(self):
        vid = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(vid, self.produto["id"], 1, garota_quarto=180)
        self.caixa.adicionar_item(vid, self.produto["id"], 1, garota_quarto=181)
        self.caixa.adicionar_item(vid, self.produto["id"], 1, garota_quarto=180)      # mais 30 min para a ANA
        self.caixa.adicionar_pagamento(vid, self.tipo("Dinheiro"), self.caixa.obter(vid)["total_cent"])
        self.caixa.fechar(vid)
        quartos = {r["garota"]: (r["quarto"], r["blocos"]) for r in self.caixa.ultimos_quartos}
        self.assertEqual(quartos, {180: (1, 2), 181: (2, 1)})

    def test_sem_quarto_livre_vai_para_a_fila_e_inicia_quando_liberar(self):
        for quarto in (1, 2, 3):
            self.q.iniciar(quarto, 1)
        self.vender()
        self.assertEqual(self.caixa.ultimos_quartos[0]["situacao"], "aguardando")
        self.assertEqual(self.com.quantidade_shows_quartos(180), 0)
        fila = self.q.fila()
        self.assertEqual([(f["garota"], f["nome"], f["duracao"]) for f in fila], [(180, "ANA", "30 min")])
        with self.assertRaisesRegex(ErroNegocio, "Nenhum quarto livre"):
            self.q.iniciar_da_fila(fila[0]["id"])
        self.q.liberar(2)
        r = self.q.iniciar_da_fila(fila[0]["id"])
        self.assertEqual((r["quarto"], r["situacao"]), (2, "iniciado"))
        self.assertEqual(self.com.quantidade_shows_quartos(180), 1)
        self.assertEqual(self.q.fila(), [])

    def test_cancelar_o_cupom_desfaz_tempo_e_shows(self):
        vid = self.vender(blocos=2)
        self.caixa.cancelar_venda(vid, "lançado errado")
        self.assertIsNone(self.ativo(1))
        self.assertEqual(self.com.quantidade_shows_quartos(180), 0)
        vid1 = self.vender(blocos=1)                        # entra no quarto
        vid2 = self.vender(blocos=1)                        # mais tempo
        self.caixa.cancelar_venda(vid2, "mais tempo cobrado errado")
        quarto = self.banco.um("SELECT * FROM quartos_uso WHERE codigo_profissional = '180' AND liberado_em IS NULL")
        self.assertEqual(quarto["blocos"], 1)
        self.assertEqual(self.com.quantidade_shows_quartos(180), 1)
        self.assertTrue(vid1)

    def test_cancelar_recusa_show_ja_pago_no_acerto(self):
        vid = self.vender()
        self.pagar()
        with self.assertRaisesRegex(ErroNegocio, "já foi pago no acerto"):
            self.caixa.cancelar_venda(vid, "tarde demais")
        self.assertEqual(self.caixa.obter(vid)["status"], "fechada")

    def test_validacoes_do_lancamento(self):
        vid = self.caixa.abrir_balcao()
        for kw, trecho in (({"garota_quarto": 999}, "não cadastrada"), ({"garota_quarto": None, "quarto_pedido": 1},
                                                                        "número de uma garota"),
                           ({"garota_quarto": 180, "quarto_pedido": 9}, "inexistente")):
            with self.assertRaisesRegex(ErroNegocio, trecho):
                self.caixa.adicionar_item(vid, self.produto["id"], 1, **kw)
        with self.assertRaisesRegex(ErroNegocio, "Só o produto do quarto"):
            self.caixa.adicionar_item(vid, self.skol, 1, garota_quarto=180)
        with self.assertRaisesRegex(ErroNegocio, "fracionada"):
            self.caixa.adicionar_item(vid, self.produto["id"], 1.5, garota_quarto=180)
        self.banco.cfg_set("usar_quartos", "N")
        with self.assertRaisesRegex(ErroNegocio, "desligado"):
            self.caixa.adicionar_item(vid, self.produto["id"], 1, garota_quarto=180)
