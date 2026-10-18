"""Impressão térmica (ESC/POS), transportes, gaveta pela impressora, roteamento do
ImpressaoController, reimpressão de cupom e migração de esquema v1 -> v2."""
from __future__ import annotations

import contextlib
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from src.controllers.config_controller import ConfigController
from src.controllers.impressao_controller import ImpressaoController
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.database.esquema import MAQUINAS_DDL, VERSAO_ESQUEMA
from src.hardware import impressora_termica as term
from src.hardware.dispositivos import DispositivoIndisponivel, Gaveta
from src.hardware.impressora_termica import ErroImpressao, ImpressoraTermica
from tests.test_caixa import BaseCaixa


@contextlib.contextmanager
def impressora_falsa():
    """Servidor TCP que aceita uma conexão e guarda os bytes recebidos. Devolve (endereco, caixa)."""
    recebido: dict = {}
    pronto = threading.Event()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    porta = srv.getsockname()[1]

    def aceitar():
        pronto.set()
        try:
            con, _ = srv.accept()
            dados = b""
            con.settimeout(2)
            try:
                while True:
                    pedaco = con.recv(4096)
                    if not pedaco:
                        break
                    dados += pedaco
            except OSError:
                pass
            recebido["dados"] = dados
            con.close()
        except OSError:
            pass
    th = threading.Thread(target=aceitar, daemon=True)
    th.start()
    pronto.wait()
    try:
        yield f"127.0.0.1:{porta}", recebido
    finally:
        th.join(timeout=3)
        srv.close()


class TesteEscPos(unittest.TestCase):
    def test_bytes_basicos(self):
        b = term.texto_para_escpos("LINHA 1\nLINHA 2", codepage="cp850", cortar=True)
        self.assertTrue(b.startswith(b"\x1b@"))              # inicializa
        self.assertIn(b"\x1bt\x02", b)                        # CP850 = tabela 2
        self.assertIn(b"\x1dV\x01", b)                        # corte parcial
        self.assertNotIn(b"\x1bp", b)                         # sem gaveta

    def test_codepage_por_nome(self):
        self.assertIn(b"\x1bt\x03", term.texto_para_escpos("x", codepage="cp860"))
        self.assertIn(b"\x1bt\x10", term.texto_para_escpos("x", codepage="cp1252"))
        self.assertNotIn(b"\x1bt", term.texto_para_escpos("x", codepage="utf-8"))  # utf-8: não seleciona tabela

    def test_acentos_na_pagina_de_codigo(self):
        b = term.texto_para_escpos("ação pão café", codepage="cp850")
        self.assertIn("ação pão café".encode("cp850"), b)
        self.assertNotIn("ção".encode("utf-8"), b)            # nunca UTF-8 cru

    def test_enfase_por_linha(self):
        b = term.texto_para_escpos("LOJA\nitem\nTOTAL: 10,00", negrito_linhas=1, grande_prefixos=("TOTAL",))
        self.assertIn(b"\x1bE\x01", b)                        # negrito (cabeçalho)
        self.assertIn(b"\x1d!\x01", b)                        # TOTAL em dobro de altura
        self.assertIn(b"\x1d!\x00", b)                        # volta ao normal depois

    def test_gaveta_e_pino(self):
        self.assertEqual(term.pulso_gaveta(0), b"\x1bp\x00\x19\xfa")
        self.assertEqual(term.pulso_gaveta(1), b"\x1bp\x01\x19\xfa")
        b = term.texto_para_escpos("x", abrir_gaveta=True, pino_gaveta=1)
        self.assertIn(b"\x1bp\x01\x19\xfa", b)

    def test_corte_total_vs_parcial(self):
        self.assertIn(b"\x1dV\x00", term.cortar_papel(parcial=False))
        self.assertIn(b"\x1dV\x01", term.cortar_papel(parcial=True))


class TesteTransportes(unittest.TestCase):
    def test_rede(self):
        with impressora_falsa() as (endereco, recebido):
            ImpressoraTermica(conexao="rede", endereco=endereco).imprimir("Cupom\nTOTAL: 5,00")
        self.assertTrue(recebido["dados"].startswith(b"\x1b@"))

    def test_rede_offline_da_erro_claro(self):
        with self.assertRaises(ErroImpressao) as e:
            # porta 1 fechada
            term.enviar_rede("127.0.0.1:1", b"x", timeout=1)
        self.assertIn("127.0.0.1", str(e.exception))

    def test_endereco_invalido(self):
        with self.assertRaises(ErroImpressao):
            term.enviar_rede("", b"x")
        with self.assertRaises(ErroImpressao):
            term.enviar_rede("host:abc", b"x")

    def test_arquivo(self):
        with tempfile.TemporaryDirectory() as d:
            arq = os.path.join(d, "saida.prn")
            ImpressoraTermica(conexao="arquivo", endereco=arq).imprimir("teste")
            self.assertTrue(Path(arq).read_bytes().startswith(b"\x1b@"))

    def test_serial_sem_biblioteca_da_mensagem_clara(self):
        # Módulo None em sys.modules faz o import falhar, tenha ou não o pyserial instalado.
        with mock.patch.dict(sys.modules, {"serial": None}):
            with self.assertRaises(ErroImpressao) as e:
                term.enviar_serial("COM9", b"x")
            self.assertIn("pyserial", str(e.exception))

    def test_endereco_serial_aceita_velocidade(self):
        self.assertEqual(term._parse_serial("COM3"), ("COM3", 9600))
        self.assertEqual(term._parse_serial(" COM3:115200 "), ("COM3", 115200))
        self.assertEqual(term._parse_serial("COM3:"), ("COM3", 9600))            # forma antiga do Windows
        self.assertEqual(term._parse_serial("\\\\.\\COM12"), ("\\\\.\\COM12", 9600))   # caminho de dispositivo
        for ruim in ("COM3:rapido", "COM3:0", "COM3:9600,n,8,1"):
            with self.assertRaises(ErroImpressao, msg=ruim):
                term._parse_serial(ruim)

    def test_serial_abre_a_porta_na_velocidade_do_endereco(self):
        aberto = {}

        class SerialFalsa:
            def __init__(self, porta, baudrate, timeout, write_timeout):
                aberto.update(porta=porta, baud=baudrate)

            def write(self, dados):
                aberto["dados"] = dados

            def flush(self):
                pass

            def close(self):
                aberto["fechada"] = True
        falso = type(sys)("serial")
        falso.Serial = SerialFalsa
        with mock.patch.dict(sys.modules, {"serial": falso}):
            term.enviar_serial("COM3:19200", b"abc")
            self.assertEqual(aberto, {"porta": "COM3", "baud": 19200, "dados": b"abc", "fechada": True})
            aberto.clear()
            ImpressoraTermica(conexao="serial", endereco="COM7").enviar_bytes(b"z")
            self.assertEqual((aberto["porta"], aberto["baud"]), ("COM7", 9600))
            with self.assertRaises(ErroImpressao):
                term.enviar_serial("", b"x")

    def test_nenhuma_conexao(self):
        with self.assertRaises(ErroImpressao):
            ImpressoraTermica(conexao="nenhuma").enviar_bytes(b"x")


class TesteImpressoraConfig(unittest.TestCase):
    def test_da_maquina(self):
        imp = ImpressoraTermica.da_maquina({
            "impressora_termica_conexao": "rede", "impressora_termica_endereco": "10.0.0.5:9100",
            "impressora_termica_codepage": "cp860", "colunas_fita": 32,
            "impressora_termica_cortar": 0, "impressora_termica_gaveta": 1, "impressora_termica_pino": 1})
        self.assertEqual((imp.conexao, imp.endereco, imp.codepage, imp.colunas), ("rede", "10.0.0.5:9100", "cp860", 32))
        self.assertEqual((imp.cortar, imp.tem_gaveta, imp.pino_gaveta), (False, True, 1))
        self.assertTrue(imp.configurada)

    def test_erro_de_impressao_e_erro_de_negocio(self):
        self.assertTrue(issubclass(ErroImpressao, ErroNegocio))


class TesteGaveta(unittest.TestCase):
    def test_abre_pela_impressora(self):
        with impressora_falsa() as (endereco, recebido):
            imp = ImpressoraTermica(conexao="rede", endereco=endereco, tem_gaveta=True, pino_gaveta=0)
            Gaveta(instalada=True, impressora=imp).abrir()
        self.assertEqual(recebido["dados"], term.INICIALIZAR + term.pulso_gaveta(0))

    def test_sem_impressora_pede_a_chave(self):
        imp = ImpressoraTermica(conexao="nenhuma", tem_gaveta=False)
        with self.assertRaises(DispositivoIndisponivel) as e:
            Gaveta(instalada=True, impressora=imp).abrir()
        self.assertIn("chave", str(e.exception).lower())

    def test_nada_configurado(self):
        with self.assertRaises(DispositivoIndisponivel):
            Gaveta(instalada=False, impressora=None).abrir()


class TesteRoteamento(BaseCaixa):
    """ImpressaoController escolhe a saída conforme o modo da máquina. Na térmica o documento vai para a
    fila (`fila.processar()` faz o papel da thread nos testes)."""

    def setUp(self):
        super().setUp()
        self.imp = ImpressaoController(self.banco)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # histórico vai para a pasta temporária (não suja o repositório)
        self.imp.pasta_saida = lambda: Path(self.tmp.name)
        self.cfg = ConfigController(self.banco)

    def _modo_termica(self, arquivo):
        self.cfg.salvar_maquina({"modo_impressao": "termica", "impressora_termica_conexao": "arquivo",
                                 "impressora_termica_endereco": arquivo, "impressora_termica_codepage": "cp850",
                                 "impressora_termica_gaveta": "S"})

    def _venda_fechada(self, forma="Dinheiro"):
        vid = self.vender((self.skol, 2))
        self.pagar(vid, forma, 2000)
        self.caixa.fechar(vid)
        return vid

    def test_documentos_do_mesmo_nome_no_mesmo_segundo_nao_se_sobrescrevem(self):
        for i in range(3):
            self.imp.enviar(f"documento {i}", "pedido_Lanches")
        textos = sorted(p.read_text(encoding="utf-8") for p in Path(self.tmp.name).glob("*pedido_Lanches*.txt"))
        self.assertEqual(textos, ["documento 0", "documento 1", "documento 2"])

    def test_pedido_remoto_em_pasta_nao_perde_pedidos_simultaneos(self):
        remota = Path(self.tmp.name) / "cozinha"
        self.cfg.salvar_maquina({"modo_impressao": "tela", "impressora_remota_conexao": "pasta",
                                 "impressora_remota_pasta": str(remota)})
        for i in range(3):
            self.imp.enviar_remoto(f"pedido {i}", "pedido_Lanches")
        textos = sorted(p.read_text(encoding="utf-8") for p in remota.glob("*.txt"))
        self.assertEqual(textos, ["pedido 0", "pedido 1", "pedido 2"])

    def test_modo_tela_nao_imprime(self):
        self.assertTrue(self.imp.deve_mostrar_na_tela())
        vid = self._venda_fechada()
        caminho = self.imp.enviar(self.imp.cupom(vid), "cupom", tipo="cupom")
        self.assertTrue(Path(caminho).exists())              # histórico gravado
        self.assertEqual(self.imp.modo(), "tela")
        self.assertEqual(self.imp.fila.contagem()["pendentes"], 0)   # nada foi para a fila

    def test_modo_termica_enfileira_e_a_fila_imprime(self):
        arq = os.path.join(self.tmp.name, "cupom.prn")
        self._modo_termica(arq)
        vid = self._venda_fechada()
        self.imp.enviar(self.imp.cupom(vid), "cupom", tipo="cupom", abrir_gaveta=True)
        self.assertEqual(self.imp.fila.contagem()["pendentes"], 1)
        self.assertFalse(os.path.exists(arq))                # ainda não imprimiu: quem imprime é a fila
        self.assertEqual(self.imp.fila.processar()["enviados"], 1)
        dados = Path(arq).read_bytes()
        self.assertTrue(dados.startswith(b"@"))
        self.assertIn(b"t", dados)                    # CP850
        self.assertIn(b"!", dados)                    # TOTAL em destaque
        self.assertIn(b"p", dados)                        # gaveta abriu (venda em dinheiro)
        self.assertIn("TOTAL".encode("cp850"), dados)
        self.assertEqual(self.imp.fila.contagem()["pendentes"], 0)

    def test_impressora_fora_do_ar_nao_trava_o_caixa_e_nada_se_perde(self):
        import time
        self._modo_termica("")
        self.banco.executar("UPDATE maquinas SET impressora_termica_conexao='rede', impressora_termica_endereco='127.0.0.1:1'")
        vid = self._venda_fechada()
        inicio = time.monotonic()
        self.imp.enviar(self.imp.cupom(vid), "cupom", tipo="cupom")
        self.assertLess(time.monotonic() - inicio, 2.0)      # voltou na hora, sem esperar a conexão
        r = self.imp.fila.processar()
        self.assertEqual((r["enviados"], r["falhas"]), (0, 1))
        item = self.imp.fila.listar()[0]
        self.assertEqual((item["status"], item["tentativas"]), ("pendente", 1))
        self.assertIn("127.0.0.1", item["ultimo_erro"])
        self.assertEqual(self.imp.fila.texto_indicador()[1], "aviso")

    def test_termica_sem_impressora_configurada_levanta_erro_na_hora(self):
        self.cfg.salvar_maquina({"modo_impressao": "termica", "impressora_termica_conexao": "nenhuma"})
        vid = self._venda_fechada()
        with self.assertRaises(ErroNegocio):
            self.imp.enviar(self.imp.cupom(vid), "cupom", tipo="cupom")
        self.assertEqual(self.imp.fila.contagem()["pendentes"], 0)

    def test_reimpressao_marca_segunda_via(self):
        arq = os.path.join(self.tmp.name, "r.prn")
        self._modo_termica(arq)
        vid = self._venda_fechada()
        texto = self.imp.reimprimir_cupom(vid)
        self.assertIn("SEGUNDA VIA", texto)
        self.imp.fila.processar()
        self.assertIn("SEGUNDA VIA".encode("cp850"), Path(arq).read_bytes())

    def test_pedido_remoto_por_rede_vai_pela_fila_e_nao_pela_impressora_do_caixa(self):
        with impressora_falsa() as (endereco, recebido):
            self.banco.executar("UPDATE maquinas SET impressora_remota_conexao='rede', impressora_remota_endereco=?", (endereco,))
            self.banco.executar("UPDATE subgrupos SET impressora_remota=1")
            vid = self.caixa.abrir_balcao()
            item = self.caixa.adicionar_item(vid, self.skol, 1)
            tickets = self.imp.pedido_remoto(vid, [item])
            self.assertTrue(tickets)
            for sub, texto in tickets.items():
                self.imp.enviar_remoto(texto, f"pedido_{sub}")
            self.assertEqual(self.imp.fila.listar()[0]["destino"], "remota")
            self.imp.fila.processar()
        self.assertTrue(recebido["dados"].startswith(b"@"))

    def test_pedido_remoto_por_impressora_do_windows_vai_pela_fila_ao_spooler(self):
        self.banco.executar("UPDATE maquinas SET impressora_remota_conexao='spooler', impressora_remota_endereco='COZINHA'")
        self.banco.executar("UPDATE subgrupos SET impressora_remota=1")
        vid = self.caixa.abrir_balcao()
        item = self.caixa.adicionar_item(vid, self.skol, 1)
        for sub, texto in self.imp.pedido_remoto(vid, [item]).items():
            self.imp.enviar_remoto(texto, f"pedido_{sub}")
        self.assertEqual(self.imp.fila.listar()[0]["destino"], "remota")
        with mock.patch.object(term, "enviar_spooler") as envia:
            self.imp.fila.processar()
        nome, dados = envia.call_args.args[:2]
        self.assertEqual(nome, "COZINHA")
        self.assertTrue(dados.startswith(b"\x1b@"))
        self.assertEqual(self.imp.fila.listar()[0]["status"], "enviado")

    def test_pedido_remoto_por_impressora_do_windows_sem_nome_pede_para_configurar(self):
        self.banco.executar("UPDATE maquinas SET impressora_remota_conexao='spooler', impressora_remota_endereco=''")
        with self.assertRaises(ErroImpressao):
            self.imp.enviar_remoto("PEDIDO", "pedido_bar")
        self.assertEqual(self.imp.fila.contagem()["pendentes"], 0)

    def test_gaveta_do_contexto_abre_pela_termica(self):
        from src.ui.contexto import Contexto
        with impressora_falsa() as (endereco, recebido):
            self.banco.executar(
                "UPDATE maquinas SET impressora_termica_conexao='rede', impressora_termica_endereco=?, impressora_termica_gaveta=1, gaveta=1",
                (endereco,))
            ctx = Contexto(self.banco)
            ctx.gaveta().abrir()
        self.assertIn(b"p", recebido["dados"])


class TesteMigracao(unittest.TestCase):
    def test_v1_migra_ate_a_versao_atual_preservando_dados_e_adicionando_termica(self):
        import shutil
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)              # roda por último (LIFO)
        caminho = os.path.join(d, "v1.db")
        c = sqlite3.connect(caminho)
        c.execute("CREATE TABLE config (chave TEXT PRIMARY KEY, valor TEXT)")
        c.execute("""CREATE TABLE maquinas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, terminal INTEGER NOT NULL UNIQUE DEFAULT 1,
            nome_computador TEXT, descricao TEXT,
            modo_impressao TEXT NOT NULL DEFAULT 'tela' CHECK (modo_impressao IN ('tela','arquivo','windows')),
            colunas_fita INTEGER NOT NULL DEFAULT 40, impressora_remota_pasta TEXT,
            balanca TEXT NOT NULL DEFAULT 'Nenhuma', balanca_porta TEXT,
            gaveta INTEGER NOT NULL DEFAULT 0, leitor_optico INTEGER NOT NULL DEFAULT 0)""")
        c.execute("INSERT INTO maquinas (terminal, nome_computador, colunas_fita) VALUES (1, 'CAIXA-01', 48)")
        c.execute("PRAGMA user_version = 1")
        c.commit()
        c.close()
        b = BancoDados(caminho)
        self.addCleanup(b.fechar)                            # roda antes do rmtree (LIFO)
        self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
        m = b.um("SELECT * FROM maquinas WHERE terminal = 1")
        self.assertEqual((m["nome_computador"], m["colunas_fita"]), ("CAIXA-01", 48))
        self.assertEqual(m["impressora_termica_codepage"], "cp850")       # coluna nova com default
        b.executar("UPDATE maquinas SET modo_impressao = 'termica'")       # CHECK antigo não impede mais
        self.assertEqual(b.valor("SELECT modo_impressao FROM maquinas"), "termica")

    def test_banco_novo_ja_nasce_na_versao_atual(self):
        b = BancoDados(":memory:")
        self.addCleanup(b.fechar)
        self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
        self.assertIn("impressora_termica_conexao", [r[1] for r in b.todos("PRAGMA table_info(maquinas)")])


class TesteConfigMaquina(BaseCaixa):
    def test_salvar_campos_termicos(self):
        cfg = ConfigController(self.banco)
        cfg.salvar_maquina({"modo_impressao": "termica", "impressora_termica_conexao": "rede",
                            "impressora_termica_endereco": "192.168.0.50:9100", "impressora_termica_cortar": "S",
                            "impressora_termica_gaveta": "S", "impressora_termica_pino": "1", "colunas_fita": "48"})
        m = cfg.maquina()
        self.assertEqual(m["modo_impressao"], "termica")
        self.assertEqual(m["impressora_termica_endereco"], "192.168.0.50:9100")
        self.assertEqual((m["impressora_termica_cortar"], m["impressora_termica_gaveta"], m["impressora_termica_pino"]), (1, 1, 1))

    def test_pino_invalido(self):
        from src.core.erros import ErroValidacao
        with self.assertRaises(ErroValidacao):
            ConfigController(self.banco).salvar_maquina({"impressora_termica_pino": "5"})


if __name__ == "__main__":
    unittest.main()
