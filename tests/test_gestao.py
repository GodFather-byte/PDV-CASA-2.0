"""Contas, configuração, sincronização, utilitários, relatórios e impressão."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from src.controllers.cadastro_controller import CadastroController
from src.controllers.config_controller import ConfigController
from src.controllers.contas_controller import ContasController
from src.controllers.estoque_controller import EstoqueController
from src.controllers.impressao_controller import ImpressaoController
from src.controllers.relatorio_controller import RelatorioController
from src.controllers.utilitario_controller import UtilitarioController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroValidacao
from src.core.relatorio import para_csv, para_texto
from tests.test_caixa import BaseCaixa


class TesteContas(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.contas = ContasController(self.banco, self.adm)
        self.sub = self.banco.valor("SELECT id FROM subplanos WHERE nome = 'Aluguel'")

    def test_conta_mensal_repete_por_n_meses(self):
        ids = self.contas.incluir(self.sub, "Aluguel", self.tipo(), 250000, "31/01/2026", "01/01/2026", meses=3)
        venc = [self.contas.obter(i)["dt_vencimento"] for i in ids]
        self.assertEqual(venc, ["2026-01-31", "2026-02-28", "2026-03-31"])
        self.assertEqual([self.contas.obter(i)["parcela"] for i in ids], ["1/3", "2/3", "3/3"])

    def test_validacoes(self):
        with self.assertRaises(ErroNegocio):
            self.contas.incluir(self.sub, " ", self.tipo(), 100)
        with self.assertRaises(ErroNegocio):
            self.contas.incluir(self.sub, "X", self.tipo(), 0)
        with self.assertRaises(ErroNegocio):
            self.contas.incluir(self.sub, "X", self.tipo(), 100, dt_entrada="10/10/2026", dt_quitacao="09/10/2026")

    def test_quitacao_antes_da_entrada_ou_data_invalida(self):
        cid = self.contas.incluir(self.sub, "X", self.tipo(), 100, "10/10/2026", "05/10/2026")[0]
        with self.assertRaises(ErroNegocio):
            self.contas.quitar(cid, "01/10/2026")
        with self.assertRaises(ErroNegocio):
            self.contas.incluir(self.sub, "Y", self.tipo(), 100, "31/02/2026")
        with self.assertRaises(ErroNegocio):
            self.contas.atualizar(cid, dt_vencimento="xx")
        self.assertIsNone(self.contas.obter(cid)["dt_quitacao"])

    def test_quitar_e_painel(self):
        self.contas.incluir(self.sub, "Vencida", self.tipo(), 100, "01/10/2026", "01/10/2026")
        hoje = self.contas.incluir(self.sub, "Hoje", self.tipo(), 100, "03/10/2026", "01/10/2026")[0]
        self.contas.incluir(self.sub, "Futura", self.tipo(), 100, "10/10/2026", "01/10/2026")
        self.assertEqual(self.contas.painel(), {"anteriores": 1, "hoje": 1})
        self.contas.quitar(hoje)
        self.assertEqual(self.contas.painel()["hoje"], 0)
        self.assertEqual(len(self.contas.listar(quitada=False)), 2)

    def test_transferencia_entre_contas_gera_debito_e_credito(self):
        banco_a, banco_b = self.tipo("Pix"), self.tipo("Cartão Débito")
        self.contas.transferir(banco_a, banco_b, 50000, "03/10/2026")
        extrato = {ln[0]: ln for ln in RelatorioController(self.banco).extrato_contas({"ate": "2026-10-03"}).linhas}
        self.assertEqual(extrato["Pix"][3], "500,00")        # saída
        self.assertEqual(extrato["Cartão Débito"][2], "500,00")     # entrada
        with self.assertRaises(ErroNegocio):
            self.contas.transferir(banco_a, banco_a, 100)

    def test_conta_a_pagar_gerada_pela_compra_nao_duplica(self):
        forn = self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        est = EstoqueController(self.banco, self.adm)
        lid = est.criar_lancamento("compra", fornecedor_id=forn, valor_cent=4800)
        est.adicionar_item(lid, self.skol, 24, 4800)
        ids = self.contas.criar_da_compra(lid, "15/10/2026", self.tipo())
        c = self.contas.obter(ids[0])
        self.assertEqual((c["valor_cent"], c["fornecedor"], c["plano"]), (4800, "AMBEV", "Mercadorias (-)"))
        with self.assertRaises(ErroNegocio):
            self.contas.criar_da_compra(lid, "15/10/2026", self.tipo())


class TesteConfig(BaseCaixa):
    def test_config_valida_e_normaliza(self):
        cfg = ConfigController(self.banco)
        cfg.salvar_config({"num_mesas": "30", "cobra_servico_mesa": "sim", "servico_pct": "12,5"})
        self.assertEqual((self.banco.cfg_int("num_mesas"), self.banco.cfg_bool("cobra_servico_mesa")), (30, True))
        self.assertEqual(float(self.banco.cfg("servico_pct")), 12.5)
        with self.assertRaises(ErroValidacao):
            cfg.salvar_config({"num_mesas": "0"})
        with self.assertRaises(ErroValidacao):
            cfg.salvar_config({"servico_pct": "150"})
        with self.assertRaises(ErroNegocio):
            cfg.salvar_config({"inexistente": "1"})

    def test_mudar_servico_afeta_novas_vendas(self):
        ConfigController(self.banco).salvar_config({"servico_pct": "15"})
        vid, _ = self.caixa.abrir_mesa(1)
        self.caixa.adicionar_item(vid, self.skol, 5)
        self.assertEqual(self.caixa.obter(vid)["servico_cent"], 600)

    def test_loja_e_maquina(self):
        cfg = ConfigController(self.banco)
        cfg.salvar_loja({"nome_fantasia": "Boate X", "uf": "SP"})
        self.assertEqual(cfg.nome_loja(), "Boate X")
        with self.assertRaises(ErroValidacao):
            cfg.salvar_loja({"uf": "SAO"})
        cfg.salvar_maquina({"colunas_fita": "48", "gaveta": "S"})
        m = cfg.maquina()
        self.assertEqual((m["colunas_fita"], m["gaveta"]), (48, 1))
        with self.assertRaises(ErroValidacao):
            cfg.salvar_maquina({"colunas_fita": "10"})


class TesteUtilitarios(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.banco.cfg_set("pasta_backup", self.pasta.name)
        self.util = UtilitarioController(self.banco, self.adm)

    def test_backup_gera_copia_valida_e_poda_antigas(self):
        caminho = self.util.backup(manter=2)
        import sqlite3
        con = sqlite3.connect(caminho)
        self.assertEqual(con.execute("SELECT nome FROM operadores").fetchone()[0], "ADM")
        con.close()
        for _ in range(3):
            self.avancar(seconds=1)
            self.util.backup(manter=2)
        self.assertEqual(len(list(Path(self.pasta.name).glob("loja_offline-*.db"))), 2)
        self.assertEqual(self.util.ultimo_backup(), fmt.agora())

    def _venda_antiga(self, dias_atras):
        self.avancar(days=-dias_atras)
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Dinheiro", 800)
        self.caixa.fechar(vid)
        self.avancar(days=dias_atras)
        return vid

    def test_limpeza_apaga_ate_o_dia_anterior_a_data_informada(self):
        self.turnos.fechar(self.turno, self.adm, 10000)
        self.turno = self.turnos.abrir(self.adm, 2, 0)
        velha = self._venda_antiga(10)
        nova = self._venda_antiga(1)
        corte = fmt.somar_dias(fmt.hoje(), -2)                 # apaga o que for anterior a hoje-2
        res = self.util.limpar_movimento(fmt.fmt_data(corte))
        self.assertEqual(res["vendas"], 1)
        existentes = [r[0] for r in self.banco.todos("SELECT id FROM vendas")]
        self.assertEqual(existentes, [nova])
        self.assertTrue(os.path.exists(res["backup"]))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda WHERE venda_id = ?", (velha,)), 0)

    def test_limpeza_preserva_saldo_da_caderneta(self):
        cid = self.cliente("MARIA")
        self.avancar(days=-5)
        vid = self.caixa.abrir_caderneta(cid)
        self.caixa.adicionar_item(vid, self.skol, 1)
        self.caixa.fechar(vid)
        self.avancar(days=5)
        self.util.limpar_movimento(fmt.fmt_data(fmt.somar_dias(fmt.hoje(), -1)))
        self.assertEqual(self.banco.valor("SELECT saldo_cent FROM clientes WHERE id = ?", (cid,)), -800)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM caderneta"), 1)

    def test_limpeza_recusa_data_de_hoje_e_futura(self):
        with self.assertRaises(ErroNegocio):
            self.util.limpar_movimento(fmt.fmt_data(fmt.hoje()))
        with self.assertRaises(ErroNegocio):
            self.util.limpar_movimento(fmt.fmt_data(fmt.somar_dias(fmt.hoje(), 3)))


class TesteRelatorios(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("usar_desconto", "S")
        self.rel = RelatorioController(self.banco)
        sub = self.banco.valor("SELECT id FROM subgrupos LIMIT 1")
        # SKOL R$ 8 (custo 3) e AGUA R$ 3,50 (custo 1)
        self.banco.executar("UPDATE produtos SET ult_preco_cent = 300 WHERE id = ?", (self.skol,))
        self.banco.executar("UPDATE produtos SET ult_preco_cent = 100, controla_estoque = 1, qt_atual = 10 WHERE id = ?", (self.agua,))
        v1 = self.vender((self.skol, 2), (self.agua, 1))     # 19,50
        self.pagar(v1, "Dinheiro", 2000); self.caixa.fechar(v1)
        v2 = self.vender((self.skol, 1), mesa=3)             # 8,00 + 0,80
        self.caixa.definir_desconto(v2, valor_cent=100)
        self.pagar(v2, "Pix", 780); self.caixa.fechar(v2, garcom_id=self.adm)
        v3 = self.vender((self.agua, 1))
        self.caixa.cancelar_venda(v3, "teste")
        self.hoje = fmt.hoje()
        self.f = {"de": self.hoje, "ate": self.hoje}

    def test_cupons_listam_cancelado_e_turno_atual(self):
        c = self.rel.cupons(self.f)
        self.assertEqual([(x["cupom"], x["cancelado"], x["atual"]) for x in c], [(1, False, True), (2, False, True), (3, True, True)])
        self.assertEqual(len(self.rel.cupons(self.f, incluir_cancelados=False)), 2)
        self.assertEqual(len(self.rel.cupons({"cupom_ini": 2, "cupom_fim": 2})), 1)
        self.assertEqual(len(self.rel.cupons({**self.f, "modalidade": "mesa"})), 1)

    def test_filtro_de_hora(self):
        self.assertEqual(len(self.rel.cupons({**self.f, "hora_ini": "20:00", "hora_fim": "22:00"})), 3)
        self.assertEqual(len(self.rel.cupons({**self.f, "hora_ini": "22:00"})), 0)

    def test_totalizacao_tc_tm_formas_e_subgrupo(self):
        t = self.rel._totais(self.f)
        self.assertEqual((t["tc"], t["venda"], t["desconto"], t["servico"], t["total"]), (2, 2750, 100, 80, 2730))
        self.assertEqual(t["tm"], 1365)
        formas = {x["tipo"]: x["valor"] for x in t["formas"]}
        self.assertEqual(formas, {"Dinheiro": 1950, "Pix": 780})        # dinheiro já líquido do troco
        texto = para_texto(self.rel.totalizacao_fita(self.f), 40)
        self.assertTrue(all(len(l) <= 40 for l in texto.splitlines()))
        self.assertIn("TC (cupons)", texto)

    def test_vendas_por_grupo_percentuais(self):
        r = self.rel.vendas_por_grupo(self.f)
        ultimo = r.linhas[-1]
        self.assertEqual((ultimo[0], ultimo[2], ultimo[3]), ("TOTAL DE VENDAS", "27,50", "100,00"))

    def test_cmv_margem(self):
        r = self.rel.cmv(self.f)
        total = r.linhas[-1]
        # vendido 27,50; custo = 3 skol x 3,00 + 1 agua x 1,00 = 10,00
        self.assertEqual((total[3], total[4], total[5], total[6]), ("10,00", "27,50", "17,50", "63,64"))

    def test_garcons_e_comandas(self):
        g = self.rel.garcons(self.f)
        self.assertEqual(g.linhas[0][:3], ["ADM", "1", "1"])
        c = self.rel.comandas(self.f)
        self.assertEqual((c.linhas[0][0], c.linhas[0][-1]), ("M3", "7,80"))

    def test_estoque_atual_cores_e_filtros(self):
        self.banco.executar("UPDATE produtos SET estoque_minimo = 100 WHERE id = ?", (self.skol,))
        rel, dados = self.rel.estoque_atual()
        sit = {d["nome"]: d["situacao"] for d in dados}
        self.assertEqual(sit["SKOL"], "ponto")      # 97 unidades, mínimo 100
        self.assertEqual(sit["AGUA"], "normal")
        _, so_pontos = self.rel.estoque_atual({"situacao": "ponto"})
        self.assertEqual([d["nome"] for d in so_pontos], ["SKOL"])
        _, caros = self.rel.estoque_atual({"valor": 20000, "verifica_valores": "maior"})
        self.assertEqual([d["nome"] for d in caros], ["SKOL"])   # 97 x 3,00 = 291,00 >= 200,00

    def test_estoque_parado_por_data(self):
        self.banco.executar("UPDATE produtos SET ult_atualizacao = '2026-08-01 10:00:00' WHERE id = ?", (self.agua,))
        corte = fmt.somar_dias(fmt.hoje(), -20)
        _, parados = self.rel.estoque_atual({"data": corte, "verifica_datas": "menor"})
        self.assertEqual([d["nome"] for d in parados], ["AGUA"])

    def test_resultado_financeiro_agrupa_por_plano(self):
        contas = ContasController(self.banco, self.adm)
        aluguel = self.banco.valor("SELECT id FROM subplanos WHERE nome = 'Aluguel'")
        contas.incluir(aluguel, "Aluguel", self.tipo(), 100000, self.hoje, self.hoje, self.hoje)
        r = self.rel.resultado_financeiro({"de": self.hoje, "ate": self.hoje})
        por_rotulo = {l[0].strip(): l[1] for l in r.linhas}
        self.assertEqual(por_rotulo["Total de créditos"], "27,30")           # vendas do PDV
        self.assertEqual(por_rotulo["Total de débitos"], "1.000,00")
        self.assertEqual(por_rotulo["Resultado operacional"], "-972,70")

    def test_clientes_inativos(self):
        ativo = self.cliente("ATIVA")
        self.cliente("PARADO")
        vid = self.caixa.abrir_caderneta(ativo)
        self.caixa.adicionar_item(vid, self.skol, 1)
        self.caixa.fechar(vid)
        r = self.rel.clientes_inativos(fmt.somar_dias(self.hoje, -7), self.hoje)
        self.assertEqual([l[1] for l in r.linhas], ["PARADO"])

    def test_cancelados(self):
        r = self.rel.cancelados(self.f)
        textos = {l[0]: l for l in r.linhas}
        self.assertTrue(any("1" == l[1] for l in r.linhas if l[0] == "Cancelados"))

    def test_informativo_por_dia_e_hora(self):
        r = self.rel.informativo_dias(self.f)
        self.assertEqual(r.linhas[-1][2], "2")
        h = self.rel.vendas_por_hora(self.f)
        self.assertEqual(h.linhas[0][1], "21:00 a 22:00")

    def test_painel(self):
        p = self.rel.painel()
        self.assertEqual((p["vendas_dia"], p["venda_media"]), (2, 1365))
        self.assertEqual(p["estoque_total"], 2)

    def test_csv_usa_ponto_e_virgula(self):
        csv = para_csv(self.rel.vendas_por_grupo(self.f))
        self.assertIn(";", csv.splitlines()[2])

    def test_fechamentos_e_caixa(self):
        self.turnos.movimentar(self.turno, self.adm, "saida", 500, "gelo")
        res = self.turnos.fechar(self.turno, self.adm, 10000 + 1950 - 500)   # o Pix (7,80) não está na gaveta
        self.assertEqual((res["esperado"], res["fora_da_gaveta"]), (10000 + 1950 - 500, 780))
        r = self.rel.fechamentos(self.f)
        self.assertEqual(r.linhas[0][-1], "0,00")
        m = self.rel.caixa_movimentos(self.f)
        self.assertEqual(m.rodape[1], ("Total de saídas (sangrias)", "5,00"))

    def test_fechamento_e_sangria_da_madrugada_contam_na_noite(self):
        self.avancar(hours=6)                                    # 04/10 às 3h: ainda é a noite de 03/10
        self.turnos.movimentar(self.turno, self.adm, "saida", 500, "gelo")
        self.turnos.fechar(self.turno, self.adm, 10000 + 1950 - 500)
        noite = {"de": self.hoje, "ate": self.hoje}
        self.assertEqual(len(self.rel.fechamentos(noite).linhas), 1)
        self.assertEqual(self.rel.caixa_movimentos(noite).rodape[1], ("Total de saídas (sangrias)", "5,00"))
        dia_seguinte = {"de": fmt.somar_dias(self.hoje, 1), "ate": fmt.somar_dias(self.hoje, 1)}
        self.assertEqual(self.rel.fechamentos(dia_seguinte).linhas, [])
        self.assertEqual(self.rel.caixa_movimentos(dia_seguinte).linhas, [])


class TesteImpressao(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.imp = ImpressaoController(self.banco)
        ConfigController(self.banco).salvar_loja({"nome_fantasia": "Boate X", "cnpj": "00.000.000/0001-00"})

    def test_cupom_cabe_na_fita_e_mostra_troco(self):
        vid = self.vender((self.skol, 2), mesa=5)
        self.pagar(vid, "Dinheiro", 2000)
        self.caixa.fechar(vid)
        texto = self.imp.cupom(vid)
        linhas = texto.splitlines()
        self.assertTrue(all(len(l) <= 40 for l in linhas), [l for l in linhas if len(l) > 40])
        for esperado in ("BOATE X", "CUPOM NÃO FISCAL", "Mesa 5", "SKOL", "Serviço (+)", "TOTAL", "Troco"):
            self.assertIn(esperado, texto)

    def test_pedido_remoto_so_para_subgrupo_marcado_e_com_observacao(self):
        cozinha = self.banco.inserir("subgrupos", {"nome": "COZINHA", "grupo_id": self.banco.valor("SELECT id FROM grupos LIMIT 1"),
                                                   "impressora_remota": 1})
        prato = CadastroController(self.banco).salvar("produtos", {
            "codigo": "70", "nome": "FILE", "subgrupo_id": cozinha,
            "unidade_id": self.banco.valor("SELECT id FROM unidades LIMIT 1"), "preco_cent": "30,00"})
        vid = self.caixa.abrir_balcao()
        self.caixa.adicionar_item(vid, self.skol, 1)
        item = self.caixa.adicionar_item(vid, prato, 1, observacao="ao ponto")
        tickets = self.imp.pedido_remoto(vid)
        self.assertEqual(list(tickets), ["COZINHA"])
        self.assertIn("ao ponto", tickets["COZINHA"])
        self.assertNotIn("SKOL", tickets["COZINHA"])
        self.assertNotIn("ao ponto", self.imp.pre_conta(vid) if False else self.imp._corpo_itens(vid, 40)[0])

    def test_fechamento_de_turno_texto(self):
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Dinheiro", 800)
        self.caixa.fechar(vid)
        res = self.turnos.fechar(self.turno, self.adm, 10800)
        texto = self.imp.fechamento(res)
        self.assertIn("FECHAMENTO DE TURNO", texto)
        self.assertIn("CAIXA CONFERIDO", texto)
        self.assertTrue(all(len(l) <= 40 for l in texto.splitlines()))

    def test_enviar_grava_arquivo(self):
        caminho = Path(self.imp.enviar("teste de impressão", "cupom 1"))
        try:
            self.assertEqual(caminho.read_text(encoding="utf-8"), "teste de impressão")
        finally:
            caminho.unlink(missing_ok=True)

    def test_reducao_z_e_leitura_x_sao_gerenciais(self):
        vid = self.vender((self.skol, 1))
        self.pagar(vid, "Dinheiro", 800)
        self.caixa.fechar(vid)
        self.assertIn("GERENCIAL", self.imp.leitura_x(self.turno))
        self.assertIn("Redução Z".upper(), self.imp.reducao_z().upper())

    def test_pedido_de_entrega_leva_troco(self):
        from src.controllers.entrega_controller import EntregaController
        bairro = CadastroController(self.banco).salvar("bairros", {"nome": "CENTRO", "taxa_cent": "3,00"})
        cid = CadastroController(self.banco).salvar("clientes", {
            "numero_consulta": "9", "nome": "WESLEY", "endereco": "R Antonio Carlos 582", "bairro_id": bairro})
        ent = EntregaController(self.banco, self.caixa)
        vid = ent.abrir(cid)
        self.caixa.adicionar_item(vid, self.skol, 4)                     # 32,00 + 3,00 de taxa
        self.assertEqual(self.caixa.obter(vid)["total_cent"], 3500)
        self.assertEqual(ent.definir_dados(vid, troco_para_cent=5000, mensagem="MANDAR CARDAPIO"), 1500)
        with self.assertRaises(ErroNegocio):
            ent.definir_dados(vid, troco_para_cent=-1)
        ent.emitir_pedido(vid)
        texto = self.imp.pedido_entrega(vid)
        for esperado in ("E N T R E G A", "WESLEY", "CENTRO", "LEVAR TROCO DE", "15,00", "MANDAR CARDAPIO"):
            self.assertIn(esperado, texto)
        pend = ent.pendentes()
        self.assertEqual((pend[0]["cliente"], pend[0]["t_entrega"]), ("WESLEY", 0))
        ent.atribuir_entregador(vid, self.adm)
        self.avancar(minutes=12)
        self.assertEqual(ent.pendentes()[0]["t_entrega"], 12)
        self.pagar(vid, "Dinheiro", 5000)
        v = self.caixa.fechar(vid)
        self.assertEqual((v["troco_cent"], v["status"]), (1500, "fechada"))
        self.assertEqual(ent.pendentes(), [])
        self.assertEqual(self.turnos.resumo(self.turno)["entregas"], 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
