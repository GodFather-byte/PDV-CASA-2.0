"""Código 1002: libera a saída de quem não consumiu nada e imprime o comprovante de saída."""
from __future__ import annotations

from src.controllers.config_controller import ConfigController
from src.controllers.impressao_controller import ImpressaoController
from src.core.erros import ErroNegocio, ErroValidacao
from tests.test_caixa import BaseCaixa


class TesteSaidaSemConsumo(BaseCaixa):
    def test_comanda_aberta_vazia_e_liberada_e_registrada_no_turno(self):
        self.caixa.abrir_mesa(180, comanda=True)
        info = self.caixa.liberar_saida(True, 180)
        self.assertEqual((info["nome"], info["rotulo"], info["turno"]), ("Comanda 180", "180", 1))
        self.assertEqual(self.caixa.mesas(), [])                               # a posição ficou livre
        saidas = self.caixa.saidas_liberadas(self.turno)
        self.assertEqual([(s["rotulo"], s["operador"]) for s in saidas], [("180", "ADM")])

    def test_comanda_que_nunca_foi_aberta_tambem_libera(self):
        self.assertEqual(self.caixa.liberar_saida(True, 77)["nome"], "Comanda 77")
        self.assertEqual(len(self.caixa.saidas_liberadas(self.turno)), 1)

    def test_com_consumo_ou_pagamento_recusa(self):
        vid = self.vender((self.skol, 1), mesa=12)
        with self.assertRaisesRegex(ErroNegocio, "consumo de R\\$ 8,80"):
            self.caixa.liberar_saida(False, 12)
        vazia, _ = self.caixa.abrir_mesa(13)
        self.caixa.adicionar_pagamento(vazia, self.tipo("Dinheiro"), 1000)
        with self.assertRaisesRegex(ErroNegocio, "pagamento lançado"):
            self.caixa.liberar_saida(False, 13)
        self.assertEqual(self.caixa.saidas_liberadas(self.turno), [])
        self.assertEqual(self.caixa.obter(vid)["status"], "aberta")

    def test_itens_cancelados_contam_como_sem_consumo(self):
        vid = self.vender((self.skol, 1), mesa=12)
        self.caixa.cancelar_item(self.caixa.itens(vid)[0]["id"])
        self.caixa.liberar_saida(False, 12)
        self.assertEqual(self.caixa.obter(vid)["status"], "cancelada")

    def test_exige_turno_aberto(self):
        self.turnos.fechar(self.turno, self.adm, 10000)
        with self.assertRaises(ErroNegocio):
            self.caixa.liberar_saida(True, 5)

    def test_codigo_configuravel(self):
        self.assertTrue(self.caixa.eh_codigo_saida("1002"))
        self.assertTrue(self.caixa.eh_codigo_saida("01002"))
        self.assertFalse(self.caixa.eh_codigo_saida("1003"))
        cfg = ConfigController(self.banco)
        cfg.salvar_config({"codigo_saida": "999"})
        self.assertTrue(self.caixa.eh_codigo_saida("999"))
        with self.assertRaises(ErroValidacao):
            cfg.salvar_config({"codigo_saida": "50"})                      # já é o da comissão
        cfg.salvar_config({"codigo_saida": ""})
        self.assertFalse(self.caixa.eh_codigo_saida("1002"))

    def test_ticket_de_saida_no_modelo_da_casa(self):
        self.banco.atualizar("loja", 1, {"nome_fantasia": "Boate Estrela", "razao_social": "Estrela Diversoes LTDA"})
        imp = ImpressaoController(self.banco)
        texto = imp.comprovante_saida(self.caixa.liberar_saida(True, 180), "ADM")
        for trecho in ("TICKET DE SAIDA", "BOATE ESTRELA", "ESTRELA DIVERSOES LTDA", "FAVOR ENTREGAR ESTE TICKET NA SAIDA",
                       "DATA: 03/10/2026", "HORA: 21:00:00", "OPERADOR: ADM", "TICKET: 000001", "POSICAO DE ORIGEM: 180",
                       "CARTAO: 180  LIBERADO"):
            self.assertIn(trecho, texto)
        self.assertNotIn("CASA VERDE", texto.upper())
        segundo = imp.comprovante_saida(self.caixa.liberar_saida(False, 5), "ADM")
        self.assertIn("TICKET: 000002", segundo)                       # numeração sequencial
        self.assertIn("MESA: M5  LIBERADO", segundo)

    def test_ticket_cabe_na_fita_de_58mm(self):
        self.banco.atualizar("loja", 1, {"nome_fantasia": "Boate Estrela"})
        self.banco.executar("UPDATE maquinas SET colunas_fita = 32")
        texto = ImpressaoController(self.banco).comprovante_saida(self.caixa.liberar_saida(True, 180), "ADM")
        self.assertTrue(all(len(l) <= 32 for l in texto.splitlines()), texto)
        self.assertIn("FAVOR ENTREGAR ESTE", texto)
        self.assertIn("TICKET NA SAIDA", texto)

try:
    from tests.test_comissao_na_tela import BaseNaTela
    from tests.ui_robo import clicar, entradas
except ImportError:                       # sem Tkinter só rodam as regras
    BaseNaTela = None

if BaseNaTela is not None:
    class TesteSaidaNaTelaDoCaixa(BaseNaTela):
        def test_1002_na_comanda_imprime_a_saida_e_libera(self):
            self.posicao("180")                                              # chama a comanda 180 (vazia)
            impressos = []
            self.robo.quando("Visualizador", lambda w: (impressos.append(w.texto), w.destroy()))
            self.digitar_codigo("1002")
            self.assertEqual(len(impressos), 1)
            self.assertIn("TICKET DE SAIDA", impressos[0])
            self.assertIn("CARTAO: 180  LIBERADO", impressos[0])
            self.assertIn("Saída liberada", self.status())
            self.assertEqual(self.ctx.caixa.mesas(), [])
            self.sem_travar()

        def test_1002_com_consumo_avisa_e_nao_imprime(self):
            self.posicao("180")
            self.cx.var_cod.set("1"); self.cx._enter_codigo(); self.cx.update()
            self.valor("1")                                                  # 1 SKOL na comanda
            avisos, impressos = [], []
            self.dialogos({"Atenção": lambda w: (avisos.extend(self.textos(w)), clicar(w, "OK"))})
            self.robo.quando("Visualizador", lambda w: (impressos.append(w.texto), w.destroy()))
            self.digitar_codigo("1002")
            self.assertTrue(any("tem consumo" in a for a in avisos), avisos)
            self.assertEqual(impressos, [])
            self.sem_travar()

        def test_1002_no_balcao_pergunta_a_comanda(self):
            self.posicao("0")
            impressos = []
            self.dialogos({"Saída sem consumo": lambda w: (entradas(w)[0].insert(0, "55"), clicar(w, "OK"))})
            self.robo.quando("Visualizador", lambda w: (impressos.append(w.texto), w.destroy()))
            self.digitar_codigo("1002")
            self.assertIn("CARTAO: 55  LIBERADO", impressos[0])
            self.sem_travar()


class TesteCodigoDaSaidaReservado(BaseCaixa):
    def test_produto_nao_pode_usar_o_codigo_da_saida(self):
        from src.controllers.cadastro_controller import CadastroController
        cad = CadastroController(self.banco)
        sub = self.banco.valor("SELECT id FROM subgrupos LIMIT 1")
        un = self.banco.valor("SELECT id FROM unidades LIMIT 1")
        base = {"nome": "COISA", "codigo": "77", "subgrupo_id": sub, "unidade_id": un, "preco_cent": "5,00"}
        for campo in ("codigo", "atalho", "cbarra"):
            with self.assertRaisesRegex(ErroValidacao, "reservado", msg=campo):
                cad.salvar("produtos", {**base, campo: "1002"})
        ConfigController(self.banco).salvar_config({"codigo_saida": ""})
        cad.salvar("produtos", {**base, "codigo": "1002"})          # sem o código de saída, o 1002 fica livre


class TesteSaidaJuntoComOPagamento(BaseCaixa):
    """Comanda paga: o cupom sai e, junto, o ticket de saída da comanda para a portaria (sem precisar do 1002)."""

    def pagar_comanda(self, numero=100, comanda=True):
        vid, _ = self.caixa.abrir_mesa(numero, comanda=comanda)
        self.caixa.adicionar_item(vid, self.skol, 1)
        self.pagar(vid, "Dinheiro", self.caixa.recalcular(vid)["total"])
        self.caixa.fechar(vid)
        return vid

    def test_comanda_paga_gera_o_ticket_com_o_cupom(self):
        self.banco.atualizar("loja", 1, {"nome_fantasia": "Boate Estrela"})
        vid = self.pagar_comanda(100)
        texto = ImpressaoController(self.banco).saida_da_venda(vid)
        for trecho in ("TICKET DE SAIDA", "BOATE ESTRELA", "FAVOR ENTREGAR ESTE TICKET NA SAIDA", "OPERADOR: ADM",
                       f"CUPOM: {self.caixa.obter(vid)['cupom']}", "POSICAO DE ORIGEM: 100", "CARTAO: 100  PAGO - LIBERADO"):
            self.assertIn(trecho, texto)
        self.assertEqual(self.caixa.saidas_liberadas(self.turno), [])       # não conta como saída sem consumo (1002)

    def test_mesa_paga_tambem(self):
        texto = ImpressaoController(self.banco).saida_da_venda(self.pagar_comanda(5, comanda=False))
        self.assertIn("MESA: M5  PAGO - LIBERADO", texto)

    def test_balcao_e_venda_aberta_nao_tem_ticket(self):
        imp = ImpressaoController(self.banco)
        balcao = self.vender((self.skol, 1))
        self.pagar(balcao, "Dinheiro", 800)
        self.caixa.fechar(balcao)
        self.assertIsNone(imp.saida_da_venda(balcao))
        aberta, _ = self.caixa.abrir_mesa(7, comanda=True)
        self.caixa.adicionar_item(aberta, self.skol, 1)
        self.assertIsNone(imp.saida_da_venda(aberta))

    def test_desligado_nas_configuracoes(self):
        ConfigController(self.banco).salvar_config({"imprimir_saida_ao_pagar": "N"})
        self.assertIsNone(ImpressaoController(self.banco).saida_da_venda(self.pagar_comanda()))

