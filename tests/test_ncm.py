"""NCM no cadastro de produto: limpeza, validação, sugestão pelo nome e obrigatório com a NFC-e ligada."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.controllers.cadastro_controller import CadastroController
from src.core.erros import ErroNegocio
from src.fiscal import ncm
from tests.base import BaseTeste
from tests.test_qt_caixa import BaseCaixaQt, QApplication


class TesteSugestao(unittest.TestCase):
    def test_sugere_pelo_nome(self):
        casos = {
            "SKOL LATA 350ML": "22030000", "Heineken 0.0 long neck": "22029100", "Coca-Cola 2L": "22021000",
            "Água Mineral Crystal 500ml": "22011000", "Red Bull 250ml": "22029900", "Smirnoff Ice": "22089000",
            "Vodka Smirnoff 998ml": "22086000", "Gelo 5kg": "22019000", "Marlboro Box": "24022000",
            "Whisky Red Label 1L": "22083020", "Cachaça 51": "22084000", "Vinho Pérgola Tinto": "22042100",
            "Biscoito Trakinas": "19053100", "Chocolate ao leite Lacta": "18069000", "Carvão 3kg": "44029000",
        }
        for nome, esperado in casos.items():
            self.assertEqual(ncm.sugerir(nome)[0], esperado, nome)

    def test_sem_sugestao_quando_nao_sabe(self):
        for nome in ("", None, "Produto X", "Água de coco 1L"):
            self.assertIsNone(ncm.sugerir(nome), nome)

    def test_limpar_validar_formatar(self):
        self.assertEqual(ncm.validar("2203.00.00"), "22030000")
        self.assertEqual(ncm.validar(""), "")
        self.assertEqual(ncm.formatar("22030000"), "2203.00.00")
        with self.assertRaisesRegex(ErroNegocio, "8 números"):
            ncm.validar("2203")

    def test_toda_sugestao_tem_8_numeros(self):
        for _, codigo, _ in ncm.SUGESTOES:
            self.assertIn(len(codigo), (0, 8), codigo)


class TesteCadastro(BaseTeste):
    def test_grava_so_os_numeros_e_recusa_ncm_curto(self):
        pid = self.novo_produto("SKOL", ncm="2203.00.00")
        self.assertEqual(self.banco.valor("SELECT ncm FROM produtos WHERE id = ?", (pid,)), "22030000")
        with self.assertRaisesRegex(ErroNegocio, "8 números"):
            self.novo_produto("BRAHMA", ncm="2203")
        self.assertIsNone(self.banco.valor("SELECT ncm FROM produtos WHERE id = ?", (self.novo_produto("SEM"),)))

    def test_outros_caminhos_continuam_sem_exigir_ncm(self):
        self.banco.cfg_set("nfce_emissao", "homologacao")
        cad = CadastroController(self.banco)
        self.assertTrue(cad.obter("produtos", self.novo_produto("PRODUTO SEM NCM")))


@unittest.skipIf(QApplication is None, "PySide6 não instalado")
class TesteFormulario(BaseCaixaQt):
    def formulario(self):
        from src.ui_qt.cadastros import FormularioCadastro
        f = FormularioCadastro(self.ctx, "produtos")
        self.addCleanup(f.deleteLater)
        return f

    def aba_do_ncm(self, f):
        for i in range(f.abas.count()):
            if f.abas.widget(i).findChild(type(f.campos["ncm"]), "produto_ncm") is not None:
                return f.abas.tabText(i)

    def test_desligada_fica_na_aba_fiscal_e_nao_e_obrigatorio(self):
        f = self.formulario()
        self.assertEqual(self.aba_do_ncm(f), "Fiscal")
        self.assertFalse(f.ncm_obrigatorio)
        f._exigir_ncm()                                         # não reclama

    def test_ligada_vem_para_a_primeira_aba_sugere_e_exige(self):
        self.banco.cfg_set("nfce_emissao", "homologacao")
        f = self.formulario()
        self.assertEqual(self.aba_do_ncm(f), "Geral")
        f.campos["nome"].setText("SKOL LATA 350ML")
        self.assertFalse(f.btn_sugerir_ncm.isHidden())
        self.assertIn("2203.00.00", f.btn_sugerir_ncm.text())
        with self.assertRaisesRegex(ErroNegocio, "precisa do NCM.*2203.00.00"):
            f._exigir_ncm()
        f.usar_ncm_sugerido()
        self.assertEqual(f.campos["ncm"].text(), "2203.00.00")
        self.assertTrue(f.btn_sugerir_ncm.isHidden())           # já está usando a sugestão
        f._exigir_ncm()
        f.campos["ncm"].clear()
        f.campos["venda"].setChecked(False)                     # insumo que não é vendido: não precisa
        f._exigir_ncm()

    def test_salvar_sem_ncm_mostra_o_aviso(self):
        self.banco.cfg_set("nfce_emissao", "producao")
        f = self.formulario()
        f.campos["nome"].setText("PRODUTO X")
        f.salvar()
        self.assertIn("precisa do NCM", f.mensagem.text())
        self.assertFalse(f.result())


if __name__ == "__main__":
    unittest.main()
