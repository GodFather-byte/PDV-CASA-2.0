"""Recorte de compras, consumo histórico e classificação indicativa da Adega."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from uuid import uuid4

from src.controllers.estoque_controller import EstoqueController
from src.controllers.produto_controller import ProdutoController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio
from tests.base import BaseTeste



class TesteMelhoriasEstoqueAdega(BaseTeste):
    def setUp(self):
        super().setUp()
        self.est = EstoqueController(self.banco, self.operador_adm())
        self.prod = ProdutoController(self.banco)
        self.fornecedor = self.banco.inserir("fornecedores", {"nome": "DISTRIBUIDORA"})

    def produto(self, nome="CERVEJA TESTE", qt=5, minimo=10, **kw):
        pid = self.novo_produto(nome, estoque=True, qt=qt, **kw)
        self.banco.executar("UPDATE produtos SET estoque_minimo = ? WHERE id = ?", (minimo, pid))
        return pid

    def categoria(self, grupo, subgrupo):
        gid = self.banco.inserir("grupos", {"nome": grupo})
        return self.banco.inserir("subgrupos", {"nome": subgrupo, "grupo_id": gid})

    def movimento(self, pid, quantidade, tipo="venda", dias=0, segundos=0, ref_tipo="venda"):
        data = self._hora["t"] + timedelta(days=dias, seconds=segundos)
        self.banco.inserir("movimentos_estoque", {
            "produto_id": pid, "tipo": tipo, "quantidade": quantidade, "qt_apos": 5,
            "ref_tipo": ref_tipo, "criado_em": data.strftime("%Y-%m-%d %H:%M:%S"),
        })

    def test_pedido_e_lista_adega_combinam_todos_os_filtros_sem_alterar_geral(self):
        sub = self.categoria("Bebidas da loja", "Cervejas")
        alvo = self.produto("CERVEJA ALVO", subgrupo_id=sub)
        self.produto("CERVEJA OUTRA", subgrupo_id=sub)
        self.produto("CERVEJA ALVO DE OUTRO GRUPO")
        self.produto("CERVEJA ALVO NORMAL", qt=30, subgrupo_id=sub)
        zerado = self.produto("CERVEJA ALVO SEM ESTOQUE", qt=0, subgrupo_id=sub)
        fora = self.produto("SABONETE", qt=0)
        recorte = {"adega": True, "situacao": "ponto", "texto": "alvo", "grupo": "Bebidas da loja"}
        self.assertEqual([p["id"] for p in self.est.lista_de_compras(**recorte)], [alvo])
        geral = self.est.lista_de_compras()
        self.assertEqual(len(geral), 5)
        self.assertIn(fora, [p["id"] for p in geral])
        self.assertEqual([p["id"] for p in self.est.lista_de_compras(
            **{**recorte, "situacao": "sem"})], [zerado])
        pedido = self.est.pedido_sugerido(self.fornecedor, **recorte)
        self.assertEqual([(p["produto_id"], p["quantidade"]) for p in self.est.itens(pedido)], [(alvo, 15)])
        self.assertEqual(self.prod.por_id(alvo)["qt_atual"], 5)
        self.assertEqual(self.est.historico(alvo), [])
        self.assertEqual(self.est.lista_de_compras(), geral)
        self.assertIn("Adega", self.est.lancamento(pedido)["descricao"])

    def test_recorte_vazio_nao_cai_no_pedido_geral_e_lista_nao_grava(self):
        self.produto("SABONETE", qt=0)
        self.assertEqual(self.est.lista_de_compras(adega=True), [])
        with self.assertRaises(ErroNegocio):
            self.est.pedido_sugerido(self.fornecedor, adega=True)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_estoque"), 0)
        self.assertEqual(len(self.est.itens(self.est.pedido_sugerido(self.fornecedor))), 1)

    def test_produtos_explicitos_nao_escapam_do_recorte_adega(self):
        self.produto()
        fora = self.produto("SABONETE")
        with self.assertRaisesRegex(ErroNegocio, "recorte"):
            self.est.pedido_sugerido(self.fornecedor, [(fora, 1)], adega=True)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 0)
        pedido = self.est.pedido_sugerido(self.fornecedor, [(fora, 1)])
        self.assertEqual(self.est.itens(pedido)[0]["produto_id"], fora)

    def test_compras_excluem_inativos_sem_minimo_sem_controle_e_saldo_normal(self):
        alvo = self.produto(qt=0)
        self.produto("VINHO SEM MINIMO", qt=0, minimo=0)
        self.produto("VINHO NORMAL", qt=30)
        inativo = self.produto("VINHO INATIVO", qt=0)
        self.banco.executar("UPDATE produtos SET ativo = 0 WHERE id = ?", (inativo,))
        self.novo_produto("VINHO LIVRE")
        self.assertEqual([p["id"] for p in self.est.lista_de_compras(adega=True, texto="")], [alvo])
        self.assertEqual(self.est.lista_de_compras(adega=True, situacao="livre"), [])
        self.assertEqual(self.est.lista_de_compras(adega=True, situacao="normal"), [])

    def test_cobertura_janela_exata_30_dias_estornos_e_movimentos_ignorados(self):
        pid = self.produto(qt=20)
        self.movimento(pid, -20, dias=-30)
        self.movimento(pid, -15)
        self.movimento(pid, 5, tipo="estorno_venda")
        self.movimento(pid, -500, dias=-30, segundos=-1)
        self.movimento(pid, -500, segundos=1)
        for tipo in ("quebra", "saida", "descarte", "oxidacao", "devolucao", "entrada",
                     "compra", "contagem", "estorno"):
            self.movimento(pid, -100, tipo=tipo)
        self.movimento(pid, -100, ref_tipo="item_estoque")
        p = self.est.painel(adega=True)[0]
        self.assertEqual(p["consumo_30_dias"], 30)
        self.assertEqual(p["media_diaria"], 1)
        self.assertEqual(p["cobertura_dias"], 20)
        self.assertEqual(p["cobertura_rotulo"], "20,0 dias")
        self.assertEqual(p["repor"], 0)  # Cobertura não altera a regra de reposição.

    def test_cobertura_sem_consumo_ou_estorno_excedente_tem_fallback_seguro(self):
        pid = self.produto(qt=5)
        for movimentos in ([], [(-5, "venda"), (5, "estorno_venda")], [(10, "estorno_venda")]):
            self.banco.executar("DELETE FROM movimentos_estoque")
            for qtd, tipo in movimentos:
                self.movimento(pid, qtd, tipo=tipo)
            p = self.est.painel(adega=True)[0]
            self.assertEqual(p["consumo_30_dias"], 0)
            self.assertEqual(p["media_diaria"], 0)
            self.assertIsNone(p["cobertura_dias"])
            self.assertIn("Sem consumo", p["cobertura_rotulo"])
            self.assertEqual(p["repor"], 15)

    def test_historico_curto_divide_por_30_saldo_negativo_e_sem_controle(self):
        pid = self.produto(qt=2)
        self.movimento(pid, -0.5)
        p = self.est.painel(adega=True)[0]
        self.assertAlmostEqual(p["media_diaria"], 0.5 / 30)
        self.assertEqual(p["cobertura_dias"], 120)
        for saldo in (0, -1):
            self.banco.executar("UPDATE produtos SET qt_atual = ? WHERE id = ?", (saldo, pid))
            self.assertEqual(self.est.painel(adega=True)[0]["cobertura_dias"], 0)
        self.banco.executar("UPDATE produtos SET controla_estoque = 0 WHERE id = ?", (pid,))
        p = self.est.painel("livre", adega=True)[0]
        self.assertIsNone(p["cobertura_dias"])
        self.assertEqual(p["cobertura_rotulo"], "Sem controle")
        self.assertEqual(p["repor"], 0)

    def test_estorno_de_venda_fora_da_janela_nao_inventa_consumo(self):
        pid = self.produto()
        self.movimento(pid, -30, dias=-31)
        self.movimento(pid, 30, tipo="estorno_venda")
        self.assertIsNone(self.est.painel(adega=True)[0]["cobertura_dias"])

    def test_venda_de_fardo_e_composicao_soma_unidades_sem_dupla_contagem(self):
        pid = self.produto(qt=60)
        fardo = self.prod.criar_embalagem(pid, 12, "CERVEJA FARDO", 9000)
        composto = self.novo_produto("COMBO", 1000)
        self.prod.incluir_composicao(composto, pid, 0.5)
        venda = self.banco.inserir("vendas", {"uuid": str(uuid4()), "aberta_em": fmt.agora()})
        for produto, quantidade in ((pid, 2), (fardo, 2), (composto, 2)):
            self.banco.inserir("itens_venda", {
                "venda_id": venda, "produto_id": produto, "quantidade": quantidade,
                "preco_unit_cent": 1000, "total_cent": 1000 * quantidade, "criado_em": fmt.agora()})
        self.est.baixar_venda(venda)
        linhas = self.est.painel(adega=True)
        self.assertEqual([p["id"] for p in linhas], [pid])
        self.assertEqual(linhas[0]["consumo_30_dias"], 27)
        self.assertAlmostEqual(linhas[0]["cobertura_dias"], 33 / (27 / 30))
        self.est.estornar_venda(venda)
        self.assertIsNone(self.est.painel(adega=True)[0]["cobertura_dias"])

    def test_classificacao_normaliza_grupo_subgrupo_e_familias_sem_mudar_geral(self):
        ids = []
        for grupo, categoria in (
                ("  bEbÍdAs / balcão  ", "Outros"), ("Loja A", " cerveja — long-neck "),
                ("Loja B", "VINHOS/ESPUMANTES"), ("Loja C", "Águas & Sucos"),
                ("  ConVenIÊncIa  ", "Petiscos"), ("Loja D", "Whisky importado"),
                ("Loja E", "GELO + CARVÃO")):
            sub = self.categoria(grupo, categoria)
            ids.append(self.produto("ITEM " + str(len(ids)), subgrupo_id=sub))
        fora = self.produto("SABONETE")
        self.assertEqual({p["id"] for p in self.est.painel(adega=True)}, set(ids))
        self.assertEqual({p["id"] for p in self.est.painel()}, {*ids, fora})
        self.assertTrue(all(p["classificacao_adega"] == "Família do grupo/subgrupo"
                            for p in self.est.painel(adega=True)))

    def test_nome_e_prefixo_indicativo_sem_marcas_ou_fragmentos(self):
        dentro = [self.produto(nome) for nome in (
            "  cErVeJa — artesanal", "ÁGUA MINERAL 500 ML", "Gin London", "CARVÃO VEGETAL 5KG")]
        for nome in ("GINÁSTICA", "GENGIBRE", "GINGER", "AGUARDENTE", "SUCOSE",
                     "VINHOTECA", "SABONETE DE CERVEJA", "ÁGUA SANITÁRIA", "SKOL", "MANGINHA"):
            self.produto(nome)
        linhas = self.est.painel(adega=True)
        self.assertEqual({p["id"] for p in linhas}, set(dentro))
        self.assertTrue(all(p["classificacao_adega"] == "Nome indicativo" for p in linhas))

    def test_grupo_e_subgrupo_nao_classificam_por_substring(self):
        for indice, (grupo, categoria) in enumerate((
                ("AGUARDENTES", "OUTROS"), ("LOJA A", "GINGER E GENGIBRE"),
                ("GINASTICA", "ARTIGOS"), ("LOJA B", "VINHOTECA"),
                ("BEBIDASCASEIRAS", "ADEGADOS"), ("LOJA C", "SUCOSE"))):
            sub = self.categoria(grupo, categoria)
            self.produto(f"ITEM PERSONALIZADO {indice}", subgrupo_id=sub)
        self.assertEqual(self.est.painel(adega=True), [])
        self.assertEqual(len(self.est.painel()), 6)

    def test_grupo_adega_marca_explicitamente_nome_nao_reconhecido(self):
        sub = self.categoria("  AdÉga  ", "MARCA PERSONALIZADA")
        pid = self.produto("AGUARDENTE ARTESANAL", subgrupo_id=sub)
        p = self.est.painel(adega=True)[0]
        self.assertEqual(p["id"], pid)
        self.assertEqual(p["classificacao_adega"], "Família do grupo/subgrupo")
        self.assertEqual((p["preco_gelada_cent"], p["atacado_qtd"], p["atacado_gelada_qtd"]), (0, 0, 0))
        self.assertIsNone(p["casco_produto_id"])
        self.banco.executar("UPDATE grupos SET nome = 'OUTROS' WHERE id = "
                            "(SELECT grupo_id FROM subgrupos WHERE id = ?)", (sub,))
        self.assertEqual(self.est.painel(adega=True), [])
        self.assertEqual(self.est.painel()[0]["id"], pid)

    def test_sinais_configurados_e_cascos_vinculados_continuam_incluidos(self):
        ids = [self.produto("ITEM " + str(i)) for i in range(6)]
        self.banco.executar("UPDATE produtos SET preco_gelada_cent = 500 WHERE id = ?", (ids[0],))
        self.banco.executar("UPDATE produtos SET atacado_qtd = 6 WHERE id = ?", (ids[1],))
        self.banco.executar("UPDATE produtos SET atacado_gelada_qtd = 6 WHERE id = ?", (ids[2],))
        self.banco.executar("UPDATE produtos SET casco_produto_id = ? WHERE id = ?", (ids[4], ids[3]))
        self.assertEqual({p["id"] for p in self.est.painel(adega=True)}, set(ids[:5]))

    def test_consulta_agregada_sem_n_mais_um_nem_escrita(self):
        def consultar():
            consultas = []
            self.banco.conexao.set_trace_callback(consultas.append)
            try:
                self.est.painel(adega=True)
            finally:
                self.banco.conexao.set_trace_callback(None)
            self.assertTrue(all(c.lstrip().upper().startswith("SELECT") for c in consultas))
            return consultas

        self.produto()
        inicial = consultar()
        for i in range(25):
            self.produto("CERVEJA " + str(i))
        ampliada = consultar()
        self.assertEqual(len(ampliada), len(inicial))
        self.assertEqual(len(ampliada), 2)
        self.assertEqual(sum("SUM(quantidade)" in c for c in ampliada), 1)

    def test_cadastro_legado_com_defaults_e_historico_antigo_mantem_fallback(self):
        sub = self.categoria("  Adega / antiga  ", "Importados")
        unidade = self.banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'")
        pid = self.banco.inserir("produtos", {
            "codigo": "LEGADO", "nome": "ITEM ANTIGO", "subgrupo_id": sub, "unidade_id": unidade,
            "controla_estoque": 1, "qt_atual": 3, "estoque_minimo": 5})
        self.movimento(pid, -100, dias=-365)
        # Histórico sem referência confiável não deve fabricar uma média de vendas.
        self.movimento(pid, -50, ref_tipo=None)
        p = self.est.painel(adega=True)[0]
        self.assertIsNone(p["cbarra"])
        self.assertIsNone(p["ult_atualizacao"])
        self.assertEqual(p["preco_gelada_cent"], 0)
        self.assertEqual(p["atacado_qtd"], 0)
        self.assertIsNone(p["casco_produto_id"])
        self.assertEqual(p["classificacao_adega"], "Família do grupo/subgrupo")
        self.assertEqual(p["valor_cent"], 0)
        self.assertEqual(p["consumo_30_dias"], 0)
        self.assertIsNone(p["cobertura_dias"])
        self.assertEqual(p["repor"], 7)
        compras = self.est.lista_de_compras(adega=True)
        self.assertEqual([(i["id"], i["repor"]) for i in compras], [(pid, 7)])
        self.assertNotIn("cobertura_dias", compras[0])
        pedido = self.est.pedido_sugerido(self.fornecedor, adega=True)
        self.assertEqual(self.est.itens(pedido)[0]["quantidade"], 7)
        self.assertEqual(self.prod.por_id(pid)["qt_atual"], 3)

    def test_legado_sem_minimo_e_nome_customizado_continua_disponivel_em_geral(self):
        pid = self.produto("MARCA ANTIGA PERSONALIZADA", qt=-1, minimo=0)
        self.assertEqual(self.est.painel(adega=True), [])
        geral = self.est.painel(texto="marca antiga")[0]
        self.assertEqual(geral["id"], pid)
        self.assertEqual(geral["situacao"], "sem")
        self.assertEqual(geral["repor"], 0)
        self.assertEqual(self.est.lista_de_compras(), [])
        self.assertNotIn("cobertura_dias", geral)

    def massa_produtos(self, quantidade=5000):
        """Carga sintética mínima: metade bebidas, metade outros produtos."""
        sub = self.banco.valor("SELECT id FROM subgrupos LIMIT 1")
        unidade = self.banco.valor("SELECT id FROM unidades WHERE abreviatura = 'UN'")
        with self.banco.transacao():
            self.banco.conexao.executemany(
                """INSERT INTO produtos (codigo, nome, subgrupo_id, unidade_id,
                                         controla_estoque, qt_atual, estoque_minimo)
                   VALUES (?, ?, ?, ?, 1, 5, 10)""",
                [(f"MASSA{i}", f"{'CERVEJA' if i % 2 == 0 else 'SABONETE'} {i:05}",
                  sub, unidade) for i in range(quantidade)])
            self.banco.executar(
                """INSERT INTO movimentos_estoque
                   (produto_id, tipo, quantidade, qt_apos, ref_tipo, criado_em)
                   SELECT id, 'venda', -30, 5, 'venda', ? FROM produtos""", (fmt.agora(),))

    def test_massa_5000_produtos_com_historico_mantem_consultas_constantes_e_somente_leitura(self):
        self.massa_produtos()
        consultas = []
        self.banco.conexao.set_trace_callback(consultas.append)
        try:
            painel = self.est.painel(adega=True)
            resumo = self.est.resumo(adega=True)
            compras = self.est.lista_de_compras(adega=True)
        finally:
            self.banco.conexao.set_trace_callback(None)
        self.assertEqual(len(painel), 2500)
        self.assertEqual(resumo["total"], 2500)
        self.assertEqual(resumo["ponto"], 2500)
        self.assertEqual(resumo["livre"], 0)
        self.assertEqual(len(compras), 2500)
        self.assertTrue(all(p["cobertura_dias"] == 5 and p["repor"] == 15 for p in painel))
        self.assertEqual(len(consultas), 5)  # Painel: 2; resumo: 2; compras: 1.
        self.assertEqual(sum("SUM(quantidade)" in c for c in consultas), 1)
        self.assertTrue(all(c.lstrip().upper().startswith("SELECT") for c in consultas))
        self.assertEqual(len(self.est.painel()), 5000)

    def test_resumo_lista_e_pedido_nao_consultam_consumo_historico(self):
        self.produto()
        with patch.object(self.est, "_consumo_30_dias", side_effect=AssertionError("Histórico desnecessário")):
            self.assertEqual(self.est.resumo(adega=True)["total"], 1)
            self.assertEqual(len(self.est.lista_de_compras(adega=True)), 1)
            pedido = self.est.pedido_sugerido(self.fornecedor, adega=True)
        self.assertEqual(len(self.est.itens(pedido)), 1)


