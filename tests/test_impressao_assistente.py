"""Assistente de impressora (Elgin i9 e parecidas): sugestão, configuração de uma vez e diagnóstico do que impede o cupom de sair."""
from __future__ import annotations

from unittest import mock

from src.controllers import impressao_assistente as assistente
from src.controllers.config_controller import ConfigController
from src.core.erros import ErroNegocio
from src.hardware import impressora_termica as term
from src.hardware.impressoras_so import ImpressoraWindows as Imp
from tests.base import BaseTeste

ELGIN = Imp("Elgin i9", "USB001", "Elgin i9 Series", termica_provavel=True)
PDF = Imp("Microsoft Print to PDF", "PORTPROMPT:", "Microsoft Print To PDF", padrao=True, virtual=True)
HP = Imp("HP DeskJet", "IP_1", "HP DeskJet 5820")


class TesteSugestao(BaseTeste):
    def test_elgin_vem_primeiro_mesmo_sendo_a_virtual_a_padrao(self):
        self.assertEqual(assistente.sugerir([PDF, HP, ELGIN]).nome, "Elgin i9")

    def test_sem_elgin_serve_qualquer_termica_e_nunca_a_virtual(self):
        epson = Imp("CAIXA", "TMUSB001", "EPSON TM-T20", termica_provavel=True)
        self.assertEqual(assistente.sugerir([PDF, HP, epson]).nome, "CAIXA")
        self.assertIsNone(assistente.sugerir([PDF]))
        self.assertEqual(assistente.sugerir([PDF, Imp("Outra", padrao=True)]).nome, "Outra")

    def test_reconhece_o_nome_do_driver_mesmo_com_nome_diferente(self):
        caixa = Imp("CAIXA", "USB001", "ELGIN I9 (USB)")
        self.assertEqual(assistente.sugerir([HP, caixa]).nome, "CAIXA")


class TesteConfigurar(BaseTeste):
    def test_grava_o_perfil_da_elgin_de_uma_vez(self):
        self.assertEqual(ConfigController(self.banco).maquina()["modo_impressao"], "tela")        # de fábrica nada sai na impressora
        assistente.configurar(self.banco, "Elgin i9")
        m = ConfigController(self.banco).maquina()
        self.assertEqual((m["modo_impressao"], m["impressora_termica_conexao"], m["impressora_termica_endereco"]),
                         ("termica", "spooler", "Elgin i9"))
        self.assertEqual((m["colunas_fita"], m["impressora_termica_codepage"], m["impressora_termica_cortar"]), (48, "cp850", 1))

    def test_nao_mexe_na_gaveta_nem_no_logotipo_ja_configurados(self):
        ConfigController(self.banco).salvar_maquina({"impressora_termica_gaveta": "S", "impressora_termica_logotipo": "S"})
        assistente.configurar(self.banco, "Elgin i9")
        m = ConfigController(self.banco).maquina()
        self.assertEqual((m["impressora_termica_gaveta"], m["impressora_termica_logotipo"]), (1, 1))

    def test_sem_nome_nao_configura(self):
        with self.assertRaises(term.ErroImpressao):
            assistente.configurar(self.banco, "  ")

    def test_depois_de_configurar_o_cupom_vai_para_a_fila_do_windows(self):
        assistente.configurar(self.banco, "Elgin i9")
        from src.controllers.impressao_controller import ImpressaoController
        imp = ImpressaoController(self.banco)
        imp.enviar("CUPOM TESTE\nTOTAL 1,00", "teste", "cupom")
        item = self.banco.um("SELECT * FROM fila_impressao")
        self.assertEqual((item["destino"], item["status"]), ("caixa", "pendente"))
        usados = []
        with mock.patch.object(term, "enviar_spooler", side_effect=lambda nome, dados, doc="x": usados.append((nome, bytes(dados)))):
            imp.fila.processar()
        self.assertEqual(usados[0][0], "Elgin i9")
        self.assertTrue(usados[0][1].startswith(b"\x1b@"))                  # ESC @ : começa reiniciando a impressora
        self.assertIn(b"TOTAL", usados[0][1])


class TesteDiagnostico(BaseTeste):
    def niveis(self, **kw):
        return [(a.nivel, a.texto) for a in assistente.diagnosticar(self.banco, spooler=kw.pop("spooler", True), **kw)]

    def test_de_fabrica_avisa_que_o_caixa_esta_em_modo_tela(self):
        erros = [t for n, t in self.niveis(impressoras=[ELGIN]) if n == "erro"]
        self.assertTrue(any("modo 'tela'" in t and "NÃO vão para a impressora" in t for t in erros), erros)

    def test_configuracao_certa_e_impressora_pronta_nao_tem_erro(self):
        assistente.configurar(self.banco, "Elgin i9")
        achados = self.niveis(impressoras=[ELGIN, PDF])
        self.assertEqual([n for n, _ in achados], ["ok"])

    def test_nome_que_nao_existe_no_windows(self):
        assistente.configurar(self.banco, "Elgin i9 antiga")
        erros = [t for n, t in self.niveis(impressoras=[ELGIN]) if n == "erro"]
        self.assertTrue(any("nenhuma impressora chamada 'Elgin i9 antiga'" in t for t in erros))

    def test_impressora_offline_pausada_e_fila_presa(self):
        assistente.configurar(self.banco, "Elgin i9")
        off = Imp("Elgin i9", "USB001", "Elgin i9 Series", offline=True, trabalhos=3)
        self.assertTrue(any("OFFLINE" in t for _, t in self.niveis(impressoras=[off])))
        pausada = Imp("Elgin i9", "USB001", "Elgin i9 Series", pausada=True)
        self.assertTrue(any("PAUSADA" in t for _, t in self.niveis(impressoras=[pausada])))
        presa = Imp("Elgin i9", "USB001", "Elgin i9 Series", trabalhos=4)
        achados = self.niveis(impressoras=[presa])
        self.assertIn(("aviso", "Há 4 documento(s) parado(s) na fila do Windows de 'Elgin i9'."), achados)

    def test_spooler_parado(self):
        assistente.configurar(self.banco, "Elgin i9")
        self.assertTrue(any("Spooler de Impressão" in t and n == "erro" for n, t in self.niveis(impressoras=[ELGIN], spooler=False)))

    def test_virtual_escolhida_e_erro(self):
        assistente.configurar(self.banco, "Microsoft Print to PDF")
        self.assertTrue(any("virtual" in t and n == "erro" for n, t in self.niveis(impressoras=[PDF])))

    def test_fila_do_pdv_com_erro_aparece_com_o_ultimo_erro(self):
        assistente.configurar(self.banco, "Elgin i9")
        item = self.banco.inserir("fila_impressao", {"criado_em": "2026-10-09 20:00:00", "destino": "caixa", "nome": "cupom_1", "dados": b"x",
                                                     "status": "erro", "tentativas": 60, "ultimo_erro": "Impressora 'Elgin i9' não encontrada [erro 1801]"})
        achados = self.niveis(impressoras=[ELGIN])
        self.assertTrue(any(n == "erro" and "1 com erro" in t and "1801" in t for n, t in achados), achados)

    def test_relatorio_junta_configuracao_impressoras_fila_e_achados(self):
        assistente.configurar(self.banco, "Elgin i9")
        texto = assistente.relatorio(self.banco, [ELGIN, PDF], spooler=True, versao="1.2.0")
        for esperado in ("DIAGNÓSTICO DE IMPRESSÃO — WillPDV 1.2.0", "modo: termica   conexão: spooler   endereço: Elgin i9",
                         "Spooler de Impressão do Windows: rodando", "- Elgin i9  porta: USB001  driver: Elgin i9 Series",
                         "[virtual]", "[OK] Configuração do caixa conferida"):
            self.assertIn(esperado, texto)


class TesteErrosDoWindows(BaseTeste):
    def test_dicas_em_portugues_para_os_erros_que_mais_aparecem(self):
        for codigo in (5, 1722, 1801, 1804, 1906):
            self.assertIn(codigo, term.DICAS_WINDOWS)
            self.assertTrue(term.DICAS_WINDOWS[codigo].strip())
        with mock.patch.object(term.ctypes, "get_last_error", lambda: 1801, create=True), \
                mock.patch.object(term.ctypes, "FormatError", lambda c: "Nome de impressora inválido.", create=True):
            msg = term._erro_windows()
        self.assertIn("[erro 1801]", msg)
        self.assertIn("Assistente de impressora", msg)

    def test_codigo_sem_dica_continua_mostrando_o_codigo(self):
        with mock.patch.object(term.ctypes, "get_last_error", lambda: 9999, create=True), \
                mock.patch.object(term.ctypes, "FormatError", lambda c: "Algo.", create=True):
            self.assertEqual(term._erro_windows(), "Algo. [erro 9999]")


class TesteElginNaoInstalada(BaseTeste):
    """O caso real: no Windows só aparecem PDF/XPS/OneNote, a Elgin i9 nunca foi instalada."""

    VIRTUAIS = [PDF, Imp("Microsoft XPS Document Writer", "PORTPROMPT:", "Microsoft XPS Document Writer v4", virtual=True)]

    def achados(self, impressoras, portas):
        return [(a.nivel, a.texto, a.solucao) for a in assistente.diagnosticar(self.banco, impressoras, True, portas)]

    def test_com_porta_usb_manda_instalar_o_driver_generico(self):
        erros = [a for a in self.achados(self.VIRTUAIS, ["USB001"]) if a[0] == "erro"]
        texto = " ".join(a[1] + a[2] for a in erros)
        self.assertIn("não está instalada no Windows", texto)
        self.assertIn("USB001", texto)
        self.assertIn("Instalar Elgin i9 (driver genérico)", texto)

    def test_sem_porta_usb_manda_conferir_cabo_e_energia(self):
        erros = [a for a in self.achados(self.VIRTUAIS, []) if a[0] == "erro"]
        texto = " ".join(a[1] + a[2] for a in erros)
        self.assertIn("nada de impressora detectado no cabo USB", texto)
        self.assertIn("cabo", texto)

    def test_com_a_elgin_instalada_o_aviso_some(self):
        achados = self.achados([ELGIN, *self.VIRTUAIS], ["USB001"])
        self.assertFalse([a for a in achados if "não está instalada" in a[1] or "não encontrou a Elgin" in a[1]])

    def test_relatorio_mostra_as_portas_usb(self):
        self.assertIn("Portas USB de impressora detectadas: USB001", assistente.relatorio(self.banco, self.VIRTUAIS, True, portas_usb=["USB001"]))
        self.assertIn("Portas USB de impressora detectadas: nenhuma", assistente.relatorio(self.banco, self.VIRTUAIS, True, portas_usb=[]))


class TesteInstalarGenerica(BaseTeste):
    def test_fora_do_windows_recusa(self):
        with mock.patch.object(assistente, "_eh_windows", return_value=False), self.assertRaisesRegex(term.ErroImpressao, "só existe no Windows"):
            assistente.instalar_generica()

    def test_sem_porta_usb_explica_o_que_conferir(self):
        with mock.patch.object(assistente, "_eh_windows", return_value=True), \
                mock.patch.object(assistente.impressoras_so, "listar_impressoras", return_value=[PDF]), \
                mock.patch.object(assistente.impressoras_so, "listar_portas_usb", return_value=[]), \
                self.assertRaisesRegex(term.ErroImpressao, "não detectou nenhuma impressora na USB"):
            assistente.instalar_generica()

    def test_instala_com_o_printui_na_porta_usb_e_confere_o_resultado(self):
        chamadas = []
        instalada = Imp("Elgin i9", "USB001", "Generic / Text Only")
        listas = iter([[PDF], [PDF, instalada]])                      # antes não existe; depois que o printui roda, existe
        with mock.patch.object(assistente, "_eh_windows", return_value=True), \
                mock.patch.object(assistente.impressoras_so, "listar_impressoras", side_effect=lambda: next(listas)), \
                mock.patch.object(assistente.impressoras_so, "listar_portas_usb", return_value=["USB001"]), \
                mock.patch.object(assistente.subprocess, "run", side_effect=lambda cmd, **kw: chamadas.append(cmd)):
            self.assertEqual(assistente.instalar_generica(), "Elgin i9")
        comando = chamadas[0]
        self.assertEqual(comando[:3], ["rundll32", "printui.dll,PrintUIEntry", "/if"])
        self.assertIn("USB001", comando)
        self.assertIn("Generic / Text Only", comando)
        self.assertEqual(comando[comando.index("/b") + 1], "Elgin i9")

    def test_se_o_windows_nao_instalou_orienta_a_instalar_a_mao(self):
        with mock.patch.object(assistente, "_eh_windows", return_value=True), \
                mock.patch.object(assistente.impressoras_so, "listar_impressoras", return_value=[PDF]), \
                mock.patch.object(assistente.impressoras_so, "listar_portas_usb", return_value=["USB002"]), \
                mock.patch.object(assistente.subprocess, "run"), \
                self.assertRaisesRegex(term.ErroImpressao, "USB002.*Generic / Text Only"):
            assistente.instalar_generica()

    def test_ja_instalada_nao_roda_de_novo(self):
        with mock.patch.object(assistente, "_eh_windows", return_value=True), \
                mock.patch.object(assistente.impressoras_so, "listar_impressoras", return_value=[ELGIN]), \
                mock.patch.object(assistente.subprocess, "run") as rodar:
            self.assertEqual(assistente.instalar_generica("Elgin i9"), "Elgin i9")
        rodar.assert_not_called()
