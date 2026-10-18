"""A tela do caixa refeita: coluna de cartões, indicadores do cabeçalho, selo da venda, nome da comanda, navegação entre
comandas (clientes e garotas), ações da linha e a disposição que acompanha o tamanho da janela."""
from __future__ import annotations

import os
import re
import tempfile
import tkinter as tk
import unittest
from tkinter import ttk

from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.database.esquema import VERSAO_ESQUEMA
from tests.test_comissao_na_tela import BaseNaTela
from tests.ui_robo import clicar, entradas


def achar(w, classe):
    """O primeiro widget da `classe` dentro de `w`."""
    for f in w.winfo_children():
        if isinstance(f, classe):
            return f
        dentro = achar(f, classe)
        if dentro is not None:
            return dentro
    return None


def escolher_opcao(posicao: int):
    """Resposta do robô à lista de ações (tema.escolher): marca a opção `posicao` e confirma."""
    def acao(w):
        arvore = achar(w, ttk.Treeview)
        filho = arvore.get_children()[posicao]
        arvore.selection_set(filho)
        arvore.focus(filho)
        clicar(w, "Escolher")
    return acao


class BaseCartoes(BaseNaTela):
    def comanda(self, numero, *itens, nome=None):
        vid, _ = self.ctx.caixa.abrir_mesa(numero, comanda=True)
        for produto, qtd in itens or ((self.skol, 1),):
            self.ctx.caixa.adicionar_item(vid, produto, qtd)
        if nome:
            self.ctx.caixa.definir_apelido(vid, nome)
        return vid

    def ir_para(self, numero):
        self.posicao(str(numero))

    def texto_do_cartao(self, chave, marca):
        c = self.cx.painel_mesas.canvas
        itens = c.find_withtag(f"t:{chave}&&{marca}")
        return c.itemcget(itens[0], "text") if itens else None


class TesteNomeDaComanda(BaseCartoes):
    def test_dar_nome_limpar_e_limites(self):
        vid = self.comanda(12)
        self.assertEqual(self.ctx.caixa.definir_apelido(vid, "  Carlos   Silva "), "Carlos Silva")      # espaços arrumados
        self.assertEqual(self.ctx.caixa.obter(vid)["apelido"], "Carlos Silva")
        self.assertEqual(self.ctx.caixa.definir_apelido(vid, ""), "")
        self.assertIsNone(self.ctx.caixa.obter(vid)["apelido"])
        with self.assertRaises(ErroNegocio):
            self.ctx.caixa.definir_apelido(vid, "x" * 25)

    def test_balcao_nao_tem_nome(self):
        balcao = self.ctx.caixa.abrir_balcao()
        with self.assertRaises(ErroNegocio):
            self.ctx.caixa.definir_apelido(balcao, "Carlos")

    def test_nome_aparece_no_titulo_e_no_cartao_e_a_busca_acha_por_ele(self):
        self.comanda(12)
        self.ir_para(12)
        self.dialogos({"Nome da comanda": lambda w: (entradas(w)[0].delete(0, "end"), entradas(w)[0].insert(0, "Carlos"),
                                                    clicar(w, "OK"))})
        self.cx.nomear_comanda(); self.cx.update()
        self.assertEqual(self.cx.lbl_situacao.cget("text"), "Comanda 12 · Carlos")
        self.assertEqual(self.tiles()["12"]["nome"], "Carlos")
        self.assertEqual(self.texto_do_cartao("12", "identificacao"), "Carlos")
        p = self.cx.painel_mesas
        p.var_busca.set("carl")
        self.assertEqual([t["chave"] for t in p.tiles()], ["12"])
        self.sem_travar()

    def test_cancelar_a_janela_nao_muda_o_nome(self):
        vid = self.comanda(12, nome="Carlos")
        self.ir_para(12)
        self.dialogos({"Nome da comanda": "Cancelar"})
        self.cx.nomear_comanda(); self.cx.update()
        self.assertEqual(self.ctx.caixa.obter(vid)["apelido"], "Carlos")

    def test_nomear_no_balcao_avisa_e_nao_abre_a_janela(self):
        avisos = []
        self.dialogos({"Aviso": lambda w: (avisos.append(self.textos(w)), clicar(w, "OK"))})
        self.cx.nomear_comanda(); self.cx.update()
        self.assertTrue(any("comanda ou mesa" in t for a in avisos for t in a), avisos)


class TesteMigracaoDoNome(unittest.TestCase):
    def test_banco_v14_ganha_a_coluna_do_nome(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "v14.db")
            b = BancoDados(caminho)
            b.executar("ALTER TABLE vendas DROP COLUMN apelido")
            b.executar("PRAGMA user_version = 14")
            b.fechar()
            b = BancoDados(caminho)
            try:
                self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
                self.assertIn("apelido", {r[1] for r in b.todos("PRAGMA table_info(vendas)")})
            finally:
                b.fechar()


class TesteIndicadoresESelo(BaseCartoes):
    def test_cabecalho_conta_posicoes_acertos_e_o_que_esta_em_aberto(self):
        self.comanda(12)                                          # 8,00 + 10% de serviço = 8,80
        vid = self.comanda(27)
        self.ctx.caixa.enviar_conta(vid)                          # aguardando acerto
        self.dar(180, 25)                                         # garota com comissão a pagar: também espera acerto
        self.cx.recarregar(); self.cx.update()
        self.assertEqual(self.cx.lbl_abertas.cget("text"), "2")
        self.assertEqual(self.cx.lbl_acertos.cget("text"), "2")
        self.assertEqual(self.cx.lbl_aberto_casa.cget("text"), "R$ 17,60")
        self.assertTrue(re.fullmatch(r"\d\d:\d\d", self.cx.lbl_hora.cget("text")))
        self.assertIn("TURNO 1", self.cx.lbl_turno.cget("text"))
        self.assertIn("ADM", self.cx.lbl_turno.cget("text"))

    def test_indicadores_acompanham_o_que_acontece_na_tela(self):
        self.assertEqual(self.cx.lbl_abertas.cget("text"), "0")
        self.comanda(12)
        self.cx.recarregar(); self.cx.update()
        self.assertEqual(self.cx.lbl_abertas.cget("text"), "1")
        self.ctx.caixa.cancelar_venda(self.banco.valor("SELECT id FROM vendas WHERE comanda = 1"))
        self.cx.recarregar(); self.cx.update()
        self.assertEqual(self.cx.lbl_abertas.cget("text"), "0")

    def test_selo_da_venda_segue_a_situacao(self):
        selo = lambda: self.cx.lbl_status_venda.cget("text")
        self.assertEqual(selo(), "Balcão")
        vid = self.comanda(12)
        self.ir_para(12)
        self.assertEqual(selo(), "Aberta")
        pix = self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Pix'")
        pagamento = self.ctx.caixa.adicionar_pagamento(vid, pix, 500)
        self.cx.recarregar(); self.cx.update()
        self.assertEqual(selo(), "Pago em parte")
        self.ctx.caixa.remover_pagamento(pagamento)
        self.ctx.caixa.adicionar_pagamento(vid, pix, 880)
        self.cx.recarregar(); self.cx.update()
        self.assertEqual(selo(), "Concluir acerto")
        self.ctx.caixa.remover_pagamento(self.ctx.caixa.pagamentos(vid)[0]["id"])
        self.ctx.caixa.enviar_conta(vid)
        self.cx.recarregar(); self.cx.update()
        self.assertEqual(selo(), "Conta enviada")

    def test_total_explica_o_servico_e_a_taxa_do_credito(self):
        vid = self.comanda(12)
        self.ir_para(12)
        self.assertEqual(self.cx.lbl_detalhe_total.cget("text"), "Serviço (10%): R$ 0,80")
        credito = self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Cartão Crédito'")
        self.ctx.caixa.adicionar_pagamento(vid, credito, 500)
        self.cx.recarregar(); self.cx.update()
        self.assertIn("Taxa do crédito: R$ 5,00", self.cx.lbl_detalhe_total.cget("text"))
        self.assertEqual(self.cx.lbl_total.cget("text"), "13,80")

    def test_total_sem_acrescimo_fica_sem_detalhe(self):
        self.banco.cfg_set("cobra_servico_comanda", "N")
        self.comanda(12)
        self.ir_para(12)
        self.assertEqual(self.cx.lbl_detalhe_total.cget("text"), "")


class TesteCartoesDoPainel(BaseCartoes):
    def test_cartao_da_garota_mostra_o_nome_e_quantas_marcacoes(self):
        self.cadastrar(180, "Bianca")
        self.dar(180, 20); self.dar(180, 20)
        self.cx.carregar_mesas(); self.cx.update()
        t = self.tiles()["180"]
        self.assertEqual((t["nome"], t["marcacoes"], t["total"]), ("Bianca", 2, "40,00"))
        self.assertEqual(self.texto_do_cartao("180", "rotulo"), "Bianca")
        self.assertEqual(self.texto_do_cartao("180", "identificacao"), "2 drinks marcados")
        self.assertEqual(self.texto_do_cartao("180", "icone"), "GAROTA 180")

    def test_cartao_da_comanda_mostra_itens_e_o_aviso_de_falta(self):
        vid = self.comanda(12, (self.skol, 1), (self.agua, 2))
        pix = self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Pix'")
        self.ctx.caixa.adicionar_pagamento(vid, pix, 500)
        self.cx.recarregar(); self.cx.update()
        self.assertEqual(self.texto_do_cartao("12", "identificacao"), "2 itens")
        self.assertTrue(self.texto_do_cartao("12", "detalhe").startswith("Falta R$ "))
        self.assertEqual(self.texto_do_cartao("12", "estado"), "Parcial")

    def test_balcao_mostra_total_zerado(self):
        self.assertEqual(self.texto_do_cartao("0", "total"), "R$ 0,00")
        self.assertEqual(self.texto_do_cartao("0", "estado"), "Balcão")

    def test_abas_filtram_e_a_aba_ativa_fica_destacada(self):
        self.comanda(12)
        vid = self.comanda(27)
        self.ctx.caixa.enviar_conta(vid)
        self.cx.recarregar(); self.cx.update()
        p = self.cx.painel_mesas
        p._abas["Aguardando acerto"].event_generate("<Button-1>"); self.cx.update()
        self.assertEqual(p.var_estado.get(), "Aguardando acerto")
        self.assertEqual([t["chave"] for t in p.tiles()], ["27"])
        self.assertNotEqual(str(p._abas["Aguardando acerto"].cget("bg")), str(p._abas["Todas"].cget("bg")))

    def test_texto_guia_da_busca_some_ao_digitar(self):
        p = self.cx.painel_mesas
        self.assertEqual(p.dica_busca.winfo_manager(), "place")
        p.var_busca.set("12")
        self.assertEqual(p.dica_busca.winfo_manager(), "")
        p.var_busca.set("")
        self.assertEqual(p.dica_busca.winfo_manager(), "place")


class TesteDisposicaoResponsiva(BaseCartoes):
    def test_abas_e_busca_se_reorganizam_conforme_a_largura(self):
        p = self.cx.painel_mesas
        p._dispor(640)
        self.assertEqual(p._abas["Pago em parte"].cget("text"), "Pago em parte")
        self.assertEqual(p.busca.grid_info()["row"], 0)                      # busca ao lado do título
        p._dispor(420)
        self.assertEqual(p._abas["Pago em parte"].cget("text"), "Parciais")
        self.assertEqual(p.busca.grid_info()["row"], 1)                      # busca embaixo
        p._dispor(220)                                                       # uma coluna: as abas quebram de linha
        linhas = {a.grid_info()["row"] for a in p._abas.values()}
        self.assertGreater(len(linhas), 1)

    def test_balcao_e_uma_faixa_fina_acima_dos_cartoes_e_as_comandas_ficam_menores(self):
        from src.ui.painel_mesas import ALTURA, ALTURA_FAIXA, LARGURA
        for n in range(1, 8):
            self.comanda(n)
        self.redimensionar(1700)
        self.cx.carregar_mesas(); self.cx.update()
        p = self.cx.painel_mesas
        self.assertLess(LARGURA, 204)                                              # comandas menores que antes (204 x 146)
        self.assertLess(ALTURA, 146)
        self.assertGreater(LARGURA, 150)                                           # mas não pequenas demais
        self.assertGreater(ALTURA, 100)
        x, y, largura, altura = p._celula(0)
        self.assertEqual((x, y, altura), (0, 0, ALTURA_FAIXA))
        self.assertGreater(largura, 2 * LARGURA)                                   # a faixa ocupa a largura toda, não um cartão
        self.assertLess(ALTURA_FAIXA, ALTURA // 2 + 10)
        self.assertEqual(p._celula(1)[:2], (0, ALTURA_FAIXA))                      # a primeira comanda logo abaixo da faixa
        self.assertEqual(p._celula(2)[:2], (LARGURA, ALTURA_FAIXA))                # e a grade segue em colunas
        self.assertEqual(self.texto_do_cartao("0", "total"), "R$ 0,00")            # a faixa continua mostrando total e estado
        self.assertEqual(self.texto_do_cartao("0", "estado"), "Balcão")
        self.assertIsNone(self.texto_do_cartao("0", "rotulo"))                     # sem o número grande de um cartão
        linhas = -(-7 // p._por_linha)
        self.assertEqual(p._altura_total, ALTURA_FAIXA + linhas * ALTURA + 8)

    def test_setas_passam_pela_faixa_do_balcao(self):
        from types import SimpleNamespace
        for n in range(1, 8):
            self.comanda(n)
        self.redimensionar(1700)
        self.cx.carregar_mesas(); self.cx.update()
        p = self.cx.painel_mesas
        chaves = [t["chave"] for t in p.tiles()]
        self.assertEqual(chaves[0], "0")
        p.focar("0")
        p._tecla(SimpleNamespace(keysym="Down", char=""))
        self.assertEqual(p.cursor(), chaves[1])                                    # da faixa, desce para a primeira comanda
        p._tecla(SimpleNamespace(keysym="Down", char=""))
        self.assertEqual(p.cursor(), chaves[1 + p._por_linha])                     # e dali anda uma linha da grade
        p._tecla(SimpleNamespace(keysym="Up", char=""))
        self.assertEqual(p.cursor(), chaves[1])
        p._tecla(SimpleNamespace(keysym="Up", char=""))
        self.assertEqual(p.cursor(), "0")                                          # da primeira linha, sobe para a faixa
        voltou = []
        p._ao_voltar = lambda: voltou.append(True)
        p._tecla(SimpleNamespace(keysym="Up", char=""))
        self.assertEqual(voltou, [True])                                           # e da faixa volta ao campo da posição

    def test_filtro_sem_balcao_mantem_a_grade_sem_faixa(self):
        from src.ui.painel_mesas import ALTURA
        for n in range(1, 4):
            self.comanda(n)
        self.cx.carregar_mesas(); self.cx.update()
        p = self.cx.painel_mesas
        p.var_busca.set("2"); self.cx.update()                                     # a busca esconde o balcão
        self.assertEqual([t["tipo"] for t in p.tiles()], ["comanda"])              # só a comanda 2: o balcão saiu da lista
        self.assertEqual(p._celula(0)[:2], (0, 0))
        self.assertEqual(p._altura_total, ALTURA + 8)

    def test_definir_colunas_muda_a_largura_do_painel(self):
        from src.ui.painel_mesas import LARGURA, RESERVA_BARRA
        p = self.cx.painel_mesas
        p.definir_colunas(2)
        self.assertEqual(int(p.cget("width")), 2 * LARGURA + RESERVA_BARRA + 4)
        p.definir_colunas(0)                                                 # nunca menos de uma coluna
        self.assertEqual(p.colunas, 1)

    def redimensionar(self, largura):
        """Simula a janela com essa largura sem depender do tamanho da tela de quem roda o teste (no Windows do CI o sistema
        encolhe qualquer janela maior que o monitor)."""
        from types import SimpleNamespace
        self.cx._ao_redimensionar(SimpleNamespace(widget=self.cx, width=largura))
        self.cx.update()

    def test_janela_pequena_reduz_as_colunas_do_painel(self):
        self.redimensionar(1000)
        self.assertEqual(self.cx.painel_mesas.colunas, 1)
        self.redimensionar(1700)
        self.assertEqual(self.cx.painel_mesas.colunas, 3)

    def test_cartoes_quebram_em_linhas_conforme_as_colunas(self):
        for n in range(1, 10):
            self.comanda(n)
        self.redimensionar(1700)
        self.cx.carregar_mesas(); self.cx.update()
        p = self.cx.painel_mesas
        self.assertEqual(p._por_linha, 3)
        self.redimensionar(1000)
        self.assertEqual(p._por_linha, 1)


class TesteTextosGuia(BaseCartoes):
    def test_codigo_e_descricao_mostram_o_guia_enquanto_vazios(self):
        self.assertEqual(self.cx.dica_codigo.winfo_manager(), "place")
        self.assertEqual(self.cx.lbl_desc._dica.winfo_manager(), "place")
        self.assertEqual(self.cx.lbl_desc.cget("text"), "")                     # o texto real continua vazio
        self.cx.var_cod.set("1")
        self.assertEqual(self.cx.dica_codigo.winfo_manager(), "")
        self.cx._enter_codigo(); self.cx.update()                               # o produto escolhido preenche a descrição
        self.assertEqual(self.cx.lbl_desc.cget("text"), "SKOL")
        self.assertEqual(self.cx.lbl_desc._dica.winfo_manager(), "")
        self.cx.cancelar_item_pendente(); self.cx.update()
        self.assertEqual(self.cx.lbl_desc._dica.winfo_manager(), "place")
        self.assertEqual(self.cx.dica_codigo.winfo_manager(), "place")


class TesteNavegarEntreComandas(BaseCartoes):
    def setUp(self):
        super().setUp()
        self.comanda(8)
        self.comanda(12)
        self.comanda(27)
        self.cadastrar(180, "Bianca")
        self.dar(180, 30)
        self.cx.carregar_mesas(); self.cx.update()

    def venda_atual(self):
        return self.cx._chave_atual()            # '0' no balcão (a venda dele só nasce no primeiro item)

    def test_proxima_e_anterior_passam_por_clientes_e_garotas(self):
        self.ir_para(12)
        self.cx.navegar_comanda(1)
        self.assertEqual(self.venda_atual(), "27")
        self.cx.navegar_comanda(1)                                           # depois da última comanda vem a garota
        self.assertEqual(self.venda_atual(), "180")
        self.assertIn("COMISSÃO MARCADA NA COMANDA 180", self.cx.faixa.cget("text"))
        self.cx.navegar_comanda(1)                                           # é a última da lista: não dá a volta
        self.assertEqual(self.venda_atual(), "180")
        self.assertIn("última comanda", self.cx.status.cget("text"))
        self.cx.navegar_comanda(-1)
        self.assertEqual(self.venda_atual(), "27")
        self.sem_travar()

    def test_anterior_chega_ao_balcao_e_para(self):
        self.ir_para(8)
        self.cx.navegar_comanda(-1)
        self.assertEqual(self.venda_atual(), "0")
        self.cx.navegar_comanda(-1)
        self.assertIn("primeira comanda", self.cx.status.cget("text"))

    def test_respeita_a_aba_escolhida(self):
        self.ir_para(12)
        self.cx.painel_mesas.var_estado.set("Comissões")
        self.cx.navegar_comanda(1)                                           # só a garota está na lista
        self.assertEqual(self.venda_atual(), "180")
        self.cx.navegar_comanda(-1)                                          # e dela não há anterior na aba
        self.assertEqual(self.venda_atual(), "180")

    def test_lista_sem_resultado_avisa(self):
        self.cx.painel_mesas.var_busca.set("999")
        self.cx.navegar_comanda(1)
        self.assertIn("Não há comandas neste filtro", self.cx.status.cget("text"))

    def test_botoes_e_teclas_de_pagina_fazem_o_mesmo(self):
        self.ir_para(12)
        self.cx.btn_proxima.invoke(); self.cx.update()
        self.assertEqual(self.venda_atual(), "27")
        self.cx.btn_anterior.invoke(); self.cx.update()
        self.assertEqual(self.venda_atual(), "12")
        self.cx.ent_codigo.focus_force(); self.cx.update()
        self.cx.ent_codigo.event_generate("<Next>"); self.cx.update()
        self.assertEqual(self.venda_atual(), "27")
        self.cx.ent_codigo.event_generate("<Prior>"); self.cx.update()
        self.assertEqual(self.venda_atual(), "12")

    def test_nao_deixa_o_balcao_com_itens_para_tras(self):
        self.ir_para(0)
        self.digitar_codigo("1"); self.valor("1")                            # venda de balcão em andamento
        avisos = []
        self.dialogos({"Aviso": lambda w: (avisos.append(self.textos(w)), clicar(w, "OK"))})
        self.cx.navegar_comanda(1); self.cx.update()
        self.assertEqual(self.venda_atual(), "0")
        self.assertTrue(any("Conclua, pague ou cancele" in t for a in avisos for t in a), avisos)

    def test_sair_da_comanda_vazia_da_garota_nao_deixa_venda_fantasma(self):
        self.ir_para(180)
        self.cx.navegar_comanda(-1)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas WHERE posicao = 180 AND status = 'aberta'"), 0)
        self.assertEqual(self.tiles()["180"]["tipo"], "garota")                # o cartão dela continua (a comissão é dela)


class TesteAcoesDaLinha(BaseCartoes):
    def test_enter_no_item_abre_as_acoes_e_cancelar_remove_o_item(self):
        self.comanda(12, (self.skol, 1), (self.agua, 1))
        self.ir_para(12)
        item = self.ctx.caixa.itens(self.cx.venda_id)[0]["id"]
        self.cx.grade.selecionar(item)
        self.dialogos({"Ações do item": escolher_opcao(2), "Cancela Item": "Sim"})
        self.cx._enter_grade(); self.cx.update()
        self.assertEqual(len(self.ctx.caixa.itens(self.cx.venda_id)), 1)
        self.sem_travar()

    def test_duplo_clique_e_o_mesmo_que_enter(self):
        self.assertTrue(self.cx.grade.tree.bind("<Double-1>"))
        self.assertTrue(self.cx.grade.tree.bind("<Return>"))

    def test_enter_sem_linha_escolhida_nao_faz_nada(self):
        self.cx.grade.tree.selection_set(())
        self.cx._enter_grade()
        self.sem_travar()

    def test_enter_na_comissao_pendente_permite_cancelar_o_lancamento(self):
        c = self.dar(180, 25)
        self.ir_para(180)
        self.cx.grade.selecionar(f"c{c}")
        self.dialogos({"Ações da comissão": escolher_opcao(1), "Cancelar comissão": "Sim"})
        self.cx._enter_grade(); self.cx.update()
        self.assertEqual(self.com.pendente(180), 0)
        self.assertEqual(self.banco.valor("SELECT status FROM comissoes_garotas WHERE id = ?", (c,)), "cancelada")
        self.sem_travar()

    def test_enter_na_comissao_pendente_permite_pagar_a_garota(self):
        c = self.dar(180, 25)
        self.ir_para(180)
        self.cx.grade.selecionar(f"c{c}")
        self.robo.quando("Visualizador", lambda w: w.destroy(), vezes=5)
        self.dialogos({"Ações da comissão": escolher_opcao(0), "Pagar comissão": "Pagar"})
        self.cx._enter_grade(); self.cx.update()
        self.assertEqual(self.com.pendente(180), 0)
        self.sem_travar()

    def test_enter_na_comissao_ja_paga_so_avisa(self):
        c = self.dar(180, 25)
        self.com.pagar(180, self.turno, self.ctx.operador_id, False)
        self.ir_para(180)
        self.cx.grade.selecionar(f"c{c}")
        avisos = []
        self.dialogos({"Aviso": lambda w: (avisos.append(self.textos(w)), clicar(w, "OK"))})
        self.cx._enter_grade(); self.cx.update()
        self.assertTrue(any("já foi paga" in t for a in avisos for t in a), avisos)

    def test_seta_para_cima_na_primeira_linha_volta_ao_codigo(self):
        self.comanda(12, (self.skol, 1), (self.agua, 1))
        self.ir_para(12)
        self.cx._foco_grade(); self.cx.grade.selecionar_indice(0); self.cx.update()
        self.assertEqual(self.cx._cima_grade(), "break")
        self.assertIs(self.cx.focus_lastfor(), self.cx.ent_codigo)
        self.cx.grade.selecionar_indice(1)
        self.assertIsNone(self.cx._cima_grade())                             # fora da primeira linha, a seta anda normal


if __name__ == "__main__":
    unittest.main()
