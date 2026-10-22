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
