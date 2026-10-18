"""Status de preparo por item (módulo Cozinha/Bar, usar_cozinha_bar): PreparoController."""
from __future__ import annotations

import unittest

from src.controllers.preparo_controller import PreparoController
from src.core.erros import ErroNegocio
from tests.test_caixa import BaseCaixa


class TestePreparo(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.preparo = PreparoController(self.banco, self.adm)
        self.banco.executar("UPDATE subgrupos SET impressora_remota = 1")

    def item_remoto(self, produto=None, qtd=1):
        vid = self.caixa.abrir_balcao()
        return self.caixa.adicionar_item(vid, produto or self.skol, qtd)

    def outro_subgrupo(self, produto_id: int, impressora_remota: bool = False) -> int:
        """Move `produto_id` para um subgrupo próprio (skol e agua nascem no mesmo subgrupo em BaseCaixa)."""
        grupo_id = self.banco.valor("SELECT id FROM grupos LIMIT 1")
        sub_id = self.banco.inserir("subgrupos", {"nome": f"Outro {produto_id}", "grupo_id": grupo_id,
                                                    "impressora_remota": int(impressora_remota)})
        self.banco.executar("UPDATE produtos SET subgrupo_id = ? WHERE id = ?", (sub_id, produto_id))
        return sub_id

    def test_fila_so_itens_de_subgrupo_remoto_nao_cancelados(self):
        remoto = self.item_remoto()
        self.outro_subgrupo(self.agua, impressora_remota=False)
        outro = self.caixa.adicionar_item(self.caixa.abrir_balcao(), self.agua, 1)
        ids = [i["id"] for i in self.preparo.fila()]
        self.assertIn(remoto, ids)
        self.assertNotIn(outro, ids)

    def test_item_cancelado_nao_aparece(self):
        item = self.item_remoto()
        self.caixa.cancelar_item(item, "teste")
        self.assertNotIn(item, [i["id"] for i in self.preparo.fila()])

    def test_marcar_grava_quem_e_quando(self):
        item = self.item_remoto()
        self.preparo.marcar(item, "em_preparo")
        r = self.banco.um("SELECT status_preparo, preparo_atualizado_em, preparo_operador_id FROM itens_venda WHERE id = ?",
                          (item,))
        self.assertEqual(r["status_preparo"], "em_preparo")
        self.assertEqual(r["preparo_atualizado_em"], fmt_agora(self))
        self.assertEqual(r["preparo_operador_id"], self.adm)

    def test_marcar_status_invalido_recusa(self):
        item = self.item_remoto()
        with self.assertRaises(ErroNegocio):
            self.preparo.marcar(item, "voando")

    def test_marcar_item_inexistente_recusa(self):
        with self.assertRaises(ErroNegocio):
            self.preparo.marcar(999999, "em_preparo")

    def test_avancar_pendente_para_em_preparo_para_entregue(self):
        item = self.item_remoto()
        self.assertEqual(self.preparo.avancar(item), "em_preparo")
        self.assertEqual(self.preparo.avancar(item), "entregue")
        self.assertEqual(self.preparo.avancar(item), "entregue")   # já no fim: fica

    def test_entregue_some_da_fila_padrao(self):
        item = self.item_remoto()
        self.preparo.marcar(item, "entregue")
        self.assertNotIn(item, [i["id"] for i in self.preparo.fila()])
        self.assertIn(item, [i["id"] for i in self.preparo.fila(status=("entregue",))])

    def test_fila_filtra_por_setor_quando_subgrupo_tem_setor(self):
        setor_a = self.banco.inserir("setores_impressao", {"nome": "Cozinha", "conexao": "pasta", "ativo": 1, "ordem": 0})
        setor_b = self.banco.inserir("setores_impressao", {"nome": "Bar", "conexao": "pasta", "ativo": 1, "ordem": 1})
        sub_skol = self.banco.valor("SELECT subgrupo_id FROM produtos WHERE id = ?", (self.skol,))
        sub_agua = self.outro_subgrupo(self.agua, impressora_remota=True)
        self.banco.executar("UPDATE subgrupos SET setor_impressao_id = ? WHERE id = ?", (setor_a, sub_skol))
        self.banco.executar("UPDATE subgrupos SET setor_impressao_id = ? WHERE id = ?", (setor_b, sub_agua))
        item_skol = self.item_remoto(self.skol)
        item_agua = self.item_remoto(self.agua)
        ids_a = [i["id"] for i in self.preparo.fila(setor_id=setor_a)]
        ids_b = [i["id"] for i in self.preparo.fila(setor_id=setor_b)]
        self.assertEqual(ids_a, [item_skol])
        self.assertEqual(ids_b, [item_agua])

    def test_posicao_rotulo_balcao_e_mesa(self):
        item_balcao = self.item_remoto()
        linha_balcao = next(i for i in self.preparo.fila() if i["id"] == item_balcao)
        self.assertEqual(linha_balcao["posicao_rotulo"], "Balcão")
        vid, _ = self.caixa.abrir_mesa(5)
        item_mesa = self.caixa.adicionar_item(vid, self.skol, 1)
        linha_mesa = next(i for i in self.preparo.fila() if i["id"] == item_mesa)
        self.assertIn("5", linha_mesa["posicao_rotulo"])


def fmt_agora(teste) -> str:
    from src.core import formatacao as fmt
    return fmt.agora()


if __name__ == "__main__":
    unittest.main()
