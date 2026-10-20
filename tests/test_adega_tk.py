"""Balcão Tk da adega: preços, temperatura e troca de cascos pelo teclado/leitor."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from src.controllers.perfil_controller import PerfilController
from src.ui import adega_dialogos
from src.ui.caixa_ui import JanelaCaixa
from tests.test_comissao_na_tela import BaseNaTela
from tests.ui_robo import clicar, entradas


class BaseAdegaTk(BaseNaTela):
    def setUp(self):
        # O robô usa saída de impressão isolada dentro do projeto, não na pasta temporária do sistema.
        saida = Path.cwd() / ".teste_adega_tk_saida"
        saida.mkdir(exist_ok=True)
        with mock.patch("tests.test_ui.tempfile.mkdtemp", return_value=str(saida)):
            super().setUp()
        self.cx.destroy()
        PerfilController(self.banco, self.ctx.operador_id).aplicar("adega")
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()

    def bebida(self, **campos):
        p = dict(self.ctx.produtos.por_id(self.skol))
        p.update(campos)
        return p

    def selecionar(self, p, qtd="6"):
        self.cx.selecionar_produto(p, qtd)
        self.cx.update()


class TesteBalcaoAdegaTk(BaseAdegaTk):
    def test_resumo_e_acoes_sem_abrir_mais_opcoes(self):
        cx = self.cx
        self.assertTrue(cx.perfil_adega)
        self.assertFalse(cx.ent_pos.winfo_ismapped())
        self.assertIn("6*789", cx.lbl_oferta.cget("text"))
        self.assertIn("Quantidade: 0", cx.lbl_resumo_adega.cget("text"))
        for nome in ("Pagar (F12)", "Delivery (F6)", "Caderneta (F5)"):
            i = next(i for i, t in enumerate(cx.tarefas) if t[0] == nome)
            self.assertTrue(cx.botoes_tarefa[i].winfo_ismapped(), nome)
        self.assertIn("Retornável", cx.lbl_vazio.cget("text"))

    def test_previa_informa_dois_precos_e_faixas_por_temperatura(self):
        self.cx.leitor = False
        self.cx.selecionar_produto(self.bebida(preco_gelada_cent=950, atacado_qtd=6, preco_atacado_cent=700,
                                              atacado_gelada_qtd=12, preco_atacado_gelada_cent=850,
                                              casco_produto_id=self.agua))
        texto = self.cx.lbl_oferta.cget("text")
        for esperado in ("Natural: R$ 8,00", "Gelada: R$ 9,50", "Atacado natural: 6+", "R$ 7,00/un",
                         "Atacado gelada: 12+", "R$ 8,50/un", "Retornável"):
            self.assertIn(esperado, texto)
        self.cx.cancelar_item_pendente()
        self.assertIn("6*789", self.cx.lbl_oferta.cget("text"))

    def test_atacado_nao_e_prometido_na_entrega(self):
        self.cx.venda_id = self.ctx.caixa.abrir_balcao()
        self.banco.atualizar("vendas", self.cx.venda_id, {"modalidade": "entrega"})
        self.cx.leitor = False
        self.cx.selecionar_produto(self.bebida(atacado_qtd=6, preco_atacado_cent=700))
        self.assertIn("somente no balcão", self.cx.lbl_oferta.cget("text"))
        self.assertNotIn("R$ 7,00", self.cx.lbl_oferta.cget("text"))

    def test_resumo_e_grade_mostram_temperatura_atacado_e_economia(self):
        self.digitar_codigo("6*1")
        itens = self.ctx.caixa.itens(self.cx.venda_id)
        itens[0].update(temperatura="gelada", preco_base_cent=950, preco_unit_cent=850, total_cent=5100)
        with mock.patch.object(type(self.ctx.caixa), "itens", return_value=itens):
            self.cx.recarregar()
        self.assertIn("[Gelada · Atacado]", self.linhas()[0][1])
        texto = self.cx.lbl_resumo_adega.cget("text")
        for esperado in ("Quantidade: 6", "Natural: 0", "Gelada: 6", "Economia no atacado: R$ 6,00"):
            self.assertIn(esperado, texto)

    def test_recarrega_item_migrado_com_preco_base_nulo(self):
        self.digitar_codigo("6*1")
        self.banco.executar("UPDATE itens_venda SET preco_base_cent = NULL WHERE venda_id = ?", (self.cx.venda_id,))
        self.cx.recarregar()
        self.cx.update()
        item = self.ctx.caixa.itens(self.cx.venda_id)[0]
        self.assertIsNone(item["preco_base_cent"])
        self.assertEqual(self.linhas()[0][1], "SKOL")                       # sem preço gelada, sem etiqueta de temperatura
        self.assertEqual(self.cx.lbl_total.cget("text"), "48,00")
        resumo = self.cx.lbl_resumo_adega.cget("text")
        self.assertIn("Quantidade: 6", resumo)
        self.assertIn("Natural: 6", resumo)
        self.assertNotIn("Economia no atacado", resumo)
        self.sem_travar()

    def test_demais_perfis_preservam_o_layout(self):
        self.cx.destroy()
        PerfilController(self.banco, self.ctx.operador_id).aplicar("comercio")
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()
        self.assertFalse(self.cx.perfil_adega)
        self.assertFalse(hasattr(self.cx, "lbl_resumo_adega"))
        self.assertFalse(hasattr(self.cx, "lbl_oferta"))
        self.digitar_codigo("1")
        self.valor("2")
        self.assertEqual(self.linhas()[0][1], "SKOL")

    def test_perfil_com_mesas_preserva_painel_e_fluxo(self):
        self.cx.destroy()
        PerfilController(self.banco, self.ctx.operador_id).aplicar("boate")
        self.cx = JanelaCaixa(self.root, self.ctx)
        self.cx.update()
        self.assertTrue(self.cx.com_mesas)
        self.assertFalse(self.cx.perfil_adega)
        self.assertTrue(self.cx.ent_pos.winfo_ismapped())
        self.assertFalse(hasattr(self.cx, "lbl_resumo_adega"))
        self.posicao("M5")
        self.digitar_codigo("1")
        self.valor("2")
        self.assertEqual(self.ctx.caixa.obter(self.cx.venda_id)["modalidade"], "mesa")
        self.assertEqual(self.linhas()[0][1], "SKOL")

    def test_atalhos_e_resumo_cabem_em_notebook(self):
        self.cx.state("normal")
        self.cx.geometry("1180x678")
        self.cx.update()
        for w in (self.cx.lbl_resumo_adega, self.cx.btn_opcoes, self.cx.lbl_oferta,
                  self.cx.ent_codigo, self.cx.ent_qtd, self.cx.lbl_preco):
            with self.subTest(widget=str(w)):
                self.assertTrue(w.winfo_ismapped())
                self.assertLessEqual(w.winfo_rooty() + w.winfo_height(),
                                     self.cx.status.winfo_rooty())
                self.assertLessEqual(w.winfo_rootx() + w.winfo_width(),
                                     self.cx.winfo_rootx() + self.cx.winfo_width())
        self.assertGreater(self.cx.grade.tree.winfo_height(), 100)

    def test_produto_simples_nao_abre_dialogos_nem_passa_opcoes_novas(self):
        with mock.patch("src.ui.caixa_ui.adega_dialogos.pedir_temperatura") as temp, \
                mock.patch("src.ui.caixa_ui.adega_dialogos.pedir_cascos") as cascos, \
                mock.patch.object(self.cx, "_lancar", return_value=1) as lancar:
            self.selecionar(self.bebida())
        temp.assert_not_called()
        cascos.assert_not_called()
        lancar.assert_called_once_with(self.skol, 6.0, None)

    def test_leitor_pergunta_temperatura_e_lanca_uma_unidade(self):
        self.cx.leitor = True
        self.dialogos({"Temperatura da bebida": "Gelada"})
        with mock.patch.object(self.cx, "_lancar", return_value=1) as lancar:
            self.cx.selecionar_produto(self.bebida(preco_gelada_cent=950))
        lancar.assert_called_once_with(self.skol, 1.0, None, temperatura="gelada")
        self.sem_travar()

    def test_quantidade_antes_do_codigo_escolhe_natural_e_cascos_em_uma_chamada(self):
        self.dialogos({"Temperatura da bebida": "Natural", "Cascos / vasilhames": "Confirmar"})
        with mock.patch.object(self.cx, "_lancar", return_value=1) as lancar:
            self.selecionar(self.bebida(preco_gelada_cent=950, casco_produto_id=self.agua))
        lancar.assert_called_once_with(self.skol, 6.0, None, temperatura="natural", quantidade_cascos=0)
        self.sem_travar()

    def test_cancelar_temperatura_nao_cria_venda_e_limpa_entrada(self):
        self.dialogos({"Temperatura da bebida": "Cancelar"})
        with mock.patch.object(type(self.ctx.caixa), "adicionar_item") as adicionar:
            self.selecionar(self.bebida(preco_gelada_cent=950, casco_produto_id=self.agua))
        adicionar.assert_not_called()
        self.assertIsNone(self.cx.venda_id)
        self.assertIsNone(self.cx.produto)
        self.assertEqual(self.cx.var_cod.get(), "")
        self.sem_travar()

    def test_cancelar_cascos_depois_de_gelada_nao_lanca_bebida(self):
        self.dialogos({"Temperatura da bebida": "Gelada", "Cascos / vasilhames": "Cancelar"})
        with mock.patch.object(type(self.ctx.caixa), "adicionar_item") as adicionar:
            self.selecionar(self.bebida(preco_gelada_cent=950, casco_produto_id=self.agua))
        adicionar.assert_not_called()
        self.assertIsNone(self.cx.venda_id)
        self.sem_travar()

    def test_quantidade_invalida_nao_abre_dialogos(self):
        with mock.patch("src.ui.caixa_ui.adega_dialogos.pedir_temperatura") as temp, \
                mock.patch.object(type(self.ctx.caixa), "adicionar_item") as adicionar:
            for qtd in ("0", "-1", "1,5"):
                self.selecionar(self.bebida(preco_gelada_cent=950), qtd)
        temp.assert_not_called()
        adicionar.assert_not_called()
        self.assertIsNone(self.cx.venda_id)

    def test_opcoes_encaminhadas_ao_core_sem_lancamento_separado(self):
        with mock.patch.object(type(self.ctx.caixa), "adicionar_item", return_value=10) as adicionar, \
                mock.patch.object(self.cx, "_enviar_remoto"):
            self.cx._lancar(self.skol, 6, None, temperatura="gelada", quantidade_cascos=2)
        adicionar.assert_called_once_with(self.cx.venda_id, self.skol, 6, partes=None,
                                          temperatura="gelada", quantidade_cascos=2)

    def test_venda_real_com_casco_e_preco_gelado_de_atacado(self):
        self.banco.atualizar("produtos", self.skol, {"preco_gelada_cent": 950, "atacado_gelada_qtd": 6,
                                                   "preco_atacado_gelada_cent": 850, "casco_produto_id": self.agua})

        def cascos(w):
            entrada = entradas(w)[0]
            entrada.delete(0, "end")
            entrada.insert(0, "2")
            self.assertIn("Cancelar a bebida NÃO cancela o casco (nem o contrário).",
                          "\n".join(self.textos(w)))
            clicar(w, "Confirmar")

        self.dialogos({"Temperatura da bebida": "Gelada", "Cascos / vasilhames": cascos})
        self.digitar_codigo("6*1")
        itens = self.ctx.caixa.itens(self.cx.venda_id)
        self.assertEqual(len(itens), 2)
        bebida = next(i for i in itens if i["produto_id"] == self.skol)
        casco = next(i for i in itens if i["produto_id"] == self.agua)
        self.assertEqual((bebida["temperatura"], bebida["quantidade"], bebida["preco_unit_cent"]), ("gelada", 6, 850))
        self.assertEqual((casco["quantidade"], casco["total_cent"]), (2, 700))
        self.assertEqual(self.ctx.caixa.obter(self.cx.venda_id)["total_cent"], 5800)
        self.assertTrue(bebida["observacao"].startswith("Gelada"))
        self.assertIn("Economia no atacado: R$ 6,00", self.cx.lbl_resumo_adega.cget("text"))
        self.sem_travar()

    def test_repetir_bipe_agrupa_e_atacado_atualiza_resumo(self):
        self.banco.atualizar("produtos", self.skol, {"atacado_qtd": 6, "preco_atacado_cent": 700})
        self.cx.leitor = True
        for _ in range(6):
            self.digitar_codigo("1")
        itens = self.ctx.caixa.itens(self.cx.venda_id)
        self.assertEqual([(i["quantidade"], i["preco_unit_cent"]) for i in itens], [(6, 700)])
        self.assertEqual(len(self.linhas()), 1)
        self.assertEqual(self.linhas()[0][1], "SKOL  [Atacado]")
        self.assertIn("Economia no atacado: R$ 6,00", self.cx.lbl_resumo_adega.cget("text"))
        self.assertIn("a partir de 6 un", self.linhas()[0][6])
        self.assertIn("economia nesta linha: R$ 6,00", self.linhas()[0][6])
        self.assertIn("a partir de 6 un", self.cx.lbl_detalhe_preco.cget("text"))

    def test_detalhe_de_preco_visivel_em_notebook_e_por_selecao(self):
        self.cx.state("normal")
        self.cx.geometry("1180x678")
        self.banco.atualizar("produtos", self.skol, {"atacado_qtd": 6, "preco_atacado_cent": 700})
        self.digitar_codigo("6*1")
        self.digitar_codigo("2")
        self.cx.grade.tree.selection_set(self.ctx.caixa.itens(self.cx.venda_id)[0]["id"])
        self.cx.update()
        self.assertIn("Atacado natural: a partir de 6 un", self.cx.lbl_detalhe_preco.cget("text"))
        self.assertTrue(self.cx.lbl_detalhe_preco.winfo_ismapped())
        self.assertLessEqual(self.cx.lbl_detalhe_preco.winfo_rooty() + self.cx.lbl_detalhe_preco.winfo_height(),
                             self.cx.status.winfo_rooty())
        self.assertGreater(self.cx.grade.tree.winfo_height(), 100)

    def test_bebida_com_dois_precos_mostra_natural_e_a_observacao_nao_repete_gelada(self):
        self.banco.atualizar("produtos", self.skol, {"preco_gelada_cent": 950})
        vid = self.ctx.caixa.abrir_balcao()
        self.cx.venda_id = vid
        self.ctx.caixa.adicionar_item(vid, self.skol, 1)
        gelada = self.ctx.caixa.adicionar_item(vid, self.skol, 1, temperatura="gelada", observacao="sem copo")
        self.ctx.caixa.adicionar_item(vid, self.agua, 1)
        self.cx.recarregar()
        linhas = self.linhas()
        self.assertEqual([l[1] for l in linhas], ["SKOL  [Natural]", "SKOL  [Gelada]", "AGUA"])
        self.assertEqual([l[6] for l in linhas], ["", "sem copo", ""])
        self.assertTrue(self.ctx.caixa.itens(vid)[1]["observacao"].startswith("Gelada - "))   # no cupom continua inteira
        self.assertEqual(gelada, self.ctx.caixa.itens(vid)[1]["id"])

    def test_natural_e_gelada_ficam_em_linhas_distintas(self):
        self.banco.atualizar("produtos", self.skol, {"preco_gelada_cent": 950})
        for escolha in ("Natural", "Gelada"):
            self.dialogos({"Temperatura da bebida": escolha})
            self.digitar_codigo("2*1")
        itens = self.ctx.caixa.itens(self.cx.venda_id)
        self.assertEqual({i["temperatura"] for i in itens}, {"natural", "gelada"})
        self.assertEqual(self.ctx.caixa.obter(self.cx.venda_id)["total_cent"], 3500)
        texto = self.cx.lbl_resumo_adega.cget("text")
        self.assertIn("Natural: 2,000  ·  Gelada: 2,000", texto)
        self.sem_travar()

    def test_cancelar_dialogo_preserva_venda_existente(self):
        self.digitar_codigo("2*2")
        vid = self.cx.venda_id
        self.banco.atualizar("produtos", self.skol, {"preco_gelada_cent": 950, "casco_produto_id": self.agua})
        antes = self.ctx.caixa.itens(vid)
        self.dialogos({"Temperatura da bebida": "Gelada", "Cascos / vasilhames": "Cancelar"})
        self.digitar_codigo("6*1")
        self.assertEqual(self.ctx.caixa.itens(vid), antes)
        self.assertEqual(self.cx.venda_id, vid)
        self.assertEqual(self.ctx.caixa.obter(vid)["total_cent"], 700)
        self.sem_travar()


class TesteDialogosAdegaTk(BaseAdegaTk):
    def test_atalhos_de_cascos_atualizam_previa_sem_confirmar(self):
        def responder(w):
            self.assertIn("Impacto dos cascos: + R$ 0,00", self.textos(w))
            clicar(w, "Sem troca (F3)")
            self.assertEqual(entradas(w)[0].get(), "6")
            self.assertIn("Impacto dos cascos: + R$ 48,00", self.textos(w))
            clicar(w, "Todas trocas (F2)")
            self.assertEqual(entradas(w)[0].get(), "0")
            w.focus_force()
            w.event_generate("<KeyPress-F3>")
            self.assertEqual(entradas(w)[0].get(), "6")
            w.event_generate("<KeyPress-F2>")
            self.assertEqual(entradas(w)[0].get(), "0")
            entrada = entradas(w)[0]
            entrada.delete(0, "end")
            entrada.insert(0, "2")
            self.assertIn("Impacto dos cascos: + R$ 16,00", self.textos(w))
            clicar(w, "Confirmar")
        self.robo.quando("Dialogo", responder)
        self.assertEqual(adega_dialogos.pedir_cascos(self.cx, self.bebida(), self.bebida(), 6), 2)
        self.sem_travar()

    def test_cascos_fracionados_preservam_limite_arredondado_para_baixo(self):
        def responder(w):
            self.assertIn("A fração da bebida não gera casco: no máximo 2 casco(s).", self.textos(w))
            clicar(w, "Sem troca (F3)")
            self.assertIn("Impacto dos cascos: + R$ 16,00", self.textos(w))
            clicar(w, "Confirmar")
        self.robo.quando("Dialogo", responder)
        self.assertEqual(adega_dialogos.pedir_cascos(self.cx, self.bebida(), self.bebida(), 2.5), 2)

    def test_cascos_aceita_zero_parcial_e_todos(self):
        for qtd in (0, 2, 6):
            with self.subTest(qtd=qtd):
                def responder(w, valor=qtd):
                    entrada = entradas(w)[0]
                    entrada.delete(0, "end")
                    entrada.insert(0, str(valor))
                    clicar(w, "Confirmar")
                self.robo.quando("Dialogo", responder)
                resultado = adega_dialogos.pedir_cascos(self.cx, self.bebida(), self.bebida(), 6)
                self.assertEqual(resultado, qtd)
        self.sem_travar()

    def test_cascos_recusa_fracao_negativo_acima_da_quantidade_e_vazio(self):
        for valor in ("1,5", "1.5", "-1", "7", "", "nan", "9" * 5000):
            with self.subTest(valor=valor):
                def responder(w, texto=valor):
                    entrada = entradas(w)[0]
                    entrada.delete(0, "end")
                    entrada.insert(0, texto)
                    clicar(w, "Confirmar")
                    self.assertTrue(w.winfo_exists())
                    self.assertIn("Informe um número inteiro de 0 a 6.", self.textos(w))
                    self.assertIn("Impacto indisponível: corrija a quantidade.", self.textos(w))
                    entrada.delete(0, "end")
                    entrada.insert(0, "2")
                    clicar(w, "Confirmar")
                self.robo.quando("Dialogo", responder)
                self.assertEqual(adega_dialogos.pedir_cascos(self.cx, self.bebida(), self.bebida(), 6), 2)
        self.sem_travar()

    def test_escolha_gelada_por_atalho(self):
        def responder(w):
            w.focus_force()
            w.event_generate("<KeyPress-g>")
        self.robo.quando("Dialogo", responder)
        self.assertEqual(adega_dialogos.pedir_temperatura(self.cx, self.bebida(preco_gelada_cent=950), 800), "gelada")
        self.sem_travar()

    def test_escape_cancela_troca_de_cascos(self):
        def responder(w):
            w.focus_force()
            w.event_generate("<Escape>")
        self.robo.quando("Dialogo", responder)
        self.assertIsNone(adega_dialogos.pedir_cascos(self.cx, self.bebida(), self.bebida(), 6))
        self.sem_travar()
