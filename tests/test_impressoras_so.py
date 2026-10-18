"""Impressoras e portas que o computador enxerga, e o envio RAW pelo spooler do Windows (sem pywin32)."""
from __future__ import annotations

import ctypes
import sys
import unittest
from unittest import mock

from src.hardware import impressora_termica as term
from src.hardware import impressoras_so as so
from src.hardware.impressora_termica import ErroImpressao, ImpressoraTermica


def bruta(nome, porta="USB001", driver="Driver", status=0, atributos=0):
    return {"nome": nome, "porta": porta, "driver": driver, "status": status, "atributos": atributos}


class TesteSituacao(unittest.TestCase):
    def test_pronta_e_ocupada_servem_para_imprimir(self):
        self.assertEqual(so.situacao(0, 0), ("Pronta", True))
        self.assertEqual(so.situacao(so.ST_PRINTING, 0), ("Ocupada", True))

    def test_o_que_impede_de_imprimir(self):
        casos = {so.ST_OFFLINE: "Offline", so.ST_NOT_AVAILABLE: "Offline", so.ST_PAPER_OUT: "Sem papel",
                 so.ST_DOOR_OPEN: "Tampa aberta", so.ST_PAPER_JAM: "Problema com o papel",
                 so.ST_PAPER_PROBLEM: "Problema com o papel", so.ST_ERROR: "Com erro", so.ST_PAUSED: "Pausada",
                 so.ST_USER_INTERVENTION: "Precisa de atenção"}
        for status, esperado in casos.items():
            texto, pronta = so.situacao(status, 0)
            self.assertTrue(texto.startswith(esperado), (status, texto))
            self.assertFalse(pronta)

    def test_usar_impressora_offline_do_windows_conta_como_offline(self):
        texto, pronta = so.situacao(0, so.ATTR_WORK_OFFLINE)
        self.assertTrue(texto.startswith("Offline"))
        self.assertFalse(pronta)

    def test_offline_vence_os_outros_avisos(self):
        self.assertTrue(so.situacao(so.ST_OFFLINE | so.ST_PAPER_OUT, 0)[0].startswith("Offline"))


class TesteClassificacao(unittest.TestCase):
    def test_termicas_de_cupom_conhecidas(self):
        for nome, driver in (("CAIXA", "EPSON TM-T(203dpi) Receipt6"), ("Balcao", "Elgin i9"), ("Cozinha", "Bematech MP-4200 TH"),
                             ("POS-80C", "POS-80C"), ("Bar", "Generic / Text Only"), ("Cupom", "Daruma DR800"),
                             ("Impressora do caixa", "Tanca TP-650"), ("Epson TM-T20", "")):
            self.assertTrue(so._termica(nome, driver), (nome, driver))

    def test_impressoras_comuns_nao_sao_apontadas_como_termicas(self):
        for nome, driver in (("HP DeskJet 5820 series", "HP DeskJet 5820 series"), ("Brother HL-L2350DW", "Brother HL-L2350DW series"),
                             ("Canon MG3600", "Canon MG3600 series")):
            self.assertFalse(so._termica(nome, driver), (nome, driver))

    def test_virtuais_pelo_nome_driver_ou_porta(self):
        self.assertTrue(so._virtual("Microsoft Print to PDF", "Microsoft Print To PDF", "PORTPROMPT:"))
        self.assertTrue(so._virtual("Fax", "Microsoft Shared Fax Driver", "SHRFAX:"))
        self.assertTrue(so._virtual("OneNote for Windows 10", "Microsoft Software Printer Driver", "Microsoft.Office.OneNote"))
        self.assertTrue(so._virtual("AnyDesk Printer", "AnyDesk v4 Printer Driver", "AD_Port"))
        self.assertTrue(so._virtual("Qualquer", "Qualquer", "FILE:"))
        self.assertFalse(so._virtual("CAIXA", "EPSON TM-T(203dpi) Receipt6", "TMUSB001"))


class TesteListagem(unittest.TestCase):
    def listar(self, brutas, padrao=None):
        with mock.patch.object(so, "_WINDOWS", True), mock.patch.object(so, "_enumerar_windows", return_value=brutas), \
                mock.patch.object(so, "_padrao_windows", return_value=padrao):
            return so.listar_impressoras()

    def test_termicas_primeiro_virtuais_por_ultimo_e_o_resto_em_ordem_alfabetica(self):
        lista = self.listar([bruta("Zebra comum", "IP_1", "Laser X"), bruta("Microsoft Print to PDF", "PORTPROMPT:", "Microsoft Print To PDF"),
                             bruta("CAIXA", "TMUSB001", "EPSON TM-T(203dpi) Receipt6"), bruta("Ana", "USB002", "Jato de tinta"),
                             bruta("Fax", "SHRFAX:", "Microsoft Shared Fax Driver")])
        self.assertEqual([i.nome for i in lista], ["CAIXA", "Ana", "Zebra comum", "Fax", "Microsoft Print to PDF"])
        self.assertTrue(lista[0].termica_provavel)
        self.assertFalse(lista[1].termica_provavel)
        self.assertTrue(lista[3].virtual and lista[4].virtual)

    def test_marca_a_padrao_sem_diferenciar_maiusculas(self):
        lista = self.listar([bruta("CAIXA"), bruta("Outra")], padrao="caixa")
        self.assertEqual([(i.nome, i.padrao) for i in lista], [("CAIXA", True), ("Outra", False)])
        self.assertIn("padrão do Windows", lista[0].rotulo)

    def test_traz_porta_driver_e_situacao(self):
        i = self.listar([bruta("CAIXA", "TMUSB001", "EPSON TM-T", so.ST_PAPER_OUT)])[0]
        self.assertEqual((i.porta, i.driver, i.situacao, i.pronta), ("TMUSB001", "EPSON TM-T", "Sem papel", False))

    def test_compartilhada_de_outro_computador_aparece_como_de_rede(self):
        lista = self.listar([bruta(r"\\SERVIDOR\Balcao", "", "", 0, so.ATTR_NETWORK), bruta("Local")])
        self.assertEqual({i.nome: i.de_rede for i in lista}, {r"\\SERVIDOR\Balcao": True, "Local": False})

    def test_ignora_nome_vazio(self):
        self.assertEqual([i.nome for i in self.listar([bruta(""), bruta("   "), bruta("Boa")])], ["Boa"])

    def test_falha_do_sistema_vira_lista_vazia(self):
        with mock.patch.object(so, "_WINDOWS", True), mock.patch.object(so, "_enumerar_windows", side_effect=OSError("sem spooler")):
            self.assertEqual(so.listar_impressoras(), [])

    def test_fora_do_windows_nao_lista_nada(self):
        with mock.patch.object(so, "_WINDOWS", False):
            self.assertEqual(so.listar_impressoras(), [])
            self.assertIsNone(so.impressora_padrao())
            self.assertEqual(so.listar_portas_seriais(), [])


class TestePortasSeriais(unittest.TestCase):
    def test_ordem_numerica_sem_repetir_e_com_descricao_quando_ha(self):
        with mock.patch.object(so, "_portas_do_registro", return_value=["COM10", "COM3", "com2", "COM3", " "]), \
                mock.patch.object(so, "_descricoes_pyserial", return_value={"COM3": "USB-SERIAL CH340 (COM3)", "COM10": "COM10"}):
            portas = so.listar_portas_seriais()
        self.assertEqual([(p.porta, p.descricao) for p in portas],
                         [("COM2", ""), ("COM3", "USB-SERIAL CH340 (COM3)"), ("COM10", "")])

    def test_sem_portas(self):
        with mock.patch.object(so, "_portas_do_registro", return_value=[]):
            self.assertEqual(so.listar_portas_seriais(), [])


@unittest.skipUnless(sys.platform == "win32", "só no Windows")
class TesteNoWindowsDeVerdade(unittest.TestCase):
    """Chama a API real do spooler (somente leitura): valida as estruturas e os tipos dos handles de 64 bits."""

    def test_lista_sem_quebrar_sem_repetir_e_com_no_maximo_uma_padrao(self):
        lista = so.listar_impressoras()
        nomes = [i.nome.lower() for i in lista]
        self.assertEqual(len(nomes), len(set(nomes)))
        self.assertLessEqual(sum(i.padrao for i in lista), 1)
        self.assertTrue(all(i.nome for i in lista))

    def test_portas_seriais_tem_o_formato_comn(self):
        for p in so.listar_portas_seriais():
            self.assertRegex(p.porta, r"^COM\d+$")

    def test_abre_e_fecha_uma_impressora_local_sem_imprimir(self):
        locais = [i for i in so.listar_impressoras() if not i.de_rede]
        if not locais:
            self.skipTest("este Windows não tem impressora local instalada")
        dll = so.winspool()
        handle = ctypes.c_void_p()
        self.assertTrue(dll.OpenPrinterW(locais[0].nome, ctypes.byref(handle), None))
        self.assertTrue(handle.value)
        self.assertTrue(dll.ClosePrinter(handle))

    def test_impressora_que_nao_existe_da_erro_claro(self):
        with self.assertRaises(ErroImpressao) as e:
            term.enviar_spooler("Impressora que nao existe 123", b"x")
        self.assertIn("não encontrada", str(e.exception))


class SpoolFalso:
    """Imita as funções do spooler que o envio usa e guarda o que recebeu, sem tocar em nenhuma impressora."""

    def __init__(self, abre=True, inicia=True, pagina=True, escreve=True, escrito=None):
        self.abre, self.inicia, self.pagina, self.escreve, self.escrito = abre, inicia, pagina, escreve, escrito
        self.chamadas: list[tuple] = []
        self.dados = b""

    def OpenPrinterW(self, nome, ref, padrao):
        self.chamadas.append(("abre", nome))
        if not self.abre:
            return 0
        ref._obj.value = 4321
        return 1

    def StartDocPrinterW(self, handle, nivel, ref):
        self.chamadas.append(("documento", handle.value, nivel, ref._obj.pDocName, ref._obj.pDatatype))
        return 7 if self.inicia else 0

    def StartPagePrinter(self, handle):
        self.chamadas.append(("pagina",))
        return 1 if self.pagina else 0

    def WritePrinter(self, handle, dados, tamanho, ref):
        self.chamadas.append(("escreve", tamanho))
        self.dados += dados
        ref._obj.value = tamanho if self.escrito is None else self.escrito
        return 1 if self.escreve else 0

    def EndPagePrinter(self, handle):
        self.chamadas.append(("fim_pagina",))
        return 1

    def EndDocPrinter(self, handle):
        self.chamadas.append(("fim_documento",))
        return 1

    def ClosePrinter(self, handle):
        self.chamadas.append(("fecha", handle.value))
        return 1


class TesteSpooler(unittest.TestCase):
    def enviar(self, spool, nome="CAIXA", dados=b"\x1b@cupom\x00fim"):
        with mock.patch.object(term.sys, "platform", "win32"), mock.patch.object(so, "winspool", return_value=spool):
            term.enviar_spooler(nome, dados)

    def test_manda_o_documento_raw_na_ordem_certa_e_fecha_a_impressora(self):
        spool, dados = SpoolFalso(), b"\x1b@cupom\x00fim"
        self.enviar(spool, dados=dados)
        self.assertEqual(spool.chamadas, [("abre", "CAIXA"), ("documento", 4321, 1, "PDV Cupom", "RAW"), ("pagina",),
                                          ("escreve", len(dados)), ("fim_pagina",), ("fim_documento",), ("fecha", 4321)])
        self.assertEqual(spool.dados, dados)          # bytes iguais, inclusive o NUL no meio

    def test_impressora_nao_encontrada(self):
        spool = SpoolFalso(abre=False)
        with self.assertRaises(ErroImpressao) as e:
            self.enviar(spool, "Fantasma")
        self.assertIn("'Fantasma' não encontrada", str(e.exception))
        self.assertEqual(spool.chamadas, [("abre", "Fantasma")])         # nada a fechar: nunca abriu

    def test_documento_recusado_ainda_fecha_a_impressora(self):
        spool = SpoolFalso(inicia=False)
        with self.assertRaises(ErroImpressao):
            self.enviar(spool)
        self.assertEqual([c[0] for c in spool.chamadas], ["abre", "documento", "fecha"])

    def test_envio_incompleto_e_erro_e_encerra_documento_e_pagina(self):
        spool = SpoolFalso(escrito=5)
        with self.assertRaises(ErroImpressao) as e:
            self.enviar(spool)
        self.assertIn("Falha ao enviar", str(e.exception))
        self.assertEqual([c[0] for c in spool.chamadas][-3:], ["fim_pagina", "fim_documento", "fecha"])

    def test_falha_na_escrita_tambem_encerra_tudo(self):
        spool = SpoolFalso(escreve=False)
        with self.assertRaises(ErroImpressao):
            self.enviar(spool)
        self.assertEqual([c[0] for c in spool.chamadas][-3:], ["fim_pagina", "fim_documento", "fecha"])

    def test_sem_nome_usa_a_padrao_do_windows(self):
        spool = SpoolFalso()
        with mock.patch.object(so, "impressora_padrao", return_value="CAIXA"):
            self.enviar(spool, nome="  ")
        self.assertEqual(spool.chamadas[0], ("abre", "CAIXA"))

    def test_sem_nome_e_sem_padrao_pede_para_configurar(self):
        with mock.patch.object(so, "impressora_padrao", return_value=None), self.assertRaises(ErroImpressao) as e:
            self.enviar(SpoolFalso(), nome="")
        self.assertIn("Nenhuma impressora do Windows", str(e.exception))

    def test_fora_do_windows_diz_que_so_existe_no_windows(self):
        with mock.patch.object(term.sys, "platform", "linux"), self.assertRaises(ErroImpressao) as e:
            term.enviar_spooler("Qualquer", b"x")
        self.assertIn("só existe no Windows", str(e.exception))

    def test_a_fachada_envia_o_cupom_escpos_pelo_spooler(self):
        spool = SpoolFalso()
        with mock.patch.object(term.sys, "platform", "win32"), mock.patch.object(so, "winspool", return_value=spool):
            ImpressoraTermica(conexao="spooler", endereco="CAIXA").imprimir("TESTE\nTOTAL: 5,00")
        self.assertTrue(spool.dados.startswith(b"\x1b@"))
        self.assertIn(b"TOTAL", spool.dados)
