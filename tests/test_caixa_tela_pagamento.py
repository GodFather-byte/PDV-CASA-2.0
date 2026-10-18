"""A tela do caixa renovada (cabeçalho, total e ações na coluna da direita, lista com convite quando vazia) e o seletor de
pagamento (Dinheiro, Débito, Crédito e Pix): nada que o operador digite pode travar o caixa nem fechar a venda com um valor errado."""
from __future__ import annotations

import time
import tkinter as tk
import unittest
from tkinter import ttk
from types import SimpleNamespace
from unittest import mock

from src.core.erros import ErroNegocio
from src.ui import tema
from src.ui.caixa_pagamento import LIMITE_VALOR_CENT, ler_valor_pagamento
from tests.test_ui import BaseUI
from tests.ui_robo import clicar


class TesteLeituraDoValor(unittest.TestCase):
    def test_formatos_aceitos(self):
        casos = {"25": 2500, "25,5": 2550, "25,50": 2550, "25.50": 2550, "1.000": 100000, "1.000,50": 100050,
                 "1.000.000": 100000000, "R$ 10,00": 1000, " 10 ": 1000, ",5": 50, ".5": 50, "0,01": 1}
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(ler_valor_pagamento(texto), esperado)

    def test_formatos_recusados(self):
        for texto in ("", "   ", "abc", "1e5", "-5", "+5", "0", "0,00", "1,2,3", "10,555", "1,5,", "5,", "٣", "inf", "nan",
                      "1..000", "12a", "1 2 3 4,5,6"):
            with self.subTest(texto=texto):
                with self.assertRaises(ValueError):
                    ler_valor_pagamento(texto)

    def test_valor_absurdo_e_recusado_com_mensagem(self):
        with self.assertRaises(ValueError) as c:
            ler_valor_pagamento("9" * 25)
        self.assertIn("alto demais", str(c.exception))
        self.assertEqual(ler_valor_pagamento("1.000.000"), LIMITE_VALOR_CENT)         # o limite em si ainda vale
        with self.assertRaises(ValueError):
            ler_valor_pagamento("1.000.001")


def textos(w) -> list[str]:
    achados = []
    for f in w.winfo_children():
        if isinstance(f, (ttk.Label, tk.Label)):
            achados.append(str(f.cget("text")))
        achados += textos(f)
    return achados


class BasePagamento(BaseUI):
    """Caixa aberto com uma SKOL (R$ 8,00) lançada no balcão."""

    def setUp(self):
        super().setUp()
        self.abrir_turno()
        from src.ui.caixa_ui import JanelaCaixa
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()
        self.cx.var_cod.set("1"); self.cx._enter_codigo(); self.cx.update()
        self.cx.var_qtd.set("1"); self.cx.confirmar_item(); self.cx.update()
        self.dialogos: list[tuple[str, str]] = []              # (título, texto) de cada diálogo que o robô viu
        self.respostas: list[str] = []                         # botões a apertar nos diálogos, na ordem; vazio = só fecha
        self.callback_erros: list[str] = []
        self.root.report_callback_exception = lambda t, v, tb: self.callback_erros.append(f"{t.__name__}: {v}")

    def _dialogo(self, w) -> None:
        self.dialogos.append((w.title(), " ".join(textos(w))))
        if self.respostas:
            clicar(w, self.respostas.pop(0))
        else:
            w.destroy()

    def pagamentos(self):
        return self.ctx.caixa.pagamentos(self.cx.venda_id)

    def pagar(self, passos) -> None:
        """Abre o pagamento e roda `passos(janela)` FORA do ciclo do robô (senão o diálogo de erro nunca seria fechado)."""
        falhas = []

        def acao(j):
            def rodar():
                try:
                    passos(j)
                except Exception as e:  # noqa: BLE001
                    falhas.append(repr(e))
                finally:
                    if j.winfo_exists():
                        j.destroy()
            j.after(30, rodar)
        self.robo.quando("JanelaPagamento", acao)
        self.robo.quando("Dialogo", self._dialogo, vezes=30)
        self.robo.quando("Visualizador", lambda w: w.destroy(), vezes=5)
        self.cx.pagar(); self.cx.update()
        self.assertEqual(falhas, [])
        self.assertEqual(self.callback_erros, [])
        self.sem_travar()

    @staticmethod
    def forma(j, nome: str) -> None:
        f = [i for i in j.grade_formas.tree.get_children() if j.grade_formas.valores(i)[0] == nome][0]
        j.grade_formas.selecionar(f); j._forma_escolhida()


class TesteSeletorDePagamento(BasePagamento):
    def test_as_quatro_formas_aparecem_com_a_tecla_de_cada_uma(self):
        vistas = []
        self.pagar(lambda j: vistas.extend(j.grade_formas.valores(i) for i in j.grade_formas.tree.get_children()))
        self.assertEqual(vistas, [["Dinheiro", "1"], ["Cartão Débito", "2"], ["Cartão Crédito", "3"], ["Pix", "4"]])

    def test_dinheiro_da_troco_e_a_venda_fecha_uma_vez_so(self):
        def passos(j):
            self.forma(j, "Dinheiro")
            j.var_valor.set("10,00"); j._lancar_valor()
            self.assertEqual(j.lbl_troco_rotulo.cget("text"), "Troco:")
            self.assertEqual(j.lbl_troco.cget("text"), "2,00")
            j.fechar_venda()
            j.fechar_venda()                                    # F10 apertado de novo: não pode gravar outra vez
        self.pagar(passos)
        v = self.banco.um("SELECT status, troco_cent, pago_cent FROM vendas")
        self.assertEqual((v["status"], v["troco_cent"], v["pago_cent"]), ("fechada", 200, 1000))
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM vendas WHERE status = 'fechada'"), 1)

    def test_cartao_e_pix_nao_aceitam_mais_do_que_falta(self):
        # o crédito sugere e limita com a taxa de R$ 5,00 (8,00 + 5,00); a falta mostrada continua sem ela até lançar
        for forma, limite in (("Cartão Débito", "8,00"), ("Cartão Crédito", "13,00"), ("Pix", "8,00")):
            with self.subTest(forma=forma):
                self.dialogos.clear()

                def passos(j):
                    self.forma(j, forma)
                    j.var_valor.set("100,00"); j._lancar_valor()
                    self.assertEqual(j.var_valor.get(), limite)              # volta a sugerir o que falta
                    self.assertEqual(j.lbl_troco.cget("text"), "8,00")
                self.pagar(passos)
                self.assertEqual(self.pagamentos(), [])                       # nada ficou gravado: a conta não encalha
                self.assertEqual(self.dialogos[0][0], "Atenção")
                self.assertIn("não dá troco", self.dialogos[0][1])
                self.assertIn(limite, self.dialogos[0][1])

    def test_pagamento_misto_dinheiro_e_cartao(self):
        def passos(j):
            self.forma(j, "Dinheiro"); j.var_valor.set("3,00"); j._lancar_valor()
            self.assertEqual(j.lbl_troco.cget("text"), "5,00")                # falta
            self.forma(j, "Cartão Débito")
            self.assertEqual(j.var_valor.get(), "5,00")
            j._lancar_valor()
            j.fechar_venda()
        self.pagar(passos)
        self.assertEqual(self.banco.valor("SELECT status FROM vendas"), "fechada")
        self.assertEqual(sorted(p["valor_cent"] for p in self.ctx.caixa.pagamentos(self.banco.valor("SELECT id FROM vendas"))), [300, 500])

    def test_troco_alto_pede_confirmacao(self):
        self.respostas = ["Corrigir"]
        def corrigir(j):
            self.forma(j, "Dinheiro")
            j.var_valor.set("1000"); j._lancar_valor()
        self.pagar(corrigir)
        self.assertEqual(self.pagamentos(), [])
        self.assertIn("992,00", self.dialogos[0][1])

        self.respostas = ["Está certo"]
        def confirmar(j):
            self.forma(j, "Dinheiro")
            j.var_valor.set("1000"); j._lancar_valor()
        self.pagar(confirmar)
        self.assertEqual([p["valor_cent"] for p in self.pagamentos()], [100000])

    def test_valor_digitado_errado_avisa_na_janela_e_nao_grava(self):
        casos = {"1e5": "inválido", "abc": "inválido", "-5": "inválido", "": "Digite o valor", "0": "maior que zero",
                 "9" * 25: "alto demais", "10,555": "inválido"}
        def passos(j):
            self.forma(j, "Dinheiro")
            for texto, trecho in casos.items():
                j.var_valor.set(texto); j._lancar_valor()
                self.assertIn(trecho, j.lbl_msg.cget("text"), texto)
        self.pagar(passos)
        self.assertEqual(self.pagamentos(), [])
        self.assertEqual(self.dialogos, [])                                   # só a mensagem na janela, sem diálogo

    def test_lancar_sem_escolher_a_forma_orienta(self):
        def passos(j):
            j.grade_formas.tree.selection_set(())
            j.var_valor.set("8,00"); j._lancar_valor()
            self.assertIn("Escolha a forma", j.lbl_msg.cget("text"))
        self.pagar(passos)
        self.assertEqual(self.pagamentos(), [])

    def test_atalhos_numero_e_inicial(self):
        def passos(j):
            def tecla(c):
                j._tecla_forma(SimpleNamespace(char=c))
                return j.grade_formas.valores(j.grade_formas.selecionado())[0]
            self.assertEqual(tecla("3"), "Cartão Crédito")
            self.assertEqual(tecla("4"), "Pix")
            self.assertEqual(tecla("1"), "Dinheiro")
            self.assertEqual(tecla("9"), "Dinheiro")                             # número sem forma: ignora
            self.assertEqual(tecla("c"), "Cartão Crédito")                      # C = Crédito
            self.assertEqual(tecla("p"), "Pix")
            self.assertEqual(tecla("d"), "Dinheiro")                            # D alterna entre Dinheiro e Débito
            self.assertEqual(tecla("d"), "Cartão Débito")
            self.assertEqual(tecla("d"), "Dinheiro")
            self.assertEqual(tecla("x"), "Dinheiro")                            # sem forma com X: fica onde está
        self.pagar(passos)

    def test_remover_pagamento_com_e_sem_selecao(self):
        def passos(j):
            j._remover_pagamento()
            self.assertIn("Não há pagamento", j.lbl_msg.cget("text"))
            self.forma(j, "Dinheiro"); j.var_valor.set("3,00"); j._lancar_valor()
            self.forma(j, "Pix"); j.var_valor.set("2,00"); j._lancar_valor()
            self.assertEqual(len(self.pagamentos()), 2)
            j._remover_pagamento()                                                # sem seleção: o último lançado
            self.assertEqual([p["tipo"] for p in self.pagamentos()], ["Dinheiro"])
            self.assertIn("removido", j.lbl_msg.cget("text"))
            j.grade_pag.selecionar_indice(0)
            j._remover_pagamento()
            self.assertEqual(self.pagamentos(), [])
        self.pagar(passos)

    def test_remover_pagamento_que_o_sistema_recusa_mostra_o_motivo(self):
        def passos(j):
            self.forma(j, "Dinheiro"); j.var_valor.set("3,00"); j._lancar_valor()
            with mock.patch.object(j.caixa, "remover_pagamento", side_effect=ErroNegocio("Pagamento de turno fechado.")):
                j._remover_pagamento()
            self.assertEqual(len(self.pagamentos()), 1)
        self.pagar(passos)
        self.assertIn("turno fechado", self.dialogos[0][1])

    def test_sem_nenhuma_forma_habilitada_explica_e_nao_abre_janela_vazia(self):
        self.banco.executar("UPDATE tipos_pagamento SET ativo = 0")
        self.robo.quando("Dialogo", self._dialogo, vezes=5)
        self.cx.pagar(); self.cx.update()
        self.assertEqual([w for w in self.cx.winfo_children() if type(w).__name__ == "JanelaPagamento"], [])
        self.assertIn("Nenhuma forma de pagamento", self.dialogos[0][1])
        self.assertEqual(self.callback_erros, [])
        self.cx.var_cod.set("2"); self.cx._enter_codigo(); self.cx.update()        # o caixa continua utilizável
        self.assertEqual(str(self.cx.ent_qtd.cget("state")), "normal")
        self.sem_travar()

    def test_falha_ao_preparar_o_cupom_nao_deixa_o_caixa_pendurado(self):
        def passos(j):
            self.forma(j, "Dinheiro"); j.var_valor.set("8,00"); j._lancar_valor()
            with mock.patch.object(self.ctx.impressao, "cupom", side_effect=RuntimeError("falha no cupom")), \
                    mock.patch("src.core.registro.registrar_excecao") as registro:
                j.fechar_venda()
            self.assertEqual(registro.call_args.kwargs["origem"], "pagamento")                  # ficou no log para o suporte
        self.pagar(passos)
        self.assertEqual(self.banco.valor("SELECT status FROM vendas"), "fechada")             # a venda está gravada
        self.assertIn("foi gravada", self.dialogos[0][1])
        self.assertIsNone(self.cx.venda())                                                      # e a tela do caixa já voltou ao balcão limpo
        self.assertEqual(self.cx.grade.total(), 0)

    def test_erro_ao_montar_a_janela_nao_deixa_janela_nem_trava_para_tras(self):
        from src.ui.caixa_pagamento import JanelaPagamento
        with mock.patch.object(JanelaPagamento, "_montar", side_effect=RuntimeError("quebrou")):
            with self.assertRaises(RuntimeError):
                JanelaPagamento(self.cx, self.ctx, self.cx.venda_id)
        self.assertEqual([w for w in self.cx.winfo_children() if type(w).__name__ == "JanelaPagamento"], [])
        self.assertIsNone(self.cx.grab_current())                                               # nenhuma trava de teclado esquecida

    def test_janela_mae_escondida_nao_trava_a_espera_da_janela_modal(self):
        mae = tk.Toplevel(self.root)
        mae.withdraw()
        filha = tk.Toplevel(mae)
        filha.transient(mae)                       # transient de janela escondida: nunca fica visível
        self.addCleanup(lambda: [w.destroy() for w in (filha, mae) if w.winfo_exists()])
        rede = self.root.after(1500, lambda: filha.winfo_exists() and filha.destroy())   # rede de segurança: uma espera infinita acabaria aqui
        self.addCleanup(self.root.after_cancel, rede)
        t0 = time.monotonic()
        tema.modalizar(filha)
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertTrue(filha.winfo_exists())


class TesteTelaDoCaixa(BasePagamento):
    def test_acoes_do_dia_a_dia_ficam_a_vista_e_as_demais_em_mais_opcoes(self):
        self.assertEqual([t[0] for t in self.cx.tarefas[:3]],
                         ["Pagar (F12)", "Lançar produto", "Escolher comanda (F4)"])
        fixos = self.cx._n_fixos
        nomes = [t[0] for t in self.cx.tarefas]
        for esperado in ("Pré-Conta (F8)", "Transfere (F10)", "Repique (F9)", "Comissões", "Sangria (F7)", "Gaveta (F11)",
                         "Consulta Comanda", "Cancelar"):
            self.assertLess(nomes.index(esperado), fixos, esperado)
        self.assertFalse(self.cx.opcoes.winfo_viewable())
        self.assertTrue(all(b.winfo_viewable() for b in self.cx.botoes_tarefa[:fixos]))     # a coluna da direita
        self.assertTrue(all(not b.winfo_viewable() for b in self.cx.botoes_tarefa[fixos:-1]))   # o resto, só na janela
        leitor = self.cx.leitor
        self.cx.btn_opcoes.invoke(); self.cx.update()
        self.assertTrue(self.cx.opcoes.winfo_viewable())
        i = [t[0] for t in self.cx.tarefas].index("Leitor (F3)")
        self.cx.botoes_tarefa[i].invoke(); self.cx.update()
        self.assertEqual(self.cx.leitor, not leitor)
        self.assertFalse(self.cx.opcoes.winfo_viewable())
        self.assertEqual(len(self.ctx.caixa.itens(self.cx.venda_id)), 1)

    def test_navegacao_por_setas_abre_opcoes_e_esc_preserva_a_venda(self):
        venda_id = self.cx.venda_id
        self.cx._entrar_barra()
        for _ in range(self.cx._n_fixos):                 # passa pelas ações à vista e chega às de "Mais opções"
            self.cx._barra_mover(1)
        self.cx.update()
        self.assertTrue(self.cx.opcoes.winfo_viewable())
        self.cx.opcoes.event_generate("<Escape>"); self.cx.update()
        self.assertFalse(self.cx.opcoes.winfo_viewable())
        self.assertIsNone(self.cx.indice_barra)
        self.assertEqual(self.cx.venda_id, venda_id)

    def test_voltar_ao_codigo_fecha_opcoes_e_enter_continua_lancando_produto(self):
        self.cx.btn_opcoes.invoke(); self.cx.update()
        self.cx.ent_codigo.focus_force(); self.cx.update()
        self.assertFalse(self.cx.opcoes.winfo_viewable())
        self.assertIsNone(self.cx.indice_barra)
        self.cx.var_cod.set("1")
        self.cx.ent_codigo.event_generate("<Return>"); self.cx.update()
        self.assertEqual(self.cx.produto["id"], self.skol)
        self.assertEqual(str(self.cx.ent_qtd.cget("state")), "normal")

    def test_pagamento_parcial_mostra_saldo_e_acerto_sem_fechar_comanda(self):
        self.banco.cfg_set("posicao_padrao", "mesa")
        vid, _ = self.ctx.caixa.abrir_mesa(3, comanda=True)
        self.ctx.caixa.adicionar_item(vid, self.skol, 1)
        pix = self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = 'Pix'")
        pid = self.ctx.caixa.adicionar_pagamento(vid, pix, 500)
        self.cx.venda_id = vid; self.cx.recarregar(); self.cx.update()
        tile = next(t for t in self.cx.painel_mesas.tiles() if t["chave"] == "C3")
        self.assertEqual((tile["estado"], tile["falta"]), ("parcial", "3,80"))
        self.assertIn("Falta receber: R$ 3,80", self.cx.lbl_recebido.cget("text"))
        self.assertEqual(self.ctx.caixa.obter(vid)["status"], "aberta")
        self.ctx.caixa.remover_pagamento(pid)
        self.cx.recarregar(); self.cx.update()
        tile = next(t for t in self.cx.painel_mesas.tiles() if t["chave"] == "C3")
        self.assertEqual(tile["estado"], "consumindo")
        self.ctx.caixa.adicionar_pagamento(vid, pix, 880)
        self.cx.recarregar(); self.cx.update()
        tile = next(t for t in self.cx.painel_mesas.tiles() if t["chave"] == "C3")
        self.assertEqual((tile["estado"], tile["falta"]), ("acerto", "0,00"))
        self.assertEqual(self.ctx.caixa.obter(vid)["status"], "aberta")

    def test_filtro_e_busca_selecionam_a_comanda_correta(self):
        self.banco.cfg_set("posicao_padrao", "mesa")
        ids = {}
        for n in (7, 8):
            ids[n], _ = self.ctx.caixa.abrir_mesa(n, comanda=True)
            self.ctx.caixa.adicionar_item(ids[n], self.skol, 1)
        self.ctx.caixa.enviar_conta(ids[8])
        self.cx.venda_id = ids[7]; self.cx.recarregar(); self.cx.update()
        p = self.cx.painel_mesas
        p.var_estado.set("Aguardando acerto")
        self.assertEqual([t["chave"] for t in p.tiles()], ["C8"])
        p.focar("C8"); p._tecla(SimpleNamespace(keysym="Return", char=""))
        self.assertEqual(self.cx.venda_id, ids[8])
        p.var_estado.set("Todas"); p.var_busca.set("7")
        self.assertEqual([t["chave"] for t in p.tiles()], ["C7"])
        p.var_busca.set("999")
        self.assertEqual(p.tiles(), [])
        p.var_busca.set("")
        self.assertEqual(len(p.tiles()), 3)

    def test_tela_compacta_preserva_lista_total_e_rolagem_de_comandas(self):
        for n in range(1, 15):
            vid, _ = self.ctx.caixa.abrir_mesa(n, comanda=True)
            self.ctx.caixa.adicionar_item(vid, self.skol, 1)
        self.cx.carregar_mesas()
        self.cx.state("normal")
        self.cx.geometry("1000x600"); self.cx.update()
        self.assertGreater(self.cx.grade.tree.winfo_height(), 50)
        self.assertIn("tot", self.cx.grade.tree.cget("displaycolumns"))
        self.assertTrue(self.cx.botoes_tarefa[0].winfo_viewable())
        p = self.cx.painel_mesas
        self.assertGreater(p._altura_total, p.canvas.winfo_height())      # as comandas não cabem: o painel rola
        p.focar(); p._tecla(SimpleNamespace(keysym="End", char=""))
        self.assertGreater(p.canvas.yview()[0], 0)
        antes = p.canvas.yview()[0]
        mesas = self.ctx.caixa.mesas()
        mesas[0]["minutos_parada"] += 1
        p.atualizar(mesas, self.ctx.caixa.balcao_aberto(), self.cx._chave_atual())
        self.assertAlmostEqual(p.canvas.yview()[0], antes)

    def test_barra_de_acoes_na_ordem_da_tela_com_pagar_e_sair_em_destaque(self):
        nomes = [t[0] for t in self.cx.tarefas]
        self.assertEqual(nomes[0], "Pagar (F12)")
        self.assertEqual(nomes[-1], "Sair")
        self.assertEqual(len(self.cx.botoes_tarefa), len(nomes))
        self.assertEqual(str(self.cx.botoes_tarefa[0].cget("style")), "Cx.Pagar.TButton")
        self.assertEqual(str(self.cx.botoes_tarefa[-1].cget("style")), "Cx.Perigo.TButton")
        self.assertIs(self.cx.botoes_tarefa[-1].master, self.cx.slot_sair)         # Sair no canto do cabeçalho

    def test_setas_destacam_a_acao_escolhida_pelo_teclado(self):
        self.cx._entrar_barra()
        self.assertEqual(str(self.cx.botoes_tarefa[0].cget("style")), "Cx.Sel.TButton")
        self.cx._barra_mover(1)
        self.assertEqual(str(self.cx.botoes_tarefa[0].cget("style")), "Cx.Pagar.TButton")      # volta ao estilo de origem
        self.assertEqual(str(self.cx.botoes_tarefa[1].cget("style")), "Cx.Sel.TButton")
        self.cx._barra_mover(-1)
        self.cx._barra_mover(-1)                                                                # volta ao fim: o Sair
        self.assertEqual(str(self.cx.botoes_tarefa[-1].cget("style")), "Cx.Sel.TButton")
        self.cx._sair_barra()
        self.assertEqual(str(self.cx.botoes_tarefa[-1].cget("style")), "Cx.Perigo.TButton")

    def test_lista_vazia_mostra_o_convite_e_some_com_o_primeiro_item(self):
        self.assertEqual(self.cx.lbl_vazio.winfo_manager(), "")                  # a SKOL do setUp já está lançada
        self.cx.venda_id = None
        self.cx.recarregar()
        self.assertEqual(self.cx.lbl_vazio.winfo_manager(), "place")
        self.assertIn("Nenhum item", self.cx.lbl_vazio.cget("text"))

    def test_total_e_troco_no_cartao_da_direita(self):
        self.assertEqual(self.cx.lbl_total.cget("text"), "8,00")
        self.assertEqual(self.cx.lbl_troco.cget("text"), "0,00")
        self.assertEqual(self.cx.lbl_loja.cget("text"), "CASA DE TESTE")

    def test_tela_estreita_economiza_espaco_dos_campos(self):
        """As duas larguras são simuladas: o resultado não pode depender do tamanho da tela de quem roda o teste."""
        from src.ui.caixa_ui import JanelaCaixa
        janelas = {}
        for largura in (1024, 1920):
            with mock.patch.object(tk.Misc, "winfo_screenwidth", return_value=largura):
                janelas[largura] = JanelaCaixa(self.root, self.ctx)
            self.addCleanup(janelas[largura].destroy)
            janelas[largura].update()
        estreita, larga = janelas[1024], janelas[1920]
        self.assertTrue(estreita.compacto)
        self.assertFalse(larga.compacto)
        botoes_do_cartao = lambda cx: [w for w in cx.cartao_entrada.winfo_children() if isinstance(w, ttk.Button)]
        self.assertEqual(botoes_do_cartao(estreita), [])                      # o "Consultar" fica só na coluna de ações
        self.assertTrue(botoes_do_cartao(larga))

    def test_estilos_escuros_so_valem_para_quem_pede(self):
        s = ttk.Style(self.root)
        self.assertNotEqual(s.lookup("Cx.TButton", "background"), s.lookup("TButton", "background"))
        self.assertEqual(s.lookup("Cx.Treeview", "rowheight"), 30)
        self.assertEqual(s.lookup("CxForma.Treeview", "rowheight"), 46)
        self.assertEqual(str(self.cx.grade.tree.cget("style")), "Cx.Treeview")


if __name__ == "__main__":
    unittest.main()
