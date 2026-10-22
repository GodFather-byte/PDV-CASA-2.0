"""Fechamento do turno para passar o caixa: sobrou/faltou em palavras, sangrias listadas e a assinatura do caixa responsável
e do gerente; impresso sozinho ao trocar o turno. E a via da garota (o texto que ela leva a cada comissão)."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.controllers.cadastro_controller import CadastroController
from src.controllers.comissao_controller import ComissaoController
from src.controllers.impressao_controller import LIMITE_MOVIMENTOS, _ESTILOS, ImpressaoController
from src.core import formatacao as fmt
from src.hardware.impressora_termica import TAMANHO_ALTO, TAMANHO_NORMAL, texto_para_escpos
from tests.test_caixa import BaseCaixa

ESPERADO = 10000 + 880            # fundo de caixa + uma venda de R$ 8,80 em dinheiro


class BaseFechamento(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.imp = ImpressaoController(self.banco)

    def vender_em_dinheiro(self):
        v = self.vender((self.skol, 1), mesa=5)
        self.pagar(v, "Dinheiro", 880)
        self.caixa.fechar(v)

    def fechar(self, declarado, operador=None, justificativa=""):
        return self.turnos.fechar(self.turno, operador or self.adm, declarado, justificativa=justificativa)

    def fita(self, declarado=ESPERADO, operador=None, justificativa=""):
        self.vender_em_dinheiro()
        return self.imp.fechamento(self.fechar(declarado, operador, justificativa))


class TesteSobraEFalta(BaseFechamento):
    def test_sobrou_aparece_em_palavras(self):
        texto = self.fita(ESPERADO + 120, justificativa="Sobrou R$ 1,20 na contagem")
        self.assertIn("SOBROU R$ 1,20", texto)
        self.assertNotIn("FALTOU", texto)
        self.assertNotIn("CAIXA CONFERIDO", texto)

    def test_faltou_aparece_em_palavras_e_sem_sinal_de_menos(self):
        texto = self.fita(ESPERADO - 880, justificativa="Faltaram R$ 8,80 na contagem")
        self.assertIn("FALTOU R$ 8,80", texto)
        self.assertNotIn("SOBROU", texto)

    def test_sem_diferenca_diz_que_o_caixa_esta_conferido(self):
        texto = self.fita(ESPERADO)
        self.assertIn("CAIXA CONFERIDO (sem diferença)", texto)
        self.assertNotIn("SOBROU", texto)
        self.assertNotIn("FALTOU", texto)

    def test_o_resultado_numerico_continua_na_fita(self):
        texto = self.fita(ESPERADO + 120, justificativa="Sobrou R$ 1,20 na contagem")
        self.assertIn("SOBROU R$ 1,20", texto)
        self.assertRegex(texto, r"ESPERADO NA GAVETA +108,80")
        self.assertRegex(texto, r"DECLARADO PELO CAIXA +110,00")

    def letra_grande(self, declarado, frase, justificativa=""):
        dados = texto_para_escpos(self.fita(declarado, justificativa=justificativa), **_ESTILOS["fechamento"])
        antes = dados[:dados.index(frase)].rstrip(b" ")                # a frase vem centralizada, depois dos espaços
        self.assertTrue(antes.endswith(TAMANHO_ALTO))                  # o dobro da altura vem logo antes da linha
        self.assertIn(TAMANHO_NORMAL, dados[dados.index(frase):])      # e volta ao normal depois

    def test_sobrou_sai_em_letra_grande_na_termica(self):
        self.letra_grande(ESPERADO + 120, b"SOBROU", "Sobrou R$ 1,20 na contagem")

    def test_faltou_sai_em_letra_grande_na_termica(self):
        self.letra_grande(ESPERADO - 880, b"FALTOU", "Faltaram R$ 8,80 na contagem")

    def test_conferido_sai_em_letra_grande_na_termica(self):
        self.letra_grande(ESPERADO, b"CAIXA CONFERIDO")

class TesteAssinaturas(BaseFechamento):
    def linhas_de_assinatura(self, texto, w=40):
        return [i for i, l in enumerate(texto.splitlines()) if l == "_" * w]

    def test_traz_o_caixa_responsavel_e_o_gerente_no_fim(self):
        texto = self.fita(ESPERADO)
        linhas = [l.strip() for l in texto.splitlines()]
        self.assertIn("Caixa responsável: ADM", linhas)
        self.assertEqual(linhas[-1], "=" * 40)
        i_gerente = linhas.index("Gerente / quem recebe o caixa")
        self.assertGreater(i_gerente, linhas.index("Caixa responsável: ADM"))   # o gerente assina por último
        i_caixa = linhas.index("Caixa responsável: ADM")
        self.assertEqual(linhas[i_caixa - 1], "_" * 40)                        # a linha para assinar vem acima do nome
        self.assertEqual(linhas[i_gerente - 1], "_" * 40)
        self.assertGreater(len(self.linhas_de_assinatura(texto)), 1)

    def test_sem_diferenca_nao_pede_justificativa(self):
        texto = self.fita(ESPERADO)
        self.assertNotIn("Justificativa", texto)
        self.assertEqual(len(self.linhas_de_assinatura(texto)), 2)             # só as duas assinaturas

    def justificativa(self, declarado):
        texto = self.fita(declarado, justificativa="Diferença constatada na contagem física")
        self.assertIn("Justificativa da diferença:", texto)
        self.assertIn("Diferença constatada na contagem física", texto)
        self.assertEqual(len(self.linhas_de_assinatura(texto)), 4)     # 2 linhas de justificativa + 2 de assinatura
        self.assertLess(texto.index("Justificativa"), texto.index("Caixa responsável"))

    def test_sobra_pede_justificativa_com_linhas_para_escrever(self):
        self.justificativa(ESPERADO + 100)

    def test_falta_pede_justificativa_com_linhas_para_escrever(self):
        self.justificativa(ESPERADO - 100)
    def test_assina_quem_fechou_o_turno_e_nao_quem_abriu(self):
        noite = CadastroController(self.banco).salvar("operadores", {"nome": "NOITE", "senha": "1", "nivel": "1"})
        texto = self.fita(ESPERADO, operador=noite)
        self.assertIn("Caixa responsável: NOITE", texto)
        self.assertNotIn("Caixa responsável: ADM", texto)

    def test_nome_comprido_e_cortado_na_coluna(self):
        longo = CadastroController(self.banco).salvar("operadores", {"nome": "A" * 30, "senha": "1", "nivel": "1"})
        texto = self.fita(ESPERADO, operador=longo)
        self.assertTrue(all(len(l) <= 40 for l in texto.splitlines()))

    def test_leitura_x_nao_tem_resultado_nem_assinatura(self):
        self.vender_em_dinheiro()
        texto = self.imp.leitura_x(self.turno)
        for ausente in ("Caixa responsável", "Gerente", "SOBROU", "FALTOU", "CAIXA CONFERIDO", "Justificativa", "RESULTADO"):
            self.assertNotIn(ausente, texto)
        self.assertIn("LEITURA X", texto)


class TesteSangriasNaFita(BaseFechamento):
    def test_lista_cada_sangria_e_suprimento_com_hora_motivo_e_operador(self):
        self.turnos.movimentar(self.turno, self.adm, "saida", 3000, "Pagamento do gelo")
        self.turnos.movimentar(self.turno, self.adm, "entrada", 5000, "Troco do gerente")
        texto = self.fita(ESPERADO - 3000 + 5000)
        self.assertIn("SANGRIAS E SUPRIMENTOS (2)", texto)
        self.assertRegex(texto, r"21:00 Saída +30,00\n +Pagamento do gelo - ADM")
        self.assertRegex(texto, r"21:00 Entrada +50,00\n +Troco do gerente - ADM")

    def test_sem_movimentos_a_secao_nao_aparece(self):
        self.assertNotIn("SANGRIAS", self.fita(ESPERADO))

    def test_o_pagamento_de_comissao_aparece_como_sangria(self):
        CadastroController(self.banco).salvar("garotas", {"numero": 180, "nome": "MARIA", "ativo": "S"})
        com = ComissaoController(self.banco)
        com.lancar(180, 2500, self.turno, self.adm)
        com.pagar(180, self.turno, self.adm, True)
        texto = self.fita(ESPERADO - 2500)
        self.assertIn("Comissão garota 180 MARIA", texto)
        self.assertIn("CAIXA CONFERIDO", texto)                                 # o dinheiro que saiu já está na conta

    def test_lista_longa_e_cortada_com_e_mais_n(self):
        for i in range(LIMITE_MOVIMENTOS + 5):
            self.turnos.movimentar(self.turno, self.adm, "saida", 100, f"gelo {i}")
        texto = self.fita(ESPERADO - 100 * (LIMITE_MOVIMENTOS + 5))
        self.assertIn(f"SANGRIAS E SUPRIMENTOS ({LIMITE_MOVIMENTOS + 5})", texto)
        self.assertIn("... e mais 5", texto)
        self.assertEqual(len(re.findall(r"\d\d:\d\d Saída", texto)), LIMITE_MOVIMENTOS)

    def test_a_leitura_x_tambem_lista_as_sangrias(self):
        self.turnos.movimentar(self.turno, self.adm, "saida", 3000, "Gelo")
        self.assertIn("SANGRIAS E SUPRIMENTOS (1)", self.imp.leitura_x(self.turno))


class TesteLarguraDaFita(BaseFechamento):
    def cabe(self, colunas):
        self.imp.largura = lambda: colunas
        self.turnos.movimentar(self.turno, self.adm, "saida", 3000, "Pagamento de fornecedor com nome bem comprido aqui")
        CadastroController(self.banco).salvar("garotas", {"numero": 180, "nome": "MARIA", "ativo": "S"})
        ComissaoController(self.banco).lancar(180, 2500, self.turno, self.adm)
        linhas = self.fita(ESPERADO - 3000 - 500, justificativa="Faltaram R$ 5,00 na contagem").splitlines()
        self.assertTrue(all(len(l) <= colunas for l in linhas), [l for l in linhas if len(l) > colunas])
        self.assertEqual(linhas[-1], "=" * colunas)
        self.assertIn("_" * colunas, linhas)

    def test_cabe_em_40_colunas(self):
        self.cabe(40)

    def test_cabe_em_48_colunas(self):
        self.cabe(48)

class TesteViaDaGarotaNoTexto(BaseFechamento):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("comissao_em_pontos", "N")        # a via em reais; a via em pontos tem teste em test_comissao_garotas
        self.com = ComissaoController(self.banco)

    def lancar(self, garota, reais):
        return self.com.lancar(garota, round(reais * 100), self.turno, self.adm)

    def via(self, lancamento_id, nome="MARIA"):
        return self.imp.via_comissao(self.com.lancamento(lancamento_id), nome, "ADM")

    def test_traz_a_garota_e_so_o_valor_desta_comissao(self):
        self.lancar(180, 30)
        segunda = self.lancar(180, 5)
        texto = self.via(segunda)
        for trecho in ("COMISSÃO LANÇADA", "VIA DA GAROTA", "Garota: 180 MARIA", "Lançamento nº 2", "Operador: ADM"):
            self.assertIn(trecho, texto)
        self.assertRegex(texto, r"Valor desta comissão +5,00")
        # o que já estava marcado (30,00) não entra nem é somado: a via é só do lançamento que acabou de ser marcado
        self.assertNotIn("30,00", texto)
        self.assertNotIn("35,00", texto)
        self.assertNotIn("TOTAL A RECEBER", texto)

    def test_so_a_garota_dela_entra(self):
        self.lancar(7, 99)
        texto = self.via(self.lancar(180, 25))
        self.assertNotIn("99,00", texto)

    def test_garota_sem_cadastro_sai_so_com_o_numero(self):
        texto = self.via(self.lancar(180, 25), nome="")
        self.assertIn("Garota: 180", texto.splitlines())

    def test_cabe_na_coluna(self):
        for colunas in (40, 48):
            self.imp.largura = lambda c=colunas: c
            ultimo = self.lancar(180, 1234.56)
            linhas = self.via(ultimo, nome="MARIA DAS GRACAS COM NOME MUITO COMPRIDO").splitlines()
            self.assertTrue(all(len(l) <= colunas for l in linhas), [l for l in linhas if len(l) > colunas])

    def test_valor_sai_em_letra_grande_na_termica(self):
        texto = self.via(self.lancar(180, 25))
        dados = texto_para_escpos(texto, **_ESTILOS["via_comissao"])
        self.assertIn(TAMANHO_ALTO, dados[:dados.index(b"Valor desta")][-12:])

    def test_lancamento_inexistente(self):
        self.assertIsNone(self.com.lancamento(999))
        self.assertIsNone(self.imp.imprimir_via_comissao(999, "ADM"))


class TesteImpressaoDaVia(BaseFechamento):
    def setUp(self):
        super().setUp()
        self.pasta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.pasta, True)
        self.imp.pasta_saida = lambda: Path(self.pasta)
        self.com = ComissaoController(self.banco)

    def test_grava_o_historico_e_devolve_o_caminho(self):
        cid = self.com.lancar(180, 2500, self.turno, self.adm)
        caminho = self.imp.imprimir_via_comissao(cid, "ADM")
        self.assertTrue(Path(caminho).name.endswith(f"via_comissao_180_{cid}.txt"))
        self.assertIn("VIA DA GAROTA", Path(caminho).read_text(encoding="utf-8"))

    def test_desligada_nao_grava_nem_imprime(self):
        self.banco.cfg_set("imprimir_via_comissao", "N")
        cid = self.com.lancar(180, 2500, self.turno, self.adm)
        self.assertIsNone(self.imp.imprimir_via_comissao(cid, "ADM"))
        self.assertEqual(list(Path(self.pasta).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
