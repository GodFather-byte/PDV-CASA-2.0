"""Acerto da garota com shows (lançados pelo operador, nunca contados sozinhos) e conferência da maquininha no fechamento."""
from __future__ import annotations

from src.controllers.config_controller import ConfigController
from src.controllers.impressao_controller import ImpressaoController
from src.controllers.utilitario_controller import UtilitarioController
from src.core.erros import ErroNegocio, ErroValidacao
from tests.test_comissao_garotas import BaseComissao


class TesteAcertoComShows(BaseComissao):
    def acertar(self, shows, valor, **kw):
        return self.com.pagar(180, self.turno, self.adm, shows=shows, valor_show_cent=valor, **kw)

    def test_o_exemplo_da_casa_5_pontos_25_mais_10_shows_de_50_da_525(self):
        self.garota(180, "MARIA")
        self.lancar(180, 25)                                                # 5 pontos de R$ 5,00 = R$ 25,00
        esperado = self.turnos.resumo(self.turno)["esperado"]
        p = self.acertar(10, 5000)
        self.assertEqual((p["comissao_cent"], p["shows"], p["valor_show_cent"], p["shows_cent"], p["total_cent"]),
                         (2500, 10, 5000, 50000, 52500))
        self.assertEqual(self.com.pendente(180), 0)
        m = self.banco.um("SELECT tipo, valor_cent, descricao FROM movimentos_caixa")
        self.assertEqual(tuple(m), ("saida", 52500, "Acerto garota 180 MARIA"))
        self.assertEqual(self.turnos.resumo(self.turno)["esperado"], esperado - 52500)
        a = self.banco.um("SELECT * FROM acertos_garotas")
        self.assertEqual((a["garota"], a["comissao_cent"], a["shows_qtd"], a["show_valor_cent"], a["total_cent"], a["tirou_do_caixa"]),
                         (180, 2500, 10, 5000, 52500, 1))

    def test_recibo_mostra_comissao_shows_e_total(self):
        self.garota(180, "MARIA")
        self.lancar(180, 25)
        recibo = ImpressaoController(self.banco).recibo_comissao(self.acertar(10, 5000), "ADM")
        for trecho in ("RECIBO DE ACERTO", "Garota: 180 MARIA", "COMISSÃO (1)", "25,00", "SHOWS: 10 x 50,00", "500,00",
                       "TOTAL PAGO", "525,00", "Assinatura da garota"):
            self.assertIn(trecho, recibo)
        self.assertTrue(all(len(l) <= 40 for l in recibo.splitlines()), recibo)

    def test_sem_shows_tudo_continua_igual(self):
        self.lancar(180, 25)
        p = self.com.pagar(180, self.turno, self.adm)
        self.assertEqual((p["shows"], p["shows_cent"], p["comissao_cent"], p["total_cent"]), (0, 0, 2500, 2500))
        self.assertEqual(self.banco.valor("SELECT descricao FROM movimentos_caixa"), "Comissão garota 180")
        recibo = ImpressaoController(self.banco).recibo_comissao(p, "ADM")
        self.assertIn("RECIBO DE COMISSÃO", recibo)
        self.assertNotIn("SHOWS", recibo)

    def test_so_shows_sem_comissao_pendente_tambem_acerta(self):
        p = self.acertar(3, 6000)
        self.assertEqual((p["comissao_cent"], p["shows_cent"], p["total_cent"], p["quantidade"]), (0, 18000, 18000, 0))
        self.assertEqual(self.banco.valor("SELECT valor_cent FROM movimentos_caixa"), 18000)
        recibo = ImpressaoController(self.banco).recibo_comissao(p, "ADM")
        self.assertIn("SHOWS: 3 x 60,00", recibo)
        self.assertIn("180,00", recibo)

    def test_sem_comissao_e_sem_shows_nao_ha_o_que_pagar(self):
        with self.assertRaises(ErroNegocio) as e:
            self.com.pagar(180, self.turno, self.adm)
        self.assertIn("não tem comissão pendente", str(e.exception))

    def test_fechar_sem_comissao_nem_shows_so_com_permissao_explicita_e_nao_repete(self):
        with self.assertRaises(ErroNegocio):
            self.com.pagar(180, self.turno, self.adm)                         # sem o aval da tela, nada a pagar continua recusado
        p = self.com.pagar(180, self.turno, self.adm, permitir_zerado=True)
        self.assertEqual((p["total_cent"], p["quantidade"], p["shows"], p["dinheiro_cent"], p["tirou_do_caixa"]), (0, 0, 0, 0, False))
        self.assertEqual(self.banco.valor("SELECT total_cent FROM acertos_garotas"), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 0)       # nada saiu da gaveta
        with self.assertRaises(ErroNegocio):
            self.com.pagar(180, self.turno, self.adm)                         # um segundo clique não grava outro acerto
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM acertos_garotas"), 1)

    def test_vale_nao_passa_do_total_nem_no_fechamento_sem_valor(self):
        with self.assertRaises(ErroNegocio):
            self.com.pagar(180, self.turno, self.adm, vale_cent=1000, permitir_zerado=True)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM acertos_garotas"), 0)

    def test_recibo_nao_lista_os_lancamentos_um_a_um(self):
        self.garota(180, "MARIA")
        self.lancar(180, 25); self.lancar(180, 30)
        recibo = ImpressaoController(self.banco).recibo_comissao(self.com.pagar(180, self.turno, self.adm), "ADM")
        self.assertNotIn("lançamento", recibo)
        self.assertIn("RECIBO DE COMISSÃO", recibo)
        self.assertIn("TOTAL PAGO (2)", recibo)
        self.assertIn("55,00", recibo)
        recibo = ImpressaoController(self.banco).recibo_comissao(self.acertar(2, 5000), "ADM")
        self.assertNotIn("lançamento", recibo)
        self.assertEqual(recibo.count("-" * 40), 2)                           # sem faixas de traços seguidas onde estavam as linhas

    def test_recibo_do_fechamento_sem_valor(self):
        p = self.com.pagar(180, self.turno, self.adm, permitir_zerado=True)
        recibo = ImpressaoController(self.banco).recibo_comissao(p, "ADM")
        for trecho in ("RECIBO DE ACERTO", "TOTAL PAGO (0)", "Conta fechada, nada a pagar.", "Assinatura da garota"):
            self.assertIn(trecho, recibo)
        self.assertNotIn("Pago fora do caixa", recibo)

    def test_papeis_da_garota_saem_com_as_linhas_importantes_em_letra_mais_alta(self):
        from src.controllers.impressao_controller import _ESTILOS
        from src.hardware import impressora_termica as term
        self.garota(180, "MARIA")
        self.lancar(180, 25)
        imp = ImpressaoController(self.banco)
        recibo = imp.recibo_comissao(self.com.pagar(180, self.turno, self.adm), "ADM")
        dados = term.texto_para_escpos(recibo, **_ESTILOS["recibo_garota"])
        for linha in ("Garota: 180 MARIA", "TOTAL PAGO (1)"):
            posicao = dados.index(linha.encode("cp850"))
            self.assertIn(term.TAMANHO_ALTO, dados[max(0, posicao - 12):posicao], linha)      # o dobro de altura vem logo antes
        saida = imp.comprovante_movimento("saida", 2500, "Comissão garota 180 MARIA", "ADM")
        dados = term.texto_para_escpos(saida, **_ESTILOS["saida_garota"])
        posicao = dados.index(b"Motivo:")
        self.assertIn(term.TAMANHO_ALTO, dados[max(0, posicao - 12):posicao])
        self.assertEqual(_ESTILOS["comprovante"], {"negrito_linhas": 1, "grande_prefixos": ("Valor",)})     # a sangria comum não mudou

    def test_shows_pagos_fora_do_caixa_nao_mexem_na_gaveta(self):
        self.lancar(180, 25)
        self.acertar(2, 5000, tirar_do_caixa=False)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 0)
        self.assertEqual(self.banco.valor("SELECT tirou_do_caixa FROM acertos_garotas"), 0)

    def test_validacoes(self):
        self.lancar(180, 25)
        for qtd, valor in ((-1, 5000), (1000, 5000), ("abc", 5000), (2, 0)):
            with self.assertRaises(ErroNegocio, msg=(qtd, valor)):
                self.acertar(qtd, valor)
        self.assertEqual(self.com.pendente(180), 2500)                       # nada foi pago nos erros
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM acertos_garotas"), 0)

    def test_valor_do_show_so_importa_se_ha_shows(self):
        self.lancar(180, 25)
        self.assertEqual(self.acertar(0, 0)["total_cent"], 2500)

    def test_valores_do_show_vem_da_configuracao(self):
        self.assertEqual(self.com.valores_show(), [5000, 6000])
        ConfigController(self.banco).salvar_config({"show_valores": "70;50,50"})
        self.assertEqual(self.com.valores_show(), [5050, 7000])
        self.assertEqual(self.banco.cfg("show_valores"), "70;50,50")
        for ruim in ("", "abc", "0", "10;20;30;40;50"):
            with self.assertRaises(ErroValidacao, msg=ruim):
                ConfigController(self.banco).salvar_config({"show_valores": ruim})

    def test_fechamento_do_turno_lista_os_shows_pagos(self):
        self.garota(180, "MARIA")
        self.lancar(180, 25)
        self.acertar(10, 5000)
        res = self.turnos.resumo(self.turno)
        self.assertEqual((res["shows"]["quantidade"], res["shows"]["total_cent"]), (10, 50000))
        res = self.turnos.fechar(self.turno, self.adm, 0,
                                 justificativa="Contagem zerada após o acerto dos shows")
        fita = ImpressaoController(self.banco).fechamento(res)
        self.assertIn("SHOWS PAGOS ÀS GAROTAS (1)", fita)
        self.assertIn("180 MARIA (10x)", fita)
        self.assertIn("500,00", fita)

    def test_limpeza_do_movimento_leva_o_acerto_junto_com_o_turno(self):
        self.lancar(180, 25)
        self.acertar(2, 5000)
        self.turnos.fechar(self.turno, self.adm, 0,
                          justificativa="Contagem zerada após o acerto dos shows")
        self.banco.executar("UPDATE turnos SET aberto_em = '2020-01-01 10:00:00', fechado_em = '2020-01-02 04:00:00'")
        UtilitarioController(self.banco, self.adm).limpar_movimento("01/01/2021")
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM acertos_garotas"), 0)


class TestePixNoAcerto(BaseComissao):
    def test_so_o_dinheiro_sai_da_gaveta_e_o_resto_vai_no_pix(self):
        self.garota(180, "MARIA")
        self.lancar(180, 25)
        esperado = self.turnos.resumo(self.turno)["esperado"]
        p = self.com.pagar(180, self.turno, self.adm, shows=10, valor_show_cent=5000, pix_cent=30000)     # total 525
        self.assertEqual((p["total_cent"], p["pix_cent"], p["dinheiro_cent"], p["tirou_do_caixa"]), (52500, 30000, 22500, True))
        m = self.banco.um("SELECT valor_cent, descricao FROM movimentos_caixa")
        self.assertEqual(m["valor_cent"], 22500)
        self.assertIn("resto no Pix: R$ 300,00", m["descricao"])
        self.assertEqual(self.turnos.resumo(self.turno)["esperado"], esperado - 22500)
        self.assertEqual(self.banco.valor("SELECT pix_cent FROM acertos_garotas"), 30000)

    def test_tudo_no_pix_nao_faz_sangria_mesmo_pedindo_para_tirar_do_caixa(self):
        self.lancar(180, 25)
        p = self.com.pagar(180, self.turno, self.adm, True, pix_cent=2500)
        self.assertEqual((p["movimento_id"], p["tirou_do_caixa"], p["dinheiro_cent"]), (None, False, 0))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 0)
        self.assertEqual(self.com.pendente(180), 0)

    def test_tudo_no_pix_nao_exige_turno_aberto_para_a_gaveta(self):
        self.lancar(180, 25)
        p = self.com.pagar(180, None, self.adm, True, pix_cent=2500)
        self.assertEqual(p["pix_cent"], 2500)

    def test_pix_invalido(self):
        self.lancar(180, 25)
        for pix in (-1, 2501):
            with self.assertRaises(ErroNegocio, msg=pix):
                self.com.pagar(180, self.turno, self.adm, pix_cent=pix)
        self.assertEqual(self.com.pendente(180), 2500)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 0)

    def test_recibo_separa_dinheiro_e_pix(self):
        self.lancar(180, 100)
        p = self.com.pagar(180, self.turno, self.adm, pix_cent=4000)
        recibo = ImpressaoController(self.banco).recibo_comissao(p, "ADM")
        for trecho in ("Dinheiro (saiu do caixa)", "60,00", "Pix", "40,00"):
            self.assertIn(trecho, recibo)
        self.assertNotIn("Saiu do dinheiro do caixa.", recibo)
        self.assertTrue(all(len(l) <= 40 for l in recibo.splitlines()), recibo)
        tudo = self.com.pagar(156, self.turno, self.adm, pix_cent=500) if self.lancar(156, 5) else None
        self.assertNotIn("Dinheiro (", ImpressaoController(self.banco).recibo_comissao(tudo, "ADM"))

    def test_fechamento_mostra_o_pix_pago_as_garotas(self):
        self.lancar(180, 100)
        self.com.pagar(180, self.turno, self.adm, pix_cent=4000)
        res = self.turnos.fechar(self.turno, self.adm, 10000 - 6000)
        self.assertEqual(res["pix_garotas_cent"], 4000)
        fita = ImpressaoController(self.banco).fechamento(res)
        self.assertIn("Pago às garotas por Pix", fita)
        self.assertIn("não saiu da gaveta", fita)

    def test_sem_pix_o_recibo_e_o_de_sempre(self):
        self.lancar(180, 25)
        p = self.com.pagar(180, self.turno, self.adm)
        self.assertEqual((p["pix_cent"], p["dinheiro_cent"]), (0, 2500))
        self.assertIn("Saiu do dinheiro do caixa.", ImpressaoController(self.banco).recibo_comissao(p, "ADM"))


class TesteConferenciaDaMaquininha(BaseComissao):
    def vender_em(self, forma, valor):
        vid = self.vender((self.skol, 1))
        self.caixa.adicionar_pagamento(vid, self.tipo(forma), valor)
        self.caixa.fechar(vid)

    def test_debito_e_credito_vem_separados_com_quantidade_e_valor(self):
        self.vender_em("Cartão Débito", 800)
        self.vender_em("Cartão Débito", 800)
        self.vender_em("Cartão Crédito", 1300)                               # 8,00 + R$ 5,00 da taxa do crédito
        self.vender_em("Dinheiro", 800)                                      # dinheiro não é maquininha
        maq = self.turnos.maquininha(self.turno)
        por_tipo = {l["tipo"]: (l["qtd"], l["valor"]) for l in maq["linhas"]}
        self.assertEqual(por_tipo, {"Cartão Débito": (2, 1600), "Cartão Crédito": (1, 1300), "Pix": (0, 0)})
        self.assertEqual((maq["qtd"], maq["total"]), (3, 2900))
        self.assertEqual(self.turnos.resumo(self.turno)["maquininha"], maq)

    def test_debito_e_credito_aparecem_mesmo_sem_movimento(self):
        nomes = [l["tipo"] for l in self.turnos.maquininha(self.turno)["linhas"]]
        self.assertEqual(nomes[:2], ["Cartão Débito", "Cartão Crédito"])

    def test_nao_revela_o_dinheiro_esperado(self):
        self.vender_em("Dinheiro", 800)
        maq = self.turnos.maquininha(self.turno)
        self.assertEqual(maq["total"], 0)
        self.assertNotIn("esperado", maq)

    def test_fita_do_fechamento_traz_o_bloco_da_maquininha(self):
        self.vender_em("Cartão Débito", 800)
        self.vender_em("Cartão Crédito", 1300)                               # com a taxa do crédito
        self.vender_em("Cartão Crédito", 1300)
        fita = ImpressaoController(self.banco).fechamento(self.turnos.fechar(self.turno, self.adm, 10000))
        self.assertIn("CONFERIR NA MAQUININHA", fita)
        for trecho in ("Cartão Débito (1)", "Cartão Crédito (2)", "TOTAL (3)", "34,00"):
            self.assertIn(trecho, fita)
        self.assertTrue(all(len(l) <= 40 for l in fita.splitlines()), fita)

    def test_pagamento_de_venda_cancelada_nao_entra(self):
        vid = self.vender((self.skol, 1))
        self.caixa.adicionar_pagamento(vid, self.tipo("Cartão Débito"), 800)
        self.caixa.fechar(vid)
        self.caixa.cancelar_venda(vid, "erro")
        self.assertEqual(self.turnos.maquininha(self.turno)["total"], 0)


class TesteValeDaGarota(BaseComissao):
    """Vale que a garota já pegou: descontado do total do acerto (dinheiro ou Pix) e sem sair do caixa de novo."""

    def setUp(self):
        super().setUp()
        self.garota(180, "MARIA")
        self.lancar(180, 25)                       # comissão R$ 25 + 10 shows de R$ 50 = R$ 525

    def pagar(self, **kw):
        return self.com.pagar(180, self.turno, self.adm, shows=10, valor_show_cent=5000, **kw)

    def test_vale_em_dinheiro_so_tira_do_caixa_o_que_sobra(self):
        esperado = self.turnos.resumo(self.turno)["esperado"]
        p = self.pagar(vale_cent=5000)
        self.assertEqual((p["total_cent"], p["vale_cent"], p["pix_cent"], p["dinheiro_cent"]), (52500, 5000, 0, 47500))
        self.assertEqual(self.banco.valor("SELECT valor_cent FROM movimentos_caixa"), 47500)     # não 52500
        self.assertEqual(self.turnos.resumo(self.turno)["esperado"], esperado - 47500)
        a = self.banco.um("SELECT total_cent, pix_cent, vale_cent FROM acertos_garotas")
        self.assertEqual(tuple(a), (52500, 0, 5000))
        self.assertEqual(self.com.pendente(180), 0)

    def test_vale_com_pix_e_dinheiro(self):
        p = self.pagar(pix_cent=30000, vale_cent=10000)          # sobram 425: 300 no Pix e 125 em dinheiro
        self.assertEqual((p["pix_cent"], p["vale_cent"], p["dinheiro_cent"]), (30000, 10000, 12500))
        self.assertEqual(self.banco.valor("SELECT valor_cent FROM movimentos_caixa"), 12500)
        self.assertEqual(self.com.pix_do_turno(self.turno), 30000)                                # fechamento: o Pix que saiu

    def test_tudo_no_pix_com_vale_paga_so_a_diferenca(self):
        p = self.pagar(pix_cent=47500, vale_cent=5000)
        self.assertEqual((p["pix_cent"], p["dinheiro_cent"], p["movimento_id"]), (47500, 0, None))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 0)

    def test_vale_do_valor_inteiro_nao_move_o_caixa(self):
        p = self.pagar(vale_cent=52500)
        self.assertEqual((p["dinheiro_cent"], p["pix_cent"], p["movimento_id"]), (0, 0, None))
        self.assertEqual(self.com.pendente(180), 0)

    def test_vale_e_pix_invalidos(self):
        for kw in ({"vale_cent": 52501}, {"vale_cent": -1}, {"pix_cent": 47501, "vale_cent": 5000}):
            with self.assertRaises(ErroNegocio, msg=kw):
                self.pagar(**kw)
        self.assertEqual(self.com.pendente(180), 2500)                                            # nada foi pago

    def test_recibo_mostra_o_vale(self):
        p = self.pagar(pix_cent=30000, vale_cent=10000)
        recibo = ImpressaoController(self.banco).recibo_comissao(p, "ADM")
        for trecho in ("Dinheiro", "125,00", "Vale (já recebido)", "100,00", "Pix", "300,00", "TOTAL PAGO", "525,00"):
            self.assertIn(trecho, recibo)

    def test_recibo_com_vale_e_sem_pix_nao_mostra_linha_de_pix(self):
        p = self.pagar(vale_cent=5000)
        recibo = ImpressaoController(self.banco).recibo_comissao(p, "ADM")
        self.assertIn("Vale (já recebido)", recibo)
        self.assertNotIn("Pix", recibo)


class TesteNomeNoAcerto(BaseComissao):
    """O nome digitado no acerto vai para o acerto e o recibo; o cadastro não muda (o número pode ser de outra garota)."""

    def test_nome_digitado_sai_no_recibo_e_na_sangria_sem_mexer_no_cadastro(self):
        self.garota(180, "MARIA")
        p = self.com.pagar(180, self.turno, self.adm, shows=2, valor_show_cent=5000, nome="  Bia   Souza ")
        self.assertEqual(p["nome"], "Bia Souza")
        self.assertEqual(self.banco.valor("SELECT nome FROM acertos_garotas"), "Bia Souza")
        self.assertEqual(self.banco.valor("SELECT descricao FROM movimentos_caixa"), "Acerto garota 180 Bia Souza")
        self.assertIn("Garota: 180 Bia Souza", ImpressaoController(self.banco).recibo_comissao(p, "ADM"))
        self.assertEqual(self.com.nome(180), "MARIA")
        self.assertEqual(self.com.shows_do_turno(self.turno)["por_garota"][0]["nome"], "Bia Souza")

    def test_sem_nome_usa_o_do_cadastro_e_sem_cadastro_fica_vazio(self):
        self.garota(180, "MARIA")
        self.assertEqual(self.com.pagar(180, self.turno, self.adm, shows=1, valor_show_cent=5000)["nome"], "MARIA")
        p = self.com.pagar(45, self.turno, self.adm, shows=1, valor_show_cent=5000, nome="")
        self.assertEqual(p["nome"], "")
        self.assertIsNone(self.banco.valor("SELECT nome FROM acertos_garotas WHERE garota = 45"))

    def test_conta_zerada_com_nome_tem_o_recibo_em_letra_mais_alta(self):
        from src.controllers.impressao_controller import _ESTILOS
        from src.hardware import impressora_termica as term
        p = self.com.pagar(77, self.turno, self.adm, permitir_zerado=True, nome="Ana")
        recibo = ImpressaoController(self.banco).recibo_comissao(p, "ADM")
        dados = term.texto_para_escpos(recibo, **_ESTILOS["recibo_garota"])
        for linha in ("Garota: 77 Ana", "Conta fechada", "RECIBO DE ACERTO"):
            posicao = dados.index(linha.encode("cp850"))
            self.assertIn(term.TAMANHO_ALTO, dados[max(0, posicao - 40):posicao], linha)

    def test_banco_da_versao_29_ganha_a_coluna_do_nome(self):
        import tempfile
        from pathlib import Path
        from src.database.conexao import BancoDados
        from src.database.esquema import VERSAO_ESQUEMA
        with tempfile.TemporaryDirectory() as pasta:
            caminho = str(Path(pasta) / "v29.db")
            b = BancoDados(caminho)
            colunas = [r[1] for r in b.todos("PRAGMA table_info(acertos_garotas)") if r[1] != "nome"]
            b.executar(f"CREATE TABLE _antiga AS SELECT {', '.join(colunas)} FROM acertos_garotas")   # como era até a v29
            b.executar("DROP TABLE acertos_garotas")
            b.executar("ALTER TABLE _antiga RENAME TO acertos_garotas")
            b.executar("PRAGMA user_version = 29")
            b.fechar()
            b = BancoDados(caminho)
            try:
                self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
                self.assertIn("nome", [r[1] for r in b.todos("PRAGMA table_info(acertos_garotas)")])
            finally:
                b.fechar()
