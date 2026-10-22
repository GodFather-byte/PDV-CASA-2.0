"""Fila de impressão assíncrona, serviço em segundo plano, logotipo BMP -> ESC/POS, vias e gaveta por forma de pagamento."""
from __future__ import annotations

import os
import shutil
import struct
import tempfile
import time
import unittest
from pathlib import Path

from src.controllers.config_controller import ConfigController
from src.controllers.fila_impressao_controller import (ESPERAS, MAX_TENTATIVAS, FilaImpressao,
                                                       ServicoFilaImpressao)
from src.controllers.impressao_controller import ImpressaoController
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.hardware import imagem_escpos as img
from src.hardware.impressora_termica import ErroImpressao
from tests.base import BaseTeste
from tests.test_caixa import BaseCaixa
from tests.test_impressao import impressora_falsa


# ------------------------------------------------------------------ fila (sem thread)
class TesteFila(BaseTeste):
    def setUp(self):
        super().setUp()
        self.enviados: list[str] = []
        self.falhar = False

        def enviador(item, maquina):
            if self.falhar:
                raise ErroImpressao("impressora offline")
            self.enviados.append(item["nome"])
        self.fila = FilaImpressao(self.banco, enviador)

    def novo(self, nome="cupom_1", destino="caixa", dados=b"\x1b@abc"):
        return self.fila.enfileirar(destino, nome, dados, tipo="cupom")

    def test_envia_em_ordem_e_marca_enviado(self):
        for n in ("a", "b", "c"):
            self.novo(n)
        self.assertEqual(self.fila.processar(), {"enviados": 3, "falhas": 0})
        self.assertEqual(self.enviados, ["a", "b", "c"])
        self.assertEqual(self.fila.contagem(), {"pendentes": 0, "falhando": 0, "erros": 0, "ultimo_erro": None})
        self.assertTrue(all(i["status"] == "enviado" and i["enviado_em"] for i in self.fila.listar()))

    def test_bytes_gravados_sao_os_mesmos(self):
        dados = bytes(range(256))
        iid = self.novo(dados=dados)
        self.assertEqual(self.banco.valor("SELECT dados FROM fila_impressao WHERE id = ?", (iid,)), dados)

    def test_falha_agenda_nova_tentativa_e_nao_tenta_antes_da_hora(self):
        self.falhar = True
        self.novo("cupom")
        self.assertEqual(self.fila.processar(), {"enviados": 0, "falhas": 1})
        item = self.fila.listar()[0]
        self.assertEqual((item["status"], item["tentativas"], item["ultimo_erro"]), ("pendente", 1, "impressora offline"))
        self.assertEqual(item["proxima_tentativa"], "2026-10-03 21:00:05")      # relógio fixo + 5 s
        self.falhar = False
        self.assertEqual(self.fila.processar(), {"enviados": 0, "falhas": 0})   # ainda não é a hora
        self.assertEqual(self.enviados, [])
        self.avancar(seconds=6)
        self.assertEqual(self.fila.processar(), {"enviados": 1, "falhas": 0})
        self.assertEqual(self.enviados, ["cupom"])
        self.assertIsNone(self.fila.listar()[0]["ultimo_erro"])               # limpou o erro ao imprimir

    def test_espera_cresce_ate_o_limite(self):
        self.falhar = True
        self.novo()
        esperas = []
        for _ in range(7):
            self.avancar(hours=1)                                              # sempre vencido
            self.fila.processar()
            item = self.fila.listar()[0]
            esperas.append(int((fmt_dt(item["proxima_tentativa"]) - self._hora["t"]).total_seconds()))
        self.assertEqual(esperas, [5, 10, 20, 40, 60, 60, 60])
        self.assertEqual(ESPERAS[-1], 60)

    def test_ordem_preservada_primeiro_com_falha_segura_os_seguintes(self):
        self.falhar = True
        self.novo("primeiro")
        self.novo("segundo")
        self.fila.processar()
        self.falhar = False
        self.assertEqual(self.fila.processar()["enviados"], 0)                # primeiro espera; segundo NÃO passa na frente
        self.avancar(seconds=6)
        self.fila.processar()
        self.assertEqual(self.enviados, ["primeiro", "segundo"])

    def test_destinos_sao_independentes(self):
        def enviador(item, maquina):
            if item["destino"] == "caixa":
                raise ErroImpressao("caixa offline")
            self.enviados.append(item["nome"])
        fila = FilaImpressao(self.banco, enviador)
        fila.enfileirar("caixa", "cupom", b"x")
        fila.enfileirar("remota", "cozinha", b"y")
        fila.processar()
        self.assertEqual(self.enviados, ["cozinha"])                           # a cozinha imprime mesmo com o caixa fora

    def test_depois_do_limite_vira_erro_e_o_operador_reenvia(self):
        self.falhar = True
        self.novo("preso")
        self.novo("depois")
        for _ in range(MAX_TENTATIVAS):
            self.avancar(hours=1)
            self.fila.processar()
        preso = next(i for i in self.fila.listar() if i["nome"] == "preso")
        self.assertEqual(preso["status"], "erro")
        self.assertEqual(self.fila.texto_indicador()[1], "erro")
        self.falhar = False
        self.fila.processar()
        self.assertEqual(self.enviados, ["depois"])                            # item com erro não bloqueia os outros
        self.fila.reenviar(preso["id"])
        self.fila.processar()
        self.assertEqual(self.enviados, ["depois", "preso"])

    def test_cancelar_e_reenviar_todos(self):
        a, b = self.novo("a"), self.novo("b")
        self.fila.cancelar(a)
        self.fila.processar()
        self.assertEqual(self.enviados, ["b"])
        with self.assertRaises(ErroNegocio):
            self.fila.cancelar(b)                                              # já impresso
        with self.assertRaises(ErroNegocio):
            self.fila.reenviar(b)
        self.fila.reenviar(a)                                                  # cancelado volta para a fila
        self.fila.processar()
        self.assertEqual(self.enviados, ["b", "a"])

    def test_reenviar_todos_antecipa_quem_esta_esperando(self):
        self.falhar = True
        self.novo("x")
        self.fila.processar()
        self.falhar = False
        self.assertEqual(self.fila.reenviar_todos(), 1)
        self.assertEqual(self.fila.processar()["enviados"], 1)

    def test_limpar_antigos_so_apaga_o_que_ja_saiu(self):
        a = self.novo("velho")
        self.novo("pendente")
        self.fila.enviador = lambda item, maq: (_ for _ in ()).throw(ErroImpressao("x")) if item["nome"] == "pendente" else None
        self.fila.processar()
        self.avancar(days=10)
        self.assertEqual(self.fila.limpar_antigos(dias=7), 1)
        self.assertEqual([i["nome"] for i in self.fila.listar()], ["pendente"])

    def test_validacoes(self):
        with self.assertRaises(ErroNegocio):
            self.fila.enfileirar("inexistente", "x", b"y")
        with self.assertRaises(ErroNegocio):
            self.fila.enfileirar("caixa", "x", b"")

    def test_indicador_do_caixa(self):
        self.assertEqual(self.fila.texto_indicador(), ("Impressora: ok", "ok"))
        self.novo()
        self.assertEqual(self.fila.texto_indicador()[1], "aviso")
        self.falhar = True
        self.fila.processar()
        texto, nivel = self.fila.texto_indicador()
        self.assertEqual(nivel, "aviso")
        self.assertIn("fora", texto)

    def test_enfileirar_com_setor_grava_a_coluna(self):
        setor_id = self.banco.inserir("setores_impressao", {"nome": "Cozinha", "conexao": "pasta", "ativo": 1, "ordem": 0})
        iid = self.fila.enfileirar("remota", "pedido_cozinha", b"x", setor_id=setor_id)
        self.assertEqual(self.banco.valor("SELECT setor_id FROM fila_impressao WHERE id = ?", (iid,)), setor_id)

    def test_enfileirar_sem_setor_grava_nulo(self):
        iid = self.novo(destino="remota")
        self.assertIsNone(self.banco.valor("SELECT setor_id FROM fila_impressao WHERE id = ?", (iid,)))


# ------------------------------------------------ enviador padrão (sem mock) e setor de impressão
class TesteEnviadorPadraoSetor(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.imp = ImpressaoController(self.banco)

    def test_enviador_padrao_resolve_a_conexao_do_setor(self):
        with impressora_falsa() as (endereco_setor, recebido):
            setor_id = self.banco.inserir("setores_impressao", {
                "nome": "Bar", "conexao": "rede", "endereco": endereco_setor, "ativo": 1, "ordem": 0})
            self.banco.executar(
                "UPDATE maquinas SET impressora_remota_conexao='rede', impressora_remota_endereco='127.0.0.1:1'")
            self.imp.fila.enfileirar("remota", "pedido_bar", b"\x1b@TESTE", setor_id=setor_id)
            self.assertEqual(self.imp.fila.processar()["enviados"], 1)
        self.assertEqual(recebido["dados"], b"\x1b@TESTE")


def fmt_dt(texto: str):
    from datetime import datetime
    return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------- serviço em segundo plano
class TesteServico(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.caminho = os.path.join(self.dir, "pdv.db")
        self.banco = BancoDados(self.caminho)
        self.addCleanup(self.banco.fechar)

    def esperar(self, condicao, limite=6.0):
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            if condicao():
                return True
            time.sleep(0.05)
        return False

    def test_recusa_banco_em_memoria(self):
        with self.assertRaises(ErroNegocio):
            ServicoFilaImpressao(":memory:")

    def test_thread_imprime_sem_ninguem_chamar_processar(self):
        with impressora_falsa() as (endereco, recebido):
            ConfigController(self.banco).salvar_maquina({
                "modo_impressao": "termica", "impressora_termica_conexao": "rede", "impressora_termica_endereco": endereco})
            servico = ServicoFilaImpressao(self.caminho, intervalo=0.05)
            servico.iniciar()
            self.addCleanup(servico.parar)
            ImpressaoController(self.banco).enviar("TOTAL 10,00", "cupom_9", tipo="cupom")
            fila = FilaImpressao(self.banco)
            self.assertTrue(self.esperar(lambda: fila.contagem()["pendentes"] == 0 and fila.listar()[0]["status"] == "enviado"),
                            fila.listar())
        self.assertTrue(recebido["dados"].startswith(b"\x1b@"))
        self.assertIn(b"TOTAL", recebido["dados"])

    def test_enfileirar_volta_na_hora_com_a_impressora_fora_e_a_thread_continua_tentando(self):
        ConfigController(self.banco).salvar_maquina({
            "modo_impressao": "termica", "impressora_termica_conexao": "rede", "impressora_termica_endereco": "127.0.0.1:1"})
        servico = ServicoFilaImpressao(self.caminho, intervalo=0.05)
        servico.iniciar()
        self.addCleanup(servico.parar)
        imp = ImpressaoController(self.banco)
        inicio = time.monotonic()
        imp.enviar("TOTAL 1,00", "cupom_1", tipo="cupom")
        self.assertLess(time.monotonic() - inicio, 2.0)
        fila = FilaImpressao(self.banco)
        self.assertTrue(self.esperar(lambda: fila.listar()[0]["tentativas"] >= 1), fila.listar())
        item = fila.listar()[0]
        self.assertEqual(item["status"], "pendente")                           # não se perdeu
        self.assertTrue(item["ultimo_erro"])

    def test_impressora_volta_e_o_que_ficou_na_fila_sai(self):
        imp = ImpressaoController(self.banco)
        cfg = ConfigController(self.banco)
        cfg.salvar_maquina({"modo_impressao": "termica", "impressora_termica_conexao": "rede",
                            "impressora_termica_endereco": "127.0.0.1:1"})
        servico = ServicoFilaImpressao(self.caminho, intervalo=0.05)
        servico.iniciar()
        self.addCleanup(servico.parar)
        imp.enviar("PRIMEIRO", "cupom_1", tipo="cupom")
        fila = FilaImpressao(self.banco)
        self.assertTrue(self.esperar(lambda: fila.listar()[0]["tentativas"] >= 1))
        with impressora_falsa() as (endereco, recebido):
            cfg.salvar_maquina({"impressora_termica_endereco": endereco})
            fila.reenviar_todos()                                               # operador aperta "reenviar"
            self.assertTrue(self.esperar(lambda: fila.listar()[0]["status"] == "enviado"), fila.listar())
        self.assertIn(b"PRIMEIRO", recebido["dados"])

    def test_parar_encerra_a_thread(self):
        servico = ServicoFilaImpressao(self.caminho, intervalo=0.05)
        servico.iniciar()
        self.assertTrue(servico.ativo)
        servico.parar()
        self.assertFalse(servico.ativo)


# --------------------------------------------------------------------------- logotipo BMP
def gravar_bmp(caminho, linhas_rgb, bpp=24, de_cima_para_baixo=False, paleta=None, indices=None):
    """BMP mínimo. linhas_rgb: lista de linhas (de cima para baixo) de tuplas (r, g, b). Para 8/1 bits use `indices` + `paleta`."""
    altura = len(linhas_rgb) if bpp == 24 else len(indices)
    largura = len(linhas_rgb[0]) if bpp == 24 else len(indices[0])
    if bpp == 24:
        tam_linha = ((largura * 24 + 31) // 32) * 4
        linhas = [b"".join(bytes((b, g, r)) for r, g, b in lin).ljust(tam_linha, b"\0") for lin in linhas_rgb]
        pal = b""
    else:
        tam_linha = ((largura * bpp + 31) // 32) * 4
        pal = b"".join(bytes((b, g, r, 0)) for r, g, b in paleta)
        linhas = []
        for lin in indices:
            if bpp == 8:
                bruto = bytes(lin)
            else:  # 1 bit
                bruto = bytearray((largura + 7) // 8)
                for x, v in enumerate(lin):
                    if v:
                        bruto[x // 8] |= 0x80 >> (x % 8)
                bruto = bytes(bruto)
            linhas.append(bruto.ljust(tam_linha, b"\0"))
    if not de_cima_para_baixo:
        linhas = linhas[::-1]
    corpo = b"".join(linhas)
    offset = 14 + 40 + len(pal)
    cab = b"BM" + struct.pack("<IHHI", offset + len(corpo), 0, 0, offset)
    dib = struct.pack("<IiiHHIIiiII", 40, largura, -altura if de_cima_para_baixo else altura, 1, bpp, 0,
                      len(corpo), 2835, 2835, len(paleta or []), 0)
    Path(caminho).write_bytes(cab + dib + pal + corpo)


PRETO, BRANCO = (0, 0, 0), (255, 255, 255)


class TesteImagem(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def arq(self, nome="logo.bmp"):
        return os.path.join(self.dir, nome)

    def test_24_bits_preto_em_cima_branco_embaixo(self):
        gravar_bmp(self.arq(), [[PRETO] * 16, [BRANCO] * 16])
        l, a, linhas = img.ler_bmp(self.arq())
        self.assertEqual((l, a), (16, 2))
        self.assertEqual(linhas[0], [0] * 16)
        self.assertEqual(linhas[1], [255] * 16)
        raster = img.para_raster(l, a, linhas)
        self.assertEqual(raster, b"\x1dv0\x00" + struct.pack("<HH", 2, 2) + b"\xff\xff" + b"\x00\x00")

    def test_largura_nao_multipla_de_8_completa_com_branco(self):
        gravar_bmp(self.arq(), [[PRETO] * 10])
        raster = img.para_raster(*img.ler_bmp(self.arq()))
        self.assertEqual(raster, b"\x1dv0\x00" + struct.pack("<HH", 2, 1) + b"\xff\xc0")   # 10 pontos pretos, 6 de folga

    def test_paleta_de_8_bits_e_orientacao_de_baixo_para_cima(self):
        gravar_bmp(self.arq(), None, bpp=8, paleta=[BRANCO, PRETO], indices=[[1, 1, 1, 1], [0, 0, 0, 0], [1, 0, 1, 0]])
        l, a, linhas = img.ler_bmp(self.arq())
        self.assertEqual(linhas[0], [0, 0, 0, 0])            # primeira linha de cima = a que foi gravada primeiro
        self.assertEqual(linhas[1], [255, 255, 255, 255])
        self.assertEqual(linhas[2], [0, 255, 0, 255])

    def test_de_cima_para_baixo_e_1_bit(self):
        gravar_bmp(self.arq(), None, bpp=1, de_cima_para_baixo=True, paleta=[PRETO, BRANCO], indices=[[0, 1, 0, 1], [1, 1, 1, 1]])
        _, _, linhas = img.ler_bmp(self.arq())
        self.assertEqual(linhas[0], [0, 255, 0, 255])
        self.assertEqual(linhas[1], [255] * 4)

    def test_imagem_larga_e_reduzida_para_a_largura_da_impressora(self):
        gravar_bmp(self.arq(), [[PRETO] * 1000 for _ in range(100)])
        l, a, linhas = img.ler_bmp(self.arq())
        raster = img.para_raster(l, a, linhas, max_largura=384)
        bytes_linha, altura = struct.unpack_from("<HH", raster, 4)
        self.assertEqual((bytes_linha, altura), (48, 38))     # 384 pontos; 100 * 384 / 1000 = 38 linhas

    def test_imagem_alta_e_dividida_em_blocos(self):
        gravar_bmp(self.arq(), [[PRETO] * 8 for _ in range(450)])
        raster = img.para_raster(*img.ler_bmp(self.arq()))
        self.assertEqual(raster.count(b"\x1dv0\x00"), 3)       # 200 + 200 + 50 linhas

    def test_arquivos_invalidos_dao_erro_claro(self):
        Path(self.arq("x.bmp")).write_bytes(b"isto nao e um bmp" * 10)
        with self.assertRaises(ErroImpressao) as e:
            img.ler_bmp(self.arq("x.bmp"))
        self.assertIn("BMP", str(e.exception))
        with self.assertRaises(ErroImpressao):
            img.ler_bmp(self.arq("nao_existe.bmp"))
        gravar_bmp(self.arq("t.bmp"), [[PRETO] * 16] * 4)
        truncado = Path(self.arq("t.bmp")).read_bytes()[:-20]
        Path(self.arq("trunc.bmp")).write_bytes(truncado)
        with self.assertRaises(ErroImpressao) as e:
            img.ler_bmp(self.arq("trunc.bmp"))
        self.assertIn("incompleto", str(e.exception))

    def test_logotipo_vem_centralizado_e_tem_cache(self):
        gravar_bmp(self.arq(), [[PRETO] * 16] * 2)
        a = img.logotipo_escpos(self.arq(), 48)
        self.assertTrue(a.startswith(b"\x1ba\x01") and a.endswith(b"\n\x1ba\x00"))
        self.assertIs(img.logotipo_escpos(self.arq(), 48), a)  # mesmo objeto: veio do cache
        with self.assertRaises(ErroImpressao):
            img.logotipo_escpos("", 48)


# ------------------------------------------------------- logotipo, vias e gaveta no cupom
class TesteCupomTermico(BaseCaixa):
    def setUp(self):
        super().setUp()
        self.imp = ImpressaoController(self.banco)
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.imp.pasta_saida = lambda: Path(self.dir)
        self.arq_saida = os.path.join(self.dir, "saida.prn")
        ConfigController(self.banco).salvar_maquina({
            "modo_impressao": "termica", "impressora_termica_conexao": "arquivo",
            "impressora_termica_endereco": self.arq_saida, "impressora_termica_gaveta": "S"})

    def vender_e_fechar(self, forma, valor):
        vid = self.vender((self.skol, 1))                      # R$ 8,00
        self.pagar(vid, forma, valor)
        self.caixa.fechar(vid)
        return vid

    def test_gaveta_abre_para_dinheiro_e_forma_na_gaveta_mas_nao_para_cartao_ou_pix(self):
        self.banco.inserir("tipos_pagamento", {"tipo": "Cheque", "ordem": 50})        # forma cadastrada pelo dono: fica na gaveta
        self.assertTrue(self.imp.opcoes_cupom(self.vender_e_fechar("Dinheiro", 800))["abrir_gaveta"])
        self.assertTrue(self.imp.opcoes_cupom(self.vender_e_fechar("Cheque", 800))["abrir_gaveta"])
        self.assertFalse(self.imp.opcoes_cupom(self.vender_e_fechar("Pix", 800))["abrir_gaveta"])
        self.assertFalse(self.imp.opcoes_cupom(self.vender_e_fechar("Cartão Débito", 800))["abrir_gaveta"])

    def test_numero_de_vias_vem_da_forma_de_pagamento(self):
        self.banco.executar("UPDATE tipos_pagamento SET vias = 2 WHERE tipo = 'Cartão Crédito'")
        self.assertEqual(self.imp.opcoes_cupom(self.vender_e_fechar("Cartão Crédito", 1300))["copias"], 2)   # com a taxa
        self.assertEqual(self.imp.opcoes_cupom(self.vender_e_fechar("Dinheiro", 800))["copias"], 1)
        self.banco.executar("UPDATE tipos_pagamento SET vias = 9 WHERE tipo = 'Pix'")
        self.assertEqual(self.imp.opcoes_cupom(self.vender_e_fechar("Pix", 800))["copias"], 3)   # teto de segurança

    def test_duas_vias_saem_duas_vezes_com_corte_entre_elas_e_gaveta_so_na_primeira(self):
        vid = self.vender_e_fechar("Dinheiro", 800)
        self.imp.enviar(self.imp.cupom(vid), "cupom", tipo="cupom", abrir_gaveta=True, copias=2)
        self.imp.fila.processar()
        dados = Path(self.arq_saida).read_bytes()
        self.assertEqual(dados.count(b"\x1b@"), 2)
        self.assertEqual(dados.count(b"\x1dV"), 2)
        self.assertEqual(dados.count(b"\x1bp"), 1)

    def test_logotipo_so_sai_quando_ligado_e_so_nos_documentos_do_cliente(self):
        bmp = os.path.join(self.dir, "logo.bmp")
        gravar_bmp(bmp, [[PRETO] * 16] * 2)
        self.banco.atualizar("loja", 1, {"logotipo": bmp})     # caminho BMP legado, anterior à importação controlada
        vid = self.vender_e_fechar("Dinheiro", 800)
        texto = self.imp.cupom(vid)
        self.imp.enviar(texto, "sem_logo", tipo="cupom")                       # flag desligada
        self.imp.fila.processar()
        self.assertNotIn(b"\x1dv0", Path(self.arq_saida).read_bytes())
        ConfigController(self.banco).salvar_maquina({"impressora_termica_logotipo": "S"})
        Path(self.arq_saida).unlink()
        self.imp.enviar(texto, "com_logo", tipo="cupom")
        self.imp.enviar("SANGRIA\nValor 10,00", "sangria", tipo="comprovante")   # documento interno: sem logo
        self.imp.fila.processar()
        dados = Path(self.arq_saida).read_bytes()
        self.assertEqual(dados.count(b"\x1dv0"), 1)

    def test_logotipo_quebrado_nao_impede_o_cupom_de_sair(self):
        Path(os.path.join(self.dir, "ruim.bmp")).write_bytes(b"lixo")
        self.banco.atualizar("loja", 1, {"logotipo": os.path.join(self.dir, "ruim.bmp")})  # arquivo corrompido após configurar
        ConfigController(self.banco).salvar_maquina({"impressora_termica_logotipo": "S"})
        vid = self.vender_e_fechar("Dinheiro", 800)
        self.imp.enviar(self.imp.cupom(vid), "cupom", tipo="cupom")
        self.assertEqual(self.imp.fila.processar()["enviados"], 1)
        self.assertNotIn(b"\x1dv0", Path(self.arq_saida).read_bytes())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM log_eventos WHERE evento = 'logotipo_invalido'"), 1)


# --------------------------------------------------------------------- migração v4 -> v5
class TesteMigracaoV5(unittest.TestCase):
    def test_banco_da_versao_4_ganha_a_fila_e_a_coluna_do_logotipo(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        caminho = os.path.join(d, "v4.db")
        b = BancoDados(caminho)
        b.executar("DROP TABLE fila_impressao")
        b.executar("ALTER TABLE maquinas DROP COLUMN impressora_termica_logotipo")
        b.executar("PRAGMA user_version = 4")
        b.fechar()
        b = BancoDados(caminho)
        self.addCleanup(b.fechar)
        self.assertGreaterEqual(b.valor("PRAGMA user_version"), 5)
        self.assertIn("impressora_termica_logotipo", [r[1] for r in b.todos("PRAGMA table_info(maquinas)")])
        FilaImpressao(b).enfileirar("caixa", "x", b"y")
        self.assertEqual(b.valor("SELECT COUNT(*) FROM fila_impressao"), 1)


if __name__ == "__main__":
    unittest.main()
