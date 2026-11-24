"""Segunda via dos papéis das garotas: o recibo do pagamento (dinheiro/Pix) refeito pelo banco sai igual ao original, com a
marca de SEGUNDA VIA e sem abrir a gaveta; o papel de cada comissão também sai de novo; a reimpressão fica no registro."""
from unittest.mock import patch

from src.ui_qt.comissao import DialogoReimpressao
from tests.test_qt_caixa import BaseCaixaQt

MARCA = "** SEGUNDA VIA - REIMPRESSÃO **"


class TesteReimpressaoGarota(BaseCaixaQt):
    def setUp(self):
        super().setUp()
        self.turno = self.abrir_turno()
        for chave, valor in (("comissao_na_linha", "N"), ("imprimir_via_comissao", "N"), ("comissao_pede_shows", "S"),
                             ("num_comandas", "300"), ("posicao_padrao", "comanda")):
            self.banco.cfg_set(chave, valor)
        self.banco.inserir("garotas", {"numero": 180, "nome": "ANA", "ativo": 1})

    def pagar(self, **escolha):
        j = self.janela()
        self.ctx.comissoes.lancar(180, 1500, self.turno, self.ctx.operador_id)
        self.ctx.comissoes.lancar(180, 2500, self.turno, self.ctx.operador_id)
        base = dict(do_caixa=True, shows=2, valor_show_cent=5000, vale_cent=2000, pix_cent=3000, zerado=False,
                    consumos_ids=[])
        with patch.object(j, "_dialogo_acerto", return_value=base | escolha), patch.object(j, "_emitir") as emitir:
            j.pagar_comissao(180)
        return j, emitir.call_args_list[0].args[1]

    def sem_marca(self, texto):
        return "\n".join(l for l in texto.split("\n") if l.strip() != MARCA)

    def test_recibo_reimpresso_e_igual_ao_original_com_a_marca(self):
        _, original = self.pagar()
        acerto = self.banco.valor("SELECT id FROM acertos_garotas")
        segunda = self.ctx.impressao.reimpressao_recibo_garota(acerto)
        self.assertIn(MARCA, segunda)
        self.assertEqual(self.sem_marca(segunda), original)
        self.assertIn("Pix", segunda)
        self.assertIn("Dinheiro", segunda)

    def test_recibo_so_no_pix_mostra_o_pix(self):
        _, original = self.pagar(shows=0, valor_show_cent=0, vale_cent=0, pix_cent=4000, do_caixa=False)
        acerto = self.banco.valor("SELECT id FROM acertos_garotas")
        self.assertEqual(self.sem_marca(self.ctx.impressao.reimpressao_recibo_garota(acerto)), original)

    def test_via_da_comissao_sai_de_novo_com_a_marca(self):
        lanc = self.ctx.comissoes.lancar(180, 1500, self.turno, self.ctx.operador_id)
        texto = self.ctx.impressao.reimpressao_via_comissao(lanc)
        self.assertIn(MARCA, texto)
        self.assertIn("COMISSÃO LANÇADA", texto)
        self.assertIn(f"Lançamento nº {lanc}", texto)

    def test_tela_lista_e_reimprime_sem_abrir_a_gaveta_e_registra(self):
        j, _ = self.pagar()
        dlg = DialogoReimpressao(j, 180)
        self.addCleanup(dlg.close)
        self.assertEqual(dlg.tabela_recibos.rowCount(), 1)
        self.assertEqual(dlg.tabela_vias.rowCount(), 2)
        dlg.tabela_recibos.setCurrentCell(0, 0)
        with patch.object(j, "_emitir") as emitir:
            self.assertTrue(dlg.imprimir())
        self.assertIn(MARCA, emitir.call_args.args[1])
        self.assertFalse(emitir.call_args.kwargs.get("abrir_gaveta", False))
        self.assertTrue(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'reimpressao_garota'", (), 0))
        dlg.abas.setCurrentIndex(1)
        dlg.tabela_vias.setCurrentCell(0, 0)
        with patch.object(j, "_emitir") as emitir:
            self.assertTrue(dlg.imprimir())
        self.assertIn("COMISSÃO LANÇADA", emitir.call_args.args[1])

    def test_filtro_de_outra_garota_nao_mostra_nada(self):
        j, _ = self.pagar()
        dlg = DialogoReimpressao(j, 181)
        self.addCleanup(dlg.close)
        self.assertEqual((dlg.tabela_recibos.rowCount(), dlg.tabela_vias.rowCount()), (0, 0))

    def test_botao_na_janela_de_comissoes(self):
        j = self.janela()
        janela = j.abrir_comissoes()
        self.addCleanup(janela.close)
        dlg = janela.reimprimir()
        self.addCleanup(dlg.close)
        self.assertEqual(dlg.windowTitle(), "Reimprimir papéis das garotas")
