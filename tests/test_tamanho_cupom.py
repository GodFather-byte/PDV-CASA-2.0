"""Tamanho do cupom na térmica (papel 58/80 mm e letra normal/pequena): o cupom cabe no papel sem quebrar linha,
o assistente reconhece o papel pelo nome da impressora e a retaguarda ajusta pelo caixa principal."""
from __future__ import annotations

from unittest import mock

from src.controllers import impressao_assistente as assistente
from src.controllers.config_controller import ConfigController
from src.controllers.impressao_controller import ImpressaoController
from src.controllers.retaguarda_controller import RetaguardaController
from src.core.erros import ErroValidacao
from src.hardware import impressora_termica as term, perfis_impressora as perfis
from src.hardware.impressoras_so import ImpressoraWindows as Imp
from tests.base import BaseTeste


class TestePerfis(BaseTeste):
    def test_colunas_de_cada_papel_e_letra(self):
        self.assertEqual([perfis.colunas(p, l) for p in (58, 80) for l in ("normal", "pequena")], [32, 42, 48, 64])

    def test_papel_pelo_nome_da_impressora(self):
        for nome, papel in (("POS-58", 58), ("XP-58IIH", 58), ("Mini impressora Bluetooth", 58), ("POS-80C", 80),
                            ("Elgin i9", 80), ("EPSON TM-T20", 80), ("Impressora 80mm", 80), ("KA 1445", None),
                            ("HP DeskJet 5820", None)):
            self.assertEqual(perfis.papel_pelo_nome(nome), papel, nome)
        self.assertEqual(perfis.papel_pelo_nome("CAIXA", "Generic POS-58 driver"), 58)

    def test_ka_1445_e_reconhecida_como_impressora_de_cupom(self):
        from src.hardware import impressoras_so
        self.assertTrue(impressoras_so._termica("KA 1445", ""))
        self.assertTrue(impressoras_so._termica("KA-1445", "Generic / Text Only"))


class TesteAjusteNaMaquina(BaseTeste):
    def test_papel_e_letra_ajustam_as_colunas_sozinhos(self):
        feito = assistente.ajustar_tamanho(self.banco, 58, "normal")
        self.assertEqual(feito, {"papel_mm": 58, "letra": "normal", "colunas": 32})
        self.assertEqual(assistente.ajustar_tamanho(self.banco, 58, "pequena")["colunas"], 42)
        self.assertEqual(assistente.ajustar_tamanho(self.banco, 80, "pequena")["colunas"], 64)
        with self.assertRaises(term.ErroImpressao):
            assistente.ajustar_tamanho(self.banco, 76, "normal")
        with self.assertRaises(ErroValidacao):
            ConfigController(self.banco).salvar_maquina({"impressora_papel_mm": "100"})

    def test_configurar_reconhece_o_papel_pelo_nome_e_respeita_a_escolha(self):
        self.assertEqual(assistente.configurar(self.banco, "POS-58")["colunas"], 32)
        self.assertEqual(assistente.configurar(self.banco, "KA 1445", papel_mm=58, letra="pequena"),
                         {"papel_mm": 58, "letra": "pequena", "colunas": 42})
        # Elgin i9 continua com o padrão de sempre (80 mm, 48 colunas) quando nada foi escolhido antes.
        ConfigController(self.banco).salvar_maquina({"impressora_papel_mm": "0", "impressora_letra": "normal"})
        self.assertEqual(assistente.configurar(self.banco, "Elgin i9")["colunas"], 48)

    def test_cupom_de_58mm_cabe_no_papel(self):
        assistente.configurar(self.banco, "POS-58", papel_mm=58)
        imp = ImpressaoController(self.banco)
        self.assertEqual(imp.largura(), 32)
        teste = imp.impressora_termica().ticket_teste("Adega com nome muito comprido de verdade")
        self.assertTrue(all(len(l) <= 32 for l in teste.split("\n")), teste)
        self.assertIn("1234567890123456789012345678901" + "2", teste)            # régua com as 32 colunas

    def test_letra_pequena_manda_a_fonte_b(self):
        assistente.configurar(self.banco, "POS-80", papel_mm=80, letra="pequena")
        imp = ImpressaoController(self.banco).impressora_termica()
        dados = imp.montar("CUPOM\nTOTAL 1,00", negrito_linhas=1)
        self.assertIn(term.FONTE_PEQUENA, dados)
        assistente.ajustar_tamanho(self.banco, 80, "normal")
        self.assertNotIn(term.FONTE_PEQUENA, ImpressaoController(self.banco).impressora_termica().montar("X"))

    def test_diagnostico_acusa_cupom_grande(self):
        ConfigController(self.banco).salvar_maquina({"modo_impressao": "windows"})
        textos = " ".join(a.texto for a in assistente.diagnosticar(self.banco, [], True, []))
        self.assertIn("documento comum do Windows", textos)
        assistente.configurar(self.banco, "POS-58", papel_mm=58)
        ConfigController(self.banco).salvar_maquina({"colunas_fita": 48})          # alguém mexeu na mão
        achados = assistente.diagnosticar(self.banco, [Imp("POS-58", "USB001", "POS-58", termica_provavel=True)], True, [])
        self.assertTrue(any("só comporta 32" in a.texto and a.nivel == "erro" for a in achados))


class TesteAjusteCompleto(BaseTeste):
    def test_modo_documento_do_windows_vira_termica_na_impressora_de_cupom(self):
        ConfigController(self.banco).salvar_maquina({"modo_impressao": "windows"})
        lista = [Imp("Microsoft Print to PDF", "PORTPROMPT:", "PDF", padrao=True, virtual=True),
                 Imp("KA 1445", "USB001", "Generic / Text Only", termica_provavel=True)]
        feito = assistente.ajustar_e_ligar(self.banco, 58, "normal", impressoras=lista)
        self.assertEqual((feito["impressora_ligada"], feito["modo"], feito["colunas"]), ("KA 1445", "termica", 32))

    def test_sem_impressora_de_cupom_so_grava_o_tamanho(self):
        ConfigController(self.banco).salvar_maquina({"modo_impressao": "windows"})
        feito = assistente.ajustar_e_ligar(self.banco, 80, "pequena", impressoras=[Imp("HP DeskJet", "IP_1", "HP")])
        self.assertEqual((feito["impressora_ligada"], feito["modo"], feito["colunas"]), ("", "windows", 64))


class TesteRetaguarda(BaseTeste):
    def test_espelho_mostra_a_impressora_e_o_comando_ajusta(self):
        assistente.configurar(self.banco, "KA 1445", papel_mm=80)
        ret = RetaguardaController(self.banco)
        sit = ret.espelho()["impressora"]
        self.assertEqual((sit["impressora"], sit["papel_mm"], sit["colunas"]), ("KA 1445", 80, 48))
        with mock.patch.object(ImpressaoController, "imprimir_teste") as teste:
            ret._executar("impressora.ajustar", {"papel_mm": 58, "letra": "pequena", "cortar": False, "testar": True})
        teste.assert_called_once()
        m = ConfigController(self.banco).maquina()
        self.assertEqual((m["impressora_papel_mm"], m["impressora_letra"], m["colunas_fita"], m["impressora_termica_cortar"]),
                         (58, "pequena", 42, 0))
        self.assertIn("papel de 58 mm", ret.ultimo_detalhe)


class TesteRetaguardaNuvem(BaseTeste):
    def test_nuvem_aceita_a_secao_e_o_comando_e_a_tela_existe(self):
        from pathlib import Path
        raiz = Path(__file__).resolve().parents[1]
        nuvem = (raiz / "backend" / "retaguarda.py").read_text(encoding="utf-8")
        self.assertIn('"impressora.ajustar"', nuvem)
        self.assertIn('prefixo + "/impressora"', nuvem)
        try:
            from backend import retaguarda
        except Exception:                                    # noqa: BLE001 - sem dependências da nuvem
            return
        self.assertTrue(retaguarda.SECAO_VALIDA.fullmatch("impressora"))
        tela = (raiz / "backend" / "retaguarda_web" / "app.js").read_text(encoding="utf-8")
        for trecho in ('botao("impressora", "Impressora do cupom")', "async function telaImpressora()", '"impressora.ajustar"'):
            self.assertIn(trecho, tela)
