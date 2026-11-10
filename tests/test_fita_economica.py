"""Fita econômica: menos papel com o mesmo conteúdo, e linhas mais juntas na térmica."""
from src.controllers.impressao_controller import ImpressaoController
from src.core import fita
from src.hardware import impressora_termica as term
from tests.test_caixa import BaseCaixa


class TesteCompactar(BaseCaixa):
    def test_moldura_vira_uma_linha_e_branco_some_sem_perder_conteudo(self):
        original = "\n".join(["LOJA".center(40), "=" * 40, "CUPOM NÃO FISCAL".center(40), "=" * 40, "Cupom: 1",
                              "-" * 40, "1   SKOL  8,00", "-" * 40, "TOTAL  R$ 8,00", "",
                              " PAGAMENTO ".center(40, "-"), "Dinheiro  8,00", "=" * 40, "Obrigado!".center(40), "=" * 40])
        compacto = fita.compactar(original, 40, ("TOTAL",))
        linhas = compacto.split("\n")
        self.assertEqual(len(linhas), len(original.split("\n")) - 5)
        self.assertEqual(linhas[1], " CUPOM NÃO FISCAL ".center(40, "="))
        self.assertEqual(linhas[-1], " Obrigado! ".center(40, "="))
        self.assertNotIn("", linhas)
        for trecho in ("Cupom: 1", "1   SKOL  8,00", "TOTAL  R$ 8,00", "Dinheiro  8,00"):
            self.assertIn(trecho, linhas)
        self.assertTrue(all(len(l) <= 40 for l in linhas))

    def test_linha_em_destaque_sai_da_moldura_sozinha_para_continuar_grande(self):
        compacto = fita.compactar("\n".join(["=" * 40, "FALTOU R$ 3,00".center(40), "=" * 40, "resto"]), 40, ("FALTOU",))
        self.assertEqual(compacto.split("\n"), ["FALTOU R$ 3,00".center(40), "resto"])

    def test_espaco_para_assinar_continua(self):
        original = "\n".join([" ASSINATURAS ".center(40, "-"), "", "", "_" * 40, "Caixa responsável", "", "", "_" * 40, "Gerente"])
        self.assertEqual(fita.compactar(original, 40), original)

    def test_titulo_comprido_nao_estoura_a_largura(self):
        compacto = fita.compactar("\n".join(["=" * 32, "PARCIAL DO TURNO (LEITURA X)", "=" * 32]), 32)
        self.assertEqual(compacto.split("\n"), ["=" * 32, "PARCIAL DO TURNO (LEITURA X)"])

    def test_cupom_e_fechamento_reais_ficam_menores_com_os_mesmos_valores(self):
        venda = self.vender((self.skol, 2), (self.agua, 1))
        self.pagar(venda, "Dinheiro", 2000)
        self.caixa.fechar(venda)
        imp = ImpressaoController(self.banco)
        cupom = imp.cupom(venda)
        compacto = fita.compactar(cupom, imp.largura(), ("TOTAL",))
        self.assertLess(len(compacto.split("\n")), len(cupom.split("\n")) - 3)
        resumo = self.turnos.fechar(self.turno, self.adm, self.turnos.resumo(self.turno)["esperado"])
        fechamento = imp.fechamento(resumo)
        curto = fita.compactar(fechamento, imp.largura(), ("ESPERADO NA GAVETA", "CAIXA CONFERIDO"))
        self.assertLess(len(curto.split("\n")), len(fechamento.split("\n")) * 0.9)
        for texto, menor in ((cupom, compacto), (fechamento, curto)):
            for linha in texto.split("\n"):                      # toda linha com valor continua igual
                if any(c.isdigit() for c in linha) and not set(linha.strip()) <= set("=-_ "):
                    if not (linha.strip().startswith("Impresso em")):
                        self.assertIn(linha.strip(), menor, linha)


class TesteEnvioEconomico(BaseCaixa):
    def setUp(self):
        super().setUp()
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        saida = patch.object(ImpressaoController, "pasta_saida", lambda _self: Path(pasta.name))
        saida.start()
        self.addCleanup(saida.stop)
        self.imp = ImpressaoController(self.banco)
        self.texto = "\n".join(["LOJA", "=" * 40, "CUPOM NÃO FISCAL".center(40), "=" * 40, "", "TOTAL  R$ 8,00"])

    def test_envio_grava_a_fita_compacta_e_desligado_grava_a_original(self):
        from pathlib import Path
        self.assertEqual(self.banco.cfg("papel_economico"), "S")
        gravado = Path(self.imp.enviar(self.texto, "cupom_a", tipo="cupom")).read_text(encoding="utf-8")
        self.assertEqual(len(gravado.strip("\n").split("\n")), 3)
        self.banco.cfg_set("papel_economico", "N")
        gravado = Path(self.imp.enviar(self.texto, "cupom_b", tipo="cupom")).read_text(encoding="utf-8")
        self.assertEqual(gravado.strip("\n"), self.texto)

    def test_termica_recebe_o_espaco_reduzido_e_volta_ao_padrao_antes_do_corte(self):
        dados = term.texto_para_escpos("LINHA", espacamento=term.ESPACO_ECONOMICO)
        reduzido, padrao = term.espaco_entre_linhas(term.ESPACO_ECONOMICO), term.ESPACO_PADRAO
        self.assertEqual(reduzido, b"\x1b3\x1a")
        self.assertLess(dados.index(reduzido), dados.index(b"LINHA"))
        self.assertLess(dados.index(b"LINHA"), dados.index(padrao))
        self.assertLess(dados.index(padrao), dados.index(term.cortar_papel()))
        sem = term.texto_para_escpos("LINHA")
        self.assertNotIn(b"\x1b3", sem)
        self.assertNotIn(padrao, sem)
        self.assertEqual(term.espaco_entre_linhas(5), b"\x1b3\x18")   # nunca abaixo da altura da letra
