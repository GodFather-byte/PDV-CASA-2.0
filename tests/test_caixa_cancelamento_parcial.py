"""Melhoria 1 do caixa: cancelamento parcial por quantidade, só do que não foi pago, com motivo e auditoria."""
from __future__ import annotations

import json
from unittest.mock import patch

from src.core.erros import ErroNegocio
from tests.test_caixa import BaseCaixa

# Contrato DDL entregue ao dono do esquema (a migração oficial cria esta tabela; os testes a criam aqui).
DDL_PAGAMENTOS_ITENS = """
CREATE TABLE IF NOT EXISTS pagamentos_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pagamento_id INTEGER NOT NULL REFERENCES pagamentos_venda(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES itens_venda(id) ON DELETE CASCADE,
    quantidade REAL NOT NULL CHECK (quantidade > 0),
    valor_cent INTEGER NOT NULL CHECK (valor_cent >= 0),
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pagamentos_itens_item ON pagamentos_itens(item_id);
CREATE INDEX IF NOT EXISTS ix_pagamentos_itens_pagamento ON pagamentos_itens(pagamento_id);
"""


def criar_vinculos(banco) -> None:
    banco.conexao.executescript(DDL_PAGAMENTOS_ITENS)


class BaseCancelamentoParcial(BaseCaixa):
    def setUp(self):
        super().setUp()
        criar_vinculos(self.banco)

    def linhas(self, vid):
        return [dict(r) for r in self.banco.todos(
            "SELECT * FROM itens_venda WHERE venda_id = ? ORDER BY id", (vid,))]

    def auditorias(self, acao):
        return [dict(r) for r in self.banco.todos(
            "SELECT * FROM auditoria_eventos WHERE acao = ? ORDER BY id", (acao,))]


class TestCancelamentoParcial(BaseCancelamentoParcial):
    def test_cinde_a_linha_e_preserva_o_historico(self):
        vid = self.vender((self.skol, 5))
        item = self.caixa.itens(vid)[0]["id"]
        retrato = self.linhas(vid)[0]["regra_preco_json"]
        cancelado = self.caixa.cancelar_item(item, "cliente desistiu", quantidade=2)
        ativa, linha = self.linhas(vid)
        self.assertEqual((ativa["id"], ativa["quantidade"], ativa["total_cent"], ativa["cancelado"]), (item, 3, 2400, 0))
        self.assertEqual((linha["id"], linha["quantidade"], linha["total_cent"], linha["cancelado"]),
                         (cancelado, 2, 1600, 1))
        self.assertEqual(linha["cancelado_em"], "2026-10-03 21:00:00")
        self.assertEqual((linha["produto_id"], linha["preco_unit_cent"], linha["regra_preco_json"]),
                         (ativa["produto_id"], ativa["preco_unit_cent"], retrato))   # retrato do preço preservado
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 2400)
        aud = self.auditorias("cancelamento_parcial")
        self.assertEqual(len(aud), 1)
        self.assertEqual((aud[0]["entidade"], aud[0]["entidade_id"], aud[0]["operador_id"]), ("itens_venda", str(item), self.adm))
        depois = json.loads(aud[0]["depois"])
        self.assertEqual((depois["linha_cancelada_id"], depois["quantidade_cancelada"], depois["valor_cancelado_cent"],
                          depois["motivo"]), (cancelado, 2, 1600, "cliente desistiu"))
        self.assertEqual(json.loads(aud[0]["antes"])["quantidade"], 5)
        log = self.banco.valor("SELECT detalhe FROM log_eventos WHERE evento = 'item_cancelado'")
        self.assertTrue(log.startswith(f"venda {vid} item {cancelado} (parcial de {item}"))
        self.assertTrue(log.endswith("motivo: cliente desistiu"))

    def test_relatorio_do_turno_le_a_quantidade_cancelada(self):
        from src.controllers.conferencia_turno import _itens_cancelados
        vid = self.vender((self.skol, 5))
        self.caixa.cancelar_item(self.caixa.itens(vid)[0]["id"], "quebrou", quantidade=2)
        r = _itens_cancelados(self.banco, "2026-10-03 00:00:00", "2026-10-04 00:00:00")
        self.assertEqual([(x["quantidade"], x["total_cent"], x["motivo"]) for x in r], [(2, 1600, "quebrou")])

    def test_motivo_e_obrigatorio_no_parcial(self):
        vid = self.vender((self.skol, 5))
        item = self.caixa.itens(vid)[0]["id"]
        for motivo in ("", "   ", None):
            with self.assertRaisesRegex(ErroNegocio, "motivo"):
                self.caixa.cancelar_item(item, motivo, quantidade=1)
        self.assertEqual(len(self.linhas(vid)), 1)
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 4000)

    def test_quantidade_invalida(self):
        vid = self.vender((self.skol, 5))
        item = self.caixa.itens(vid)[0]["id"]
        for qtd, erro in ((0, "maior que zero"), (-1, "maior que zero"), (6, "acima"), (1.5, "fracionada"),
                          ("abc", ".")):
            with self.subTest(qtd=qtd), self.assertRaisesRegex(ErroNegocio, erro):
                self.caixa.cancelar_item(item, "x", quantidade=qtd)
        self.assertEqual(len(self.linhas(vid)), 1)

    def test_quantidade_inteira_e_o_cancelamento_total_de_sempre(self):
        vid = self.vender((self.skol, 5), (self.agua, 1))
        item = self.caixa.itens(vid)[0]["id"]
        self.assertEqual(self.caixa.cancelar_item(item, quantidade=5), item)   # sem motivo: como o cancelamento total
        self.assertEqual(len(self.linhas(vid)), 2)
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 350)
        self.assertEqual(self.auditorias("cancelamento_parcial"), [])

    def test_fracionado_e_comissao_somam_exatamente_o_original(self):
        queijo = self.novo_produto("QUEIJO", 3333, aceita_decimal="S", comissao_pct="7")
        vid = self.vender((queijo, 1.237))
        original = self.linhas(vid)[0]
        self.caixa.cancelar_item(original["id"], "pesou errado", quantidade=0.4115)
        ativa, linha = self.linhas(vid)
        self.assertAlmostEqual(ativa["quantidade"] + linha["quantidade"], original["quantidade"])
        self.assertEqual(ativa["quantidade"], 0.8255)
        self.assertEqual(ativa["total_cent"] + linha["total_cent"], original["total_cent"])
        self.assertEqual(ativa["comissao_cent"] + linha["comissao_cent"], original["comissao_cent"])
        self.assertIsInstance(linha["total_cent"], int)

    def test_composicao_copia_as_partes_para_a_linha_cancelada(self):
        a = self.novo_produto("PARTE A", 1200, montagem="S")
        b = self.novo_produto("PARTE B", 1600, montagem="S")
        pizza = self.novo_produto("PIZZA", 1000)
        self.banco.executar("UPDATE produtos SET partes = 2 WHERE id = ?", (pizza,))
        vid = self.caixa.abrir_balcao()
        item = self.caixa.adicionar_item(vid, pizza, 3, partes=[a, b])
        cancelado = self.caixa.cancelar_item(item, "voltou", quantidade=1)
        partes = lambda i: [(r["produto_id"], r["fracao"]) for r in self.banco.todos(
            "SELECT produto_id, fracao FROM itens_venda_partes WHERE item_id = ? ORDER BY id", (i,))]
        self.assertEqual(partes(cancelado), partes(item))
        self.assertEqual(self.caixa.itens(vid)[0]["partes_nomes"], ["PARTE A", "PARTE B"])
        self.assertEqual(self.caixa.itens(vid)[0]["quantidade"], 2)

    def test_atacado_do_balcao_e_reavaliado(self):
        cerveja = self.novo_produto("LATA", 800, atacado_qtd="6", preco_atacado_cent="7,00")
        vid = self.vender((cerveja, 6))
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 4200)          # 6 x 7,00 no atacado
        self.caixa.cancelar_item(self.caixa.itens(vid)[0]["id"], "devolveu uma", quantidade=1)
        ativa = self.caixa.itens(vid)[0]
        self.assertEqual((ativa["quantidade"], ativa["preco_unit_cent"], ativa["total_cent"]), (5, 800, 4000))
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 4000)          # saiu da faixa: volta ao preço normal
        retrato = json.loads(ativa["regra_preco_json"])
        self.assertEqual((retrato["quantidade_grupo"], retrato["faixa_atingida"]), (5, False))

    def test_mesa_com_servico_recalcula(self):
        vid = self.vender((self.skol, 5), mesa=3)
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 4400)
        self.caixa.cancelar_item(self.caixa.itens(vid)[0]["id"], "erro", quantidade=1)
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 3520)


class TestProtecaoDoQueFoiPago(BaseCancelamentoParcial):
    def test_pagamento_por_valor_bloqueia_cancelar_parcela_paga(self):
        vid = self.vender((self.skol, 5))
        self.pagar(vid, "Dinheiro", 3000)
        item = self.caixa.itens(vid)[0]["id"]
        self.caixa.cancelar_item(item, "sobrou", quantidade=1)                 # 32,00 ainda cobre os 30,00 pagos
        antes = self.linhas(vid)
        with self.assertRaisesRegex(ErroNegocio, "abaixo do que já foi pago"):
            self.caixa.cancelar_item(item, "sobrou", quantidade=1)             # 24,00 < 30,00: tiraria o que foi pago
        with self.assertRaisesRegex(ErroNegocio, "abaixo do que já foi pago"):
            self.caixa.cancelar_item(item)                                     # o total também
        self.assertEqual(self.linhas(vid), antes)                              # rollback: nada mudou
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 3200)
        self.assertEqual(len(self.auditorias("cancelamento_parcial")), 1)

    def test_recarga_do_prepago_nao_conta_como_pagamento_de_item(self):
        self.banco.cfg_set("usar_prepago", "S")
        self.banco.cfg_set("cobra_servico_comanda", "N")
        vid, _ = self.caixa.abrir_mesa(15, comanda=True)
        self.caixa.recarregar(vid, self.tipo("Dinheiro"), 5000)
        self.caixa.adicionar_item(vid, self.skol, 4)
        self.caixa.cancelar_item(self.caixa.itens(vid)[0]["id"], "devolveu", quantidade=3)
        self.assertEqual(self.caixa.saldo_prepago(vid)["saldo"], 4200)

    def test_item_pago_por_item_so_cancela_a_parte_livre(self):
        vid = self.vender((self.skol, 5))
        item = self.caixa.itens(vid)[0]["id"]
        pid = self.caixa.pagar_itens(vid, self.tipo("Pix"), [(item, 2)])
        with self.assertRaisesRegex(ErroNegocio, "até 3"):
            self.caixa.cancelar_item(item)
        with self.assertRaisesRegex(ErroNegocio, "até 3"):
            self.caixa.cancelar_item(item, "x", quantidade=4)
        self.caixa.cancelar_item(item, "x", quantidade=3)
        self.assertEqual(self.caixa.itens(vid)[0]["quantidade"], 2)
        with self.assertRaisesRegex(ErroNegocio, "Remova o pagamento"):
            self.caixa.cancelar_item(item, "x", quantidade=1)
        self.caixa.remover_pagamento(pid)
        self.caixa.cancelar_item(item)                                         # liberado: cancela inteiro
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 0)

    def test_venda_fechada_e_caderneta_fechada_nao_mudam(self):
        vid = self.vender((self.skol, 5))
        self.pagar(vid, "Dinheiro", 4000)
        self.caixa.fechar(vid)
        item = self.caixa.itens(vid)[0]["id"]
        with self.assertRaisesRegex(ErroNegocio, "encerrada"):
            self.caixa.cancelar_item(item, "x", quantidade=1)
        cli = self.cliente("ANA", limite=100000)
        cad = self.caixa.abrir_caderneta(cli)
        self.caixa.adicionar_item(cad, self.skol, 3)
        self.caixa.fechar(cad)
        saldo = self.banco.valor("SELECT saldo_cent FROM clientes WHERE id = ?", (cli,))
        with self.assertRaisesRegex(ErroNegocio, "encerrada"):
            self.caixa.cancelar_item(self.caixa.itens(cad)[0]["id"], "x", quantidade=1)
        self.assertEqual(self.banco.valor("SELECT saldo_cent FROM clientes WHERE id = ?", (cli,)), saldo)
        self.assertEqual(len(self.linhas(vid)) + len(self.linhas(cad)), 2)

    def test_caderneta_aberta_cancela_parcial_sem_mexer_no_saldo(self):
        cli = self.cliente("BIA", limite=100000)
        cad = self.caixa.abrir_caderneta(cli)
        self.caixa.adicionar_item(cad, self.skol, 3)
        self.caixa.cancelar_item(self.caixa.itens(cad)[0]["id"], "x", quantidade=1)
        self.assertEqual(self.banco.valor("SELECT saldo_cent FROM clientes WHERE id = ?", (cli,)), 0)
        self.caixa.fechar(cad)
        self.assertEqual(self.banco.valor("SELECT saldo_cent FROM clientes WHERE id = ?", (cli,)), -1600)

    def test_falha_no_meio_desfaz_tudo(self):
        vid = self.vender((self.skol, 5))
        antes = self.linhas(vid)
        with patch.object(self.banco, "registrar_auditoria", side_effect=RuntimeError("disco cheio")):
            with self.assertRaises(RuntimeError):
                self.caixa.cancelar_item(antes[0]["id"], "x", quantidade=2)
        self.assertEqual(self.linhas(vid), antes)
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 4000)

    def test_estoque_baixa_so_o_que_ficou(self):
        vid = self.vender((self.skol, 5))
        self.caixa.cancelar_item(self.caixa.itens(vid)[0]["id"], "x", quantidade=2)
        self.pagar(vid, "Dinheiro", 2400)
        self.caixa.fechar(vid)
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 97)

    def test_sem_tabela_de_vinculos_o_cancelamento_funciona(self):
        self.banco.conexao.executescript("DROP TABLE pagamentos_itens;")
        vid = self.vender((self.skol, 5))
        self.caixa.cancelar_item(self.caixa.itens(vid)[0]["id"], "x", quantidade=2)
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 2400)
