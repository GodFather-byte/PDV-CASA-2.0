"""Motivo do cancelamento de item e de venda: opcional de fábrica, obrigatório por configuração, e aparece na conferência."""
from __future__ import annotations

from src.controllers.conferencia_turno import conferencia
from src.core.erros import ErroNegocio
from tests.test_regras_caixa import BaseRegras


class TesteMotivoCancelamento(BaseRegras):
    def _venda_com_item(self):
        v = self.caixa.abrir_balcao()
        item = self.caixa.adicionar_item(v, self.novo_produto(), 1)
        return v, item

    def test_sem_exigencia_cancela_sem_motivo(self):
        v, item = self._venda_com_item()
        self.caixa.cancelar_item(item)
        self.caixa.cancelar_venda(v)

    def test_exigido_recusa_cancelar_sem_motivo(self):
        self.banco.cfg_set("exigir_motivo_cancelamento", "S")
        v, item = self._venda_com_item()
        with self.assertRaises(ErroNegocio):
            self.caixa.cancelar_item(item, "  ")
        with self.assertRaises(ErroNegocio):
            self.caixa.cancelar_venda(v)
        self.caixa.cancelar_item(item, "cliente desistiu")
        self.caixa.cancelar_venda(v, "erro de lançamento")

    def test_motivo_do_item_vai_para_a_conferencia(self):
        v, item = self._venda_com_item()
        self.caixa.cancelar_item(item, "pedido errado")
        res = conferencia(self.banco, self.turnos.atual())
        self.assertEqual(res["itens_cancelados"][0]["motivo"], "pedido errado")
