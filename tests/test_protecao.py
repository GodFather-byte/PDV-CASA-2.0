"""Proteção do banco: backup automático, integridade, restauração, instância única, log de erros e o caixa passando de
um turno para o outro com comanda aberta."""
from __future__ import annotations

import logging
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from src.controllers.caixa_controller import CaixaController
from src.controllers.turno_controller import TurnoController
from src.controllers.utilitario_controller import UtilitarioController
from src.core import registro
from src.core.erros import ErroNegocio
from src.core.instancia import InstanciaUnica
from src.database import protecao
from src.database.conexao import BancoDados
from tests.base import BaseTeste


class BaseArquivo(BaseTeste):
    """Banco em arquivo (o backup e a integridade precisam de um arquivo de verdade)."""

    def setUp(self):
        super().setUp()
        self.pasta = Path(tempfile.mkdtemp(prefix="pdv_protecao_"))
        self.addCleanup(shutil.rmtree, self.pasta, True)
        self.caminho = str(self.pasta / "loja.db")
        self.banco = BancoDados(self.caminho)
        self.addCleanup(self.banco.fechar)
        self.banco.cfg_set("pasta_backup", str(self.pasta / "Backup"))
        self.util = UtilitarioController(self.banco)


class TesteIntegridade(BaseArquivo):
    def test_banco_novo_e_banco_saudavel_passam(self):
        self.assertIsNone(protecao.verificar_arquivo(self.pasta / "nao_existe.db"))
        self.assertIsNone(protecao.verificar_arquivo(self.caminho))

    def test_arquivo_que_nao_e_banco_e_apontado(self):
        ruim = self.pasta / "ruim.db"
        ruim.write_bytes(b"isto nao e um banco sqlite" * 100)
        self.assertIsNotNone(protecao.verificar_arquivo(ruim))

    def test_banco_truncado_e_apontado(self):
        self.banco.fechar()
        dados = Path(self.caminho).read_bytes()
        corrompido = self.pasta / "corrompido.db"
        corrompido.write_bytes(dados[:len(dados) // 2] + b"\x00" * 4096)
        self.assertIsNotNone(protecao.verificar_arquivo(corrompido))


class TesteBackup(BaseArquivo):
    def test_backup_e_valido_e_registra_a_pasta(self):
        caminho = self.util.backup()
        self.assertTrue(protecao.backup_valido(caminho))
        self.assertIn(str((self.pasta / "Backup").resolve()), protecao.pastas_conhecidas(self.caminho))

    def test_copia_extra_e_gravada_e_falha_dela_nao_cancela_o_backup(self):
        extra = self.pasta / "pendrive"
        self.banco.cfg_set("pasta_backup_extra", str(extra))
        nome = Path(self.util.backup()).name
        self.assertTrue((extra / nome).exists())
        self.assertEqual(self.banco.cfg("backup_extra_erro"), "")
        arquivo = self.pasta / "arquivo.txt"
        arquivo.write_text("x")
        self.banco.cfg_set("pasta_backup_extra", str(arquivo / "dentro"))      # impossível criar a pasta
        self.avancar(minutes=1)
        self.assertTrue(protecao.backup_valido(self.util.backup()))
        self.assertIn("pasta extra", self.banco.cfg("backup_extra_erro"))
        self.assertEqual(self.util.situacao_backup()[0], "aviso")

    def test_poda_deixa_so_os_mais_novos(self):
        for _ in range(5):
            self.avancar(minutes=1)
            self.util.backup(manter=3)
        self.assertEqual(len(self.util.listar_backups()), 3)

    def test_automatico_nunca_levanta_erro_e_avisa(self):
        with mock.patch.object(self.util, "backup", side_effect=OSError("disco cheio")):
            self.assertIsNone(self.util.backup_automatico("teste"))
        self.assertIn("disco cheio", self.banco.cfg("backup_erro"))
        self.assertEqual(self.util.situacao_backup()[0], "sem")        # ainda nunca houve um backup
        self.util.backup()
        self.banco.cfg_set("backup_erro", "x")
        self.assertEqual(self.util.situacao_backup()[0], "aviso")

    def test_automatico_respeita_o_intervalo_minimo(self):
        self.assertIsNotNone(self.util.backup_automatico("a"))
        self.avancar(minutes=10)
        self.assertIsNone(self.util.backup_automatico("b", minimo_min=60))
        self.avancar(minutes=60)
        self.assertIsNotNone(self.util.backup_automatico("c", minimo_min=60))

    def test_alerta_de_backup_atrasado(self):
        self.assertEqual(self.util.situacao_backup()[0], "sem")
        self.util.backup()
        self.assertEqual(self.util.situacao_backup()[0], "ok")
        self.avancar(hours=25)
        nivel, texto = self.util.situacao_backup()
        self.assertEqual(nivel, "aviso")
        self.assertIn("ATENÇÃO", texto)

    def test_backup_danificado_e_descartado(self):
        with mock.patch.object(protecao, "verificar_arquivo", return_value="malformed"):
            with self.assertRaises(ErroNegocio):
                self.util.backup()
        self.assertEqual(self.util.listar_backups(), [])


class TesteRestauracao(BaseArquivo):
    def _pedido_com_original(self):
        backup = self.util.backup()
        self.banco.cfg_set("nome_teste", "ORIGINAL")
        self.banco.fechar()
        protecao.pedir_restauracao(self.caminho, backup)
        return Path(self.caminho).read_bytes(), Path(self.caminho + "." + protecao.PENDENTE)

    def test_falha_na_copia_preserva_original_e_pedido_e_cancela_abertura(self):
        original, pedido = self._pedido_com_original()
        with mock.patch.object(protecao.shutil, "copyfile", side_effect=OSError("disco cheio")):
            self.assertEqual(protecao.preparar_banco(self.caminho, mock.Mock()), "cancelado")
        self.assertEqual(Path(self.caminho).read_bytes(), original)
        self.assertTrue(pedido.exists())
        self.assertFalse(list(self.pasta.glob("*.restaurando-*")))

    def test_falha_na_validacao_da_copia_preserva_original_e_pedido(self):
        original, pedido = self._pedido_com_original()
        validar = protecao.backup_valido
        with mock.patch.object(protecao, "backup_valido",
                               side_effect=lambda p: False if ".restaurando-" in str(p) else validar(p)):
            self.assertEqual(protecao.preparar_banco(self.caminho, mock.Mock()), "cancelado")
        self.assertEqual(Path(self.caminho).read_bytes(), original)
        self.assertTrue(pedido.exists())

    def test_falha_na_substituicao_reverte_laterais_e_preserva_pedido(self):
        original, pedido = self._pedido_com_original()
        laterais = {}
        for sufixo in ("-wal", "-shm"):
            lateral = Path(self.caminho + sufixo)
            lateral.write_bytes(sufixo.encode())
            laterais[lateral] = lateral.read_bytes()
        substituir = protecao.os.replace

        def falhar(origem, destino):
            if ".restaurando-" in str(origem):
                raise OSError("arquivo bloqueado")
            return substituir(origem, destino)

        with mock.patch.object(protecao.os, "replace", side_effect=falhar):
            self.assertEqual(protecao.preparar_banco(self.caminho, mock.Mock()), "cancelado")
        self.assertEqual(Path(self.caminho).read_bytes(), original)
        for lateral, conteudo in laterais.items():
            self.assertEqual(lateral.read_bytes(), conteudo)
        self.assertTrue(pedido.exists())

    def test_falha_ao_mover_segundo_lateral_reverte_primeiro(self):
        original, pedido = self._pedido_com_original()
        for sufixo in ("-wal", "-shm"):
            Path(self.caminho + sufixo).write_bytes(sufixo.encode())
        substituir = protecao.os.replace

        def falhar(origem, destino):
            if str(origem) == self.caminho + "-shm":
                raise OSError("lateral bloqueado")
            return substituir(origem, destino)

        with mock.patch.object(protecao.os, "replace", side_effect=falhar):
            self.assertEqual(protecao.preparar_banco(self.caminho, mock.Mock()), "cancelado")
        self.assertEqual(Path(self.caminho).read_bytes(), original)
        self.assertEqual(Path(self.caminho + "-wal").read_bytes(), b"-wal")
        self.assertEqual(Path(self.caminho + "-shm").read_bytes(), b"-shm")
        self.assertTrue(pedido.exists())

    def test_pedido_invalido_sem_banco_nao_permite_criar_banco_vazio(self):
        self.banco.fechar()
        Path(self.caminho).unlink()
        pedido = Path(self.caminho + "." + protecao.PENDENTE)
        pedido.write_text(str(self.pasta / "backup-ausente.db"), encoding="utf-8")
        self.assertEqual(protecao.preparar_banco(self.caminho, mock.Mock()), "cancelado")
        self.assertFalse(Path(self.caminho).exists())
        self.assertTrue(pedido.exists())

    def test_banco_vazio_sem_backup_nao_pode_ser_aberto(self):
        self.banco.fechar()
        Path(self.caminho).write_bytes(b"")
        with mock.patch.object(protecao, "_pastas_de_backup", return_value=[]):
            self.assertEqual(protecao.preparar_banco(self.caminho, lambda *a: True), "cancelado")

    def test_falha_antes_da_substituicao_sem_original_nao_cria_banco(self):
        backup = self.util.backup()
        self.banco.fechar()
        Path(self.caminho).unlink()
        protecao.pedir_restauracao(self.caminho, backup)
        pedido = Path(self.caminho + "." + protecao.PENDENTE)
        with mock.patch.object(protecao.os, "replace", side_effect=OSError("sem permissão")):
            self.assertEqual(protecao.preparar_banco(self.caminho, mock.Mock()), "cancelado")
        self.assertFalse(Path(self.caminho).exists())
        self.assertTrue(pedido.exists())

    def test_restauracao_inclui_transacoes_no_wal_do_backup(self):
        origem = BancoDados(str(self.pasta / "backup-aberto.db"))
        self.addCleanup(origem.fechar)
        origem.cfg_set("nome_teste", "NO WAL")
        self.assertTrue(Path(origem.caminho + "-wal").exists())
        self.banco.fechar()
        protecao.restaurar(self.caminho, origem.caminho)
        restaurado = BancoDados(self.caminho)
        self.addCleanup(restaurado.fechar)
        self.assertEqual(restaurado.cfg("nome_teste"), "NO WAL")

    def test_restauracoes_seguidas_guardam_originais_distintos(self):
        backup = self.util.backup()
        self.banco.fechar()
        primeiro = protecao.restaurar(self.caminho, backup)
        segundo = protecao.restaurar(self.caminho, backup)
        self.assertNotEqual(primeiro, segundo)
        self.assertTrue(primeiro.exists())
        self.assertTrue(segundo.exists())

    def test_restaurar_troca_o_banco_e_guarda_o_antigo(self):
        self.util.backup()
        self.banco.cfg_set("nome_teste", "DEPOIS")
        backup = self.util.listar_backups()[0]
        self.banco.fechar()
        guardado = protecao.restaurar(self.caminho, backup)
        self.assertTrue(guardado.exists())
        novo = BancoDados(self.caminho)
        self.addCleanup(novo.fechar)
        self.assertEqual(novo.cfg("nome_teste"), "")
        antigo = BancoDados(str(guardado), semear=False)
        self.addCleanup(antigo.fechar)
        self.assertEqual(antigo.cfg("nome_teste"), "DEPOIS")

    def test_recusa_backup_invalido(self):
        lixo = self.pasta / "loja_offline-lixo.db"
        lixo.write_bytes(b"nada" * 500)
        with self.assertRaises(ValueError):
            protecao.restaurar(self.caminho, lixo)

    def test_restauracao_marcada_roda_no_proximo_inicio(self):
        self.banco.cfg_set("nome_teste", "ANTES")
        self.util.backup()
        self.avancar(minutes=5)
        self.banco.cfg_set("nome_teste", "DEPOIS")
        self.util.pedir_restauracao(str(self.util.listar_backups()[-1]))
        self.banco.fechar()
        self.assertEqual(protecao.preparar_banco(self.caminho, lambda t, m: self.fail("não devia perguntar")), "restaurado")
        novo = BancoDados(self.caminho)
        self.addCleanup(novo.fechar)
        self.assertEqual(novo.cfg("nome_teste"), "ANTES")
        self.assertFalse(Path(self.caminho + "." + protecao.PENDENTE).exists())

    def test_banco_corrompido_volta_do_ultimo_backup_valido(self):
        self.banco.cfg_set("nome_teste", "BOM")
        self.util.backup()
        self.banco.fechar()
        Path(self.caminho).write_bytes(b"corrompido" * 1000)
        for sufixo in ("-wal", "-shm"):
            Path(self.caminho + sufixo).unlink(missing_ok=True)
        perguntas = []
        with mock.patch.object(protecao, "_raiz", return_value=self.pasta):
            r = protecao.preparar_banco(self.caminho, lambda t, m: perguntas.append(t) or True)
        self.assertEqual((r, perguntas), ("restaurado", ["Banco danificado"]))
        novo = BancoDados(self.caminho)
        self.addCleanup(novo.fechar)
        self.assertEqual(novo.cfg("nome_teste"), "BOM")
        self.assertTrue(list(self.pasta.glob("loja.db.antes-*")))

    def test_corrompido_sem_backup_pergunta_e_respeita_a_resposta(self):
        self.banco.fechar()
        Path(self.caminho).write_bytes(b"corrompido" * 1000)
        with mock.patch.object(protecao, "_raiz", return_value=self.pasta / "vazio"):
            self.assertEqual(protecao.preparar_banco(self.caminho, lambda t, m: False), "cancelado")
            self.assertEqual(protecao.preparar_banco(self.caminho, lambda t, m: True), "ok")

    def test_operador_pode_recusar_a_restauracao(self):
        self.util.backup()
        self.banco.fechar()
        Path(self.caminho).write_bytes(b"corrompido" * 1000)
        with mock.patch.object(protecao, "_raiz", return_value=self.pasta):
            self.assertEqual(protecao.preparar_banco(self.caminho, lambda t, m: False), "cancelado")
        self.assertEqual(Path(self.caminho).read_bytes()[:10], b"corrompido")      # nada foi mexido


class TesteInstanciaUnica(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="pdv_instancia_"))
        self.addCleanup(shutil.rmtree, self.pasta, True)

    def test_segunda_instancia_e_recusada_ate_a_primeira_sair(self):
        a, b = InstanciaUnica(self.pasta / "loja.db"), InstanciaUnica(self.pasta / "loja.db")
        self.addCleanup(a.liberar)
        self.addCleanup(b.liberar)
        self.assertTrue(a.adquirir())
        self.assertFalse(b.adquirir())
        a.liberar()
        self.assertTrue(b.adquirir())

    def test_bancos_diferentes_nao_se_bloqueiam(self):
        a, b = InstanciaUnica(self.pasta / "a.db"), InstanciaUnica(self.pasta / "b.db")
        self.addCleanup(a.liberar)
        self.addCleanup(b.liberar)
        self.assertTrue(a.adquirir() and b.adquirir())


class TesteRegistroDeErros(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="pdv_log_"))
        self.addCleanup(shutil.rmtree, self.pasta, True)

    def test_log_guarda_o_traceback_e_o_pacote_leva_so_logs(self):
        antigo = (sys.excepthook, threading.excepthook, registro._configurado, list(registro.log.handlers), registro.log.level)

        def restaurar():
            for h in list(registro.log.handlers):
                if h not in antigo[3]:
                    h.close()
                    registro.log.removeHandler(h)
            sys.excepthook, threading.excepthook, registro._configurado = antigo[:3]
            registro.log.setLevel(antigo[4])
        self.addCleanup(restaurar)
        registro._configurado = False
        arquivo = registro.configurar_logs(self.pasta / "logs")
        try:
            raise ValueError("falha de teste")
        except ValueError:
            registro.registrar_excecao(*sys.exc_info(), origem="teste")
        for h in registro.log.handlers:
            h.flush()
        texto = arquivo.read_text(encoding="utf-8")
        self.assertIn("falha de teste", texto)
        self.assertIn("Traceback", texto)
        (self.pasta / "loja.db").write_bytes(b"vendas secretas")
        pacote = registro.pacote_suporte(self.pasta / "Suporte", self.pasta / "logs")
        with zipfile.ZipFile(pacote) as z:
            nomes = z.namelist()
        self.assertIn("resumo.txt", nomes)
        self.assertIn("logs/pdv.log", nomes)
        self.assertFalse([n for n in nomes if n.endswith(".db")])


class TesteComandaAbertaNaTrocaDeTurno(BaseTeste):
    """A comanda do turno 1 que só é paga no turno 2: o dinheiro entra no caixa do turno 2 e o turno 1 não dá falta."""

    def test_pagar_no_turno_seguinte_nao_gera_falta_no_primeiro(self):
        adm = self.operador_adm()
        turnos = TurnoController(self.banco)
        caixa = CaixaController(self.banco, adm)
        skol = self.novo_produto("SKOL", 1000)
        t1 = turnos.abrir(adm, 1, 10000)
        venda, _ = caixa.abrir_mesa(7, comanda=True)
        caixa.adicionar_item(venda, skol, 3)                              # R$ 30 de consumo, ainda não paga
        fechamento1 = turnos.fechar(t1, adm, 10000)                       # gaveta só com o fundo
        self.assertEqual((fechamento1["esperado"], fechamento1["resultado"]), (10000, 0))
        self.assertEqual([p["nome"] for p in fechamento1["posicoes_abertas"]], ["Comanda 7"])      # segue aberta
        self.avancar(hours=1)
        t2 = turnos.abrir(adm, 2, 10000)
        total = caixa.obter(venda)["total_cent"]
        caixa.adicionar_pagamento(venda, self.tipo("Dinheiro"), total)
        caixa.fechar(venda)
        fechamento2 = turnos.fechar(t2, adm, 10000 + total)
        self.assertEqual(fechamento2["esperado"], 10000 + total)           # o dinheiro é do turno 2
        self.assertEqual(fechamento2["resultado"], 0)
        antigo = turnos.obter(t1)
        self.assertEqual((antigo["esperado_cent"], antigo["resultado_cent"]), (10000, 0))     # o turno 1 não mudou


if __name__ == "__main__":
    unittest.main()
