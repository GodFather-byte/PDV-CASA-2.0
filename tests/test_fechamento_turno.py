"""Fechamento completo do turno: posições abertas, cupons e itens cancelados, transferências, a fita e as telas."""
from __future__ import annotations

import tkinter as tk
import unittest
from tkinter import ttk
from unittest import mock

from src.controllers.cadastro_controller import CadastroController
from src.controllers.caixa_controller import CaixaController
from src.controllers.conferencia_turno import LIMITE_FITA, linhas_fita, texto_conferencia
from src.controllers.impressao_controller import ImpressaoController
from tests.test_caixa import BaseCaixa
from tests.test_ui import BaseUI
from tests.ui_robo import clicar, entradas


class BaseConferencia(BaseCaixa):
    def comanda(self, numero, *itens):
        vid, _ = self.caixa.abrir_mesa(numero, comanda=True)
        for pid, qtd in itens:
            self.caixa.adicionar_item(vid, pid, qtd)
        return vid

    def operador(self, nome="NOITE") -> CaixaController:
        id_ = CadastroController(self.banco).salvar("operadores", {"nome": nome, "senha": "1", "nivel": "1"})
        return CaixaController(self.banco, id_)


class TesteConferenciaDoTurno(BaseConferencia):
    def test_posicoes_abertas_com_total_e_situacao(self):
        self.vender((self.skol, 1), mesa=5)
        c2 = self.comanda(2, (self.agua, 1))
        self.caixa.enviar_conta(c2)
        self.comanda(9)                                        # recém-aberta e vazia: não conta
        fechada = self.vender((self.skol, 1), mesa=7)
        self.pagar(fechada, "Dinheiro", 880)
        self.caixa.fechar(fechada)                             # paga: não está mais aberta
        esperado = [{"rotulo": "5", "nome": "Mesa 5", "status": "aberta", "total_cent": 880, "itens": 1},
                    {"rotulo": "C2", "nome": "Comanda 2", "status": "conta_enviada", "total_cent": 385, "itens": 1}]
        self.assertEqual(self.turnos.resumo(self.turno)["posicoes_abertas"], esperado)
        self.assertEqual(self.turnos.posicoes_abertas(), esperado)

    def test_cupom_e_item_cancelados_mostram_quem_cancelou(self):
        noite = self.operador()
        c3 = self.comanda(3, (self.skol, 1), (self.agua, 1))
        noite.cancelar_item(self.caixa.itens(c3)[1]["id"])                 # a NOITE cancela a água
        balcao = self.vender((self.skol, 1))
        self.caixa.cancelar_venda(balcao, "cliente desistiu")              # o ADM cancela o cupom
        r = self.turnos.resumo(self.turno)
        self.assertEqual([(i["local"], i["produto"], i["quantidade"], i["total_cent"], i["por"], i["cupom"])
                          for i in r["itens_cancelados"]], [("Comanda 3", "AGUA", 1, 350, "NOITE", None)])
        self.assertEqual(r["cupons_cancelados"], [{"cupom": 1, "local": "Balcão", "total_cent": 800,
                                                    "motivo": "cliente desistiu", "por": "ADM"}])

    def test_transferencias_ficam_registradas_com_origem_destino_valor_e_quem_fez(self):
        self.vender((self.skol, 2), mesa=5)
        self.vender((self.agua, 1), mesa=6)
        self.comanda(1, (self.skol, 1))
        c2 = self.caixa.transferir_mesa(5, "C2")                           # posição inteira
        self.caixa.transferir_varias([6, "C1"], "C2")                      # duas para uma
        self.caixa.transferir_item(self.caixa.itens(c2)[0]["id"], "C9", 1)       # 1 das 2 SKOL
        r = self.turnos.resumo(self.turno)
        self.assertEqual([(t["tipo"], t["origem"], t["destino"], t["valor_cent"], t["produto"], t["quantidade"], t["por"])
                          for t in r["transferencias"]], [
            ("mesa", "5", "C2", 1600, None, None, "ADM"), ("mesa", "6", "C2", 350, None, None, "ADM"),
            ("mesa", "C1", "C2", 800, None, None, "ADM"), ("item", "C2", "C9", 800, "SKOL", 1.0, "ADM")])

    def test_cada_turno_conta_so_o_que_aconteceu_nele(self):
        c1 = self.comanda(1, (self.agua, 1), (self.agua, 1))
        self.caixa.cancelar_item(self.caixa.itens(c1)[0]["id"])                    # turno 1
        self.vender((self.agua, 1), mesa=8)
        self.caixa.transferir_mesa(8, 9)                                           # turno 1
        self.avancar(minutes=5)
        self.turnos.fechar(self.turno, self.adm, 10000)
        self.avancar(minutes=5)
        turno2 = self.turnos.abrir(self.adm, 2, 0)
        c2 = self.comanda(2, (self.skol, 1), (self.agua, 1))
        self.caixa.cancelar_item(self.caixa.itens(c2)[0]["id"])                    # turno 2 (a SKOL)
        self.caixa.transferir_mesa(9, "C6")                                        # turno 2
        um, dois = self.turnos.resumo(self.turno), self.turnos.resumo(turno2)
        self.assertEqual([(i["local"], i["produto"]) for i in um["itens_cancelados"]], [("Comanda 1", "AGUA")])
        self.assertEqual([(t["origem"], t["destino"]) for t in um["transferencias"]], [("8", "9")])
        self.assertEqual([(i["local"], i["produto"]) for i in dois["itens_cancelados"]], [("Comanda 2", "SKOL")])
        self.assertEqual([(t["origem"], t["destino"]) for t in dois["transferencias"]], [("9", "C6")])

    def test_turno_tranquilo_nao_traz_nada_a_conferir(self):
        r = self.turnos.resumo(self.turno)
        self.assertEqual((r["posicoes_abertas"], r["cupons_cancelados"], r["itens_cancelados"], r["transferencias"]),
                         ([], [], [], []))


class TesteFitaDoFechamento(BaseConferencia):
    def cenario(self):
        noite = self.operador()
        self.vender((self.skol, 1), mesa=5)
        self.caixa.enviar_conta(self.comanda(2, (self.agua, 1)))
        c3 = self.comanda(3, (self.skol, 1), (self.agua, 1))
        noite.cancelar_item(self.caixa.itens(c3)[1]["id"])
        self.caixa.cancelar_venda(self.vender((self.skol, 1)), "cliente desistiu")
        self.caixa.transferir_mesa(5, "C7")

    def test_fita_traz_as_secoes_e_cabe_em_40_colunas(self):
        self.cenario()
        res = self.turnos.fechar(self.turno, self.adm, 10000)
        texto = ImpressaoController(self.banco).fechamento(res)
        linhas = texto.splitlines()
        self.assertTrue(all(len(l) <= 40 for l in linhas), [l for l in linhas if len(l) > 40])
        for esperado in ("POSIÇÕES EM ABERTO (3)", "Comanda 2 - conta enviada", "Comanda 3", "Comanda 7",
                         "CUPONS CANCELADOS (1)", "1 Balcão", "ADM: cliente desistiu", "ITENS CANCELADOS (1)",
                         "21:00 C3 1x AGUA", "por NOITE", "TRANSFERÊNCIAS (1)", "21:00 M5>C7 inteira", "por ADM"):
            self.assertIn(esperado, texto)
        self.assertRegex(texto, r"Total em aberto +21,45")                 # 3,85 + 8,80 + 8,80
        self.assertTrue(linhas[-1] == "=" * 40)
        self.assertRegex(texto, r"SOBROU|FALTOU|CAIXA CONFERIDO")

    def test_sem_ocorrencias_so_a_linha_das_posicoes_abertas(self):
        res = self.turnos.fechar(self.turno, self.adm, 10000)
        texto = ImpressaoController(self.banco).fechamento(res)
        self.assertRegex(texto, r"Nenhuma mesa ou comanda aberta +OK")
        for ausente in ("POSIÇÕES EM ABERTO (", "CANCELADOS", "TRANSFERÊNCIAS"):
            self.assertNotIn(ausente, texto)

    def test_secao_longa_e_cortada_com_e_mais_n(self):
        transf = {"quando": "2026-10-03 21:00:00", "por": "ADM", "tipo": "mesa", "origem": "1", "destino": "C2", "valor_cent": 100}
        linhas = linhas_fita({"transferencias": [transf] * (LIMITE_FITA + 5)}, 40)
        self.assertTrue(any(f" TRANSFERÊNCIAS ({LIMITE_FITA + 5}) " in l for l in linhas), linhas[:5])
        self.assertIn("  ... e mais 5", linhas)
        self.assertEqual(sum(1 for l in linhas if "M1>C2 inteira" in l), LIMITE_FITA)

    def test_conferencia_avulsa_para_a_tela(self):
        self.cenario()
        texto = texto_conferencia(self.turnos.resumo(self.turno))
        self.assertEqual(texto.splitlines()[0].strip(), "CONFERÊNCIA DO TURNO")
        self.assertIn("TRANSFERÊNCIAS (1)", texto)

    def test_leitura_x_tambem_mostra_a_conferencia(self):
        self.cenario()
        texto = ImpressaoController(self.banco).leitura_x(self.turno)
        self.assertIn("LEITURA X", texto)
        self.assertIn("POSIÇÕES EM ABERTO (3)", texto)


def rotulos(janela) -> str:
    achados, pilha = [], [janela]
    while pilha:
        w = pilha.pop()
        pilha.extend(w.winfo_children())
        if isinstance(w, (ttk.Label, tk.Label)):
            achados.append(str(w.cget("text")))
    return "\n".join(achados)


class TesteFechamentoNaTela(BaseUI):
    def abrir_comanda(self, numero, itens):
        self.abrir_turno()
        v, _ = self.ctx.caixa.abrir_mesa(numero, comanda=True)
        for pid, qtd in itens:
            self.ctx.caixa.adicionar_item(v, pid, qtd)
        return v

    def test_troca_de_turno_avisa_das_comandas_abertas(self):
        from src.ui import caixa_dialogos
        self.abrir_comanda(2, [(self.skol, 1)])
        textos = []

        def trocar(w):
            campos = entradas(w)
            if w.title() == "Conferir maquininha":      # 1º diálogo: cartão/Pix lançados, para bater com a maquininha
                clicar(w, "Continuar")
            elif campos:                         # 2º diálogo: valor encontrado na gaveta
                campos[0].delete(0, "end"); campos[0].insert(0, "100,00"); clicar(w, "OK")
            else:                                # 3º diálogo: "Confirma?"
                textos.append(rotulos(w)); clicar(w, "Sim")
        self.robo.quando("Dialogo", trocar, vezes=3)
        self.robo.quando("PainelFechamento", lambda w: w.destroy())
        declarados = {r["tipo_id"]: 10000 if r["dinheiro"] else 0
                      for r in self.ctx.turnos.formas_conferencia(
                          self.ctx.turnos.atual()["id"], self.ctx.operador_id)}
        with mock.patch("src.ui.fechamento_ui.coletar", return_value={
                "informados_por_forma": declarados, "justificativa": ""}):
            self.assertTrue(caixa_dialogos.trocar_turno(self.root, self.ctx))
        self.assertIn("1 mesa(s)/comanda(s) aberta(s), R$ 8,80", textos[0])
        self.assertIn("Comanda 2", textos[0])
        self.assertIn("continuam abertas no próximo turno", textos[0])
        self.sem_travar()

    def test_troca_de_turno_sem_posicoes_abertas_nao_avisa(self):
        from src.ui import caixa_dialogos
        self.abrir_turno()
        textos = []

        def trocar(w):
            campos = entradas(w)
            if w.title() == "Conferir maquininha":
                clicar(w, "Continuar")
            elif campos:
                campos[0].delete(0, "end"); campos[0].insert(0, "100,00"); clicar(w, "OK")
            else:
                textos.append(rotulos(w)); clicar(w, "Sim")
        self.robo.quando("Dialogo", trocar, vezes=3)
        self.robo.quando("PainelFechamento", lambda w: w.destroy())
        declarados = {r["tipo_id"]: 10000 if r["dinheiro"] else 0
                      for r in self.ctx.turnos.formas_conferencia(
                          self.ctx.turnos.atual()["id"], self.ctx.operador_id)}
        with mock.patch("src.ui.fechamento_ui.coletar", return_value={
                "informados_por_forma": declarados, "justificativa": ""}):
            caixa_dialogos.trocar_turno(self.root, self.ctx)
        self.assertNotIn("ATENÇÃO", textos[0])

    def test_painel_do_fechamento_mostra_a_conferencia(self):
        from src.ui.caixa_dialogos import PainelFechamento
        v = self.abrir_comanda(2, [(self.skol, 2), (self.agua, 1)])
        self.ctx.caixa.cancelar_item(self.ctx.caixa.itens(v)[1]["id"])
        self.ctx.caixa.transferir_item(self.ctx.caixa.itens(v)[0]["id"], "C5", 1)
        res = self.ctx.turnos.fechar(self.ctx.turnos.atual()["id"], self.ctx.operador_id, 10000)
        pares, abertos = {}, []

        def ler(janela):
            linhas, pilha = {}, [janela]
            while pilha:
                w = pilha.pop()
                pilha.extend(w.winfo_children())
                if isinstance(w, ttk.Label) and w.grid_info():
                    info = w.grid_info()
                    linhas.setdefault((str(w.master), int(info["row"])), {})[int(info["column"])] = w.cget("text")
            pares.update({c[0]: c[1] for c in linhas.values() if 0 in c and 1 in c})
            with mock.patch("src.ui.caixa_dialogos.Visualizador") as visualizador:
                janela.conferencia()                                        # botão "Conferência do turno"
            abertos.append(visualizador.call_args.args[3])
            janela.destroy()
        self.robo.quando("PainelFechamento", ler)
        PainelFechamento(self.root, self.ctx, res)
        self.assertEqual((pares["Itens cancelados"], pares["Cupons cancelados"], pares["Transferências"]), ("1", "0", "1"))
        self.assertTrue(pares["Posições em aberto"].startswith("2 ("))        # a C2 e a C5
        self.assertIn("ITENS CANCELADOS (1)", abertos[0])
        self.assertIn("C2>C5", abertos[0])
        self.sem_travar()


if __name__ == "__main__":
    unittest.main()


class TesteConferenciaDaMaquininhaNaTela(BaseUI):
    """Antes de contar a gaveta, a tela mostra o cartão (débito e crédito separados) para comparar com a maquininha."""

    def vender_em(self, forma, valor):
        v = self.ctx.caixa.abrir_balcao()
        self.ctx.caixa.adicionar_item(v, self.skol, 1)
        self.ctx.caixa.adicionar_pagamento(v, self.tipo(forma), valor)
        self.ctx.caixa.fechar(v)

    def tipo(self, nome):
        return self.banco.valor("SELECT id FROM tipos_pagamento WHERE tipo = ?", (nome,))

    def test_mostra_debito_e_credito_antes_de_pedir_o_dinheiro(self):
        from src.ui import caixa_dialogos
        self.abrir_turno()
        self.vender_em("Cartão Débito", 800)
        self.vender_em("Cartão Débito", 800)
        self.vender_em("Cartão Crédito", 1300)                     # 8,00 + R$ 5,00 da taxa do crédito
        ordem, tela = [], []

        def trocar(w):
            if w.title() == "Conferir maquininha":
                ordem.append("maquininha"); tela.append(rotulos(w)); clicar(w, "Continuar")
            elif entradas(w):
                ordem.append("gaveta")
                entradas(w)[0].delete(0, "end"); entradas(w)[0].insert(0, "100,00"); clicar(w, "OK")
            else:
                ordem.append("confirma"); clicar(w, "Sim")
        self.robo.quando("Dialogo", trocar, vezes=3)
        self.robo.quando("PainelFechamento", lambda w: w.destroy())
        declarados = {self.tipo("Dinheiro"): 10000, self.tipo("Cartão Débito"): 1600,
                      self.tipo("Cartão Crédito"): 1300, self.tipo("Pix"): 0}
        with mock.patch("src.ui.fechamento_ui.coletar", return_value={
                "informados_por_forma": declarados, "justificativa": ""}):
            self.assertTrue(caixa_dialogos.trocar_turno(self.root, self.ctx))
        self.assertEqual(ordem, ["maquininha", "gaveta", "confirma"])
        for trecho in ("Cartão Débito", "Cartão Crédito", "16,00", "13,00", "29,00"):
            self.assertIn(trecho, tela[0])
        self.assertNotIn("esperado", tela[0].lower())                      # a contagem da gaveta continua às cegas
        self.sem_travar()

    def test_cancelar_a_conferencia_nao_fecha_o_turno(self):
        from src.ui import caixa_dialogos
        self.abrir_turno()
        self.robo.quando("Dialogo", lambda w: clicar(w, "Cancelar"), vezes=1)
        self.assertFalse(caixa_dialogos.trocar_turno(self.root, self.ctx))
        self.assertEqual(self.banco.valor("SELECT status FROM turnos"), "aberto")
        self.sem_travar()
