"""Regras do caixa e dos cadastros corrigidas na revisão: divisão de item, quantidade, conferência da gaveta,
parcelas da compra, número de cliente e busca sem acento."""
from __future__ import annotations

import unittest

from src.controllers.cadastro_controller import CadastroController
from src.controllers.caderneta_controller import CadernetaController
from src.controllers.caixa_controller import CaixaController
from src.controllers.contas_controller import ContasController
from src.controllers.estoque_controller import EstoqueController
from src.controllers.produto_controller import ProdutoController
from src.controllers.turno_controller import TurnoController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from tests.base import BaseTeste


class BaseRegras(BaseTeste):
    def setUp(self):
        super().setUp()
        self.adm = self.operador_adm()
        self.turnos = TurnoController(self.banco)
        self.turno = self.turnos.abrir(self.adm, 1, 10000)
        self.caixa = CaixaController(self.banco, self.adm)
        self.cad = CadastroController(self.banco)

    def vender(self, produto, qtd, pagamentos):
        """Fecha uma venda de balcão. `pagamentos` = [(forma, valor_cent), ...]."""
        v = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(v, produto, qtd)
        for forma, valor in pagamentos:
            self.caixa.adicionar_pagamento(v, self.tipo(forma), valor)
        return self.caixa.fechar(v)


class TesteDividirItemDaMesa(BaseRegras):
    def somas(self):
        r = self.banco.um("SELECT SUM(total_cent) AS t, SUM(comissao_cent) AS c FROM itens_venda")
        return r["t"], r["c"]

    def test_transferencia_parcial_nao_duplica_a_comissao_nem_o_total(self):
        cerveja = self.novo_produto("SKOL", 1000, comissao_pct="10")
        mesa, _ = self.caixa.abrir_mesa(1)
        item = self.caixa.adicionar_item(mesa, cerveja, 10)
        self.assertEqual(self.somas(), (10000, 1000))
        self.caixa.transferir_item(item, 2, 4)
        self.assertEqual(self.somas(), (10000, 1000))
        itens = [dict(r) for r in self.banco.todos("SELECT quantidade, total_cent, comissao_cent FROM itens_venda ORDER BY id")]
        self.assertEqual(itens, [{"quantidade": 6, "total_cent": 6000, "comissao_cent": 600},
                                 {"quantidade": 4, "total_cent": 4000, "comissao_cent": 400}])

    def test_fracao_nao_perde_nem_cria_centavo(self):
        pao = self.novo_produto("PAO KG", 5, aceita_decimal="S", comissao_pct="50")
        mesa, _ = self.caixa.abrir_mesa(1)
        item = self.caixa.adicionar_item(mesa, pao, 0.5)               # 5 x 0,5 = 2,5 -> 3 centavos
        antes = self.somas()
        self.caixa.transferir_item(item, 2, 0.25)                       # cada metade, sozinha, daria 1 centavo
        self.assertEqual(self.somas(), antes)
        self.assertEqual(self.banco.valor("SELECT SUM(total_cent) FROM vendas WHERE modalidade = 'mesa'"),
                         self.banco.valor("SELECT SUM(subtotal_cent) FROM vendas WHERE modalidade = 'mesa'"))


class TesteQuantidade(BaseRegras):
    def test_para_qtd_recusa_valores_nao_finitos(self):
        for texto in ("nan", "NaN", "inf", "-inf", "1e999", "infinity"):
            with self.subTest(texto=texto):
                with self.assertRaises(ValueError):
                    fmt.para_qtd(texto)
        self.assertEqual((fmt.para_qtd("1,5"), fmt.para_qtd("2"), fmt.para_qtd("")), (1.5, 2.0, 0.0))

    def test_adicionar_item_barra_codigo_de_barras_no_campo_quantidade(self):
        skol = self.novo_produto("SKOL", 800)
        venda = self.caixa.abrir_balcao()
        with self.assertRaisesRegex(ErroNegocio, "código de barras"):
            self.caixa.adicionar_item(venda, skol, 7891234567890)
        for ruim in (float("nan"), float("inf"), 0, -1):
            with self.subTest(qtd=ruim):
                with self.assertRaises(ErroNegocio):
                    self.caixa.adicionar_item(venda, skol, ruim)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda"), 0)
        self.caixa.adicionar_item(venda, skol, 99999)                  # exatamente no teto
        self.assertEqual(self.banco.valor("SELECT quantidade FROM itens_venda"), 99999)

    def test_teto_e_configuravel_e_zero_desliga(self):
        skol = self.novo_produto("SKOL", 800)
        venda = self.caixa.abrir_balcao()
        self.banco.cfg_set("qtd_maxima_item", "10")
        with self.assertRaises(ErroNegocio):
            self.caixa.adicionar_item(venda, skol, 11)
        self.caixa.adicionar_item(venda, skol, 10)
        self.banco.cfg_set("qtd_maxima_item", "0")
        self.caixa.adicionar_item(venda, skol, 1_000_000)


class TesteConferenciaDaGaveta(BaseRegras):
    def test_cartao_e_pix_nao_entram_no_esperado_da_gaveta(self):
        skol = self.novo_produto("SKOL", 1000)
        self.vender(skol, 3, [("Dinheiro", 1000), ("Pix", 2000)])
        self.turnos.movimentar(self.turno, self.adm, "saida", 300, "gelo")
        r = self.turnos.resumo(self.turno)
        self.assertEqual((r["total_recebido"], r["esperado"], r["fora_da_gaveta"]), (3000, 10000 + 1000 - 300, 2000))
        res = self.turnos.fechar(self.turno, self.adm, 10000 + 1000 - 300)     # o que de fato está na gaveta
        self.assertEqual((res["resultado"], res["esperado"]), (0, 10700))

    def test_forma_nova_fica_na_gaveta_por_padrao_e_pode_ficar_fora(self):
        skol = self.novo_produto("SKOL", 1000)
        self.cad.salvar("tipos_pagamento", {"tipo": "Voucher Digital", "na_gaveta": "N"})
        self.cad.salvar("tipos_pagamento", {"tipo": "Vale Papel"})                  # padrão: fica na gaveta
        self.cad.salvar("tipos_pagamento", {"tipo": "Ticket"})
        self.vender(skol, 1, [("Voucher Digital", 1000)])
        self.vender(skol, 1, [("Vale Papel", 1000)])
        self.vender(skol, 1, [("Ticket", 1000)])
        r = self.turnos.resumo(self.turno)
        self.assertEqual((r["esperado"], r["fora_da_gaveta"]), (10000 + 2000, 1000))

    def test_sobra_e_falta_seguem_o_valor_declarado_da_gaveta(self):
        skol = self.novo_produto("SKOL", 1000)
        self.vender(skol, 2, [("Dinheiro", 2000)])
        self.vender(skol, 1, [("Cartão Débito", 1000)])
        self.assertEqual(self.turnos.fechar(self.turno, self.adm, 12000 - 500)["resultado"], -500)

    def test_sementes_marcam_cartao_e_pix_fora_da_gaveta(self):
        formas = {r["tipo"]: r["na_gaveta"] for r in self.banco.todos("SELECT tipo, na_gaveta FROM tipos_pagamento")}
        self.assertEqual(formas, {"Dinheiro": 1, "Cartão Débito": 0, "Cartão Crédito": 0, "Pix": 0})

    def test_so_dinheiro_debito_credito_e_pix_aparecem_como_formas_de_pagamento(self):
        self.assertEqual([f["tipo"] for f in self.caixa.formas_pagamento()],
                         ["Dinheiro", "Cartão Débito", "Cartão Crédito", "Pix"])

    def test_banco_antigo_perde_cheque_ticket_e_contra_vale_uma_vez_so(self):
        from src.database import sementes
        for i, nome in enumerate(sementes.FORMAS_APOSENTADAS):                       # como estava em um banco antigo
            self.banco.executar("INSERT INTO tipos_pagamento(tipo, ordem) VALUES (?, ?)", (nome, 10 + i))
        self.banco.executar("INSERT INTO tipos_pagamento(tipo, ordem) VALUES ('Voucher', 20)")
        self.banco.executar("DELETE FROM config WHERE chave = 'formas_pagamento_enxutas'")
        sementes.aplicar(self.banco)
        ativas = [r["tipo"] for r in self.banco.todos("SELECT tipo FROM tipos_pagamento WHERE ativo = 1 ORDER BY ordem")]
        self.assertEqual(ativas, ["Dinheiro", "Cartão Débito", "Cartão Crédito", "Pix", "Voucher"])    # a do dono fica
        self.banco.executar("UPDATE tipos_pagamento SET ativo = 1 WHERE tipo = 'Cheque'")             # o dono reativou
        sementes.aplicar(self.banco)
        self.assertEqual(self.banco.valor("SELECT ativo FROM tipos_pagamento WHERE tipo = 'Cheque'"), 1)


class TesteParcelasDaCompra(BaseRegras):
    def compra(self, total_cent):
        if not hasattr(self, "_fornecedor"):
            self._fornecedor = self.cad.salvar("fornecedores", {"nome": "AMBEV"})
            self._produto = self.novo_produto("SKOL", 1000, estoque=True)
        est = EstoqueController(self.banco, self.adm)
        lanc = est.criar_lancamento("compra", fornecedor_id=self._fornecedor)
        est.adicionar_item(lanc, self._produto, 10, valor_cent=total_cent)
        return lanc

    def valores(self, ids):
        return [self.banco.valor("SELECT valor_cent FROM contas WHERE id = ?", (i,)) for i in ids]

    def test_compra_parcelada_divide_o_total_e_a_sobra_vai_na_primeira(self):
        contas = ContasController(self.banco, self.adm)
        ids = contas.criar_da_compra(self.compra(10000), "2026-11-10", self.tipo("Dinheiro"), meses=3)
        self.assertEqual(self.valores(ids), [3334, 3333, 3333])
        self.assertEqual([self.banco.valor("SELECT dt_vencimento FROM contas WHERE id = ?", (i,)) for i in ids],
                         ["2026-11-10", "2026-12-10", "2027-01-10"])
        self.assertEqual([self.banco.valor("SELECT parcela FROM contas WHERE id = ?", (i,)) for i in ids], ["1/3", "2/3", "3/3"])

    def test_sem_parcelas_ou_com_dividir_falso_mantem_o_comportamento_antigo(self):
        contas = ContasController(self.banco, self.adm)
        self.assertEqual(self.valores(contas.criar_da_compra(self.compra(30000), "2026-11-10", self.tipo("Dinheiro"))), [30000])
        lanc = self.compra(30000)
        ids = contas.criar_da_compra(lanc, "2026-11-10", self.tipo("Dinheiro"), meses=2, dividir=False)
        self.assertEqual(self.valores(ids), [30000, 30000])

    def test_conta_mensal_continua_repetindo_o_valor(self):
        contas = ContasController(self.banco, self.adm)
        sub = self.banco.valor("SELECT id FROM subplanos LIMIT 1")
        ids = contas.incluir(sub, "Aluguel", self.tipo("Dinheiro"), 250000, "2026-11-10", meses=3)
        self.assertEqual(self.valores(ids), [250000] * 3)

    def test_valor_pequeno_demais_para_dividir(self):
        contas = ContasController(self.banco, self.adm)
        lanc = self.compra(2)
        with self.assertRaisesRegex(ErroNegocio, "pequeno demais"):
            contas.criar_da_compra(lanc, "2026-11-10", self.tipo("Dinheiro"), meses=3)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM contas"), 0)


class TesteNumeroDoCliente(BaseRegras):
    def test_sugestao_usa_o_maior_numero_e_nao_a_contagem(self):
        ids = [self.cad.salvar("clientes", {"numero_consulta": n, "nome": f"C{n}"}) for n in ("000001", "000002", "000003")]
        self.cad.excluir("clientes", ids[1])
        sugerido = self.cad.valores_iniciais("clientes")["numero_consulta"]
        self.assertEqual(sugerido, "000004")
        self.cad.salvar("clientes", {"numero_consulta": sugerido, "nome": "Novo"})          # não colide

    def test_numeros_com_letras_sao_ignorados(self):
        self.cad.salvar("clientes", {"numero_consulta": "VIP-9", "nome": "Vip"})
        self.assertEqual(self.cad.valores_iniciais("clientes")["numero_consulta"], "000001")
        self.cad.salvar("clientes", {"numero_consulta": "12", "nome": "Doze"})
        self.assertEqual(self.cad.valores_iniciais("clientes")["numero_consulta"], "000013")


class TesteBuscaSemAcento(BaseRegras):
    def setUp(self):
        super().setUp()
        for nome in ("Café Expresso", "Pão de Queijo", "Açaí 300ml", "SKOL"):
            self.novo_produto(nome, 500)
        self.cad.salvar("clientes", {"numero_consulta": "1", "nome": "João da Silva", "telefone": "11 9999"})
        self.cad.salvar("clientes", {"numero_consulta": "2", "nome": "MARIA"})

    def nomes(self, texto):
        return [p["nome"] for p in ProdutoController(self.banco).pesquisar(texto)]

    def test_produto_acha_com_ou_sem_acento_em_qualquer_caixa(self):
        for texto in ("café", "CAFÉ", "cafe", "CAFE", "Cafe E"):
            self.assertEqual(self.nomes(texto), ["Café Expresso"], texto)
        for texto in ("pao", "PÃO", "pão"):
            self.assertEqual(self.nomes(texto), ["Pão de Queijo"], texto)
        self.assertEqual(self.nomes("acai"), ["Açaí 300ml"])
        self.assertEqual(self.nomes("skol"), ["SKOL"])
        self.assertEqual(self.nomes("xyz"), [])

    def test_prefixo_vem_antes_do_meio_da_palavra(self):
        self.novo_produto("Cafezinho", 300)
        self.novo_produto("Descafeinado", 300)
        self.assertEqual(self.nomes("cafe"), ["Cafezinho", "Café Expresso", "Descafeinado"])

    def test_cliente_na_caderneta_e_no_cadastro(self):
        cc, cad = CadernetaController(self.banco), self.cad
        for texto in ("joão", "JOÃO", "joao", "JOAO"):
            self.assertEqual([c["nome"] for c in cc.buscar(texto)], ["João da Silva"], texto)
            self.assertEqual([c["nome"] for c in cad.listar("clientes", texto)], ["João da Silva"], texto)
        self.assertEqual([c["nome"] for c in cc.buscar("maria")], ["MARIA"])
        self.assertEqual([c["nome"] for c in cc.buscar("1")], ["João da Silva"])      # número de consulta exato

    def test_coringas_do_like_continuam_literais_no_cadastro(self):
        self.assertEqual(self.cad.listar("clientes", "%"), [])
        self.assertEqual(self.cad.listar("clientes", "_"), [])

    def test_busca_de_contas_ignora_acento(self):
        contas = ContasController(self.banco, self.adm)
        sub = self.banco.valor("SELECT id FROM subplanos LIMIT 1")
        contas.incluir(sub, "Manutenção do ar-condicionado", self.tipo("Dinheiro"), 15000, "2026-10-10")
        self.assertEqual(len(contas.listar(texto="manutencao")), 1)
        self.assertEqual(len(contas.listar(texto="MANUTENÇÃO")), 1)
        self.assertEqual(len(contas.listar(texto="aluguel")), 0)


class TesteFechamentoImpresso(BaseRegras):
    def fechar_com(self, pagamentos):
        skol = self.novo_produto("SKOL", 1000)
        self.vender(skol, 3, pagamentos)
        gaveta = sum(v for f, v in pagamentos if f == "Dinheiro")
        return self.turnos.fechar(self.turno, self.adm, 10000 + gaveta)

    def test_texto_mostra_o_que_ficou_fora_da_gaveta(self):
        from src.controllers.impressao_controller import ImpressaoController
        res = self.fechar_com([("Dinheiro", 1000), ("Pix", 2000)])
        texto = ImpressaoController(self.banco).fechamento(res)
        linhas = texto.splitlines()
        self.assertTrue(all(len(l) <= 40 for l in linhas), [l for l in linhas if len(l) > 40])
        self.assertTrue(any(l.startswith("Pix (fora da gaveta)") and l.endswith("20,00") for l in linhas), texto)
        self.assertTrue(any(l.startswith("Dinheiro") and "fora" not in l for l in linhas), texto)
        self.assertTrue(any(l.startswith("  Fora da gaveta (cartão/Pix)") and l.endswith("20,00") for l in linhas), texto)
        esperado = next(l for l in linhas if l.startswith("ESPERADO NA GAVETA"))
        self.assertTrue(esperado.endswith("110,00"), esperado)                 # fundo 100,00 + dinheiro 10,00

    def test_so_dinheiro_nao_mostra_aviso_de_fora_da_gaveta(self):
        from src.controllers.impressao_controller import ImpressaoController
        res = self.fechar_com([("Dinheiro", 3000)])
        texto = ImpressaoController(self.banco).fechamento(res)
        self.assertNotIn("fora da gaveta", texto.lower())
        self.assertNotIn("*", texto)

    def test_resumo_antigo_sem_o_campo_novo_ainda_imprime(self):
        from src.controllers.impressao_controller import ImpressaoController
        res = self.fechar_com([("Dinheiro", 3000)])
        res.pop("fora_da_gaveta")
        for r in res["recebimentos"]:
            r.pop("na_gaveta")
        self.assertIn("FECHAMENTO DE TURNO", ImpressaoController(self.banco).fechamento(res))


if __name__ == "__main__":
    unittest.main()
